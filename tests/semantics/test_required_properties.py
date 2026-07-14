"""Named required-property tests for the LTLf monitor (research plan 3.4A).

Each test pins one property the project's semantics must exhibit, with the
expected verdict DERIVED in a comment from the denotational semantics in the
``ltl.py`` module docstring (and re-checked against the independent oracle).
Every case is asserted against BOTH engines: the textbook oracle
(``satisfies_dsl``) and the compiled monitor (``monitor_accepts``), so a
failure localizes to "the semantics itself is wrong" rather than "the two
implementations merely disagree".

Trace notation in comments: a trace is written [v0, v1, ...] where each vi
lists the atoms true at position i (e.g. [a, -, b] means a@0, nothing@1, b@2).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/ on path

from oracles.ltlf_reference import (  # noqa: E402
    compile_dsl,
    monitor_accepts,
    monitor_run,
    satisfies_dsl,
)

EMPTY = frozenset()
A = frozenset({"a"})
B = frozenset({"b"})
C = frozenset({"c"})
AB = frozenset({"a", "b"})


def check(dsl: str, trace, expected: bool) -> None:
    """Assert BOTH engines deliver the expected verdict."""
    oracle = satisfies_dsl(dsl, trace)
    monitor = monitor_accepts(dsl, trace)
    assert oracle == expected, (
        f"oracle: {dsl!r} on {[sorted(v) for v in trace]!r} gave {oracle}, "
        f"expected {expected}"
    )
    assert monitor == expected, (
        f"compiled monitor: {dsl!r} on {[sorted(v) for v in trace]!r} gave "
        f"{monitor}, expected {expected}"
    )


def test_empty_trace_semantics() -> None:
    # Project convention (module docstring / oracle docstring): on the empty
    # trace, Globally is vacuously TRUE; Eventually, Until and
    # BoundedEventually are strongly FALSE; Not/And/Or homomorphic.
    check("G !a", [], True)              # G vacuous over no positions
    check("a -> F b", [], True)          # desugars to G(!a OR F b): vacuous G
    check("a -> F[<=2] b", [], True)     # G(!a OR F[<=2] b): vacuous G
    check("a U b", [], False)            # strong until: b must occur
    check("(a U b) U a", [], False)      # strong until at top level
    check("(G !a) OR (a U b)", [], True)   # left disjunct vacuously true
    check("(G !a) AND (a U b)", [], False)  # right conjunct strongly false


def test_repeated_antecedents() -> None:
    # "a -> F b" = G(!a OR F b): EVERY a-position needs a b at some j >= i.
    # [a, a, b]: a@0 -> b@2, a@1 -> b@2: both obligations discharged -> accept.
    check("a -> F b", [A, A, B], True)
    # [a, b, a]: a@0 -> b@1 ok, but a@2 has no b at j >= 2 -> reject
    # (unfulfilled obligation at termination, not a bad prefix).
    check("a -> F b", [A, B, A], False)
    # [a, b, a, b]: the repeated antecedent a@2 is discharged by b@3 -> accept.
    check("a -> F b", [A, B, A, B], True)


def test_simultaneous_antecedent_and_consequent() -> None:
    # Eventually is REFLEXIVE (j >= i includes j = i): an event where a and b
    # hold simultaneously discharges its own obligation.
    # [ab]: a@0 -> F b holds via b@0 itself -> accept.
    check("a -> F b", [AB], True)
    # [ab, a]: a@0 discharged at 0, but a@1 has no b at j >= 1 -> reject.
    check("a -> F b", [AB, A], False)
    # F[<=0] means "within the same event" — only simultaneity can satisfy it.
    # [ab]: b at j = i -> accept.  [a, b]: b at j = i+1 > i+0 -> reject.
    check("a -> F[<=0] b", [AB], True)
    check("a -> F[<=0] b", [A, B], False)


def test_obligation_fulfilled_vs_open_at_termination() -> None:
    # "a -> F b" on [a, b]: obligation discharged before the end -> accept.
    check("a -> F b", [A, B], True)
    # [a]: the trace simply ENDS (normal termination or abort — LTLf does not
    # distinguish: both are the trace ending) while F b is pending -> reject.
    check("a -> F b", [A], False)
    # The rejection must come from finalize (end of trace), NOT from a
    # mid-trace bad prefix: an extension [a, b] would have been fine, so no
    # event may be flagged as a violation while the trace is still running.
    accepted, step = monitor_run(compile_dsl("a -> F b"), [A])
    assert accepted is False and step is None
    # Contrast with a genuine bad prefix: "G !a" on [a] is unrepairable and
    # must be flagged ON the offending event (step 0), not at finalize.
    accepted, step = monitor_run(compile_dsl("G !a"), [A])
    assert accepted is False and step == 0


def test_conjunction_truth_table_at_trace_end() -> None:
    # "(G !a) AND (b U c)": left = no a anywhere; right = c occurs with b
    # holding until then. Verdict at end of trace = left AND right.
    check("(G !a) AND (b U c)", [B, C], True)    # T and T -> accept
    check("(G !a) AND (b U c)", [B, B], False)   # T and F (no c) -> reject
    check("(G !a) AND (b U c)", [frozenset({"a", "b"}), C], False)  # F and T
    check("(G !a) AND (b U c)", [A], False)      # F and F -> reject


def test_disjunction_truth_table_at_trace_end() -> None:
    # "(G !a) OR (b U c)": verdict at end of trace = left OR right.
    check("(G !a) OR (b U c)", [B, C], True)     # T or T -> accept
    check("(G !a) OR (b U c)", [B, B], True)     # T or F -> accept
    check("(G !a) OR (b U c)", [frozenset({"a", "b"}), C], True)  # F or T
    check("(G !a) OR (b U c)", [A], False)       # F or F -> reject


def test_bounded_response_boundary_at_k_and_k_plus_1() -> None:
    # "a -> F[<=k] b": b must occur at some j in [i, i+k]. With k = 2 and the
    # trigger at i = 0, positions 0, 1, 2 are allowed; position 3 is not.
    # [a, -, b]: b at j = i+2 = i+k, EXACTLY on the boundary -> accept.
    check("a -> F[<=2] b", [A, EMPTY, B], True)
    # [a, -, -, b]: b at j = i+3 = i+k+1, one past the boundary -> reject.
    check("a -> F[<=2] b", [A, EMPTY, EMPTY, B], False)
    # That rejection is a BAD PREFIX: after [a, -, -] the deadline has
    # already passed, so the monitor must flag step 2 (the third event),
    # before b even arrives — no extension can repair it.
    accepted, step = monitor_run(
        compile_dsl("a -> F[<=2] b"), [A, EMPTY, EMPTY, B]
    )
    assert accepted is False and step == 2
    # Same trace with k = 3: b at j = i+3 = i+k is back on the boundary.
    check("a -> F[<=3] b", [A, EMPTY, EMPTY, B], True)


def test_response_chain_overlap() -> None:
    # "a -> F b -> F c" = G(!a OR F(b AND F c)): every a needs a LATER b
    # (reflexively >= the a) that is itself followed by a c.
    # [a, b, a, c]: a@0 -> b@1, c@3: ok. a@2 -> needs b at j >= 2, but only
    # c@3 follows: no b -> reject.
    check("a -> F b -> F c", [A, B, A, C], False)
    # [a, b, a, b, c]: a@0 -> b@1, c@4; a@2 -> b@3, c@4: both chains (which
    # OVERLAP in the shared c@4) are discharged -> accept.
    check("a -> F b -> F c", [A, B, A, B, C], True)


def test_strong_until_termination() -> None:
    # "a U b" is STRONG until: b must actually occur, with a at every
    # position before it.
    # [a, a, a]: b never occurs -> reject at termination (obligation open,
    # not a bad prefix: appending b would have satisfied it).
    check("a U b", [A, A, A], False)
    accepted, step = monitor_run(compile_dsl("a U b"), [A, A, A])
    assert accepted is False and step is None
    # [a, a, b]: b@2 with a at 0, 1 -> accept.
    check("a U b", [A, A, B], True)
    # [b]: b immediately, "a until" vacuous over [0, 0) -> accept.
    check("a U b", [B], True)
    # [-, b]: at position 0 neither b (would need b@0) nor a (breaks the
    # until chain before b@1) holds -> reject; moreover this is a bad prefix
    # (no extension of [-] can put a or b at position 0) flagged at step 0.
    check("a U b", [EMPTY, B], False)
    accepted, step = monitor_run(compile_dsl("a U b"), [EMPTY, B])
    assert accepted is False and step == 0
