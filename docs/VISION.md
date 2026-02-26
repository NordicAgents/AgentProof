# Vision: Static Graph Verification for AI Agents

## Problem

AI agents built on LangGraph (and similar frameworks) define their behavior as state-machine graphs: nodes are tools or LLM calls, edges are conditional transitions. Today, nobody analyzes these graphs before deployment. Safety checks happen at runtime — or not at all.

Runtime gatekeeping has fundamental limits:

- It adds latency to every step.
- It duplicates tool-binding logic the framework already provides.
- It can only observe violations after they happen.
- Audit trails are a commodity — multiple vendors already do this.

The gap is **pre-deployment static analysis** of the agent's workflow graph.

## Core Idea

Treat a LangGraph `StateGraph` as a formal directed graph. Extract the topology — nodes, edges, conditional branches, tool bindings — and run verification algorithms on it before a single token is generated.

If a safety property holds on the graph structure, it holds for every possible execution trace.

## What We Verify

- **Reachability:** Can the agent reach a dangerous tool node from its entry point?
- **Isolation:** Are tool nodes with side effects gated by approval nodes?
- **Temporal properties:** Do sequences of tool calls satisfy LTL constraints (e.g., "always authenticate before accessing data")?
- **Dead paths:** Are there unreachable nodes or impossible transitions?
- **Cycles:** Do loops have bounded iteration or exit conditions?

## Approach

1. **Graph extraction:** Parse a `StateGraph` definition into an abstract directed graph with typed nodes and labeled edges.
2. **Property specification:** Express safety properties as LTL formulas or structural graph predicates.
3. **Static analysis:** Run model checking, reachability analysis, and structural verification on the abstract graph.
4. **Verification report:** Produce a pass/fail report with counterexample traces for any violations.

## What We Keep From v1

The LTL-to-DFA monitor compiler (`agentproof.monitor.ltl`) — a genuinely useful primitive for compiling temporal formulas into deterministic finite automata. This feeds directly into the graph model-checking pipeline.

## Non-Goals

- Runtime interception or gatekeeping.
- Replacing LangGraph's execution engine.
- Proving properties about LLM outputs (inherently non-deterministic).
- Building another audit-trail SaaS.

## Why This Matters

As AI agents move into production — managing infrastructure, accessing APIs, executing transactions — the cost of a bad workflow graph grows fast. Catching structural flaws before deployment is cheaper, faster, and more reliable than catching them at runtime.

Static verification is the missing layer in the agent safety stack.
