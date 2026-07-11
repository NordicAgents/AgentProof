#!/usr/bin/env python3
"""Run structural checks on all corpus workflows and report defects.

Reports defects separated by category (structural vs policy) and optionally
computes TP/FP precision when annotation labels are provided.

Usage:
    python scripts/defect_study.py [--corpus corpus/curated] [--output scripts/defect_results.json]
    python scripts/defect_study.py --corpus corpus/real_world/graphs --annotations corpus/annotations/defect_labels.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentproof.graph.model import graph_from_dict
from agentproof.verify import run_structural_checks

STRUCTURAL_CHECKS = {"exit_reachability", "dead_ends", "router_shape", "tool_declarations"}
POLICY_CHECKS = {"human_presence"}


def load_annotations(path: Path) -> dict[str, str]:
    """Load defect annotations mapping 'workflow:check_id' -> 'tp'|'fp'|'arguable'."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return data


def compute_cohens_kappa(annotations: dict) -> float | None:
    """Compute Cohen's kappa for inter-annotator agreement.

    Expects annotations with 'annotator_1' and 'annotator_2' fields.
    """
    labels = []
    for key, val in annotations.items():
        if isinstance(val, dict) and "annotator_1" in val and "annotator_2" in val:
            labels.append((val["annotator_1"], val["annotator_2"]))

    if not labels:
        return None

    categories = sorted(set(l for pair in labels for l in pair))
    n = len(labels)
    if n == 0:
        return None

    # Observed agreement
    po = sum(1 for a, b in labels if a == b) / n

    # Expected agreement
    pe = 0.0
    for cat in categories:
        p1 = sum(1 for a, _ in labels if a == cat) / n
        p2 = sum(1 for _, b in labels if b == cat) / n
        pe += p1 * p2

    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def main():
    parser = argparse.ArgumentParser(description="Defect study on workflow corpus")
    parser.add_argument("--corpus", type=str, default="corpus/curated")
    parser.add_argument("--output", type=str, default="scripts/defect_results.json")
    parser.add_argument("--annotations", type=str, default=None,
                        help="Path to defect label annotations for TP/FP analysis")
    args = parser.parse_args()

    corpus_dir = Path(args.corpus)
    annotations = load_annotations(Path(args.annotations)) if args.annotations else {}
    results: list[dict] = []
    total_defects = 0
    workflows_with_defects = 0
    workflows_with_structural = 0
    workflows_with_policy = 0

    for path in sorted(corpus_dir.glob("*.json")):
        data = json.loads(path.read_text())
        graph = graph_from_dict(data)

        report = run_structural_checks(graph, require_human=True)

        defects: list[dict] = []
        has_structural = False
        has_policy = False

        for check in report["checks"]:
            if not check["passed"]:
                category = check.get("category", "structural")
                defect: dict = {
                    "check": check["check_id"],
                    "category": category,
                }
                if check["check_id"] == "exit_reachability":
                    defect["detail"] = f"unreachable exits: {check['missing_exits']}"
                    defect["severity"] = "critical"
                elif check["check_id"] == "reverse_reachability":
                    defect["detail"] = f"livelock nodes: {check['livelock_nodes']}"
                    defect["severity"] = "high"
                    if "witnesses" in check:
                        defect["witnesses"] = {
                            k: v for k, v in check["witnesses"].items() if v is not None
                        }
                elif check["check_id"] == "dead_ends":
                    defect["detail"] = f"dead-end nodes: {check['dead_ends']}"
                    defect["severity"] = "high"
                    if "witnesses" in check:
                        defect["witnesses"] = {
                            k: v for k, v in check["witnesses"].items() if v is not None
                        }
                elif check["check_id"] == "router_shape":
                    defect["detail"] = f"{len(check['violations'])} router(s) with non-conditional edges"
                    defect["severity"] = "medium"
                elif check["check_id"] == "human_presence":
                    defect["detail"] = "no human-in-the-loop node"
                    defect["severity"] = "high"
                elif check["check_id"] == "tool_declarations":
                    defect["detail"] = f"tools without declarations: {check['tool_nodes_missing_tools']}"
                    defect["severity"] = "low"

                # TP/FP annotation lookup
                ann_key = f"{graph.name}:{check['check_id']}"
                if ann_key in annotations:
                    ann = annotations[ann_key]
                    defect["label"] = ann if isinstance(ann, str) else ann.get("agreed", "unlabeled")
                elif annotations:
                    defect["label"] = "unlabeled"

                defects.append(defect)

                if category == "structural":
                    has_structural = True
                else:
                    has_policy = True

        entry = {
            "name": graph.name,
            "framework": graph.framework,
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "passed": report["passed_count"],
            "total_checks": report["total"],
            "defects": defects,
        }
        results.append(entry)

        n_defects = len(defects)
        total_defects += n_defects
        if n_defects > 0:
            workflows_with_defects += 1
        if has_structural:
            workflows_with_structural += 1
        if has_policy:
            workflows_with_policy += 1

        if n_defects > 0:
            print(f"  {graph.name} ({graph.framework}): {n_defects} defect(s)")
            for d in defects:
                label_str = f" [{d.get('label', '')}]" if "label" in d else ""
                print(f"    [{d['severity']}] [{d['category']}] {d['check']}: {d['detail']}{label_str}")
        else:
            print(f"  {graph.name} ({graph.framework}): clean")

    total_wf = len(results)
    print(f"\n{'='*60}")
    print(f"Total workflows: {total_wf}")
    print(f"Workflows with any defect: {workflows_with_defects} ({workflows_with_defects*100//total_wf}%)")
    print(f"Workflows with structural defects: {workflows_with_structural} ({workflows_with_structural*100//total_wf}%)")
    print(f"Workflows with policy violations: {workflows_with_policy} ({workflows_with_policy*100//total_wf}%)")
    print(f"Total defects found: {total_defects}")

    # Summary by defect type and category
    defect_types: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {"structural": 0, "policy": 0}
    for r in results:
        for d in r["defects"]:
            defect_types[d["check"]] = defect_types.get(d["check"], 0) + 1
            severity_counts[d["severity"]] = severity_counts.get(d["severity"], 0) + 1
            category_counts[d["category"]] = category_counts.get(d["category"], 0) + 1

    print(f"\nDefects by type:")
    for dt, count in sorted(defect_types.items()):
        print(f"  {dt}: {count}")
    print(f"\nDefects by category:")
    for cat, count in sorted(category_counts.items()):
        print(f"  {cat}: {count}")
    print(f"\nDefects by severity:")
    for sev, count in sorted(severity_counts.items()):
        print(f"  {sev}: {count}")

    # TP/FP precision analysis
    precision_by_check: dict[str, dict] = {}
    if annotations:
        all_defects = [d for r in results for d in r["defects"]]
        labeled = [d for d in all_defects if d.get("label") in ("tp", "fp", "arguable")]
        if labeled:
            print(f"\n{'='*60}")
            print(f"TP/FP Analysis ({len(labeled)} labeled defects):")
            for check_id in sorted(defect_types.keys()):
                check_labeled = [d for d in labeled if d["check"] == check_id]
                tp = sum(1 for d in check_labeled if d["label"] == "tp")
                fp = sum(1 for d in check_labeled if d["label"] == "fp")
                arguable = sum(1 for d in check_labeled if d["label"] == "arguable")
                total = tp + fp
                precision = tp / total if total > 0 else None
                precision_by_check[check_id] = {
                    "tp": tp, "fp": fp, "arguable": arguable,
                    "precision": round(precision, 3) if precision is not None else None,
                }
                prec_str = f"{precision:.1%}" if precision is not None else "N/A"
                print(f"  {check_id}: TP={tp} FP={fp} Arguable={arguable} Precision={prec_str}")

            kappa = compute_cohens_kappa(annotations)
            if kappa is not None:
                print(f"\n  Cohen's kappa (inter-annotator): {kappa:.3f}")

    summary = {
        "total_workflows": total_wf,
        "workflows_with_defects": workflows_with_defects,
        "workflows_with_structural_defects": workflows_with_structural,
        "workflows_with_policy_violations": workflows_with_policy,
        "structural_defect_rate": round(workflows_with_structural * 100 / total_wf, 1) if total_wf else 0,
        "policy_violation_rate": round(workflows_with_policy * 100 / total_wf, 1) if total_wf else 0,
        "total_defects": total_defects,
        "defects_by_type": defect_types,
        "defects_by_category": category_counts,
        "defects_by_severity": severity_counts,
        "precision_by_check": precision_by_check,
        "details": results,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2))
    print(f"\nResults written to {output_path}")


if __name__ == "__main__":
    main()
