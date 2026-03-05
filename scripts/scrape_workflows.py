#!/usr/bin/env python3
"""Search GitHub for real agent workflow definitions, clone repos, and extract graphs.

Requires: pip install PyGithub
Requires: GITHUB_TOKEN environment variable

Usage:
    GITHUB_TOKEN=ghp_... python scripts/scrape_workflows.py
    GITHUB_TOKEN=ghp_... python scripts/scrape_workflows.py --max-per-query 50 --clone-dir /tmp/agentproof_repos
    # Extract graphs from already-cloned repos:
    python scripts/scrape_workflows.py --extract-only --clone-dir /tmp/agentproof_repos
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SEARCH_QUERIES = [
    # LangGraph
    ("langgraph", 'language:Python "StateGraph" "add_node"'),
    ("langgraph", 'language:Python "StateGraph" "add_conditional_edges"'),
    ("langgraph", 'language:Python "from langgraph" "add_edge"'),
    # CrewAI
    ("crewai", 'language:Python "from crewai" "Crew(" "Task("'),
    ("crewai", 'language:Python "crewai" "process=Process"'),
    ("crewai", 'language:Python "from crewai" "sequential"'),
    # AutoGen
    ("autogen", 'language:Python "GroupChat" "autogen"'),
    ("autogen", 'language:Python "RoundRobinGroupChat" "autogen"'),
    ("autogen", 'language:Python "SelectorGroupChat" "autogen"'),
    # Google ADK
    ("adk", 'language:Python "SequentialAgent" "google.adk"'),
    ("adk", 'language:Python "from google.adk" "Agent"'),
    ("adk", 'language:Python "ParallelAgent" "google.adk"'),
]

# Patterns used to detect framework usage via simple text matching
FRAMEWORK_FILE_PATTERNS: dict[str, list[str]] = {
    "langgraph": ["StateGraph", "add_node", "add_edge"],
    "crewai": ["Crew(", "Task(", "from crewai"],
    "autogen": ["GroupChat", "RoundRobinGroupChat", "SelectorGroupChat"],
    "adk": ["SequentialAgent", "ParallelAgent", "LoopAgent", "from google.adk"],
}


def search_github(token: str, max_per_query: int) -> list[dict]:
    """Search GitHub Code Search API for workflow files."""
    from github import Github, GithubException

    g = Github(token)
    results: list[dict] = []
    seen: set[str] = set()  # track (repo, file_path) pairs

    for framework, query in SEARCH_QUERIES:
        print(f"Searching: {query[:70]}...")
        try:
            code_results = g.search_code(query)
            count = 0
            for item in code_results:
                if count >= max_per_query:
                    break
                key = f"{item.repository.full_name}:{item.path}"
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "framework": framework,
                    "repo": item.repository.full_name,
                    "file_path": item.path,
                    "url": item.html_url,
                    "repo_stars": item.repository.stargazers_count,
                    "clone_url": item.repository.clone_url,
                })
                count += 1
                print(f"  [{count}] {item.repository.full_name}/{item.path} "
                      f"({item.repository.stargazers_count} stars)")
            # Rate-limit courtesy
            time.sleep(2)
        except GithubException as e:
            print(f"  GitHub API error: {e}")
        except Exception as e:
            print(f"  Error: {e}")

    return results


def clone_repos(results: list[dict], clone_dir: Path) -> dict[str, Path]:
    """Clone unique repos into clone_dir. Returns mapping of repo name to local path."""
    clone_dir.mkdir(parents=True, exist_ok=True)
    repos: dict[str, Path] = {}

    unique_repos = {}
    for r in results:
        if r["repo"] not in unique_repos:
            unique_repos[r["repo"]] = r.get("clone_url", f"https://github.com/{r['repo']}.git")

    for repo_name, clone_url in unique_repos.items():
        safe_name = repo_name.replace("/", "__")
        dest = clone_dir / safe_name
        if dest.exists():
            print(f"  Already cloned: {repo_name}")
            repos[repo_name] = dest
            continue
        print(f"  Cloning {repo_name}...")
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", "--quiet", clone_url, str(dest)],
                timeout=120,
                check=True,
                capture_output=True,
            )
            repos[repo_name] = dest
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"    Failed to clone {repo_name}: {e}")

    return repos


def detect_framework(file_path: Path) -> str | None:
    """Detect which framework a Python file uses via simple text matching."""
    try:
        text = file_path.read_text(errors="ignore")
    except Exception:
        return None
    for fw, patterns in FRAMEWORK_FILE_PATTERNS.items():
        if sum(1 for p in patterns if p in text) >= 2:
            return fw
    return None


def find_workflow_files(repo_path: Path) -> list[tuple[Path, str]]:
    """Find Python files in a repo that use a known framework."""
    found: list[tuple[Path, str]] = []
    for py_file in repo_path.rglob("*.py"):
        # Skip tests, venvs, and hidden dirs
        parts = py_file.relative_to(repo_path).parts
        if any(p.startswith(".") or p in ("venv", ".venv", "node_modules", "__pycache__") for p in parts):
            continue
        fw = detect_framework(py_file)
        if fw:
            found.append((py_file, fw))
    return found


def extract_with_ast(file_path: Path, framework: str) -> dict | None:
    """Try AST-based extraction (imported from ast_extractor module)."""
    try:
        from ast_extractor import extract_graph_from_source
        return extract_graph_from_source(file_path, framework)
    except ImportError:
        # ast_extractor not available, try inline
        pass
    except Exception:
        pass
    return None


def extract_workflows(
    results: list[dict],
    repos: dict[str, Path],
    output_dir: Path,
) -> dict:
    """Attempt to extract AgentGraph JSON from each discovered workflow file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata: list[dict] = []
    extracted_count = 0
    failed_count = 0

    # Add ast_extractor to path
    scripts_dir = Path(__file__).parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    for entry in results:
        repo_name = entry["repo"]
        if repo_name not in repos:
            continue

        repo_path = repos[repo_name]
        file_path = repo_path / entry["file_path"]

        if not file_path.exists():
            # Search for file by name
            candidates = list(repo_path.rglob(Path(entry["file_path"]).name))
            if candidates:
                file_path = candidates[0]
            else:
                metadata.append({**entry, "status": "file_not_found"})
                failed_count += 1
                continue

        framework = entry["framework"]
        graph_dict = extract_with_ast(file_path, framework)

        if graph_dict:
            safe_name = f"{repo_name.replace('/', '__')}__{file_path.stem}"
            out_path = output_dir / f"{safe_name}.json"
            out_path.write_text(json.dumps(graph_dict, indent=2))
            metadata.append({**entry, "status": "extracted", "output": str(out_path)})
            extracted_count += 1
            print(f"  Extracted: {repo_name}/{entry['file_path']}")
        else:
            metadata.append({**entry, "status": "extraction_failed"})
            failed_count += 1

    # Also scan cloned repos for additional workflow files not in search results
    seen_files = {(e["repo"], e["file_path"]) for e in results}
    for repo_name, repo_path in repos.items():
        for wf_file, fw in find_workflow_files(repo_path):
            rel = str(wf_file.relative_to(repo_path))
            if (repo_name, rel) in seen_files:
                continue
            seen_files.add((repo_name, rel))

            graph_dict = extract_with_ast(wf_file, fw)
            if graph_dict:
                safe_name = f"{repo_name.replace('/', '__')}__{wf_file.stem}"
                out_path = output_dir / f"{safe_name}.json"
                out_path.write_text(json.dumps(graph_dict, indent=2))
                metadata.append({
                    "framework": fw,
                    "repo": repo_name,
                    "file_path": rel,
                    "status": "extracted",
                    "output": str(out_path),
                    "source": "repo_scan",
                })
                extracted_count += 1
                print(f"  Extracted (scan): {repo_name}/{rel}")

    print(f"\nExtraction: {extracted_count} succeeded, {failed_count} failed")
    return {
        "total_attempted": len(results),
        "extracted": extracted_count,
        "failed": failed_count,
        "details": metadata,
    }


def main():
    parser = argparse.ArgumentParser(description="Mine GitHub for real agent workflows")
    parser.add_argument("--max-per-query", type=int, default=30,
                        help="Max results per GitHub search query")
    parser.add_argument("--clone-dir", type=str, default="/tmp/agentproof_repos",
                        help="Directory to clone repos into")
    parser.add_argument("--output-dir", type=str, default="corpus/real_world/graphs",
                        help="Output directory for extracted graphs")
    parser.add_argument("--extract-only", action="store_true",
                        help="Skip GitHub search, extract from already-cloned repos")
    parser.add_argument("--search-results", type=str,
                        default="corpus/real_world/search_results.json",
                        help="Path to save/load search results")
    args = parser.parse_args()

    clone_dir = Path(args.clone_dir)
    output_dir = Path(args.output_dir)
    search_file = Path(args.search_results)

    if args.extract_only:
        if not search_file.exists():
            print(f"No search results at {search_file}. Run without --extract-only first.")
            sys.exit(1)
        results = json.loads(search_file.read_text())
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            print("Set GITHUB_TOKEN environment variable.")
            sys.exit(1)

        try:
            from github import Github  # noqa: F401
        except ImportError:
            print("PyGithub not installed. Install with: pip install PyGithub")
            sys.exit(1)

        results = search_github(token, args.max_per_query)
        search_file.parent.mkdir(parents=True, exist_ok=True)
        search_file.write_text(json.dumps(results, indent=2))
        print(f"\nFound {len(results)} files. Saved to {search_file}")

    # Clone
    repos = clone_repos(results, clone_dir)
    print(f"Cloned {len(repos)} repos to {clone_dir}")

    # Extract
    extraction_meta = extract_workflows(results, repos, output_dir)

    # Save metadata
    meta_path = Path("corpus/real_world/metadata.json")
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(extraction_meta, indent=2))
    print(f"Metadata written to {meta_path}")


if __name__ == "__main__":
    main()
