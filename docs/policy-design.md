# Policy design

## Goal

Most users should not need to learn LTL. `agentproof.yml` should express common
agent safety controls in reviewable language while compiling to the existing
monitor and graph-product engines.

## Proposed configuration

```yaml
version: 1

framework:
  detect: true
  incomplete_analysis: error

packs:
  - agentproof/destructive-tools
  - agentproof/human-approval

rules:
  - id: production-delete-requires-approval
    description: Production deletion must be approved by a human.
    severity: error
    when:
      tool: delete_production_db
    require:
      preceded_by:
        node_kind: human

  - id: no-shell-after-untrusted-input
    severity: error
    when:
      tool: shell
    forbid_if:
      data_from: user_input

  - id: deployment-must-be-audited
    severity: warning
    when:
      tool: deploy
    require:
      eventually:
        tool: write_audit_log

advanced_rules:
  - id: no-recursive-delete
    ltl: "G !tool:rm_rf"
    on_violation: halt

suppressions:
  - rule: deployment-must-be-audited
    location: workflows/dev_preview.py
    owner: platform-security
    reason: Preview deployments use the central audit proxy.
    expires: 2026-12-31
```

The exact schema will be finalized in
[#20](https://github.com/NordicAgents/AgentProof/issues/20). Data-flow forms such
as `data_from` must remain unavailable until the graph model can represent and
verify provenance soundly.

## Initial policy forms

- forbid a tool, action, decision, or tag;
- require a node or tool before another tool;
- require an eventual or bounded response;
- require human approval before sensitive capabilities;
- restrict tools to agents, routes, or environments;
- limit repeated calls or total tool-call budget;
- detect paths with no exit or no terminating control;
- advanced LTL for policies outside the friendly schema.

## Starter packs

1. **Destructive tools:** filesystem deletion, database mutation, code
   execution, deployment, and credential changes.
2. **Human approval:** payments, external messages, production changes, and
   high-impact MCP calls.
3. **Data handling:** PII, secrets, external egress, and logging requirements.
4. **Operational safety:** call budgets, loop bounds, timeouts, and escalation.
5. **Agentic threats:** excessive agency, tool misuse, insecure handoffs, and
   missing authorization controls.

## Finding contract

Every finding should contain:

- stable rule and finding IDs;
- severity and confidence;
- source location and relevant graph element;
- shortest or clearest witness path;
- policy assumptions and analysis completeness;
- remediation guidance;
- stable fingerprint for baselines and SARIF;
- suppression metadata when applicable.

For example:

```text
AP-HUMAN-001 error: delete_production_db is reachable without approval
Location: src/workflow.py:84
Witness: entry -> triage -> admin_agent -> delete_production_db
Coverage: complete for 12/12 nodes; 1 dynamic condition unresolved
Remediation: insert an approval interrupt before admin_agent
```
