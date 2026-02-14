from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from vac.engine.step import step
from vac.state.model import BudgetCounters, State, canonical_state_hash
from vac.tools.registry import ToolDefinition, ToolRegistry
from vac.verification.spec import load_spec


def test_schema_rejection_unknown_action_type(base_state: State, deterministic_registry: ToolRegistry, valid_proposal: dict[str, object]) -> None:
    proposal = deepcopy(valid_proposal)
    proposal["action_type"] = "unknown_type"

    result = step(base_state, proposal, deterministic_registry)

    assert result.status == "halted"
    assert result.trace[-1]["decision"] == "denied"
    assert result.trace[-1]["violations"] == ["schema:unknown action_type"]
    assert result.trace[-1]["rejection"]["rule_id"] == "SCHEMA-VALIDATION"
    assert result.trace[-1]["rejection"]["solver_result"] == "unknown"


def test_schema_rejection_invalid_input_payload(base_state: State, deterministic_registry: ToolRegistry, valid_proposal: dict[str, object]) -> None:
    proposal = deepcopy(valid_proposal)
    proposal["input"] = ["bad", "payload"]

    result = step(base_state, proposal, deterministic_registry)

    assert result.status == "halted"
    assert result.trace[-1]["violations"] == ["schema:input must be an object"]


def test_unregistered_tool_fails_before_execution(base_state: State, valid_proposal: dict[str, object]) -> None:
    calls = {"count": 0}
    registry = ToolRegistry()

    def counting_wrapper(payload: Mapping[str, object]) -> Mapping[str, object]:
        calls["count"] += 1
        return {"ok": True, "payload": payload}

    registry.register(
        ToolDefinition(
            name="safe.noop",
            input_schema={"x": int},
            permission_scope="scope:safe.noop",
            cost_model=lambda _payload: 0.1,
            wrapper=counting_wrapper,
        )
    )

    proposal = deepcopy(valid_proposal)
    proposal["tool_name"] = "not.registered"

    result = step(base_state, proposal, registry)

    assert result.status == "halted"
    assert result.trace[-1]["violations"] == ["permissions:unregistered tool not.registered"]
    assert result.trace[-1]["rejection"]["rule_id"] == "PERM-REGISTERED"
    assert result.trace[-1]["rejection"]["solver_result"] == "unsat"
    assert calls["count"] == 0


def test_permission_mismatch_rejected(base_state: State, deterministic_registry: ToolRegistry, valid_proposal: dict[str, object]) -> None:
    restricted_state = base_state.with_updates(permissions=frozenset())

    result = step(restricted_state, valid_proposal, deterministic_registry)

    assert result.status == "halted"
    assert result.trace[-1]["violations"] == ["permissions:missing scope scope:email.send for email.send"]
    assert result.trace[-1]["rejection"]["rule_id"] == "PERM-SCOPE"


def test_policy_guard_failures_include_rule_ids(base_state: State, deterministic_registry: ToolRegistry, valid_proposal: dict[str, object]) -> None:
    precondition_proposal = deepcopy(valid_proposal)
    precondition_proposal["precondition"] = {
        "rule_id": "PRE-001",
        "predicate": {"op": "eq", "left": 1, "right": 2},
    }

    precondition_result = step(base_state, precondition_proposal, deterministic_registry)

    assert precondition_result.status == "halted"
    assert precondition_result.trace[-1]["violations"] == ["preconditions:failed:PRE-001"]

    invariant_proposal = deepcopy(valid_proposal)
    invariant_proposal["invariant"] = {
        "rule_id": "INV-009",
        "predicate": {"op": "eq", "left": "a", "right": "b"},
    }

    invariant_result = step(base_state, invariant_proposal, deterministic_registry)

    assert invariant_result.status == "halted"
    assert invariant_result.trace[-1]["violations"] == ["invariants:failed:INV-009"]


def test_budget_controls_max_calls_cost_and_retries(base_state: State, deterministic_registry: ToolRegistry, valid_proposal: dict[str, object]) -> None:
    over_calls = base_state.with_updates(
        budgets=BudgetCounters(
            max_calls=0,
            used_calls=0,
            max_cost=10.0,
            used_cost=0.0,
            max_retries=2,
            used_retries=0,
        )
    )
    calls_result = step(over_calls, valid_proposal, deterministic_registry)
    assert calls_result.trace[-1]["violations"] == ["budget:exceeded"]

    over_cost = base_state.with_updates(
        budgets=BudgetCounters(
            max_calls=5,
            used_calls=0,
            max_cost=1.0,
            used_cost=0.0,
            max_retries=2,
            used_retries=0,
        )
    )
    cost_result = step(over_cost, valid_proposal, deterministic_registry)
    assert cost_result.trace[-1]["violations"] == ["budget:exceeded"]

    over_retries = base_state.with_updates(
        budgets=BudgetCounters(
            max_calls=5,
            used_calls=0,
            max_cost=10.0,
            used_cost=0.0,
            max_retries=1,
            used_retries=2,
        )
    )
    retries_result = step(over_retries, valid_proposal, deterministic_registry)
    assert retries_result.trace[-1]["violations"] == ["budget:exceeded"]


def test_determinism_same_inputs_same_decision_and_hash(base_state: State, deterministic_registry: ToolRegistry, valid_proposal: dict[str, object]) -> None:
    result_one = step(base_state, valid_proposal, deterministic_registry)
    result_two = step(base_state, valid_proposal, deterministic_registry)

    assert result_one.status == result_two.status
    assert result_one.trace[-1]["decision"] == result_two.trace[-1]["decision"]
    assert canonical_state_hash(result_one) == canonical_state_hash(result_two)


def test_timeout_solver_result_is_stable(base_state: State, deterministic_registry: ToolRegistry, valid_proposal: dict[str, object]) -> None:
    spec = load_spec({"solver": {"timeout_ms": 0, "random_seed": 11, "tactic_profile": "fixed"}})
    result = step(base_state, valid_proposal, deterministic_registry, spec=spec)

    assert result.status == "halted"
    assert result.trace[-1]["violations"] == ["solver:timeout"]
    assert result.trace[-1]["rejection"]["solver_result"] == "timeout"
    assert result.trace[-1]["rejection"]["diagnostics"] == {
        "seed": 11,
        "tactic_profile": "fixed",
        "timeout_ms": 0,
        "timeout": True,
    }


def test_trace_integrity_appends_step_hashes_decision_and_violations(base_state: State, deterministic_registry: ToolRegistry, valid_proposal: dict[str, object]) -> None:
    allowed = step(base_state, valid_proposal, deterministic_registry)
    denied = step(allowed, {**valid_proposal, "action_type": "bad.type"}, deterministic_registry)

    assert len(allowed.trace) == 1
    allowed_event = allowed.trace[-1]
    assert allowed_event["state_hash_before"]
    assert allowed_event["state_hash_after"]
    assert allowed_event["decision"] == "allowed"
    assert allowed_event["violations"] == []

    assert len(denied.trace) == 2
    denied_event = denied.trace[-1]
    assert denied_event["state_hash_before"] == denied_event["state_hash_after"]
    assert denied_event["decision"] == "denied"
    assert denied_event["violations"] == ["schema:unknown action_type"]
