#!/usr/bin/env python
"""Real-corpus evaluation harness for AgentProof-CEGAR (Paper 2, plan §4.3, §7).

This is the measurement harness over **all** real, mined agent workflows in
``corpus/real_world/graphs_v2/`` (912 flat ``AgentGraph`` JSONs across the
langgraph / autogen / crewai / adk frameworks). It replaces the synthetic-only
benchmark with an honest measurement on lossy, real extractions.

What it measures, per policy in :data:`benchmarks.real_corpus.policies.POLICIES`
over every lifted graph, under the SOUND default gate
(``assume_trace_conservative=False``):

* the tri-valued verdict distribution (SAFE / UNSAFE / UNKNOWN);
* the ``unknown_reason`` breakdown (``unsupported_region`` /
  ``uncertified_extraction`` / ``may_violation_candidate`` / ...);
* the per-framework verdict split;
* policy-alphabet coverage (how many graphs actually contain an atom the policy
  references / could be *triggered* by — separating "vacuously not-applicable"
  from a genuine SAFE/UNSAFE);
* the ``may_violation_candidate`` count, with the first ~20 candidates listed by
  graph name + witness path (labelled clearly as **unvalidated** candidates, not
  ground-truth defects).

Global metrics:

* **Certification rate** — the fraction of graphs (where at least one policy is
  applicable) that certify SAFE under any applicable policy. Expected near-zero:
  that IS the extraction-bottleneck result (Paper 1's thesis, measured on real
  data). A transparent ``sentinel_exempt`` sensitivity variant re-runs treating
  ``EffectKind.NONE`` nodes (entry/exit/passthrough sentinels, which emit no
  policy atom) as certifiable regardless of provenance, and reports how much (if
  at all) the SAFE rate rises — clearly labelled as an assumption, not default.
* **Repair substrate** — over graphs the analyzer reports *definite* UNSAFE, run
  the solver-only :func:`~agentproof.cegar.repair.repair` and record how many
  reach SAFE and are admitted by the INDEPENDENT certificate checker, with mean
  cost / edits.
* **Static/runtime partition (E5 on real data)** — effect-bearing node-visits in
  a certified region (no runtime judge needed) vs routed to UNKNOWN (need a
  runtime guard); reports the certifiable fraction (honestly likely tiny).
* **Zero-false-SAFE audit** — for every SAFE result, an independent recomputation
  asserts :func:`~agentproof.cegar.ir.region_is_certifiable` holds over the
  may-reachable region and that region carries no unsupported fact. This is the
  headline soundness guarantee and is a HARD ASSERT (the run aborts on any
  violation).
* timing (total wall time, mean per-graph analysis time).

The analysis is deterministic and uses no LLM/network: repair runs with the
default solver proposer only.

HONESTY: real mined graphs are lossy AST extractions; UNKNOWN domination is the
correct, sound outcome and the central measurement. may-candidates are
unvalidated; no human ground truth is claimed.

Run: ``.venv/bin/python scripts/cegar/real_corpus_eval.py``
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from collections import Counter, deque
from dataclasses import replace
from typing import Any

# Make the repo root importable so `benchmarks` and `agentproof` resolve when the
# script is run from anywhere.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from benchmarks.real_corpus.policies import (  # noqa: E402
    POLICIES,
    classify_tool,
    lift_real,
    policy_alphabet_atoms,
)

from agentproof.cegar.checker import check_certificate  # noqa: E402
from agentproof.cegar.ir import (  # noqa: E402
    EffectKind,
    EffectNode,
    MayMustGraph,
    Verdict,
    region_is_certifiable,
)
from agentproof.cegar.policy import (  # noqa: E402
    All,
    Bounded,
    Forbid,
    LeadsTo,
    Never,
    Policy,
    Predicate,
    RequireBefore,
)
from agentproof.cegar.product import ProductResult, check  # noqa: E402
from agentproof.cegar.repair import repair  # noqa: E402

CORPUS_DIR = os.path.join(_REPO_ROOT, "corpus", "real_world", "graphs_v2")
FRAMEWORKS = ("langgraph", "autogen", "crewai", "adk")
# Effect kinds that constitute a guardable side effect (NONE = pure routing).
_EFFECTFUL: frozenset[EffectKind] = frozenset(
    e for e in EffectKind if e is not EffectKind.NONE
)


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------

class LoadedGraph:
    """A lifted real graph plus the metadata the harness reports against."""

    __slots__ = ("name", "framework", "path", "mm", "atom_may")

    def __init__(self, name: str, framework: str, path: str, mm: MayMustGraph) -> None:
        self.name = name
        self.framework = framework
        self.path = path
        self.mm = mm
        # atom_key -> True if some node's MAY-side eval of that atom is True.
        self.atom_may: dict[str, bool] = {}


def load_corpus() -> list[LoadedGraph]:
    """Lift every corpus JSON into a :class:`LoadedGraph` (deterministic order)."""
    files = sorted(glob.glob(os.path.join(CORPUS_DIR, "*.json")))
    if not files:
        raise SystemExit(f"no corpus graphs under {CORPUS_DIR}")
    out: list[LoadedGraph] = []
    for path in files:
        with open(path, encoding="utf-8") as fh:
            gd = json.load(fh)
        mm = lift_real(gd, tag_effects=True)
        fw = gd.get("framework", mm.framework) or "unknown"
        out.append(LoadedGraph(gd.get("name", mm.name), fw, path, mm))
    return out


# ---------------------------------------------------------------------------
# Policy alphabet / trigger atoms
# ---------------------------------------------------------------------------

def _trigger_atoms(policy: Policy) -> tuple[Predicate, ...]:
    """The leaf atoms whose presence could *trigger* the policy.

    A policy is only genuinely applicable to a graph if the graph can emit the
    atom that creates an obligation / violation: the forbidden predicate of
    :class:`Never`, the guarded predicate of :class:`RequireBefore`, the bounded
    predicate of :class:`Bounded`, the ordered steps of :class:`Forbid`, the
    trigger of :class:`LeadsTo`, or (recursively) the triggers of an
    :class:`All`. The *required* side of a ``RequireBefore`` (e.g. the approval)
    is deliberately excluded: an approval alone, with no guarded effect, cannot
    trigger the property.
    """
    if isinstance(policy, Never):
        return policy.pred.atoms()
    if isinstance(policy, RequireBefore):
        return policy.guarded.atoms()
    if isinstance(policy, Bounded):
        return policy.pred.atoms()
    if isinstance(policy, Forbid):
        return tuple(a for s in policy.steps for a in s.atoms())
    if isinstance(policy, LeadsTo):
        return policy.trigger.atoms()
    if isinstance(policy, All):
        out: list[Predicate] = []
        for sub in policy.policies:
            out.extend(_trigger_atoms(sub))
        return tuple(out)
    return policy.predicates()


def _index_atom_may(graphs: list[LoadedGraph]) -> None:
    """Populate ``LoadedGraph.atom_may`` for every atom any policy references.

    For each policy leaf atom, mark whether some node's MAY-side abstract eval is
    True on the graph (i.e. the atom can fire on at least one node).
    """
    atoms: dict[str, Predicate] = {}
    for _pid, pol, _desc in POLICIES:
        for atom in pol.predicates():
            atoms.setdefault(atom.atom_key(), atom)
    for g in graphs:
        for key, atom in atoms.items():
            g.atom_may[key] = any(atom.abstract_eval(n)[0] for n in g.mm.nodes)


def _policy_applicable(policy: Policy, g: LoadedGraph) -> bool:
    """Does ``g`` contain at least one atom that could *trigger* ``policy``?"""
    triggers = _trigger_atoms(policy)
    if not triggers:
        return False
    keys = {a.atom_key() for a in triggers}
    return any(g.atom_may.get(k, False) for k in keys)


def _alphabet_present(policy: Policy, g: LoadedGraph) -> bool:
    """Does ``g`` contain at least one atom the policy references (any side)?"""
    return any(g.atom_may.get(a.atom_key(), False) for a in policy.predicates())


# ---------------------------------------------------------------------------
# Reachable-region recomputation (independent zero-false-SAFE audit)
# ---------------------------------------------------------------------------

def _reachable_region(g: MayMustGraph) -> tuple[set[str], set[tuple[str, str]]]:
    """May-reachable nodes/edges from the entry over ALL out-edges (BFS).

    Independent of the product monitor: this is the over-approximation of what
    any policy run could touch, used to audit SAFE certificates.
    """
    nodes: set[str] = set()
    edges: set[tuple[str, str]] = set()
    q: deque[str] = deque([g.entry_id])
    nodes.add(g.entry_id)
    while q:
        nid = q.popleft()
        for e in g.out_edges(nid):
            edges.add((e.source, e.target))
            if e.target not in nodes:
                nodes.add(e.target)
                q.append(e.target)
    return nodes, edges


def _audit_safe(g: MayMustGraph, res: ProductResult) -> None:
    """HARD ASSERT that a SAFE verdict is genuinely certifiable (zero-false-SAFE).

    Recomputes the may-reachable region independently and asserts
    :func:`region_is_certifiable` holds over it, that no node in that region
    carries an unsupported fact, and that the product agrees the region is
    certified with no residual unsupported facts. Any failure aborts the run.
    """
    assert res.certified, f"SAFE without certified flag: {g.name}"
    assert not res.unsupported_facts, (
        f"SAFE with residual unsupported facts on {g.name}: {res.unsupported_facts}"
    )
    nodes, edges = _reachable_region(g)
    assert region_is_certifiable(g, nodes, edges, assume_trace_conservative=False), (
        f"SAFE but reachable region not certifiable: {g.name}"
    )
    for nid in nodes:
        n = g.node_by_id(nid)
        assert n is not None and not n.unsupported and n.provenance.is_exact, (
            f"SAFE but node {nid} in region is not proof-eligible: {g.name}"
        )


# ---------------------------------------------------------------------------
# Sentinel-exempt sensitivity variant
# ---------------------------------------------------------------------------

def _sentinel_exempt_graph(g: MayMustGraph) -> MayMustGraph:
    """Return a copy where every ``EffectKind.NONE`` node is made certifiable.

    ASSUMPTION (sensitivity only, never the sound default): entry / exit /
    passthrough sentinels lift to ``EffectKind.NONE`` and emit no policy atom, so
    treating them as exact + fact-free cannot change *which* effects a policy
    sees. This isolates how much of the near-zero SAFE rate is attributable to
    lossy provenance on those pure-routing sentinels versus genuine effect nodes
    and edges (which are left untouched — edges can still block certification).
    """
    new_nodes: list[EffectNode] = []
    changed = False
    for n in g.nodes:
        if n.effect is EffectKind.NONE and (
            not n.provenance.is_exact or n.unsupported
        ):
            new_nodes.append(
                replace(
                    n,
                    provenance=replace(n.provenance, confidence="exact"),
                    modeling_confidence="exact",
                    unsupported=(),
                )
            )
            changed = True
        else:
            new_nodes.append(n)
    if not changed:
        return g
    return replace(g, nodes=tuple(new_nodes))


# ---------------------------------------------------------------------------
# Per-policy evaluation
# ---------------------------------------------------------------------------

def _witness_path_str(res: ProductResult) -> str:
    if res.witness is None:
        return ""
    return " -> ".join(res.witness.product_path)


def eval_policy(
    pid: str,
    policy: Policy,
    desc: str,
    graphs: list[LoadedGraph],
    *,
    safe_graph_hits: dict[str, set[str]],
    partition: Counter,
) -> dict[str, Any]:
    """Run one policy over the whole corpus and return its report block."""
    verdicts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    per_fw: dict[str, Counter[str]] = {fw: Counter() for fw in FRAMEWORKS}
    per_fw_other: Counter[str] = Counter()
    alphabet_present = 0
    applicable = 0
    unsafe_examples: list[dict[str, Any]] = []
    may_candidates: list[dict[str, Any]] = []

    for g in graphs:
        res = check(g.mm, policy, assume_trace_conservative=False)
        v = res.verdict.value
        verdicts[v] += 1

        present = _alphabet_present(policy, g)
        appl = _policy_applicable(policy, g)
        if present:
            alphabet_present += 1
        if appl:
            applicable += 1

        fw_counter = per_fw.get(g.framework)
        if fw_counter is None:
            per_fw_other[v] += 1
        else:
            fw_counter[v] += 1

        if res.verdict is Verdict.SAFE:
            _audit_safe(g.mm, res)  # HARD zero-false-SAFE assert
            if appl:
                safe_graph_hits.setdefault(g.name, set()).add(pid)
        elif res.verdict is Verdict.UNKNOWN:
            reasons[res.unknown_reason or "none"] += 1
            if res.unknown_reason == "may_violation_candidate":
                may_candidates.append({
                    "policy": pid,
                    "graph": g.name,
                    "framework": g.framework,
                    "violation_kind": res.violation_kind,
                    "witness_path": _witness_path_str(res),
                })
        elif res.verdict is Verdict.UNSAFE:
            if len(unsafe_examples) < 20:
                unsafe_examples.append({
                    "graph": g.name,
                    "framework": g.framework,
                    "violation_kind": res.violation_kind,
                    "certified": res.certified,
                    "witness_path": _witness_path_str(res),
                })

        # Static/runtime partition contribution (E5 on real data), aggregated
        # across all policy x graph analyses.
        wpath = set(res.witness.product_path) if res.witness is not None else set()
        for n in g.mm.nodes:
            if n.effect not in _EFFECTFUL:
                continue
            if res.verdict is Verdict.SAFE and n.is_certifiable:
                partition["safe"] += 1
            elif res.verdict is Verdict.UNSAFE and n.id in wpath:
                partition["unsafe"] += 1
            else:
                partition["unknown"] += 1

    return {
        "policy_id": pid,
        "description": desc,
        "alphabet_atoms": list(policy_alphabet_atoms(policy)),
        "trigger_atoms": sorted({a.atom_key() for a in _trigger_atoms(policy)}),
        "verdicts": {k: verdicts.get(k, 0) for k in ("safe", "unsafe", "unknown")},
        "unknown_reason_breakdown": dict(sorted(reasons.items())),
        "per_framework": {
            fw: {k: per_fw[fw].get(k, 0) for k in ("safe", "unsafe", "unknown")}
            for fw in FRAMEWORKS
        },
        "per_framework_other": dict(sorted(per_fw_other.items())),
        "graphs_with_alphabet_present": alphabet_present,
        "graphs_policy_applicable": applicable,
        "may_violation_candidate_count": len(may_candidates),
        "unsafe_examples": unsafe_examples,
        "_may_candidates": may_candidates,  # collected globally, stripped below
    }


# ---------------------------------------------------------------------------
# Repair substrate over definite-UNSAFE graphs (solver only)
# ---------------------------------------------------------------------------

def eval_repair_substrate(graphs: list[LoadedGraph]) -> dict[str, Any]:
    """Run solver-only repair over every definite-UNSAFE (graph, policy)."""
    attempted = 0
    repaired_safe = 0
    checker_accepted = 0
    costs: list[float] = []
    edit_counts: list[int] = []
    examples: list[dict[str, Any]] = []

    for g in graphs:
        for pid, policy, _desc in POLICIES:
            res = check(g.mm, policy, assume_trace_conservative=False)
            if res.verdict is not Verdict.UNSAFE:
                continue
            attempted += 1
            rr = repair(g.mm, policy, assume_trace_conservative=False)  # default solver
            accepted = False
            if rr.success and rr.certificate is not None:
                accepted = check_certificate(rr.certificate).accepted
            if rr.verdict is Verdict.SAFE:
                repaired_safe += 1
            if accepted:
                checker_accepted += 1
                if rr.cost is not None:
                    costs.append(rr.cost)
                edit_counts.append(len(rr.edits))
            if len(examples) < 20:
                examples.append({
                    "graph": g.name,
                    "framework": g.framework,
                    "policy": pid,
                    "repair_success": rr.success,
                    "final_verdict": rr.verdict.value,
                    "checker_accepted": accepted,
                    "cost": rr.cost,
                    "edits": rr.edits,
                })

    return {
        "definite_unsafe_attempts": attempted,
        "repaired_to_safe": repaired_safe,
        "checker_accepted": checker_accepted,
        "mean_cost": (sum(costs) / len(costs)) if costs else None,
        "mean_edits": (sum(edit_counts) / len(edit_counts)) if edit_counts else None,
        "examples": examples,
    }


# ---------------------------------------------------------------------------
# Sentinel-exempt sensitivity: SAFE count under the relaxed gate
# ---------------------------------------------------------------------------

def eval_sentinel_exempt(graphs: list[LoadedGraph]) -> dict[str, Any]:
    """Re-run every policy with NONE-node provenance exempted; count SAFE.

    Returns the count of (graph, policy) pairs that go SAFE and the number of
    distinct graphs that certify SAFE under any *applicable* policy, so the
    certification rate can be recomputed under the assumption.
    """
    safe_pairs = 0
    safe_graph_hits: set[str] = set()
    for g in graphs:
        exempt = _sentinel_exempt_graph(g.mm)
        for _pid, policy, _desc in POLICIES:
            res = check(exempt, policy, assume_trace_conservative=False)
            if res.verdict is Verdict.SAFE:
                safe_pairs += 1
                if _policy_applicable(policy, g):
                    safe_graph_hits.add(g.name)
    return {
        "safe_pairs": safe_pairs,
        "safe_graphs_applicable": len(safe_graph_hits),
        "_safe_graph_hits": safe_graph_hits,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "results", "real_corpus_eval.json"),
        help="output JSON path",
    )
    args = parser.parse_args(argv)

    wall0 = time.perf_counter()
    graphs = load_corpus()
    _index_atom_may(graphs)
    load_secs = time.perf_counter() - wall0

    # -- per-policy evaluation (sound default) -----------------------------
    analysis0 = time.perf_counter()
    safe_graph_hits: dict[str, set[str]] = {}
    partition: Counter = Counter()
    per_policy: list[dict[str, Any]] = []
    all_may_candidates: list[dict[str, Any]] = []
    for pid, policy, desc in POLICIES:
        block = eval_policy(
            pid, policy, desc, graphs,
            safe_graph_hits=safe_graph_hits, partition=partition,
        )
        all_may_candidates.extend(block.pop("_may_candidates"))
        per_policy.append(block)
    analysis_secs = time.perf_counter() - analysis0

    n_graphs = len(graphs)
    n_pairs = n_graphs * len(POLICIES)

    # -- certification rate (strict, sound default) ------------------------
    applicable_graphs = {
        g.name
        for g in graphs
        if any(_policy_applicable(pol, g) for _pid, pol, _ in POLICIES)
    }
    safe_under_any = set(safe_graph_hits.keys())
    denom = len(applicable_graphs)
    cert_rate_strict = (len(safe_under_any) / denom) if denom else 0.0

    # -- sentinel-exempt sensitivity ---------------------------------------
    sentinel = eval_sentinel_exempt(graphs)
    sent_hits = sentinel.pop("_safe_graph_hits")
    cert_rate_sentinel = (len(sent_hits) / denom) if denom else 0.0

    # -- repair substrate --------------------------------------------------
    repair0 = time.perf_counter()
    repair_block = eval_repair_substrate(graphs)
    repair_secs = time.perf_counter() - repair0

    # -- static/runtime partition (E5 on real data) ------------------------
    total_effect_visits = sum(partition.values())
    part_safe = partition.get("safe", 0)
    part_unsafe = partition.get("unsafe", 0)
    part_unknown = partition.get("unknown", 0)
    certifiable_fraction = (part_safe / total_effect_visits) if total_effect_visits else 0.0

    # -- zero-false-SAFE audit summary -------------------------------------
    total_safe_pairs = sum(b["verdicts"]["safe"] for b in per_policy)
    # The audit ran inline as a hard assert during eval_policy; reaching here
    # means it passed for all SAFE results.

    total_verdicts = Counter()
    for b in per_policy:
        for k, v in b["verdicts"].items():
            total_verdicts[k] += v

    wall_total = time.perf_counter() - wall0

    # -- tool-name effect coverage (context for the reader) ----------------
    tool_effect_counts: Counter[str] = Counter()
    tool_name_examples: dict[str, list[str]] = {}
    for g in graphs:
        for n in g.mm.nodes:
            name = n.tool or ""
            if not name:
                continue
            eff, _sens, _rev = classify_tool(name)
            tool_effect_counts[eff.value] += 1
            tool_name_examples.setdefault(eff.value, [])
            if name not in tool_name_examples[eff.value] and len(tool_name_examples[eff.value]) < 8:
                tool_name_examples[eff.value].append(name)

    payload: dict[str, Any] = {
        "experiment": "real_corpus_eval",
        "honesty": (
            "Real mined agent graphs are lossy AST extractions: tools carry no "
            "schema and provenance is mixed/mostly non-exact, so under the sound "
            "default gate (assume_trace_conservative=False) essentially every "
            "graph returns UNKNOWN. That UNKNOWN domination is the CORRECT sound "
            "outcome and is itself the central measurement — it quantifies Paper "
            "1's extraction-bottleneck thesis on real data. may_violation "
            "candidates are UNVALIDATED potential defects surfaced by the "
            "MAY-side tool-name heuristic, NOT ground-truth defects; no human "
            "ground truth is claimed. The sentinel_exempt certification rate is a "
            "labelled SENSITIVITY assumption (NONE-effect entry/exit/passthrough "
            "sentinels treated as certifiable), never the sound default. Every "
            "number here comes from actually running the analyzer over the 912 "
            "real corpus files."
        ),
        "corpus": {
            "dir": CORPUS_DIR,
            "n_graphs": n_graphs,
            "n_policies": len(POLICIES),
            "n_analysis_pairs": n_pairs,
            "framework_counts": dict(sorted(Counter(g.framework for g in graphs).items())),
        },
        "aggregate_verdicts": {k: total_verdicts.get(k, 0) for k in ("safe", "unsafe", "unknown")},
        "per_policy": per_policy,
        "certification_rate": {
            "definition": (
                "fraction of graphs (with >=1 applicable policy) that certify "
                "SAFE under any applicable policy"
            ),
            "graphs_with_any_applicable_policy": denom,
            "strict_sound_default": {
                "safe_graphs": len(safe_under_any),
                "rate": cert_rate_strict,
                "safe_graph_names": sorted(safe_under_any),
            },
            "sentinel_exempt_sensitivity": {
                "assumption": (
                    "NONE-effect (entry/exit/passthrough) nodes treated as "
                    "certifiable regardless of provenance; edges left untouched"
                ),
                "safe_pairs": sentinel["safe_pairs"],
                "safe_graphs": len(sent_hits),
                "rate": cert_rate_sentinel,
                "safe_graph_names": sorted(sent_hits),
            },
        },
        "may_violation_candidates": {
            "note": (
                "UNVALIDATED potential defects surfaced by the MAY-side "
                "tool-name effect heuristic; NOT ground-truth defects"
            ),
            "total": len(all_may_candidates),
            "first_20": all_may_candidates[:20],
        },
        "repair_substrate": {
            "note": (
                "solver-only proposer (no LLM/network); success requires the "
                "INDEPENDENT certificate checker to admit the patched program"
            ),
            **repair_block,
        },
        "static_runtime_partition_e5": {
            "note": (
                "effect-bearing node-visits across all policy x graph analyses; "
                "SAFE = executes under certificate (no runtime judge), UNSAFE = "
                "statically denied/repaired, UNKNOWN = needs runtime guard/judge"
            ),
            "total_effect_node_visits": total_effect_visits,
            "certified_safe": part_safe,
            "statically_denied_unsafe": part_unsafe,
            "runtime_unknown": part_unknown,
            "certifiable_fraction": certifiable_fraction,
        },
        "zero_false_safe_audit": {
            "note": (
                "HARD ASSERT during analysis: every SAFE result had its "
                "may-reachable region independently re-checked with "
                "region_is_certifiable and verified free of unsupported facts"
            ),
            "safe_results_audited": total_safe_pairs,
            "violations": 0,
            "passed": True,
        },
        "tool_name_effect_coverage": {
            "note": "classify_tool applied to every bound tool name in the corpus",
            "effect_counts": dict(sorted(tool_effect_counts.items())),
            "examples_by_effect": {k: v for k, v in sorted(tool_name_examples.items())},
        },
        "timing": {
            "total_wall_seconds": wall_total,
            "load_and_lift_seconds": load_secs,
            "analysis_seconds": analysis_secs,
            "repair_seconds": repair_secs,
            "mean_per_graph_analysis_seconds": (analysis_secs / n_graphs) if n_graphs else 0.0,
        },
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
        fh.write("\n")

    _print_summary(payload)
    print(f"\nresults -> {args.out}")
    return 0


def _print_summary(payload: dict[str, Any]) -> None:
    corpus = payload["corpus"]
    print("=" * 78)
    print("Real-corpus evaluation — AgentProof-CEGAR on mined agent workflows")
    print("=" * 78)
    print(f"graphs: {corpus['n_graphs']}   policies: {corpus['n_policies']}   "
          f"analysis pairs: {corpus['n_analysis_pairs']}")
    print(f"frameworks: {corpus['framework_counts']}")
    agg = payload["aggregate_verdicts"]
    print(f"aggregate verdicts (all pairs): SAFE={agg['safe']}  "
          f"UNSAFE={agg['unsafe']}  UNKNOWN={agg['unknown']}")
    print("-" * 78)
    print("per-policy verdicts (SAFE / UNSAFE / UNKNOWN) [alphabet-present | applicable]")
    print(f"{'policy':<28}{'SAFE':>6}{'UNSAFE':>8}{'UNKNOWN':>9}{'alph':>7}{'appl':>7}")
    for b in payload["per_policy"]:
        v = b["verdicts"]
        print(f"{b['policy_id']:<28}{v['safe']:>6}{v['unsafe']:>8}{v['unknown']:>9}"
              f"{b['graphs_with_alphabet_present']:>7}{b['graphs_policy_applicable']:>7}")
    print("-" * 78)
    cr = payload["certification_rate"]
    strict = cr["strict_sound_default"]
    sent = cr["sentinel_exempt_sensitivity"]
    print(f"certification rate denom (graphs w/ applicable policy): "
          f"{cr['graphs_with_any_applicable_policy']}")
    print(f"  strict (sound default):     {strict['safe_graphs']} graphs SAFE  "
          f"-> {strict['rate']*100:.3f}%   (extraction-bottleneck result)")
    print(f"  sentinel_exempt (ASSUMPTION): {sent['safe_graphs']} graphs SAFE  "
          f"-> {sent['rate']*100:.3f}%   (labelled sensitivity, not default)")
    print("-" * 78)
    mvc = payload["may_violation_candidates"]
    print(f"may_violation candidates (UNVALIDATED potential defects): {mvc['total']}")
    for c in mvc["first_20"][:20]:
        print(f"  [{c['policy']}] {c['graph']} ({c['framework']}): {c['witness_path']}")
    print("-" * 78)
    rs = payload["repair_substrate"]
    print(f"repair substrate: {rs['definite_unsafe_attempts']} definite-UNSAFE attempts  "
          f"-> {rs['repaired_to_safe']} repaired SAFE, "
          f"{rs['checker_accepted']} checker-accepted")
    if rs["mean_cost"] is not None:
        print(f"  mean cost={rs['mean_cost']:.3f}  mean edits={rs['mean_edits']:.3f}")
    print("-" * 78)
    part = payload["static_runtime_partition_e5"]
    print(f"static/runtime partition (E5, effect node-visits={part['total_effect_node_visits']}): "
          f"SAFE={part['certified_safe']} UNSAFE={part['statically_denied_unsafe']} "
          f"UNKNOWN={part['runtime_unknown']}")
    print(f"  certifiable fraction (no runtime judge): {part['certifiable_fraction']*100:.3f}%")
    print("-" * 78)
    audit = payload["zero_false_safe_audit"]
    print(f"ZERO-FALSE-SAFE audit: {audit['safe_results_audited']} SAFE results audited, "
          f"{audit['violations']} violations  -> "
          f"{'PASS' if audit['passed'] else 'FAIL'}")
    t = payload["timing"]
    print(f"timing: total {t['total_wall_seconds']:.2f}s  "
          f"analysis {t['analysis_seconds']:.2f}s  "
          f"mean/graph {t['mean_per_graph_analysis_seconds']*1000:.2f}ms")


if __name__ == "__main__":
    raise SystemExit(main())
