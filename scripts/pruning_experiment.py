#!/usr/bin/env python3
"""Path-sensitive monitor pruning: does the graph x DFA product prune monitors
that a cheaper static analysis cannot?  (Reviewer demand #8 / minimum
experiment #9.)

Motivation
----------
The prior monitor-pruning result (scripts/monitor_pruning.py) ran a fixed set
of GENERIC policies cross-product against the whole corpus.  Because those
policies' atoms almost never appear in a given workflow, EVERY prune it
reported was ALPHABET-LEVEL (the atom is simply absent) and ZERO prunes were
path-sensitive -- the product construction did no work that a one-line "is the
atom in the vocabulary?" check could not.  A reviewer correctly flagged that
this makes the product's contribution unmeasurable.

This experiment fixes that by design.  It authors WORKFLOW-SPECIFIC policies
(corpus/policies/workflow_specific_policies.json) whose atoms DO occur in the
target workflow, so an alphabet-only check can NEVER prune them.  It then
compares four pruning strategies of increasing power and reports the
INCREMENTAL count of monitors the full product proves inert that the cheaper
strategies do not -- the number the reviewer wants to be nonzero.

Four pruning strategies (over each authored (workflow, policy) pair)
--------------------------------------------------------------------
  (a) ALPHABET-ONLY        prune iff NONE of the policy's atoms appear in the
                           graph's tool/action vocabulary (the trivial
                           baseline; provenance-independent).
  (b) NODE-REACHABILITY    prune iff NO node emitting a policy atom is
                           reachable from entry (ignores DFA state / ordering).
  (c) PATH-SENSITIVE       prune iff check_temporal_property returns a
      PRODUCT               CERTIFIED verdict=="safe" -- the full graph x DFA
                           product.  Certification is EARNED from provenance
                           (assume_trace_conservative is NOT asserted); the
                           curated graphs are all exact-provenance and the
                           synthetic fixtures are exact except the deliberate
                           uncertified control.
  (d) RUNTIME-ONLY         never prune (deploy every monitor) -- the no-static
                           baseline.

Strategies form a lattice: reachability prunes a superset of alphabet-only
(an unreachable declared atom is prunable by (b) but not (a)); the product
prunes a superset of reachability (a satisfied response obligation over
reachable atoms is prunable by (c) but not (b)).  The HEADLINE is
``product_over_alphabet`` = monitors the product prunes that alphabet-only
keeps.

Soundness (zero false pruning)
------------------------------
For every monitor the product prunes, we exhaustively enumerate the graph's
finite maximal executions (bounded loop unrolling) and, for each TOOL-node
visit, every concrete tool resolution (each declared tool, plus the
tool-not-invoked / bare-visit case), then replay evaluate_monitors +
finalize_monitors and assert NO violation.  The static conservative model is a
superset of these runtime-representable traces, so a certified "safe" verdict
that survives this check is sound.  We report false_prunes (must be 0).

Certification gate control (reviewer fix #6)
--------------------------------------------
One synthetic fixture (syn_uncertified) is topologically a product-safe
response case but carries may-provenance on a traversed edge.  Under strategy
(c) (no caller assertion) the gate refuses to emit "safe" (returns
inconclusive / uncertified_extraction), so the product does NOT prune it -- we
confirm it WOULD be safe if conservatism were asserted, proving the gate, not
the topology, is what withholds the prune.

Determinism / offline: reads only local corpus files, enumerates
deterministically, writes corpus/real_world/pruning_experiment.json.  Run:
    /path/to/.venv/bin/python scripts/pruning_experiment.py
"""

from __future__ import annotations

import itertools
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from agentproof.graph.model import (
    AgentGraph,
    GraphNode,
    NodeKind,
    adjacency,
    graph_from_dict,
    node_by_id,
)
from agentproof.monitor.ltl import (
    CompiledMonitorRule,
    MonitorRuleSpec,
    compile_monitor_rule,
    evaluate_monitors,
    finalize_monitors,
)
from agentproof.monitor.ltl import _event_matches_predicate  # DFA event semantics
from agentproof.verify.temporal import check_temporal_property, node_visit_event

REPO = Path(__file__).resolve().parent.parent
CURATED_DIR = REPO / "corpus" / "curated"
POLICIES_PATH = REPO / "corpus" / "policies" / "workflow_specific_policies.json"
OUTPUT_PATH = REPO / "corpus" / "real_world" / "pruning_experiment.json"

# Soundness-enumeration bounds (kept small; pruned graphs are small/acyclic
# except one bounded-loop fixture).
MAX_NODE_VISITS = 3      # loop-unrolling bound per node along a path
MAX_PATHS = 20000        # cap on enumerated maximal paths per graph
MAX_RESOLUTIONS = 4096   # cap on concrete tool-resolutions per path


# ---------------------------------------------------------------------------
# Synthetic fixtures (embedded, clearly labeled; NOT sampled from any corpus)
# ---------------------------------------------------------------------------
# Purpose-built to exercise path-sensitivity that the curated (mostly linear)
# topologies cannot.  Every element is exact-provenance so the fixtures certify
# from provenance alone -- EXCEPT syn_uncertified, which deliberately carries a
# may-provenance edge to drive the certification-gate control.  origin is
# "synthesized": these correspond to no source code and are documented as
# constructed, not mined.

def _n(nid: str, kind: str, tools: tuple[str, ...] = (), conf: str = "exact") -> dict:
    return {
        "id": nid, "kind": kind, "label": nid, "tools": list(tools), "metadata": {},
        "origin": "synthesized", "confidence": conf, "source_span": "",
        "effects": [], "capabilities": [],
    }


def _e(src: str, tgt: str, cond: str = "", kind: str = "direct",
       conf: str = "exact", back: bool = False) -> dict:
    return {
        "source": src, "target": tgt, "kind": kind, "condition": cond,
        "origin": "synthesized", "confidence": conf, "source_span": "",
        "back_edge": back,
    }


def _g(name: str, nodes: list[dict], edges: list[dict]) -> dict:
    return {
        "name": name, "framework": "synthetic", "entry_id": "__start__",
        "exit_ids": ["__end__"], "nodes": nodes, "edges": edges,
    }


SYNTHETIC_GRAPHS: dict[str, dict] = {
    # forbidden tool DECLARED (danger node) but UNREACHABLE from entry.
    "syn_unreachable_forbidden": _g(
        "syn_unreachable_forbidden",
        [_n("__start__", "entry"), _n("proc", "llm"), _n("save", "tool", ("safe_write",)),
         _n("danger", "tool", ("drop_table",)), _n("__end__", "exit")],
        [_e("__start__", "proc"), _e("proc", "save"), _e("save", "__end__"),
         _e("danger", "__end__")],  # danger has no incoming edge -> unreachable
    ),
    # branching response: sensitive branch fetches PII then always human-reviews;
    # normal branch never fetches.  Obligation satisfied on every branch.
    "syn_response_branch": _g(
        "syn_response_branch",
        [_n("__start__", "entry"), _n("triage", "router"), _n("fetch", "tool", ("fetch_pii",)),
         _n("review", "human"), _n("handle", "llm"), _n("__end__", "exit")],
        [_e("__start__", "triage"), _e("triage", "fetch", "sensitive", "conditional"),
         _e("triage", "handle", "normal", "conditional"), _e("fetch", "review"),
         _e("review", "__end__"), _e("handle", "__end__")],
    ),
    # bounded response met within k on BOTH branches (deterministic antecedent
    # router + deterministic human consequent, no conservative tool node between).
    "syn_bounded_branch": _g(
        "syn_bounded_branch",
        [_n("__start__", "entry"), _n("gate", "router"), _n("reviewA", "human"),
         _n("reviewB", "human"), _n("__end__", "exit")],
        [_e("__start__", "gate"), _e("gate", "reviewA", "pathA", "conditional"),
         _e("gate", "reviewB", "pathB", "conditional"), _e("reviewA", "__end__"),
         _e("reviewB", "__end__")],
    ),
    # looping workflow with an unreachable forbidden tool: product proves inert
    # despite the retry cycle.
    "syn_loop_safe": _g(
        "syn_loop_safe",
        [_n("__start__", "entry"), _n("work", "llm"), _n("check", "tool", ("validate",)),
         _n("router", "router"), _n("danger", "tool", ("drop_table",)), _n("__end__", "exit")],
        [_e("__start__", "work"), _e("work", "check"), _e("check", "router"),
         _e("router", "work", "retry", "conditional", back=True),
         _e("router", "__end__", "done", "conditional"),
         _e("danger", "__end__")],  # danger unreachable
    ),
    # LIVE: forbidden tool on a REACHABLE node -> bad-prefix witness (must keep).
    "syn_forbidden_reachable": _g(
        "syn_forbidden_reachable",
        [_n("__start__", "entry"), _n("proc", "llm"), _n("danger", "tool", ("drop_table",)),
         _n("__end__", "exit")],
        [_e("__start__", "proc"), _e("proc", "danger"), _e("danger", "__end__")],
    ),
    # LIVE: branch fetches PII then terminates via a fast path with no human
    # review -> unfulfilled-obligation witness (must keep).
    "syn_response_violated": _g(
        "syn_response_violated",
        [_n("__start__", "entry"), _n("triage", "router"), _n("fetch", "tool", ("fetch_pii",)),
         _n("review", "human"), _n("skip", "llm"), _n("__end__", "exit")],
        [_e("__start__", "triage"), _e("triage", "fetch", "sensitive", "conditional"),
         _e("triage", "skip", "fast", "conditional"), _e("fetch", "skip"),
         _e("review", "__end__"), _e("skip", "__end__")],
    ),
    # LIVE: one branch reaches the human two steps after the routing decision,
    # beyond the F[<=1] bound -> bad-prefix witness (must keep; the bound bites).
    "syn_bounded_late": _g(
        "syn_bounded_late",
        [_n("__start__", "entry"), _n("gate", "router"), _n("stepA", "llm"),
         _n("reviewA", "human"), _n("reviewB", "human"), _n("__end__", "exit")],
        [_e("__start__", "gate"), _e("gate", "stepA", "slow", "conditional"),
         _e("gate", "reviewB", "fast", "conditional"), _e("stepA", "reviewA"),
         _e("reviewA", "__end__"), _e("reviewB", "__end__")],
    ),
    # LIVE: retry loop can postpone the human approval forever -> inconclusive
    # (divergent obligation, infinite runs out of finite-trace scope; must keep).
    "syn_loop_divergent": _g(
        "syn_loop_divergent",
        [_n("__start__", "entry"), _n("gen", "llm"), _n("val", "tool", ("run_check",)),
         _n("router", "router"), _n("approve", "human"), _n("__end__", "exit")],
        [_e("__start__", "gen"), _e("gen", "val"), _e("val", "router"),
         _e("router", "gen", "fail", "conditional", back=True),
         _e("router", "approve", "pass", "conditional"),
         _e("approve", "__end__")],
    ),
    # CERTIFICATION-GATE CONTROL: topologically a product-safe response case, but
    # the fetch->review edge carries may-provenance.  Without a caller
    # conservatism assertion the gate downgrades the would-be "safe" verdict.
    "syn_uncertified": _g(
        "syn_uncertified",
        [_n("__start__", "entry"), _n("fetch", "tool", ("fetch_pii",)),
         _n("review", "human"), _n("__end__", "exit")],
        [_e("__start__", "fetch"), _e("fetch", "review", conf="may"),
         _e("review", "__end__")],
    ),
}


# ---------------------------------------------------------------------------
# Graph loading
# ---------------------------------------------------------------------------

def load_graph(target: str) -> dict:
    """Return the raw graph dict for a target name (curated basename or synthetic)."""
    if target in SYNTHETIC_GRAPHS:
        return SYNTHETIC_GRAPHS[target]
    path = CURATED_DIR / f"{target}.json"
    if not path.exists():
        raise FileNotFoundError(f"unknown target graph: {target!r}")
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Atom emission (tied to the DFA event semantics)
# ---------------------------------------------------------------------------

def _candidate_events(node: GraphNode) -> list[dict[str, Any]]:
    """Every per-visit event a node CAN emit, built with node_visit_event.

    A TOOL node with declared tools T can emit one event per t in T (binding
    tool_name=t) plus the bare visit event (tool_name=None, the
    tool-not-invoked / empty-sequence resolution).  Any other node emits its
    single deterministic visit event.  This mirrors both the static closure in
    verify.temporal and the runtime api._event_for_node, so the alphabet /
    reachability strategies are defined by exactly the events the DFA checks.
    """
    if node.kind == NodeKind.TOOL and node.tools:
        return [node_visit_event(node, t) for t in node.tools] + [node_visit_event(node, None)]
    return [node_visit_event(node, None)]


def node_atoms(node: GraphNode, predicates: tuple[str, ...]) -> set[str]:
    """Policy atoms this node can satisfy (via the DFA's _event_matches_predicate)."""
    hits: set[str] = set()
    events = _candidate_events(node)
    for pred in predicates:
        if any(_event_matches_predicate(pred, ev) for ev in events):
            hits.add(pred)
    return hits


def workflow_alphabet(graph: AgentGraph, predicates: tuple[str, ...]) -> set[str]:
    alpha: set[str] = set()
    for node in graph.nodes:
        alpha |= node_atoms(node, predicates)
    return alpha


def reachable_node_ids(graph: AgentGraph) -> set[str]:
    adj = adjacency(graph)
    seen = {graph.entry_id}
    stack = [graph.entry_id]
    while stack:
        cur = stack.pop()
        for nxt in adj.get(cur, []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def reachable_alphabet(graph: AgentGraph, predicates: tuple[str, ...]) -> set[str]:
    reach = reachable_node_ids(graph)
    alpha: set[str] = set()
    for node in graph.nodes:
        if node.id in reach:
            alpha |= node_atoms(node, predicates)
    return alpha


# ---------------------------------------------------------------------------
# Exhaustive concrete-execution enumeration (bounded) for the soundness check
# ---------------------------------------------------------------------------

def enumerate_maximal_paths(graph: AgentGraph) -> list[list[str]]:
    """All finite maximal executions (paths to a termination point).

    A termination point is an exit node or a dead end (no successors).  Loops
    are unrolled with a per-node visit cap (MAX_NODE_VISITS); a branch that
    would exceed the cap is dropped (its continuations are longer unrollings of
    the same cycle, already represented by shorter ones for finite-trace
    checking).  Capped at MAX_PATHS.
    """
    adj = adjacency(graph)
    exit_set = set(graph.exit_ids)
    paths: list[list[str]] = []
    # DFS stack of (path, visit_counts)
    stack: list[tuple[list[str], dict[str, int]]] = [([graph.entry_id], {graph.entry_id: 1})]
    while stack and len(paths) < MAX_PATHS:
        path, counts = stack.pop()
        cur = path[-1]
        succ = adj.get(cur, [])
        if cur in exit_set or not succ:
            paths.append(path)
            continue
        for nxt in succ:
            if counts.get(nxt, 0) >= MAX_NODE_VISITS:
                continue  # loop-unroll bound reached on this branch
            new_counts = dict(counts)
            new_counts[nxt] = new_counts.get(nxt, 0) + 1
            stack.append((path + [nxt], new_counts))
    return paths


def _node_resolution_events(node: GraphNode) -> list[dict[str, Any]]:
    """Concrete single-visit event choices for the soundness enumeration."""
    return _candidate_events(node)


def concrete_traces_for_path(graph: AgentGraph, path: list[str]) -> list[list[dict[str, Any]]]:
    """All concrete event traces for a path: cartesian product of per-node
    resolution choices (one emitted event per node visit).  Capped."""
    per_node_choices: list[list[dict[str, Any]]] = []
    for nid in path:
        node = node_by_id(graph, nid)
        if node is None:
            per_node_choices.append([{"node_id": nid, "action_type": "unknown"}])
        else:
            per_node_choices.append(_node_resolution_events(node))
    traces: list[list[dict[str, Any]]] = []
    for combo in itertools.product(*per_node_choices):
        traces.append(list(combo))
        if len(traces) >= MAX_RESOLUTIONS:
            break
    return traces


def trace_violates(rule: CompiledMonitorRule, trace: list[dict[str, Any]]) -> bool:
    """Replay a concrete trace through the runtime monitor; True iff any
    bad-prefix event OR an unfulfilled obligation at termination."""
    state: dict[str, int] = {}
    rules = (rule,)
    for event in trace:
        state, snapshots, _ = evaluate_monitors(rules, state, event)
        if any(s.violation for s in snapshots):
            return True
    end_snapshots, _ = finalize_monitors(rules, state)
    return any(s.violation for s in end_snapshots)


def soundness_check(graph: AgentGraph, rule: CompiledMonitorRule) -> tuple[bool, int, list]:
    """Enumerate concrete finite maximal executions; return
    (no_violation_found, n_executions_checked, witness_traces)."""
    n_checked = 0
    witnesses: list[list[str]] = []
    for path in enumerate_maximal_paths(graph):
        for trace in concrete_traces_for_path(graph, path):
            n_checked += 1
            if trace_violates(rule, trace):
                witnesses.append([e.get("tool_name") or e.get("action_type") for e in trace])
    return (len(witnesses) == 0, n_checked, witnesses)


# ---------------------------------------------------------------------------
# Experiment driver
# ---------------------------------------------------------------------------

def main() -> None:
    spec = json.loads(POLICIES_PATH.read_text())
    policies = spec["policies"]

    rows: list[dict[str, Any]] = []
    # strategy prune tallies
    pruned = {"alphabet_only": 0, "node_reachability": 0, "path_sensitive_product": 0,
              "runtime_only": 0}
    incr_over_alpha = 0
    incr_over_reach = 0
    incr_alpha_curated = 0
    incr_alpha_synthetic = 0
    false_prunes = 0
    total_executions_checked = 0
    product_pruned_pairs = 0
    cert_gate_controls: list[dict[str, Any]] = []
    per_case_type: dict[str, dict[str, int]] = defaultdict(
        lambda: {"pairs": 0, "product_pruned": 0, "incr_over_alpha": 0})
    unexpected_verdicts: list[dict[str, str]] = []

    for pol in policies:
        target = pol["target"]
        gdict = load_graph(target)
        graph = graph_from_dict(gdict)
        rule = compile_monitor_rule(MonitorRuleSpec(
            rule_id=pol["id"], dsl=pol["dsl"], on_violation=pol.get("on_violation", "halt")))
        preds = rule.predicates

        alpha = workflow_alphabet(graph, preds)
        reach_alpha = reachable_alphabet(graph, preds)
        atoms_present = bool(alpha)
        atoms_reachable = bool(reach_alpha)

        alpha_prune = not atoms_present
        reach_prune = not atoms_reachable

        # Strategy (c): earn certification from provenance (no caller assertion).
        result = check_temporal_property(graph, rule, assume_trace_conservative=False)
        verdict = result["verdict"]
        product_prune = verdict == "safe" and result.get("certified", False)

        # Certification-gate control: what WOULD the verdict be if the caller
        # asserted conservatism?  (Proves the gate, not the topology, withholds.)
        gate_note = None
        if pol.get("case_type") == "uncertified_control":
            asserted = check_temporal_property(graph, rule, assume_trace_conservative=True)
            gate_note = {
                "policy_id": pol["id"], "target": target,
                "verdict_without_assertion": verdict,
                "inconclusive_reason": result.get("inconclusive_reason"),
                "certified_without_assertion": result.get("certified"),
                "verdict_with_conservatism_asserted": asserted["verdict"],
                "product_pruned_without_assertion": product_prune,
                "would_be_safe_if_asserted": asserted["verdict"] == "safe",
            }
            cert_gate_controls.append(gate_note)

        # tallies
        if alpha_prune:
            pruned["alphabet_only"] += 1
        if reach_prune:
            pruned["node_reachability"] += 1
        if product_prune:
            pruned["path_sensitive_product"] += 1
        # runtime_only never prunes

        this_incr_alpha = product_prune and not alpha_prune
        this_incr_reach = product_prune and not reach_prune
        if this_incr_alpha:
            incr_over_alpha += 1
            if pol.get("synthetic"):
                incr_alpha_synthetic += 1
            else:
                incr_alpha_curated += 1
        if this_incr_reach:
            incr_over_reach += 1

        ct = pol.get("case_type", "?")
        per_case_type[ct]["pairs"] += 1
        if product_prune:
            per_case_type[ct]["product_pruned"] += 1
        if this_incr_alpha:
            per_case_type[ct]["incr_over_alpha"] += 1

        # soundness check on every product-pruned pair
        soundness_ok = None
        n_exec = 0
        if product_prune:
            product_pruned_pairs += 1
            soundness_ok, n_exec, witnesses = soundness_check(graph, rule)
            total_executions_checked += n_exec
            if not soundness_ok:
                false_prunes += 1

        # expected-verdict audit (design self-check; does not affect metrics)
        expected = pol.get("expected_product_verdict")
        if expected is not None and expected != verdict:
            unexpected_verdicts.append(
                {"policy_id": pol["id"], "expected": expected, "actual": verdict})

        rows.append({
            "policy_id": pol["id"],
            "target": target,
            "synthetic": bool(pol.get("synthetic")),
            "case_type": ct,
            "dsl": rule.dsl,
            "atoms": list(preds),
            "atoms_in_vocabulary": sorted(alpha),
            "atoms_reachable": sorted(reach_alpha),
            "alphabet_only_prune": alpha_prune,
            "node_reachability_prune": reach_prune,
            "product_verdict": verdict,
            "product_certified": result.get("certified"),
            "product_inconclusive_reason": result.get("inconclusive_reason"),
            "path_sensitive_prune": product_prune,
            "runtime_only_prune": False,
            "incremental_over_alphabet": this_incr_alpha,
            "incremental_over_reachability": this_incr_reach,
            "soundness_no_violation": soundness_ok,
            "concrete_executions_checked": n_exec,
        })

    n_pairs = len(policies)
    curated_pairs = sum(1 for p in policies if not p.get("synthetic"))
    synthetic_pairs = n_pairs - curated_pairs

    summary = {
        "experiment": "monitor_pruning_path_sensitive",
        "reviewer_demand": "#8 (path-sensitive pruning beyond alphabet-only) / min experiment #9",
        "config": {
            "policies_file": str(POLICIES_PATH.relative_to(REPO)),
            "assume_trace_conservative": False,
            "note": (
                "Strategy (c) earns certification from provenance; curated "
                "graphs are all exact-provenance and synthetic fixtures are "
                "exact except the deliberate uncertified control."
            ),
            "soundness_bounds": {
                "max_node_visits": MAX_NODE_VISITS,
                "max_paths_per_graph": MAX_PATHS,
                "max_resolutions_per_path": MAX_RESOLUTIONS,
            },
        },
        "n_pairs": n_pairs,
        "n_curated_pairs": curated_pairs,
        "n_synthetic_pairs": synthetic_pairs,
        "strategies": {
            name: {"pruned": pruned[name], "kept": n_pairs - pruned[name]}
            for name in ("alphabet_only", "node_reachability",
                         "path_sensitive_product", "runtime_only")
        },
        "incremental": {
            "product_over_alphabet": incr_over_alpha,
            "product_over_reachability": incr_over_reach,
            "product_over_alphabet_curated": incr_alpha_curated,
            "product_over_alphabet_synthetic": incr_alpha_synthetic,
            "note": (
                "product_over_alphabet is THE headline: monitors the product "
                "proves inert that an alphabet-only check keeps. "
                "product_over_reachability isolates the cases needing genuine "
                "DFA/ordering reasoning (satisfied response/bounded obligations "
                "over reachable atoms), excluding declared-but-unreachable "
                "forbidden tools that node-reachability already prunes."
            ),
        },
        "false_pruning": {
            "product_pruned_pairs_checked": product_pruned_pairs,
            "concrete_executions_checked": total_executions_checked,
            "false_prunes": false_prunes,
            "sound": false_prunes == 0,
            "method": (
                "exhaustive bounded enumeration of finite maximal executions x "
                "concrete tool resolutions, replayed through evaluate_monitors + "
                "finalize_monitors; the static conservative model is a superset "
                "of these runtime-representable traces."
            ),
        },
        "certification_gate": {
            "controls": cert_gate_controls,
            "refused_to_prune_uncertified": all(
                not c["product_pruned_without_assertion"] for c in cert_gate_controls
            ) if cert_gate_controls else None,
            "would_be_safe_if_asserted": all(
                c["would_be_safe_if_asserted"] for c in cert_gate_controls
            ) if cert_gate_controls else None,
        },
        "per_case_type": {k: dict(v) for k, v in sorted(per_case_type.items())},
        "expected_verdict_mismatches": unexpected_verdicts,
        "results_table": rows,
    }

    OUTPUT_PATH.write_text(json.dumps(summary, indent=2))

    # ---- console summary ----
    line = "=" * 74
    print(line)
    print("PATH-SENSITIVE MONITOR PRUNING  (reviewer demand #8 / min experiment #9)")
    print(line)
    print(f"workflow-specific (workflow, policy) pairs: {n_pairs} "
          f"({curated_pairs} curated, {synthetic_pairs} synthetic)")
    print("  (every policy names an atom present in its target -> alphabet-only "
          "cannot prune it)")
    print()
    print("  strategy                    pruned   kept")
    print("  " + "-" * 42)
    for name, label in (("alphabet_only", "(a) alphabet-only"),
                        ("node_reachability", "(b) node-reachability"),
                        ("path_sensitive_product", "(c) path-sensitive PRODUCT"),
                        ("runtime_only", "(d) runtime-only")):
        print(f"  {label:26s} {pruned[name]:6d} {n_pairs - pruned[name]:6d}")
    print()
    print("  INCREMENTAL path-sensitive pruning (product proves inert, cheaper "
          "check does not):")
    print(f"    (c) over (a) alphabet-only     : {incr_over_alpha:3d}   "
          f"<== HEADLINE  (curated {incr_alpha_curated}, synthetic {incr_alpha_synthetic})")
    print(f"    (c) over (b) node-reachability : {incr_over_reach:3d}   "
          f"(cases needing DFA/ordering reasoning)")
    print()
    print(f"  SOUNDNESS: {total_executions_checked} concrete executions checked "
          f"over {product_pruned_pairs} pruned pairs -> false prunes = {false_prunes}")
    if cert_gate_controls:
        c = cert_gate_controls[0]
        print(f"  CERT GATE: uncertified control '{c['target']}' -> "
              f"verdict={c['verdict_without_assertion']} "
              f"(reason={c['inconclusive_reason']}), NOT pruned; "
              f"would be '{c['verdict_with_conservatism_asserted']}' if asserted")
    if unexpected_verdicts:
        print(f"  WARNING: expected-verdict mismatches: {unexpected_verdicts}")
    print()
    print("  per-case-type (pairs / product-pruned / incremental-over-alphabet):")
    for ct, d in sorted(per_case_type.items()):
        print(f"    {ct:30s} {d['pairs']:2d} / {d['product_pruned']:2d} / {d['incr_over_alpha']:2d}")
    print()
    print(f"written to {OUTPUT_PATH.relative_to(REPO)}")


if __name__ == "__main__":
    main()
