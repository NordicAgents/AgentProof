"""Spec loading helpers for deterministic verification runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .config import SolverConfig
from .monitoring import CompiledMonitorRule, MonitorRuleSpec, compile_monitor_rule


@dataclass(frozen=True)
class VerificationSpec:
    """Loaded verification spec with deterministic solver options."""

    solver: SolverConfig
    monitors: tuple[CompiledMonitorRule, ...] = ()


def load_spec(spec: Mapping[str, Any] | None = None) -> VerificationSpec:
    """Load verification spec from mapping with deterministic defaults."""
    spec_data: Mapping[str, Any] = spec or {}
    solver = SolverConfig.from_mapping(spec_data.get("solver") if isinstance(spec_data, Mapping) else None)
    monitors = _load_monitors(spec_data)
    return VerificationSpec(solver=solver, monitors=monitors)


def _load_monitors(spec_data: Mapping[str, Any]) -> tuple[CompiledMonitorRule, ...]:
    raw_rules: Any = spec_data.get("temporal")
    if raw_rules is None:
        raw_rules = spec_data.get("temporal_rules")
    if raw_rules is None:
        return ()
    if not isinstance(raw_rules, list):
        raise TypeError("temporal rules must be a list")

    compiled: list[CompiledMonitorRule] = []
    for index, raw in enumerate(raw_rules):
        if not isinstance(raw, Mapping):
            raise TypeError(f"temporal rule at index {index} must be an object")
        rule_id = str(raw.get("rule_id", f"TEMP-{index+1}"))
        dsl = str(raw.get("dsl", "")).strip()
        if not dsl:
            raise ValueError(f"temporal rule {rule_id} requires non-empty dsl")
        on_violation = str(raw.get("on_violation", "block"))
        compiled.append(compile_monitor_rule(MonitorRuleSpec(rule_id=rule_id, dsl=dsl, on_violation=on_violation)))
    return tuple(compiled)
