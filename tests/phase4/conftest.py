from __future__ import annotations

from collections.abc import Mapping

import pytest

from vac.state.model import BudgetCounters, State
from vac.tools.registry import ToolDefinition, ToolRegistry


@pytest.fixture
def base_state() -> State:
    return State(
        version="4",
        run_id="phase4-run-001",
        budgets=BudgetCounters(
            max_calls=3,
            used_calls=0,
            max_cost=10.0,
            used_cost=0.0,
            max_retries=1,
            used_retries=0,
        ),
        permissions=frozenset({"scope:email.send"}),
    )


@pytest.fixture
def enterprise_registry() -> ToolRegistry:
    registry = ToolRegistry()

    def wrapper(payload: Mapping[str, object]) -> Mapping[str, object]:
        return {"ok": True, "echo": dict(payload)}

    registry.register(
        ToolDefinition(
            name="email.send",
            input_schema={"to": str, "subject": str, "body": str},
            permission_scope="scope:email.send",
            cost_model=lambda _payload: 1.0,
            wrapper=wrapper,
            sandbox_profile="strict",
        )
    )
    return registry


@pytest.fixture
def valid_proposal() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "action_type": "tool_call",
        "tool_name": "email.send",
        "input": {"to": "safe@example.com", "subject": "Phase4", "body": "ok"},
        "sandbox_profile": "isolated",
        "infoflow_labels": {
            "source_labels": ["internal"],
            "sink_label": "confidential",
        },
        "multi_agent": {
            "actor_id": "agent-exec",
            "target_id": "agent-review",
            "allowed_targets": ["agent-review"],
            "require_approval": True,
            "approved_by": "agent-lead",
        },
        "metadata": {
            "proposal_id": "phase4-proposal-001",
            "proposed_by": "planner",
            "timestamp": "2026-03-01T00:00:00Z",
        },
    }
