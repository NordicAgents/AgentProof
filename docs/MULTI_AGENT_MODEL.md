# Multi-Agent Model

## Goal
Support orchestrated multi-agent workflows while preserving single-boundary verification guarantees.

## Model
- Shared global state + per-agent local memory partitions.
- Agent-scoped permissions and budget slices.
- Inter-agent messages treated as typed actions/events.

## Coordination Rules
- All cross-agent tool intents pass through global `step()`.
- Conflict resolution via deterministic ordering (`step_index`, agent_id).
- Temporal policies may span agents (e.g., reviewer must approve executor).

## Isolation
- Agent A cannot mutate Agent B private partition unless policy grants.
- Shared resources require explicit lock/lease action types.

## Auditability
- Trace includes `agent_id` and causality links.
- Replay reproduces global schedule deterministically.
