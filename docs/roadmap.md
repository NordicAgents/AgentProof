# Product roadmap

The umbrella tracker is
[Epic #30](https://github.com/NordicAgents/AgentProof/issues/30). Delivery is
split into three milestones so that usability, trust, and operational adoption
arrive in that order.

## v0.4 — Five-minute CI adoption

[Milestone](https://github.com/NordicAgents/AgentProof/milestone/1), due
2026-10-30.

Outcome: a supported repository can go from installation to an actionable
pull-request finding in under five minutes.

| Issue | Deliverable |
|---|---|
| [#19](https://github.com/NordicAgents/AgentProof/issues/19) | `init`, `check`, and `explain` CLI commands with framework auto-detection |
| [#20](https://github.com/NordicAgents/AgentProof/issues/20) | Versioned YAML policy schema and starter policy pack |
| [#21](https://github.com/NordicAgents/AgentProof/issues/21) | SARIF output and reusable GitHub Action |

## v0.5 — Trustworthy analysis and enforcement

[Milestone](https://github.com/NordicAgents/AgentProof/milestone/2), due
2026-11-27.

Outcome: reports expose coverage and uncertainty, one extractor has measured
high fidelity, and policies can be enforced in supported runtimes.

| Issue | Deliverable |
|---|---|
| [#22](https://github.com/NordicAgents/AgentProof/issues/22) | Source provenance, extraction coverage, and explicit unknowns |
| [#23](https://github.com/NordicAgents/AgentProof/issues/23) | Versioned LangGraph compatibility matrix and extractor benchmark |
| [#24](https://github.com/NordicAgents/AgentProof/issues/24) | OpenAI Agents SDK graph extraction and trace ingestion |
| [#25](https://github.com/NordicAgents/AgentProof/issues/25) | LangGraph and OpenAI runtime enforcement adapters |

## v0.6 — Production adoption

[Milestone](https://github.com/NordicAgents/AgentProof/milestone/3), due
2026-12-31.

Outcome: teams can adopt incrementally, use standard security packs, compare
runtime behavior with static models, and review public benchmark evidence.

| Issue | Deliverable |
|---|---|
| [#26](https://github.com/NordicAgents/AgentProof/issues/26) | Baselines, diff-only scanning, and expiring suppressions |
| [#27](https://github.com/NordicAgents/AgentProof/issues/27) | OWASP agentic-risk and MCP authorization policy packs |
| [#28](https://github.com/NordicAgents/AgentProof/issues/28) | Trace replay and static/runtime drift detection |
| [#29](https://github.com/NordicAgents/AgentProof/issues/29) | Public benchmark, vulnerable demo, and design-partner release gate |

## Release gates

| Measure | Target by v0.6 |
|---|---|
| Median install-to-first-result time | Under five minutes |
| Edge and tool recall | At least 90% for explicitly supported versions |
| Finding presentation | Stable, source-mapped SARIF with witness paths |
| Policy consistency | Shared static/runtime conformance suite |
| External use | At least five repositories running AgentProof in CI |
| Safety claims | Scoped to measured model and trace coverage |

## Sequencing rules

- CLI output depends on stable finding and exit-code contracts.
- SARIF depends on source provenance; the first version may use workflow entry
  locations until edge-level provenance is available.
- Runtime adapters must reuse policy semantics rather than reimplement rules.
- New framework support requires a compatibility matrix and benchmark fixtures.
- A milestone is complete only when its user-visible exit criterion is met, not
  merely when its issues are closed.
