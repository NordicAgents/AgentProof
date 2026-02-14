# Formal Verification of AI Agents

# Product Requirements Document (PRD)

## Product: Verifiable Agent Core (VAC)

---

## 1. Overview

### Purpose

Build a deterministic execution core that enables formal verification of AI agent behavior by enforcing typed actions, policy constraints, and runtime verification before any side effects occur.

The system must allow integration with LLM orchestration frameworks (e.g., LangGraph, OpenAI SDK) while maintaining verifiable guarantees at the execution boundary.

### Non-Goals

* Verifying internal correctness of neural network models
* Guaranteeing truthfulness of LLM outputs
* Replacing orchestration frameworks
* Full theorem-proving of unbounded agent behavior (initial release)

---

## 2. Problem Statement

LLM-based agents are probabilistic and untrusted. Current frameworks allow direct execution of tool calls without formal enforcement of:

* Safety invariants
* Resource limits
* Permission boundaries
* Information flow constraints

There is no standardized execution boundary that enables formal verification of agent behavior.

---

## 3. Product Scope

The product will provide:

* A deterministic core execution engine
* Typed action enforcement
* Policy specification DSL
* Formal constraint checking (SMT-based)
* Runtime trace monitoring
* Verification reporting

All side effects must be mediated through this core.

---

# 4. Core Functional Requirements

## 4.1 Typed Action System

### Requirement

The system must require all agent proposals to conform to a registered typed action schema.

### Capabilities

* Define actions with strict schemas (JSON Schema / Pydantic / equivalent)
* Validate all proposals against schema before execution
* Reject malformed or unknown actions

### Acceptance Criteria

* Any action not matching schema is rejected deterministically
* Schema validation occurs before policy checks
* All tools are represented as typed actions

---

## 4.2 Tool Registration & Wrapper Enforcement

### Requirement

All side-effectful operations must be registered as wrapped tools.

### Capabilities

* Register tool with:

  * Name
  * Input schema
  * Optional output schema
  * Cost model
  * Permission scope
* Tools are callable only through the core
* External frameworks cannot bypass tool wrappers

### Acceptance Criteria

* No tool can be executed without passing through validation pipeline
* Tool calls are logged with full input/output trace
* Permission mismatches are rejected

---

## 4.3 State Model

### Requirement

The core must maintain an explicit and minimal deterministic state.

### Required State Components

* Memory (key-value store)
* Budget counters (tool calls, cost, retries)
* Permission flags
* Execution trace
* Task status

### Acceptance Criteria

* State transitions are deterministic
* State before/after each action is recorded
* State can be serialized for replay and verification

---

## 4.4 Policy Specification DSL

### Requirement

Provide a human-readable DSL that compiles into formal constraints.

### Supported Policy Types

#### A. Invariants (Safety)

* Must always hold
* Example: “Never call DeleteUser”

#### B. Preconditions

* Conditions required before action execution
* Example: “SendEmail requires consent == true”

#### C. Resource Constraints

* Max tool calls
* Max cost
* Max retries

#### D. Information Flow Constraints

* Label-based data restrictions
* Example: SECRET cannot flow to network tool

### Acceptance Criteria

* DSL compiles into executable constraint representation
* Invalid DSL rules fail compilation
* Rules are evaluated deterministically

---

## 4.5 Step-Level Verification Engine

### Requirement

Each proposed action must pass formal verification before execution.

### Verification Steps

1. Schema validation
2. Permission check
3. Preconditions evaluation
4. Invariant evaluation
5. Budget check
6. Info-flow validation

### Implementation

* SMT solver (e.g., Z3) for constraint checking
* Deterministic evaluation logic

### Acceptance Criteria

* Any rule violation results in rejection
* Rejection returns structured error with violated rule ID
* Verification decision is deterministic for same state + action

---

## 4.6 Runtime Trace Monitoring

### Requirement

Support temporal rules across execution traces.

### Supported Temporal Properties

* “Action X must not occur before Y”
* “If A happens, B must eventually happen”
* “No more than N retries”
* “Must terminate within K steps”

### Implementation

* LTL-style runtime monitor
* Streaming trace evaluation

### Acceptance Criteria

* Violations trigger immediate halt or escalation
* Temporal properties evaluated incrementally
* Trace can be replayed for audit

---

## 4.7 Bounded Model Checking (Optional Phase 2)

### Requirement

Enable bounded verification over k-step traces before execution.

### Capabilities

* Simulate execution up to k steps
* Check invariants across all possible traces within bound
* Generate counterexample trace if property fails

### Acceptance Criteria

* Verification report includes bound (k)
* Counterexample includes minimal failing trace
* Assumptions are documented

---

## 4.8 Execution Gating API

### Requirement

Expose a minimal deterministic execution API.

### Required Interface

```
register_tool(...)
load_spec(...)
initialize_state(...)
step(state, proposal) -> {allowed|rejected, result, new_state}
```

### Acceptance Criteria

* All external frameworks must call `step()`
* No side effects occur outside `step()`
* Deterministic replay produces identical result

---

## 4.9 Verification Reporting

### Requirement

System must generate formal verification reports.

### Report Contents

* Spec version/hash
* Agent version/hash
* Tool versions
* Properties enforced
* Verification method used
* Bounds (if applicable)
* Assumptions
* Violations or counterexamples

### Acceptance Criteria

* Report generated per run
* Report exportable (JSON + human-readable)
* Counterexamples reproducible

---

## 4.10 Integration Requirements

### Requirement

Allow integration with external orchestration frameworks.

### Constraints

* External frameworks can propose actions only
* They cannot directly execute tools
* All effects mediated by core

### Acceptance Criteria

* LangGraph adapter available
* OpenAI SDK adapter available
* Bypass attempts rejected

---

# 5. Non-Functional Requirements

## Determinism

Given identical state and proposal, verification decision must be identical.

## Performance

* Step verification latency < 100ms for typical constraints
* Trace monitoring overhead < 5%

## Auditability

* Full trace logging
* State snapshot capability
* Deterministic replay

## Security

* No dynamic code execution
* Tool isolation enforced

---

# 6. Assumptions

* Tools behave according to declared schemas
* External services are trusted within declared contracts
* Verification is bounded where specified

---

# 7. Success Criteria

The system is considered successful when:

1. An agent cannot execute a forbidden tool under any condition.
2. Resource limits cannot be exceeded.
3. Violations produce deterministic counterexamples.
4. External frameworks cannot bypass the core.
5. Users can produce a machine-verifiable safety report.


