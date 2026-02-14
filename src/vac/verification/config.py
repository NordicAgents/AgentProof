"""Deterministic verification solver configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SolverConfig:
    """Pinned deterministic solver options for reproducible runs."""

    random_seed: int = 7
    tactic_profile: str = "qflia-simplify-v1"
    timeout_ms: int = 250
    unknown_on_error: bool = True

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "SolverConfig":
        if raw is None:
            return cls()
        return cls(
            random_seed=int(raw.get("random_seed", cls.random_seed)),
            tactic_profile=str(raw.get("tactic_profile", cls.tactic_profile)),
            timeout_ms=int(raw.get("timeout_ms", cls.timeout_ms)),
            unknown_on_error=bool(raw.get("unknown_on_error", cls.unknown_on_error)),
        )
