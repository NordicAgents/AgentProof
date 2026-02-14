# Tool Wrapper Guide

## How to Register Tools
1. Implement wrapper interface (`validate`, `execute`, `postcheck`).
2. Provide metadata bundle.
3. Call `register_tool()` at startup.
4. Run conformance checks before enabling in production.

## Required Metadata
- Tool name and version
- Input/output schemas
- Permission requirements
- Side-effect class (`read`, `write`, `external_network`, etc.)
- Cost model
- Idempotency behavior

## Preconditions / Postconditions
- Preconditions: must hold before execution (state, permissions, budgets).
- Postconditions: validate output shape and declared effect summary.
- Violations convert to rejection/escalation events.

## Cost Model Integration
- Static cost: fixed per invocation.
- Dynamic cost: function of validated input size/operation class.
- Actual cost must be returned for budget reconciliation.

## Security Constraints
- No raw secret exposure in logs.
- Enforce outbound allowlists for network tools.
- Disallow shell/exec by default unless explicitly approved.
- Ensure deterministic error classes for policy handling.
