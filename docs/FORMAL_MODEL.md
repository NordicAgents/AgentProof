# Formal Model

This document defines the abstract transition system audited for correctness.

## State Definition
State `S` is a tuple:
- `memory`: finite key-value map
- `budgets`: `(calls_used, cost_used, retries_used)`
- `permissions`: set of granted capabilities
- `trace`: ordered list of events
- `status`: `{ready, halted, completed}`
- `monitor_state`: automaton states for temporal rules

## Action Definition
Action `A` is a typed record:
- `action_type`: registered symbol
- `tool_name`: target wrapper identifier
- `input`: schema-conformant payload
- `metadata`: proposer id, correlation id, timestamp, version

## Transition Function
Deterministic transition:
`T : S × A -> (Decision, S', Output)`
where `Decision ∈ {allowed, rejected, halted}`.

Rules:
1. Reject if schema invalid.
2. Reject if permission/precondition/invariant/budget/info-flow fails.
3. If allowed, execute wrapped tool and apply deterministic state update.
4. Update trace and monitor state exactly once per step.

## Invariants
- Only registered tools may execute.
- Budgets never exceed configured bounds.
- Protected data cannot flow to disallowed sinks.
- Rejected actions cause no side effects.
- Trace is append-only and hash-linked.

## Temporal Properties
Examples:
- `G(!DeleteUser)` for forbidden operations.
- `G(ApprovePayment -> F LedgerWrite)` for obligation eventuality.
- `G(retries <= N)` bounded retries.
- `F completed` within bounded step horizon where required.

## Assumptions
- Wrapper metadata accurately reflects tool behavior.
- External systems honor declared idempotency contracts.
- Serialization/deserialization preserves semantic equality.
- Clock-based fields do not influence transition decisions.

## Determinism Guarantees
Given identical `(S, A, spec, tool_stub_outputs)`:
- Decision is identical.
- Next state hash is identical.
- Verification report hash is identical.

Nondeterministic tool outputs must be isolated via stubs/mocks during replay and certification runs.
