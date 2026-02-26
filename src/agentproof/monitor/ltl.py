"""Temporal monitor compilation and runtime evaluation."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


class MonitorCompileError(ValueError):
    """Raised when temporal rule DSL cannot be compiled."""


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


def compile_monitor_rule(rule: MonitorRuleSpec) -> CompiledMonitorRule:
    level = rule.on_violation.strip().lower()
    if level not in VIOLATION_LEVELS:
        raise MonitorCompileError(f"invalid violation handling level: {rule.on_violation}")

    dsl = " ".join(rule.dsl.split())
    forbidden_match = re.fullmatch(r"G\s+!\s*([^\s]+)", dsl)
    if forbidden_match is not None:
        atom = forbidden_match.group(1)
        predicates = (atom,)
        table = _build_transition_table(predicates, _forbidden_transition(atom))
        return CompiledMonitorRule(
            rule_id=rule.rule_id,
            dsl=dsl,
            on_violation=level,
            predicates=predicates,
            initial_state=0,
            transition_table=table,
            violation_states=frozenset({1}),
        )

    implication_match = re.fullmatch(r"([^\s]+)\s*->\s*F\s+([^\s]+)", dsl)
    if implication_match is not None:
        antecedent = implication_match.group(1)
        consequent = implication_match.group(2)
        predicates = tuple(sorted({antecedent, consequent}))
        table = _build_transition_table(predicates, _implication_future_transition(antecedent, consequent))
        return CompiledMonitorRule(
            rule_id=rule.rule_id,
            dsl=dsl,
            on_violation=level,
            predicates=predicates,
            initial_state=0,
            transition_table=table,
            violation_states=frozenset({2}),
        )

    until_match = re.fullmatch(r"([^\s]+)\s+U\s+([^\s]+)", dsl)
    if until_match is not None:
        left = until_match.group(1)
        right = until_match.group(2)
        predicates = tuple(sorted({left, right}))
        table = _build_transition_table(predicates, _until_transition(left, right))
        return CompiledMonitorRule(
            rule_id=rule.rule_id,
            dsl=dsl,
            on_violation=level,
            predicates=predicates,
            initial_state=0,
            transition_table=table,
            violation_states=frozenset({2}),
        )

    raise MonitorCompileError(f"unsupported temporal DSL expression: {rule.dsl}")


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


def _forbidden_transition(atom: str):
    def transition(_state: int, valuation: Mapping[str, bool]) -> int:
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


def _build_transition_table(predicates: tuple[str, ...], transition_fn):
    table: dict[int, dict[int, int]] = {}
    for state in (0, 1, 2):
        table[state] = {}
        for symbol in range(0, 2 ** len(predicates)):
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
