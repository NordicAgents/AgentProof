"""Canonical state model and deterministic serialization/hashing."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping


@dataclass(frozen=True)
class BudgetCounters:
    max_calls: int
    used_calls: int
    max_cost: float
    used_cost: float
    max_retries: int
    used_retries: int


@dataclass(frozen=True)
class MonitorRuntimeState:
    """Deterministic runtime monitor state keyed by rule identifier."""

    rules: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class State:
    version: str
    run_id: str
    memory: Mapping[str, Any] = field(default_factory=dict)
    budgets: BudgetCounters = field(
        default_factory=lambda: BudgetCounters(
            max_calls=0,
            used_calls=0,
            max_cost=0.0,
            used_cost=0.0,
            max_retries=0,
            used_retries=0,
        )
    )
    permissions: frozenset[str] = field(default_factory=frozenset)
    trace: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    monitor_state: MonitorRuntimeState = field(default_factory=MonitorRuntimeState)
    status: str = "ready"

    def with_updates(self, **changes: Any) -> "State":
        data = self.to_dict()
        data.update(changes)
        if "budgets" in data and isinstance(data["budgets"], Mapping):
            data["budgets"] = BudgetCounters(**data["budgets"])
        if "permissions" in data and not isinstance(data["permissions"], frozenset):
            data["permissions"] = frozenset(data["permissions"])
        if "trace" in data and not isinstance(data["trace"], tuple):
            data["trace"] = tuple(data["trace"])
        if "monitor_state" in data:
            monitor_state = data["monitor_state"]
            if isinstance(monitor_state, MonitorRuntimeState):
                pass
            elif isinstance(monitor_state, Mapping):
                if "rules" in monitor_state and isinstance(monitor_state["rules"], Mapping):
                    data["monitor_state"] = MonitorRuntimeState(rules=dict(monitor_state["rules"]))
                else:
                    data["monitor_state"] = MonitorRuntimeState(rules=dict(monitor_state))
            else:
                raise TypeError("monitor_state must be a mapping or MonitorRuntimeState")
        return State(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "run_id": self.run_id,
            "memory": _normalize(self.memory),
            "budgets": {
                "max_calls": self.budgets.max_calls,
                "used_calls": self.budgets.used_calls,
                "max_cost": self.budgets.max_cost,
                "used_cost": self.budgets.used_cost,
                "max_retries": self.budgets.max_retries,
                "used_retries": self.budgets.used_retries,
            },
            "permissions": sorted(self.permissions),
            "trace": [_normalize(e) for e in self.trace],
            "monitor_state": {"rules": _normalize(self.monitor_state.rules)},
            "status": self.status,
        }


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _normalize(value[k]) for k in sorted(value)}
    if isinstance(value, tuple):
        return [_normalize(v) for v in value]
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, set):
        return sorted(_normalize(v) for v in value)
    if isinstance(value, frozenset):
        return sorted(_normalize(v) for v in value)
    return value


def canonical_state_json(state: State) -> str:
    """Canonical JSON form: sorted keys, UTF-8 safe, compact separators."""
    return json.dumps(state.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_state_hash(state: State) -> str:
    """Stable SHA-256 hash over canonical bytes."""
    return hashlib.sha256(canonical_state_json(state).encode("utf-8")).hexdigest()
