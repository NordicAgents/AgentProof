"""Single deterministic engine step transition."""

from __future__ import annotations

from typing import Any, Mapping

from vac.actions.schema import ActionProposal, ActionSchemaError, validate_action_schema
from vac.enterprise import (
    EnterprisePolicyError,
    MultiAgentPolicyError,
    evaluate_information_flow_payload,
    evaluate_multi_agent_payload,
    evaluate_sandbox_profile,
)
from vac.state.model import BudgetCounters, MonitorRuntimeState, State, canonical_state_hash
from vac.tools.registry import ToolRegistry, ToolRegistryError
from vac.verification.monitoring import MonitorSnapshot, evaluate_monitors
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
    verification_spec = spec if spec is not None else load_spec(None)

    event = {
        "action_type": str(proposal.get("action_type", "")),
        "tool_name": str(proposal.get("tool_name", "")),
        "decision": "pending",
        "tags": tuple(sorted(str(t) for t in proposal.get("tags", []) if isinstance(t, str))),
    }
    monitor_state, monitor_snapshots, monitor_decision = evaluate_monitors(
        verification_spec.monitors,
        state.monitor_state.rules,
        event,
    )

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
        return _rejected(
            state,
            proposal,
            before_hash,
            [violation],
            rejection,
            monitor_state,
            monitor_snapshots,
            status="halted",
        )

    if monitor_decision.denied:
        return _monitor_rejection(
            state=state,
            proposal=proposal,
            before_hash=before_hash,
            monitor_state=monitor_state,
            monitor_snapshots=monitor_snapshots,
            monitor_decision=monitor_decision,
        )

    # 2) phase-4 enterprise hardening checks
    try:
        if not evaluate_information_flow_payload(proposal.get("infoflow_labels")):
            return _rejected(
                state,
                proposal,
                before_hash,
                ["infoflow:label violation"],
                {
                    "rule_type": "infoflow",
                    "rule_id": "INFOFLOW-LABELS",
                    "solver_result": "unsat",
                    "diagnostics": {},
                },
                monitor_state,
                monitor_snapshots,
                status="halted",
            )

        if not evaluate_multi_agent_payload(proposal.get("multi_agent")):
            return _rejected(
                state,
                proposal,
                before_hash,
                ["multi-agent:policy violation"],
                {
                    "rule_type": "permissions",
                    "rule_id": "MULTIAGENT-ACCESS",
                    "solver_result": "unsat",
                    "diagnostics": {},
                },
                monitor_state,
                monitor_snapshots,
                status="halted",
            )
    except (EnterprisePolicyError, MultiAgentPolicyError) as exc:
        return _rejected(
            state,
            proposal,
            before_hash,
            [f"enterprise:{exc}"],
            {
                "rule_type": "schema",
                "rule_id": "ENTERPRISE-POLICY",
                "solver_result": "unknown",
                "diagnostics": {"error": str(exc)},
            },
            monitor_state,
            monitor_snapshots,
            status="halted",
        )

    # 3) solver-backed policy layer
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
        return _rejected(
            state,
            proposal,
            before_hash,
            [violation],
            rejection,
            monitor_state,
            monitor_snapshots,
            status="halted",
        )

    # 4) execute wrapper (all side-effects must stay inside wrapper)
    try:
        if registry.is_registered(action.tool_name):
            required_profile = registry.get(action.tool_name).sandbox_profile
            requested_profile = str(proposal.get("sandbox_profile", "standard"))
            if not evaluate_sandbox_profile(required=required_profile, requested=requested_profile):
                return _rejected(
                    state,
                    proposal,
                    before_hash,
                    [f"sandbox:requires {required_profile}, got {requested_profile}"],
                    {
                        "rule_type": "permissions",
                        "rule_id": "SANDBOX-PROFILE",
                        "solver_result": "unsat",
                        "diagnostics": {
                            "required": required_profile,
                            "requested": requested_profile,
                        },
                    },
                    monitor_state,
                    monitor_snapshots,
                    status="halted",
                )

        tool_output = registry.invoke(action.tool_name, action.input, set(state.permissions))
    except ToolRegistryError as exc:
        violations = [f"execute:{exc}"]
        rejection = {
            "rule_type": "execute",
            "rule_id": "EXECUTE-WRAPPER",
            "solver_result": "unknown",
            "diagnostics": {"error": str(exc)},
        }
        return _rejected(
            state,
            proposal,
            before_hash,
            violations,
            rejection,
            monitor_state,
            monitor_snapshots,
            status="halted",
        )

    # 5) append trace
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

    trace_event = {
        "step_index": next_step_index,
        "proposal_hash": _proposal_hash(action.metadata.get("proposal_id", "")),
        "decision": "allowed",
        "violations": [],
        "tool_call": {"name": action.tool_name, "input": dict(action.input)},
        "state_hash_before": before_hash,
        "state_hash_after": "pending",
        "monitor": _monitor_trace_payload(monitor_snapshots, monitor_decision.escalate),
    }

    candidate = state.with_updates(
        memory=new_memory,
        budgets=new_budgets,
        monitor_state=MonitorRuntimeState(rules=monitor_state),
        trace=tuple(updated_trace + [trace_event]),
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


def _monitor_rejection(
    *,
    state: State,
    proposal: Mapping[str, Any],
    before_hash: str,
    monitor_state: Mapping[str, int],
    monitor_snapshots: list[MonitorSnapshot],
    monitor_decision: Any,
) -> State:
    violations = [f"temporal:{snapshot.rule_id}" for snapshot in monitor_snapshots if snapshot.violation]
    first = sorted((s for s in monitor_snapshots if s.violation), key=lambda s: s.rule_id)[0]
    rejection = {
        "rule_type": "temporal",
        "rule_id": first.rule_id,
        "solver_result": "unsat",
        "diagnostics": {
            "handling": first.handling,
            "escalate": monitor_decision.escalate,
        },
    }
    return _rejected(
        state,
        proposal,
        before_hash,
        violations,
        rejection,
        monitor_state,
        monitor_snapshots,
        status=monitor_decision.status,
    )


def _monitor_trace_payload(monitor_snapshots: list[MonitorSnapshot], escalated: bool) -> Mapping[str, Any]:
    return {
        "transitions": [snapshot.to_trace_entry() for snapshot in monitor_snapshots],
        "escalated": escalated,
    }


def _rejected(
    state: State,
    proposal: Mapping[str, Any],
    before_hash: str,
    violations: list[str],
    rejection: Mapping[str, Any],
    monitor_state: Mapping[str, int],
    monitor_snapshots: list[MonitorSnapshot],
    *,
    status: str,
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
            "monitor": _monitor_trace_payload(monitor_snapshots, bool(rejection.get("diagnostics", {}).get("escalate", False))),
        }
    )
    return state.with_updates(trace=tuple(trace), monitor_state=MonitorRuntimeState(rules=monitor_state), status=status)
