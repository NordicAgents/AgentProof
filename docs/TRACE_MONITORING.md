# Trace Monitoring

## Temporal Property Enforcement
VAC enforces temporal policies over an append-only execution trace using monitor automata derived from DSL temporal rules.

## Trace Structure
Each trace event contains:
- step index
- action summary
- verification decision
- monitor transition snapshot
- state hash before/after
- optional tool I/O digest

## LTL-Style Rule Mapping
Examples:
- `G !X` -> forbidden-event automaton.
- `A -> F B` -> obligation tracker with pending set.
- `B U C` -> until monitor.

Compilation pipeline:
1. Parse LTL subset.
2. Convert to automaton.
3. Generate deterministic transition table.

## Violation Handling
- Immediate rejection for hard temporal violations.
- Configurable handling for soft obligations (warn, grace, escalate).
- Violation includes rule id, triggering event, and monitor state.

## Escalation Model
Levels:
1. Warn-only (non-blocking telemetry).
2. Block step (reject proposal).
3. Halt run (terminal safety breach).
4. External escalation (webhook/page/audit queue).

## Replay Support
- Recompute monitor transitions from trace genesis.
- Validate that historical violation points are reproducible.
- Produce signed replay report hash.
