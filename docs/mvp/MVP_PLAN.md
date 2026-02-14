# MVP Plan — Phase 1 (Core Foundation)

## Purpose

This document defines the implementation scope for **Phase 1: Core Foundation** in `docs/ROADMAP.md`, focused on establishing a deterministic, enforceable execution boundary for the Verifiable Agent Core (VAC).

Phase 1 delivers the minimum viable kernel required for safe action gating and replayable execution, while explicitly deferring deeper formal methods and temporal monitoring to later phases.

## Phase 1 Scope (Aligned to Roadmap)

Phase 1 includes the following roadmap items:

1. Typed action schema and validation.
2. Tool registry and wrapper enforcement.
3. Deterministic state transition core (`step`).
4. Invariant, precondition, and budget checks.

## Deliverables

### 1) Typed Action Schema + Validation

- Define a canonical typed action model (`name`, `version`, `payload`, `metadata`).
- Implement schema registration and validation flow for all incoming proposals.
- Enforce rejection behavior for:
  - unknown action/tool names,
  - malformed payloads,
  - schema-version mismatches.
- Ensure schema validation runs before all other verification checks.

### 2) Tool Registry / Wrapper Enforcement

- Create a registry for wrapped tools with required metadata:
  - tool name,
  - input schema,
  - optional output schema,
  - cost model,
  - permission scope.
- Route all tool invocation through wrapper adapters controlled by VAC.
- Capture deterministic input/output trace records for every attempted tool call.
- Reject direct or bypass invocation paths outside the wrapper pipeline.

### 3) Deterministic State Transition Core (`step`)

- Implement deterministic execution API surface:
  - `register_tool(...)`
  - `load_spec(...)`
  - `initialize_state(...)`
  - `step(state, proposal) -> decision`
- Implement explicit state model with:
  - memory map,
  - budget counters,
  - permission flags,
  - execution trace,
  - task status.
- Persist before/after snapshots for each transition.
- Guarantee deterministic decision and state transition for identical `(state, proposal)` input.

### 4) Invariant / Precondition / Budget Checks

- Implement deterministic rule evaluator for:
  - preconditions (must hold before action),
  - invariants (must always hold),
  - budget/resource limits (calls, cost, retries).
- Enforce ordered verification sequence within `step`:
  1. schema validation,
  2. permission checks,
  3. precondition checks,
  4. invariant checks,
  5. budget checks.
- Return structured rejection responses with stable rule identifiers and reason codes.

## Acceptance Criteria Mapping (PRD)

### PRD §4.1 — Typed Action System

- All proposals are validated against registered typed schemas before policy evaluation.
- Non-conforming or unknown actions are rejected deterministically.
- All tool operations are modeled as typed actions.

### PRD §4.2 — Tool Registration & Wrapper Enforcement

- Tool execution is only available via VAC-registered wrappers.
- Every tool call attempt records full input/output (or rejection) in trace.
- Permission mismatch blocks execution with explicit rejection metadata.

### PRD §4.3 — State Model

- State contains memory, budgets, permission flags, trace, and task status.
- Each step records pre-state and post-state snapshots.
- State is serializable and replayable without semantic loss.

### PRD §4.5 — Step-Level Verification Engine

- Step verification enforces ordered checks with deterministic outcomes.
- Any violated invariant, precondition, permission, or budget rule rejects the action.
- Rejections contain structured error payload with violated rule ID.

### PRD §4.8 — Execution Gating API

- `step()` is the only side-effect gateway.
- Integrations interact by proposing actions, never by executing tools directly.
- Deterministic replay on identical inputs reproduces identical decisions and transitions.

## Out of Scope for Phase 1

The following roadmap/PRD capabilities are explicitly deferred:

- **SMT depth and bounded model checking** (Phase 2 formal depth).
- **Temporal runtime monitoring** across traces (LTL/streaming monitor).
- Advanced counterexample generation beyond single-step rejection metadata.

## Milestone Checklist (Target Modules)

- [ ] Create `src/vac/actions/` for typed action definitions, schema registry, and validators.
- [ ] Create `src/vac/tools/` for tool registry, wrappers, permission scoping, and cost metadata.
- [ ] Create `src/vac/state/` for deterministic state model, serialization, and snapshot support.
- [ ] Create `src/vac/engine/` for `step` orchestration and ordered verification pipeline.
- [ ] Add shared error/result contracts for deterministic allow/reject decisions.
- [ ] Add replay utility path for deterministic re-execution from serialized state + proposal.

## Definition of Done (Phase 1)

Phase 1 is complete only when all of the following are true:

1. **Functional completeness**
   - Deliverables in this document are implemented behind the execution boundary.
2. **Test coverage**
   - Unit tests cover schema validation, wrapper enforcement, state transition determinism, and rule rejection paths.
   - Integration tests cover end-to-end `step()` gating with side-effect mediation.
3. **Deterministic replay evidence**
   - A replay test fixture demonstrates identical outcomes for repeated runs with same initial state and proposal sequence.
   - Replay artifacts include decision parity and state-hash parity checks.
4. **Documentation parity**
   - API and architecture docs reflect final Phase 1 interfaces and constraints.
