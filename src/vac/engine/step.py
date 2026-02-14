"""Single deterministic engine step transition."""

from __future__ import annotations

from typing import Any, Mapping

from vac.actions.schema import ActionProposal, ActionSchemaError, validate_action_schema
from vac.state.model import BudgetCounters, State, canonical_state_hash
from vac.tools.registry import ToolRegistry, ToolRegistryError
from vac.verification.solver import SolverDecision, solve_constraints
from vac.verification.spec import VerificationSpec, load_spec


class StepViolation(RuntimeError):
    """Raised on step transition violations."""


def step(
    state: State,
    proposal: Mapping[str, Any],
    registry: ToolRegistry,
    spec: VerificationSpec | None = None,
) -> State:
    """Apply one proposal through ordered deterministic checks and wrapper execution."""
    before_hash = canonical_state_hash(state)

    # 1) schema
    try:
        validate_action_schema(proposal)
        action = ActionProposal.from_mapping(proposal)
    except ActionSchemaError as exc:
        violation = f"schema:{exc}"
        rejection = {
            "rule_type": "schema",
            "rule_id": "SCHEMA-VALIDATION",
            "solver_result": "unknown",
            "diagnostics": {"error": str(exc)},
        }
        return _halted(state, proposal, before_hash, [violation], rejection)

    # 2) solver-backed policy layer
    verification_spec = spec if spec is not None else load_spec(None)
    permission_scope: str | None = None
    if registry.is_registered(action.tool_name):
        permission_scope = registry.get(action.tool_name).permission_scope

    if action.cost_hint is not None:
        estimated_cost = action.cost_hint
    elif registry.is_registered(action.tool_name):
        estimated_cost = registry.estimate_cost(action.tool_name, action.input)
    else:
        estimated_cost = 0.0

    decision = solve_constraints(
        state=state,
        proposal=proposal,
        tool_name=action.tool_name,
        tool_permission_scope=permission_scope,
        estimated_cost=estimated_cost,
        registry=registry,
        config=verification_spec.solver,
    )

    if not decision.is_allowed:
        violation = _format_solver_violation(decision)
        rejection = _rejection_payload(decision)
        return _halted(state, proposal, before_hash, [violation], rejection)

    # 3) execute wrapper (all side-effects must stay inside wrapper)
    try:
        tool_output = registry.invoke(action.tool_name, action.input, set(state.permissions))
    except ToolRegistryError as exc:
        violations = [f"execute:{exc}"]
        rejection = {
            "rule_type": "execute",
            "rule_id": "EXECUTE-WRAPPER",
            "solver_result": "unknown",
            "diagnostics": {"error": str(exc)},
        }
        return _halted(state, proposal, before_hash, violations, rejection)

    # 4) append trace
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
    from hashlib import sha256

    return sha256(seed.encode("utf-8")).hexdigest()


def _format_solver_violation(decision: SolverDecision) -> str:
    if decision.failed_constraint is None:
        return f"solver:{decision.result_class}"

    failed = decision.failed_constraint
    if failed.violation_message is not None:
        return failed.violation_message
    return f"{failed.rule_type}:failed:{failed.rule_id}"


def _rejection_payload(decision: SolverDecision) -> Mapping[str, Any]:
    if decision.failed_constraint is None:
        return {
            "rule_type": "solver",
            "rule_id": "SOLVER-TIMEOUT",
            "solver_result": decision.result_class,
            "diagnostics": dict(decision.diagnostics),
        }

    return {
        "rule_type": decision.failed_constraint.rule_type,
        "rule_id": decision.failed_constraint.rule_id,
        "solver_result": decision.result_class,
        "diagnostics": dict(decision.diagnostics),
    }


def _halted(
    state: State,
    proposal: Mapping[str, Any],
    before_hash: str,
    violations: list[str],
    rejection: Mapping[str, Any],
) -> State:
    trace = list(state.trace)
    trace.append(
        {
            "step_index": len(trace),
            "proposal_hash": _proposal_hash(str(proposal.get("metadata", {}).get("proposal_id", ""))),
            "decision": "denied",
            "violations": violations,
            "rejection": dict(rejection),
            "tool_call": None,
            "state_hash_before": before_hash,
            "state_hash_after": before_hash,
        }
    )
    return state.with_updates(trace=tuple(trace), status="halted")
