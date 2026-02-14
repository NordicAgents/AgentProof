"""Single deterministic engine step transition."""

from __future__ import annotations

from typing import Any, Mapping

from vac.actions.schema import ActionProposal, ActionSchemaError, validate_action_schema
from vac.policy.evaluator import evaluate_budget, evaluate_predicate
from vac.state.model import BudgetCounters, State, canonical_state_hash
from vac.tools.registry import ToolRegistry, ToolRegistryError


class StepViolation(RuntimeError):
    """Raised on step transition violations."""


def step(state: State, proposal: Mapping[str, Any], registry: ToolRegistry) -> State:
    """Apply one proposal through ordered deterministic checks and wrapper execution."""
    before_hash = canonical_state_hash(state)
    violations: list[str] = []

    # 1) schema
    try:
        validate_action_schema(proposal)
        action = ActionProposal.from_mapping(proposal)
    except ActionSchemaError as exc:
        violations.append(f"schema:{exc}")
        return _halted(state, proposal, before_hash, violations)

    # 2) permissions (+ registered guardrails)
    if not registry.is_registered(action.tool_name):
        violations.append(f"permissions:unregistered tool {action.tool_name}")
        return _halted(state, proposal, before_hash, violations)

    tool = registry.get(action.tool_name)
    if tool.permission_scope not in state.permissions:
        violations.append(
            f"permissions:missing scope {tool.permission_scope} for {action.tool_name}"
        )
        return _halted(state, proposal, before_hash, violations)

    # 3) preconditions
    precondition, precondition_rule = _extract_guard(proposal.get("precondition", True))
    precondition_ctx = {"state": state.to_dict(), "proposal": proposal}
    if not evaluate_predicate(precondition, precondition_ctx):
        violations.append(_rule_violation("preconditions", precondition_rule))
        return _halted(state, proposal, before_hash, violations)

    # 4) invariants (checked before execution)
    invariant, invariant_rule = _extract_guard(proposal.get("invariant", True))
    if not evaluate_predicate(invariant, precondition_ctx):
        violations.append(_rule_violation("invariants", invariant_rule))
        return _halted(state, proposal, before_hash, violations)

    # 5) budget
    estimated_cost = action.cost_hint if action.cost_hint is not None else registry.estimate_cost(
        action.tool_name, action.input
    )
    budget_rule = proposal.get("budget_rule")
    if not evaluate_budget(
        max_calls=state.budgets.max_calls,
        used_calls=state.budgets.used_calls,
        max_cost=state.budgets.max_cost,
        used_cost=state.budgets.used_cost,
        estimated_cost=estimated_cost,
        max_retries=state.budgets.max_retries,
        used_retries=state.budgets.used_retries,
        additional_rule=budget_rule,
    ):
        violations.append("budget:exceeded")
        return _halted(state, proposal, before_hash, violations)

    # 6) execute wrapper (all side-effects must stay inside wrapper)
    try:
        tool_output = registry.invoke(action.tool_name, action.input, set(state.permissions))
    except ToolRegistryError as exc:
        violations.append(f"execute:{exc}")
        return _halted(state, proposal, before_hash, violations)

    # 7) append trace
    updated_trace = list(state.trace)
    next_step_index = len(updated_trace)

    new_budgets = BudgetCounters(
        max_calls=state.budgets.max_calls,
        used_calls=state.budgets.used_calls + 1,
        max_cost=state.budgets.max_cost,
        used_cost=state.budgets.used_cost + estimated_cost,
        max_retries=state.budgets.max_retries,
        used_retries=state.budgets.used_retries,
    )

    new_memory = dict(state.memory)
    new_memory[f"tools.{action.tool_name}.last_output"] = dict(tool_output)

    candidate = state.with_updates(
        memory=new_memory,
        budgets=new_budgets,
        trace=tuple(
            updated_trace
            + [
                {
                    "step_index": next_step_index,
                    "proposal_hash": _proposal_hash(action.metadata.get("proposal_id", "")),
                    "decision": "allowed",
                    "violations": [],
                    "tool_call": {"name": action.tool_name, "input": dict(action.input)},
                    "state_hash_before": before_hash,
                    "state_hash_after": "pending",
                }
            ]
        ),
    )

    after_hash = canonical_state_hash(candidate)
    finalized_trace = list(candidate.trace)
    finalized_trace[-1] = dict(finalized_trace[-1])
    finalized_trace[-1]["state_hash_after"] = after_hash

    return candidate.with_updates(trace=tuple(finalized_trace), status="ready")


def _proposal_hash(seed: str) -> str:
    # Minimal deterministic hash helper avoiding extra imports outside step semantics.
    from hashlib import sha256

    return sha256(seed.encode("utf-8")).hexdigest()


def _extract_guard(guard: Any) -> tuple[Any, str | None]:
    if isinstance(guard, Mapping) and "predicate" in guard:
        rule_id = guard.get("rule_id")
        if rule_id is not None and not isinstance(rule_id, str):
            rule_id = str(rule_id)
        return guard.get("predicate", True), rule_id
    return guard, None


def _rule_violation(prefix: str, rule_id: str | None) -> str:
    if rule_id:
        return f"{prefix}:failed:{rule_id}"
    return f"{prefix}:failed"


def _halted(state: State, proposal: Mapping[str, Any], before_hash: str, violations: list[str]) -> State:
    trace = list(state.trace)
    trace.append(
        {
            "step_index": len(trace),
            "proposal_hash": _proposal_hash(str(proposal.get("metadata", {}).get("proposal_id", ""))),
            "decision": "denied",
            "violations": violations,
            "tool_call": None,
            "state_hash_before": before_hash,
            "state_hash_after": before_hash,
        }
    )
    return state.with_updates(trace=tuple(trace), status="halted")
