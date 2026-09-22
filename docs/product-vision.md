# Product vision

## Positioning

AgentProof is policy-as-code for agent tool safety. It finds unsafe tool paths
before deployment, explains the path that violates policy, and can enforce the
same policy at runtime through framework adapters.

The initial product promise is deliberately narrow:

> When a code change introduces a sensitive tool or a path that bypasses a
> required control, AgentProof identifies the source, shows a witness path, and
> tells the developer how to fix it.

## Target users

The first users are teams building tool-using Python agents with explicit
workflow structure:

- application engineers who need fast feedback in pull requests;
- security engineers who need reviewable policies and evidence;
- platform teams that support multiple agent frameworks;
- researchers who need reproducible graph and temporal analyses.

The first framework should be exceptionally reliable before support expands.
LangGraph is the recommended initial focus, followed by the OpenAI Agents SDK
for static extraction, runtime traces, and tool-call enforcement.

## North-star workflow

```console
$ pip install agentproofx
$ agentproof init
Detected: LangGraph
Created: agentproof.yml

$ agentproof check .
ERROR prod-delete-needs-approval
src/workflow.py:84 exposes delete_production_db without prior approval
Witness: entry -> triage -> admin_agent -> delete_production_db
Fix: add an approval interrupt before admin_agent or suppress with an owner,
reason, and expiry.
```

The same policy should be usable as a runtime guard:

```python
guard = agentproof.load("agentproof.yml")
secured_tool = guard.wrap(delete_production_db)
```

## Product boundaries

AgentProof can verify graph topology, declared tool capabilities, event order,
approval placement, and supported temporal properties. It can also compare
observed traces with the static model.

AgentProof does not automatically prove:

- that prompts cannot be manipulated;
- that tool implementations are secure;
- that tool arguments or returned data are safe unless modeled;
- that an extractor discovered every dynamic behavior;
- that an LLM will follow an intended business goal.

Reports must therefore distinguish `verified`, `violated`, `unknown`, and
`incomplete` outcomes. A proof is scoped to the analyzed model, policy, and
declared assumptions.

## Product principles

1. **Actionability over finding count.** Every finding needs a witness, source
   location, severity, explanation, and remediation.
2. **Uncertainty is output.** Unsupported dynamic behavior must be reported,
   not silently replaced with a convenient graph.
3. **One policy, two modes.** Static checking and runtime enforcement share the
   same policy semantics and conformance tests.
4. **Safe incremental adoption.** Baselines and expiring suppressions let teams
   adopt the tool without ignoring new risk.
5. **Evidence before claims.** Framework versions, extractor fidelity, false
   positives, and known limitations are published.
6. **Local-first operation.** Core analysis works without sending source,
   prompts, traces, or tool payloads to an external service.

## Non-goals for the first three milestones

- a hosted dashboard before the CLI and findings are trusted;
- broad support for every agent framework;
- LLM-generated policies enabled by default;
- generic risk scores without paths and evidence;
- replacing sandboxing, authorization, secrets management, or human review.
