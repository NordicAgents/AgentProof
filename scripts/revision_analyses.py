#!/usr/bin/env python3
"""Revision analyses addressing the AAAI review.

Produces corpus/real_world/revision_analyses.json with:

1. prevalence_gt      — six structural checks + risk-aware gate run on the 120
                        LLM-reconstructed ground-truth graphs (measures defects
                        the AST extractor may have MISSED: false negatives, the
                        estimand the original study could not see).
2. composition        — corpus composition: unique repos, tutorial/test/demo
                        fraction by filename, self-referential (project-repo)
                        contamination, duplicate graphs across repos.
3. confidence         — GT-reconstruction confidence distribution and fidelity
                        restricted to high-confidence GT graphs.
4. cluster_cis        — repo-level cluster bootstrap CIs for fidelity means and
                        for the per-workflow / per-repo genuine-defect
                        prevalence implied by the existing adversarial triage.
5. flags_for_triage   — the GT-graph flags that need LLM triage
                        (real vs intentional), written for the triage workflow.

All exclusions are reported, never silent: the NordicAgents/AgentProof repo
(the project's own test fixtures, spotted in review) is dropped from every
denominator, and the raw numbers are kept alongside.
"""

from __future__ import annotations

import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from agentproof.graph.model import graph_from_dict
from agentproof.verify import run_structural_checks
from risk_aware_gate import SENSITIVE_KEYWORDS

ROOT = Path(__file__).resolve().parents[1]
RW = ROOT / "corpus" / "real_world"

SELF_REPO_PREFIX = "NordicAgents__AgentProof"
STRUCTURAL_CHECKS = {
    "exit_reachability", "reverse_reachability", "dead_ends",
    "router_shape", "tool_declarations",
}
NAME_PAT = re.compile(
    r"(test|tutorial|example|demo|exercise|learn|course|sample|starter|"
    r"quickstart|playground|template|lesson)", re.I)


def slug_repo(slug: str) -> str:
    parts = slug.split("__")
    return parts[0] + "/" + parts[1] if len(parts) >= 2 else slug


def sensitive_tool_set(graphs: list[dict]) -> set[str]:
    """All tool names in *graphs* matching the sensitivity lexicon."""
    keywords = [kw for kws in SENSITIVE_KEYWORDS.values() for kw in kws]
    out: set[str] = set()
    for g in graphs:
        for n in g.get("nodes", []):
            for t in n.get("tools", []) or []:
                low = t.lower()
                if any(kw in low for kw in keywords):
                    out.add(t)
    return out


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def cluster_bootstrap(values_by_cluster: dict[str, list[float]],
                      n_boot: int = 10_000, seed: int = 7) -> tuple[float, float, float]:
    """Bootstrap resampling clusters (repos) with replacement; mean + 95% CI."""
    rng = random.Random(seed)
    clusters = sorted(values_by_cluster)
    flat = [v for c in clusters for v in values_by_cluster[c]]
    point = sum(flat) / len(flat)
    means = []
    for _ in range(n_boot):
        sample: list[float] = []
        for _ in range(len(clusters)):
            sample.extend(values_by_cluster[rng.choice(clusters)])
        means.append(sum(sample) / len(sample))
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[int(0.975 * n_boot)] if int(0.975 * n_boot) < n_boot else means[-1]
    return point, lo, hi


def main() -> None:
    gt_files = sorted((RW / "ground_truth").glob("*.json"))
    gt_graphs = {p.stem: json.loads(p.read_text()) for p in gt_files}
    mined_files = sorted((RW / "graphs").glob("*.json"))
    mined = {p.stem: json.loads(p.read_text()) for p in mined_files}
    combined = json.loads((RW / "wf_output_combined.json").read_text())
    conf_by_slug = {g["slug"]: g.get("confidence", "?") for g in combined["groundTruth"]}
    validated = json.loads((RW / "validated_results.json").read_text())
    fidelity_details = validated["fidelity_details"]
    triage_details = validated["triage_details"]

    excluded = sorted(s for s in mined if s.startswith(SELF_REPO_PREFIX))
    excluded_sample = sorted(s for s in gt_graphs if s.startswith(SELF_REPO_PREFIX))

    # ---- 1. Structural checks + risk-aware gate on ground-truth graphs ----
    sensitive = sensitive_tool_set(list(gt_graphs.values()))
    prevalence_rows = []
    flags_for_triage = []
    for slug, g in sorted(gt_graphs.items()):
        if slug.startswith(SELF_REPO_PREFIX):
            continue
        graph = graph_from_dict(g)
        report = run_structural_checks(
            graph, require_human=True, sensitive_tools=sensitive)
        failed = [c for c in report["checks"] if not c["passed"]]
        row = {
            "slug": slug,
            "repo": slug_repo(slug),
            "framework": g.get("framework"),
            "gt_confidence": conf_by_slug.get(slug, "?"),
            "failed_checks": [c["check_id"] for c in failed],
            "failed_structural": [c["check_id"] for c in failed
                                  if c["check_id"] in STRUCTURAL_CHECKS],
            "human_gate_coverage_failed": any(
                c["check_id"] == "human_gate_coverage" for c in failed),
            "human_presence_failed": any(
                c["check_id"] == "human_presence" for c in failed),
        }
        prevalence_rows.append(row)
        for c in failed:
            if c["check_id"] == "human_presence":
                continue  # blunt check, already triaged in the original study
            flags_for_triage.append({
                "slug": slug,
                "repo": slug_repo(slug),
                "framework": g.get("framework"),
                "gt_confidence": conf_by_slug.get(slug, "?"),
                "check_id": c["check_id"],
                "detail": {k: v for k, v in c.items()
                           if k not in ("check_id", "category", "passed")},
            })

    n_gt = len(prevalence_rows)
    n_struct_flagged = sum(1 for r in prevalence_rows if r["failed_structural"])
    n_gate_flagged = sum(1 for r in prevalence_rows if r["human_gate_coverage_failed"])
    n_presence_flagged = sum(1 for r in prevalence_rows if r["human_presence_failed"])

    prevalence_gt = {
        "n_gt_workflows": n_gt,
        "sensitive_tools_in_gt": sorted(sensitive),
        "workflows_with_structural_flags": n_struct_flagged,
        "workflows_with_structural_flags_ci": wilson_ci(n_struct_flagged, n_gt),
        "workflows_with_risk_aware_gate_flags": n_gate_flagged,
        "workflows_with_risk_aware_gate_flags_ci": wilson_ci(n_gate_flagged, n_gt),
        "workflows_with_human_presence_flags": n_presence_flagged,
        "structural_flag_counts": Counter(
            c for r in prevalence_rows for c in r["failed_structural"]),
        "per_workflow": prevalence_rows,
    }

    # ---- 2. Composition ----
    def compose(slugs: list[str]) -> dict:
        repos = sorted({slug_repo(s) for s in slugs})
        flagged = [s for s in slugs if NAME_PAT.search(s)]
        return {
            "n_workflows": len(slugs),
            "n_repos": len(repos),
            "tutorial_test_named": len(flagged),
            "tutorial_test_named_pct": round(100 * len(flagged) / len(slugs), 1),
        }

    mined_kept = [s for s in mined if not s.startswith(SELF_REPO_PREFIX)]
    sample_kept = [s for s in gt_graphs if not s.startswith(SELF_REPO_PREFIX)]

    # duplicate detection: identical canonical topology across different repos
    def canon(g: dict) -> str:
        nodes = tuple(sorted((n["id"], n.get("kind", "")) for n in g["nodes"]))
        edges = tuple(sorted((e["source"], e["target"], e.get("kind", ""))
                             for e in g["edges"]))
        return json.dumps([nodes, edges])

    by_canon: dict[str, list[str]] = defaultdict(list)
    for s in mined_kept:
        by_canon[canon(mined[s])].append(s)
    dup_groups = {k: v for k, v in by_canon.items()
                  if len({slug_repo(s) for s in v}) > 1
                  and len(json.loads(k)[0]) > 3}  # >3 nodes: ignore trivial shells
    n_dup_workflows = sum(len(v) - 1 for v in dup_groups.values())

    # non-sentinel node sizes after exclusions
    sizes = []
    for s in mined_kept:
        g = mined[s]
        sizes.append(sum(1 for n in g["nodes"]
                         if n.get("kind") not in ("entry", "exit")))
    sizes.sort()
    composition = {
        "excluded_self_repo_workflows": excluded,
        "excluded_self_repo_in_sample": excluded_sample,
        "mined": compose(mined_kept),
        "sample": compose(sample_kept),
        "mined_nonsentinel_median": sizes[len(sizes) // 2],
        "mined_nonsentinel_mean": round(sum(sizes) / len(sizes), 2),
        "duplicate_topology_groups_gt3_nodes": len(dup_groups),
        "duplicate_topology_extra_workflows": n_dup_workflows,
    }

    # ---- 3. Confidence distribution + high-confidence fidelity ----
    conf_dist = Counter(conf_by_slug.get(s, "?") for s in sample_kept)
    fid_kept = [f for f in fidelity_details
                if not f["slug"].startswith(SELF_REPO_PREFIX)]

    def fid_means(rows: list[dict]) -> dict:
        return {
            "n": len(rows),
            "edge_recall": round(sum(r["edge_detection"]["recall"] for r in rows) / len(rows), 3),
            "edge_precision": round(sum(r["edge_detection"]["precision"] for r in rows) / len(rows), 3),
            "kind_accuracy": round(sum(r["node_kind_accuracy"] for r in rows) / len(rows), 3),
        }

    hi = [f for f in fid_kept if f.get("gt_confidence") == "high"]
    confidence = {
        "gt_confidence_distribution": dict(conf_dist),
        "fidelity_all": fid_means(fid_kept),
        "fidelity_high_confidence_only": fid_means(hi),
        "fidelity_high_confidence_by_framework": {
            fw: fid_means([f for f in hi if f["framework"] == fw])
            for fw in sorted({f["framework"] for f in hi})
            if [f for f in hi if f["framework"] == fw]
        },
    }

    # ---- 4. Cluster (repo-level) bootstrap CIs ----
    by_repo_recall: dict[str, list[float]] = defaultdict(list)
    by_repo_prec: dict[str, list[float]] = defaultdict(list)
    by_repo_kind: dict[str, list[float]] = defaultdict(list)
    for f in fid_kept:
        r = slug_repo(f["slug"])
        by_repo_recall[r].append(f["edge_detection"]["recall"])
        by_repo_prec[r].append(f["edge_detection"]["precision"])
        by_repo_kind[r].append(f["node_kind_accuracy"])

    triage_kept = [t for t in triage_details
                   if not t["slug"].startswith(SELF_REPO_PREFIX)]
    real_slugs = {t["slug"] for t in triage_kept if t["label"] == "real_defect"}
    arguable_slugs = {t["slug"] for t in triage_kept if t["label"] == "arguable"}
    by_repo_real: dict[str, list[float]] = defaultdict(list)
    for s in sample_kept:
        by_repo_real[slug_repo(s)].append(1.0 if s in real_slugs else 0.0)

    n_real_wf = len(real_slugs & set(sample_kept))
    repos_with_real = {slug_repo(s) for s in real_slugs}
    n_repos_sample = len({slug_repo(s) for s in sample_kept})

    er = cluster_bootstrap(by_repo_recall)
    ep = cluster_bootstrap(by_repo_prec)
    ka = cluster_bootstrap(by_repo_kind)
    pv = cluster_bootstrap(by_repo_real)
    cluster_cis = {
        "edge_recall": {"mean": round(er[0], 3), "ci95": [round(er[1], 3), round(er[2], 3)]},
        "edge_precision": {"mean": round(ep[0], 3), "ci95": [round(ep[1], 3), round(ep[2], 3)]},
        "kind_accuracy": {"mean": round(ka[0], 3), "ci95": [round(ka[1], 3), round(ka[2], 3)]},
        "prevalence_per_workflow": {
            "k": n_real_wf, "n": len(sample_kept),
            "mean": round(pv[0], 4), "ci95_cluster": [round(pv[1], 4), round(pv[2], 4)],
            "wilson_ci_unclustered": [round(x, 4) for x in wilson_ci(n_real_wf, len(sample_kept))],
        },
        "prevalence_per_repo": {
            "k": len(repos_with_real), "n": n_repos_sample,
            "wilson_ci": [round(x, 4) for x in wilson_ci(len(repos_with_real), n_repos_sample)],
        },
        "flag_ppv_after_exclusion": {
            "genuine": sum(1 for t in triage_kept if t["label"] == "real_defect"),
            "total_flags": len(triage_kept),
            "artifact": sum(1 for t in triage_kept if t["label"] == "extraction_artifact"),
            "intentional": sum(1 for t in triage_kept if t["label"] == "intentional"),
            "arguable": sum(1 for t in triage_kept if t["label"] == "arguable"),
        },
        "arguable_slugs": sorted(arguable_slugs),
    }

    out = {
        "prevalence_gt": prevalence_gt,
        "composition": composition,
        "confidence": confidence,
        "cluster_cis": cluster_cis,
    }
    (RW / "revision_analyses.json").write_text(json.dumps(out, indent=2, default=int))
    (RW / "gt_flags_for_triage.json").write_text(
        json.dumps(flags_for_triage, indent=2, default=int))

    print(json.dumps({k: v for k, v in out.items() if k != "prevalence_gt"},
                     indent=1, default=int)[:3000])
    print("--- prevalence_gt summary ---")
    print({k: v for k, v in prevalence_gt.items() if k != "per_workflow"})
    print(f"flags needing triage: {len(flags_for_triage)}")


if __name__ == "__main__":
    main()
