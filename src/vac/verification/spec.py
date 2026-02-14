"""Spec loading helpers for deterministic verification runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .config import SolverConfig


@dataclass(frozen=True)
class VerificationSpec:
    """Loaded verification spec with deterministic solver options."""

    solver: SolverConfig


def load_spec(spec: Mapping[str, Any] | None = None) -> VerificationSpec:
    """Load verification spec from mapping with deterministic defaults."""
    spec_data: Mapping[str, Any] = spec or {}
    solver = SolverConfig.from_mapping(spec_data.get("solver") if isinstance(spec_data, Mapping) else None)
    return VerificationSpec(solver=solver)
