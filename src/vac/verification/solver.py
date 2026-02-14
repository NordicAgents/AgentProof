"""Deterministic SMT-style constraint encoding and solving."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from vac.policy.evaluator import PolicyEvaluationError, evaluate_budget, evaluate_predicate
from vac.state.model import State
from vac.tools.registry import ToolRegistry

from .config import SolverConfig

SolverResultClass = str


@dataclass(frozen=True)
class EncodedConstraint:
    """Single encoded rule with deterministic identity."""

    rule_type: str
    rule_id: str
    predicate: Any
    context: Mapping[str, Any]
    violation_message: str | None = None


@dataclass(frozen=True)
class SolverDecision:
    """Solver outcome and minimal replay metadata."""

    is_allowed: bool
    result_class: SolverResultClass
    failed_constraint: EncodedConstraint | None
    diagnostics: Mapping[str, Any]


def solve_constraints(
    *,
    state: State,
    proposal: Mapping[str, Any],
    tool_name: str,
    tool_permission_scope: str | None,
    estimated_cost: float,
    registry: ToolRegistry,
    config: SolverConfig,
) -> SolverDecision:
    """Evaluate encoded constraints with deterministic SAT/UNSAT classes."""
    if config.timeout_ms <= 0:
        return SolverDecision(
            is_allowed=False,
            result_class="timeout",
            failed_constraint=None,
            diagnostics=_diagnostics(config, timeout=True),
        )

    constraints = _encode_constraints(
        state=state,
        proposal=proposal,
        tool_name=tool_name,
        tool_permission_scope=tool_permission_scope,
        estimated_cost=estimated_cost,
        registry=registry,
    )

    for index, constraint in enumerate(constraints):
        try:
            satisfied = evaluate_predicate(constraint.predicate, constraint.context)
        except PolicyEvaluationError:
            return SolverDecision(
                is_allowed=False,
                result_class="unknown" if config.unknown_on_error else "unsat",
                failed_constraint=constraint,
                diagnostics=_diagnostics(config, constraint_index=index, predicate_error=True),
            )

        if not satisfied:
            return SolverDecision(
                is_allowed=False,
                result_class="unsat",
                failed_constraint=constraint,
                diagnostics=_diagnostics(config, constraint_index=index),
            )

    return SolverDecision(
        is_allowed=True,
        result_class="sat",
        failed_constraint=None,
        diagnostics=_diagnostics(config, constraint_count=len(constraints)),
    )


def _encode_constraints(
    *,
    state: State,
    proposal: Mapping[str, Any],
    tool_name: str,
    tool_permission_scope: str | None,
    estimated_cost: float,
    registry: ToolRegistry,
) -> list[EncodedConstraint]:
    precondition = proposal.get("precondition", True)
    invariant = proposal.get("invariant", True)
    budget_rule = proposal.get("budget_rule")
    infoflow = proposal.get("infoflow", True)

    precondition_predicate, precondition_id = _extract_rule(precondition, "PRECOND-DEFAULT")
    invariant_predicate, invariant_id = _extract_rule(invariant, "INVARIANT-DEFAULT")
    infoflow_predicate, infoflow_id = _extract_rule(infoflow, "INFOFLOW-DEFAULT")

    base_context = {"state": state.to_dict(), "proposal": proposal}

    budget_predicate = {
        "op": "eq",
        "left": evaluate_budget(
            max_calls=state.budgets.max_calls,
            used_calls=state.budgets.used_calls,
            max_cost=state.budgets.max_cost,
            used_cost=state.budgets.used_cost,
            estimated_cost=estimated_cost,
            max_retries=state.budgets.max_retries,
            used_retries=state.budgets.used_retries,
            additional_rule=budget_rule,
        ),
        "right": True,
    }

    return [
        EncodedConstraint(
            rule_type="permissions",
            rule_id="PERM-REGISTERED",
            predicate={"op": "eq", "left": registry.is_registered(tool_name), "right": True},
            context={},
            violation_message=f"permissions:unregistered tool {tool_name}",
        ),
        EncodedConstraint(
            rule_type="permissions",
            rule_id="PERM-SCOPE",
            predicate={"op": "eq", "left": tool_permission_scope in state.permissions, "right": True},
            context={},
            violation_message=(
                f"permissions:missing scope {tool_permission_scope} for {tool_name}"
            ),
        ),
        EncodedConstraint(
            rule_type="preconditions",
            rule_id=precondition_id,
            predicate=precondition_predicate,
            context=base_context,
        ),
        EncodedConstraint(
            rule_type="invariants",
            rule_id=invariant_id,
            predicate=invariant_predicate,
            context=base_context,
        ),
        EncodedConstraint(
            rule_type="budgets",
            rule_id="BUDGET-LIMITS",
            predicate=budget_predicate,
            context={},
            violation_message="budget:exceeded",
        ),
        EncodedConstraint(
            rule_type="infoflow",
            rule_id=infoflow_id,
            predicate=infoflow_predicate,
            context=base_context,
        ),
    ]


def _extract_rule(raw_rule: Any, fallback_rule_id: str) -> tuple[Any, str]:
    if isinstance(raw_rule, Mapping) and "predicate" in raw_rule:
        rule_id = raw_rule.get("rule_id", fallback_rule_id)
        return raw_rule.get("predicate", True), str(rule_id)
    return raw_rule, fallback_rule_id


def _diagnostics(
    config: SolverConfig,
    *,
    timeout: bool = False,
    predicate_error: bool = False,
    constraint_index: int | None = None,
    constraint_count: int | None = None,
) -> Mapping[str, Any]:
    diagnostics: dict[str, Any] = {
        "seed": config.random_seed,
        "tactic_profile": config.tactic_profile,
        "timeout_ms": config.timeout_ms,
    }
    if timeout:
        diagnostics["timeout"] = True
    if predicate_error:
        diagnostics["predicate_error"] = True
    if constraint_index is not None:
        diagnostics["constraint_index"] = constraint_index
    if constraint_count is not None:
        diagnostics["constraint_count"] = constraint_count
    return diagnostics
