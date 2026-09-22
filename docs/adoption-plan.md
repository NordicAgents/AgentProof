# Adoption plan

## Five-minute experience

The shortest route to adoption is a local CLI that becomes a pull-request
check without requiring a service account or hosted control plane.

1. Install `agentproofx` or use the GitHub Action.
2. Run `agentproof init` to detect the framework and create a configuration.
3. Run `agentproof check .` locally.
4. Commit `agentproof.yml` and the optional findings baseline.
5. Review source-mapped findings in the pull request.

The GitHub integration should emit SARIF 2.1.0 because GitHub can render
third-party static-analysis findings as code-scanning alerts and pull-request
annotations. See GitHub's
[SARIF documentation](https://docs.github.com/en/code-security/concepts/code-scanning/sarif-files).

## Static and runtime integrations

Static analysis earns early feedback; runtime integration provides actual
enforcement and evidence. The planned adapters should use framework-native
hooks:

- LangGraph interrupts for approval and resumption;
- OpenAI Agents SDK tool guardrails for pre-execution decisions;
- OpenAI trace processors for observed tool calls, handoffs, and guardrails;
- later AutoGen intervention handlers and equivalent framework mechanisms.

The policy engine remains framework-independent. Adapters translate native
objects and events into the shared graph, event, decision, and finding models.

## Trust and false-positive controls

- Report analysis coverage and unknown constructs beside every verdict.
- Default pull-request checks to new or worsened findings after a baseline is
  accepted.
- Require suppression owner and reason; support expiry.
- Rank findings using measured rule precision, not opaque risk scores.
- Provide a strict mode that fails closed on incomplete extraction.
- Publish framework-version compatibility and fidelity results.

These controls matter because a technically correct finding that lacks source
context or arrives with many extraction artifacts will still be ignored.

## Demonstration strategy

Maintain one deliberately vulnerable application that contains:

- a destructive tool reachable without approval;
- a response obligation that is not fulfilled;
- a dynamic route the extractor must mark unknown;
- an observed runtime tool absent from the static model;
- a fixed version showing the expected remediation.

Use it for the README, CLI snapshots, GitHub Action, SARIF annotations, runtime
guard demo, and release smoke test.

## Distribution

- Publish a reusable GitHub Action and copyable workflow.
- Contribute examples to supported framework template repositories.
- Keep the core local and dependency-light.
- Publish compatibility and benchmark badges only when backed by reproducible
  artifacts.
- Recruit design partners before building a hosted dashboard.

## Metrics

Track product usefulness rather than repository activity alone:

- time from install to first actionable finding;
- extraction node, edge, and tool precision/recall;
- actionable findings versus suppressions;
- new findings caught on pull requests;
- static/runtime drift found in real traces;
- active external repositories and repeated CI use;
- policy packs enabled and rules customized.

## Deferred work

Until the first three milestones are complete, defer a hosted dashboard,
organization management, broad framework expansion, automatic LLM-authored
policies, and a generic numeric risk score. Those features amplify the product
only after its model and findings are trusted.
