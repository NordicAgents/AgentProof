"""Phase 4 deterministic multi-agent policy helpers."""

from __future__ import annotations

from typing import Any, Mapping


class MultiAgentPolicyError(ValueError):
    """Raised when a multi-agent payload is malformed."""


def evaluate_multi_agent_payload(payload: Mapping[str, Any] | None) -> bool:
    """Evaluate optional multi-agent access control payload."""
    if payload is None:
        return True

    actor_id = payload.get("actor_id")
    target_id = payload.get("target_id")
    allowed_targets = payload.get("allowed_targets", ())
    require_approval = payload.get("require_approval", False)
    approved_by = payload.get("approved_by")

    if not isinstance(actor_id, str) or not actor_id:
        raise MultiAgentPolicyError("multi_agent.actor_id must be a non-empty string")
    if not isinstance(target_id, str) or not target_id:
        raise MultiAgentPolicyError("multi_agent.target_id must be a non-empty string")
    if not isinstance(allowed_targets, (list, tuple)):
        raise MultiAgentPolicyError("multi_agent.allowed_targets must be a list/tuple")
    if not isinstance(require_approval, bool):
        raise MultiAgentPolicyError("multi_agent.require_approval must be bool")

    if actor_id == target_id:
        return True
    if target_id not in {str(item) for item in allowed_targets}:
        return False
    if require_approval and (not isinstance(approved_by, str) or not approved_by):
        return False
    return True
