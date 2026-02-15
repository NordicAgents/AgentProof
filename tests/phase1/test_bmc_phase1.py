from __future__ import annotations

from vac.state.model import State
from vac.tools.registry import ToolRegistry
from vac.verification.bmc import (
    BMC_RESULT_SAT,
    BMC_RESULT_TIMEOUT,
    BMC_RESULT_UNKNOWN,
    BMC_RESULT_UNSAT,
    run_bmc,
)


def _build_spec(registry: ToolRegistry, proposal: dict[str, object]) -> dict[str, object]:
    return {
        "solver": {"timeout_ms": 250},
        "bmc": {
            "registry": registry,
            "transition_candidates": [proposal],
            "properties": [
                {
                    "property_id": "P-NO-CALLS",
                    "description": "No tool calls should be consumed",
                    "predicate": {"op": "eq", "left": {"var": "used_calls"}, "right": 0},
                }
            ],
        },
    }


def test_bmc_sat_returns_counterexample_trace(
    base_state: State,
    deterministic_registry: ToolRegistry,
    valid_proposal: dict[str, object],
) -> None:
    result = run_bmc(
        _build_spec(deterministic_registry, valid_proposal),
        base_state,
        bound_k=1,
        property_id="P-NO-CALLS",
    )

    assert result.status == "sat"
    assert result.result_code == BMC_RESULT_SAT
    assert len(result.counterexample) == 1
    assert result.counterexample[0].step == 1
    assert result.counterexample[0].action_summary["tool_name"] == "email.send"
    assert result.counterexample[0].state_summary["used_calls"] == 1
    assert result.violated_property is not None
    assert result.violated_property["property_id"] == "P-NO-CALLS"


def test_bmc_unsat_within_bound_returns_explicit_code(
    base_state: State,
    deterministic_registry: ToolRegistry,
    valid_proposal: dict[str, object],
) -> None:
    spec = _build_spec(deterministic_registry, valid_proposal)
    spec["bmc"] = dict(spec["bmc"])  # shallow copy for mypy/typing
    spec["bmc"]["properties"] = [
        {
            "property_id": "P-CALLS-LTE-2",
            "description": "Used calls stays <=2 in one step",
            "predicate": {"op": "le", "left": {"var": "used_calls"}, "right": 2},
        }
    ]

    result = run_bmc(spec, base_state, bound_k=1, property_id="P-CALLS-LTE-2")

    assert result.status == "unsat"
    assert result.result_code == BMC_RESULT_UNSAT
    assert result.counterexample == ()


def test_bmc_timeout_returns_unknown_timeout_code(
    base_state: State,
    deterministic_registry: ToolRegistry,
    valid_proposal: dict[str, object],
) -> None:
    spec = _build_spec(deterministic_registry, valid_proposal)
    spec["bmc"] = dict(spec["bmc"])
    spec["bmc"]["timeout_ms"] = 0

    result = run_bmc(spec, base_state, bound_k=2, property_id="P-NO-CALLS")

    assert result.status == "unknown"
    assert result.result_code == BMC_RESULT_TIMEOUT


def test_bmc_predicate_error_returns_unknown_code(
    base_state: State,
    deterministic_registry: ToolRegistry,
    valid_proposal: dict[str, object],
) -> None:
    spec = _build_spec(deterministic_registry, valid_proposal)
    spec["bmc"] = dict(spec["bmc"])
    spec["bmc"]["properties"] = [
        {
            "property_id": "P-BAD",
            "description": "Malformed predicate",
            "predicate": {"left": 1, "right": 2},
        }
    ]

    result = run_bmc(spec, base_state, bound_k=1, property_id="P-BAD")

    assert result.status == "unknown"
    assert result.result_code == BMC_RESULT_UNKNOWN
