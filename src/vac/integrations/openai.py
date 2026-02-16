"""OpenAI tool-call adapter into VAC canonical proposals."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


def adapt_openai_tool_call(
    tool_call: Mapping[str, Any],
    *,
    response_id: str,
    turn_id: str,
    correlation_id: str,
    proposed_by: str = "openai",
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Convert an OpenAI-style tool call payload into a VAC proposal mapping."""
    function_payload = tool_call.get("function", {})
    tool_name = str(function_payload.get("name", "")).strip()

    arguments = function_payload.get("arguments", {})
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, Mapping):
        raise ValueError("tool_call.function.arguments must be a mapping")

    call_id = str(tool_call.get("id", "")).strip()
    if not call_id:
        call_id = f"{response_id}:{turn_id}:{tool_name}"

    ts = timestamp or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    metadata = {
        "proposal_id": call_id,
        "proposed_by": proposed_by,
        "timestamp": ts,
        "response_id": response_id,
        "turn_id": turn_id,
        "correlation_id": correlation_id,
        "raw_tool_call": dict(tool_call),
    }

    return {
        "schema_version": "1.0",
        "action_type": "tool_call",
        "tool_name": tool_name,
        "input": dict(arguments),
        "metadata": metadata,
    }
