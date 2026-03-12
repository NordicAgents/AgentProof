#!/usr/bin/env python3
"""Measure extractor accuracy against ground truth annotations.

Compares extracted AgentGraph JSON against manually annotated ground truth
to compute precision/recall for node-kind classification and edge detection.
Reports per-framework metrics and failure mode categorization.

Usage:
    python scripts/extractor_accuracy.py [--corpus corpus/graphs] [--truth corpus/ground_truth]
    python scripts/extractor_accuracy.py --corpus corpus/real_world/graphs --truth corpus/real_world/ground_truth
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


FAILURE_MODES = {
    "dynamic_construction": "Nodes/edges added in loops or conditionally at runtime",
    "custom_node_type": "Unrecognized node kinds or custom agent types",
    "version_incompatibility": "Framework API changes between versions",
    "naming_heuristic_failure": "Human/router detection by name convention failed",
}


def compute_accuracy(extracted: dict, ground_truth: dict) -> dict:
    """Compare extracted graph against ground truth."""
    # Node-kind accuracy
    gt_node_kinds = {n["id"]: n["kind"] for n in ground_truth["nodes"]}
    ex_node_kinds = {n["id"]: n["kind"] for n in extracted["nodes"]}

    node_ids_gt = set(gt_node_kinds.keys())
    node_ids_ex = set(ex_node_kinds.keys())

    common_nodes = node_ids_gt & node_ids_ex
    kind_correct = sum(1 for nid in common_nodes if gt_node_kinds[nid] == ex_node_kinds[nid])
    kind_total = len(common_nodes)

    # Edge detection
    gt_edges = {(e["source"], e["target"]) for e in ground_truth["edges"]}
    ex_edges = {(e["source"], e["target"]) for e in extracted["edges"]}

    edge_tp = len(gt_edges & ex_edges)
    edge_fp = len(ex_edges - gt_edges)
    edge_fn = len(gt_edges - ex_edges)

    edge_precision = edge_tp / (edge_tp + edge_fp) if (edge_tp + edge_fp) > 0 else 0.0
    edge_recall = edge_tp / (edge_tp + edge_fn) if (edge_tp + edge_fn) > 0 else 0.0

    # Node detection
    node_tp = len(node_ids_gt & node_ids_ex)
    node_fp = len(node_ids_ex - node_ids_gt)
    node_fn = len(node_ids_gt - node_ids_ex)

    node_precision = node_tp / (node_tp + node_fp) if (node_tp + node_fp) > 0 else 0.0
    node_recall = node_tp / (node_tp + node_fn) if (node_tp + node_fn) > 0 else 0.0

    # Kind classification mismatches with failure mode categorization
    mismatches = []
    for nid in sorted(common_nodes):
        if gt_node_kinds[nid] != ex_node_kinds[nid]:
            mismatch: dict = {
                "node_id": nid,
                "expected": gt_node_kinds[nid],
                "actual": ex_node_kinds[nid],
            }
            # Categorize failure mode
            if gt_node_kinds[nid] == "human" and ex_node_kinds[nid] == "llm":
                mismatch["failure_mode"] = "naming_heuristic_failure"
            elif gt_node_kinds[nid] == "router" and ex_node_kinds[nid] == "llm":
                mismatch["failure_mode"] = "naming_heuristic_failure"
            else:
                mismatch["failure_mode"] = "custom_node_type"
            mismatches.append(mismatch)

    # Human-node detection analysis
    gt_human_ids = {nid for nid, k in gt_node_kinds.items() if k == "human"}
    ex_human_ids = {nid for nid, k in ex_node_kinds.items() if k == "human"}
    human_tp = len(gt_human_ids & ex_human_ids)
    human_fn = len(gt_human_ids - ex_human_ids)
    human_fp = len(ex_human_ids - gt_human_ids)

    return {
        "node_detection": {
            "precision": round(node_precision, 3),
            "recall": round(node_recall, 3),
            "tp": node_tp, "fp": node_fp, "fn": node_fn,
        },
        "node_kind_accuracy": round(kind_correct / kind_total, 3) if kind_total > 0 else 0.0,
        "kind_correct": kind_correct,
        "kind_total": kind_total,
        "kind_mismatches": mismatches,
        "edge_detection": {
            "precision": round(edge_precision, 3),
            "recall": round(edge_recall, 3),
            "tp": edge_tp, "fp": edge_fp, "fn": edge_fn,
        },
        "human_detection": {
            "tp": human_tp,
            "fn": human_fn,
            "fp": human_fp,
            "recall": round(human_tp / (human_tp + human_fn), 3) if (human_tp + human_fn) > 0 else None,
        },
        "failure_modes": {},
    }


def main():
    parser = argparse.ArgumentParser(description="Extractor accuracy measurement")
    parser.add_argument("--corpus", type=str, default="corpus/graphs")
    parser.add_argument("--truth", type=str, default="corpus/ground_truth")
    parser.add_argument("--output", type=str, default="scripts/accuracy_results.json")
    args = parser.parse_args()

    corpus_dir = Path(args.corpus)
    truth_dir = Path(args.truth)
    results: list[dict] = []
    per_framework: dict[str, list[dict]] = {}

    gt_files = sorted(truth_dir.glob("*.json"))
    if not gt_files:
        print(f"No ground truth files found in {truth_dir}/")
        print("Create ground truth annotations by copying and correcting graphs from corpus/graphs/")
        return

    for gt_path in gt_files:
        name = gt_path.stem
        ex_path = corpus_dir / f"{name}.json"
        if not ex_path.exists():
            print(f"  {name}: no extracted graph found, skipping")
            continue

        gt_data = json.loads(gt_path.read_text())
        ex_data = json.loads(ex_path.read_text())

        accuracy = compute_accuracy(ex_data, gt_data)
        accuracy["workflow"] = name
        framework = ex_data.get("framework", "unknown")
        accuracy["framework"] = framework

        # Categorize failure modes
        failure_mode_counts: dict[str, int] = {}
        for mm in accuracy["kind_mismatches"]:
            fm = mm.get("failure_mode", "unknown")
            failure_mode_counts[fm] = failure_mode_counts.get(fm, 0) + 1
        accuracy["failure_modes"] = failure_mode_counts

        print(f"  {name} ({framework}):")
        print(f"    Node detection: P={accuracy['node_detection']['precision']:.3f} R={accuracy['node_detection']['recall']:.3f}")
        print(f"    Node kind accuracy: {accuracy['node_kind_accuracy']:.3f} ({accuracy['kind_correct']}/{accuracy['kind_total']})")
        print(f"    Edge detection: P={accuracy['edge_detection']['precision']:.3f} R={accuracy['edge_detection']['recall']:.3f}")
        if accuracy["human_detection"]["recall"] is not None:
            print(f"    Human detection recall: {accuracy['human_detection']['recall']:.3f}")
        if accuracy["kind_mismatches"]:
            print(f"    Mismatches: {accuracy['kind_mismatches']}")
        if accuracy["failure_modes"]:
            print(f"    Failure modes: {accuracy['failure_modes']}")

        results.append(accuracy)
        per_framework.setdefault(framework, []).append(accuracy)

    if results:
        print(f"\n{'='*60}")
        print("Overall averages:")
        avg_node_p = sum(r["node_detection"]["precision"] for r in results) / len(results)
        avg_node_r = sum(r["node_detection"]["recall"] for r in results) / len(results)
        avg_kind = sum(r["node_kind_accuracy"] for r in results) / len(results)
        avg_edge_p = sum(r["edge_detection"]["precision"] for r in results) / len(results)
        avg_edge_r = sum(r["edge_detection"]["recall"] for r in results) / len(results)

        print(f"  Node detection: P={avg_node_p:.3f} R={avg_node_r:.3f}")
        print(f"  Kind accuracy: {avg_kind:.3f}")
        print(f"  Edge detection: P={avg_edge_p:.3f} R={avg_edge_r:.3f}")

        # Per-framework summary
        print(f"\n{'='*60}")
        print("Per-framework averages:")
        framework_summary = {}
        for fw, fw_results in sorted(per_framework.items()):
            n = len(fw_results)
            fw_avg = {
                "count": n,
                "node_precision": round(sum(r["node_detection"]["precision"] for r in fw_results) / n, 3),
                "node_recall": round(sum(r["node_detection"]["recall"] for r in fw_results) / n, 3),
                "kind_accuracy": round(sum(r["node_kind_accuracy"] for r in fw_results) / n, 3),
                "edge_precision": round(sum(r["edge_detection"]["precision"] for r in fw_results) / n, 3),
                "edge_recall": round(sum(r["edge_detection"]["recall"] for r in fw_results) / n, 3),
            }
            framework_summary[fw] = fw_avg
            print(f"  {fw} ({n} workflows): "
                  f"NodeP={fw_avg['node_precision']:.3f} "
                  f"NodeR={fw_avg['node_recall']:.3f} "
                  f"Kind={fw_avg['kind_accuracy']:.3f} "
                  f"EdgeP={fw_avg['edge_precision']:.3f} "
                  f"EdgeR={fw_avg['edge_recall']:.3f}")

        # Failure mode distribution
        all_modes: dict[str, int] = {}
        for r in results:
            for fm, count in r.get("failure_modes", {}).items():
                all_modes[fm] = all_modes.get(fm, 0) + count
        if all_modes:
            print(f"\nFailure mode distribution:")
            for fm, count in sorted(all_modes.items(), key=lambda x: -x[1]):
                desc = FAILURE_MODES.get(fm, "")
                print(f"  {fm}: {count} — {desc}")

        output_data = {
            "overall": {
                "node_precision": round(avg_node_p, 3),
                "node_recall": round(avg_node_r, 3),
                "kind_accuracy": round(avg_kind, 3),
                "edge_precision": round(avg_edge_p, 3),
                "edge_recall": round(avg_edge_r, 3),
            },
            "per_framework": framework_summary,
            "failure_modes": all_modes,
            "details": results,
        }

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output_data, indent=2))
        print(f"\nResults written to {output_path}")


if __name__ == "__main__":
    main()
