#!/usr/bin/env python3
"""Monitor-pruning result: how many runtime monitors are provably inert?

For each (workflow, policy) pair we run the graph x DFA product construction
(agentproof.verify.temporal.check_temporal_property). Its claim is scoped to
the FINITE MAXIMAL EXECUTIONS of the graph (entry to an exit node or a
dead end); infinite executions are out of scope. The checker returns a
three-valued verdict:

  - "safe"         -- no resolution of the graph's finite maximal executions
                      violates the policy (neither by bad prefix nor by
                      non-accepting termination); the monitor is provably
                      inert and can be pruned.
  - "may_violate"  -- some resolution violates it; the monitor must be kept.
  - "inconclusive" -- the finite-trace checker cannot certify the graph
                      (e.g. a divergent-obligation cycle, or no reachable
                      termination point); the monitor must be kept.

Multi-tool nodes need no pre-expansion: the checker's default event mapper
natively closes over every finite invocation sequence of a node's declared
tools -- all orders, all subsets, including the empty sequence -- so the
product conservatively over-approximates multi-tool behavior.

SOUNDNESS PREMISE (trace containment): pruning is sound only relative to a
graph whose paths OVER-approximate the workflow's runtime traces. That holds
for the curated corpus (graphs authored with the code) and for
runtime-extracted graphs under a no-dynamic-modification assumption; it does
NOT hold for the lossy AST-extracted mined graphs (edge recall 0.64), which
under-approximate. Do not use this script's verdicts to prune monitors for
AST-extracted graphs.

Given that premise: a monitor is pruned ONLY on a "safe" verdict. We report
the overall pruning rate over corpus x policies, split into
  - trivially inert: the policy's atoms never appear in the workflow, and
  - reachability-proven inert: atoms appear, yet the product proves no
    violation path exists (the case where the product does real work),
and the kept monitors split into may-violate and inconclusive.

Usage:
    python scripts/monitor_pruning.py --corpus corpus/real_world/graphs \
        --policies corpus/policies/temporal_policies.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from agentproof.graph.model import graph_from_dict
from agentproof.monitor.ltl import MonitorRuleSpec, compile_monitor_rule
from agentproof.verify.temporal import check_temporal_property


def workflow_alphabet(g: dict) -> set[str]:
    """Symbols a workflow can emit: tool:<t> for tool nodes, plus kind/tag labels."""
    alpha: set[str] = set()
    for n in g["nodes"]:
        for t in n.get("tools", []) or []:
            alpha.add(f"tool:{t}")
        alpha.add(n["kind"])            # action_type / kind label
        alpha.add({"tool": "tool", "llm": "llm_step", "human": "human",
                   "router": "router"}.get(n["kind"], n["kind"]))
    return alpha


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus/real_world/graphs")
    ap.add_argument("--policies", default="corpus/policies/temporal_policies.json")
    ap.add_argument("--output", default="corpus/real_world/monitor_pruning.json")
    args = ap.parse_args()

    policies = json.loads(Path(args.policies).read_text())
    compiled = []
    for p in policies:
        rule = compile_monitor_rule(MonitorRuleSpec(rule_id=p["id"], dsl=p["dsl"],
                                                    on_violation="block"))
        compiled.append((p, rule))

    graph_files = sorted(Path(args.corpus).glob("*.json"))
    n_pairs = 0
    prunable = 0
    trivial = 0            # prunable because atoms never appear
    reach_proven = 0       # prunable although atoms appear (product did real work)
    must_keep = 0          # kept monitors = may_violate + inconclusive
    may_violate = 0        # kept: some resolution violates the policy
    inconclusive = 0       # kept: checker cannot certify (must-keep, own category)
    per_policy = defaultdict(lambda: {"pairs": 0, "prunable": 0, "reach_proven": 0,
                                      "keep": 0, "may_violate": 0, "inconclusive": 0})
    per_wf_pruned = []     # how many of the N policies each workflow can prune

    for gf in graph_files:
        g = json.loads(gf.read_text())
        alpha = workflow_alphabet(g)
        graph = graph_from_dict(g)
        wf_pruned = 0
        for p, rule in compiled:
            n_pairs += 1
            pp = per_policy[p["id"]]
            pp["pairs"] += 1
            atoms_present = any(a in alpha for a in rule.predicates)
            result = check_temporal_property(graph, rule)
            verdict = result.get("verdict")
            if verdict is None:
                # Robustness fallback for older checker builds that predate
                # the three-valued verdict: treat "not violated" as safe.
                verdict = "may_violate" if result.get("violated") else "safe"
            if verdict == "safe":
                prunable += 1
                wf_pruned += 1
                pp["prunable"] += 1
                if atoms_present:
                    reach_proven += 1
                    pp["reach_proven"] += 1
                else:
                    trivial += 1
            else:
                # Anything not proven safe is conservatively kept.
                must_keep += 1
                pp["keep"] += 1
                if verdict == "inconclusive":
                    inconclusive += 1
                    pp["inconclusive"] += 1
                else:
                    may_violate += 1
                    pp["may_violate"] += 1
        per_wf_pruned.append(wf_pruned)

    n_pol = len(compiled)
    summary = {
        "n_workflows": len(graph_files),
        "n_policies": n_pol,
        "n_monitor_instances": n_pairs,
        "prunable": prunable,
        "prunable_pct": round(prunable * 100 / n_pairs, 1) if n_pairs else 0,
        "trivially_inert": trivial,
        "reachability_proven_inert": reach_proven,
        "must_keep": must_keep,
        "must_keep_pct": round(must_keep * 100 / n_pairs, 1) if n_pairs else 0,
        "may_violate": may_violate,
        "inconclusive": inconclusive,
        "inconclusive_pct": round(inconclusive * 100 / n_pairs, 1) if n_pairs else 0,
        "reach_proven_pct_of_atoms_present": round(
            reach_proven * 100 / (reach_proven + must_keep), 1) if (reach_proven + must_keep) else 0,
        "mean_monitors_pruned_per_workflow": round(sum(per_wf_pruned) / len(per_wf_pruned), 2) if per_wf_pruned else 0,
        "per_policy": {k: v for k, v in per_policy.items()},
    }
    Path(args.output).write_text(json.dumps(summary, indent=2))

    print("=" * 62)
    print(f"MONITOR PRUNING: {len(graph_files)} workflows x {n_pol} policies = {n_pairs} monitor instances")
    print(f"  provably inert (prunable):     {prunable:5d}  ({summary['prunable_pct']}%)")
    print(f"    - trivially inert (no atoms): {trivial:5d}")
    print(f"    - reachability-proven inert:  {reach_proven:5d}  (atoms present, product proves safe)")
    print(f"  must keep:                     {must_keep:5d}  ({summary['must_keep_pct']}%)")
    print(f"    - may violate (monitor may fire): {may_violate:5d}")
    print(f"    - inconclusive (uncertifiable):   {inconclusive:5d}  ({summary['inconclusive_pct']}%)")
    print(f"  mean monitors pruned / workflow: {summary['mean_monitors_pruned_per_workflow']} of {n_pol}")
    print(f"  of monitors whose atoms DO appear, {summary['reach_proven_pct_of_atoms_present']}% still provably inert")
    print(f"\nWritten to {args.output}")


if __name__ == "__main__":
    main()
