"""Textbook LTLf reference oracle for differential testing of the compiled monitor.

This module implements finite-trace LTL (LTLf, De Giacomo & Vardi 2013) by
DIRECT STRUCTURAL RECURSION over the formula AST — deliberately simple and
slow, with no automata, no progression, no canonicalization. It exists so
that ``src/agentproof/monitor/ltl.py`` (which compiles formulas to DFAs via
formula progression) can be differentially tested against an independent
implementation of the same denotational semantics.

Trusted computing base
----------------------
The surface-syntax parser (:func:`agentproof.monitor.ltl.parse_dsl`) and the
formula AST dataclasses (``Atom``, ``Not``, ``And``, ``Or``, ``Globally``,
``Eventually``, ``Until``, ``BoundedEventually``) are SHARED with the
compiler and are therefore trusted, not tested, by this oracle: a parser bug
that mis-reads the DSL would affect both sides identically. Everything
downstream of the AST — the SEMANTICS — is independent: :func:`holds` below
imports nothing from the compiler beyond those AST classes and the parser,
and in particular never touches progression, canonicalization, ``_nu``, or
the compiled transition tables.

Trace model
-----------
A trace is a list/tuple of valuations. Each valuation is either a
``set``/``frozenset`` of the atom names true at that position, or a
``dict[str, bool]``. Atoms absent from a valuation are false.

Semantics (``holds(formula, trace, i)``)
----------------------------------------
For ``0 <= i < len(trace)``:

    Atom a                   a is true in trace[i]
    Not / And / Or           standard Boolean connectives
    Globally f               f holds at every j >= i
    Eventually f             f holds at some j >= i (REFLEXIVE: j = i counts)
    Until(l, r)              exists j >= i with r at j and l at all k in [i, j)
                             (STRONG until: r must actually occur)
    BoundedEventually(f, k)  exists j in [i, min(i + k, len(trace) - 1)]
                             with f at j (the triggering position counts,
                             then up to k further positions)

Empty-trace / end-of-trace convention (PROJECT CONVENTION)
----------------------------------------------------------
For the empty trace, and generally when ``i == len(trace)`` (the empty
remainder), the project fixes the following semantics, which every AgentProof
component must agree on:

    Atom                 false   (there is no position to inspect)
    Globally f           TRUE    (vacuous: universally quantified over nothing)
    Eventually f         false   (strong: a witness position must exist)
    Until(l, r)          false   (strong: r must actually occur)
    BoundedEventually    false   (strong, like Eventually)
    Not / And / Or       homomorphic (Not f = not f, etc.)

Consequently ``G !a`` and ``a -> F b`` (which desugars to
``G(!a OR F b)``) hold on the empty trace, while ``a U b`` does not. This is
exactly the ``nu`` (empty-remainder) valuation stated in the compiler's
module docstring; the oracle re-derives it independently from the recursion
above (every quantifier ranges over ``range(i, len(trace))``, which is empty).

Monitor harness
---------------
:func:`monitor_accepts` runs the COMPILED monitor end-to-end on the same
trace: compile via ``compile_monitor_rule``, feed one event per valuation
through ``evaluate_monitors`` (bare atoms are matched via the event's
``tags``), then ``finalize_monitors``. The trace is accepted iff no snapshot
reports a violation at any step and none at finalization.
"""

from __future__ import annotations

from typing import Mapping, Sequence, Union

from agentproof.monitor.ltl import (
    And,
    Atom,
    BoundedEventually,
    CompiledMonitorRule,
    Eventually,
    Formula,
    Globally,
    MonitorRuleSpec,
    Not,
    Or,
    Until,
    compile_monitor_rule,
    evaluate_monitors,
    finalize_monitors,
    parse_dsl,
)

Valuation = Union[Mapping[str, bool], frozenset, set]
Trace = Sequence[Valuation]


def _atom_true(valuation: Valuation, name: str) -> bool:
    """Is *name* true in *valuation*? Supports set-of-true-atoms and dict forms."""
    if isinstance(valuation, Mapping):
        return bool(valuation.get(name, False))
    return name in valuation


def _true_atoms(valuation: Valuation) -> list[str]:
    if isinstance(valuation, Mapping):
        return sorted(name for name, value in valuation.items() if value)
    return sorted(valuation)


# ---------------------------------------------------------------------------
# The oracle proper: textbook LTLf by structural recursion
# ---------------------------------------------------------------------------

def holds(formula: Formula, trace: Trace, i: int = 0) -> bool:
    """Does *formula* hold at position *i* of *trace* under textbook LTLf?

    ``i`` may equal ``len(trace)`` (the empty remainder); see the module
    docstring for the project's empty-trace convention, which falls out of
    the recursion because every temporal quantifier ranges over the empty
    ``range(i, len(trace))``.
    """
    n = len(trace)
    if isinstance(formula, Atom):
        return i < n and _atom_true(trace[i], formula.name)
    if isinstance(formula, Not):
        return not holds(formula.f, trace, i)
    if isinstance(formula, And):
        return holds(formula.left, trace, i) and holds(formula.right, trace, i)
    if isinstance(formula, Or):
        return holds(formula.left, trace, i) or holds(formula.right, trace, i)
    if isinstance(formula, Globally):
        return all(holds(formula.f, trace, j) for j in range(i, n))
    if isinstance(formula, Eventually):
        return any(holds(formula.f, trace, j) for j in range(i, n))
    if isinstance(formula, Until):
        return any(
            holds(formula.right, trace, j)
            and all(holds(formula.left, trace, k) for k in range(i, j))
            for j in range(i, n)
        )
    if isinstance(formula, BoundedEventually):
        # j in [i, min(i + k, n - 1)]; empty when i >= n, hence false.
        upper = min(i + formula.bound + 1, n)
        return any(holds(formula.f, trace, j) for j in range(i, upper))
    raise TypeError(
        f"oracle does not evaluate node {formula!r}; only the public AST "
        f"produced by parse_dsl is supported"
    )


def satisfies_dsl(dsl: str, trace: Trace) -> bool:
    """Parse *dsl* (shared, trusted parser) and evaluate it at position 0."""
    return holds(parse_dsl(dsl), trace, 0)


# ---------------------------------------------------------------------------
# Compiled-monitor harness (the implementation under test)
# ---------------------------------------------------------------------------

def compile_dsl(dsl: str) -> CompiledMonitorRule:
    """Compile *dsl* once; pass the result to monitor_accepts/monitor_run."""
    return compile_monitor_rule(
        MonitorRuleSpec(rule_id="oracle-harness", dsl=dsl, on_violation="block")
    )


def monitor_run(
    compiled: CompiledMonitorRule, trace: Trace
) -> tuple[bool, int | None]:
    """Run the compiled monitor over *trace*.

    Returns ``(accepted, violation_step)`` where ``violation_step`` is the
    0-based index of the event on which a mid-trace (bad-prefix) violation
    was first reported, or ``None`` if no mid-trace violation occurred.
    ``accepted`` is False exactly when a violation was reported mid-trace or
    by ``finalize_monitors`` at end of trace — so ``(False, None)`` means
    "rejected only because the trace ended with an unfulfilled obligation".
    """
    rules = (compiled,)
    state: Mapping[str, int] = {}
    for step, valuation in enumerate(trace):
        event = {"tags": _true_atoms(valuation)}
        state, snapshots, _decision = evaluate_monitors(rules, state, event)
        if any(snapshot.violation for snapshot in snapshots):
            # Violation states are absorbing FALSE: no extension can repair
            # the trace and finalize would flag it too. Stop here.
            return False, step
    snapshots, _decision = finalize_monitors(rules, state)
    if any(snapshot.violation for snapshot in snapshots):
        return False, None
    return True, None


def monitor_accepts(
    dsl: str, trace: Trace, *, compiled: CompiledMonitorRule | None = None
) -> bool:
    """Does the COMPILED monitor accept *trace* for *dsl*?

    Accepted iff no violation snapshot at any evaluate_monitors step and no
    violation at finalize_monitors. Pass ``compiled=compile_dsl(dsl)`` to
    amortize compilation over many traces.
    """
    if compiled is None:
        compiled = compile_dsl(dsl)
    accepted, _step = monitor_run(compiled, trace)
    return accepted
