#!/usr/bin/env python3
"""Mine GitHub for real agent workflows using the authenticated `gh` CLI.

This is a drop-in alternative to ``scrape_workflows.py`` that requires no
PyGithub and no GITHUB_TOKEN env var -- it shells out to an already
authenticated ``gh`` CLI (``gh auth status`` must be green). It searches
GitHub code search for the four supported frameworks, shallow-clones the
unique repositories, scans them for workflow files, and runs the AST-based
extractor. Extracted graphs plus full provenance (repo, commit SHA, path,
stars, URL) are written to ``corpus/real_world/``.

Usage:
    python scripts/mine_github_gh.py --search            # search only, cache candidates
    python scripts/mine_github_gh.py --clone --extract   # clone + extract from cached candidates
    python scripts/mine_github_gh.py --all --max-repos 120 --per-query 40
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Reuse the existing extractor + scanner from the sibling scripts.
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ast_extractor import extract_graph_from_source  # noqa: E402
from scrape_workflows import find_workflow_files  # noqa: E402

# (framework, code-search query). Kept aligned with scrape_workflows.SEARCH_QUERIES.
SEARCH_QUERIES: list[tuple[str, str]] = [
    ("langgraph", 'StateGraph add_node language:python'),
    ("langgraph", 'StateGraph add_conditional_edges language:python'),
    ("langgraph", 'from langgraph.graph add_edge language:python'),
    ("crewai", 'from crewai Crew Task language:python'),
    ("crewai", 'crewai "process=Process" language:python'),
    ("autogen", 'GroupChat autogen language:python'),
    ("autogen", 'RoundRobinGroupChat language:python'),
    ("autogen", 'SelectorGroupChat language:python'),
    ("adk", 'SequentialAgent google.adk language:python'),
    ("adk", 'from google.adk Agent language:python'),
    ("adk", 'ParallelAgent google.adk language:python'),
]


def gh_search(query: str, per_query: int) -> list[dict]:
    """Run one `gh search code` query and return parsed items."""
    cmd = [
        "gh", "search", "code", query,
        "--limit", str(per_query),
        "--json", "repository,path,url,sha",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        print(f"    timeout on query: {query[:60]}")
        return []
    if proc.returncode != 0:
        print(f"    gh error ({proc.returncode}): {proc.stderr.strip()[:160]}")
        return []
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []


def search(per_query: int) -> list[dict]:
    """Search all framework queries, dedup by (repo, path)."""
    results: list[dict] = []
    seen: set[str] = set()
    for framework, query in SEARCH_QUERIES:
        print(f"Searching [{framework}]: {query}")
        items = gh_search(query, per_query)
        added = 0
        for item in items:
            repo = item.get("repository", {})
            full_name = repo.get("nameWithOwner") or repo.get("full_name")
            path = item.get("path")
            if not full_name or not path:
                continue
            key = f"{full_name}:{path}"
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "framework": framework,
                "repo": full_name,
                "file_path": path,
                "url": item.get("url", ""),
                "sha": item.get("sha", ""),
            })
            added += 1
        print(f"    +{added} candidates ({len(results)} total)")
        time.sleep(3)  # code-search rate-limit courtesy
    return results


def repo_stars(full_name: str) -> int | None:
    """Fetch stargazer count for a repo via `gh api` (best effort)."""
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{full_name}", "--jq", ".stargazers_count"],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode == 0 and proc.stdout.strip().isdigit():
            return int(proc.stdout.strip())
    except subprocess.TimeoutExpired:
        pass
    return None


def clone_repos(candidates: list[dict], clone_dir: Path, max_repos: int) -> dict[str, dict]:
    """Shallow-clone unique repos (capped). Returns repo -> {path, sha, stars}."""
    clone_dir.mkdir(parents=True, exist_ok=True)
    unique: list[str] = []
    for c in candidates:
        if c["repo"] not in unique:
            unique.append(c["repo"])
    unique = unique[:max_repos]

    repos: dict[str, dict] = {}
    for i, repo_name in enumerate(unique, 1):
        safe = repo_name.replace("/", "__")
        dest = clone_dir / safe
        if not dest.exists():
            print(f"[{i}/{len(unique)}] cloning {repo_name}")
            url = f"https://github.com/{repo_name}.git"
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", "--quiet", url, str(dest)],
                    timeout=180, check=True, capture_output=True,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                print(f"    clone failed: {str(e)[:100]}")
                continue
        else:
            print(f"[{i}/{len(unique)}] cached {repo_name}")
        # commit SHA for reproducibility
        try:
            sha = subprocess.run(
                ["git", "-C", str(dest), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=15,
            ).stdout.strip()
        except subprocess.TimeoutExpired:
            sha = ""
        repos[repo_name] = {"path": str(dest), "sha": sha, "stars": repo_stars(repo_name)}
    return repos


def extract_all(repos: dict[str, dict], out_dir: Path, sources_dir: Path) -> dict:
    """Scan every cloned repo for workflow files and AST-extract graphs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    n_files_scanned = 0
    n_extracted = 0

    for repo_name, info in repos.items():
        repo_path = Path(info["path"])
        wf_files = find_workflow_files(repo_path)
        for wf_file, framework in wf_files:
            n_files_scanned += 1
            rel = str(wf_file.relative_to(repo_path))
            slug = f"{repo_name.replace('/', '__')}__{wf_file.stem}"
            graph = None
            try:
                graph = extract_graph_from_source(wf_file, framework)
            except Exception as e:  # noqa: BLE001 - extractor must never crash the run
                records.append({
                    "repo": repo_name, "file_path": rel, "framework": framework,
                    "sha": info["sha"], "stars": info["stars"],
                    "status": "extractor_error", "error": str(e)[:200], "slug": slug,
                })
                continue

            if graph is None:
                records.append({
                    "repo": repo_name, "file_path": rel, "framework": framework,
                    "sha": info["sha"], "stars": info["stars"],
                    "status": "no_graph", "slug": slug,
                })
                continue

            graph["name"] = slug
            real_nodes = [n for n in graph["nodes"] if n["kind"] not in ("entry", "exit")]
            out_path = out_dir / f"{slug}.json"
            out_path.write_text(json.dumps(graph, indent=2))
            # snapshot the source file for downstream manual validation
            src_snap = sources_dir / f"{slug}.py"
            try:
                src_snap.write_text(wf_file.read_text(errors="ignore"))
            except Exception:  # noqa: BLE001
                pass
            n_extracted += 1
            records.append({
                "repo": repo_name, "file_path": rel, "framework": framework,
                "sha": info["sha"], "stars": info["stars"], "url":
                    f"https://github.com/{repo_name}/blob/{info['sha']}/{rel}",
                "status": "extracted", "slug": slug,
                "n_nodes": len(graph["nodes"]), "n_real_nodes": len(real_nodes),
                "n_edges": len(graph["edges"]),
                "source_snapshot": str(src_snap),
            })
            print(f"    extracted {slug} ({len(real_nodes)} nodes, {len(graph['edges'])} edges)")

    return {
        "n_repos": len(repos),
        "n_files_scanned": n_files_scanned,
        "n_extracted": n_extracted,
        "records": records,
    }


def stream_mine(candidates: list[dict], clone_dir: Path, out_dir: Path,
                sources_dir: Path, max_repos: int, cleanup: bool) -> dict:
    """Clone -> extract -> (optionally) delete each repo in turn, so disk never
    accumulates all clones at once. Disk-safe alternative to clone-all-then-extract."""
    clone_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    unique: list[str] = []
    for c in candidates:
        if c["repo"] not in unique:
            unique.append(c["repo"])
    unique = unique[:max_repos]

    records: list[dict] = []
    repos_meta: dict[str, dict] = {}
    n_scanned = n_extracted = 0
    for i, repo_name in enumerate(unique, 1):
        safe = repo_name.replace("/", "__")
        dest = clone_dir / safe
        if not dest.exists():
            url = f"https://github.com/{repo_name}.git"
            try:
                subprocess.run(["git", "clone", "--depth", "1", "--quiet", url, str(dest)],
                               timeout=180, check=True, capture_output=True)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                print(f"[{i}/{len(unique)}] clone failed: {repo_name}")
                continue
        try:
            sha = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"],
                                 capture_output=True, text=True, timeout=15).stdout.strip()
        except subprocess.TimeoutExpired:
            sha = ""
        repos_meta[repo_name] = {"path": str(dest), "sha": sha, "stars": repo_stars(repo_name)}
        for wf_file, fw in find_workflow_files(dest):
            n_scanned += 1
            rel = str(wf_file.relative_to(dest))
            slug = f"{safe}__{wf_file.stem}"
            try:
                graph = extract_graph_from_source(wf_file, fw)
            except Exception as e:  # noqa: BLE001
                records.append({"repo": repo_name, "file_path": rel, "framework": fw,
                                "sha": sha, "status": "extractor_error", "error": str(e)[:200], "slug": slug})
                continue
            if graph is None:
                records.append({"repo": repo_name, "file_path": rel, "framework": fw,
                                "sha": sha, "status": "no_graph", "slug": slug})
                continue
            graph["name"] = slug
            real = [n for n in graph["nodes"] if n["kind"] not in ("entry", "exit")]
            (out_dir / f"{slug}.json").write_text(json.dumps(graph, indent=2))
            try:
                (sources_dir / f"{slug}.py").write_text(wf_file.read_text(errors="ignore"))
            except Exception:  # noqa: BLE001
                pass
            n_extracted += 1
            records.append({"repo": repo_name, "file_path": rel, "framework": fw,
                            "sha": sha, "stars": repos_meta[repo_name]["stars"],
                            "url": f"https://github.com/{repo_name}/blob/{sha}/{rel}",
                            "status": "extracted", "slug": slug,
                            "n_nodes": len(graph["nodes"]), "n_real_nodes": len(real),
                            "n_edges": len(graph["edges"]),
                            "source_snapshot": str(sources_dir / f"{slug}.py")})
        print(f"[{i}/{len(unique)}] {repo_name}: extracted so far {n_extracted}", flush=True)
        if cleanup:
            shutil.rmtree(dest, ignore_errors=True)
    return {"n_repos": len(unique), "n_files_scanned": n_scanned,
            "n_extracted": n_extracted, "records": records, "repos": repos_meta}


def main() -> None:
    ap = argparse.ArgumentParser(description="Mine GitHub for agent workflows via gh CLI")
    ap.add_argument("--search", action="store_true", help="run code search, cache candidates")
    ap.add_argument("--clone", action="store_true", help="clone cached candidate repos")
    ap.add_argument("--extract", action="store_true", help="extract graphs from cloned repos")
    ap.add_argument("--all", action="store_true", help="search + clone + extract")
    ap.add_argument("--per-query", type=int, default=40)
    ap.add_argument("--max-repos", type=int, default=120)
    ap.add_argument("--clone-dir", type=str, default=None)
    ap.add_argument("--out-root", type=str, default="corpus/real_world")
    ap.add_argument("--frameworks", type=str, default=None,
                    help="comma-separated subset to include, e.g. autogen,adk")
    ap.add_argument("--cleanup", action="store_true",
                    help="stream mode: clone->extract->delete each repo (disk-safe)")
    args = ap.parse_args()

    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    candidates_path = out_root / "candidates.json"
    repos_path = out_root / "repos.json"
    graphs_dir = out_root / "graphs"
    sources_dir = out_root / "sources"
    meta_path = out_root / "metadata.json"

    clone_dir = Path(args.clone_dir) if args.clone_dir else out_root / "_repos"

    do_search = args.search or args.all
    do_clone = args.clone or args.all
    do_extract = args.extract or args.all

    if do_search:
        candidates = search(args.per_query)
        candidates_path.write_text(json.dumps(candidates, indent=2))
        print(f"\nSaved {len(candidates)} candidates to {candidates_path}")
    else:
        candidates = json.loads(candidates_path.read_text()) if candidates_path.exists() else []

    if args.frameworks:
        keep = {f.strip() for f in args.frameworks.split(",")}
        before = len(candidates)
        candidates = [c for c in candidates if c["framework"] in keep]
        print(f"Filtered to {sorted(keep)}: {len(candidates)}/{before} candidates")

    if args.cleanup and do_clone and do_extract:
        meta = stream_mine(candidates, clone_dir, graphs_dir, sources_dir, args.max_repos, cleanup=True)
        repos_path.write_text(json.dumps(meta.pop("repos"), indent=2))
        meta_path.write_text(json.dumps(meta, indent=2))
        print(f"\n=== Extraction summary (stream) ===")
        print(f"repos scanned:   {meta['n_repos']}")
        print(f"files scanned:   {meta['n_files_scanned']}")
        print(f"graphs extracted:{meta['n_extracted']}")
        print(f"metadata -> {meta_path}")
        return

    if do_clone:
        repos = clone_repos(candidates, clone_dir, args.max_repos)
        repos_path.write_text(json.dumps(repos, indent=2))
        print(f"\nCloned {len(repos)} repos; metadata -> {repos_path}")
    else:
        repos = json.loads(repos_path.read_text()) if repos_path.exists() else {}

    if do_extract:
        meta = extract_all(repos, graphs_dir, sources_dir)
        meta_path.write_text(json.dumps(meta, indent=2))
        print(f"\n=== Extraction summary ===")
        print(f"repos scanned:   {meta['n_repos']}")
        print(f"files scanned:   {meta['n_files_scanned']}")
        print(f"graphs extracted:{meta['n_extracted']}")
        print(f"metadata -> {meta_path}")


if __name__ == "__main__":
    main()
