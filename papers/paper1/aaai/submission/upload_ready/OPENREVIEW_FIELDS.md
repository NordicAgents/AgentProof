# OpenReview fields

This is an operator copy/paste aid. Do **not** upload this Markdown file.
Re-sync it if `main.tex` changes.

## Title

Auditing File-Level Static Analysis of Agent Workflows: Extraction Fidelity and Policy Applicability

## Abstract

Static analysis of agent workflows depends on two choices that are often left
implicit: whether the extracted graph represents the source, and whether a
policy applies to the workflow being checked. We audit both choices on 922
extracted file-level graphs from public GitHub across LangGraph, CrewAI,
AutoGen, and Google ADK. On a quota-selected 119-graph sample, an LLM-assisted
source audit labels 184 of 186 findings non-actionable; these are exploratory
labels pending independent human validation. Attribution is check-family
dependent: a graph-substitution survival test attributes 68 of 72
non-actionable structural findings to extraction, whereas it attributes 94 of
112 non-actionable human-gate findings to an inapplicable approval policy.
Holding checks fixed and substituting source-reconstructed graphs removes 62
of 184 findings. A declaration-sensitive human-gate rule moves blanket firings
from 113 to 0, but only because mined graphs expose no sensitive bindings. The
reverse audit exposes the consequence: all 12 source-audited human-gate
violations escape the mined pipeline, and a source-reconstructed graph
recovers only one; nine effects occur inside node bodies that the graph
vocabulary does not represent. Moreover, every side-effecting workflow cleared
by both graph checks was cleared by a placebo gate—a node typed human whose
body cannot block. We therefore separate extraction fidelity, policy
applicability, and abstraction coverage, and make safe conditional on an
authored event-complete abstraction; otherwise the analyzer returns
inconclusive. The result is a methodological requirement for agent-workflow
analysis: validate both the recovered model and the applicability of every
policy. All proportions are descriptive of these audited files, not estimates
for executable or deployed workflows.

## TL;DR

In an audit of agent-workflow analysis, structural false alarms track graph
extraction, while human-gate false alarms track policy applicability; misses
arise mainly from effects absent from the graph abstraction.

## Human-entered fields

- Authors and order: **confirm in OpenReview**
- Topics/subject areas: **select and freeze in OpenReview**
- Suggested topic concepts, subject to the live taxonomy: AI safety,
  multi-agent systems, static analysis, software verification
- Conflicts: **complete for every author**
- Concurrent-submission declaration: **author attestation required**
- Ethics declaration: **author attestation required**
- Generative-AI disclosure approval: **author attestation required**
