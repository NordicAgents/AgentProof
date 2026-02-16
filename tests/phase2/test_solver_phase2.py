from __future__ import annotations

from copy import deepcopy

from vac.verification.solver import solve_constraints
from vac.verification.spec import load_spec


def test_solver_outcome_is_deterministic_for_identical_inputs(base_state, deterministic_registry, valid_proposal) -> None:
    spec = load_spec({"solver": {"random_seed": 17, "tactic_profile": "fixed", "timeout_ms": 250}})

    decision_a = solve_constraints(
        state=base_state,
        proposal=valid_proposal,
        tool_name="email.send",
        tool_permission_scope="scope:email.send",
        estimated_cost=1.0,
        registry=deterministic_registry,
        config=spec.solver,
    )
    decision_b = solve_constraints(
        state=base_state,
        proposal=deepcopy(valid_proposal),
        tool_name="email.send",
        tool_permission_scope="scope:email.send",
        estimated_cost=1.0,
        registry=deterministic_registry,
        config=spec.solver,
    )

    assert decision_a == decision_b
    assert decision_a.is_allowed is True
    assert decision_a.result_class == "sat"


def test_solver_degraded_predicate_error_maps_to_configured_result_class(base_state, deterministic_registry, valid_proposal) -> None:
    degraded = deepcopy(valid_proposal)
    degraded["precondition"] = {"left": 1, "right": 2}

    unknown_spec = load_spec({"solver": {"unknown_on_error": True}})
    unknown_decision = solve_constraints(
        state=base_state,
        proposal=degraded,
        tool_name="email.send",
        tool_permission_scope="scope:email.send",
        estimated_cost=1.0,
        registry=deterministic_registry,
        config=unknown_spec.solver,
    )

    unsat_spec = load_spec({"solver": {"unknown_on_error": False}})
    unsat_decision = solve_constraints(
        state=base_state,
        proposal=degraded,
        tool_name="email.send",
        tool_permission_scope="scope:email.send",
        estimated_cost=1.0,
        registry=deterministic_registry,
        config=unsat_spec.solver,
    )

    assert unknown_decision.is_allowed is False
    assert unknown_decision.result_class == "unknown"
    assert unsat_decision.is_allowed is False
    assert unsat_decision.result_class == "unsat"
