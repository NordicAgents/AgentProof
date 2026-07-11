#!/usr/bin/env python3
"""Monitor-pruning result: how many runtime monitors are provably inert?

For each (workflow, policy) pair we run the graph x DFA product construction
(agentproof.verify.temporal.check_temporal_property). Because the product
explores a *superset* of runtime paths, if it reaches no violation state the
policy can never be violated on that workflow at runtime -- so its monitor is
provably inert and can be pruned (skipped) before deployment. This is sound:
pruning never removes a monitor that could fire.

We report the overall pruning rate over the corpus x policies, split into
  - trivially inert: the policy's atoms never appear in the workflow, and
  - reachability-proven inert: atoms appear, yet the product proves no violation
    path exists (the case where the product construction does real work).

Multi-tool nodes are split into a chain of single-tool nodes first, so the
default (tools[0]) event mapper stays sound.

Usage:
    python scripts/monitor_pruning.py --corpus corpus/real_world/graphs \
        --policies corpus/policies/temporal_policies.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from agentproof.graph.model import graph_from_dict
from agentproof.monitor.ltl import MonitorRuleSpec, compile_monitor_rule
from agentproof.verify.temporal import check_temporal_property


def expand_multitool(g: dict) -> dict:
    """Split each tool node with >1 tool into a linear chain of single-tool
    nodes, preserving incoming/outgoing edges. Sound over-approximation of a
    node that invokes several tools in sequence."""
    remap_in: dict[str, str] = {}
    remap_out: dict[str, str] = {}
    out_nodes: list[dict] = []
    out_edges: list[dict] = []
    for n in g["nodes"]:
        tools = n.get("tools", []) or []
        if n["kind"] == "tool" and len(tools) > 1:
            subs = []
            for i, t in enumerate(tools):
                sid = f"{n['id']}__tool{i}"
                out_nodes.append({**n, "id": sid, "tools": [t]})
                subs.append(sid)
            for a, b in zip(subs, subs[1:]):
                out_edges.append({"source": a, "target": b, "kind": "direct"})
            remap_in[n["id"]] = subs[0]
            remap_out[n["id"]] = subs[-1]
        else:
            out_nodes.append(n)
            remap_in[n["id"]] = n["id"]
            remap_out[n["id"]] = n["id"]
    for e in g["edges"]:
        out_edges.append({**e,
                          "source": remap_out.get(e["source"], e["source"]),
                          "target": remap_in.get(e["target"], e["target"])})
    return {**g, "nodes": out_nodes, "edges": out_edges}


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
    must_keep = 0
    per_policy = defaultdict(lambda: {"pairs": 0, "prunable": 0, "reach_proven": 0, "keep": 0})
    per_wf_pruned = []     # how many of the N policies each workflow can prune

    for gf in graph_files:
        g = expand_multitool(json.loads(gf.read_text()))
        alpha = workflow_alphabet(g)
        graph = graph_from_dict(g)
        wf_pruned = 0
        for p, rule in compiled:
            n_pairs += 1
            per_policy[p["id"]]["pairs"] += 1
            atoms_present = any(a in alpha for a in rule.predicates)
            violated = check_temporal_property(graph, rule)["violated"]
            if not violated:
                prunable += 1
                wf_pruned += 1
                per_policy[p["id"]]["prunable"] += 1
                if atoms_present:
                    reach_proven += 1
                    per_policy[p["id"]]["reach_proven"] += 1
                else:
                    trivial += 1
            else:
                must_keep += 1
                per_policy[p["id"]]["keep"] += 1
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
    print(f"  must keep (monitor may fire):  {must_keep:5d}  ({summary['must_keep_pct']}%)")
    print(f"  mean monitors pruned / workflow: {summary['mean_monitors_pruned_per_workflow']} of {n_pol}")
    print(f"  of monitors whose atoms DO appear, {summary['reach_proven_pct_of_atoms_present']}% still provably inert")
    print(f"\nWritten to {args.output}")


if __name__ == "__main__":
    main()
