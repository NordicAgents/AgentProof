"""Temporal monitor compilation and runtime evaluation.

Supported DSL patterns:
  - G !atom                          (Forbidden)
  - antecedent -> F consequent       (Implication-future)
  - left U right                     (Until)
  - (expr) AND (expr)                (Conjunction — product DFA)
  - (expr) OR (expr)                 (Disjunction — product DFA)
  - antecedent -> F[<=k] consequent  (Bounded response)
  - a -> F b -> F c                  (Response chain)
  - a U (b U c)                      (Nested until)
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


class MonitorCompileError(ValueError):
    """Raised when temporal rule DSL cannot be compiled."""


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Forbidden:
    atom: str

@dataclass(frozen=True)
class _ImplFuture:
    antecedent: str
    consequent: str

@dataclass(frozen=True)
class _Until:
    left: str
    right: str

@dataclass(frozen=True)
class _Conjunction:
    left: _ASTNode
    right: _ASTNode

@dataclass(frozen=True)
class _Disjunction:
    left: _ASTNode
    right: _ASTNode

@dataclass(frozen=True)
class _BoundedResponse:
    antecedent: str
    consequent: str
    bound: int

@dataclass(frozen=True)
class _ResponseChain:
    steps: tuple[str, ...]  # a -> F b -> F c  =>  ("a", "b", "c")

# Type alias for AST nodes
_ASTNode = _Forbidden | _ImplFuture | _Until | _Conjunction | _Disjunction | _BoundedResponse | _ResponseChain

# ---------------------------------------------------------------------------
# Internal DFA representation used during compilation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _DFA:
    predicates: tuple[str, ...]
    num_states: int
    initial_state: int
    transition_table: dict[int, dict[int, int]]
    violation_states: frozenset[int]


# ---------------------------------------------------------------------------
# Public data classes
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
# Parser
# ---------------------------------------------------------------------------

def _parse_dsl(dsl: str) -> _ASTNode:
    """Parse a DSL string into an AST node."""
    dsl = " ".join(dsl.split())

    # Conjunction: (expr) AND (expr)
    conj = _try_split_binary(dsl, "AND")
    if conj is not None:
        return _Conjunction(_parse_dsl(conj[0]), _parse_dsl(conj[1]))

    # Disjunction: (expr) OR (expr)
    disj = _try_split_binary(dsl, "OR")
    if disj is not None:
        return _Disjunction(_parse_dsl(disj[0]), _parse_dsl(disj[1]))

    # Forbidden: G !atom
    m = re.fullmatch(r"G\s+!\s*([^\s]+)", dsl)
    if m:
        return _Forbidden(m.group(1))

    # Bounded response: a -> F[<=k] b
    m = re.fullmatch(r"([^\s]+)\s*->\s*F\[<=(\d+)\]\s+([^\s]+)", dsl)
    if m:
        return _BoundedResponse(m.group(1), m.group(3), int(m.group(2)))

    # Response chain: a -> F b -> F c (-> F d ...)
    chain_match = re.fullmatch(r"([^\s]+)(\s*->\s*F\s+[^\s]+){2,}", dsl)
    if chain_match:
        parts = re.split(r"\s*->\s*F\s+", dsl)
        return _ResponseChain(tuple(parts))

    # Implication-future: a -> F b
    m = re.fullmatch(r"([^\s]+)\s*->\s*F\s+([^\s]+)", dsl)
    if m:
        return _ImplFuture(m.group(1), m.group(2))

    # Nested until: a U (b U c)
    m = re.fullmatch(r"([^\s]+)\s+U\s+\((.+)\)", dsl)
    if m:
        inner = _parse_dsl(m.group(2))
        if isinstance(inner, _Until):
            # Flatten: a U (b U c) — compiled as nested until
            return _Until(m.group(1), f"({m.group(2)})")
        # Treat as regular until with parenthesized right
        return _Until(m.group(1), m.group(2).strip())

    # Until: a U b
    m = re.fullmatch(r"([^\s]+)\s+U\s+([^\s]+)", dsl)
    if m:
        return _Until(m.group(1), m.group(2))

    raise MonitorCompileError(f"unsupported temporal DSL expression: {dsl}")


def _try_split_binary(dsl: str, operator: str) -> tuple[str, str] | None:
    """Try to split DSL at a top-level binary operator between parenthesized sub-expressions."""
    # Pattern: (expr) OP (expr)
    m = re.fullmatch(r"\((.+)\)\s+" + operator + r"\s+\((.+)\)", dsl)
    if m:
        return (m.group(1), m.group(2))
    return None


# ---------------------------------------------------------------------------
# AST -> DFA compilation
# ---------------------------------------------------------------------------

def _collect_predicates(ast: _ASTNode) -> set[str]:
    """Collect all atomic predicates from an AST."""
    if isinstance(ast, _Forbidden):
        return {ast.atom}
    if isinstance(ast, _ImplFuture):
        return {ast.antecedent, ast.consequent}
    if isinstance(ast, _Until):
        return {ast.left, ast.right}
    if isinstance(ast, _BoundedResponse):
        return {ast.antecedent, ast.consequent}
    if isinstance(ast, _ResponseChain):
        return set(ast.steps)
    if isinstance(ast, (_Conjunction, _Disjunction)):
        return _collect_predicates(ast.left) | _collect_predicates(ast.right)
    raise MonitorCompileError(f"unknown AST node: {ast}")


def _compile_ast(ast: _ASTNode) -> _DFA:
    """Compile an AST node into an internal DFA."""
    if isinstance(ast, _Forbidden):
        return _compile_forbidden(ast)
    if isinstance(ast, _ImplFuture):
        return _compile_impl_future(ast)
    if isinstance(ast, _Until):
        return _compile_until(ast)
    if isinstance(ast, _BoundedResponse):
        return _compile_bounded_response(ast)
    if isinstance(ast, _ResponseChain):
        return _compile_response_chain(ast)
    if isinstance(ast, _Conjunction):
        return _compile_product(ast.left, ast.right, conj=True)
    if isinstance(ast, _Disjunction):
        return _compile_product(ast.left, ast.right, conj=False)
    raise MonitorCompileError(f"unknown AST node: {ast}")


def _compile_forbidden(ast: _Forbidden) -> _DFA:
    predicates = (ast.atom,)
    table = _build_transition_table(predicates, 2, _forbidden_transition(ast.atom))
    return _DFA(predicates=predicates, num_states=2, initial_state=0,
                transition_table=table, violation_states=frozenset({1}))


def _compile_impl_future(ast: _ImplFuture) -> _DFA:
    predicates = tuple(sorted({ast.antecedent, ast.consequent}))
    table = _build_transition_table(predicates, 3, _implication_future_transition(ast.antecedent, ast.consequent))
    return _DFA(predicates=predicates, num_states=3, initial_state=0,
                transition_table=table, violation_states=frozenset({2}))


def _compile_until(ast: _Until) -> _DFA:
    predicates = tuple(sorted({ast.left, ast.right}))
    table = _build_transition_table(predicates, 3, _until_transition(ast.left, ast.right))
    return _DFA(predicates=predicates, num_states=3, initial_state=0,
                transition_table=table, violation_states=frozenset({2}))


def _compile_bounded_response(ast: _BoundedResponse) -> _DFA:
    """Compile a -> F[<=k] b into a counter-augmented DFA.

    States: 0=idle, 1..k=counting, k+1=violation.
    """
    k = ast.bound
    num_states = k + 2  # 0, 1, ..., k, k+1
    predicates = tuple(sorted({ast.antecedent, ast.consequent}))
    violation_state = k + 1

    def transition(state: int, valuation: Mapping[str, bool]) -> int:
        a = valuation.get(ast.antecedent, False)
        b = valuation.get(ast.consequent, False)
        if state == violation_state:
            return violation_state
        if state == 0:
            if a and not b:
                return 1
            return 0
        # In counting states 1..k
        if b:
            return 0
        if state >= k:
            return violation_state
        return state + 1

    table = _build_transition_table(predicates, num_states, transition)
    return _DFA(predicates=predicates, num_states=num_states, initial_state=0,
                transition_table=table, violation_states=frozenset({violation_state}))


def _compile_response_chain(ast: _ResponseChain) -> _DFA:
    """Compile a -> F b -> F c into a sequential chain DFA.

    For chain (a, b, c) with n=3 steps:
      State 0: idle (waiting for a)
      State 1: saw a, waiting for b
      State 2: saw b, waiting for c
      State n: violation (a repeated before chain completed)
    When we see the last step in state n-1, we reset to 0.
    """
    steps = ast.steps
    n = len(steps)
    predicates = tuple(sorted(set(steps)))
    num_states = n + 1  # 0..n-1 for chain positions, n for violation
    violation_state = n

    def transition(state: int, valuation: Mapping[str, bool]) -> int:
        if state == violation_state:
            return violation_state
        if state == 0:
            if valuation.get(steps[0], False):
                return 1
            return 0
        # In waiting state: state i means we've seen steps[0..i-1], waiting for steps[i]
        expected = steps[state]
        if valuation.get(expected, False):
            if state + 1 >= n:
                return 0  # Chain completed, reset
            return state + 1
        # Check if first step recurs before chain completes
        if valuation.get(steps[0], False):
            return violation_state
        return state

    table = _build_transition_table(predicates, num_states, transition)
    return _DFA(predicates=predicates, num_states=num_states, initial_state=0,
                transition_table=table, violation_states=frozenset({violation_state}))


def _compile_product(left_ast: _ASTNode, right_ast: _ASTNode, *, conj: bool) -> _DFA:
    """Build product DFA for conjunction (AND) or disjunction (OR).

    For AND: violation if either sub-DFA is in a violation state.
    For OR: violation if both sub-DFAs are in violation states.
    """
    left_dfa = _compile_ast(left_ast)
    right_dfa = _compile_ast(right_ast)

    all_preds = tuple(sorted(set(left_dfa.predicates) | set(right_dfa.predicates)))

    # Map product states to integers
    state_map: dict[tuple[int, int], int] = {}
    counter = 0
    for ls in range(left_dfa.num_states):
        for rs in range(right_dfa.num_states):
            state_map[(ls, rs)] = counter
            counter += 1

    num_states = counter
    initial = state_map[(left_dfa.initial_state, right_dfa.initial_state)]

    # Identify violation states
    violation_states: set[int] = set()
    for (ls, rs), sid in state_map.items():
        left_viol = ls in left_dfa.violation_states
        right_viol = rs in right_dfa.violation_states
        if conj and (left_viol or right_viol):
            violation_states.add(sid)
        elif not conj and (left_viol and right_viol):
            violation_states.add(sid)

    # Build transition table
    table: dict[int, dict[int, int]] = {}
    for (ls, rs), sid in state_map.items():
        table[sid] = {}
        for symbol in range(2 ** len(all_preds)):
            valuation = _symbol_to_valuation(all_preds, symbol)
            left_sym = _project_symbol(all_preds, left_dfa.predicates, symbol)
            right_sym = _project_symbol(all_preds, right_dfa.predicates, symbol)
            left_next = left_dfa.transition_table[ls][left_sym]
            right_next = right_dfa.transition_table[rs][right_sym]
            table[sid][symbol] = state_map[(left_next, right_next)]

    return _DFA(predicates=all_preds, num_states=num_states, initial_state=initial,
                transition_table=table, violation_states=frozenset(violation_states))


def _project_symbol(all_preds: tuple[str, ...], sub_preds: tuple[str, ...], symbol: int) -> int:
    """Project a symbol over all_preds down to sub_preds."""
    valuation = _symbol_to_valuation(all_preds, symbol)
    result = 0
    for i, p in enumerate(sub_preds):
        if valuation.get(p, False):
            result |= 1 << i
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compile_monitor_rule(rule: MonitorRuleSpec) -> CompiledMonitorRule:
    level = rule.on_violation.strip().lower()
    if level not in VIOLATION_LEVELS:
        raise MonitorCompileError(f"invalid violation handling level: {rule.on_violation}")

    ast = _parse_dsl(rule.dsl)
    dfa = _compile_ast(ast)

    return CompiledMonitorRule(
        rule_id=rule.rule_id,
        dsl=" ".join(rule.dsl.split()),
        on_violation=level,
        predicates=dfa.predicates,
        initial_state=dfa.initial_state,
        transition_table=dfa.transition_table,
        violation_states=dfa.violation_states,
    )


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
# Transition functions for basic patterns
# ---------------------------------------------------------------------------

def _forbidden_transition(atom: str):
    def transition(state: int, valuation: Mapping[str, bool]) -> int:
        if state == 1:
            return 1  # Absorbing violation state
        if valuation.get(atom, False):
            return 1
        return 0

    return transition


def _implication_future_transition(antecedent: str, consequent: str):
    def transition(state: int, valuation: Mapping[str, bool]) -> int:
        antecedent_now = valuation.get(antecedent, False)
        consequent_now = valuation.get(consequent, False)

        if state == 2:
            return 2
        if state == 0:
            if antecedent_now and not consequent_now:
                return 1
            return 0

        if consequent_now:
            return 0
        if antecedent_now:
            return 2
        return 1

    return transition


def _until_transition(left: str, right: str):
    def transition(state: int, valuation: Mapping[str, bool]) -> int:
        if state in (1, 2):
            return state

        right_now = valuation.get(right, False)
        left_now = valuation.get(left, False)
        if right_now:
            return 1
        if left_now:
            return 0
        return 2

    return transition


# ---------------------------------------------------------------------------
# DFA table construction helpers
# ---------------------------------------------------------------------------

def _build_transition_table(predicates: tuple[str, ...], num_states: int, transition_fn):
    table: dict[int, dict[int, int]] = {}
    for state in range(num_states):
        table[state] = {}
        for symbol in range(2 ** len(predicates)):
            valuation = _symbol_to_valuation(predicates, symbol)
            table[state][symbol] = int(transition_fn(state, valuation))
    return table


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
    return predicate in set(event.get("tags", []))
