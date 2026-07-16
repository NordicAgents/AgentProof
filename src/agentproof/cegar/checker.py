"""Independent, minimal SAFE-certificate checker (Paper 2, §4.6, Theorem 2).

Trusted computing base (TCB) argument
--------------------------------------
This checker decides whether to *accept* a :class:`~agentproof.cegar.certificate.Certificate`.
It is the last line of defense against a false SAFE proof, so it is kept small,
auditable, and — crucially — **independent** of the analyzer. It imports ONLY:

    * :mod:`agentproof.cegar.ir`         — the may/must effect IR + the
                                           certification gate ``region_is_certifiable``;
    * :mod:`agentproof.cegar.policy`     — the typed policy language and its
                                           per-atom ``abstract_eval``;
    * :mod:`agentproof.cegar.certificate` — the certificate dataclass and
                                           :func:`canonical_hash`.

It does **not** import ``product``, ``oracle``, ``cegar``, or ``repair``. The
whole point is common-mode-failure resistance: a bug in the analyzer's product
construction that emitted a false SAFE must be caught here, because this file
re-derives the reachability proof from a *second, independent* implementation of
the shared finite-trace monitor semantics.

What the checker trusts, and nothing else
-----------------------------------------
The checker trusts:

    (a) the semantics of :mod:`ir` and :mod:`policy` (the shared contract), and
    (b) the ``graph`` and ``policy`` dicts *recorded in the certificate*, but
        only after confirming their content hashes match the recorded hashes.

It does NOT trust ``abstract_transitions`` (the analyzer's recorded product
exploration). That field is used only for an optional cross-check; the accept
decision rests entirely on the checker's own BFS.

The re-derivation (a SAFE-only may-reachability check)
------------------------------------------------------
A SAFE proof needs exactly this: *no bad state and no possibly-unfulfilled
obligation is reachable* in the product of the graph and the policy monitor,
under the sound may/must over-approximation. The checker walks the product
``(node, monitor_state)`` by BFS. At each node it enumerates every atom-valuation
the abstraction admits (``must`` ⇒ only True, ``¬may`` ⇒ only False, otherwise
both), steps the monitor, and rejects the moment ANY admissible valuation drives
a bad prefix, or a terminating node (exit or dead end) can be reached with the
monitor non-accepting (an unfulfilled obligation). Over-approximating admits
more traces than the concrete program can produce, so if no violation is
reachable here the certificate's SAFE claim holds — and a spurious analyzer SAFE
is caught. The monitor is a verbatim second implementation of the SHARED
FINITE-TRACE SEMANTICS (see :mod:`agentproof.cegar.policy` and the plan).

The monitor state space is finite by construction (a seen-flag for
``RequireBefore``, a bounded step index for ``Forbid``, a saturating counter for
``Bounded``, a pending-flag for ``LeadsTo``, tuples thereof for ``All``), so the
BFS over ``(node, monitor_state)`` terminates even on cyclic graphs.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from agentproof.cegar.certificate import Certificate, canonical_hash
from agentproof.cegar.ir import MayMustGraph, region_is_certifiable
from agentproof.cegar.policy import (
    All,
    Bounded,
    FalseP,
    Forbid,
    LeadsTo,
    Never,
    Policy,
    PredAnd,
    PredNot,
    PredOr,
    Predicate,
    RequireBefore,
    TrueP,
    policy_from_dict,
)


@dataclass
class CheckResult:
    """Outcome of checking a certificate.

    ``accepted`` is True only if every gate passed. ``reasons`` lists the
    rejection reasons (empty when accepted).
    """

    accepted: bool
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Predicate evaluation under an atom-valuation (independent re-implementation)
# ---------------------------------------------------------------------------

def _eval_pred(pred: Predicate, valuation: dict[str, bool]) -> bool:
    """Truth of ``pred`` under a Boolean ``valuation`` of its leaf atoms.

    A second, self-contained structural evaluator (not calling the analyzer's
    machinery): constants fold, Not/And/Or recurse, and leaf atoms are looked up
    by :meth:`~agentproof.cegar.policy.Predicate.atom_key`.
    """
    if isinstance(pred, TrueP):
        return True
    if isinstance(pred, FalseP):
        return False
    if isinstance(pred, PredNot):
        return not _eval_pred(pred.inner, valuation)
    if isinstance(pred, PredAnd):
        return _eval_pred(pred.left, valuation) and _eval_pred(pred.right, valuation)
    if isinstance(pred, PredOr):
        return _eval_pred(pred.left, valuation) or _eval_pred(pred.right, valuation)
    return bool(valuation.get(pred.atom_key(), False))


def _policy_atoms(policy: Policy) -> tuple[Predicate, ...]:
    """De-duplicated leaf atoms of ``policy`` (its abstract alphabet)."""
    seen: dict[str, Predicate] = {}
    for atom in policy.predicates():
        seen.setdefault(atom.atom_key(), atom)
    return tuple(seen[k] for k in sorted(seen))


def _admissible_valuations(node: Any, atoms: tuple[Predicate, ...]) -> list[dict[str, bool]]:
    """All atom-valuations the abstraction admits at ``node``.

    For each atom, ``(may, must) = atom.abstract_eval(node)`` bounds its truth:
    ``must`` ⇒ only True, ``¬may`` ⇒ only False, otherwise both. The Cartesian
    product over atoms is the set of admissible symbols — the sound may/must
    over-approximation the product automaton is driven by.
    """
    valuations: list[dict[str, bool]] = [{}]
    for atom in atoms:
        may, must = atom.abstract_eval(node)
        if must:
            options = (True,)
        elif not may:
            options = (False,)
        else:
            options = (True, False)
        valuations = [
            {**v, atom.atom_key(): opt} for v in valuations for opt in options
        ]
    return valuations


# ---------------------------------------------------------------------------
# Monitor: a second implementation of the SHARED FINITE-TRACE SEMANTICS
# ---------------------------------------------------------------------------
# A monitor state is a small hashable value:
#   Never          -> None            (no memory)
#   RequireBefore  -> bool  seen
#   Forbid         -> int   idx       (progress into the forbidden sequence)
#   Bounded        -> int   count     (saturating at k+1)
#   LeadsTo        -> bool  pending
#   All            -> tuple of sub-states
# The state space is finite, so the product BFS terminates.

def _initial_state(policy: Policy) -> Any:
    if isinstance(policy, Never):
        return None
    if isinstance(policy, RequireBefore):
        return False
    if isinstance(policy, Forbid):
        return 0
    if isinstance(policy, Bounded):
        return 0
    if isinstance(policy, LeadsTo):
        return False
    if isinstance(policy, All):
        return tuple(_initial_state(p) for p in policy.policies)
    raise ValueError(f"unsupported policy kind: {type(policy).__name__}")


def _step(policy: Policy, state: Any, valuation: dict[str, bool]) -> tuple[Any, bool]:
    """One monitor transition. Returns ``(next_state, bad)``.

    ``bad`` is True iff processing this event is a BAD PREFIX under the shared
    finite-trace semantics. Follows the documented per-operator scan EXACTLY.
    """
    if isinstance(policy, Never):
        bad = _eval_pred(policy.pred, valuation)
        return None, bad

    if isinstance(policy, RequireBefore):
        seen = state
        if policy.strict:
            bad = _eval_pred(policy.guarded, valuation) and not seen
            if _eval_pred(policy.required, valuation):
                seen = True
        else:
            if _eval_pred(policy.required, valuation):
                seen = True
            bad = _eval_pred(policy.guarded, valuation) and not seen
        return seen, bad

    if isinstance(policy, Forbid):
        steps = policy.steps
        idx = state
        if not policy.contiguous:
            if idx < len(steps) and _eval_pred(steps[idx], valuation):
                idx += 1
        else:
            if _eval_pred(steps[idx], valuation):
                idx += 1
            else:
                idx = 1 if _eval_pred(steps[0], valuation) else 0
        bad = idx == len(steps)
        return idx, bad

    if isinstance(policy, Bounded):
        count = state
        if _eval_pred(policy.pred, valuation):
            count += 1
        bad = count > policy.k
        # Saturate so the state space stays finite; count > k is absorbing-bad.
        return min(count, policy.k + 1), bad

    if isinstance(policy, LeadsTo):
        pending = state
        if _eval_pred(policy.trigger, valuation):
            pending = True
        if _eval_pred(policy.response, valuation):
            pending = False
        return pending, False  # LeadsTo is never a bad prefix

    if isinstance(policy, All):
        next_states = []
        any_bad = False
        for sub, sub_state in zip(policy.policies, state):
            ns, b = _step(sub, sub_state, valuation)
            next_states.append(ns)
            any_bad = any_bad or b
        return tuple(next_states), any_bad

    raise ValueError(f"unsupported policy kind: {type(policy).__name__}")


def _accepting(policy: Policy, state: Any) -> bool:
    """May a finite trace validly END in ``state``?

    Safety monitors (Never/RequireBefore/Forbid/Bounded) accept in every
    non-bad state. LeadsTo accepts only when no obligation is pending. All
    accepts iff every sub-monitor accepts.
    """
    if isinstance(policy, (Never, RequireBefore, Forbid, Bounded)):
        return True
    if isinstance(policy, LeadsTo):
        return not state
    if isinstance(policy, All):
        return all(_accepting(p, s) for p, s in zip(policy.policies, state))
    raise ValueError(f"unsupported policy kind: {type(policy).__name__}")


# ---------------------------------------------------------------------------
# The checker
# ---------------------------------------------------------------------------

def check_certificate(cert: Certificate) -> CheckResult:
    """Independently decide whether to accept a SAFE certificate.

    Gates, in order (any failure rejects, accumulating reasons):

    1. ``verdict`` must be ``"safe"``.
    2. Recomputed program/policy hashes must match the recorded hashes.
    3. Graph and policy must re-parse from their recorded dicts.
    4. Independent may-reachability BFS: no bad prefix and no possibly-
       unfulfilled obligation may be reachable in the product.
    5. Certification gate: :func:`region_is_certifiable` over the visited region
       must hold, unless ``"trace_conservative_assumed"`` is asserted.
    """
    reasons: list[str] = []

    # -- Gate 5(verdict): certificates are SAFE-only -----------------------
    if cert.verdict != "safe":
        reasons.append(f"verdict is {cert.verdict!r}, not 'safe'")
        # Nothing else is meaningful for a non-SAFE certificate.
        return CheckResult(accepted=False, reasons=reasons)

    # -- Gate 1: content hashes bind the certificate to graph+policy -------
    recomputed_program = canonical_hash(cert.graph)
    if recomputed_program != cert.program_hash:
        reasons.append(
            "program_hash mismatch: recorded "
            f"{cert.program_hash!r} != recomputed {recomputed_program!r}"
        )
    recomputed_policy = canonical_hash(cert.policy)
    if recomputed_policy != cert.policy_hash:
        reasons.append(
            "policy_hash mismatch: recorded "
            f"{cert.policy_hash!r} != recomputed {recomputed_policy!r}"
        )
    if reasons:
        return CheckResult(accepted=False, reasons=reasons)

    # -- Gate 2: re-parse graph and policy ---------------------------------
    try:
        graph = MayMustGraph.from_dict(cert.graph)
    except Exception as exc:  # malformed graph dict
        reasons.append(f"could not re-parse graph: {exc}")
        return CheckResult(accepted=False, reasons=reasons)
    try:
        policy = policy_from_dict(cert.policy)
    except Exception as exc:  # malformed policy dict
        reasons.append(f"could not re-parse policy: {exc}")
        return CheckResult(accepted=False, reasons=reasons)

    # -- Gate 3: independent may-reachability re-derivation -----------------
    atoms = _policy_atoms(policy)
    exit_ids = set(graph.exit_ids)

    entry = graph.node_by_id(graph.entry_id)
    if entry is None:
        reasons.append(f"entry node {graph.entry_id!r} not present in graph")
        return CheckResult(accepted=False, reasons=reasons)

    initial = (graph.entry_id, _initial_state(policy))
    queue: deque[tuple[str, Any]] = deque([initial])
    visited: set[tuple[str, Any]] = {initial}

    region_nodes: set[str] = set()
    region_edges: set[tuple[str, str]] = set()

    while queue:
        node_id, mstate = queue.popleft()
        region_nodes.add(node_id)

        node = graph.node_by_id(node_id)
        if node is None:
            # A referenced node with no definition: its emitted events are
            # unknown, so we cannot certify. Reject conservatively.
            reasons.append(f"reachable node {node_id!r} not present in graph")
            return CheckResult(accepted=False, reasons=reasons)

        successors = graph.successors(node_id)
        is_terminal = (node_id in exit_ids) or (len(successors) == 0)

        for valuation in _admissible_valuations(node, atoms):
            next_state, bad = _step(policy, mstate, valuation)
            if bad:
                reasons.append(
                    f"reachable BAD PREFIX at node {node_id!r} "
                    "(some admissible resolution violates the policy)"
                )
                return CheckResult(accepted=False, reasons=reasons)
            if is_terminal and not _accepting(policy, next_state):
                reasons.append(
                    f"reachable UNFULFILLED OBLIGATION at terminal node "
                    f"{node_id!r} (a run may end here with an open obligation)"
                )
                return CheckResult(accepted=False, reasons=reasons)
            for succ in successors:
                region_edges.add((node_id, succ))
                nxt = (succ, next_state)
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)

    # -- Gate 4: certification (trace-conservatism) gate -------------------
    assume = "trace_conservative_assumed" in cert.assumptions
    if not region_is_certifiable(
        graph,
        region_nodes,
        region_edges,
        assume_trace_conservative=assume,
    ):
        reasons.append(
            "certification gate failed: the visited region is not "
            "trace-conservative-certifiable (non-exact provenance or an "
            "unsupported fact in the reachable region)"
        )
        return CheckResult(accepted=False, reasons=reasons)

    return CheckResult(accepted=True, reasons=[])


# ---------------------------------------------------------------------------
# Smoke test (lean). The exhaustive monitor-vs-reference semantics differential
# and the per-operator end-to-end coverage live in
# tests/cegar/test_checker_differential.py, keeping this module small and
# auditable (its trusted-computing-base role wants minimal surface).
# ---------------------------------------------------------------------------

def _smoke() -> None:
    """Accept a clean SAFE certificate; reject a hash-consistent unsafe tamper.

    Run: ``.venv/bin/python src/agentproof/cegar/checker.py``.
    """
    import copy

    from agentproof.cegar.certificate import build_certificate
    from agentproof.cegar.ir import (
        EffectKind,
        EffectNode,
        Modality,
        ModalEdge,
        Provenance,
        Verdict,
    )
    from agentproof.cegar.policy import Never, Tool

    exact = Provenance(origin="ast_explicit", confidence="exact", source_span="f:1:2")
    nodes = (
        EffectNode(id="entry", effect=EffectKind.NONE, provenance=exact,
                   modeling_confidence="exact", state_predicates=("kind:entry",)),
        EffectNode(id="t1", effect=EffectKind.READ, tool="safe_reader", provenance=exact,
                   modeling_confidence="exact", state_predicates=("kind:tool",)),
        EffectNode(id="exit", effect=EffectKind.NONE, provenance=exact,
                   modeling_confidence="exact", state_predicates=("kind:exit",)),
    )
    edges = (
        ModalEdge(source="entry", target="t1", modality=Modality.MUST, provenance=exact),
        ModalEdge(source="t1", target="exit", modality=Modality.MUST, provenance=exact),
    )
    graph = MayMustGraph(name="smoke", framework="none", nodes=nodes, edges=edges,
                         entry_id="entry", exit_ids=("exit",))
    policy = Never(Tool("danger"), rule_id="no-danger")

    class _SafeResult:  # duck-typed SAFE product result (checker must not import product)
        verdict = Verdict.SAFE

    cert = build_certificate(graph, policy, _SafeResult(), created_tag="smoke")
    assert check_certificate(cert).accepted, "clean certificate rejected"

    # Tamper: add a reachable forbidden-tool node and recompute the hash so the
    # hash gate passes — the independent re-derivation must still reject it.
    tampered = graph.with_node(
        EffectNode(id="bad", effect=EffectKind.EXECUTE, tool="danger", provenance=exact,
                   modeling_confidence="exact", state_predicates=("kind:tool",))
    ).with_edges(graph.edges + (
        ModalEdge(source="entry", target="bad", modality=Modality.MAY, provenance=exact),
        ModalEdge(source="bad", target="exit", modality=Modality.MAY, provenance=exact),
    ))
    mutated = copy.deepcopy(cert)
    object.__setattr__(mutated, "graph", tampered.to_dict())
    object.__setattr__(mutated, "program_hash", canonical_hash(tampered.to_dict()))
    res = check_certificate(mutated)
    assert not res.accepted and any("BAD PREFIX" in r for r in res.reasons), res

    print("CHECKER SMOKE OK")


if __name__ == "__main__":
    _smoke()
