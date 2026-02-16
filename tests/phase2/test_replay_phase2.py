from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from vac.engine.step import step
from vac.state.model import canonical_state_hash
from vac.verification.spec import load_spec


def _hash_payload(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _decision_hash(event: dict[str, object]) -> str:
    return _hash_payload(
        {
            "step_index": event["step_index"],
            "decision": event["decision"],
            "violations": event["violations"],
            "proposal_hash": event["proposal_hash"],
        }
    )


def _verification_report_hash(state, event: dict[str, object]) -> str:
    report = {
        "run_id": state.run_id,
        "status": state.status,
        "event": event,
        "state_hash": canonical_state_hash(state),
    }
    return _hash_payload(report)


def test_replay_parity_matches_decision_state_and_report_hash(base_state, deterministic_registry, valid_proposal) -> None:
    run_a = step(base_state, valid_proposal, deterministic_registry)
    run_b = step(base_state, deepcopy(valid_proposal), deterministic_registry)

    event_a = run_a.trace[-1]
    event_b = run_b.trace[-1]

    assert event_a["decision"] == event_b["decision"]
    assert _decision_hash(event_a) == _decision_hash(event_b)
    assert canonical_state_hash(run_a) == canonical_state_hash(run_b)
    assert _verification_report_hash(run_a, event_a) == _verification_report_hash(run_b, event_b)


def test_rejection_payload_identifiers_are_stable(base_state, deterministic_registry, valid_proposal) -> None:
    denied_proposal = deepcopy(valid_proposal)
    denied_proposal["tool_name"] = "not.registered"

    denied_a = step(base_state, denied_proposal, deterministic_registry)
    denied_b = step(base_state, deepcopy(denied_proposal), deterministic_registry)

    event_a = denied_a.trace[-1]
    event_b = denied_b.trace[-1]

    assert event_a["decision"] == "denied"
    assert event_a["proposal_hash"] == event_b["proposal_hash"]
    assert event_a["rejection"]["rule_id"] == "PERM-REGISTERED"
    assert event_a["rejection"] == event_b["rejection"]


def test_timeout_and_degraded_solver_policy_are_deterministic_and_safe(base_state, deterministic_registry, valid_proposal) -> None:
    timeout_spec = load_spec({"solver": {"timeout_ms": 0, "random_seed": 13, "tactic_profile": "fixed"}})
    timeout_a = step(base_state, valid_proposal, deterministic_registry, spec=timeout_spec)
    timeout_b = step(base_state, deepcopy(valid_proposal), deterministic_registry, spec=timeout_spec)

    assert timeout_a.status == "halted"
    assert timeout_a.trace[-1]["decision"] == "denied"
    assert timeout_a.trace[-1]["rejection"]["solver_result"] == "timeout"
    assert timeout_a.trace[-1]["rejection"] == timeout_b.trace[-1]["rejection"]

    degraded = deepcopy(valid_proposal)
    degraded["precondition"] = {"left": 1, "right": 2}

    unknown_spec = load_spec({"solver": {"unknown_on_error": True}})
    unknown = step(base_state, degraded, deterministic_registry, spec=unknown_spec)
    assert unknown.status == "halted"
    assert unknown.trace[-1]["decision"] == "denied"
    assert unknown.trace[-1]["rejection"]["solver_result"] == "unknown"

    unsat_spec = load_spec({"solver": {"unknown_on_error": False}})
    unsat = step(base_state, degraded, deterministic_registry, spec=unsat_spec)
    assert unsat.status == "halted"
    assert unsat.trace[-1]["decision"] == "denied"
    assert unsat.trace[-1]["rejection"]["solver_result"] == "unsat"
