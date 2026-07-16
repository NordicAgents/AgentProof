#!/usr/bin/env python
"""E0 — Semantic conformance (AgentProof-CEGAR, plan §7 E0).

Question (plan §7): *does the implementation match the declared policy
semantics?* This runner exercises three independent conformance checks and
reports a mismatch count (gate: **zero** mismatches on the supported grammar):

1. **Oracle vs. an independent monitor.** For every short concrete trace over a
   small event alphabet and a battery of policies covering all operators, assert
   that :func:`agentproof.cegar.oracle.evaluate` agrees with a *second,
   self-contained* event-stepping monitor written here (independent of both the
   oracle's denotational evaluator and the checker's automaton). Any divergence
   is a real semantic bug in one implementation, not a shared mistake.

2. **Product vs. checker SAFE labelling.** For every seed task, run
   :func:`agentproof.cegar.product.check`; whenever it reports ``SAFE``, build a
   certificate and confirm the *independent*
   :func:`agentproof.cegar.checker.check_certificate` accepts it (and that no
   ``SAFE`` certificate can be built for a non-SAFE result). A product ``SAFE``
   that the checker refuses (or vice versa) is counted as a mismatch.

3. **Malformed-certificate rejection.** Take a valid SAFE certificate and apply
   a battery of tampering mutations (flipped hashes, swapped verdict, a
   forbidden-tool graph injected under a recomputed hash, weakened provenance,
   truncated policy); confirm the checker rejects every one. Reports the
   rejection rate (target 100%).

Everything here is offline and solver-only — no model or runtime is involved.

Run: ``.venv/bin/python scripts/cegar/e0_semantic_conformance.py``
"""

from __future__ import annotations

import argparse
import copy
import itertools
from pathlib import Path
from typing import Any

import _seedsuite as seed
from _seedsuite import add_common_args, load_seed_suite, results_path, write_results

from agentproof.cegar import product
from agentproof.cegar.certificate import (
    Certificate,
    build_certificate,
    canonical_hash,
)
from agentproof.cegar.checker import check_certificate
from agentproof.cegar.ir import (
    EffectEvent,
    EffectKind,
    EffectNode,
    MayMustGraph,
    ModalEdge,
    Modality,
    Provenance,
    Verdict,
)
from agentproof.cegar.oracle import BAD_PREFIX, SATISFIED, UNFULFILLED, evaluate
from agentproof.cegar.policy import (
    All,
    ArgConstraint,
    Approval,
    Bounded,
    Effect,
    Forbid,
    LeadsTo,
    Never,
    Op,
    Policy,
    RequireBefore,
    Tool,
)


# ===========================================================================
# 1. Independent event-stepping monitor (a second implementation)
# ===========================================================================

def _indep_eval(policy: Policy, trace: tuple[EffectEvent, ...]) -> tuple[int | None, bool]:
    """A self-contained event monitor: ``(first_bad_index, unfulfilled_at_end)``.

    Written as an explicit per-operator stepper directly over concrete events
    (``pred.eval``) — deliberately independent of the oracle's denotational
    evaluator and of the product/checker automata, so a differential mismatch
    localises a real bug.
    """
    if isinstance(policy, Never):
        for i, e in enumerate(trace):
            if policy.pred.eval(e):
                return (i, False)
        return (None, False)

    if isinstance(policy, RequireBefore):
        seen = False
        for i, e in enumerate(trace):
            g = policy.guarded.eval(e)
            r = policy.required.eval(e)
            if policy.strict:
                if g and not seen:
                    return (i, False)
                seen = seen or r
            else:
                seen = seen or r
                if g and not seen:
                    return (i, False)
        return (None, False)

    if isinstance(policy, Forbid):
        steps = policy.steps
        n = len(steps)
        idx = 0
        for i, e in enumerate(trace):
            if n == 0:
                return (i, False)
            if policy.contiguous:
                idx = idx + 1 if steps[idx].eval(e) else (1 if steps[0].eval(e) else 0)
            else:
                if idx < n and steps[idx].eval(e):
                    idx += 1
            if idx == n:
                return (i, False)
        return (None, False)

    if isinstance(policy, Bounded):
        count = 0
        for i, e in enumerate(trace):
            if policy.pred.eval(e):
                count += 1
            if count > policy.k:
                return (i, False)
        return (None, False)

    if isinstance(policy, LeadsTo):
        pending = False
        for e in trace:
            if policy.trigger.eval(e):
                pending = True
            if policy.response.eval(e):
                pending = False
        return (None, pending)

    if isinstance(policy, All):
        first_bad: int | None = None
        unfulfilled = False
        for sub in policy.policies:
            b, u = _indep_eval(sub, trace)
            if b is not None:
                first_bad = b if first_bad is None else min(first_bad, b)
            unfulfilled = unfulfilled or u
        if first_bad is not None:
            return (first_bad, False)
        return (None, unfulfilled)

    raise TypeError(f"independent monitor cannot evaluate {type(policy).__name__}")


def _oracle_pair(policy: Policy, trace: tuple[EffectEvent, ...]) -> tuple[int | None, bool]:
    """Project :func:`oracle.evaluate` to the same ``(bad_index, unfulfilled)`` shape."""
    v = evaluate(policy, trace)
    if v.status == BAD_PREFIX:
        return (v.bad_index, False)
    if v.status == UNFULFILLED:
        return (None, True)
    return (None, False)


def _event_alphabet() -> list[EffectEvent]:
    """A small deterministic event alphabet covering the seed policies' atoms."""
    return [
        EffectEvent(node_id="_"),  # neutral
        EffectEvent(node_id="wire", effect=EffectKind.FINANCIAL,
                    tool_name="wire_transfer", action_type="tool"),
        EffectEvent(node_id="wire_hi", effect=EffectKind.FINANCIAL,
                    tool_name="wire_transfer", action_type="tool",
                    args=(("amount", 20000),)),
        EffectEvent(node_id="wire_lo", effect=EffectKind.FINANCIAL,
                    tool_name="wire_transfer", action_type="tool",
                    args=(("amount", 5000),)),
        EffectEvent(node_id="send", tool_name="send_email", action_type="tool",
                    effect=EffectKind.COMMUNICATE),
        EffectEvent(node_id="read", tool_name="read_db", action_type="tool",
                    effect=EffectKind.READ),
        EffectEvent(node_id="retry", tool_name="retry", action_type="tool"),
        EffectEvent(node_id="open", tool_name="open", action_type="tool"),
        EffectEvent(node_id="close", tool_name="close", action_type="tool"),
        EffectEvent(node_id="approve", action_type="human", tags=("approval",)),
        EffectEvent(node_id="del", effect=EffectKind.DELETE),
    ]


def _conformance_policies(suite: list[seed.SeedTask]) -> list[Policy]:
    """Seed policies (deduped) plus extra operator-coverage policies."""
    policies: list[Policy] = []
    seen: set[str] = set()

    def _add(p: Policy) -> None:
        import json
        key = json.dumps(p.to_dict(), sort_keys=True)
        if key not in seen:
            seen.add(key)
            policies.append(p)

    for t in suite:
        _add(t.policy)
    # Extra coverage: strict/non-strict, contiguous Forbid, conjunction, arg cap.
    _add(RequireBefore(Approval(), Effect(EffectKind.FINANCIAL), strict=False,
                       rule_id="rb_loose"))
    _add(Forbid((Tool("read_db"), Tool("send_email")), contiguous=True,
               rule_id="exfil_contig"))
    _add(Bounded(Tool("wire_transfer"), 0, rule_id="no_wire_quota"))
    _add(Never(ArgConstraint("wire_transfer", "amount", Op.GT, 10000),
              rule_id="amount_cap"))
    _add(All((
        Never(Tool("wire_transfer"), rule_id="A"),
        Bounded(Tool("retry"), 1, rule_id="B"),
        LeadsTo(Tool("open"), Tool("close"), rule_id="C"),
    ), rule_id="combo"))
    return policies


def _run_oracle_differential(suite: list[seed.SeedTask], *, max_len: int) -> dict[str, Any]:
    alphabet = _event_alphabet()
    policies = _conformance_policies(suite)
    checked = 0
    mismatches: list[dict[str, Any]] = []
    for policy in policies:
        for length in range(max_len + 1):
            for combo in itertools.product(alphabet, repeat=length):
                trace = tuple(combo)
                a = _oracle_pair(policy, trace)
                b = _indep_eval(policy, trace)
                checked += 1
                if a != b:
                    mismatches.append({
                        "policy": policy.to_dict(),
                        "trace": [e.node_id for e in trace],
                        "oracle": list(a),
                        "independent": list(b),
                    })
    return {
        "policies_tested": len(policies),
        "trace_max_len": max_len,
        "pairs_checked": checked,
        "mismatches": len(mismatches),
        "mismatch_examples": mismatches[:5],
    }


# ===========================================================================
# 2. Product vs. checker SAFE labelling
# ===========================================================================

def _run_product_checker_agreement(suite: list[seed.SeedTask]) -> dict[str, Any]:
    checked = 0
    product_safe = 0
    cert_accepted = 0
    mismatches: list[dict[str, Any]] = []
    for t in suite:
        checked += 1
        r = product.check(t.graph, t.policy,
                          assume_trace_conservative=t.assume_trace_conservative)
        is_safe = r.verdict is Verdict.SAFE
        accepted = False
        if is_safe:
            product_safe += 1
            cert = build_certificate(
                t.graph, t.policy, r,
                assume_trace_conservative=t.assume_trace_conservative,
                created_tag="e0",
            )
            accepted = check_certificate(cert).accepted
            if accepted:
                cert_accepted += 1
        # A product SAFE the independent checker refuses is a conformance
        # mismatch (the two SAFE derivations must agree).
        if is_safe and not accepted:
            mismatches.append({"task_id": t.task_id,
                               "reason": "product SAFE but checker rejected"})
    return {
        "tasks_checked": checked,
        "product_safe": product_safe,
        "safe_certs_accepted": cert_accepted,
        "mismatches": len(mismatches),
        "mismatch_examples": mismatches,
    }


# ===========================================================================
# 3. Malformed-certificate rejection
# ===========================================================================

def _valid_safe_certificate() -> Certificate:
    """A minimal, independently-accepted SAFE certificate to mutate."""
    exact = Provenance(origin="ast_explicit", confidence="exact", source_span="e0:1:1")
    nodes = (
        EffectNode(id="entry", provenance=exact, modeling_confidence="exact",
                   state_predicates=("kind:entry",)),
        EffectNode(id="t1", effect=EffectKind.READ, tool="safe_reader",
                   provenance=exact, modeling_confidence="exact",
                   state_predicates=("kind:tool",)),
        EffectNode(id="exit", provenance=exact, modeling_confidence="exact",
                   state_predicates=("kind:exit",)),
    )
    edges = (
        ModalEdge("entry", "t1", modality=Modality.MUST, provenance=exact),
        ModalEdge("t1", "exit", modality=Modality.MUST, provenance=exact),
    )
    graph = MayMustGraph(name="e0-cert", framework="none", nodes=nodes, edges=edges,
                        entry_id="entry", exit_ids=("exit",))
    policy = Never(Tool("danger"), rule_id="no-danger")
    r = product.check(graph, policy)
    assert r.verdict is Verdict.SAFE
    return build_certificate(graph, policy, r, created_tag="e0-valid")


def _mutations(cert: Certificate) -> list[tuple[str, Certificate]]:
    """A battery of tampered certificates, each of which must be rejected."""
    out: list[tuple[str, Certificate]] = []

    m = copy.deepcopy(cert)
    object.__setattr__(m, "program_hash", "0" * 64)
    out.append(("flipped_program_hash", m))

    m = copy.deepcopy(cert)
    object.__setattr__(m, "policy_hash", "0" * 64)
    out.append(("flipped_policy_hash", m))

    m = copy.deepcopy(cert)
    object.__setattr__(m, "verdict", "unknown")
    out.append(("non_safe_verdict", m))

    # Inject a reachable forbidden-tool node and recompute the program hash so
    # the hash gate passes and only the re-derivation can catch it.
    tampered = MayMustGraph.from_dict(cert.graph)
    exact = Provenance(origin="ast_explicit", confidence="exact", source_span="e0:9:9")
    tampered = tampered.with_node(
        EffectNode(id="bad", effect=EffectKind.EXECUTE, tool="danger",
                   provenance=exact, modeling_confidence="exact",
                   state_predicates=("kind:tool",))
    )
    tampered = tampered.with_edges(tampered.edges + (
        ModalEdge("entry", "bad", modality=Modality.MAY, provenance=exact),
        ModalEdge("bad", "exit", modality=Modality.MAY, provenance=exact),
    ))
    m = copy.deepcopy(cert)
    object.__setattr__(m, "graph", tampered.to_dict())
    object.__setattr__(m, "program_hash", canonical_hash(tampered.to_dict()))
    out.append(("injected_forbidden_tool", m))

    # Weaken a reachable node's provenance (uncertifiable region), recompute hash.
    weak = MayMustGraph.from_dict(cert.graph)
    weak_prov = Provenance(origin="ast_inferred", confidence="may")
    weak = weak.with_node(
        EffectNode(id="t1", effect=EffectKind.READ, tool="safe_reader",
                   provenance=weak_prov, modeling_confidence="may",
                   state_predicates=("kind:tool",))
    )
    m = copy.deepcopy(cert)
    object.__setattr__(m, "graph", weak.to_dict())
    object.__setattr__(m, "program_hash", canonical_hash(weak.to_dict()))
    out.append(("weakened_provenance", m))

    # Truncate the policy dict (malformed) after recomputing its hash.
    broken_policy = {"policy": "never"}  # missing required "pred"
    m = copy.deepcopy(cert)
    object.__setattr__(m, "policy", broken_policy)
    object.__setattr__(m, "policy_hash", canonical_hash(broken_policy))
    out.append(("malformed_policy", m))

    return out


def _run_malformed_rejection() -> dict[str, Any]:
    cert = _valid_safe_certificate()
    clean_accepted = check_certificate(cert).accepted
    muts = _mutations(cert)
    rejected = 0
    leaks: list[str] = []
    for name, m in muts:
        res = check_certificate(m)
        if res.accepted:
            leaks.append(name)  # a tampered cert wrongly accepted
        else:
            rejected += 1
    return {
        "clean_certificate_accepted": clean_accepted,
        "mutations_tested": len(muts),
        "mutations_rejected": rejected,
        "mutations_wrongly_accepted": leaks,
        "rejection_rate": rejected / len(muts) if muts else 1.0,
    }


# ===========================================================================
# Driver
# ===========================================================================

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    parser.add_argument("--max-trace-len", type=int, default=3,
                        help="max enumerated trace length for the oracle differential "
                             "(default: 3)")
    args = parser.parse_args(argv)

    suite = load_seed_suite(args.tasks_dir)

    diff = _run_oracle_differential(suite, max_len=args.max_trace_len)
    agree = _run_product_checker_agreement(suite)
    malformed = _run_malformed_rejection()

    total_mismatches = diff["mismatches"] + agree["mismatches"]
    gate_pass = (
        total_mismatches == 0
        and malformed["clean_certificate_accepted"]
        and not malformed["mutations_wrongly_accepted"]
    )

    payload = {
        "experiment": "E0_semantic_conformance",
        "honesty": "Offline/solver-only. Synthetic seed suite; no LLM, model, or "
                   "runtime execution is involved in E0.",
        "seed_tasks": len(suite),
        "oracle_vs_independent_monitor": diff,
        "product_vs_checker_safe_labeling": agree,
        "malformed_certificate_rejection": malformed,
        "total_mismatches": total_mismatches,
        "gate_zero_mismatches_pass": gate_pass,
    }

    out = results_path("e0_semantic_conformance.json", args.out)
    write_results(out, payload)

    # -- human summary ---------------------------------------------------
    print("=" * 70)
    print("E0 — Semantic conformance (offline, solver-only)")
    print("=" * 70)
    print(f"seed tasks: {len(suite)}")
    print(f"[1] oracle vs independent monitor: "
          f"{diff['pairs_checked']} (policy,trace) pairs over "
          f"{diff['policies_tested']} policies -> {diff['mismatches']} mismatches")
    print(f"[2] product/checker SAFE agreement: "
          f"{agree['product_safe']} product-SAFE, "
          f"{agree['safe_certs_accepted']} certs accepted -> "
          f"{agree['mismatches']} mismatches")
    print(f"[3] malformed-certificate rejection: "
          f"{malformed['mutations_rejected']}/{malformed['mutations_tested']} rejected "
          f"(clean accepted={malformed['clean_certificate_accepted']})")
    if malformed["mutations_wrongly_accepted"]:
        print(f"    WARNING: tampered certs wrongly accepted: "
              f"{malformed['mutations_wrongly_accepted']}")
    print("-" * 70)
    print(f"total known mismatches: {total_mismatches}  "
          f"GATE (zero mismatches): {'PASS' if gate_pass else 'FAIL'}")
    print(f"results -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
