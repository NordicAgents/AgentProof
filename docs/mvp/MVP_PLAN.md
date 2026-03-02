# VAC MVP Implementation Plan

## 1) MVP Goal
Ship a production-usable **MVP of the Verifiable Agent Core (VAC)** that enforces a deterministic execution boundary for AI agents via:
- typed action validation,
- wrapper-only tool execution,
- policy checks (invariants/preconditions/budgets/permissions),
- deterministic state + append-only trace,
- runtime temporal monitoring,
- auditable verification reports,
- and one end-to-end framework integration path.

This MVP intentionally excludes full unbounded proofs and enterprise hardening features.

---

## 2) Scope Alignment

### In-Scope for MVP
- Core `step()` verification and gating pipeline.
- Action schema system + tool registry.
- Deterministic state model and serialization.
- DSL compiler for core policy classes.
- SMT-backed checks for step-level constraints.
- Runtime temporal monitor with halt/reject actions.
- Verification decision/report generation.
- One first-party integration adapter (LangGraph **or** OpenAI SDK).
- Deterministic replay + CI baseline tests.

### Out-of-Scope for MVP
- Full enterprise compliance mapping.
- Advanced multi-agent governance model.
- Unbounded theorem proving.
- Deep external sandboxing/isolation hardening beyond wrapper model.

---

## 3) Success Criteria (MVP Exit)
MVP is complete when all criteria are met:
1. **No side effects outside the gate:** all tool calls flow through `step()` and registered wrappers.
2. **Deterministic decisions:** same `(state, proposal, spec, stubbed outputs)` yields identical decision and state hash.
3. **Policy enforcement:** invalid schema/permission/precondition/invariant/budget/info-flow proposals are rejected with structured rule IDs.
4. **Temporal enforcement:** runtime monitor catches configured temporal violations and enforces reject/halt.
5. **Auditability:** replay of recorded traces reproduces decision stream and final state hash.
6. **Developer usability:** adapter + API docs enable integration with one orchestrator in <1 day.

---

## 4) Delivery Phases

## Phase 0 — Foundations & Design Freeze (Week 1)
**Objective:** lock MVP architecture, interfaces, and acceptance tests before implementation.

### Workstreams
- Finalize canonical interfaces:
  - `register_tool(definition)`
  - `load_spec(specSource)`
  - `initialize_state(config)`
  - `step(state, proposal)`
  - `generate_report(runArtifacts)`
- Freeze state schema (memory/budgets/permissions/trace/status/monitor-state).
- Define deterministic serialization and hashing rules.
- Define rejection/error envelope and rule-id schema.
- Build MVP backlog with clear acceptance criteria tied to PRD requirements.

### Deliverables
- Interface contract doc and examples.
- MVP acceptance matrix (requirement → test).
- Determinism profile (seed/timeouts/pinned solver config).

### Exit Gate
- Architecture + API signoff.
- Acceptance matrix approved by engineering + product.

---

## Phase 1 — Deterministic Core Gate (Weeks 2–3)
**Objective:** implement end-to-end deterministic verification pipeline for single-step execution.

### Workstreams
1. **Typed Action & Registry**
   - Implement action schema validation and versioning checks.
   - Register tools with metadata (permissions, cost model, optional output schema).
   - Reject unknown/malformed tools and inputs deterministically.

2. **Core State Machine**
   - Implement canonical `State` and deterministic transition rules.
   - Ensure trace append happens exactly once per step.
   - Add atomic state commit semantics for allowed executions.

3. **Baseline Policy Evaluator (non-temporal)**
   - Permission checks.
   - Preconditions and invariants.
   - Budget/cost/retry checks.
   - Structured rejection with violated rule ids and machine-readable reason codes.

4. **Wrapper Enforcement**
   - Enforce that only registered wrappers can execute side effects.
   - Log input/output digests and execution metadata.

### Deliverables
- Working `step()` that supports allow/reject/halt decisions.
- Registered wrapper path for at least 2 representative tools.
- Trace events with before/after state hash and decision.

### Exit Gate
- Integration test proves side effects cannot occur when verification fails.
- Determinism test passes for repeated identical runs.

---

## Phase 2 — DSL + SMT Verification (Weeks 4–5)
**Objective:** compile policy specs and verify step constraints using deterministic SMT queries.

### Workstreams
1. **Spec Language MVP Compiler**
   - Parse and validate DSL syntax.
   - Compile invariants, preconditions, budgets, and info-flow rules into executable + SMT forms.
   - Fail fast on invalid DSL with line/column diagnostics.

2. **SMT Layer**
   - Encode action/state constraints to solver formulas.
   - Run solver with pinned deterministic profile (seed, tactics, timeout policy).
   - Normalize SAT/UNSAT/UNKNOWN handling into deterministic decision logic.

3. **Counterexample-ready Rejection Path**
   - Attach violated rule references and minimal explainability payload.
   - Store solver artifacts needed for debugging/audit.

### Deliverables
- `load_spec()` producing validated compiled policy handles.
- Solver-backed verification integrated into `step()`.
- Test fixtures for SAT/UNSAT regression.

### Exit Gate
- Rule changes in DSL immediately affect runtime decisions.
- Solver outcomes are stable across repeat runs in CI container.

---

## Phase 3 — Runtime Temporal Monitoring + Replay (Weeks 6–7)
**Objective:** enforce LTL-style temporal properties over append-only traces and guarantee replayability.

### Workstreams
1. **Temporal Rule Compilation**
   - Compile supported LTL subset to deterministic monitor automata.
   - Persist monitor state in canonical VAC state.

2. **Streaming Monitor Integration**
   - Evaluate monitor transitions each step.
   - Enforce escalation policy: warn / reject step / halt run.
   - Emit violation payload with rule id + trigger event + monitor snapshot.

3. **Replay Engine**
   - Recompute decisions and monitor transitions from genesis trace.
   - Validate historical violations and final state hash parity.

### Deliverables
- Temporal enforcement in live step pipeline.
- Replay CLI/library API for forensic validation.
- Signed/hashed replay output for audit consumption.

### Exit Gate
- Temporal violation scenarios reproducibly trigger configured escalation.
- Replay of stored traces reproduces original outcome and hashes.

---

## Phase 4 — Reporting + First Integration (Weeks 8–9)
**Objective:** make the MVP usable by application teams through reports and one production-ready adapter.

### Workstreams
1. **Verification Reporting**
   - Implement report schema fields (spec version, tool version, decision log, rule checks, hashes, assumptions).
   - Add reproducibility metadata and deterministic report hashing.

2. **Framework Adapter (choose one)**
   - Option A: LangGraph interception adapter.
   - Option B: OpenAI tool-call interception adapter.
   - Ensure all tool proposals are transformed into VAC typed actions.

3. **Developer Experience**
   - Add quickstart + integration example.
   - Add operator runbook for common rejection/violation workflows.

### Deliverables
- `generate_report()` with MVP certificate format.
- One end-to-end sample app using adapter + VAC enforcement.
- Integration docs and troubleshooting guide.

### Exit Gate
- External orchestrator cannot execute side effects without VAC gate.
- Demo flow shows allowed actions, rejection path, and audit report output.

---

## Phase 5 — Hardening Sprint (Week 10)
**Objective:** stabilize quality, performance, and release readiness.

### Workstreams
- Adversarial testing (prompt-injection-shaped proposals, bypass attempts).
- Property-based determinism testing.
- Performance tuning for p95 step latency target.
- Packaging/version pinning and release checklist.

### Deliverables
- Release candidate build.
- Known limitations + assumptions published.
- MVP launch checklist signed.

### Exit Gate
- All P0/P1 defects closed.
- CI quality bar green.
- Stakeholder go/no-go approved.

---

## 5) Cross-Phase Testing Strategy

### Mandatory Test Suites
- Unit tests for schema, policy checks, solver encoding, monitor transitions.
- Deterministic replay tests with stubbed tool outputs.
- Integration tests for wrapper-only side effects.
- Adversarial tests for bypass and permission escalation attempts.
- Golden tests for report schema and hash stability.

### CI Cadence
- Per-PR: fast deterministic unit + integration subset.
- Nightly: extended temporal + bounded model checking suite.
- Weekly: replay conformance and performance trend checks.

---

## 6) Operating Metrics (MVP)
Track continuously from Phase 2 onward:
- Verification pass/reject/halt rates.
- Top violated rule IDs.
- p50/p95 step verification latency.
- Replay success rate.
- Adapter interception coverage (% proposals routed through VAC).
- Determinism drift incidents (target: zero).

---

## 7) Risks and Mitigations

1. **Solver nondeterminism / flaky outcomes**  
   _Mitigation:_ pinned solver version/options, deterministic seeds, strict timeout policy, golden SAT/UNSAT fixtures.

2. **Spec complexity causing latency spikes**  
   _Mitigation:_ lint complexity budgets, pre-solver fast checks, rule profiling, fallback escalation policy.

3. **Framework bypass paths**  
   _Mitigation:_ enforce adapter interception at single execution choke point; add negative tests proving direct tool calls fail.

4. **Audit artifacts insufficient for forensic use**  
   _Mitigation:_ include canonical hashes, version metadata, reproducibility assumptions, and replay commands in reports.

5. **Scope creep into enterprise features**  
   _Mitigation:_ strict MVP gate; defer multi-agent advanced governance and compliance mapping post-MVP.

---

## 8) Post-MVP Immediate Next Steps
- Add bounded model checking depth controls and counterexample UX.
- Expand to second integration adapter.
- Introduce multi-agent policy package.
- Add stronger information-flow labels and sink taxonomy.
- Begin compliance evidence mapping for regulated deployments.

---

## 9) Suggested Team Structure (Lean MVP)
- 1 Tech Lead (architecture + determinism owner)
- 2 Core engineers (state machine, wrappers, API)
- 1 Formal methods engineer (DSL/compiler/SMT)
- 1 Platform engineer (adapter + CI/release)
- 1 QA/SDET (replay, adversarial, determinism suite)

This structure can be scaled down by extending timeline; quality gates should remain unchanged.
