"""Phase 4 enterprise information-flow and sandboxing helpers."""

from __future__ import annotations

from typing import Iterable, Mapping


_LABEL_ORDER = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}

_SANDBOX_ORDER = {
    "none": 0,
    "standard": 1,
    "strict": 2,
    "isolated": 3,
}


class EnterprisePolicyError(ValueError):
    """Raised when enterprise hardening policy inputs are malformed."""


def evaluate_information_flow(
    *,
    source_labels: Iterable[str],
    sink_label: str,
    declassify: Iterable[str] = (),
) -> bool:
    """Return whether all sources are permitted to flow into the sink label."""
    normalized_declassify = {str(label) for label in declassify}
    sink_rank = _label_rank(sink_label)

    for raw_label in source_labels:
        label = str(raw_label)
        if label in normalized_declassify:
            continue
        if _label_rank(label) > sink_rank:
            return False
    return True


def evaluate_sandbox_profile(*, required: str, requested: str) -> bool:
    """Return whether the requested sandbox profile meets minimum tool requirements."""
    return _sandbox_rank(requested) >= _sandbox_rank(required)


def evaluate_information_flow_payload(payload: Mapping[str, object] | None) -> bool:
    """Evaluate optional proposal info-flow payload; defaults to allow on absence."""
    if payload is None:
        return True

    source_labels = payload.get("source_labels", ())
    sink_label = payload.get("sink_label", "public")
    declassify = payload.get("declassify", ())

    if not isinstance(source_labels, (list, tuple)):
        raise EnterprisePolicyError("infoflow.source_labels must be a list/tuple")
    if not isinstance(sink_label, str):
        raise EnterprisePolicyError("infoflow.sink_label must be a string")
    if not isinstance(declassify, (list, tuple)):
        raise EnterprisePolicyError("infoflow.declassify must be a list/tuple")

    return evaluate_information_flow(
        source_labels=[str(label) for label in source_labels],
        sink_label=sink_label,
        declassify=[str(label) for label in declassify],
    )


def _label_rank(label: str) -> int:
    try:
        return _LABEL_ORDER[label]
    except KeyError as exc:
        raise EnterprisePolicyError(f"unknown info-flow label: {label}") from exc


def _sandbox_rank(label: str) -> int:
    try:
        return _SANDBOX_ORDER[label]
    except KeyError as exc:
        raise EnterprisePolicyError(f"unknown sandbox profile: {label}") from exc
