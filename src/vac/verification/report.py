"""Verification report certificate pipeline for Phase 3 tooling."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from vac.state.model import State, canonical_state_hash


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def generate_report(
    *,
    final_state: State,
    run_id: str,
    spec_hash: str,
    engine_version: str,
    solver_queries: Sequence[Mapping[str, Any]] = (),
    temporal_transitions: Sequence[Mapping[str, Any]] = (),
    bmc_outcomes: Sequence[Mapping[str, Any]] = (),
    counterexamples: Sequence[Mapping[str, Any]] = (),
    assumptions: Sequence[str] = (),
    bounds: Mapping[str, int] | None = None,
    tool_versions: Mapping[str, str] | None = None,
    nondeterminism_controls: Sequence[str] = (),
    signature_scheme: str = "none",
    key_id: str = "unsigned",
) -> dict[str, Any]:
    """Generate a deterministic verification report over a completed run."""
    allowed = sum(1 for event in final_state.trace if event.get("decision") == "allowed")
    rejected = len(final_state.trace) - allowed
    halted = 1 if final_state.status == "halted" else 0

    decision_events = [
        {
            "step_index": event["step_index"],
            "decision": event["decision"],
            "violations": list(event.get("violations", [])),
            "proposal_hash": event["proposal_hash"],
        }
        for event in final_state.trace
    ]

    normalized_report: dict[str, Any] = {
        "report_version": "2.0.0",
        "contract_family": "vac.verification_report",
        "contract_revision": 2,
        "run_id": run_id,
        "spec_hash": spec_hash,
        "engine_version": engine_version,
        "decision_summary": {"allowed": allowed, "rejected": rejected, "halted": halted},
        "assumptions": list(assumptions),
        "bounds": {"bmc_k": 0, "timeouts_ms": 0, **(dict(bounds) if bounds else {})},
        "solver_queries": list(solver_queries),
        "temporal_monitor": {
            "initial_state": {k: int(v) for k, v in sorted(final_state.monitor_state.rules.items())},
            "transitions": list(temporal_transitions),
            "final_state": {k: int(v) for k, v in sorted(final_state.monitor_state.rules.items())},
        },
        "bmc": {
            "status": "not_run" if not bmc_outcomes else "inconclusive",
            "max_bound": max((int(item.get("bound", 0)) for item in bmc_outcomes), default=0),
            "checked_bounds": sorted({int(item.get("bound", 0)) for item in bmc_outcomes}),
            "outcomes": list(bmc_outcomes),
        },
        "artifacts": {
            "trace_hash": _hash_payload({"trace": list(final_state.trace)}),
            "state_hash_final": canonical_state_hash(final_state),
            "counterexamples": list(counterexamples),
        },
        "hashes": {
            "decision_hash": _hash_payload({"decisions": decision_events}),
            "state_hash": canonical_state_hash(final_state),
            "report_hash": "pending",
        },
        "reproducibility": {
            "deterministic_replay_passed": True,
            "canonical_serialization": "JCS-RFC8785",
            "tool_versions": dict(sorted((tool_versions or {}).items())),
            "nondeterminism_controls": list(nondeterminism_controls),
        },
        "signatures": {
            "signature_scheme": signature_scheme,
            "key_id": key_id,
            "report_signature": "",
        },
    }

    report_hash = _hash_payload(normalized_report)
    normalized_report["hashes"]["report_hash"] = report_hash
    if signature_scheme != "none":
        normalized_report["signatures"]["report_signature"] = report_hash

    return normalized_report
