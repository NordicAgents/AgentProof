"""AP-RepairBench task schema (Paper 2, plan §5).

A :class:`RepairTask` is the immutable unit of the benchmark. It bundles a
policy-violating agent graph, the authoritative formal policy it violates, the
expected tri-valued verdict, a feasible violating trace, provenance/licensing
metadata, and a benign regression bundle. The schema deliberately keeps every
heavy field (the graph, the policy, the tool schemas, the trace) as plain
JSON-friendly ``dict``/``list`` data so a task round-trips through
:meth:`RepairTask.to_dict` / :meth:`RepairTask.from_dict` with no framework
imports and no code execution.

Field taxonomy mirrors plan §5 ("Each task requires …"):

* ``task_id``            — stable unique id.
* ``slice``              — which benchmark stratum this task belongs to; one of
  :data:`VALID_SLICES`. Real, mutated-real, official-example, and adversarial
  results are always reported **separately** (plan §5.1).
* ``repo`` / ``repo_sha`` — upstream repository provenance (``""`` for purely
  synthetic tasks that have no upstream repository).
* ``framework`` / ``framework_version`` — pinned framework identity.
* ``source_path``        — path to runnable source (``""`` for graph-only tasks).
* ``requirement_text``   — the natural-language requirement.
* ``policy``             — the authoritative formal policy
  (:meth:`agentproof.cegar.policy.Policy.to_dict` shape).
* ``defect_category``    — the class of defect (from the mutation taxonomy or a
  human-assigned label).
* ``expected_verdict``   — ``"unsafe"`` or ``"unknown"``; the analyzer must
  never return ``SAFE`` for a benchmark task (a false SAFE is a failure).
* ``violating_trace``    — a feasible violating event trace (list of event
  dicts) or ``None`` when only an UNKNOWN region is exhibited.
* ``graph``              — the policy-violating graph
  (:meth:`agentproof.cegar.ir.MayMustGraph.to_dict` shape).
* ``tool_schemas``       — declared tool schemas referenced by the graph/policy.
* ``regression``         — benign regression tasks / utility measurements.
* ``human_patch``        — at least one human repair description (not assumed
  uniquely correct) or ``None``.
* ``validation``         — ``{status, validators, disagreements}`` two-person
  validation record.
* ``license`` / ``disclosure_status`` / ``redistribute`` — licensing, disclosure
  status, and the redistribution decision.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

# Benchmark strata (plan §5). Kept as a frozen set so a typo becomes an error.
VALID_SLICES: frozenset[str] = frozenset(
    {"real", "mutated_real", "official_example", "adversarial"}
)

# A benchmark task must never be labelled SAFE; only UNSAFE/UNKNOWN are valid
# expected verdicts (plan §7, E2: zero false SAFE certificates).
VALID_VERDICTS: frozenset[str] = frozenset({"unsafe", "unknown"})

# Validation status vocabulary. Synthetic seeds are NOT two-person validated;
# they are marked ``synthetic_auto`` so the distinction is never lost.
VALID_VALIDATION_STATUS: frozenset[str] = frozenset(
    {"synthetic_auto", "one_person", "two_person_validated", "disputed"}
)


@dataclass(frozen=True)
class RepairTask:
    """One AP-RepairBench repair task (see module docstring for field notes)."""

    task_id: str
    slice: str
    framework: str
    framework_version: str
    requirement_text: str
    policy: dict[str, Any]
    defect_category: str
    expected_verdict: str
    graph: dict[str, Any]
    # Optional / provenance fields with defaults.
    repo: str = ""
    repo_sha: str = ""
    source_path: str = ""
    violating_trace: list[dict[str, Any]] | None = None
    tool_schemas: dict[str, Any] = field(default_factory=dict)
    regression: dict[str, Any] = field(default_factory=dict)
    human_patch: str | None = None
    validation: dict[str, Any] = field(
        default_factory=lambda: {
            "status": "synthetic_auto",
            "validators": [],
            "disagreements": [],
        }
    )
    license: str = ""
    disclosure_status: str = "not_applicable"
    redistribute: bool = False

    def __post_init__(self) -> None:
        if self.slice not in VALID_SLICES:
            raise ValueError(
                f"bad slice {self.slice!r}; expected one of {sorted(VALID_SLICES)}"
            )
        if self.expected_verdict not in VALID_VERDICTS:
            raise ValueError(
                f"bad expected_verdict {self.expected_verdict!r}; "
                f"expected one of {sorted(VALID_VERDICTS)}"
            )
        status = self.validation.get("status")
        if status is not None and status not in VALID_VALIDATION_STATUS:
            raise ValueError(
                f"bad validation status {status!r}; "
                f"expected one of {sorted(VALID_VALIDATION_STATUS)}"
            )

    # -- serialization ------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict (round-trips through :meth:`from_dict`)."""
        return {
            "task_id": self.task_id,
            "slice": self.slice,
            "repo": self.repo,
            "repo_sha": self.repo_sha,
            "framework": self.framework,
            "framework_version": self.framework_version,
            "source_path": self.source_path,
            "requirement_text": self.requirement_text,
            "policy": self.policy,
            "defect_category": self.defect_category,
            "expected_verdict": self.expected_verdict,
            "violating_trace": self.violating_trace,
            "graph": self.graph,
            "tool_schemas": self.tool_schemas,
            "regression": self.regression,
            "human_patch": self.human_patch,
            "validation": self.validation,
            "license": self.license,
            "disclosure_status": self.disclosure_status,
            "redistribute": self.redistribute,
        }

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "RepairTask":
        return RepairTask(
            task_id=d["task_id"],
            slice=d["slice"],
            framework=d["framework"],
            framework_version=d["framework_version"],
            requirement_text=d["requirement_text"],
            policy=dict(d["policy"]),
            defect_category=d["defect_category"],
            expected_verdict=d["expected_verdict"],
            graph=dict(d["graph"]),
            repo=d.get("repo", ""),
            repo_sha=d.get("repo_sha", ""),
            source_path=d.get("source_path", ""),
            violating_trace=(
                None
                if d.get("violating_trace") is None
                else [dict(e) for e in d["violating_trace"]]
            ),
            tool_schemas=dict(d.get("tool_schemas", {})),
            regression=dict(d.get("regression", {})),
            human_patch=d.get("human_patch"),
            validation=dict(
                d.get(
                    "validation",
                    {"status": "synthetic_auto", "validators": [], "disagreements": []},
                )
            ),
            license=d.get("license", ""),
            disclosure_status=d.get("disclosure_status", "not_applicable"),
            redistribute=d.get("redistribute", False),
        )


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def save_task(task: RepairTask, path: str | Path) -> str:
    """Write ``task`` as pretty-printed, key-sorted JSON. Returns the path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(task.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return str(p)


def load_task(path: str | Path) -> RepairTask:
    """Load a single :class:`RepairTask` from a JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return RepairTask.from_dict(data)


# Top-level keys every AP-RepairBench task JSON must carry. Used by
# :func:`load_suite` to skip unrelated JSON that may share the directory (the
# task directory can hold sibling fixtures from other tools).
_REQUIRED_KEYS = frozenset(
    {
        "task_id",
        "slice",
        "framework",
        "framework_version",
        "requirement_text",
        "policy",
        "defect_category",
        "expected_verdict",
        "graph",
    }
)


def _looks_like_task(data: Any) -> bool:
    return isinstance(data, Mapping) and _REQUIRED_KEYS <= set(data.keys())


def load_suite(directory: str | Path) -> list[RepairTask]:
    """Load every AP-RepairBench task JSON in ``directory`` (sorted by filename).

    Files that do not carry the full RepairTask key set (:data:`_REQUIRED_KEYS`)
    are skipped rather than raising, so an unrelated JSON fixture sharing the
    directory does not break loading.
    """
    d = Path(directory)
    tasks: list[RepairTask] = []
    for p in sorted(d.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if not _looks_like_task(data):
            continue
        tasks.append(RepairTask.from_dict(data))
    return tasks
