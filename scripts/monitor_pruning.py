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
graph whose paths OVER-approximate the workflow's runtime traces
(``Traces_event(P) subseteq L(G, lambda)``). That holds for the curated
corpus (graphs authored with the code) and for runtime-extracted graphs under
a no-dynamic-modification assumption; it does NOT hold for the lossy
AST-extracted mined graphs (edge recall 0.65), which under-approximate.

CERTIFIED-CONSERVATIVE GATE (reviewer fix #6): the checker now enforces this
premise itself. It emits a "safe" verdict ONLY when the explored region is
certified trace-conservative (every traversed edge and every visited TOOL
node is confidence=="exact"), OR when the caller asserts conservatism via
``assume_trace_conservative``. An uncertified would-be-safe run is returned as
``inconclusive`` / ``uncertified_extraction`` instead — so a lossy AST graph
can no longer yield a false "safe" proof.

Per-corpus caller policy:
  - CURATED corpus: graphs are authored-with-code and therefore
    conservative BY CONSTRUCTION, independent of per-element provenance
    tags. This script passes ``assume_trace_conservative=True`` for the
    curated corpus as an explicit CALLER ASSERTION. (Note: this preserves
    the pre-fix curated pruning counts exactly — the gate changes nothing on
    graphs the caller certifies.)
  - REAL-WORLD / mined corpus: NO assumption is passed; certification is
    earned only from ``exact`` provenance. On lossy graphs most would-be-safe
    runs therefore come back ``inconclusive`` / ``uncertified_extraction``,
    which is the sound outcome.

Given that premise: a monitor is pruned ONLY on a "safe" verdict (== a
CERTIFIED-safe verdict under the gate). We report the overall pruning rate
over corpus x policies, split into
  - trivially inert: the policy's atoms never appear in the workflow, and
  - reachability-proven inert: atoms appear, yet the product proves no
    violation path exists (the case where the product does real work),
and the kept monitors split into may-violate and inconclusive.

CERTIFIED-SAFE vs ALPHABET-INERT (descriptive): the output splits two
DISTINCT quantities. ``certified_safe`` is the number of monitor instances
the gate proves inert (the SOUND, prunable set). ``alphabet_inert_descriptive``
is the number whose policy atoms are simply ABSENT from the graph's declared
node/tool vocabulary — a provenance-INDEPENDENT descriptive statistic. On a
lossy graph alphabet-absence is NOT a sound pruning guarantee (a missing edge
could hide the atom), so ``alphabet_inert_descriptive`` is reported for
context only and MUST NOT be used to prune mined graphs; only
``certified_safe`` is prunable.

Usage:
    # mined / real-world (sound gate, no caller assumption):
    python scripts/monitor_pruning.py --corpus corpus/real_world/graphs \
        --policies corpus/policies/temporal_policies.json --corpus-kind real_world
    # curated (authored-with-code -> caller asserts conservatism):
    python scripts/monitor_pruning.py --corpus corpus/curated \
        --policies corpus/policies/temporal_policies.json --corpus-kind curated
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
    ap.add_argument(
        "--exclude-prefix", default=None,
        help=(
            "Skip graphs whose filename stem starts with this prefix. Use "
            "'NordicAgents__AgentProof' to apply the 8-file self-repo exclusion "
            "that revision_analyses.py applies via SELF_REPO_PREFIX. Without it "
            "this script globs all 930 mined graphs and reports 930x15=13950 "
            "monitor instances, which disagrees with the 922-workflow census."
        ),
    )
    ap.add_argument(
        "--corpus-kind", choices=["curated", "real_world"], default="real_world",
        help=(
            "curated: authored-with-code graphs -> assert trace-conservatism "
            "(assume_trace_conservative=True). real_world/mined: earn "
            "certification only from 'exact' provenance (the sound default)."
        ),
    )
    args = ap.parse_args()

    # Curated graphs are conservative BY CONSTRUCTION (authored with the
    # code), so the caller legitimately asserts trace-conservatism; mined
    # graphs must earn certification from provenance. See module docstring.
    assume_conservative = args.corpus_kind == "curated"

    policies = json.loads(Path(args.policies).read_text())
    compiled = []
    for p in policies:
        rule = compile_monitor_rule(MonitorRuleSpec(rule_id=p["id"], dsl=p["dsl"],
                                                    on_violation="block"))
        compiled.append((p, rule))

    graph_files = sorted(Path(args.corpus).glob("*.json"))
    n_excluded = 0
    if args.exclude_prefix:
        before = len(graph_files)
        graph_files = [g for g in graph_files
                       if not g.stem.startswith(args.exclude_prefix)]
        n_excluded = before - len(graph_files)
        print(f"[exclude] dropped {n_excluded} graph(s) matching "
              f"{args.exclude_prefix!r}: {before} -> {len(graph_files)}")
    n_pairs = 0
    prunable = 0
    trivial = 0            # prunable because atoms never appear
    reach_proven = 0       # prunable although atoms appear (product did real work)
    must_keep = 0          # kept monitors = may_violate + inconclusive
    may_violate = 0        # kept: some resolution violates the policy
    inconclusive = 0       # kept: checker cannot certify (must-keep, own category)
    # Soundness gate (fix #6) descriptive split:
    certified_safe = 0     # SOUND, prunable: gate returned a certified "safe"
    alphabet_inert_descriptive = 0   # DESCRIPTIVE: policy atoms absent from the
                                     # graph vocabulary, provenance-INDEPENDENT;
                                     # NOT a sound prune on lossy graphs
    uncertified_extraction = 0       # would-be-safe but extraction not certified
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
            # DESCRIPTIVE, provenance-independent: does the policy's alphabet
            # even touch the graph's declared node/tool vocabulary? On a
            # lossy graph this is NOT a sound prune (a missing edge could hide
            # the atom) -- reported for context only.
            if not atoms_present:
                alphabet_inert_descriptive += 1
            # Curated: caller asserts conservatism; mined: earn it from
            # provenance. The gate returns "safe" only when certified.
            result = check_temporal_property(
                graph, rule, assume_trace_conservative=assume_conservative
            )
            verdict = result.get("verdict")
            if verdict is None:
                # Robustness fallback for older checker builds that predate
                # the three-valued verdict: treat "not violated" as safe.
                verdict = "may_violate" if result.get("violated") else "safe"
            if verdict == "safe":
                # Gate invariant: a "safe" verdict is a CERTIFIED-safe verdict.
                certified_safe += 1
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
                    if result.get("inconclusive_reason") == "uncertified_extraction":
                        uncertified_extraction += 1
                else:
                    may_violate += 1
                    pp["may_violate"] += 1
        per_wf_pruned.append(wf_pruned)

    n_pol = len(compiled)
    # DESCRIPTIVE gap: alphabet-inert pairs that the gate did NOT certify as
    # safe (present only when certification is earned from provenance, i.e.
    # not asserted). On a lossy corpus this gap is exactly the set of monitors
    # a naive alphabet-only prune would UNSOUNDLY drop.
    alphabet_inert_not_certified = alphabet_inert_descriptive - trivial
    summary = {
        "corpus_kind": args.corpus_kind,
        "assume_trace_conservative": assume_conservative,
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
        # Soundness-gate split (reviewer fix #6). certified_safe is the SOUND,
        # prunable set (== "prunable" above under the gate invariant);
        # alphabet_inert_descriptive is a provenance-INDEPENDENT statistic and
        # is NOT a sound pruning guarantee on lossy graphs.
        "soundness_gate": {
            "certified_safe": certified_safe,
            "alphabet_inert_descriptive": alphabet_inert_descriptive,
            "alphabet_inert_not_certified": alphabet_inert_not_certified,
            "uncertified_extraction": uncertified_extraction,
            "note": (
                "certified_safe = SOUND prunable set (gate returned certified "
                "'safe'). alphabet_inert_descriptive = policy atoms absent from "
                "the declared graph vocabulary; DESCRIPTIVE ONLY, provenance-"
                "independent, and NOT a sound pruning guarantee on lossy graphs."
            ),
        },
        # Top-level mirror of the split for downstream readers.
        "certified_safe": certified_safe,
        "alphabet_inert_descriptive": alphabet_inert_descriptive,
        "per_policy": {k: v for k, v in per_policy.items()},
    }
    if args.exclude_prefix:
        summary["_excluded_prefix"] = args.exclude_prefix
        summary["_excluded_self_repo"] = n_excluded
    Path(args.output).write_text(json.dumps(summary, indent=2))

    print("=" * 62)
    print(f"MONITOR PRUNING [{args.corpus_kind}]: {len(graph_files)} workflows x {n_pol} policies = {n_pairs} monitor instances")
    print(f"  assume_trace_conservative (caller assertion): {assume_conservative}")
    print(f"  provably inert (prunable):     {prunable:5d}  ({summary['prunable_pct']}%)")
    print(f"    - trivially inert (no atoms): {trivial:5d}")
    print(f"    - reachability-proven inert:  {reach_proven:5d}  (atoms present, product proves safe)")
    print(f"  must keep:                     {must_keep:5d}  ({summary['must_keep_pct']}%)")
    print(f"    - may violate (monitor may fire): {may_violate:5d}")
    print(f"    - inconclusive (uncertifiable):   {inconclusive:5d}  ({summary['inconclusive_pct']}%)")
    print(f"        of which uncertified_extraction: {uncertified_extraction:5d}")
    print(f"  mean monitors pruned / workflow: {summary['mean_monitors_pruned_per_workflow']} of {n_pol}")
    print(f"  of monitors whose atoms DO appear, {summary['reach_proven_pct_of_atoms_present']}% still provably inert")
    print("  -- soundness split (fix #6) --")
    print(f"    certified_safe (SOUND, prunable):            {certified_safe:5d}")
    print(f"    alphabet_inert_descriptive (NOT sound prune):{alphabet_inert_descriptive:5d}")
    print(f"    alphabet-inert but NOT certified-safe:       {alphabet_inert_not_certified:5d}")
    print(f"\nWritten to {args.output}")


if __name__ == "__main__":
    main()
