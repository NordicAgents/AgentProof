#!/usr/bin/env python3
"""Freeze a reproducible, outcome-blind validation sample.

The historical 119-workflow audit sample is a hard-coded list whose selection
rule cannot be recovered.  This script creates its prospective replacement
from the corrected v2 corpus without reading any reference graphs, flags,
triage labels, or paper results.

Design
------
For each framework independently:

1. form a v2-extracted frame with exact pinned provenance, a local source
   snapshot, and a corrected-v2 graph artifact;
2. sample ``m`` repositories uniformly without replacement; and
3. sample one eligible workflow uniformly within each selected repository.

The workflow inclusion probability is therefore

    (m / number_of_eligible_repositories) * (1 / eligible_files_in_repository)

and is recorded with its inverse-probability weight.  A seeded eight-per-
framework subsample is also frozen for independent human graph reconstruction.

The sampling code intentionally imports no project modules and reads only:

* ``corpus/real_world/metadata_v2.json`` (pinned provenance/status),
* the two raw mining metadata files (only to mark historical slug collisions),
  and
* graph/source file existence and source bytes (for integrity hashes).

Usage
-----
    python scripts/make_prospective_validation_sample.py
    python scripts/make_prospective_validation_sample.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RW = ROOT / "corpus" / "real_world"
DEFAULT_OUTPUT = (
    ROOT / "corpus" / "annotations" / "prospective_validation_manifest.json"
)

FRAMEWORKS = ("adk", "autogen", "crewai", "langgraph")
SELF_REPO = "NordicAgents/AgentProof"
SELF_PREFIX = "NordicAgents__AgentProof"
DEFAULT_SEED = 20260728
DEFAULT_REPOS_PER_FRAMEWORK = 24
DEFAULT_HUMAN_PER_FRAMEWORK = 8


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def stable_seed(seed: int, namespace: str) -> int:
    digest = hashlib.sha256(f"{seed}:{namespace}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def colliding_slugs() -> set[str]:
    """Return slugs that represented more than one source path when mined."""
    paths_by_slug: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for filename in ("metadata.json", "metadata.lg_crew.json"):
        path = RW / filename
        if not path.exists():
            continue
        for record in load_json(path).get("records", []):
            slug = record.get("slug")
            repo = record.get("repo")
            file_path = record.get("file_path")
            if slug and repo and file_path:
                paths_by_slug[slug].add((repo, file_path))
    return {slug for slug, paths in paths_by_slug.items() if len(paths) > 1}


def build_frame() -> tuple[list[dict[str, Any]], dict[str, int]]:
    metadata = load_json(RW / "metadata_v2.json")
    collisions = colliding_slugs()
    exclusions: Counter[str] = Counter()
    frame: list[dict[str, Any]] = []

    for record in metadata["records"]:
        slug = record["slug"]
        framework = record.get("framework")
        repo = record.get("repo", "")
        source = RW / "sources" / f"{slug}.py"
        graph_v2 = RW / "graphs_v2" / f"{slug}.json"

        reason = None
        if record.get("status") != "extracted":
            reason = f"v2_status_{record.get('status', 'missing')}"
        elif framework not in FRAMEWORKS:
            reason = "unsupported_framework"
        elif repo == SELF_REPO or slug.startswith(SELF_PREFIX):
            reason = "self_repository"
        elif not record.get("sha") or not record.get("file_path"):
            reason = "incomplete_provenance"
        elif not graph_v2.exists():
            reason = "missing_v2_graph"
        elif not source.exists():
            reason = "missing_source_snapshot"

        if reason:
            exclusions[reason] += 1
            continue

        item = dict(record)
        item["workflow_id"] = (
            f"{repo}@{record['sha']}:{record['file_path']}"
        )
        item["historical_slug_collision"] = slug in collisions
        item["source_snapshot_path"] = str(source.relative_to(ROOT))
        item["source_sha256"] = sha256(source)
        item["v2_graph_path"] = str(graph_v2.relative_to(ROOT))
        item["source_url"] = (
            f"https://github.com/{repo}/blob/{record['sha']}/"
            f"{record['file_path']}"
        )
        frame.append(item)

    frame.sort(key=lambda item: (item["framework"], item["repo"], item["slug"]))
    return frame, dict(sorted(exclusions.items()))


def sample_manifest(
    *,
    seed: int,
    repos_per_framework: int,
    human_per_framework: int,
) -> dict[str, Any]:
    frame, exclusions = build_frame()
    by_framework_repo: dict[str, dict[str, list[dict[str, Any]]]] = {
        framework: defaultdict(list) for framework in FRAMEWORKS
    }
    for item in frame:
        by_framework_repo[item["framework"]][item["repo"]].append(item)

    sample: list[dict[str, Any]] = []
    frame_summary: dict[str, dict[str, int]] = {}
    for framework in FRAMEWORKS:
        repo_map = by_framework_repo[framework]
        repositories = sorted(repo_map)
        if len(repositories) < repos_per_framework:
            raise ValueError(
                f"{framework}: requested {repos_per_framework} repositories "
                f"but the eligible frame contains {len(repositories)}"
            )
        rng = random.Random(stable_seed(seed, f"audit:{framework}"))
        selected_repositories = sorted(
            rng.sample(repositories, repos_per_framework)
        )
        frame_summary[framework] = {
            "eligible_workflows": sum(len(items) for items in repo_map.values()),
            "eligible_repositories": len(repositories),
            "sampled_repositories": repos_per_framework,
        }
        repo_probability = repos_per_framework / len(repositories)

        for repo in selected_repositories:
            candidates = sorted(repo_map[repo], key=lambda item: item["slug"])
            chosen = rng.choice(candidates)
            within_repo_probability = 1 / len(candidates)
            inclusion_probability = repo_probability * within_repo_probability
            sample.append(
                {
                    "workflow_id": chosen["workflow_id"],
                    "legacy_slug": chosen["slug"],
                    "historical_slug_collision": chosen[
                        "historical_slug_collision"
                    ],
                    "framework": framework,
                    "repository": repo,
                    "commit_sha": chosen["sha"],
                    "source_path": chosen["file_path"],
                    "source_url": chosen["source_url"],
                    "source_snapshot_path": chosen["source_snapshot_path"],
                    "source_sha256": chosen["source_sha256"],
                    "v2_graph_path": chosen["v2_graph_path"],
                    "eligible_files_in_repository": len(candidates),
                    "repository_selection_probability": round(
                        repo_probability, 12
                    ),
                    "within_repository_selection_probability": round(
                        within_repo_probability, 12
                    ),
                    "workflow_inclusion_probability": round(
                        inclusion_probability, 12
                    ),
                    "design_weight": round(1 / inclusion_probability, 12),
                }
            )

    sample.sort(
        key=lambda item: (
            item["framework"],
            item["repository"],
            item["workflow_id"],
        )
    )

    human_ids: set[str] = set()
    for framework in FRAMEWORKS:
        candidates = [
            item["workflow_id"]
            for item in sample
            if item["framework"] == framework
        ]
        if len(candidates) < human_per_framework:
            raise ValueError(
                f"{framework}: human subsample size {human_per_framework} "
                f"exceeds audit sample size {len(candidates)}"
            )
        rng = random.Random(stable_seed(seed, f"human:{framework}"))
        human_ids.update(rng.sample(sorted(candidates), human_per_framework))

    for item in sample:
        item["independent_human_reconstruction"] = (
            item["workflow_id"] in human_ids
        )

    return {
        "_meta": {
            "schema_version": 1,
            "status": "frozen_before_annotation",
            "script": "scripts/make_prospective_validation_sample.py",
            "seed": seed,
            "repos_per_framework": repos_per_framework,
            "human_reconstructions_per_framework": human_per_framework,
            "outcome_blinding": (
                "The sampler reads no reference graphs, flags, triage labels, "
                "human-gate verdicts, or paper results."
            ),
            "estimand": (
                "Framework-specific file-level properties over the eligible "
                "corrected corpus; inverse-probability weights recover the "
                "eligible file distribution under the two-stage design."
            ),
            "generalization_boundary": (
                "Probability statements apply only to the fixed eligible "
                "corpus, not to GitHub, executable repository roots, private "
                "code, or deployed workflows."
            ),
            "post_sampling_rule": (
                "Two independent source audits cover all sampled workflows. "
                "Both humans reconstruct the frozen 32-workflow subsample. "
                "Both humans additionally label every candidate defect plus "
                "a seeded repository-disjoint sample of at least 32 workflows "
                "on which neither source audit reports a defect; this second "
                "sample is drawn only after predictions are locked."
            ),
        },
        "frame": {
            "source": "corpus/real_world/metadata_v2.json",
            "unit_key": "repository@commit_sha:source_path",
            "eligibility": [
                "v2 status is extracted",
                "framework is one of adk/autogen/crewai/langgraph",
                "submitting repository is excluded",
                "pinned SHA and source path are present",
                "corrected-v2 graph and its local source snapshot exist",
            ],
            "historical_collision_handling": (
                "The prospective unit is keyed by repository, commit, and "
                "source path rather than the legacy basename slug. Corrected "
                "v2 records and snapshots identify the exact selected file. "
                "Historically colliding records may enter this v2-only audit "
                "but are marked and must never be joined to v1 by slug."
            ),
            "n_eligible_workflows": len(frame),
            "n_eligible_repositories": len({item["repo"] for item in frame}),
            "by_framework": frame_summary,
            "exclusions_from_v2_metadata": exclusions,
        },
        "audit_sample": sample,
        "human_reconstruction_workflow_ids": sorted(human_ids),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--repos-per-framework",
        type=int,
        default=DEFAULT_REPOS_PER_FRAMEWORK,
    )
    parser.add_argument(
        "--human-per-framework",
        type=int,
        default=DEFAULT_HUMAN_PER_FRAMEWORK,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the existing output differs; do not write",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = sample_manifest(
        seed=args.seed,
        repos_per_framework=args.repos_per_framework,
        human_per_framework=args.human_per_framework,
    )
    rendered = json.dumps(manifest, indent=2, sort_keys=False) + "\n"

    if args.check:
        if not args.output.exists():
            print(f"missing manifest: {args.output}", file=sys.stderr)
            return 1
        if args.output.read_text(encoding="utf-8") != rendered:
            print(
                f"manifest differs from deterministic regeneration: "
                f"{args.output}",
                file=sys.stderr,
            )
            return 1
        print(f"prospective manifest is reproducible: {args.output}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(
        f"wrote {len(manifest['audit_sample'])} workflows and "
        f"{len(manifest['human_reconstruction_workflow_ids'])} human "
        f"reconstructions to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
