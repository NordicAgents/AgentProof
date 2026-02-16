"""Deterministic replay and forensic summaries for VAC traces."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence

from vac.engine.step import step
from vac.state.model import State, canonical_state_hash
from vac.tools.registry import ToolRegistry
from vac.verification.spec import VerificationSpec


@dataclass(frozen=True)
class ReplayResult:
    """Replay result with parity signals and per-step hashes."""

    final_state: State
    state_hash: str
    decision_hash: str
    decision_sequence: tuple[str, ...]


def replay_proposals(
    initial_state: State,
    proposals: Sequence[Mapping[str, Any]],
    registry: ToolRegistry,
    *,
    spec: VerificationSpec | None = None,
) -> ReplayResult:
    """Replay proposal sequence through deterministic step() and produce parity hashes."""
    current = initial_state
    decisions: list[dict[str, Any]] = []
    for proposal in proposals:
        current = step(current, proposal, registry, spec=spec)
        event = current.trace[-1]
        decisions.append(
            {
                "step_index": event["step_index"],
                "decision": event["decision"],
                "violations": list(event["violations"]),
                "proposal_hash": event["proposal_hash"],
            }
        )

    decision_payload = json.dumps(decisions, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    decision_hash = hashlib.sha256(decision_payload.encode("utf-8")).hexdigest()
    sequence = tuple(item["decision"] for item in decisions)

    return ReplayResult(
        final_state=current,
        state_hash=canonical_state_hash(current),
        decision_hash=decision_hash,
        decision_sequence=sequence,
    )


def summarize_trace(state: State) -> dict[str, Any]:
    """Summarize a state's trace for forensic reporting."""
    allowed = 0
    denied = 0
    halted = 0
    violations: dict[str, int] = {}

    for event in state.trace:
        decision = event.get("decision")
        if decision == "allowed":
            allowed += 1
        else:
            denied += 1
        for violation in event.get("violations", []):
            violations[violation] = violations.get(violation, 0) + 1

    if state.status == "halted":
        halted = 1

    return {
        "run_id": state.run_id,
        "status": state.status,
        "decision_summary": {
            "allowed": allowed,
            "rejected": denied,
            "halted": halted,
        },
        "top_violations": [
            {"violation": key, "count": violations[key]}
            for key in sorted(violations, key=lambda item: (-violations[item], item))
        ],
        "trace_length": len(state.trace),
        "state_hash": canonical_state_hash(state),
    }
