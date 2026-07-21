#!/usr/bin/env python3
"""Repository-clustered bootstrap CIs for the supplement's fidelity tables.

The committed ``corpus/real_world/confidence_intervals.json`` was computed on
the *unmatched* n=120 fidelity set (self-repo graph included) with a bootstrap
that resamples *workflows*, not repositories.  The AAAI text reports
repository-clustered intervals on the *matched, collision-free* n=106 set.
This script produces exactly that, for both instrument versions.

Point estimates reproduce
``matched_fidelity.json -> provenance_collisions.collision_free_fidelity``
exactly, which is the check that the slug set and metric extraction agree.

Usage:
    python scripts/supplement_cis.py
Output:
    corpus/real_world/supplement_cis.json
"""

from __future__ import annotations

import collections
import json
import random
from pathlib import Path

B = 10_000
SEED = 20260712
METRICS = (
    "node_precision",
    "node_recall",
    "edge_precision",
    "edge_recall",
    "kind_accuracy",
)


def repo_of(slug: str) -> str:
    """corpus slugs are ``<owner>__<repo>__<file stem>``."""
    return "__".join(slug.split("__")[:2])


def clustered_bootstrap(
    rows: list[tuple[str, float]], b: int = B, seed: int = SEED
) -> tuple[float, float, float]:
    """Cluster (repository) bootstrap CI for a mean over workflows."""
    by_repo: dict[str, list[float]] = collections.defaultdict(list)
    for repo, val in rows:
        by_repo[repo].append(val)
    keys = list(by_repo)
    n_clusters = len(keys)
    rng = random.Random(seed)
    means = []
    for _ in range(b):
        vals: list[float] = []
        for _ in range(n_clusters):
            vals.extend(by_repo[keys[rng.randrange(n_clusters)]])
        means.append(sum(vals) / len(vals))
    means.sort()
    mean = sum(v for _, v in rows) / len(rows)
    return mean, means[int(0.025 * b)], means[int(0.975 * b)]


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    rw = root / "corpus" / "real_world"
    matched = json.loads((rw / "matched_fidelity.json").read_text())
    validated = json.loads((rw / "validated_results.json").read_text())

    per_slug = matched["per_slug_matched"]
    collisions = set(matched["provenance_collisions"]["fidelity_collision_slugs"])
    framework = {r["slug"]: r["framework"] for r in validated["fidelity_details"]}

    slugs = [s for s in per_slug["v1"] if s not in collisions]
    missing = [s for s in slugs if s not in framework]
    assert not missing, f"no framework label for {missing}"

    out: dict = {
        "_meta": {
            "script": "scripts/supplement_cis.py",
            "set": "matched, collision-free (n=106)",
            "inputs": ["matched_fidelity.json", "validated_results.json"],
            "bootstrap_B": B,
            "seed": SEED,
            "clustering": "repository (owner__repo prefix of the slug)",
        }
    }
    for instrument in ("v1", "v2"):
        for stratum in ("overall", "langgraph", "crewai", "autogen", "adk"):
            sel = [
                s for s in slugs if stratum == "overall" or framework[s] == stratum
            ]
            row: dict = {"n": len(sel), "n_repos": len({repo_of(s) for s in sel})}
            for metric in METRICS:
                rows = [(repo_of(s), per_slug[instrument][s][metric]) for s in sel]
                mean, lo, hi = clustered_bootstrap(rows)
                row[metric] = [round(mean, 3), round(lo, 3), round(hi, 3)]
            out[f"{instrument}:{stratum}"] = row

    dest = rw / "supplement_cis.json"
    dest.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
