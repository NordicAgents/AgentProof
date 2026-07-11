#!/usr/bin/env python3
"""Aggregate the validate+triage workflow output into headline study numbers.

Consumes the JSON returned by scripts/wf_run.js (saved to --workflow-output) and:
  1. Writes each agent ground-truth graph to corpus/real_world/ground_truth/<slug>.json
     and computes AST-extractor precision/recall against corpus/real_world/graphs/<slug>.json.
  2. Aggregates adversarial triage labels into real-defect vs extraction-artifact vs
     intentional rates, overall and per structural check.
  3. Cross-checks: does low extractor edge-recall predict 'extraction_artifact' labels?

Usage:
    python scripts/aggregate_realworld.py \
        --workflow-output corpus/real_world/wf_output.json \
        --defect-results corpus/real_world/defect_results.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from extractor_accuracy import compute_accuracy  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow-output", required=True)
    ap.add_argument("--defect-results", default="corpus/real_world/defect_results.json")
    ap.add_argument("--out-root", default="corpus/real_world")
    args = ap.parse_args()

    out_root = Path(args.out_root)
    gt_dir = out_root / "ground_truth"
    gt_dir.mkdir(parents=True, exist_ok=True)
    graphs_dir = out_root / "graphs"

    wf = json.loads(Path(args.workflow_output).read_text())
    gt_results = wf.get("groundTruth", [])
    triage_results = wf.get("triage", [])

    # ---------- 1. Extractor fidelity on real code ----------
    fidelity = []
    edge_recall_by_slug: dict[str, float] = {}
    per_fw: dict[str, list] = defaultdict(list)
    for g in gt_results:
        slug = g["slug"]
        ex_path = graphs_dir / f"{slug}.json"
        if not ex_path.exists():
            continue
        # normalize to model dict and persist reference
        ref = {
            "name": slug,
            "framework": g.get("framework", "unknown"),
            "entry_id": g.get("entry_id", "__start__"),
            "exit_ids": g.get("exit_ids", ["__end__"]),
            "nodes": g["nodes"],
            "edges": g["edges"],
        }
        (gt_dir / f"{slug}.json").write_text(json.dumps(ref, indent=2))
        extracted = json.loads(ex_path.read_text())
        acc = compute_accuracy(extracted, ref)
        acc["slug"] = slug
        acc["framework"] = ref["framework"]
        acc["gt_confidence"] = g.get("confidence", "n/a")
        fidelity.append(acc)
        edge_recall_by_slug[slug] = acc["edge_detection"]["recall"]
        per_fw[ref["framework"]].append(acc)

    def _avg(rows, path):
        vals = [r[path[0]][path[1]] if len(path) == 2 else r[path[0]] for r in rows]
        return round(sum(vals) / len(vals), 3) if vals else None

    fidelity_summary = {
        "n": len(fidelity),
        "overall": {
            "node_precision": _avg(fidelity, ("node_detection", "precision")),
            "node_recall": _avg(fidelity, ("node_detection", "recall")),
            "edge_precision": _avg(fidelity, ("edge_detection", "precision")),
            "edge_recall": _avg(fidelity, ("edge_detection", "recall")),
            "kind_accuracy": _avg(fidelity, ("node_kind_accuracy",)),
        },
        "per_framework": {
            fw: {
                "n": len(rows),
                "node_precision": _avg(rows, ("node_detection", "precision")),
                "node_recall": _avg(rows, ("node_detection", "recall")),
                "edge_precision": _avg(rows, ("edge_detection", "precision")),
                "edge_recall": _avg(rows, ("edge_detection", "recall")),
                "kind_accuracy": _avg(rows, ("node_kind_accuracy",)),
            }
            for fw, rows in per_fw.items()
        },
    }

    # ---------- 2. Triage: real defect vs artifact ----------
    label_counts = Counter()
    by_check = defaultdict(Counter)
    workflows_with_real_structural = set()
    workflows_with_real_policy = set()
    STRUCTURAL = {"exit_reachability", "reverse_reachability", "dead_ends",
                  "router_shape", "tool_declarations"}
    POLICY = {"human_presence", "human_gate_coverage"}
    triaged_slugs = set()
    per_defect = []
    for t in triage_results:
        slug = t["slug"]
        triaged_slugs.add(slug)
        for lab in t.get("labels", []):
            final = lab.get("final_label", lab.get("label"))
            check = lab["check_id"]
            label_counts[final] += 1
            by_check[check][final] += 1
            per_defect.append({"slug": slug, "check": check, "label": final,
                               "confidence": lab.get("confidence")})
            if final == "real_defect":
                if check in STRUCTURAL:
                    workflows_with_real_structural.add(slug)
                elif check in POLICY:
                    workflows_with_real_policy.add(slug)

    n_triaged = len(triaged_slugs)
    total_defects = sum(label_counts.values())
    triage_summary = {
        "n_workflows_triaged": n_triaged,
        "n_defects_triaged": total_defects,
        "label_distribution": dict(label_counts),
        "label_fractions": {k: round(v / total_defects, 3) for k, v in label_counts.items()} if total_defects else {},
        "by_check": {c: dict(cnt) for c, cnt in by_check.items()},
        "validated_rates_on_sample": {
            "workflows_with_real_structural_defect": len(workflows_with_real_structural),
            "workflows_with_real_policy_gap": len(workflows_with_real_policy),
            "pct_real_structural": round(len(workflows_with_real_structural) * 100 / n_triaged, 1) if n_triaged else 0,
            "pct_real_policy": round(len(workflows_with_real_policy) * 100 / n_triaged, 1) if n_triaged else 0,
        },
    }
    # tool precision on real code: of flagged defects, fraction that are genuine (real_defect)
    real = label_counts.get("real_defect", 0)
    artifact = label_counts.get("extraction_artifact", 0)
    intentional = label_counts.get("intentional", 0)
    arguable = label_counts.get("arguable", 0)
    triage_summary["flag_precision_real_over_all"] = round(real / total_defects, 3) if total_defects else None
    # per-check precision (real / (real+artifact+intentional+arguable))
    triage_summary["per_check_real_fraction"] = {
        c: round(cnt.get("real_defect", 0) / sum(cnt.values()), 3) if sum(cnt.values()) else None
        for c, cnt in by_check.items()
    }

    # ---------- 3. Cross-check: edge-recall vs artifact rate ----------
    art_slugs = {d["slug"] for d in per_defect if d["label"] == "extraction_artifact"}
    real_slugs = {d["slug"] for d in per_defect if d["label"] == "real_defect"}
    def _mean(xs):
        return round(sum(xs) / len(xs), 3) if xs else None
    crosscheck = {
        "mean_edge_recall_workflows_with_artifact_label": _mean(
            [edge_recall_by_slug[s] for s in art_slugs if s in edge_recall_by_slug]),
        "mean_edge_recall_workflows_with_real_label": _mean(
            [edge_recall_by_slug[s] for s in real_slugs if s in edge_recall_by_slug]),
    }

    summary = {
        "extractor_fidelity_real_code": fidelity_summary,
        "triage": triage_summary,
        "crosscheck_edge_recall_vs_artifact": crosscheck,
        "fidelity_details": fidelity,
        "triage_details": per_defect,
    }
    out_path = out_root / "validated_results.json"
    out_path.write_text(json.dumps(summary, indent=2))

    # ---------- print ----------
    print("=" * 64)
    print("EXTRACTOR FIDELITY ON REAL CODE (AST extractor vs agent ground truth)")
    fs = fidelity_summary["overall"]
    print(f"  n={fidelity_summary['n']}  nodeP={fs['node_precision']} nodeR={fs['node_recall']} "
          f"edgeP={fs['edge_precision']} edgeR={fs['edge_recall']} kindAcc={fs['kind_accuracy']}")
    for fw, s in fidelity_summary["per_framework"].items():
        print(f"    {fw} (n={s['n']}): edgeP={s['edge_precision']} edgeR={s['edge_recall']} kindAcc={s['kind_accuracy']}")
    print("=" * 64)
    print(f"DEFECT TRIAGE ({total_defects} flagged defects across {n_triaged} workflows)")
    for k in ("real_defect", "extraction_artifact", "intentional", "arguable"):
        v = label_counts.get(k, 0)
        print(f"  {k:20s}: {v:4d}  ({round(v*100/total_defects,1) if total_defects else 0}%)")
    print(f"  --> flag precision (real / all flagged): {triage_summary['flag_precision_real_over_all']}")
    print("  per-check real fraction:")
    for c, f in triage_summary["per_check_real_fraction"].items():
        print(f"    {c:22s}: {f}")
    vr = triage_summary["validated_rates_on_sample"]
    print(f"  validated on {n_triaged}-wf sample: real structural={vr['pct_real_structural']}%  "
          f"real policy gap={vr['pct_real_policy']}%")
    print("=" * 64)
    print("CROSS-CHECK (mean AST edge-recall):")
    print(f"  workflows w/ artifact-labeled defect: {crosscheck['mean_edge_recall_workflows_with_artifact_label']}")
    print(f"  workflows w/ real-labeled defect:     {crosscheck['mean_edge_recall_workflows_with_real_label']}")
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
