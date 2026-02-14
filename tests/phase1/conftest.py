from __future__ import annotations

from collections.abc import Mapping

import pytest

from vac.state.model import BudgetCounters, State
from vac.tools.registry import ToolDefinition, ToolRegistry


@pytest.fixture
def base_state() -> State:
    return State(
        version="1",
        run_id="run-1",
        budgets=BudgetCounters(
            max_calls=5,
            used_calls=0,
            max_cost=10.0,
            used_cost=0.0,
            max_retries=2,
            used_retries=0,
        ),
        permissions=frozenset({"scope:email.send"}),
    )


@pytest.fixture
def deterministic_registry() -> ToolRegistry:
    registry = ToolRegistry()

    def stub_email_wrapper(payload: Mapping[str, object]) -> Mapping[str, object]:
        return {
            "ok": True,
            "echo": {"to": payload["to"], "subject": payload["subject"], "body": payload["body"]},
            "message_id": "msg-fixed-001",
        }

    registry.register(
        ToolDefinition(
            name="email.send",
            input_schema={"to": str, "subject": str, "body": str},
            permission_scope="scope:email.send",
            cost_model=lambda _payload: 1.5,
            wrapper=stub_email_wrapper,
        )
    )
    return registry


@pytest.fixture
def valid_proposal() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "action_type": "tool_call",
        "tool_name": "email.send",
        "input": {"to": "user@example.com", "subject": "Hello", "body": "Body"},
        "metadata": {
            "proposal_id": "proposal-1",
            "proposed_by": "planner",
            "timestamp": "2026-01-01T00:00:00Z",
        },
    }
