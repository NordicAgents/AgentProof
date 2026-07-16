"""Machine-checkable SAFE certificates for AgentProof-CEGAR (Paper 2, §4.6).

A :class:`Certificate` is the *proof artifact* the analyzer emits when it has
established that a program (a :class:`~agentproof.cegar.ir.MayMustGraph`)
satisfies a typed :class:`~agentproof.cegar.policy.Policy`. It is deliberately
**self-describing and dependency-light**: it embeds the program graph and the
policy verbatim (as their ``to_dict`` forms), the two content hashes, the
verdict, the semantics/version tags, the trace-conservatism assumptions, and a
best-effort snapshot of the product exploration — everything an *independent*
checker needs to re-derive the proof from scratch.

Theorem 2 (certificate soundness), plan §3.2
--------------------------------------------
If the independent checker (:mod:`agentproof.cegar.checker`) accepts a SAFE
certificate, then every concrete trace covered by the recorded graph satisfies
the recorded policy. The checker realizes this by *re-deriving* the may/must
reachability proof itself, using only :mod:`agentproof.cegar.ir`,
:mod:`agentproof.cegar.policy`, and this module — never the analyzer's own
product/oracle code. This module therefore records enough of the product for a
cross-check but never asks the checker to *trust* it: the checker recomputes.

Determinism
-----------
All hashing goes through :func:`canonical_hash`, which serializes with
``json.dumps(obj, sort_keys=True, default=str)`` and digests with SHA-256.
Python's built-in ``hash()`` is never used (it is salted and non-portable).

Interoperability with the product checker
-----------------------------------------
:func:`build_certificate` consumes a ``product_result`` **duck-typed** on a
single required attribute, ``verdict`` (a
:class:`~agentproof.cegar.ir.Verdict` or the string ``"safe"``). Any additional
visited-state / monitor-tag attributes it exposes are recorded best-effort into
``abstract_transitions`` for cross-checking; their absence is not an error. This
keeps this module decoupled from the concrete ``product.ProductResult`` type
(which the checker must not import anyway).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from agentproof.cegar.ir import MayMustGraph, Verdict
from agentproof.cegar.policy import Policy


# ---------------------------------------------------------------------------
# Canonical, deterministic hashing
# ---------------------------------------------------------------------------

def canonical_hash(obj: Any) -> str:
    """Deterministic SHA-256 hex digest of a JSON-serializable object.

    Serialization is ``json.dumps(obj, sort_keys=True, default=str)`` so the
    digest is independent of dict insertion order and of the Python process
    (unlike the salted built-in :func:`hash`). ``default=str`` lets enums and
    other non-JSON scalars serialize by their string form.
    """
    payload = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The certificate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Certificate:
    """A proof-carrying SAFE certificate (plan §4.6, Theorem 2).

    Every field is JSON-serializable. The two hashes bind the certificate to a
    specific program and policy; the embedded ``graph`` and ``policy`` dicts let
    an independent checker re-parse them and re-derive the proof.
    """

    program_hash: str
    policy_hash: str
    policy: dict
    graph: dict
    verdict: str
    supported_semantics: str
    dependency_versions: dict
    assumptions: list
    abstract_transitions: dict
    repair_cost: float | None
    regression_manifest: dict
    created_tag: str

    # -- serialization ------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "Certificate":
        return Certificate(
            program_hash=d["program_hash"],
            policy_hash=d["policy_hash"],
            policy=dict(d["policy"]),
            graph=dict(d["graph"]),
            verdict=d["verdict"],
            supported_semantics=d.get("supported_semantics", ""),
            dependency_versions=dict(d.get("dependency_versions", {})),
            assumptions=list(d.get("assumptions", [])),
            abstract_transitions=dict(d.get("abstract_transitions", {})),
            repair_cost=d.get("repair_cost"),
            regression_manifest=dict(d.get("regression_manifest", {})),
            created_tag=d.get("created_tag", ""),
        )

    def write_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, sort_keys=True, indent=2, default=str)

    @staticmethod
    def read_json(path: str) -> "Certificate":
        with open(path, "r", encoding="utf-8") as fh:
            return Certificate.from_dict(json.load(fh))


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def _default_dependency_versions() -> dict[str, str]:
    """Best-effort snapshot of the runtime the analyzer ran on."""
    import platform

    versions = {"python": platform.python_version()}
    try:  # importlib.metadata is stdlib on 3.8+
        from importlib import metadata

        versions["agentproof"] = metadata.version("agentproof")
    except Exception:  # pragma: no cover - package may be a bare checkout
        versions["agentproof"] = "unknown"
    return versions


def _verdict_str(product_result: Any) -> str:
    """Normalize a duck-typed ``product_result.verdict`` to a lowercase string."""
    v = getattr(product_result, "verdict", None)
    if isinstance(v, Verdict):
        return v.value
    if isinstance(v, str):
        return v.lower()
    raise ValueError(
        "product_result has no usable .verdict (expected Verdict or str, "
        f"got {v!r})"
    )


def _json_safe(value: Any) -> Any:
    """Coerce sets/tuples/enums into JSON-friendly, deterministic forms."""
    if isinstance(value, (set, frozenset)):
        return sorted(str(x) for x in value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(x) for x in value]
    if isinstance(value, Verdict):
        return value.value
    return value


def _extract_product_info(product_result: Any) -> dict[str, Any]:
    """Best-effort snapshot of the product exploration for CROSS-CHECKING only.

    The checker never trusts this; it re-derives reachability independently and
    may compare against these records. We probe a handful of plausible attribute
    names so the extraction stays robust to the concrete ``ProductResult`` shape
    (which this module intentionally does not import).
    """
    info: dict[str, Any] = {}

    visited_raw = None
    for attr in (
        "visited_product_states",
        "visited_states",
        "visited",
        "product_states",
    ):
        candidate = getattr(product_result, attr, None)
        if candidate is not None:
            visited_raw = candidate
            break

    visited: list[list[str]] = []
    if visited_raw is not None:
        try:
            for item in visited_raw:
                if isinstance(item, (tuple, list)) and len(item) >= 2:
                    visited.append([str(item[0]), str(item[1])])
                else:
                    visited.append([str(item), ""])
        except TypeError:  # not iterable; ignore
            visited = []
    info["visited"] = visited

    for attr in (
        "initial_state",
        "monitor_initial",
        "accepting_states",
        "monitor_accepting",
        "violation_states",
        "monitor_violation",
    ):
        candidate = getattr(product_result, attr, None)
        if candidate is not None:
            info[attr] = _json_safe(candidate)

    return info


def build_certificate(
    graph: MayMustGraph,
    policy: Policy,
    product_result: Any,
    *,
    assume_trace_conservative: bool = False,
    dependency_versions: dict | None = None,
    repair_cost: float | None = None,
    regression_manifest: dict | None = None,
    supported_semantics: str = "cegar-ir-0.1",
    created_tag: str = "",
) -> Certificate:
    """Emit a SAFE certificate for ``graph`` under ``policy``.

    ``product_result`` must carry a ``verdict`` equal to
    :attr:`Verdict.SAFE` (or the string ``"safe"``); otherwise a
    :class:`ValueError` is raised — certificates are ONLY emitted for SAFE.
    Any visited-state / monitor-tag attributes it exposes are recorded (for
    cross-checking) into ``abstract_transitions``; their absence is fine because
    the checker re-derives the proof from ``graph`` and ``policy`` alone.

    When ``assume_trace_conservative`` is set, the tag
    ``"trace_conservative_assumed"`` is added to ``assumptions`` and the checker
    will satisfy the certification gate unconditionally (the caller vouches that
    the extraction over-approximates the real traces).
    """
    verdict = _verdict_str(product_result)
    if verdict != Verdict.SAFE.value:
        raise ValueError(
            f"certificates are only emitted for SAFE results; got {verdict!r}"
        )

    graph_dict = graph.to_dict()
    policy_dict = policy.to_dict()

    assumptions: list[str] = []
    if assume_trace_conservative:
        assumptions.append("trace_conservative_assumed")

    return Certificate(
        program_hash=canonical_hash(graph_dict),
        policy_hash=canonical_hash(policy_dict),
        policy=policy_dict,
        graph=graph_dict,
        verdict=Verdict.SAFE.value,
        supported_semantics=supported_semantics,
        dependency_versions=dict(dependency_versions)
        if dependency_versions is not None
        else _default_dependency_versions(),
        assumptions=assumptions,
        abstract_transitions=_extract_product_info(product_result),
        repair_cost=repair_cost,
        regression_manifest=dict(regression_manifest)
        if regression_manifest is not None
        else {},
        created_tag=created_tag,
    )
