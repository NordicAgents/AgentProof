#!/usr/bin/env python3
"""Current 95% descriptive intervals for the paper's headline numbers.

- Extractor fidelity on the matched, collision-free n=106 set: repository-
  clustered bootstrap (10k resamples, fixed seed) for both instruments.
- Prevalence proportions (genuine defects, structural artifacts, triage label
  fractions, as-mined human-presence flags, and HGP-1): Wilson intervals.

Pure Python, no numpy/scipy dependency.

Usage:
    python scripts/compute_cis.py --validated corpus/real_world/validated_results.json
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import random
from pathlib import Path

Z = 1.96  # 95%
BOOT = 10_000
SEED = 20260712
SELF_REPO_PREFIX = "NordicAgents__AgentProof"
METRICS = (
    "node_precision",
    "node_recall",
    "edge_precision",
    "edge_recall",
    "kind_accuracy",
)


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


def repo_of(slug: str) -> str:
    return "__".join(slug.split("__")[:2])


def clustered_bootstrap(
    rows: list[tuple[str, float]], B: int = BOOT, seed: int = SEED
) -> tuple[float, float, float]:
    """Repository-cluster bootstrap CI for a workflow-level mean."""
    by_repo: dict[str, list[float]] = collections.defaultdict(list)
    for repo, value in rows:
        by_repo[repo].append(value)
    keys = sorted(by_repo)
    rng = random.Random(seed)
    means = []
    for _ in range(B):
        values: list[float] = []
        for _ in range(len(keys)):
            values.extend(by_repo[keys[rng.randrange(len(keys))]])
        means.append(sum(values) / len(values))
    means.sort()
    lo = means[int(0.025 * B)]
    hi = means[int(0.975 * B)]
    point = sum(value for _, value in rows) / len(rows)
    return (point, lo, hi)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validated", default="corpus/real_world/validated_results.json")
    ap.add_argument("--matched", default="corpus/real_world/matched_fidelity.json")
    ap.add_argument("--hgp", default="corpus/real_world/human_gate_audit.json")
    ap.add_argument("--output", default="corpus/real_world/confidence_intervals.json")
    args = ap.parse_args()

    v = json.loads(Path(args.validated).read_text())
    matched = json.loads(Path(args.matched).read_text())
    hgp = json.loads(Path(args.hgp).read_text())

    # ---- fidelity: matched, collision-free, repository-clustered ----
    per_slug = matched["per_slug_matched"]
    collisions = set(
        matched["provenance_collisions"]["fidelity_collision_slugs"]
    )
    framework = {r["slug"]: r["framework"] for r in v["fidelity_details"]}
    slugs = [slug for slug in per_slug["v1"] if slug not in collisions]
    assert len(slugs) == 106

    fidelity_ci: dict[str, dict] = {}
    for instrument in ("v1", "v2"):
        fidelity_ci[instrument] = {}
        for stratum in ("overall", "langgraph", "crewai", "autogen", "adk"):
            selected = [
                slug for slug in slugs
                if stratum == "overall" or framework[slug] == stratum
            ]
            row = {
                "n": len(selected),
                "n_repositories": len({repo_of(slug) for slug in selected}),
            }
            for metric in METRICS:
                values = [
                    (repo_of(slug), per_slug[instrument][slug][metric])
                    for slug in selected
                ]
                row[metric] = clustered_bootstrap(values)
            fidelity_ci[instrument][stratum] = row

    # ---- prevalence: Wilson CIs ----
    details = [
        row for row in v["triage_details"]
        if not row["slug"].startswith(SELF_REPO_PREFIX)
    ]
    assert len(details) == 186
    labels: dict[str, int] = collections.Counter(row["label"] for row in details)
    total = len(details)
    real = labels.get("real_defect", 0)
    artifact = labels.get("extraction_artifact", 0)
    intentional = labels.get("intentional", 0)
    structural = [row for row in details if "human" not in row["check"]]
    struct_total = len(structural)
    struct_real = sum(row["label"] == "real_defect" for row in structural)
    human_presence = [row for row in details if row["check"] == "human_presence"]
    hp_total = len(human_presence)
    hp_real = sum(row["label"] == "real_defect" for row in human_presence)
    hgp_k = hgp["audit_proportion_over_sample"]["k"]
    hgp_n = hgp["audit_proportion_over_sample"]["n"]
    hgp_arguable = hgp["counts"]["arguable"]

    prevalence_ci = {
        "genuine_of_all_flags": (real, total, wilson(real, total)),
        "structural_genuine": (struct_real, struct_total, wilson(struct_real, struct_total)),
        "artifact_fraction": (artifact, total, wilson(artifact, total)),
        "intentional_fraction": (intentional, total, wilson(intentional, total)),
        "as_mined_human_presence_genuine":
            (hp_real, hp_total, wilson(hp_real, hp_total)),
        "hgp1_violation": (hgp_k, hgp_n, wilson(hgp_k, hgp_n)),
        "hgp1_violation_plus_arguable":
            (hgp_k + hgp_arguable, hgp_n,
             wilson(hgp_k + hgp_arguable, hgp_n)),
    }

    out = {
        "_meta": {
            "fidelity_set": "matched, provenance-disambiguated n=106",
            "fidelity_clustering": "repository",
            "triage_set": "186 as-mined flags, self-repository excluded",
            "policy_estimand": "HGP-1 source audit; supersedes two-check 3/119",
        },
        "fidelity_ci": fidelity_ci,
        "prevalence_ci": prevalence_ci,
        "bootstrap_B": BOOT,
        "seed": SEED,
        "z": Z,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, default=list))

    def fmt(t):  # (mean/p, lo, hi)
        return f"{t[0]:.3f} [{t[1]:.3f}, {t[2]:.3f}]"

    def fmtp(t):  # percentage triple
        return f"{t[0]:.1f}% [{t[1]:.1f}, {t[2]:.1f}]"

    print("=" * 66)
    print("FIDELITY (matched n=106, repository-cluster bootstrap, B=10k)")
    for instrument in ("v1", "v2"):
        for label, d in fidelity_ci[instrument].items():
            print(
                f"  {instrument}:{label:10s} (n={d['n']:3d}): "
                f"edgeR {fmt(d['edge_recall'])}  "
                f"kindAcc {fmt(d['kind_accuracy'])}"
            )
    print("=" * 66)
    print("PREVALENCE (Wilson 95% CI)")
    for k, (x, n, ci) in prevalence_ci.items():
        print(f"  {k:22s}: {x}/{n} = {fmtp(ci)}")
    print(f"\nWritten to {args.output}")


if __name__ == "__main__":
    main()
