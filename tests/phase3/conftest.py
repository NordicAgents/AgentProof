from __future__ import annotations

from collections.abc import Mapping

import pytest

from vac.state.model import BudgetCounters, State
from vac.tools.registry import ToolDefinition, ToolRegistry


@pytest.fixture
def base_state() -> State:
    return State(
        version="3",
        run_id="phase3-run-001",
        budgets=BudgetCounters(
            max_calls=3,
            used_calls=0,
            max_cost=5.0,
            used_cost=0.0,
            max_retries=1,
            used_retries=0,
        ),
        permissions=frozenset({"scope:email.send"}),
    )


@pytest.fixture
def deterministic_registry() -> ToolRegistry:
    registry = ToolRegistry()

    def wrapper(payload: Mapping[str, object]) -> Mapping[str, object]:
        return {
            "ok": True,
            "receipt": {
                "to": payload["to"],
                "subject": payload["subject"],
            },
            "message_id": "msg-phase3-fixed",
        }

    registry.register(
        ToolDefinition(
            name="email.send",
            input_schema={"to": str, "subject": str, "body": str},
            permission_scope="scope:email.send",
            cost_model=lambda _payload: 1.0,
            wrapper=wrapper,
        )
    )
    return registry


@pytest.fixture
def valid_proposal() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "action_type": "tool_call",
        "tool_name": "email.send",
        "input": {"to": "trace@example.com", "subject": "Phase3", "body": "fixture"},
        "metadata": {
            "proposal_id": "phase3-proposal-001",
            "proposed_by": "planner",
            "timestamp": "2026-03-01T00:00:00Z",
        },
    }
