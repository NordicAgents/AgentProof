"""Action model/type definitions and deterministic schema validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

SUPPORTED_SCHEMA_VERSIONS = {"1.0"}
_REQUIRED_TOP_LEVEL = ("schema_version", "action_type", "tool_name", "input", "metadata")
_REQUIRED_METADATA = ("proposal_id", "proposed_by", "timestamp")


class ActionSchemaError(ValueError):
    """Raised when an action proposal fails schema validation."""


@dataclass(frozen=True)
class ActionProposal:
    """Canonical action proposal structure."""

    schema_version: str
    action_type: str
    tool_name: str
    input: Mapping[str, Any]
    metadata: Mapping[str, Any]
    expected_effects: tuple[str, ...] = ()
    cost_hint: float | None = None

    @classmethod
    def from_mapping(cls, proposal: Mapping[str, Any]) -> "ActionProposal":
        """Build an immutable ActionProposal from a mapping."""
        validate_action_schema(proposal)
        effects = proposal.get("expected_effects", ())
        if not isinstance(effects, (list, tuple)):
            raise ActionSchemaError("expected_effects must be a list/tuple of strings")
        if any(not isinstance(item, str) for item in effects):
            raise ActionSchemaError("expected_effects entries must be strings")

        cost_hint = proposal.get("cost_hint")
        if cost_hint is not None and not isinstance(cost_hint, (int, float)):
            raise ActionSchemaError("cost_hint must be a number")

        return cls(
            schema_version=proposal["schema_version"],
            action_type=proposal["action_type"],
            tool_name=proposal["tool_name"],
            input=proposal["input"],
            metadata=proposal["metadata"],
            expected_effects=tuple(effects),
            cost_hint=float(cost_hint) if cost_hint is not None else None,
        )


def _validate_timestamp(value: str) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ActionSchemaError("metadata.timestamp must be ISO-8601") from exc


def validate_action_schema(proposal: Mapping[str, Any]) -> None:
    """Deterministically validate proposal shape and base constraints."""
    if not isinstance(proposal, Mapping):
        raise ActionSchemaError("proposal must be a mapping")

    for key in _REQUIRED_TOP_LEVEL:
        if key not in proposal:
            raise ActionSchemaError(f"missing required field: {key}")

    if proposal["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
        raise ActionSchemaError("unsupported schema_version")

    if not isinstance(proposal["action_type"], str) or not proposal["action_type"].strip():
        raise ActionSchemaError("action_type must be a non-empty string")

    if not isinstance(proposal["tool_name"], str) or not proposal["tool_name"].strip():
        raise ActionSchemaError("tool_name must be a non-empty string")

    if not isinstance(proposal["input"], Mapping):
        raise ActionSchemaError("input must be an object")

    metadata = proposal["metadata"]
    if not isinstance(metadata, Mapping):
        raise ActionSchemaError("metadata must be an object")

    for key in _REQUIRED_METADATA:
        if key not in metadata:
            raise ActionSchemaError(f"missing metadata field: {key}")

    if not isinstance(metadata["proposal_id"], str) or not metadata["proposal_id"].strip():
        raise ActionSchemaError("metadata.proposal_id must be a non-empty string")

    if not isinstance(metadata["proposed_by"], str) or not metadata["proposed_by"].strip():
        raise ActionSchemaError("metadata.proposed_by must be a non-empty string")

    if not isinstance(metadata["timestamp"], str):
        raise ActionSchemaError("metadata.timestamp must be a string")
    _validate_timestamp(metadata["timestamp"])

    if "idempotency_key" in metadata and metadata["idempotency_key"] is not None:
        if not isinstance(metadata["idempotency_key"], str) or not metadata["idempotency_key"].strip():
            raise ActionSchemaError("metadata.idempotency_key must be a non-empty string when provided")
