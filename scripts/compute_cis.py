#!/usr/bin/env python3
"""95% confidence intervals for the paper's headline numbers.

- Extractor fidelity means (edge recall/precision, node-kind accuracy), overall
  and per framework: nonparametric bootstrap over workflows (10k resamples, seed
  set for reproducibility).
- Prevalence proportions (genuine defects, structural artifacts, triage label
  fractions, human-gate flag rates): Wilson score intervals.

Pure Python, no numpy/scipy dependency.

Usage:
    python scripts/compute_cis.py --validated corpus/real_world/validated_results.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path

Z = 1.96  # 95%


def wilson(x: int, n: int) -> tuple[float, float, float]:
    """Wilson score interval. Returns (p_hat, lo, hi) as percentages."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = x / n
    denom = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / denom
    half = (Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))) / denom
    lo = max(0.0, center - half)
    hi = min(1.0, center + half)
    return (p * 100, lo * 100, hi * 100)


def bootstrap_mean(values: list[float], B: int = 10000, seed: int = 20260712) -> tuple[float, float, float]:
    """Bootstrap 95% CI for the mean. Returns (mean, lo, hi)."""
    n = len(values)
    if n == 0:
        return (0.0, 0.0, 0.0)
    rng = random.Random(seed)
    means = []
    for _ in range(B):
        s = 0.0
        for _ in range(n):
            s += values[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[int(0.025 * B)]
    hi = means[int(0.975 * B)]
    return (sum(values) / n, lo, hi)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validated", default="corpus/real_world/validated_results.json")
    ap.add_argument("--output", default="corpus/real_world/confidence_intervals.json")
    args = ap.parse_args()

    v = json.loads(Path(args.validated).read_text())
    fid = v["fidelity_details"]
    tri = v["triage"]

    # ---- fidelity: bootstrap CIs on per-workflow metrics ----
    def series(rows, key):
        return [r["edge_detection"][key] if key in ("recall", "precision") else r["node_kind_accuracy"]
                for r in rows]

    by_fw: dict[str, list] = defaultdict(list)
    for r in fid:
        by_fw[r["framework"]].append(r)

    fidelity_ci = {}
    for label, rows in [("overall", fid)] + sorted(by_fw.items()):
        er = [r["edge_detection"]["recall"] for r in rows]
        ep = [r["edge_detection"]["precision"] for r in rows]
        ka = [r["node_kind_accuracy"] for r in rows]
        fidelity_ci[label] = {
            "n": len(rows),
            "edge_recall": bootstrap_mean(er),
            "edge_precision": bootstrap_mean(ep),
            "kind_accuracy": bootstrap_mean(ka),
        }

    # ---- prevalence: Wilson CIs ----
    labels = tri["label_distribution"]
    total = tri["n_defects_triaged"]
    real = labels.get("real_defect", 0)
    artifact = labels.get("extraction_artifact", 0)
    intentional = labels.get("intentional", 0)
    # structural flags = all non-human_presence checks
    by_check = tri["by_check"]
    struct_total = sum(sum(c.values()) for k, c in by_check.items() if "human" not in k)
    struct_real = sum(c.get("real_defect", 0) for k, c in by_check.items() if "human" not in k)
    hp = by_check.get("human_presence", {})
    hp_total = sum(hp.values())
    hp_real = hp.get("real_defect", 0)

    prevalence_ci = {
        "genuine_of_all_flags": (real, total, wilson(real, total)),
        "structural_genuine": (struct_real, struct_total, wilson(struct_real, struct_total)),
        "artifact_fraction": (artifact, total, wilson(artifact, total)),
        "intentional_fraction": (intentional, total, wilson(intentional, total)),
        "human_gate_genuine": (hp_real, hp_total, wilson(hp_real, hp_total)),
    }

    out = {"fidelity_ci": fidelity_ci, "prevalence_ci": prevalence_ci,
           "bootstrap_B": 10000, "z": Z}
    Path(args.output).write_text(json.dumps(out, indent=2, default=list))

    def fmt(t):  # (mean/p, lo, hi)
        return f"{t[0]:.3f} [{t[1]:.3f}, {t[2]:.3f}]"

    def fmtp(t):  # percentage triple
        return f"{t[0]:.1f}% [{t[1]:.1f}, {t[2]:.1f}]"

    print("=" * 66)
    print("FIDELITY (bootstrap 95% CI on per-workflow mean, B=10k)")
    for label, d in fidelity_ci.items():
        print(f"  {label:10s} (n={d['n']:3d}): edgeR {fmt(d['edge_recall'])}  "
              f"kindAcc {fmt(d['kind_accuracy'])}")
    print("=" * 66)
    print("PREVALENCE (Wilson 95% CI)")
    for k, (x, n, ci) in prevalence_ci.items():
        print(f"  {k:22s}: {x}/{n} = {fmtp(ci)}")
    print(f"\nWritten to {args.output}")


if __name__ == "__main__":
    main()
