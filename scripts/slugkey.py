#!/usr/bin/env python3
"""Collision-free corpus keys.

The original mining key was ``<repo-with-slashes-escaped>__<file basename>``
(``mine_github_gh.py``). That is NOT unique: a repository that contains
``AutoGen/sample_agent.py`` and ``LangGraph/sample_agent.py`` maps both to the
same slug, and because the miner wrote ``out_dir / f"{slug}.json"`` the later
file silently overwrote the earlier one. 76 slugs in the mined corpus are
affected. Downstream, ``remine_pinned.load_records`` resolved the same slug
first-wins, which is a *different* tie-break than the miner's last-wins, so the
v1 and v2 graphs for such a slug can come from two different programs -- and
any v1-vs-v2 comparison over them measures program difference, not instrument
difference.

``stable_key`` keys on repo + FULL file path, so collisions cannot occur.
``legacy_slug`` reproduces the old scheme so existing on-disk artifacts (which
are named by the old scheme) remain addressable, and ``ambiguous_slugs`` finds
the legacy slugs that cannot be resolved to a single file.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
_MAX = 180  # keep well inside filesystem name limits


def legacy_slug(repo: str, file_path: str) -> str:
    """The original, COLLIDING scheme: repo + file basename. Kept for lookup only."""
    stem = file_path.rstrip("/").rsplit("/", 1)[-1]
    if stem.endswith(".py"):
        stem = stem[:-3]
    return f"{repo.replace('/', '__')}__{stem}"


def stable_key(repo: str, file_path: str) -> str:
    """Collision-free key: repo + full path, escaped; hash-suffixed if over-long.

    Injective on (repo, file_path): the escape is applied to the full path, and
    whenever escaping or truncation could lose information a SHA-1 of the exact
    (repo, file_path) pair is appended.
    """
    safe_repo = _UNSAFE.sub("-", repo.replace("/", "__"))
    path = file_path.strip("/")
    if path.endswith(".py"):
        path = path[:-3]
    safe_path = _UNSAFE.sub("-", path.replace("/", "__"))
    key = f"{safe_repo}__{safe_path}"
    digest = hashlib.sha1(f"{repo}\0{file_path}".encode()).hexdigest()[:12]
    # Escaping is lossy (distinct chars collapse to '-'); append the digest
    # whenever anything was rewritten or the name must be truncated.
    lossy = safe_path != path.replace("/", "__") or safe_repo != repo.replace("/", "__")
    if lossy or len(key) > _MAX:
        key = f"{safe_repo}__{safe_path}"[: _MAX - 13] + f"__{digest}"
    return key


def ambiguous_slugs(records) -> dict[str, list[dict]]:
    """Legacy slugs claimed by more than one distinct (repo, sha, file_path).

    ``records`` is any iterable of dicts with repo/sha/file_path/slug keys.
    Returns {legacy_slug: [record, ...]} for the ambiguous ones only.
    """
    seen: dict[str, set] = defaultdict(set)
    detail: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        slug = r.get("slug") or legacy_slug(r.get("repo", ""), r.get("file_path", ""))
        ident = (r.get("repo"), r.get("sha"), r.get("file_path"))
        if ident not in seen[slug]:
            seen[slug].add(ident)
            detail[slug].append(r)
    return {s: d for s, d in detail.items() if len(d) > 1}


def assert_unique(records) -> None:
    """Raise if the stable keys of `records` are not unique (defensive; should never fire)."""
    keys: dict[str, tuple] = {}
    for r in records:
        k = stable_key(r["repo"], r["file_path"])
        ident = (r["repo"], r["sha"], r["file_path"])
        if k in keys and keys[k] != ident:
            raise ValueError(f"stable_key collision on {k!r}: {keys[k]} vs {ident}")
        keys[k] = ident
