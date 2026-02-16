from __future__ import annotations

from copy import deepcopy

from vac.verification.bmc import BMC_RESULT_SAT, BMC_RESULT_TIMEOUT, BMC_RESULT_UNKNOWN, BMC_RESULT_UNSAT, run_bmc


def _base_bmc_spec(registry, proposal, predicate) -> dict[str, object]:
    return {
        "solver": {"timeout_ms": 250},
        "bmc": {
            "registry": registry,
            "transition_candidates": [proposal],
            "properties": [
                {
                    "property_id": "P-TEST",
                    "description": "small explicit property",
                    "predicate": predicate,
                }
            ],
        },
    }


def test_bmc_handles_sat_unsat_unknown_and_timeout(base_state, deterministic_registry, valid_proposal) -> None:
    sat_spec = _base_bmc_spec(
        deterministic_registry,
        valid_proposal,
        {"op": "eq", "left": {"var": "used_calls"}, "right": 0},
    )
    sat = run_bmc(sat_spec, base_state, bound_k=1, property_id="P-TEST")
    assert sat.status == "sat"
    assert sat.result_code == BMC_RESULT_SAT
    assert len(sat.counterexample) == 1

    unsat_spec = _base_bmc_spec(
        deterministic_registry,
        valid_proposal,
        {"op": "le", "left": {"var": "used_calls"}, "right": 2},
    )
    unsat = run_bmc(unsat_spec, base_state, bound_k=1, property_id="P-TEST")
    assert unsat.status == "unsat"
    assert unsat.result_code == BMC_RESULT_UNSAT

    unknown_spec = _base_bmc_spec(deterministic_registry, valid_proposal, {"left": 1, "right": 2})
    unknown = run_bmc(unknown_spec, base_state, bound_k=1, property_id="P-TEST")
    assert unknown.status == "unknown"
    assert unknown.result_code == BMC_RESULT_UNKNOWN

    timeout_spec = deepcopy(sat_spec)
    timeout_spec["bmc"] = dict(timeout_spec["bmc"])
    timeout_spec["bmc"]["timeout_ms"] = 0
    timeout = run_bmc(timeout_spec, base_state, bound_k=1, property_id="P-TEST")
    assert timeout.status == "unknown"
    assert timeout.result_code == BMC_RESULT_TIMEOUT
