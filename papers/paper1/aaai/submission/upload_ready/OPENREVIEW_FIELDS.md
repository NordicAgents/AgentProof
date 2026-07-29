# OpenReview fields

This is an operator copy/paste aid. Do **not** upload this Markdown file.
Re-sync it if `main.tex` changes.

## Title

Before Verifying Agent Workflows: Auditing Extraction Fidelity and Policy Applicability

## Abstract

Static checks over agent workflows are credible only if the recovered graph
represents the source and the checked policy applies to that workflow. We audit
these prerequisites on 922 extracted file-level graphs from public GitHub
across LangGraph, CrewAI, AutoGen, and Google ADK. On a fixed, nonrandom
119-file audit set, LLM-assisted source review labels 184 of 186 findings
non-actionable; independent human validation is pending, so these labels are
exploratory. A graph-substitution survival test shows why the check families
must remain separate: extraction accounts for 68 of 72 non-actionable
structural findings (66/70 after legacy-key collision exclusion), whereas
policy misspecification accounts for 94 of 112 non-actionable human-gate
findings (84/102 after exclusion). The reverse audit finds a different failure
mode. All 12 source-audited human-gate violations escape the mined pipeline,
and a source-reconstructed graph recovers only one; nine regulated effects
occur inside node bodies outside the graph vocabulary. Every side-effecting
workflow cleared by both graph checks was cleared by a placebo gate—a node
typed human whose body cannot block. These descriptive case-study results do
not estimate prevalence on GitHub or deployed systems. They support a
methodological requirement: validate extraction fidelity, policy applicability,
and abstraction coverage separately. Accordingly, no mined graph receives a
safe verdict; sound monitor elimination remains only a conditional implication
for authored event-complete abstractions.

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
