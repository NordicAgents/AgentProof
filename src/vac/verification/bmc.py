"""Offline bounded model checking (BMC) entry points."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Mapping

from vac.actions.schema import ActionProposal, ActionSchemaError, validate_action_schema
from vac.policy.evaluator import PolicyEvaluationError, evaluate_predicate
from vac.state.model import BudgetCounters, MonitorRuntimeState, State, canonical_state_hash
from vac.tools.registry import ToolRegistry

from .monitoring import evaluate_monitors
from .solver import solve_constraints
from .spec import load_spec

BMC_RESULT_SAT = "BMC_SAT_COUNTEREXAMPLE"
BMC_RESULT_UNSAT = "BMC_UNSAT_WITHIN_BOUND"
BMC_RESULT_TIMEOUT = "BMC_UNKNOWN_TIMEOUT"
BMC_RESULT_UNKNOWN = "BMC_UNKNOWN"


@dataclass(frozen=True)
class BmcTraceStep:
    """Single candidate step in a counterexample trace."""

    step: int
    action_summary: Mapping[str, Any]
    state_summary: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "action_summary": dict(self.action_summary),
            "state_summary": dict(self.state_summary),
        }


@dataclass(frozen=True)
class BmcResult:
    """Machine-readable bounded model checking outcome."""

    status: str
    result_code: str
    property_id: str
    bound_k: int
    steps_explored: int
    diagnostics: Mapping[str, Any]
    counterexample: tuple[BmcTraceStep, ...] = ()
    violated_property: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "result_code": self.result_code,
            "property_id": self.property_id,
            "bound_k": self.bound_k,
            "steps_explored": self.steps_explored,
            "diagnostics": dict(self.diagnostics),
            "counterexample": [step.to_dict() for step in self.counterexample],
        }
        if self.violated_property is not None:
            payload["violated_property"] = dict(self.violated_property)
        return payload


def run_bmc(spec: Mapping[str, Any], initial_state: State, bound_k: int, property_id: str) -> BmcResult:
    """Run offline BMC by unrolling transitions up to ``bound_k`` and checking property negation."""
    if bound_k < 0:
        raise ValueError("bound_k must be >= 0")

    verification_spec = load_spec(spec)
    bmc_config = spec.get("bmc", {}) if isinstance(spec, Mapping) else {}

    properties_raw = bmc_config.get("properties", [])
    if not isinstance(properties_raw, list):
        raise TypeError("bmc.properties must be a list")

    property_spec = _find_property(properties_raw, property_id)
    predicate = property_spec.get("predicate", True)

    transition_candidates = bmc_config.get("transition_candidates", [])
    if not isinstance(transition_candidates, list):
        raise TypeError("bmc.transition_candidates must be a list")

    registry = bmc_config.get("registry")
    if not isinstance(registry, ToolRegistry):
        registry = ToolRegistry()

    timeout_ms = int(bmc_config.get("timeout_ms", verification_spec.solver.timeout_ms * max(bound_k, 1)))
    if timeout_ms <= 0:
        return BmcResult(
            status="unknown",
            result_code=BMC_RESULT_TIMEOUT,
            property_id=property_id,
            bound_k=bound_k,
            steps_explored=0,
            diagnostics={"timeout_ms": timeout_ms, "reason": "timeout"},
        )

    started = time.monotonic()
    frontier: list[tuple[State, tuple[BmcTraceStep, ...], int]] = [(initial_state, (), 0)]
    explored = 0

    for depth in range(0, bound_k + 1):
        next_frontier: list[tuple[State, tuple[BmcTraceStep, ...], int]] = []
        for current_state, path, step_count in frontier:
            explored += 1
            violated, context_or_error = _is_property_violated(predicate, current_state, depth)
            if violated:
                return BmcResult(
                    status="sat",
                    result_code=BMC_RESULT_SAT,
                    property_id=property_id,
                    bound_k=bound_k,
                    steps_explored=explored,
                    diagnostics={"depth": depth, "satisfiable_negation": True},
                    counterexample=path,
                    violated_property={
                        "property_id": property_id,
                        "description": str(property_spec.get("description", "")),
                        "violation_step": depth,
                        "context": context_or_error,
                    },
                )
            if context_or_error is None:
                continue
            if isinstance(context_or_error, str):
                return BmcResult(
                    status="unknown",
                    result_code=BMC_RESULT_UNKNOWN,
                    property_id=property_id,
                    bound_k=bound_k,
                    steps_explored=explored,
                    diagnostics={"reason": "predicate_error", "error": context_or_error},
                )

            if depth == bound_k:
                continue

            for candidate in transition_candidates:
                elapsed_ms = (time.monotonic() - started) * 1000.0
                if elapsed_ms > timeout_ms:
                    return BmcResult(
                        status="unknown",
                        result_code=BMC_RESULT_TIMEOUT,
                        property_id=property_id,
                        bound_k=bound_k,
                        steps_explored=explored,
                        diagnostics={"timeout_ms": timeout_ms, "elapsed_ms": elapsed_ms, "reason": "timeout"},
                    )

                next_state, summary = _analysis_transition(current_state, candidate, registry, verification_spec)
                if next_state is None or summary is None:
                    continue
                trace_step = BmcTraceStep(step=step_count + 1, action_summary=summary["action"], state_summary=summary["state"])
                next_frontier.append((next_state, path + (trace_step,), step_count + 1))

        frontier = next_frontier

    return BmcResult(
        status="unsat",
        result_code=BMC_RESULT_UNSAT,
        property_id=property_id,
        bound_k=bound_k,
        steps_explored=explored,
        diagnostics={"bound_exhausted": True, "satisfiable_negation": False},
    )


def _find_property(properties: list[Any], property_id: str) -> Mapping[str, Any]:
    for item in properties:
        if isinstance(item, Mapping) and str(item.get("property_id", "")) == property_id:
            return item
    raise ValueError(f"unknown bmc property_id: {property_id}")


def _is_property_violated(predicate: Any, state: State, depth: int) -> tuple[bool, Mapping[str, Any] | str | None]:
    context = {
        "state": state.to_dict(),
        "step": depth,
        "used_calls": state.budgets.used_calls,
        "used_cost": state.budgets.used_cost,
        "status": state.status,
    }
    try:
        holds = evaluate_predicate(predicate, context)
    except PolicyEvaluationError as exc:
        return False, str(exc)
    return not holds, context


def _analysis_transition(
    state: State,
    proposal: Mapping[str, Any],
    registry: ToolRegistry,
    verification_spec: Any,
) -> tuple[State | None, Mapping[str, Any] | None]:
    event = {
        "action_type": str(proposal.get("action_type", "")),
        "tool_name": str(proposal.get("tool_name", "")),
        "decision": "pending",
        "tags": tuple(sorted(str(t) for t in proposal.get("tags", []) if isinstance(t, str))),
    }
    monitor_state, _snapshots, monitor_decision = evaluate_monitors(
        verification_spec.monitors,
        state.monitor_state.rules,
        event,
    )
    if monitor_decision.denied:
        return None, None

    try:
        validate_action_schema(proposal)
        action = ActionProposal.from_mapping(proposal)
    except ActionSchemaError:
        return None, None

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
        return None, None

    new_budgets = BudgetCounters(
        max_calls=state.budgets.max_calls,
        used_calls=state.budgets.used_calls + 1,
        max_cost=state.budgets.max_cost,
        used_cost=state.budgets.used_cost + estimated_cost,
        max_retries=state.budgets.max_retries,
        used_retries=state.budgets.used_retries,
    )

    candidate = state.with_updates(
        budgets=new_budgets,
        monitor_state=MonitorRuntimeState(rules=monitor_state),
        status="ready",
    )

    summary = {
        "action": {
            "action_type": action.action_type,
            "tool_name": action.tool_name,
            "proposal_id": str(action.metadata.get("proposal_id", "")),
            "estimated_cost": estimated_cost,
        },
        "state": {
            "status": candidate.status,
            "used_calls": candidate.budgets.used_calls,
            "used_cost": candidate.budgets.used_cost,
            "state_hash": canonical_state_hash(candidate),
        },
    }
    return candidate, summary
