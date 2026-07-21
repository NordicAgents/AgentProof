#!/usr/bin/env python3
"""Symmetric decomposition of non-actionable findings (reviewer response).

The submitted paper claims "model extraction dominates static analysis of agent
workflows".  A reviewer objects that the study never estimates *check* error
symmetrically with *extraction* error: among the 186 triaged flags, 42% are
extraction artifacts but 50% are INTENTIONAL DESIGN, which is a property of the
policy/check, not of the extractor.

This script does three things.

1.  4-WAY ATTRIBUTION.  Every non-actionable flag is attributed to
    EXTRACTOR / CHECKER / POLICY-SPEC / LABEL under explicit mapping rules
    (see ATTRIBUTION below), overall and split by check and framework, with
    Wilson 95% CIs.

2.  SYMMETRIC ABLATION (the decisive experiment).  The same check suite is
    re-run on three graph populations over the SAME 119 workflows:
      v1   = original AST extraction        (corpus/real_world/graphs)
      v2   = corrected/pinned re-extraction (corpus/real_world/graphs_v2)
      GT   = LLM-reconstructed reference    (corpus/real_world/ground_truth)
    GT is treated as a near-perfect model.  Flags that SURVIVE on GT are the
    check/policy error floor: they cannot be blamed on the extractor because
    the extractor has been replaced by a (near-)oracle.  Flags that disappear
    when v1 -> GT are extraction-attributable.

3.  POLICY-HELD-CONSTANT CONTRAST.  The human-gate estimand is run under both
    the blunt policy (`human_presence`: any workflow without a human node) and
    the risk-aware policy (`human_gate_coverage`: only workflows binding a
    sensitive tool).  Holding the GRAPH fixed and varying the POLICY isolates
    policy-specification error; holding the POLICY fixed and varying the GRAPH
    isolates extraction error.  These two knobs are what make the comparison
    symmetric.

Output: corpus/real_world/error_decomposition.json
Run:    uv run python scripts/error_decomposition.py
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from agentproof.graph.model import graph_from_dict  # noqa: E402
from agentproof.verify import run_structural_checks  # noqa: E402
from risk_aware_gate import SENSITIVE_KEYWORDS  # noqa: E402

RW = ROOT / "corpus" / "real_world"
SELF_REPO_PREFIX = "NordicAgents__AgentProof"

STRUCTURAL_CHECKS = {
    "exit_reachability", "reverse_reachability", "dead_ends",
    "router_shape", "tool_declarations",
}

# Historical check-id aliases used by the first triage run, mapped onto the
# current check ids (this is the hand merge the claims audit flagged as R23).
CHECK_ALIAS = {
    "router-non-conditional-edges": "router_shape",
    "sensitive-path-bypasses-human-review": "human_gate_coverage",
}

# ---------------------------------------------------------------------------
# ATTRIBUTION TAXONOMY
# ---------------------------------------------------------------------------
# A finding is NON-ACTIONABLE if a maintainer would not change the workflow in
# response to it.  Each non-actionable finding gets exactly one attribution:
#
#   EXTRACTOR    the graph misrepresents the code; the finding is about an
#                edge/node/tool that does not exist (or a missing one that
#                does).  On a faithful graph the check would not fire.
#   CHECKER      the graph is faithful and the policy does apply, but the
#                check's decision procedure is wrong (unsound modelling
#                convention, wrong predicate, missing framework semantics).
#   POLICY-SPEC  the graph is faithful AND the check implements its own
#                specification correctly, but the specification does not apply
#                to this workflow (e.g. blunt "must contain a human node"
#                applied to a read-only tutorial).  The fix is to the policy,
#                not to the extractor or the checker.
#   LABEL        the triage judgement itself is disputed; a competent second
#                reviewer could call it either actionable or not.
#
# Mapping from the committed triage vocabulary:
#
#   extraction_artifact -> EXTRACTOR    (definitional; triage rationale is
#                                        always "this edge/node isn't in the
#                                        source")
#   intentional         -> POLICY-SPEC  (triage rationale is always "the code
#                                        is as modelled and the check fired
#                                        correctly, but this design is
#                                        deliberate / the requirement does not
#                                        apply here")
#   arguable            -> LABEL
#   real_defect         -> ACTIONABLE   (not part of the non-actionable
#                                        denominator)
#   gt_error (GT triage only) -> EXTRACTOR (the *reconstruction* misrepresents
#                                        the code; same error class, different
#                                        model producer)
#
# HONEST GAP, stated rather than papered over: the committed triage vocabulary
# has NO label that isolates CHECKER.  A checker bug is indistinguishable from
# POLICY-SPEC under the `intentional` label, because the triager was asked
# "is this a real defect?", not "whose fault is the flag?".  CHECKER is
# therefore reported as UNSEPARATED-IN-LABELS and bounded, not estimated: it is
# a subset of the POLICY-SPEC bucket.  One concrete instance is documented in
# the GT triage (the LangGraph implicit-END convention noted in the
# Brenmull12__Hoohacks2025__multiturn verification), which means the CHECKER
# share is > 0.  Both CHECKER and POLICY-SPEC lie on the *check* side of the
# extraction/check split, so the headline extraction-vs-check comparison is
# unaffected by the inability to split them.
ATTRIBUTION = {
    "extraction_artifact": "EXTRACTOR",
    "gt_error": "EXTRACTOR",
    "intentional": "POLICY_SPEC",
    "arguable": "LABEL",
    "real_defect": "ACTIONABLE",
}
CHECK_SIDE = {"CHECKER", "POLICY_SPEC"}


def wilson_ci(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def dist(labels: list[str], n: int) -> dict:
    c = Counter(labels)
    return {
        k: {"n": v, "pct": round(100 * v / n, 1), "wilson95": [round(100 * x, 1)
                                                               for x in wilson_ci(v, n)]}
        for k, v in sorted(c.items(), key=lambda kv: -kv[1])
    }


def slug_repo(slug: str) -> str:
    parts = slug.split("__")
    return parts[0] + "/" + parts[1] if len(parts) >= 2 else slug


def sensitive_tool_set(graphs) -> set[str]:
    keywords = [kw for kws in SENSITIVE_KEYWORDS.values() for kw in kws]
    out: set[str] = set()
    for g in graphs:
        for n in g.get("nodes", []):
            for t in n.get("tools", []) or []:
                if any(kw in t.lower() for kw in keywords):
                    out.add(t)
    return out


def run_suite(graphs: dict[str, dict], sensitive: set[str]) -> dict:
    """Run the full check suite over a population; return per-check flag counts."""
    flags: list[dict] = []
    per_workflow: dict[str, list[str]] = {}
    for slug, g in sorted(graphs.items()):
        report = run_structural_checks(
            graph_from_dict(g), require_human=True, sensitive_tools=sensitive)
        failed = [c["check_id"] for c in report["checks"] if not c["passed"]]
        per_workflow[slug] = failed
        for cid in failed:
            flags.append({"slug": slug, "check": cid})
    return {"flags": flags, "per_workflow": per_workflow}


def summarize(run: dict, n_wf: int) -> dict:
    by_check = Counter(f["check"] for f in run["flags"])
    struct = [f for f in run["flags"] if f["check"] in STRUCTURAL_CHECKS]
    return {
        "n_workflows": n_wf,
        "n_flags_total": len(run["flags"]),
        "flags_per_workflow": round(len(run["flags"]) / n_wf, 2),
        "by_check": dict(sorted(by_check.items(), key=lambda kv: -kv[1])),
        "n_structural_flags": len(struct),
        "n_workflows_with_structural_flag": len({f["slug"] for f in struct}),
        "n_workflows_human_presence": by_check.get("human_presence", 0),
        "n_workflows_human_gate_coverage": by_check.get("human_gate_coverage", 0),
    }


def main() -> None:
    validated = json.loads((RW / "validated_results.json").read_text())
    gt_triage = json.loads((RW / "gt_triage_results.json").read_text())

    gt_graphs = {p.stem: json.loads(p.read_text())
                 for p in sorted((RW / "ground_truth").glob("*.json"))
                 if not p.stem.startswith(SELF_REPO_PREFIX)}
    v1_all = {p.stem: json.loads(p.read_text())
              for p in sorted((RW / "graphs").glob("*.json"))}
    v2_all = {p.stem: json.loads(p.read_text())
              for p in sorted((RW / "graphs_v2").glob("*.json"))}

    fw = {s: g.get("framework") for s, g in v1_all.items()}
    for s, g in gt_graphs.items():
        fw.setdefault(s, g.get("framework"))

    # ---------------- 1. 4-way attribution over the 186 triaged flags -------
    triage = [t for t in validated["triage_details"]
              if not t["slug"].startswith(SELF_REPO_PREFIX)]
    for t in triage:
        t["check"] = CHECK_ALIAS.get(t["check"], t["check"])
        t["attribution"] = ATTRIBUTION[t["label"]]
        t["framework"] = fw.get(t["slug"], "unknown")

    n_all = len(triage)
    non_act = [t for t in triage if t["attribution"] != "ACTIONABLE"]
    n_non = len(non_act)

    decomposition = {
        "n_flags_triaged": n_all,
        "n_actionable": n_all - n_non,
        "n_non_actionable": n_non,
        "over_all_flags": dist([t["attribution"] for t in triage], n_all),
        "over_non_actionable": dist([t["attribution"] for t in non_act], n_non),
        "checker_note": (
            "CHECKER is not separable in the committed triage vocabulary; it is "
            "a subset of POLICY_SPEC. Its share is >0 (documented instance: the "
            "LangGraph implicit-END convention) but unquantified. Both are on "
            "the check side of the extraction/check split."),
    }

    by_check = defaultdict(list)
    for t in triage:
        by_check[t["check"]].append(t["attribution"])
    decomposition["by_check"] = {
        k: {"n_flags": len(v), **{"dist": dist(v, len(v))}}
        for k, v in sorted(by_check.items(), key=lambda kv: -len(kv[1]))
    }

    by_fw = defaultdict(list)
    for t in triage:
        by_fw[t["framework"]].append(t["attribution"])
    decomposition["by_framework"] = {
        k: {"n_flags": len(v), **{"dist": dist(v, len(v))}}
        for k, v in sorted(by_fw.items(), key=lambda kv: -len(kv[1]))
    }

    # Extraction-attributable share of non-actionable, per check family.
    fam = {}
    for name, sel in (
        ("structural", lambda t: t["check"] in STRUCTURAL_CHECKS),
        ("human_gate", lambda t: t["check"] in ("human_presence",
                                                "human_gate_coverage")),
    ):
        rows = [t for t in non_act if sel(t)]
        n = len(rows)
        ext = sum(1 for t in rows if t["attribution"] == "EXTRACTOR")
        chk = sum(1 for t in rows if t["attribution"] in CHECK_SIDE)
        fam[name] = {
            "n_non_actionable": n,
            "extractor": ext, "extractor_pct": round(100 * ext / n, 1),
            "extractor_wilson95": [round(100 * x, 1) for x in wilson_ci(ext, n)],
            "check_side": chk, "check_side_pct": round(100 * chk / n, 1),
            "check_side_wilson95": [round(100 * x, 1) for x in wilson_ci(chk, n)],
        }
    decomposition["by_check_family"] = fam

    # ---------------- 2. Symmetric ablation on the same files ---------------
    shared_gt_v1 = sorted(set(gt_graphs) & set(v1_all))
    shared_all = sorted(set(gt_graphs) & set(v1_all) & set(v2_all))
    sensitive = sensitive_tool_set(list(gt_graphs.values()))

    ab = {}
    ab["sensitive_tool_lexicon_hits_in_gt"] = sorted(sensitive)
    for pop, graphs, slugs in (
        ("v1_extracted", v1_all, shared_gt_v1),
        ("gt_reference", gt_graphs, shared_gt_v1),
    ):
        sub = {s: graphs[s] for s in slugs}
        ab[pop] = summarize(run_suite(sub, sensitive), len(slugs))
    ab["_matched_n"] = len(shared_gt_v1)

    ab["matched_116"] = {"_n": len(shared_all)}
    for pop, graphs in (("v1", v1_all), ("v2", v2_all), ("gt", gt_graphs)):
        sub = {s: graphs[s] for s in shared_all}
        ab["matched_116"][pop] = summarize(run_suite(sub, sensitive), len(shared_all))

    # Residual on a (near-)perfect graph, using the committed GT triage labels.
    gt_labels = [t["verify"].get("final_label", t["primary"]["label"])
                 for t in gt_triage["triage"]]
    gt_attr = [ATTRIBUTION[l] for l in gt_labels]
    ab["gt_flag_triage"] = {
        "n_triaged": len(gt_labels),
        "note": ("Only the non-human_presence GT flags were triaged (n=16); the "
                 "blunt human_presence firings on GT graphs were not re-triaged "
                 "because the same estimand was already triaged on v1."),
        "final_labels": dict(Counter(gt_labels)),
        "attribution": dist(gt_attr, len(gt_attr)),
    }

    # ---------------- 3. Policy-held-constant contrast ----------------------
    n_m = ab["_matched_n"]
    v1s, gts = ab["v1_extracted"], ab["gt_reference"]
    ab["contrast"] = {
        "graph_varied_policy_fixed": {
            "blunt_human_presence": {"v1": v1s["n_workflows_human_presence"],
                                     "gt": gts["n_workflows_human_presence"],
                                     "delta_from_extraction":
                                         v1s["n_workflows_human_presence"]
                                         - gts["n_workflows_human_presence"]},
            "risk_aware_human_gate": {"v1": v1s["n_workflows_human_gate_coverage"],
                                      "gt": gts["n_workflows_human_gate_coverage"],
                                      "delta_from_extraction":
                                          v1s["n_workflows_human_gate_coverage"]
                                          - gts["n_workflows_human_gate_coverage"]},
            "structural": {"v1": v1s["n_structural_flags"],
                           "gt": gts["n_structural_flags"],
                           "delta_from_extraction": v1s["n_structural_flags"]
                           - gts["n_structural_flags"]},
        },
        "policy_varied_graph_fixed": {
            "on_v1": {"blunt": v1s["n_workflows_human_presence"],
                      "risk_aware": v1s["n_workflows_human_gate_coverage"],
                      "delta_from_policy_spec":
                          v1s["n_workflows_human_presence"]
                          - v1s["n_workflows_human_gate_coverage"]},
            "on_gt": {"blunt": gts["n_workflows_human_presence"],
                      "risk_aware": gts["n_workflows_human_gate_coverage"],
                      "delta_from_policy_spec":
                          gts["n_workflows_human_presence"]
                          - gts["n_workflows_human_gate_coverage"]},
        },
    }

    total_v1 = v1s["n_flags_total"]
    total_gt = gts["n_flags_total"]
    ab["headline"] = {
        "n_workflows": n_m,
        "flags_on_v1_extraction": total_v1,
        "flags_on_perfect_graph": total_gt,
        "flags_removed_by_perfect_graph": total_v1 - total_gt,
        "extraction_attributable_share_of_flag_volume":
            round((total_v1 - total_gt) / total_v1, 3),
        "check_policy_residual_share_of_flag_volume":
            round(total_gt / total_v1, 3),
        "genuine_defects_found_on_perfect_graph": sum(
            1 for l in gt_labels if l == "real_defect"),
        "interpretation": (
            "Residual = flags that a PERFECT graph still produces. They are, by "
            "construction, not extraction error. Compare directly against "
            "flags_removed_by_perfect_graph."),
    }

    out = {
        "_meta": {
            "script": "scripts/error_decomposition.py",
            "purpose": ("symmetric extractor-vs-checker/policy attribution of "
                        "non-actionable findings (AAAI reviewer response)"),
            "inputs": ["validated_results.json", "gt_triage_results.json",
                       "graphs/", "graphs_v2/", "ground_truth/"],
            "attribution_rules": ATTRIBUTION,
            "check_aliases": CHECK_ALIAS,
        },
        "decomposition_186": decomposition,
        "symmetric_ablation": ab,
    }
    path = RW / "error_decomposition.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"decomposition_186": decomposition,
                      "headline": ab["headline"],
                      "contrast": ab["contrast"],
                      "v1": v1s, "gt": gts,
                      "matched_116": ab["matched_116"],
                      "gt_flag_triage": ab["gt_flag_triage"]}, indent=1))
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
