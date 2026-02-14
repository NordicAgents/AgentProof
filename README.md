# Formal Verification of AI Agents using VAC

Verifiable Agent Core (VAC) is a deterministic execution layer that enables formal verification of AI agent behavior. It provides a secure, typed, and policy-enforced boundary between AI orchestration frameworks and real-world side effects.

VAC ensures that no tool execution, state mutation, or external interaction occurs without passing through a formally enforceable verification pipeline.

---

## Overview

AI agents built with LLMs are probabilistic and non-deterministic. While they can generate plans and propose actions, they cannot be trusted to directly execute side effects.

VAC introduces a verifiable execution boundary:

LLM / Orchestrator → Proposed Action → VAC Verification → Execution

Only actions that satisfy formal constraints are executed.

---

## Core Guarantees

VAC provides enforceable guarantees at the execution layer:

- All actions are strictly typed and schema-validated
- No unregistered tool can be executed
- Policy invariants are enforced before every action
- Resource limits cannot be exceeded
- Information flow constraints are enforced
- Execution traces are logged and auditable
- Deterministic replay is supported
- Verification reports are generated per run

---

## Architecture Summary

VAC consists of the following components:

- Typed Action System
- Deterministic State Machine
- Policy Specification DSL
- Step-Level Verification Engine (SMT-backed)
- Runtime Trace Monitor
- Tool Wrapper Enforcement Layer
- Verification Report Generator

All external orchestration frameworks must call the `step()` function to execute actions.

---

## Key Concepts

### Typed Actions
All agent outputs must conform to a registered action schema. Free-form text cannot trigger side effects.

### Policy DSL
Human-readable rules defining:
- Safety invariants
- Preconditions
- Resource constraints
- Information flow restrictions
- Temporal properties

### Verification Pipeline
Every proposed action passes through:
1. Schema validation
2. Permission checks
3. Preconditions
4. Invariant checks
5. Budget validation
6. Information flow validation
7. Runtime temporal monitoring

If any rule is violated, execution is rejected.

---

## Example Flow

1. Agent proposes:
