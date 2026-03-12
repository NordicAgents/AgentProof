"""Tests for extended temporal DSL patterns."""

from __future__ import annotations

import pytest
from agentproof.monitor.ltl import (
    CompiledMonitorRule,
    MonitorCompileError,
    MonitorRuleSpec,
    compile_monitor_rule,
    evaluate_monitors,
)


def _eval_trace(rule: CompiledMonitorRule, events: list[dict]) -> list[bool]:
    """Evaluate a compiled rule against a trace, returning violation flags per step."""
    state: dict[str, int] = {}
    violations = []
    for event in events:
        state, snapshots, _ = evaluate_monitors((rule,), state, event)
        violations.append(snapshots[0].violation)
    return violations


# ---------------------------------------------------------------------------
# Regression: original three patterns still work
# ---------------------------------------------------------------------------

class TestForbiddenRegression:
    def test_no_violation(self):
        rule = compile_monitor_rule(MonitorRuleSpec("r", "G !tool:drop_db"))
        violations = _eval_trace(rule, [
            {"tool_name": "read"},
            {"tool_name": "write"},
        ])
        assert violations == [False, False]

    def test_violation(self):
        rule = compile_monitor_rule(MonitorRuleSpec("r", "G !tool:drop_db"))
        violations = _eval_trace(rule, [
            {"tool_name": "read"},
            {"tool_name": "drop_db"},
        ])
        assert violations == [False, True]


class TestImplFutureRegression:
    def test_no_violation(self):
        rule = compile_monitor_rule(MonitorRuleSpec("r", "decision:deploy -> F action:approve"))
        violations = _eval_trace(rule, [
            {"decision": "deploy"},
            {"action_type": "approve"},
        ])
        assert violations == [False, False]

    def test_violation(self):
        rule = compile_monitor_rule(MonitorRuleSpec("r", "decision:deploy -> F action:approve"))
        violations = _eval_trace(rule, [
            {"decision": "deploy"},
            {},
            {"decision": "deploy"},
        ])
        assert violations == [False, False, True]


class TestUntilRegression:
    def test_satisfied(self):
        rule = compile_monitor_rule(MonitorRuleSpec("r", "read_only U action:signoff"))
        violations = _eval_trace(rule, [
            {"tags": ["read_only"]},
            {"action_type": "signoff"},
        ])
        assert violations == [False, False]

    def test_violation(self):
        rule = compile_monitor_rule(MonitorRuleSpec("r", "read_only U action:signoff"))
        violations = _eval_trace(rule, [
            {},
        ])
        assert violations == [True]


# ---------------------------------------------------------------------------
# Conjunction: (expr) AND (expr)
# ---------------------------------------------------------------------------

class TestConjunction:
    def test_both_pass(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "(G !tool:drop_db) AND (G !tool:rm_rf)")
        )
        violations = _eval_trace(rule, [
            {"tool_name": "read"},
            {"tool_name": "write"},
        ])
        assert violations == [False, False]

    def test_first_violates(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "(G !tool:drop_db) AND (G !tool:rm_rf)")
        )
        violations = _eval_trace(rule, [
            {"tool_name": "drop_db"},
        ])
        assert violations == [True]

    def test_second_violates(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "(G !tool:drop_db) AND (G !tool:rm_rf)")
        )
        violations = _eval_trace(rule, [
            {"tool_name": "rm_rf"},
        ])
        assert violations == [True]

    def test_both_violate(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "(G !tool:drop_db) AND (G !tool:rm_rf)")
        )
        # Trigger first, then second
        violations = _eval_trace(rule, [
            {"tool_name": "drop_db"},
            {"tool_name": "rm_rf"},
        ])
        assert violations == [True, True]


# ---------------------------------------------------------------------------
# Disjunction: (expr) OR (expr)
# ---------------------------------------------------------------------------

class TestDisjunction:
    def test_both_pass(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "(G !tool:drop_db) OR (G !tool:rm_rf)")
        )
        violations = _eval_trace(rule, [
            {"tool_name": "read"},
        ])
        assert violations == [False]

    def test_one_violates_no_overall_violation(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "(G !tool:drop_db) OR (G !tool:rm_rf)")
        )
        violations = _eval_trace(rule, [
            {"tool_name": "drop_db"},
        ])
        # OR: violation only if BOTH sub-expressions violate
        assert violations == [False]

    def test_both_violate(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "(G !tool:drop_db) OR (G !tool:rm_rf)")
        )
        violations = _eval_trace(rule, [
            {"tool_name": "drop_db"},
            {"tool_name": "rm_rf"},
        ])
        # First event violates left only, second event violates both
        assert violations[-1] is True


# ---------------------------------------------------------------------------
# Bounded response: a -> F[<=k] b
# ---------------------------------------------------------------------------

class TestBoundedResponse:
    def test_within_bound(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:deploy -> F[<=3] action:approve")
        )
        violations = _eval_trace(rule, [
            {"decision": "deploy"},
            {},
            {"action_type": "approve"},
        ])
        assert violations == [False, False, False]

    def test_exactly_at_bound(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:deploy -> F[<=3] action:approve")
        )
        violations = _eval_trace(rule, [
            {"decision": "deploy"},
            {},
            {},
            {"action_type": "approve"},
        ])
        assert violations == [False, False, False, False]

    def test_exceeds_bound(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:deploy -> F[<=3] action:approve")
        )
        violations = _eval_trace(rule, [
            {"decision": "deploy"},
            {},
            {},
            {},
        ])
        # Should violate at step 4 (index 3) — exceeded bound of 3
        assert violations[-1] is True

    def test_no_trigger_no_violation(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:deploy -> F[<=2] action:approve")
        )
        violations = _eval_trace(rule, [
            {},
            {},
            {},
            {},
        ])
        assert violations == [False, False, False, False]

    def test_bound_of_1(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:deploy -> F[<=1] action:approve")
        )
        # Trigger, then approve immediately
        violations = _eval_trace(rule, [
            {"decision": "deploy"},
            {"action_type": "approve"},
        ])
        assert violations == [False, False]

    def test_bound_of_1_exceeded(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:deploy -> F[<=1] action:approve")
        )
        # Trigger, then no approve within 1 step
        violations = _eval_trace(rule, [
            {"decision": "deploy"},
            {},
        ])
        assert violations == [False, True]


# ---------------------------------------------------------------------------
# Response chain: a -> F b -> F c
# ---------------------------------------------------------------------------

class TestResponseChain:
    def test_happy_path(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:submit -> F action:review -> F action:approve")
        )
        violations = _eval_trace(rule, [
            {"decision": "submit"},
            {"action_type": "review"},
            {"action_type": "approve"},
        ])
        assert all(v is False for v in violations)

    def test_first_repeated_before_second(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:submit -> F action:review -> F action:approve")
        )
        violations = _eval_trace(rule, [
            {"decision": "submit"},
            {"decision": "submit"},  # Repeat before review — violation
        ])
        assert violations[-1] is True

    def test_no_trigger(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:submit -> F action:review -> F action:approve")
        )
        violations = _eval_trace(rule, [
            {},
            {},
        ])
        assert violations == [False, False]


# ---------------------------------------------------------------------------
# Compile errors
# ---------------------------------------------------------------------------

class TestCompileErrors:
    def test_invalid_level(self):
        with pytest.raises(MonitorCompileError, match="invalid violation handling level"):
            compile_monitor_rule(MonitorRuleSpec("r", "G !a", on_violation="unknown"))

    def test_unsupported_expr(self):
        with pytest.raises(MonitorCompileError, match="unsupported"):
            compile_monitor_rule(MonitorRuleSpec("r", "INVALID SYNTAX"))


# ---------------------------------------------------------------------------
# Mixed patterns with evaluate_monitors
# ---------------------------------------------------------------------------

class TestMixedMonitors:
    def test_multiple_rules_combined(self):
        r1 = compile_monitor_rule(MonitorRuleSpec("forbidden", "G !tool:drop_db", on_violation="halt"))
        r2 = compile_monitor_rule(
            MonitorRuleSpec("bounded", "decision:deploy -> F[<=2] action:approve", on_violation="block")
        )
        state: dict[str, int] = {}

        # Normal event
        state, snaps, dec = evaluate_monitors((r1, r2), state, {"tool_name": "read"})
        assert dec.denied is False

        # Deploy triggers bounded countdown
        state, snaps, dec = evaluate_monitors((r1, r2), state, {"decision": "deploy"})
        assert dec.denied is False

        # Drop_db triggers halt
        state, snaps, dec = evaluate_monitors((r1, r2), state, {"tool_name": "drop_db"})
        assert dec.halt is True

    def test_conjunction_with_halt(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("conj", "(G !tool:a) AND (G !tool:b)", on_violation="escalate")
        )
        state, snaps, dec = evaluate_monitors((rule,), {}, {"tool_name": "a"})
        assert dec.escalate is True
