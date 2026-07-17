"""Decisive decomposition (the panel's proposed re-analysis).

Hand-label the 12 distinct UNKNOWN-effect tool names and re-run. This separates
the TWO possible causes of the 0% strict certification rate:
  (a) effect-classifier artifact  -> labeling collapses UNKNOWN and lifts SAFE off 0
  (b) provenance/extraction constraint -> labeling collapses spurious may-candidates
      but strict certification STAYS ~0 (gated by lossy provenance, not effects)

Also measures the STRUCTURAL certifiability ceiling: how many applicable graphs
even have a fully-exact reachable region (the necessary condition for any SAFE
proof), independent of effects.
"""
import dataclasses
import glob
import json
import sys

sys.path.insert(0, "/home/midhun/Documents/MX/Research/AgentProof")

from agentproof.cegar.ir import EffectKind, MayMustGraph, UnsupportedKind, region_is_certifiable
from agentproof.cegar.product import check
from agentproof.cegar.ir import Verdict
from benchmarks.real_corpus.policies import POLICIES, lift_real, policy_alphabet_atoms

R, C = EffectKind.READ, EffectKind.COMMUNICATE
HAND_LABELS = {  # honest human judgment on the 12 unknown tool names
    "yt_tool": R, "blood_test_tool": R, "content_analyzer_tool": R, "serper_tool": R,
    "news_aggregator_tool": R, "legal_retrieval_tool": R, "investment_tool": R,
    "risk_tool": R, "pdf_tool": R, "occupancy_tool": R,
    "page_oncall": C,          # the one genuinely non-benign name -> communicate
    # "tool" (generic placeholder) intentionally left UNKNOWN — a human can't label it either
}


def relabel(mm: MayMustGraph) -> MayMustGraph:
    """Override tool-node effects from HAND_LABELS (mirrors lift_real's soundness
    rule: only drop INCOMPLETE_SCHEMA on non-exact nodes, never manufacture SAFE)."""
    for n in mm.nodes:
        if n.tool in HAND_LABELS and n.effect is EffectKind.UNKNOWN:
            eff = HAND_LABELS[n.tool]
            unsup = tuple(u for u in n.unsupported
                          if not (u.kind is UnsupportedKind.INCOMPLETE_SCHEMA and not n.provenance.is_exact))
            mm = mm.with_node(dataclasses.replace(n, effect=eff, unsupported=unsup))
    return mm


def region_all_exact(graph: MayMustGraph) -> bool:
    """Would the whole graph's reachable structure be provenance-certifiable if
    every effect were known? (necessary condition for any SAFE proof)."""
    return region_is_certifiable(
        graph, [n.id for n in graph.nodes],
        [(e.source, e.target) for e in graph.edges],
    )


def sweep(relabeled: bool):
    files = sorted(glob.glob("corpus/real_world/graphs_v2/**/*.json", recursive=True))
    safe = unsafe = unknown = maycand = applicable = 0
    for f in files:
        base = lift_real(json.load(open(f)))
        g = relabel(base) if relabeled else base
        for pid, pol, _ in POLICIES:
            r = check(g, pol)
            # applicable = policy alphabet present on some node (approx: any atom abstract-may-true)
            if r.verdict is Verdict.SAFE:
                safe += 1
            elif r.verdict is Verdict.UNSAFE:
                unsafe += 1
            else:
                unknown += 1
            if r.unknown_reason == "may_violation_candidate":
                maycand += 1
    return dict(safe=safe, unsafe=unsafe, unknown=unknown, may_candidates=maycand)


print("Decomposition: does effect-labeling move strict certification?\n" + "=" * 66)
before = sweep(relabeled=False)
after = sweep(relabeled=True)
print(f"{'metric':18s} {'baseline':>10s} {'hand-labeled':>12s}   delta")
for k in ("safe", "unsafe", "unknown", "may_candidates"):
    print(f"{k:18s} {before[k]:>10d} {after[k]:>12d}   {after[k]-before[k]:+d}")

# structural certifiability ceiling (effect-independent)
files = sorted(glob.glob("corpus/real_world/graphs_v2/**/*.json", recursive=True))
all_exact = sum(region_all_exact(lift_real(json.load(open(f)))) for f in files)
print("=" * 66)
print(f"graphs whose ENTIRE reachable structure is exact-provenance "
      f"(structural ceiling on certification): {all_exact}/{len(files)}")
print("=" * 66)
verdict = ("EFFECT-CLASSIFIER ARTIFACT" if after["safe"] > before["safe"]
           else "REAL PROVENANCE/EXTRACTION CONSTRAINT (labeling did NOT lift SAFE off 0)")
print("CONCLUSION:", verdict)
print(f"  may-candidates {before['may_candidates']} -> {after['may_candidates']} "
      f"({'collapsed: candidate count WAS an effect artifact' if after['may_candidates'] < before['may_candidates'] else 'unchanged'})")

json.dump({"before": before, "after": after, "structural_all_exact_graphs": all_exact,
           "n_graphs": len(files), "hand_labels": {k: v.value for k, v in HAND_LABELS.items()},
           "conclusion": verdict},
          open("scripts/cegar/results/decomposition.json", "w"), indent=2)
print("results -> scripts/cegar/results/decomposition.json")
