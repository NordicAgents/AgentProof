"""Phase 4 compliance mapping and audit support."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

_CONTROL_MAP = {
    "permissions": ("CC6.1", "A.9.1"),
    "preconditions": ("CC7.2", "A.14.2"),
    "invariants": ("CC7.3", "A.14.2"),
    "budgets": ("CC7.1", "A.12.1"),
    "infoflow": ("CC6.7", "A.13.2"),
    "temporal": ("CC7.2", "A.12.4"),
    "execute": ("CC6.6", "A.12.5"),
    "schema": ("CC8.1", "A.14.1"),
}


def build_compliance_summary(trace: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Map trace rejection/allow decisions to deterministic control evidence."""
    control_hits: dict[str, int] = {}

    for event in trace:
        rejection = event.get("rejection")
        if isinstance(rejection, Mapping):
            rule_type = str(rejection.get("rule_type", "schema"))
            controls = _CONTROL_MAP.get(rule_type, ("CC9.0", "A.18.1"))
        else:
            controls = ("CC5.2", "A.12.1")

        for control in controls:
            control_hits[control] = control_hits.get(control, 0) + 1

    ordered_hits = {key: control_hits[key] for key in sorted(control_hits)}
    evidence_hash = hashlib.sha256(str(list(trace)).encode("utf-8")).hexdigest()

    return {
        "frameworks": ["soc2", "iso27001"],
        "controls": ordered_hits,
        "coverage": sorted(ordered_hits),
        "evidence_hash": evidence_hash,
    }
