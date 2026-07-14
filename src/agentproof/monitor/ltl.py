"""Temporal monitor compilation and runtime evaluation.

Semantics are LTLf (LTL over finite traces, De Giacomo & Vardi 2013): a
workflow execution is a finite event trace, each event inducing a valuation
of the rule's atomic predicates.

Surface grammar
---------------
Whitespace-insensitive. Atoms are maximal non-space, non-parenthesis tokens
(e.g. ``tool:draft_email``, ``action:approve``, ``decision:deploy``, or bare
tags); the reserved tokens ``G F U AND OR -> ! ( )`` and the bounded form
``F[<=k]`` are not atoms. ::

    expr     := "(" expr ")" "AND" "(" expr ")"      conjunction
              | "(" expr ")" "OR"  "(" expr ")"      disjunction
              | "(" expr ")" "U" uoperand            strong until
              | "G" "!" atom                         forbidden
              | atom "U" uoperand                    strong until
              | atom "->" "F[<=" INT "]" atom        bounded response
              | atom ("->" "F" atom)+                response / response chain
    uoperand := atom | "(" expr ")"

Anything outside this grammar raises :class:`MonitorCompileError` — nothing
is silently accepted. Each form desugars into the public formula AST
(:class:`Atom`, :class:`Not`, :class:`And`, :class:`Or`, :class:`Globally`,
:class:`Eventually`, :class:`Until`, :class:`BoundedEventually`)::

    G !a            => Globally(Not(a))
    a -> F b        => Globally(Or(Not(a), Eventually(b)))
    a -> F[<=k] b   => Globally(Or(Not(a), BoundedEventually(b, k)))
    a -> F b -> F c => Globally(Or(Not(a), Eventually(And(b, Eventually(c)))))
                       (right-nested for longer chains)
    x U y           => Until(x, y)
    (e) AND (e)     => And(e, e);  (e) OR (e) => Or(e, e)

Denotational semantics
----------------------
For a finite trace ``t`` of valuations and a position ``0 <= i < len(t)``:

    Atom a                   t[i][a] is true
    Not / And / Or           Boolean connectives
    Globally f               f holds at every j >= i
    Eventually f             f holds at some j >= i (reflexive)
    Until(l, r)              exists j >= i with r at j and l at all k in [i, j)
    BoundedEventually(f, k)  exists j in [i, i + k] with j < len(t) and f at j
                             (the triggering position counts, then up to k
                             further events)

A non-empty trace satisfies a formula iff the formula holds at position 0.
The EMPTY trace satisfies a formula iff ``nu(formula)`` is true, where nu is
the empty-remainder valuation: nu(TRUE) = true, nu(FALSE) = false,
nu(Atom) = false, nu(Not f) = not nu(f), nu(And)/nu(Or) homomorphic,
nu(Globally f) = true, nu(Eventually f) = nu(Until) =
nu(BoundedEventually) = false. In particular ``G !x`` and ``a -> F b`` hold
on the empty trace while ``a U b`` does not.

Compilation: formula progression
--------------------------------
Formulas compile to DFAs whose states ARE canonicalized formulas (the
"formula progression" construction). The transition function is::

    delta(phi, valuation) = progress(phi, valuation)

with progression rules::

    progress(Atom a)               = TRUE if valuation[a] else FALSE
    progress(Not/And/Or)           = homomorphic, with constant folding
    progress(Globally f)           = progress(f) AND Globally(f)
    progress(Eventually f)         = progress(f) OR Eventually(f)
    progress(Until(l, r))          = progress(r) OR (progress(l) AND Until(l, r))
    progress(BoundedEventually f,k)= progress(f) OR (BoundedEventually(f, k-1)
                                     if k > 0 else FALSE)

Every progression result is canonicalized (constants folded; And/Or
flattened into an irredundant disjunctive normal form over temporal
subformulas — deduplicated, domination-minimized, sorted, rebuilt
right-nested) so the reachable state set is finite and small. Minimization
includes semantic domination among same-operand deadline terms: within a
conjunction ``BE(f,i) AND BE(f,j) == BE(f,min(i,j))`` and
``BE(f,i) AND F(f) == BE(f,i)``; within a disjunction
``BE(f,i) OR BE(f,j) == BE(f,max(i,j))`` and ``BE(f,i) OR F(f) == F(f)``
(so ``a -> F[<=k] b`` compiles to O(k) states, not 2**k). States are
enumerated by BFS from the initial formula over all ``2**|predicates|``
valuations.

Acceptance and violation:

  * ``violation_states``: the DOOMED states — those from which no accepting
    state is reachable, i.e. the precise LTLf *bad prefix* condition: no
    extension of the trace can satisfy the formula. Canonical FALSE is
    trivially doomed; unsatisfiable-but-not-FALSE states (e.g.
    ``(a U b) AND (G !b)``) are doomed too. Doomedness is closed under
    transitions, so violation states are absorbing; ``evaluate_monitors``
    reports the violation on the earliest offending event.
  * ``accepting_states``: states S with nu(S) true — the trace may validly
    END there. A trace ending in a non-accepting state carries an
    *unfulfilled obligation at termination*; ``finalize_monitors`` reports
    it when the trace ends. Canonical TRUE is absorbing and accepting.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Any, Mapping


class MonitorCompileError(ValueError):
    """Raised when temporal rule DSL cannot be compiled."""


# ---------------------------------------------------------------------------
# Formula AST (public)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Atom:
    name: str


@dataclass(frozen=True)
class Not:
    f: Formula


@dataclass(frozen=True)
class And:
    left: Formula
    right: Formula


@dataclass(frozen=True)
class Or:
    left: Formula
    right: Formula


@dataclass(frozen=True)
class Globally:
    f: Formula


@dataclass(frozen=True)
class Eventually:
    f: Formula


@dataclass(frozen=True)
class Until:
    left: Formula
    right: Formula


@dataclass(frozen=True)
class BoundedEventually:
    f: Formula
    bound: int


@dataclass(frozen=True)
class _Constant:
    """Internal TRUE/FALSE, used as canonical absorbing DFA states."""

    value: bool


_TRUE = _Constant(True)
_FALSE = _Constant(False)

Formula = (
    Atom | Not | And | Or | Globally | Eventually | Until | BoundedEventually | _Constant
)


# ---------------------------------------------------------------------------
# Public data classes (frozen surface)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MonitorRuleSpec:
    rule_id: str
    dsl: str
    on_violation: str = "block"


@dataclass(frozen=True)
class CompiledMonitorRule:
    rule_id: str
    dsl: str
    on_violation: str
    predicates: tuple[str, ...]
    initial_state: int
    transition_table: Mapping[int, Mapping[int, int]]
    violation_states: frozenset[int]
    accepting_states: frozenset[int] = frozenset({0})


@dataclass(frozen=True)
class MonitorSnapshot:
    rule_id: str
    prior_state: int
    next_state: int
    violation: bool
    handling: str | None = None

    def to_trace_entry(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "rule_id": self.rule_id,
            "prior_state": self.prior_state,
            "next_state": self.next_state,
            "violation": self.violation,
        }
        if self.handling is not None:
            payload["handling"] = self.handling
        return payload


@dataclass(frozen=True)
class MonitorDecision:
    status: str
    denied: bool
    halt: bool
    escalate: bool


VIOLATION_LEVELS: frozenset[str] = frozenset({"warn", "block", "halt", "escalate"})


# ---------------------------------------------------------------------------
# Parser (recursive descent over the surface grammar)
# ---------------------------------------------------------------------------

_F_BOUND_RE = re.compile(r"F\[<=(\d+)\]")
_RESERVED_TOKENS = frozenset({"(", ")", "AND", "OR", "U", "G", "F", "->", "!"})


def _tokenize(dsl: str) -> list[str]:
    text = dsl.replace("(", " ( ").replace(")", " ) ").replace("->", " -> ")
    return text.split()


class _Parser:
    def __init__(self, dsl: str) -> None:
        self._dsl = " ".join(dsl.split())
        self._tokens = _tokenize(dsl)
        self._pos = 0

    # -- token plumbing ----------------------------------------------------

    def _error(self, detail: str) -> MonitorCompileError:
        return MonitorCompileError(
            f"unsupported temporal DSL expression: {self._dsl!r} ({detail})"
        )

    def _peek(self) -> str | None:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _next(self) -> str:
        token = self._peek()
        if token is None:
            raise self._error("unexpected end of input")
        self._pos += 1
        return token

    def _expect(self, expected: str) -> None:
        token = self._next()
        if token != expected:
            raise self._error(f"expected {expected!r}, found {token!r}")

    # -- grammar productions -------------------------------------------------

    def parse(self) -> Formula:
        formula = self._parse_expr()
        trailing = self._peek()
        if trailing is not None:
            raise self._error(f"unexpected trailing token {trailing!r}")
        return formula

    def _parse_expr(self) -> Formula:
        token = self._peek()
        if token is None:
            raise self._error("empty expression")
        if token == "(":
            left = self._parse_paren()
            operator = self._peek()
            if operator in ("AND", "OR"):
                self._next()
                if self._peek() != "(":
                    raise self._error(
                        f"right operand of {operator} must be parenthesized"
                    )
                right = self._parse_paren()
                return And(left, right) if operator == "AND" else Or(left, right)
            if operator == "U":
                self._next()
                return Until(left, self._parse_until_operand())
            raise self._error(
                "expected AND, OR, or U after parenthesized sub-expression"
            )
        if token == "G":
            self._next()
            return Globally(Not(Atom(self._parse_negated_atom())))
        atom = self._parse_atom("a temporal operator applied to the atom")
        operator = self._peek()
        if operator == "U":
            self._next()
            return Until(Atom(atom), self._parse_until_operand())
        if operator == "->":
            return self._parse_response(atom)
        if operator is None:
            raise self._error("a bare atom is not a supported temporal formula")
        raise self._error(f"unexpected token {operator!r} after atom {atom!r}")

    def _parse_paren(self) -> Formula:
        self._expect("(")
        inner = self._parse_expr()
        self._expect(")")
        return inner

    def _parse_until_operand(self) -> Formula:
        if self._peek() == "(":
            return self._parse_paren()
        return Atom(self._parse_atom("right operand of U"))

    def _parse_negated_atom(self) -> str:
        token = self._next()
        if token == "!":
            return self._parse_atom("atom after 'G !'")
        if token.startswith("!") and len(token) > 1:
            return self._validate_atom(token[1:], "atom after 'G !'")
        raise self._error("G is only supported in the form 'G !atom'")

    def _parse_response(self, antecedent: str) -> Formula:
        self._expect("->")
        token = self._next()
        bound_match = _F_BOUND_RE.fullmatch(token)
        if bound_match:
            consequent = self._parse_atom("consequent of bounded response")
            if self._peek() == "->":
                raise self._error("bounded response 'a -> F[<=k] b' cannot be chained")
            return Globally(
                Or(
                    Not(Atom(antecedent)),
                    BoundedEventually(Atom(consequent), int(bound_match.group(1))),
                )
            )
        if token != "F":
            raise self._error("expected 'F' or 'F[<=k]' after '->'")
        steps = [self._parse_atom("consequent of response")]
        while self._peek() == "->":
            self._next()
            marker = self._next()
            if marker != "F":
                raise self._error("response chain steps must use unbounded 'F'")
            steps.append(self._parse_atom("response chain step"))
        # Right-nested: a -> F b -> F c => G(!a OR F(b AND F c))
        consequent_formula: Formula = Eventually(Atom(steps[-1]))
        for step in reversed(steps[:-1]):
            consequent_formula = Eventually(And(Atom(step), consequent_formula))
        return Globally(Or(Not(Atom(antecedent)), consequent_formula))

    def _parse_atom(self, context: str) -> str:
        return self._validate_atom(self._next(), context)

    def _validate_atom(self, token: str, context: str) -> str:
        if (
            token in _RESERVED_TOKENS
            or _F_BOUND_RE.fullmatch(token)
            or token.startswith("!")
        ):
            raise self._error(f"expected an atom as {context}, found {token!r}")
        if token in ("tool:", "action:", "decision:"):
            # A bare prefix would compile into a match-everything (or
            # match-nothing) predicate; reject it at compile time.
            raise self._error(f"empty predicate name in atom {token!r}")
        return token


def parse_dsl(dsl: str) -> Formula:
    """Parse a monitor DSL string into a formula AST.

    Raises :class:`MonitorCompileError` on anything outside the surface
    grammar documented in the module docstring.
    """
    if not dsl or not dsl.strip():
        raise MonitorCompileError(
            "unsupported temporal DSL expression: '' (empty rule)"
        )
    return _Parser(dsl).parse()


# Backward-compatible alias for the pre-rewrite private entry point.
_parse_dsl = parse_dsl


# ---------------------------------------------------------------------------
# Formula progression, canonicalization, and empty-remainder valuation
# ---------------------------------------------------------------------------

def _not1(f: Formula) -> Formula:
    if isinstance(f, _Constant):
        return _FALSE if f.value else _TRUE
    if isinstance(f, Not):
        return f.f
    return Not(f)


def _and2(left: Formula, right: Formula) -> Formula:
    if isinstance(left, _Constant):
        return right if left.value else _FALSE
    if isinstance(right, _Constant):
        return left if right.value else _FALSE
    return And(left, right)


def _or2(left: Formula, right: Formula) -> Formula:
    if isinstance(left, _Constant):
        return _TRUE if left.value else right
    if isinstance(right, _Constant):
        return _TRUE if right.value else left
    return Or(left, right)


def _progress(formula: Formula, valuation: Mapping[str, bool]) -> Formula:
    """One-step LTLf progression of *formula* under *valuation* (folded, raw)."""
    if isinstance(formula, _Constant):
        return formula
    if isinstance(formula, Atom):
        return _TRUE if valuation.get(formula.name, False) else _FALSE
    if isinstance(formula, Not):
        return _not1(_progress(formula.f, valuation))
    if isinstance(formula, And):
        return _and2(_progress(formula.left, valuation), _progress(formula.right, valuation))
    if isinstance(formula, Or):
        return _or2(_progress(formula.left, valuation), _progress(formula.right, valuation))
    if isinstance(formula, Globally):
        return _and2(_progress(formula.f, valuation), formula)
    if isinstance(formula, Eventually):
        return _or2(_progress(formula.f, valuation), formula)
    if isinstance(formula, Until):
        return _or2(
            _progress(formula.right, valuation),
            _and2(_progress(formula.left, valuation), formula),
        )
    if isinstance(formula, BoundedEventually):
        remainder: Formula = (
            BoundedEventually(formula.f, formula.bound - 1)
            if formula.bound > 0
            else _FALSE
        )
        return _or2(_progress(formula.f, valuation), remainder)
    raise MonitorCompileError(f"unknown formula node: {formula!r}")


@lru_cache(maxsize=None)
def _key(formula: Formula) -> tuple:
    """Total structural order on formulas, for canonical sorting."""
    if isinstance(formula, _Constant):
        return (0, formula.value)
    if isinstance(formula, Atom):
        return (1, formula.name)
    if isinstance(formula, Not):
        return (2, _key(formula.f))
    if isinstance(formula, And):
        return (3, _key(formula.left), _key(formula.right))
    if isinstance(formula, Or):
        return (4, _key(formula.left), _key(formula.right))
    if isinstance(formula, Globally):
        return (5, _key(formula.f))
    if isinstance(formula, Eventually):
        return (6, _key(formula.f))
    if isinstance(formula, Until):
        return (7, _key(formula.left), _key(formula.right))
    if isinstance(formula, BoundedEventually):
        return (8, formula.bound, _key(formula.f))
    raise MonitorCompileError(f"unknown formula node: {formula!r}")


def _implies(strong: Formula, weak: Formula) -> bool:
    """Sound (not complete) syntactic implication between base terms.

    Used for semantic domination during canonicalization. Covers exactly:

      * ``t => t`` (structural equality),
      * ``BE(f, i) => BE(g, j)`` when ``i <= j`` and f, g are canonically
        equal (a tighter deadline implies a looser one),
      * ``BE(f, i) => Eventually(g)`` when f, g are canonically equal.
    """
    if strong == weak:
        return True
    if isinstance(strong, BoundedEventually):
        if isinstance(weak, BoundedEventually):
            return strong.bound <= weak.bound and _canon(strong.f) == _canon(weak.f)
        if isinstance(weak, Eventually):
            return _canon(strong.f) == _canon(weak.f)
    return False


def _normalize_conjunct(terms: frozenset[Formula]) -> frozenset[Formula]:
    """Semantic domination within a conjunction: keep only strongest terms.

    Same-operand grouping (operands compared canonically via ``_implies``):
    ``BE(f, i) AND BE(f, j) == BE(f, min(i, j))`` and
    ``BE(f, i) AND Eventually(f) == BE(f, i)``.
    """
    kept: list[Formula] = []
    for term in sorted(terms, key=_key):
        if any(_implies(existing, term) for existing in kept):
            continue  # an already-kept stronger term makes this one redundant
        kept = [existing for existing in kept if not _implies(term, existing)]
        kept.append(term)
    return frozenset(kept)


def _dnf(formula: Formula) -> frozenset[frozenset[Formula]]:
    """Positive DNF over temporal base terms: a set of conjunct-sets.

    FALSE is the empty set; TRUE is {frozenset()} (one empty conjunct).
    """
    if isinstance(formula, _Constant):
        return frozenset({frozenset()}) if formula.value else frozenset()
    if isinstance(formula, Or):
        return _minimize(_dnf(formula.left) | _dnf(formula.right))
    if isinstance(formula, And):
        left = _dnf(formula.left)
        right = _dnf(formula.right)
        return _minimize(
            frozenset(_normalize_conjunct(a | b) for a in left for b in right)
        )
    # Base term: Atom, Not, Globally, Eventually, Until, BoundedEventually.
    return frozenset({frozenset({formula})})


def _minimize(
    disjuncts: frozenset[frozenset[Formula]],
) -> frozenset[frozenset[Formula]]:
    """Drop dominated disjuncts (generalized absorption via ``_implies``).

    Disjunct *d* is dominated by disjunct *e* when every term of *e* is
    implied by some term of *d* (so d => e and ``d OR e == e``). Subset
    absorption is the ``t => t`` special case; the ``_implies`` extension
    additionally yields, within a disjunction with same-operand grouping,
    ``BE(f, i) OR BE(f, j) == BE(f, max(i, j))`` and
    ``BE(f, i) OR Eventually(f) == Eventually(f)``.
    """

    def dominated(d: frozenset[Formula], e: frozenset[Formula]) -> bool:
        return all(any(_implies(t, u) for t in d) for u in e)

    kept: list[frozenset[Formula]] = []
    for d in sorted(disjuncts, key=lambda c: tuple(sorted(_key(t) for t in c))):
        if any(dominated(d, e) for e in kept):
            continue
        kept = [e for e in kept if not dominated(e, d)]
        kept.append(d)
    return frozenset(kept)


@lru_cache(maxsize=None)
def _canon(formula: Formula) -> Formula:
    """Canonical form: irredundant sorted DNF, rebuilt right-nested.

    Two progression results denoting the same monotone Boolean combination
    of temporal subformulas canonicalize to the identical formula object
    graph, which keeps the reachable DFA state set finite and small.
    """
    disjuncts = _dnf(formula)
    if not disjuncts:
        return _FALSE
    if frozenset() in disjuncts:
        return _TRUE
    conjunctions: list[Formula] = []
    for conjunct_set in sorted(
        disjuncts, key=lambda d: tuple(sorted(_key(t) for t in d))
    ):
        terms = sorted(conjunct_set, key=_key)
        conjunction: Formula = terms[-1]
        for term in reversed(terms[:-1]):
            conjunction = And(term, conjunction)
        conjunctions.append(conjunction)
    result: Formula = conjunctions[-1]
    for part in reversed(conjunctions[:-1]):
        result = Or(part, result)
    return result


@lru_cache(maxsize=None)
def _nu(formula: Formula) -> bool:
    """Empty-remainder valuation: may a finite trace validly END here?"""
    if isinstance(formula, _Constant):
        return formula.value
    if isinstance(formula, Atom):
        return False
    if isinstance(formula, Not):
        return not _nu(formula.f)
    if isinstance(formula, And):
        return _nu(formula.left) and _nu(formula.right)
    if isinstance(formula, Or):
        return _nu(formula.left) or _nu(formula.right)
    if isinstance(formula, Globally):
        return True
    if isinstance(formula, (Eventually, Until, BoundedEventually)):
        return False
    raise MonitorCompileError(f"unknown formula node: {formula!r}")


def _collect_atoms(formula: Formula) -> set[str]:
    if isinstance(formula, _Constant):
        return set()
    if isinstance(formula, Atom):
        return {formula.name}
    if isinstance(formula, (Not, Globally, Eventually, BoundedEventually)):
        return _collect_atoms(formula.f)
    if isinstance(formula, (And, Or, Until)):
        return _collect_atoms(formula.left) | _collect_atoms(formula.right)
    raise MonitorCompileError(f"unknown formula node: {formula!r}")


# ---------------------------------------------------------------------------
# Formula -> DFA compilation (BFS over canonical progressions)
# ---------------------------------------------------------------------------

_MAX_MONITOR_STATES = 4096


def compile_monitor_rule(rule: MonitorRuleSpec) -> CompiledMonitorRule:
    level = rule.on_violation.strip().lower()
    if level not in VIOLATION_LEVELS:
        raise MonitorCompileError(f"invalid violation handling level: {rule.on_violation}")

    formula = parse_dsl(rule.dsl)
    predicates = tuple(sorted(_collect_atoms(formula)))
    num_symbols = 2 ** len(predicates)

    initial = _canon(formula)
    state_ids: dict[Formula, int] = {initial: 0}
    order: list[Formula] = [initial]
    table: dict[int, dict[int, int]] = {}

    index = 0
    while index < len(order):
        phi = order[index]
        row: dict[int, int] = {}
        for symbol in range(num_symbols):
            valuation = _symbol_to_valuation(predicates, symbol)
            successor = _canon(_progress(phi, valuation))
            successor_id = state_ids.get(successor)
            if successor_id is None:
                successor_id = len(order)
                if successor_id >= _MAX_MONITOR_STATES:
                    raise MonitorCompileError(
                        f"rule {rule.rule_id!r} exceeds {_MAX_MONITOR_STATES} "
                        f"monitor states; refusing to compile {rule.dsl!r}"
                    )
                state_ids[successor] = successor_id
                order.append(successor)
            row[symbol] = successor_id
        table[state_ids[phi]] = row
        index += 1

    accepting_states = frozenset(sid for phi, sid in state_ids.items() if _nu(phi))

    # Bad-prefix completeness: a state is DOOMED iff no accepting state is
    # reachable from it (in zero or more steps) — the precise LTLf bad-prefix
    # condition. Canonical FALSE is trivially doomed; unsatisfiable-but-not-
    # FALSE states (e.g. 'Until(a,b) AND G(!b)') are doomed too and now flag
    # on the earliest offending event instead of only at finalize. Computed
    # by reverse BFS from the accepting states over the transition relation.
    predecessors: dict[int, set[int]] = {sid: set() for sid in table}
    for source, row in table.items():
        for successor in row.values():
            predecessors[successor].add(source)
    live: set[int] = set(accepting_states)
    frontier: list[int] = list(accepting_states)
    while frontier:
        node = frontier.pop()
        for predecessor in predecessors[node]:
            if predecessor not in live:
                live.add(predecessor)
                frontier.append(predecessor)
    violation_states = frozenset(set(table) - live)
    # Doomedness is closed under transitions, so violation states are
    # absorbing in behavior without mutating the table.
    assert all(
        successor in violation_states
        for doomed in violation_states
        for successor in table[doomed].values()
    ), f"doomed states not closed under transitions in rule {rule.rule_id!r}"

    return CompiledMonitorRule(
        rule_id=rule.rule_id,
        dsl=" ".join(rule.dsl.split()),
        on_violation=level,
        predicates=predicates,
        initial_state=0,
        transition_table=table,
        violation_states=violation_states,
        accepting_states=accepting_states,
    )


# ---------------------------------------------------------------------------
# Runtime evaluation (walks the compiled table; unchanged semantics)
# ---------------------------------------------------------------------------

def finalize_monitors(
    compiled_rules: tuple[CompiledMonitorRule, ...],
    prior_state: Mapping[str, int],
) -> tuple[list[MonitorSnapshot], MonitorDecision]:
    """LTLf end-of-trace check: flag rules with unfulfilled obligations.

    Must be called when the event trace ends (the workflow terminates). A
    rule whose current DFA state is not accepting — e.g. a pending
    ``a -> F b`` obligation or an ``a U b`` where *b* never occurred — is a
    violation of the property on the finite trace, even though no single
    event was a bad prefix.
    """
    snapshots: list[MonitorSnapshot] = []
    level_counts = {"warn": 0, "block": 0, "halt": 0, "escalate": 0}
    for rule in compiled_rules:
        current = int(prior_state.get(rule.rule_id, rule.initial_state))
        violation = current not in rule.accepting_states
        handling: str | None = None
        if violation:
            handling = rule.on_violation
            level_counts[rule.on_violation] += 1
        snapshots.append(MonitorSnapshot(
            rule_id=rule.rule_id, prior_state=current, next_state=current,
            violation=violation, handling=handling))
    return snapshots, map_violation_levels(level_counts)


def evaluate_monitors(
    compiled_rules: tuple[CompiledMonitorRule, ...],
    prior_state: Mapping[str, int],
    event: Mapping[str, Any],
) -> tuple[dict[str, int], list[MonitorSnapshot], MonitorDecision]:
    next_state: dict[str, int] = dict(prior_state)
    snapshots: list[MonitorSnapshot] = []
    level_counts = {"warn": 0, "block": 0, "halt": 0, "escalate": 0}

    for rule in compiled_rules:
        previous = int(next_state.get(rule.rule_id, rule.initial_state))
        symbol = _event_symbol(rule.predicates, event)
        table = rule.transition_table.get(previous)
        if table is None:
            raise MonitorCompileError(f"missing transition row for state {previous} in rule {rule.rule_id}")
        upcoming = table[symbol]
        violation = upcoming in rule.violation_states
        handling: str | None = None
        if violation:
            handling = rule.on_violation
            level_counts[rule.on_violation] += 1
        next_state[rule.rule_id] = upcoming
        snapshots.append(MonitorSnapshot(rule_id=rule.rule_id, prior_state=previous, next_state=upcoming, violation=violation, handling=handling))

    decision = map_violation_levels(level_counts)
    return next_state, snapshots, decision


def map_violation_levels(level_counts: Mapping[str, int]) -> MonitorDecision:
    warn_count = int(level_counts.get("warn", 0))
    block_count = int(level_counts.get("block", 0))
    halt_count = int(level_counts.get("halt", 0))
    escalate_count = int(level_counts.get("escalate", 0))

    if escalate_count > 0:
        return MonitorDecision(status="halted", denied=True, halt=True, escalate=True)
    if halt_count > 0:
        return MonitorDecision(status="halted", denied=True, halt=True, escalate=False)
    if block_count > 0:
        return MonitorDecision(status="ready", denied=True, halt=False, escalate=False)
    if warn_count > 0:
        return MonitorDecision(status="ready", denied=False, halt=False, escalate=False)
    return MonitorDecision(status="ready", denied=False, halt=False, escalate=False)


# ---------------------------------------------------------------------------
# Event valuation helpers
# ---------------------------------------------------------------------------

def _symbol_to_valuation(predicates: tuple[str, ...], symbol: int) -> dict[str, bool]:
    valuation: dict[str, bool] = {}
    for index, predicate in enumerate(predicates):
        valuation[predicate] = bool(symbol & (1 << index))
    return valuation


def _event_symbol(predicates: tuple[str, ...], event: Mapping[str, Any]) -> int:
    symbol = 0
    for index, predicate in enumerate(predicates):
        if _event_matches_predicate(predicate, event):
            symbol |= 1 << index
    return symbol


def _event_matches_predicate(predicate: str, event: Mapping[str, Any]) -> bool:
    if predicate.startswith("tool:"):
        return str(event.get("tool_name", "")) == predicate[5:]
    if predicate.startswith("action:"):
        return str(event.get("action_type", "")) == predicate[7:]
    if predicate.startswith("decision:"):
        return str(event.get("decision", "")) == predicate[9:]
    tags = event.get("tags", [])
    if isinstance(tags, (str, bytes)):
        # A plain string is not an iterable of tag strings; refusing to match
        # (rather than iterating its characters) keeps single-character atoms
        # from matching substrings of a malformed tags field.
        return False
    try:
        return any(isinstance(tag, str) and tag == predicate for tag in tags)
    except TypeError:
        return False  # non-iterable tags field: no match
