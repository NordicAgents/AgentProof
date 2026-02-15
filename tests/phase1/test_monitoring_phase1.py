from __future__ import annotations

from vac.engine.step import step
from vac.state.model import MonitorRuntimeState, State
from vac.tools.registry import ToolRegistry
from vac.verification.monitoring import MonitorRuleSpec, compile_monitor_rule
from vac.verification.spec import load_spec


def test_compiles_ltl_subset_to_deterministic_table() -> None:
    forbidden = compile_monitor_rule(MonitorRuleSpec(rule_id="TEMP-1", dsl="G !tool:email.send", on_violation="block"))

    assert forbidden.initial_state == 0
    assert forbidden.transition_table[0][0] == 0
    assert forbidden.transition_table[0][1] == 1


def test_step_records_monitor_transition_snapshot_and_blocks(base_state: State, deterministic_registry: ToolRegistry, valid_proposal: dict[str, object]) -> None:
    spec = load_spec(
        {
            "temporal": [
                {"rule_id": "TEMP-BLOCK", "dsl": "G !tool:email.send", "on_violation": "block"},
            ]
        }
    )

    result = step(base_state, valid_proposal, deterministic_registry, spec=spec)

    assert result.status == "ready"
    assert isinstance(result.monitor_state, MonitorRuntimeState)
    assert result.monitor_state.rules["TEMP-BLOCK"] == 1
    event = result.trace[-1]
    assert event["decision"] == "denied"
    assert event["violations"] == ["temporal:TEMP-BLOCK"]
    monitor_snapshot = event["monitor"]["transitions"][0]
    assert monitor_snapshot == {
        "rule_id": "TEMP-BLOCK",
        "prior_state": 0,
        "next_state": 1,
        "violation": True,
        "handling": "block",
    }


def test_monitor_violation_handling_levels(base_state: State, deterministic_registry: ToolRegistry, valid_proposal: dict[str, object]) -> None:
    warn_spec = load_spec(
        {
            "temporal": [
                {"rule_id": "TEMP-WARN", "dsl": "G !tool:email.send", "on_violation": "warn"},
            ]
        }
    )
    warn_result = step(base_state, valid_proposal, deterministic_registry, spec=warn_spec)
    assert warn_result.status == "ready"
    assert warn_result.trace[-1]["decision"] == "allowed"

    halt_spec = load_spec(
        {
            "temporal": [
                {"rule_id": "TEMP-HALT", "dsl": "G !tool:email.send", "on_violation": "halt"},
            ]
        }
    )
    halt_result = step(base_state, valid_proposal, deterministic_registry, spec=halt_spec)
    assert halt_result.status == "halted"
    assert halt_result.trace[-1]["decision"] == "denied"

    escalate_spec = load_spec(
        {
            "temporal": [
                {"rule_id": "TEMP-ESC", "dsl": "G !tool:email.send", "on_violation": "escalate"},
            ]
        }
    )
    escalate_result = step(base_state, valid_proposal, deterministic_registry, spec=escalate_spec)
    assert escalate_result.status == "halted"
    assert escalate_result.trace[-1]["monitor"]["escalated"] is True
