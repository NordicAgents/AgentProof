from __future__ import annotations

from vac.verification.monitoring import MonitorRuleSpec, compile_monitor_rule, evaluate_monitors


def test_monitor_automata_transitions_for_representative_rules() -> None:
    rules = (
        compile_monitor_rule(MonitorRuleSpec(rule_id="NO_EMAIL", dsl="G !tool:email.send", on_violation="block")),
        compile_monitor_rule(MonitorRuleSpec(rule_id="CALL_IMPLIES_ALLOW", dsl="tool:email.send -> F decision:allowed", on_violation="halt")),
        compile_monitor_rule(MonitorRuleSpec(rule_id="READY_UNTIL_ALLOWED", dsl="action:tool_call U decision:allowed", on_violation="warn")),
    )

    state = {}
    state, snapshots_1, decision_1 = evaluate_monitors(
        rules,
        state,
        {"action_type": "tool_call", "tool_name": "email.send", "decision": "pending", "tags": ()},
    )
    assert state == {"NO_EMAIL": 1, "CALL_IMPLIES_ALLOW": 1, "READY_UNTIL_ALLOWED": 0}
    assert [s.violation for s in snapshots_1] == [True, False, False]
    assert decision_1.denied is True
    assert decision_1.halt is False

    state, snapshots_2, decision_2 = evaluate_monitors(
        rules,
        state,
        {"action_type": "tool_call", "tool_name": "email.send", "decision": "denied", "tags": ()},
    )
    assert state == {"NO_EMAIL": 1, "CALL_IMPLIES_ALLOW": 2, "READY_UNTIL_ALLOWED": 0}
    assert snapshots_2[1].violation is True
    assert snapshots_2[1].handling == "halt"
    assert decision_2.halt is True

    state, snapshots_3, decision_3 = evaluate_monitors(
        rules,
        state,
        {"action_type": "tool_call", "tool_name": "email.send", "decision": "allowed", "tags": ()},
    )
    assert state == {"NO_EMAIL": 1, "CALL_IMPLIES_ALLOW": 2, "READY_UNTIL_ALLOWED": 1}
    assert snapshots_3[1].violation is True
    assert snapshots_3[2].violation is False
    assert decision_3.halt is True
