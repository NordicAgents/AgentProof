#!/usr/bin/env python3
"""Re-extract the mined corpus at its pinned commit SHAs with the current extractor.

For every graph in ``corpus/real_world/graphs/`` this script looks up its
provenance record (repo, commit SHA, file path) in ``metadata.json`` /
``metadata.lg_crew.json``, shallow-fetches exactly that commit from GitHub,
snapshots the source file to ``corpus/real_world/sources/<slug>.py``, and runs
the current AST extractor into ``corpus/real_world/graphs_v2/<slug>.json``.
The original ``graphs/`` directory is never modified, so v1 (as-mined
instrument) and v2 (corrected instrument) can be compared side by side.

It also records the committer date of every pinned SHA: the maximum pinned
commit date is a hard lower bound on when mining ran, which is evidence for
the paper's mining-window statement.

Failures are recorded by category rather than silently dropped:
  repo_unreachable   clone/fetch of the repository failed entirely
  sha_unreachable    the repository exists but the pinned SHA cannot be fetched
                     (force-pushed away or GC'd) -- we do NOT substitute HEAD
  path_missing       the recorded file path does not exist at the pinned SHA
  no_graph           the extractor returned no graph for the source file

Usage:
    python scripts/remine_pinned.py                 # full run (resumable)
    python scripts/remine_pinned.py --limit 3       # smoke test on 3 repo groups
    python scripts/remine_pinned.py --workers 12
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ast_extractor import extract_graph_from_source  # noqa: E402
from slugkey import ambiguous_slugs, stable_key  # noqa: E402

REAL_WORLD = ROOT / "corpus" / "real_world"
GRAPHS_V1 = REAL_WORLD / "graphs"
GRAPHS_V2 = REAL_WORLD / "graphs_v2"
SOURCES = REAL_WORLD / "sources"
OUT_MANIFEST = REAL_WORLD / "metadata_v2.json"

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def run_git(args: list[str], cwd: Path | None = None, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
    )


def load_records() -> list[dict]:
    """Provenance records for every v1 graph on disk.

    The legacy slug (repo + file BASENAME) is not unique: 76 slugs in the mined
    corpus are claimed by more than one file. This function used to resolve
    such a slug FIRST-WINS, silently. That is unsound, because the v1 miner
    resolved the same slug LAST-WINS (it wrote ``<slug>.json`` per file, so the
    last file with that basename overwrote the earlier ones) and did not record
    which file survived. A first-wins re-mine can therefore extract a totally
    different program and present it as the same workflow.

    Ambiguous slugs are now marked ``ambiguous_slug`` and NOT re-mined, so they
    can never contaminate a v1-vs-v2 comparison. Every record also carries a
    collision-free ``key`` (repo + full path) for future runs.
    """
    on_disk = {p.stem for p in GRAPHS_V1.glob("*.json")}
    all_recs: list[dict] = []
    for name in ("metadata.json", "metadata.lg_crew.json"):
        meta = json.loads((REAL_WORLD / name).read_text())
        all_recs.extend(r for r in meta["records"]
                        if r.get("slug") in on_disk and r.get("sha"))
    ambiguous = ambiguous_slugs(all_recs)

    records: dict[str, dict] = {}
    for rec in all_recs:
        slug = rec["slug"]
        if slug in records:
            continue
        entry = {
            "slug": slug,
            "key": stable_key(rec["repo"], rec["file_path"]),
            "repo": rec["repo"],
            "sha": rec["sha"],
            "file_path": rec["file_path"],
            "framework": rec["framework"],
        }
        if slug in ambiguous:
            # Unusable: v1's file for this slug was not recorded and cannot be
            # recovered, so no honest pairing exists.
            entry["ambiguous_candidates"] = [
                {"repo": c["repo"], "sha": c["sha"], "file_path": c["file_path"],
                 "framework": c.get("framework")}
                for c in ambiguous[slug]
            ]
            entry["status"] = "ambiguous_slug"
        records[slug] = entry

    if ambiguous:
        log(f"WARNING: {len(ambiguous)} on-disk slugs have ambiguous provenance "
            f"(same repo+basename, different files); marked ambiguous_slug and NOT re-mined.")
    missing = sorted(on_disk - set(records))
    if missing:
        log(f"WARNING: {len(missing)} on-disk graphs have no provenance record: {missing[:5]}...")
    return sorted(records.values(), key=lambda r: r["slug"])


def fetch_pinned(repo: str, sha: str, dest: Path) -> tuple[str, str]:
    """Fetch exactly `sha` from GitHub into dest. Returns (status, commit_date)."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    url = f"https://github.com/{repo}.git"
    try:
        run_git(["init", "-q"], cwd=dest, timeout=30)
        run_git(["remote", "add", "origin", url], cwd=dest, timeout=30)
        shallow = run_git(["fetch", "--depth", "1", "-q", "origin", sha], cwd=dest, timeout=300)
        if shallow.returncode != 0:
            # Repo reachable at all? Distinguish repo_unreachable from sha_unreachable.
            probe = run_git(["ls-remote", "--heads", url], timeout=120)
            if probe.returncode != 0:
                return "repo_unreachable", ""
            full = run_git(["fetch", "-q", "origin", sha], cwd=dest, timeout=300)
            if full.returncode != 0:
                return "sha_unreachable", ""
        co = run_git(["-c", "advice.detachedHead=false", "checkout", "-q", sha], cwd=dest, timeout=120)
        if co.returncode != 0:
            return "sha_unreachable", ""
        date = run_git(["show", "-s", "--format=%cI", sha], cwd=dest, timeout=30)
        return "ok", date.stdout.strip()
    except subprocess.TimeoutExpired:
        return "repo_unreachable", ""


def process_group(repo: str, sha: str, recs: list[dict], workdir: Path) -> list[dict]:
    """Clone one (repo, sha) and re-extract all its recorded files."""
    results: list[dict] = []
    dest = workdir / f"{repo.replace('/', '__')}@{sha[:7]}"
    status, commit_date = fetch_pinned(repo, sha, dest)
    if status != "ok":
        for r in recs:
            results.append({**r, "status": status, "commit_date": ""})
        shutil.rmtree(dest, ignore_errors=True)
        return results

    for r in recs:
        src = dest / r["file_path"]
        entry = {**r, "commit_date": commit_date}
        if not src.is_file():
            entry["status"] = "path_missing"
        else:
            (SOURCES / f"{r['slug']}.py").write_text(src.read_text(errors="ignore"))
            graph = extract_graph_from_source(src, r["framework"])
            if graph is None:
                entry["status"] = "no_graph"
            else:
                graph["name"] = r["slug"]
                (GRAPHS_V2 / f"{r['slug']}.json").write_text(json.dumps(graph, indent=1))
                entry["status"] = "extracted"
                entry["n_nodes"] = len(graph.get("nodes", []))
                entry["n_edges"] = len(graph.get("edges", []))
        results.append(entry)
    shutil.rmtree(dest, ignore_errors=True)
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int, default=0, help="only process the first N repo groups (smoke test)")
    ap.add_argument("--workdir", default="", help="scratch dir for clones (default: <repo>/.remine_tmp)")
    args = ap.parse_args()

    workdir = Path(args.workdir) if args.workdir else ROOT / ".remine_tmp"
    workdir.mkdir(parents=True, exist_ok=True)
    GRAPHS_V2.mkdir(parents=True, exist_ok=True)
    SOURCES.mkdir(parents=True, exist_ok=True)

    records = load_records()
    # Ambiguous-slug records are carried through to the manifest with their
    # status but are never fetched or extracted.
    ambiguous_records = [r for r in records if r.get("status") == "ambiguous_slug"]
    records = [r for r in records if r.get("status") != "ambiguous_slug"]
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in records:
        groups.setdefault((r["repo"], r["sha"]), []).append(r)
    group_items = sorted(groups.items())
    if args.limit:
        group_items = group_items[: args.limit]

    # Resume: skip groups whose every record already has a v2 graph or source snapshot decision.
    done_slugs = {p.stem for p in GRAPHS_V2.glob("*.json")}
    prior: list[dict] = []
    if OUT_MANIFEST.exists():
        prior = json.loads(OUT_MANIFEST.read_text()).get("records", [])
    prior_by_slug = {p["slug"]: p for p in prior}
    pending, results = [], []
    for key, recs in group_items:
        if all(r["slug"] in done_slugs or prior_by_slug.get(r["slug"], {}).get("status") in
               ("path_missing", "no_graph", "repo_unreachable", "sha_unreachable") for r in recs):
            results.extend(prior_by_slug.get(r["slug"], {**r, "status": "extracted"}) for r in recs)
        else:
            pending.append((key, recs))

    log(f"{len(records)} records in {len(group_items)} (repo, sha) groups; "
        f"{len(pending)} groups to fetch, {len(group_items) - len(pending)} already done")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_group, repo, sha, recs, workdir): (repo, sha)
                for (repo, sha), recs in pending}
        done_n = 0
        for fut in as_completed(futs):
            repo, sha = futs[fut]
            try:
                results.extend(fut.result())
            except Exception as e:  # keep going; record the crash
                results.extend({**r, "status": f"error:{type(e).__name__}", "commit_date": ""}
                               for r in groups[(repo, sha)])
            done_n += 1
            if done_n % 10 == 0 or done_n == len(pending):
                log(f"  progress: {done_n}/{len(pending)} groups")

    results.extend({**r, "commit_date": ""} for r in ambiguous_records)
    results.sort(key=lambda r: r["slug"])
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    dates = sorted(r["commit_date"] for r in results if r.get("commit_date"))
    summary = {
        "n_records": len(results),
        "by_status": by_status,
        "pinned_commit_date_min": dates[0] if dates else "",
        "pinned_commit_date_max": dates[-1] if dates else "",
        "note": ("max pinned commit date is a hard LOWER bound on when mining ran; "
                 "extractor = working-tree scripts/ast_extractor.py (post path_map/LoopAgent fixes)"),
    }
    OUT_MANIFEST.write_text(json.dumps({"summary": summary, "records": results}, indent=1))
    log(json.dumps(summary, indent=1))
    shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
