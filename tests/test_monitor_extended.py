"""Tests for extended temporal DSL patterns and LTLf progression semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agentproof.monitor.ltl import (
    And,
    Atom,
    BoundedEventually,
    CompiledMonitorRule,
    Eventually,
    Globally,
    MonitorCompileError,
    MonitorRuleSpec,
    Not,
    Or,
    Until,
    _parse_dsl,
    compile_monitor_rule,
    evaluate_monitors,
    finalize_monitors,
    parse_dsl,
)

_CORPUS_POLICIES = (
    Path(__file__).resolve().parents[1] / "corpus" / "policies" / "temporal_policies.json"
)


def _eval_trace(rule: CompiledMonitorRule, events: list[dict]) -> list[bool]:
    """Evaluate a compiled rule against a trace, returning violation flags per step."""
    state: dict[str, int] = {}
    violations = []
    for event in events:
        state, snapshots, _ = evaluate_monitors((rule,), state, event)
        violations.append(snapshots[0].violation)
    return violations


def _eval_trace_final(rule: CompiledMonitorRule, events: list[dict]) -> tuple[list[bool], bool]:
    """Evaluate a complete (terminating) trace: per-step violations plus the
    LTLf end-of-trace check for unfulfilled obligations."""
    state: dict[str, int] = {}
    violations = []
    for event in events:
        state, snapshots, _ = evaluate_monitors((rule,), state, event)
        violations.append(snapshots[0].violation)
    final_snapshots, _ = finalize_monitors((rule,), state)
    return violations, final_snapshots[0].violation


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
        violations, final = _eval_trace_final(rule, [
            {"decision": "deploy"},
            {"action_type": "approve"},
        ])
        assert violations == [False, False]
        assert final is False

    def test_pending_obligation_at_termination(self):
        # LTLf G(a -> F b): no finite prefix is bad (b may still arrive), so
        # violations surface only when the trace ends with the obligation open.
        rule = compile_monitor_rule(MonitorRuleSpec("r", "decision:deploy -> F action:approve"))
        violations, final = _eval_trace_final(rule, [
            {"decision": "deploy"},
            {},
            {"decision": "deploy"},
        ])
        assert violations == [False, False, False]
        assert final is True

    def test_obligations_merge_and_discharge(self):
        # G(a -> F b) on a,a,b: both a's are answered by b at position 2
        # (F is reflexive-forward), so the trace is accepted.
        rule = compile_monitor_rule(MonitorRuleSpec("r", "decision:deploy -> F action:approve"))
        violations, final = _eval_trace_final(rule, [
            {"decision": "deploy"},
            {"decision": "deploy"},
            {"action_type": "approve"},
        ])
        assert violations == [False, False, False]
        assert final is False


class TestUntilRegression:
    def test_satisfied(self):
        rule = compile_monitor_rule(MonitorRuleSpec("r", "read_only U action:signoff"))
        violations, final = _eval_trace_final(rule, [
            {"tags": ["read_only"]},
            {"action_type": "signoff"},
        ])
        assert violations == [False, False]
        assert final is False

    def test_violation(self):
        rule = compile_monitor_rule(MonitorRuleSpec("r", "read_only U action:signoff"))
        violations = _eval_trace(rule, [
            {},
        ])
        assert violations == [True]

    def test_strong_until_never_satisfied(self):
        # a U b with a holding forever but b never occurring: no bad prefix,
        # but a finite trace ending without b violates strong until.
        rule = compile_monitor_rule(MonitorRuleSpec("r", "read_only U action:signoff"))
        violations, final = _eval_trace_final(rule, [
            {"tags": ["read_only"]},
            {"tags": ["read_only"]},
        ])
        assert violations == [False, False]
        assert final is True


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


class TestBoundedResponseBoundary:
    """Exact boundary semantics: BoundedEventually(b, k) at trigger position i
    requires b at some j in [i, i+k] — the trigger position counts, then k
    further events."""

    def test_fulfilled_exactly_at_step_k(self):
        # k=2, trigger at position 0, approve at position 2 = i+k: satisfied,
        # so no per-step violation and no open obligation at termination.
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:deploy -> F[<=2] action:approve")
        )
        violations, final = _eval_trace_final(rule, [
            {"decision": "deploy"},
            {},
            {"action_type": "approve"},
        ])
        assert violations == [False, False, False]
        assert final is False

    def test_bad_prefix_at_step_k_plus_1(self):
        # k=2, trigger at position 0: b must occur in positions {0,1,2}. All
        # three lack approve, so after position 2 the formula is FALSE — a bad
        # prefix no extension can repair (violation at index 2, and final).
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:deploy -> F[<=2] action:approve")
        )
        violations, final = _eval_trace_final(rule, [
            {"decision": "deploy"},
            {},
            {},
        ])
        assert violations == [False, False, True]
        assert final is True

    def test_simultaneous_trigger_and_fulfilment(self):
        # Trigger position counts: an event satisfying both a and b discharges
        # BoundedEventually at j = i immediately — the trace is accepted.
        rule = compile_monitor_rule(MonitorRuleSpec("r", "req -> F[<=1] ack"))
        violations, final = _eval_trace_final(rule, [
            {"tags": ["req", "ack"]},
        ])
        assert violations == [False]
        assert final is False


class TestBoundedResponseStateComplexity:
    """'a -> F[<=k] b' must compile to O(k) states (~k+2): the canonicalizer
    collapses accumulated same-operand deadlines via
    BE(f,i) AND BE(f,j) == BE(f,min(i,j)). Before the fix the state space was
    2^k+1 (every subset of pending deadlines was a distinct state) and k=12
    already exceeded the 4096-state compilation cap."""

    @pytest.mark.parametrize("k", [3, 10, 25, 100])
    def test_linear_state_count(self, k):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", f"decision:deploy -> F[<={k}] action:approve")
        )
        num_states = len(rule.transition_table)
        assert num_states <= k + 3, (
            f"k={k} compiled to {num_states} states (expected O(k), ~k+2)"
        )

    def test_k_100_compiles_and_keeps_boundary_semantics(self):
        # k=100 compiles fine (was: MonitorCompileError at the state cap) and
        # the deadline semantics are unchanged: BE(b, 100) triggered at
        # position 0 allows b at positions 0..100, so 99 further blank events
        # leave the deadline open (b could still arrive at position 100) and
        # the 100th blank completes the bad prefix.
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:deploy -> F[<=100] action:approve")
        )
        violations = _eval_trace(rule, [{"decision": "deploy"}] + [{}] * 99)
        assert violations == [False] * 100
        violations = _eval_trace(rule, [{"decision": "deploy"}] + [{}] * 100)
        assert violations == [False] * 100 + [True]
        # A fulfilment exactly at position k is still accepted.
        violations, final = _eval_trace_final(
            rule,
            [{"decision": "deploy"}] + [{}] * 99 + [{"action_type": "approve"}],
        )
        assert violations == [False] * 101
        assert final is False


# ---------------------------------------------------------------------------
# Response chain: a -> F b -> F c, i.e. G(a -> F(b AND F c))
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

    def test_chain_incomplete_at_termination(self):
        # LTLf G(a -> F(b AND F c)): each occurrence of a imposes its own
        # b-then-c obligation; here neither is met, so the trace is rejected
        # when it ends (pure liveness — no per-step bad prefix exists).
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:submit -> F action:review -> F action:approve")
        )
        violations, final = _eval_trace_final(rule, [
            {"decision": "submit"},
            {"decision": "submit"},
        ])
        assert all(v is False for v in violations)
        assert final is True

    def test_chain_mid_step_at_termination(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:submit -> F action:review -> F action:approve")
        )
        violations, final = _eval_trace_final(rule, [
            {"decision": "submit"},
            {"action_type": "review"},
        ])
        assert all(v is False for v in violations)
        assert final is True

    def test_no_trigger(self):
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:submit -> F action:review -> F action:approve")
        )
        violations = _eval_trace(rule, [
            {},
            {},
        ])
        assert violations == [False, False]


class TestResponseChainReArm:
    """Regression for the re-arming bug: a fresh antecedent occurring
    mid-chain imposes a NEW b-then-c obligation; it must not be absorbed into
    the already-progressing one."""

    def test_rearm_mid_chain_rejected(self):
        # G(a -> F(b AND F c)) on a,b,a,c: the a at position 2 needs a review
        # at some j >= 2 followed by approve — positions 2..3 are a,c with no
        # b, so the formula fails at position 2. Rejected at termination
        # (no bad prefix: a suffix b,c could still have repaired it).
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:submit -> F action:review -> F action:approve")
        )
        violations, final = _eval_trace_final(rule, [
            {"decision": "submit"},
            {"action_type": "review"},
            {"decision": "submit"},
            {"action_type": "approve"},
        ])
        assert violations == [False, False, False, False]
        assert final is True

    def test_rearm_then_completed_accepted(self):
        # a,b,a,b,c: position 0's a is answered by b@1 then c@4; position 2's
        # a is answered by b@3 then c@4 (F is reflexive-forward) — accepted.
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:submit -> F action:review -> F action:approve")
        )
        violations, final = _eval_trace_final(rule, [
            {"decision": "submit"},
            {"action_type": "review"},
            {"decision": "submit"},
            {"action_type": "review"},
            {"action_type": "approve"},
        ])
        assert violations == [False, False, False, False, False]
        assert final is False


# ---------------------------------------------------------------------------
# Nested until — compiled compositionally, not as a literal predicate string
# ---------------------------------------------------------------------------

class TestNestedUntilRight:
    """a U (b U c): exists j with (b U c) at j and a at all positions < j."""

    DSL = "taga U (tagb U tagc)"

    def test_accept_a_a_b_c(self):
        # j=2: (b U c) holds at 2 (b@2 then c@3) and a holds at 0,1 — accepted.
        rule = compile_monitor_rule(MonitorRuleSpec("r", self.DSL))
        violations, final = _eval_trace_final(rule, [
            {"tags": ["taga"]},
            {"tags": ["taga"]},
            {"tags": ["tagb"]},
            {"tags": ["tagc"]},
        ])
        assert violations == [False, False, False, False]
        assert final is False

    def test_accept_a_c(self):
        # j=1: (b U c) holds at 1 immediately via c@1, and a holds at 0 — accepted.
        rule = compile_monitor_rule(MonitorRuleSpec("r", self.DSL))
        violations, final = _eval_trace_final(rule, [
            {"tags": ["taga"]},
            {"tags": ["tagc"]},
        ])
        assert violations == [False, False]
        assert final is False

    def test_reject_a_b_a_c(self):
        # No j works: j=0 fails (position 0 is a, neither b nor c); j=1 fails
        # ((b U c)@1 breaks at position 2 = a before c); j>=2 fails (a does
        # not hold at position 1). The a@2 makes the prefix unrepairable, so
        # a bad prefix is flagged at index 2 and the trace is rejected.
        rule = compile_monitor_rule(MonitorRuleSpec("r", self.DSL))
        violations, final = _eval_trace_final(rule, [
            {"tags": ["taga"]},
            {"tags": ["tagb"]},
            {"tags": ["taga"]},
            {"tags": ["tagc"]},
        ])
        assert violations == [False, False, True, True]
        assert final is True

    def test_reject_unfulfilled_at_termination(self):
        # a,a: (b U c) never starts holding — obligation open at termination.
        rule = compile_monitor_rule(MonitorRuleSpec("r", self.DSL))
        violations, final = _eval_trace_final(rule, [
            {"tags": ["taga"]},
            {"tags": ["taga"]},
        ])
        assert violations == [False, False]
        assert final is True


class TestNestedUntilLeft:
    """(a U b) U c: exists j with c at j and (a U b) at all positions < j."""

    DSL = "(taga U tagb) U tagc"

    def test_accept_b_c(self):
        # j=1: c@1, and (a U b) holds at 0 via b@0 — accepted.
        rule = compile_monitor_rule(MonitorRuleSpec("r", self.DSL))
        violations, final = _eval_trace_final(rule, [
            {"tags": ["tagb"]},
            {"tags": ["tagc"]},
        ])
        assert violations == [False, False]
        assert final is False

    def test_reject_a_c(self):
        # j=0 fails (position 0 is a, not c); j=1 needs (a U b)@0, but b never
        # occurs, so a U b fails at 0. Position 1's c without a preceding
        # satisfied (a U b) makes the prefix unrepairable: bad prefix at index 1.
        rule = compile_monitor_rule(MonitorRuleSpec("r", self.DSL))
        violations, final = _eval_trace_final(rule, [
            {"tags": ["taga"]},
            {"tags": ["tagc"]},
        ])
        assert violations == [False, True]
        assert final is True


# ---------------------------------------------------------------------------
# Empty-trace verdicts (LTLf: empty trace satisfies phi iff nu(phi))
# ---------------------------------------------------------------------------

class TestEmptyTrace:
    def test_forbidden_accepts_empty(self):
        # nu(G !x) = true: an empty trace trivially never performs x.
        rule = compile_monitor_rule(MonitorRuleSpec("r", "G !tool:drop_db"))
        snapshots, _ = finalize_monitors((rule,), {})
        assert snapshots[0].violation is False

    def test_until_rejects_empty(self):
        # nu(a U b) = false: strong until requires b to actually occur.
        rule = compile_monitor_rule(MonitorRuleSpec("r", "taga U tagb"))
        snapshots, _ = finalize_monitors((rule,), {})
        assert snapshots[0].violation is True

    def test_response_accepts_empty(self):
        # nu(G(a -> F b)) = true: no a ever occurs on the empty trace.
        rule = compile_monitor_rule(MonitorRuleSpec("r", "taga -> F tagb"))
        snapshots, _ = finalize_monitors((rule,), {})
        assert snapshots[0].violation is False


# ---------------------------------------------------------------------------
# Simultaneous and repeated antecedents for response
# ---------------------------------------------------------------------------

class TestResponseValuations:
    def test_simultaneous_antecedent_and_consequent(self):
        # G(a -> F b) with a and b in the SAME valuation: F is
        # reflexive-forward, so the obligation is discharged at the trigger
        # position itself — accepted.
        rule = compile_monitor_rule(MonitorRuleSpec("r", "req -> F ack"))
        violations, final = _eval_trace_final(rule, [
            {"tags": ["req", "ack"]},
        ])
        assert violations == [False]
        assert final is False

    def test_repeated_antecedents_all_discharged(self):
        # req@0 and req@1 are both answered by ack@2 — accepted.
        rule = compile_monitor_rule(MonitorRuleSpec("r", "req -> F ack"))
        violations, final = _eval_trace_final(rule, [
            {"tags": ["req"]},
            {"tags": ["req"]},
            {"tags": ["ack"]},
        ])
        assert violations == [False, False, False]
        assert final is False

    def test_repeated_antecedent_after_discharge_rejected(self):
        # req@0 is answered by ack@1, but req@2 has no later ack — rejected
        # at termination (liveness: no per-step bad prefix).
        rule = compile_monitor_rule(MonitorRuleSpec("r", "req -> F ack"))
        violations, final = _eval_trace_final(rule, [
            {"tags": ["req"]},
            {"tags": ["ack"]},
            {"tags": ["req"]},
        ])
        assert violations == [False, False, False]
        assert final is True


# ---------------------------------------------------------------------------
# Bad-prefix completeness: doomed (unsatisfiable-continuation) states flag on
# the earliest offending event, not only at finalize
# ---------------------------------------------------------------------------

class TestDoomedStateDetection:
    """violation_states is exactly the set of states from which no accepting
    state is reachable — the precise LTLf bad-prefix condition. Formerly only
    canonical FALSE was flagged mid-trace; unsatisfiable-but-not-FALSE states
    were reported only at finalize."""

    @pytest.mark.parametrize("first_event", [
        {"tags": ["taga"]},
        {"tags": ["tagb"]},
        {"tags": ["taga", "tagb"]},
        {},
    ])
    def test_unsatisfiable_conjunction_flags_on_first_event(self, first_event):
        # (a U b) AND (G !b) is unsatisfiable: the until demands b, the
        # invariant forbids it. The INITIAL state is doomed, so the very
        # first call to evaluate_monitors must report a violation whatever
        # the event is.
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "(taga U tagb) AND (G !tagb)")
        )
        violations = _eval_trace(rule, [first_event])
        assert violations == [True]

    def test_unsatisfiable_conjunction_final_verdict_unchanged(self):
        # Final-verdict semantics must not change: the trace is still
        # rejected at termination (and the empty trace is rejected too).
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "(taga U tagb) AND (G !tagb)")
        )
        violations, final = _eval_trace_final(rule, [{"tags": ["taga"]}])
        assert violations == [True]
        assert final is True
        snapshots, _ = finalize_monitors((rule,), {})
        assert snapshots[0].violation is True

    def test_response_conflicting_invariant_flags_at_first_a(self):
        # (a -> F b) AND (G !b): satisfiable while no a occurs, but the first
        # a creates an F b obligation that G !b makes unfulfillable — the
        # post-a state is doomed and must flag immediately (formerly only at
        # finalize).
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "(taga -> F tagb) AND (G !tagb)")
        )
        violations, final = _eval_trace_final(rule, [
            {},
            {"tags": ["taga"]},
            {},
        ])
        assert violations == [False, True, True]
        assert final is True

    def test_pure_cosafety_timing_unchanged(self):
        # 'a -> F[<=2] b' on a,-,-: positions 0..2 all lack b, so the bad
        # prefix is complete exactly at step index 2 — no earlier, no later.
        rule = compile_monitor_rule(
            MonitorRuleSpec("r", "decision:deploy -> F[<=2] action:approve")
        )
        violations = _eval_trace(rule, [
            {"decision": "deploy"},
            {},
            {},
        ])
        assert violations == [False, False, True]


# ---------------------------------------------------------------------------
# Event predicate hardening
# ---------------------------------------------------------------------------

class TestEventPredicateHardening:
    def test_string_tags_field_is_no_match(self):
        # tags must be an iterable of strings; a plain string is treated as
        # NO match (formerly set("xy...") iterated characters, so a
        # single-character atom matched any string containing it).
        rule = compile_monitor_rule(MonitorRuleSpec("r", "G !x"))
        violations = _eval_trace(rule, [
            {"tags": "x"},
            {"tags": "axb"},
        ])
        assert violations == [False, False]

    def test_list_tags_still_match(self):
        rule = compile_monitor_rule(MonitorRuleSpec("r", "G !x"))
        violations = _eval_trace(rule, [{"tags": ["x"]}])
        assert violations == [True]

    def test_non_string_tag_entries_ignored(self):
        rule = compile_monitor_rule(MonitorRuleSpec("r", "G !x"))
        violations = _eval_trace(rule, [{"tags": [None, 3, "x"]}])
        assert violations == [True]
        violations = _eval_trace(rule, [{"tags": [None, 3]}])
        assert violations == [False]

    @pytest.mark.parametrize("dsl", [
        "G !tool:",
        "G !action:",
        "G !decision:",
        "tool: -> F action:ok",
        "decision:go -> F[<=2] action:",
        "taga U decision:",
    ])
    def test_empty_prefixed_atom_rejected_at_compile_time(self, dsl):
        # 'G !tool:' used to compile into a rule matching every event without
        # a tool_name; degenerate prefixed atoms are now compile errors.
        with pytest.raises(MonitorCompileError, match="empty predicate name"):
            compile_monitor_rule(MonitorRuleSpec("r", dsl))


# ---------------------------------------------------------------------------
# Parser: AST desugaring, alias, and explicit errors
# ---------------------------------------------------------------------------

class TestParseDsl:
    def test_forbidden_desugars(self):
        assert parse_dsl("G !tool:x") == Globally(Not(Atom("tool:x")))

    def test_response_desugars(self):
        assert parse_dsl("a -> F b") == Globally(Or(Not(Atom("a")), Eventually(Atom("b"))))

    def test_bounded_response_desugars(self):
        assert parse_dsl("a -> F[<=3] b") == Globally(
            Or(Not(Atom("a")), BoundedEventually(Atom("b"), 3))
        )

    def test_response_chain_desugars_right_nested(self):
        assert parse_dsl("a -> F b -> F c") == Globally(
            Or(Not(Atom("a")), Eventually(And(Atom("b"), Eventually(Atom("c")))))
        )

    def test_until_desugars(self):
        assert parse_dsl("a U b") == Until(Atom("a"), Atom("b"))

    def test_nested_until_right(self):
        assert parse_dsl("a U (b U c)") == Until(Atom("a"), Until(Atom("b"), Atom("c")))

    def test_nested_until_left(self):
        assert parse_dsl("(a U b) U c") == Until(Until(Atom("a"), Atom("b")), Atom("c"))

    def test_conjunction_desugars(self):
        assert parse_dsl("(G !a) AND (G !b)") == And(
            Globally(Not(Atom("a"))), Globally(Not(Atom("b")))
        )

    def test_private_alias_kept(self):
        assert _parse_dsl is parse_dsl

    @pytest.mark.parametrize("bad", [
        "",
        "a",
        "a U",
        "(a U b) AND c",
        "a -> G b",
        "a -> F[<=x] b",
        "a -> F[<=2] b -> F c",
        "G a",
        "a AND b",
        "(a U b",
    ])
    def test_out_of_grammar_raises(self, bad):
        with pytest.raises(MonitorCompileError, match="unsupported"):
            parse_dsl(bad)


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


# ---------------------------------------------------------------------------
# Corpus + in-repo DSL surface: everything compiles, state spaces stay small
# ---------------------------------------------------------------------------

# Every DSL string used by scripts/ and examples/ (inventoried 2026-07).
_SCRIPT_AND_EXAMPLE_DSLS = [
    "G !tool:dangerous_tool",
    "decision:deploy -> F action:approve",
    "read_only U action:signoff",
    "decision:start -> F[<=5] action:complete",
    "(G !tool:drop_db) AND (G !tool:rm_rf)",
    "G !tool:send_email",
    "decision:proposed -> F action:human_review",
    "G !tool:execute_code",
    "action:fetch_raw -> F action:analyze",
    "G !tool:drop_database",
    "action:ingest -> F action:validate",
    "decision:deploy -> F action:human_approval",
    "decision:mitigate -> F action:human_approval",
    "G !tool:exfiltrate_data",
    "read_only U action:human_signoff",
    "G !tool:rm_rf",
    "G !tool:eval",
    "action:fetch -> F action:validate",
    "action:pii_detected -> F action:human_review",
    "G !tool:delete_account",
    "action:access_billing -> F action:human_review",
    "G !tool:delete",
]


class TestDslSurfaceCompiles:
    def test_corpus_policies_compile_with_small_state_spaces(self):
        policies = json.loads(_CORPUS_POLICIES.read_text())
        assert policies, "temporal policy corpus is empty"
        for policy in policies:
            rule = compile_monitor_rule(MonitorRuleSpec(
                rule_id=policy["id"],
                dsl=policy["dsl"],
                on_violation=policy.get("on_violation", "block"),
            ))
            num_states = len(rule.transition_table)
            assert num_states < 64, (
                f"policy {policy['id']!r} compiled to {num_states} states"
            )
            # Dense table: every state has a row over all 2^|predicates| symbols.
            for row in rule.transition_table.values():
                assert sorted(row) == list(range(2 ** len(rule.predicates)))

    def test_script_and_example_dsls_compile(self):
        for dsl in _SCRIPT_AND_EXAMPLE_DSLS:
            rule = compile_monitor_rule(MonitorRuleSpec("r", dsl))
            assert len(rule.transition_table) < 64
