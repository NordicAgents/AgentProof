#!/usr/bin/env python3
"""Sensitivity analyses for the real-world corpus study (research plan §3.5).

Implements the §3.5 items computable from EXISTING committed artifacts:

1. Dedup sensitivity (plan item 1): recompute every headline corpus-level
   rate after dropping the redundant members of the 48 cross-repository
   duplicate-topology groups (170 redundant workflows), keeping one
   representative per group. Reported side by side with the original rates.
2. Repository weighting (plan item 2): the same headline rates weighting
   each repository equally (mean of per-repo rates) beside the
   workflow-weighted pooled rates, plus a repo-level ">=1 firing" variant
   that admits a Wilson CI.
3. Unknown-as-positive bound (plan item 5): recompute genuine-defect counts
   on the validated sample counting every 'arguable' triage label and every
   unresolved (primary/verify disagreement) ground-truth-pass label
   pessimistically as genuine; upper-bound prevalence with Wilson CIs beside
   the primary estimates.
4. Application-only stratum (plan item 3): reproduce the paper's Table 3
   stratified prevalence (3/39 application-like vs 1/80 tutorials/demos/
   tests) from the artifacts, and add dedup + repository-weighted variants
   of the stratified rates.

Inputs (all under corpus/real_world/, all read-only):
    graphs/*.json            mined AST-extracted graphs (930 incl. self-repo)
    ground_truth/*.json      sample membership (120 incl. self-repo)
    defect_results.json      per-workflow check results on mined graphs
    validated_results.json   adversarial triage of extractor-visible flags
    gt_triage_results.json   triage of ground-truth-graph flags + source-level
                             workflow classification (application_like etc.)
    revision_analyses.json   prior revision analyses (duplicate-group census,
                             per-workflow ground-truth flag rows)
    risk_aware_gate.json     risk-aware gate result on mined graphs

Output: corpus/real_world/sensitivity_analyses.json plus a printed summary.

Deterministic (no RNG; Wilson score intervals only, mirroring
scripts/compute_cis.py), fully offline, pure standard library.

Usage:
    .venv/bin/python scripts/sensitivity_analyses.py
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RW = ROOT / "corpus" / "real_world"
sys.path.insert(0, str(ROOT / "scripts"))

from risk_aware_gate import SENSITIVE_KEYWORDS  # noqa: E402

SELF_REPO_PREFIX = "NordicAgents__AgentProof"
Z = 1.96  # 95%

# Source-level classification buckets (gt_triage_results.json).
APPLICATION_CATEGORY = "application_like"
NON_APPLICATION_CATEGORIES = ("tutorial_or_example", "demo_or_toy", "test")


# --------------------------------------------------------------------------
# Statistics (mirrors compute_cis.py / revision_analyses.py — no new deps)
# --------------------------------------------------------------------------

def wilson(k: int, n: int) -> dict:
    """Wilson score interval, as in compute_cis.py. Percent units."""
    if n == 0:
        return {"k": k, "n": n, "pct": None, "ci95_pct": [None, None]}
    p = k / n
    denom = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / denom
    half = (Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))) / denom
    lo = max(0.0, center - half)
    hi = min(1.0, center + half)
    return {
        "k": k,
        "n": n,
        "pct": round(p * 100, 2),
        "ci95_pct": [round(lo * 100, 2), round(hi * 100, 2)],
    }


# --------------------------------------------------------------------------
# Helpers shared with revision_analyses.py (copied verbatim for determinism)
# --------------------------------------------------------------------------

def slug_repo(slug: str) -> str:
    parts = slug.split("__")
    return parts[0] + "/" + parts[1] if len(parts) >= 2 else slug


def canon(g: dict) -> str:
    """Canonical topology serialization: the identity notion behind the
    paper's 48-group / 170-redundant-workflow duplicate census (the raw JSON
    files are never byte-identical because each embeds its own slug)."""
    nodes = tuple(sorted((n["id"], n.get("kind", "")) for n in g["nodes"]))
    edges = tuple(sorted((e["source"], e["target"], e.get("kind", ""))
                         for e in g["edges"]))
    return json.dumps([nodes, edges])


def duplicate_groups(slugs: list[str], graphs: dict[str, dict]) -> list[list[str]]:
    """Cross-repository duplicate-topology groups with >3 nodes — exactly the
    definition used by revision_analyses.py for the paper's census."""
    by_canon: dict[str, list[str]] = defaultdict(list)
    for s in slugs:
        by_canon[canon(graphs[s])].append(s)
    groups = []
    for k, v in sorted(by_canon.items()):
        if len({slug_repo(s) for s in v}) > 1 and len(json.loads(k)[0]) > 3:
            groups.append(sorted(v))
    return groups


def drop_redundant(slugs: list[str], groups: list[list[str]]) -> list[str]:
    """Keep the lexicographically smallest member of each duplicate group."""
    dropped: set[str] = set()
    for g in groups:
        dropped.update(g[1:])
    return [s for s in slugs if s not in dropped]


# --------------------------------------------------------------------------
# Headline corpus-level rates on the mined corpus
# --------------------------------------------------------------------------

def sensitive_tool_present(g: dict) -> bool:
    keywords = [kw for kws in SENSITIVE_KEYWORDS.values() for kw in kws]
    for n in g.get("nodes", []):
        for t in n.get("tools", []) or []:
            low = t.lower()
            if any(kw in low for kw in keywords):
                return True
    return False


def corpus_rates(slugs: list[str], details: dict[str, dict],
                 graphs: dict[str, dict]) -> dict:
    n = len(slugs)
    k_any = sum(1 for s in slugs if details[s]["defects"])
    k_struct = sum(1 for s in slugs
                   if any(d["category"] == "structural"
                          for d in details[s]["defects"]))
    k_hp = sum(1 for s in slugs
               if any(d["check"] == "human_presence"
                      for d in details[s]["defects"]))
    k_sensitive = sum(1 for s in slugs if sensitive_tool_present(graphs[s]))
    total_flags = sum(len(details[s]["defects"]) for s in slugs)
    per_check = Counter(d["check"] for s in slugs for d in details[s]["defects"])
    return {
        "n_workflows": n,
        "n_repos": len({slug_repo(s) for s in slugs}),
        "total_flags": total_flags,
        "flags_per_workflow": round(total_flags / n, 3) if n else None,
        "any_flag": wilson(k_any, n),
        "structural_flag": wilson(k_struct, n),
        "human_presence_flag": wilson(k_hp, n),
        # No mined graph declares a sensitive tool binding (the artifact's
        # risk_aware_gate.json result), so the risk-aware gate fires on 0
        # workflows in every subset; recomputed here rather than assumed.
        "workflows_with_sensitive_tool_binding": k_sensitive,
        "risk_aware_gate_flag": wilson(
            sum(1 for s in slugs
                if any(d["check"] == "human_gate_coverage"
                       for d in details[s]["defects"])), n),
        "flags_by_check": dict(sorted(per_check.items())),
    }


def repo_weighted_rates(slugs: list[str], details: dict[str, dict]) -> dict:
    """Each repository weighted equally: mean of per-repo firing fractions,
    plus the repo-level '>=1 flagged workflow' proportion (Wilson-CI-able)."""
    preds = {
        "any_flag": lambda s: bool(details[s]["defects"]),
        "structural_flag": lambda s: any(
            d["category"] == "structural" for d in details[s]["defects"]),
        "human_presence_flag": lambda s: any(
            d["check"] == "human_presence" for d in details[s]["defects"]),
    }
    by_repo: dict[str, list[str]] = defaultdict(list)
    for s in slugs:
        by_repo[slug_repo(s)].append(s)
    n_repos = len(by_repo)
    out: dict = {"n_repos": n_repos}
    for name, pred in preds.items():
        per_repo = [sum(1 for s in members if pred(s)) / len(members)
                    for _, members in sorted(by_repo.items())]
        k_repo_any = sum(1 for _, members in sorted(by_repo.items())
                         if any(pred(s) for s in members))
        out[name] = {
            "repo_weighted_mean_pct": round(
                100 * sum(per_repo) / n_repos, 2) if n_repos else None,
            "repos_with_ge1_firing": wilson(k_repo_any, n_repos),
        }
    # flags per workflow, repo-weighted: mean over repos of per-repo mean
    per_repo_fpw = [sum(len(details[s]["defects"]) for s in members) / len(members)
                    for _, members in sorted(by_repo.items())]
    out["flags_per_workflow_repo_weighted"] = round(
        sum(per_repo_fpw) / n_repos, 3) if n_repos else None
    return out


# --------------------------------------------------------------------------
# Sample-level (labelled) prevalence
# --------------------------------------------------------------------------

def prevalence_block(slugs: list[str], genuine: set[str],
                     category: dict[str, str]) -> dict:
    """Prevalence estimates on a labelled slug set, pooled + stratified."""
    slug_set = set(slugs)
    k = len(genuine & slug_set)
    repos = {slug_repo(s) for s in slugs}
    repos_genuine = {slug_repo(s) for s in genuine & slug_set}
    app = [s for s in slugs if category.get(s) == APPLICATION_CATEGORY]
    non_app = [s for s in slugs if category.get(s) in NON_APPLICATION_CATEGORIES]
    return {
        "per_workflow": wilson(k, len(slugs)),
        "per_repository": wilson(len(repos_genuine), len(repos)),
        "application_like_only": wilson(len(genuine & set(app)), len(app)),
        "tutorials_demos_tests": wilson(len(genuine & set(non_app)), len(non_app)),
        "genuine_slugs_in_scope": sorted(genuine & slug_set),
    }


def repo_weighted_prevalence(slugs: list[str], genuine: set[str],
                             category: dict[str, str]) -> dict:
    """Mean of per-repo genuine fractions (each repo weighted equally),
    pooled and restricted to the application-like / non-application strata."""
    def mean_of_repo_rates(subset: list[str]) -> dict:
        by_repo: dict[str, list[str]] = defaultdict(list)
        for s in subset:
            by_repo[slug_repo(s)].append(s)
        if not by_repo:
            return {"n_repos": 0, "repo_weighted_mean_pct": None}
        rates = [sum(1 for s in m if s in genuine) / len(m)
                 for _, m in sorted(by_repo.items())]
        return {
            "n_repos": len(by_repo),
            "repo_weighted_mean_pct": round(100 * sum(rates) / len(rates), 2),
        }
    return {
        "pooled": mean_of_repo_rates(list(slugs)),
        "application_like_only": mean_of_repo_rates(
            [s for s in slugs if category.get(s) == APPLICATION_CATEGORY]),
        "tutorials_demos_tests": mean_of_repo_rates(
            [s for s in slugs if category.get(s) in NON_APPLICATION_CATEGORIES]),
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    # ---- load artifacts -------------------------------------------------
    graphs = {p.stem: json.loads(p.read_text())
              for p in sorted((RW / "graphs").glob("*.json"))}
    defect_results = json.loads((RW / "defect_results.json").read_text())
    details = {d["name"]: d for d in defect_results["details"]}
    validated = json.loads((RW / "validated_results.json").read_text())
    gt_triage = json.loads((RW / "gt_triage_results.json").read_text())
    revision = json.loads((RW / "revision_analyses.json").read_text())
    risk_gate = json.loads((RW / "risk_aware_gate.json").read_text())
    sample_all = sorted(p.stem for p in (RW / "ground_truth").glob("*.json"))

    mined_kept = [s for s in sorted(graphs) if not s.startswith(SELF_REPO_PREFIX)]
    sample = [s for s in sample_all if not s.startswith(SELF_REPO_PREFIX)]
    category = {c["slug"]: c["category"] for c in gt_triage["classification"]}

    # ---- 1. dedup sensitivity on the mined corpus -----------------------
    groups = duplicate_groups(mined_kept, graphs)
    n_redundant = sum(len(g) - 1 for g in groups)
    mined_dedup = drop_redundant(mined_kept, groups)

    census_expected = revision["composition"]
    census_match = (
        len(groups) == census_expected["duplicate_topology_groups_gt3_nodes"]
        and n_redundant == census_expected["duplicate_topology_extra_workflows"])

    original_rates = corpus_rates(mined_kept, details, graphs)
    dedup_rates = corpus_rates(mined_dedup, details, graphs)

    # ---- 2. repository weighting ----------------------------------------
    repo_weighted_original = repo_weighted_rates(mined_kept, details)
    repo_weighted_dedup = repo_weighted_rates(mined_dedup, details)

    # ---- labelled genuine-defect sets (extractor-visible + GT pass) -----
    triage_details = [t for t in validated["triage_details"]
                      if not t["slug"].startswith(SELF_REPO_PREFIX)]
    extractor_real = {t["slug"] for t in triage_details
                      if t["label"] == "real_defect"}
    extractor_arguable = {t["slug"] for t in triage_details
                          if t["label"] == "arguable"}
    gt_real = {t["slug"] for t in gt_triage["triage"]
               if t["verify"]["final_label"] == "real_defect"}
    gt_unresolved = {t["slug"] for t in gt_triage["triage"]
                     if not t["verify"]["agree"]}
    combined_real = extractor_real | gt_real
    combined_upper = combined_real | extractor_arguable | gt_unresolved

    # ---- 4. application-only stratum: reproduce + variants --------------
    primary = prevalence_block(sample, combined_real, category)
    primary["extractor_visible_per_workflow"] = wilson(
        len(extractor_real & set(sample)), len(sample))

    # dedup variant: same duplicate rule applied within the labelled sample
    sample_groups = duplicate_groups(sample, graphs)
    sample_dedup = drop_redundant(sample, sample_groups)
    dedup_prev = prevalence_block(sample_dedup, combined_real, category)
    dedup_prev["extractor_visible_per_workflow"] = wilson(
        len(extractor_real & set(sample_dedup)), len(sample_dedup))

    # strict dedup variant: drop ANY within-sample topology duplicate
    # (same-repo and small graphs included), for completeness
    by_canon_strict: dict[str, list[str]] = defaultdict(list)
    for s in sample:
        by_canon_strict[canon(graphs[s])].append(s)
    strict_groups = [sorted(v) for _, v in sorted(by_canon_strict.items())
                     if len(v) > 1]
    sample_dedup_strict = drop_redundant(sample, strict_groups)
    strict_prev = prevalence_block(sample_dedup_strict, combined_real, category)

    repo_weighted_prev = repo_weighted_prevalence(sample, combined_real, category)
    repo_weighted_prev_dedup = repo_weighted_prevalence(
        sample_dedup, combined_real, category)

    # ground-truth-graph flag rates (from revision_analyses per_workflow
    # rows): dedup + repo-weighted variants of the GT estimand
    gt_rows = {r["slug"]: r for r in revision["prevalence_gt"]["per_workflow"]}

    def gt_flag_rates(slugs: list[str]) -> dict:
        n = len(slugs)
        k_struct = sum(1 for s in slugs if gt_rows[s]["failed_structural"])
        k_gate = sum(1 for s in slugs if gt_rows[s]["human_gate_coverage_failed"])
        k_hp = sum(1 for s in slugs if gt_rows[s]["human_presence_failed"])
        return {
            "structural_flag": wilson(k_struct, n),
            "risk_aware_gate_flag": wilson(k_gate, n),
            "human_presence_flag": wilson(k_hp, n),
        }

    def gt_flag_rates_repo_weighted(slugs: list[str]) -> dict:
        by_repo: dict[str, list[str]] = defaultdict(list)
        for s in slugs:
            by_repo[slug_repo(s)].append(s)
        out = {"n_repos": len(by_repo)}
        for name, key in [("structural_flag", "failed_structural"),
                          ("risk_aware_gate_flag", "human_gate_coverage_failed"),
                          ("human_presence_flag", "human_presence_failed")]:
            rates = [sum(1 for s in m if gt_rows[s][key]) / len(m)
                     for _, m in sorted(by_repo.items())]
            out[name] = {"repo_weighted_mean_pct":
                         round(100 * sum(rates) / len(rates), 2)}
        return out

    # ---- 3. unknown-as-positive bound ------------------------------------
    n_flags = len(triage_details)
    n_gt_flags = len(gt_triage["triage"])
    upper_prev = prevalence_block(sample, combined_upper, category)
    upper_extractor = wilson(
        len((extractor_real | extractor_arguable) & set(sample)), len(sample))
    unknown_as_positive = {
        "definition": (
            "Pessimistic bound: every 'arguable' label in the extractor-flag "
            "triage and every unresolved ground-truth-pass flag (primary/"
            "verify disagreement) is counted as a genuine defect. Primary "
            "estimates count only 'real_defect' labels."),
        "flag_level_ppv": {
            "extractor_visible_flags": {
                "primary": wilson(
                    sum(1 for t in triage_details
                        if t["label"] == "real_defect"), n_flags),
                "upper_bound": wilson(
                    sum(1 for t in triage_details
                        if t["label"] in ("real_defect", "arguable")), n_flags),
                "label_distribution": dict(sorted(Counter(
                    t["label"] for t in triage_details).items())),
            },
            "ground_truth_pass_flags": {
                "primary": wilson(
                    sum(1 for t in gt_triage["triage"]
                        if t["verify"]["final_label"] == "real_defect"),
                    n_gt_flags),
                "upper_bound": wilson(
                    sum(1 for t in gt_triage["triage"]
                        if t["verify"]["final_label"] == "real_defect"
                        or not t["verify"]["agree"]), n_gt_flags),
                "final_label_distribution": dict(sorted(Counter(
                    t["verify"]["final_label"]
                    for t in gt_triage["triage"]).items())),
                "n_unresolved_disagreements": len(gt_unresolved),
            },
        },
        "workflow_level_prevalence": {
            "primary_extractor_visible": primary["extractor_visible_per_workflow"],
            "upper_extractor_visible": upper_extractor,
            "primary_combined": primary["per_workflow"],
            "upper_combined": upper_prev["per_workflow"],
            "upper_combined_per_repository": upper_prev["per_repository"],
            "upper_combined_application_like_only":
                upper_prev["application_like_only"],
            "upper_combined_tutorials_demos_tests":
                upper_prev["tutorials_demos_tests"],
            "upper_bound_slugs": sorted(combined_upper & set(sample)),
        },
    }

    # ---- material-change assessment (soft gate, plan §3.7) --------------
    def delta_pp(a: dict, b: dict) -> float:
        return round(b["pct"] - a["pct"], 2)

    material = {
        "criterion": (
            "'Material' = the alternative point estimate falls outside the "
            "primary estimate's Wilson 95% CI."),
        "headline_estimates": {}
    }
    for name in ("any_flag", "structural_flag", "human_presence_flag"):
        orig = original_rates[name]
        ded = dedup_rates[name]
        rw = repo_weighted_original[name]["repo_weighted_mean_pct"]
        lo, hi = orig["ci95_pct"]
        material["headline_estimates"][name] = {
            "original_pct": orig["pct"],
            "dedup_pct": ded["pct"],
            "dedup_delta_pp": delta_pp(orig, ded),
            "dedup_material": not (lo <= ded["pct"] <= hi),
            "repo_weighted_pct": rw,
            "repo_weighted_delta_pp": round(rw - orig["pct"], 2),
            "repo_weighted_material": not (lo <= rw <= hi),
        }
    material["headline_estimates"]["flags_per_workflow"] = {
        "original": original_rates["flags_per_workflow"],
        "dedup": dedup_rates["flags_per_workflow"],
        "repo_weighted": repo_weighted_original[
            "flags_per_workflow_repo_weighted"],
    }
    prim_pw, ded_pw = primary["per_workflow"], dedup_prev["per_workflow"]
    material["headline_estimates"]["genuine_prevalence_per_workflow"] = {
        "original_pct": prim_pw["pct"],
        "dedup_pct": ded_pw["pct"],
        "dedup_delta_pp": delta_pp(prim_pw, ded_pw),
        "dedup_material": not (prim_pw["ci95_pct"][0] <= ded_pw["pct"]
                               <= prim_pw["ci95_pct"][1]),
        "repo_weighted_pct":
            repo_weighted_prev["pooled"]["repo_weighted_mean_pct"],
    }

    # ---- gaps ------------------------------------------------------------
    gaps = [
        {
            "item": "byte-identity definition",
            "detail": (
                "The paper calls the 48 duplicate groups 'byte-identical', "
                "but raw graph-JSON files are never byte-identical (each "
                "embeds its own slug in the 'name' field): byte-hashing the "
                "files yields 0 duplicate groups. The 48/170 census matches "
                "the canonical-topology identity computed in "
                "revision_analyses.py (sorted node id/kind + edge triples, "
                "cross-repository, >3 nodes), which is the definition "
                "reproduced here. The paper's wording should say "
                "'topologically identical' (or byte-identical canonical "
                "serialization)."),
        },
        {
            "item": "dedup/upper-bound prevalence on the full mined corpus",
            "detail": (
                "Genuine/arguable labels exist only for the 119-workflow "
                "validated sample; corpus-wide (922) prevalence variants are "
                "not computable from existing artifacts."),
        },
        {
            "item": "plan §3.5 item 4 (human-label-only sensitivity)",
            "detail": (
                "Not in scope of this script and not computable from these "
                "artifacts alone: triage labels in validated_results.json / "
                "gt_triage_results.json are LLM-adversarial labels without a "
                "parallel human-adjudicated label per flag "
                "(corpus/annotations/ holds worksheets, not per-flag "
                "adjudications)."),
        },
        {
            "item": "repo-weighted mean CIs",
            "detail": (
                "The equal-repo-weight mean of per-repo rates is not a "
                "binomial proportion, so no Wilson CI is attached; the "
                "repo-level '>=1 firing' proportion is reported with a "
                "Wilson CI as the CI-able repo-weighted variant. Cluster-"
                "bootstrap CIs for the pooled estimates already exist in "
                "revision_analyses.json."),
        },
    ]

    # ---- consistency checks against committed artifacts ------------------
    consistency = {
        "duplicate_census_matches_revision_analyses": census_match,
        "recomputed_groups": len(groups),
        "recomputed_redundant_workflows": n_redundant,
        "human_presence_pct_on_930_matches_defect_results": (
            defect_results["defects_by_type"]["human_presence"] == 846
            and risk_gate["naive_human_gate_flags"] == 846),
        "no_sensitive_tool_in_mined_graphs_matches_risk_aware_gate": (
            original_rates["workflows_with_sensitive_tool_binding"] == 0
            and risk_gate["workflows_with_sensitive_tool"] == 0),
        "extractor_visible_genuine_k": len(extractor_real & set(sample)),
        "combined_genuine_k": len(combined_real & set(sample)),
        "paper_table3_rows_reproduced": {
            "combined_per_workflow_4_of_119":
                primary["per_workflow"]["k"] == 4
                and primary["per_workflow"]["n"] == 119,
            "per_repository_4_of_87":
                primary["per_repository"]["k"] == 4
                and primary["per_repository"]["n"] == 87,
            "application_like_3_of_39":
                primary["application_like_only"]["k"] == 3
                and primary["application_like_only"]["n"] == 39,
            "tutorials_demos_tests_1_of_80":
                primary["tutorials_demos_tests"]["k"] == 1
                and primary["tutorials_demos_tests"]["n"] == 80,
        },
    }

    out = {
        "meta": {
            "script": "scripts/sensitivity_analyses.py",
            "purpose": "Research-plan §3.5 sensitivity analyses "
                       "(items 1, 2, 3, 5) from existing artifacts only",
            "self_repo_exclusion": SELF_REPO_PREFIX,
            "n_mined_workflows_after_exclusion": len(mined_kept),
            "n_sample_workflows_after_exclusion": len(sample),
            "ci_method": "Wilson score, z=1.96 (as compute_cis.py)",
            "consistency_checks": consistency,
        },
        "dedup_sensitivity": {
            "duplicate_definition": (
                "Identical canonical topology (sorted (node id, kind) + "
                "(source, target, kind) edge triples) shared across >1 "
                "repository, graphs with >3 nodes; one lexicographically "
                "smallest representative kept per group. Matches "
                "revision_analyses.py."),
            "n_duplicate_groups": len(groups),
            "n_redundant_workflows_dropped": n_redundant,
            "n_repos_losing_all_workflows":
                original_rates["n_repos"] - dedup_rates["n_repos"],
            "corpus_rates": {
                "original": original_rates,
                "deduplicated": dedup_rates,
            },
            "duplicate_groups": groups,
        },
        "repository_weighting": {
            "note": ("Workflow-weighted pooled rates are in "
                     "dedup_sensitivity.corpus_rates; here each repository "
                     "is weighted equally."),
            "original_corpus": repo_weighted_original,
            "deduplicated_corpus": repo_weighted_dedup,
        },
        "unknown_as_positive": unknown_as_positive,
        "application_stratum": {
            "classification_source": "gt_triage_results.json:classification "
                                     "(source-level, 119 sampled workflows)",
            "category_counts": dict(sorted(Counter(
                category[s] for s in sample).items())),
            "primary": primary,
            "dedup_variant": {
                "rule": "same duplicate definition applied within the sample",
                "n_groups": len(sample_groups),
                "n_dropped": len(sample) - len(sample_dedup),
                "rates": dedup_prev,
            },
            "strict_dedup_variant": {
                "rule": "drop any within-sample topology duplicate "
                        "(same-repo and <=3-node graphs included)",
                "n_dropped": len(sample) - len(sample_dedup_strict),
                "rates": strict_prev,
            },
            "repo_weighted_variant": repo_weighted_prev,
            "repo_weighted_dedup_variant": repo_weighted_prev_dedup,
            "ground_truth_flag_rates": {
                "original": gt_flag_rates(sample),
                "dedup": gt_flag_rates(sample_dedup),
                "repo_weighted": gt_flag_rates_repo_weighted(sample),
            },
        },
        "material_change_assessment": material,
        "gaps": gaps,
    }

    out_path = RW / "sensitivity_analyses.json"
    out_path.write_text(json.dumps(out, indent=2) + "\n")

    # ---- printed summary table -------------------------------------------
    def fmt(w: dict) -> str:
        return f"{w['k']}/{w['n']} = {w['pct']:.1f}% [{w['ci95_pct'][0]:.1f}, {w['ci95_pct'][1]:.1f}]"

    print(f"wrote {out_path}")
    print()
    print("=== Mined-corpus headline rates (Wilson 95% CI) ===")
    hdr = f"{'estimate':<24}{'original (922)':>34}{'deduplicated (752)':>34}{'repo-wtd %':>12}"
    print(hdr)
    print("-" * len(hdr))
    for name in ("any_flag", "structural_flag", "human_presence_flag",
                 "risk_aware_gate_flag"):
        rw = repo_weighted_original.get(name, {}).get("repo_weighted_mean_pct")
        rw_s = f"{rw:.1f}" if rw is not None else "--"
        print(f"{name:<24}{fmt(original_rates[name]):>34}"
              f"{fmt(dedup_rates[name]):>34}{rw_s:>12}")
    print(f"{'flags_per_workflow':<24}"
          f"{original_rates['flags_per_workflow']:>34}"
          f"{dedup_rates['flags_per_workflow']:>34}"
          f"{repo_weighted_original['flags_per_workflow_repo_weighted']:>12}")
    print()
    print("=== Genuine-defect prevalence (validated sample) ===")
    rows = [
        ("extractor-visible /wf", primary["extractor_visible_per_workflow"],
         dedup_prev["extractor_visible_per_workflow"]),
        ("combined /workflow", primary["per_workflow"], dedup_prev["per_workflow"]),
        ("combined /repository", primary["per_repository"], dedup_prev["per_repository"]),
        ("application-like only", primary["application_like_only"],
         dedup_prev["application_like_only"]),
        ("tutorials/demos/tests", primary["tutorials_demos_tests"],
         dedup_prev["tutorials_demos_tests"]),
    ]
    hdr2 = f"{'estimate':<24}{'primary':>32}{'dedup sample':>32}"
    print(hdr2)
    print("-" * len(hdr2))
    for label, a, b in rows:
        print(f"{label:<24}{fmt(a):>32}{fmt(b):>32}")
    print(f"repo-weighted pooled prevalence: "
          f"{repo_weighted_prev['pooled']['repo_weighted_mean_pct']}% "
          f"(app-like: "
          f"{repo_weighted_prev['application_like_only']['repo_weighted_mean_pct']}%, "
          f"tut/demo/test: "
          f"{repo_weighted_prev['tutorials_demos_tests']['repo_weighted_mean_pct']}%)")
    print()
    print("=== Unknown-as-positive upper bounds ===")
    wl = unknown_as_positive["workflow_level_prevalence"]
    print(f"{'extractor-visible /wf':<24}{fmt(wl['primary_extractor_visible']):>32}"
          f"{'-> upper ' + fmt(wl['upper_extractor_visible']):>40}")
    print(f"{'combined /wf':<24}{fmt(wl['primary_combined']):>32}"
          f"{'-> upper ' + fmt(wl['upper_combined']):>40}")
    fl = unknown_as_positive["flag_level_ppv"]
    print(f"{'flag-level PPV':<24}"
          f"{fmt(fl['extractor_visible_flags']['primary']):>32}"
          f"{'-> upper ' + fmt(fl['extractor_visible_flags']['upper_bound']):>40}")
    print(f"{'GT-pass flag PPV':<24}"
          f"{fmt(fl['ground_truth_pass_flags']['primary']):>32}"
          f"{'-> upper ' + fmt(fl['ground_truth_pass_flags']['upper_bound']):>40}")
    print()
    print("=== Consistency checks ===")
    for k, v in consistency.items():
        print(f"  {k}: {v}")
    print()
    print("=== Material-change verdicts (soft gate) ===")
    for k, v in material["headline_estimates"].items():
        if "dedup_material" in v:
            print(f"  {k}: dedup {'MATERIAL' if v['dedup_material'] else 'not material'}"
                  f" (delta {v['dedup_delta_pp']:+.2f} pp)"
                  + (f", repo-weighted "
                     f"{'MATERIAL' if v.get('repo_weighted_material') else 'not material'}"
                     f" (delta {v.get('repo_weighted_delta_pp', 0):+.2f} pp)"
                     if 'repo_weighted_material' in v else ""))


if __name__ == "__main__":
    main()
