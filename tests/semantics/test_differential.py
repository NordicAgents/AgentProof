"""Exhaustive differential tests: compiled LTLf monitor vs textbook oracle.

For every formula in the batteries below, the DFA-compiled monitor
(``agentproof.monitor.ltl``) is compared against the independent
structural-recursion oracle (``tests/oracles/ltlf_reference.py``) on

  * ALL traces up to a length bound (exhaustive over the valuation alphabet:
    4 valuations for 2 atoms, 8 for 3 atoms), and
  * seeded random long traces for the 3-atom battery.

Zero mismatches are tolerated. A final test checks bad-prefix SOUNDNESS:
whenever the monitor reports a mid-trace violation at step t, the oracle
confirms that no extension of trace[:t+1] by up to 3 further steps satisfies
the formula (i.e. the monitor only cries "bad prefix" on genuinely
unrepairable prefixes).
"""

from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/ on path

from oracles.ltlf_reference import (  # noqa: E402
    compile_dsl,
    holds,
    monitor_run,
    parse_dsl,
)

# Valuation alphabets: every subset of the atom set, as frozensets.
VALS_2 = tuple(
    frozenset(v) for v in ((), ("a",), ("b",), ("a", "b"))
)
VALS_3 = tuple(
    frozenset(c)
    for r in range(4)
    for c in itertools.combinations(("a", "b", "c"), r)
)
assert len(VALS_2) == 4 and len(VALS_3) == 8


def all_traces(vals, max_len: int, min_len: int = 0):
    """Every trace (as a tuple of valuations) of length min_len..max_len."""
    for n in range(min_len, max_len + 1):
        yield from itertools.product(vals, repeat=n)


TWO_ATOM_FORMULAS = [
    "G !a",
    "a -> F b",
    "a U b",
    "a -> F[<=1] b",
    "a -> F[<=3] b",
    "(G !a) AND (a U b)",
    "(G !a) OR (a U b)",
    "(a -> F b) AND (G !b)",
    "(a U b) OR (G !b)",
    "(a U b) U a",
    "a U (b U a)",
]

THREE_ATOM_FORMULAS = [
    "a -> F b -> F c",
    "a U (b U c)",
    "(a U b) U c",
    "(a -> F b) AND (b -> F c)",
    "(G !a) OR (b U c)",
]


def _assert_agreement(dsl: str, traces) -> int:
    """Assert monitor_accepts == satisfies_dsl on every trace; return count."""
    compiled = compile_dsl(dsl)  # compile ONCE per battery entry
    formula = parse_dsl(dsl)
    mismatches: list[str] = []
    checked = 0
    for trace in traces:
        checked += 1
        expected = holds(formula, trace)
        got, _step = monitor_run(compiled, trace)
        if got != expected:
            mismatches.append(
                f"trace={[sorted(v) for v in trace]!r} "
                f"oracle={expected} monitor={got}"
            )
            if len(mismatches) >= 5:
                break
    assert not mismatches, (
        f"compiled monitor disagrees with textbook LTLf oracle on {dsl!r} "
        f"({len(mismatches)}+ mismatches shown):\n" + "\n".join(mismatches)
    )
    return checked


@pytest.mark.parametrize("dsl", TWO_ATOM_FORMULAS)
def test_two_atom_battery_exhaustive_len_0_to_6(dsl: str) -> None:
    # 4^0 + 4^1 + ... + 4^6 = 5461 traces per formula.
    checked = _assert_agreement(dsl, all_traces(VALS_2, 6))
    assert checked == 5461


@pytest.mark.parametrize("dsl", THREE_ATOM_FORMULAS)
def test_three_atom_battery_exhaustive_len_0_to_4(dsl: str) -> None:
    # 8^0 + 8^1 + ... + 8^4 = 4681 traces per formula.
    checked = _assert_agreement(dsl, all_traces(VALS_3, 4))
    assert checked == 4681


@pytest.mark.parametrize("dsl", THREE_ATOM_FORMULAS)
def test_three_atom_battery_random_long_traces(dsl: str) -> None:
    rng = random.Random(20260713)  # seeded: deterministic across runs
    traces = [
        tuple(rng.choice(VALS_3) for _ in range(rng.randint(5, 25)))
        for _ in range(500)
    ]
    checked = _assert_agreement(dsl, traces)
    assert checked == 500


# ---------------------------------------------------------------------------
# Bad-prefix soundness: a mid-trace violation must be unrepairable
# ---------------------------------------------------------------------------

_BAD_PREFIX_CASES = [(dsl, VALS_2, 5) for dsl in TWO_ATOM_FORMULAS] + [
    (dsl, VALS_3, 3) for dsl in THREE_ATOM_FORMULAS
]


@pytest.mark.parametrize("dsl,vals,max_len", _BAD_PREFIX_CASES)
def test_bad_prefix_soundness(dsl: str, vals, max_len: int) -> None:
    """If the monitor flags step t, no <=3-step extension of trace[:t+1]
    satisfies the formula according to the oracle."""
    compiled = compile_dsl(dsl)
    formula = parse_dsl(dsl)

    # Collect the (deduplicated) violating prefixes reported anywhere in the
    # exhaustive battery. monitor_run returns the FIRST violating step, so
    # trace[:step+1] is exactly the prefix on which the violation fired.
    bad_prefixes: set[tuple] = set()
    for trace in all_traces(vals, max_len):
        _accepted, step = monitor_run(compiled, trace)
        if step is not None:
            bad_prefixes.add(trace[: step + 1])

    extensions = list(all_traces(vals, 3))  # includes the empty extension
    for prefix in sorted(bad_prefixes, key=lambda p: (len(p), repr(p))):
        for ext in extensions:
            assert not holds(formula, prefix + ext), (
                f"monitor reported a bad prefix for {dsl!r} at "
                f"{[sorted(v) for v in prefix]!r}, but the oracle satisfies "
                f"the extension by {[sorted(v) for v in ext]!r} — the "
                f"'violation' was repairable"
            )


def test_bad_prefix_soundness_is_not_vacuous() -> None:
    """Sanity: at least one battery formula actually produces mid-trace
    violations (otherwise test_bad_prefix_soundness would pass trivially)."""
    compiled = compile_dsl("G !a")
    _accepted, step = monitor_run(compiled, (frozenset({"a"}),))
    assert step == 0
