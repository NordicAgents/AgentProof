# Security Model

## Trust Boundaries
1. **Planner Boundary**: LLM/orchestrator is untrusted.
2. **Execution Boundary**: Only VAC `step()` may trigger side effects.
3. **External Boundary**: APIs/services are untrusted and must be wrapped.

## Reference Monitor Design
- Centralized policy decision point in core engine.
- Complete mediation: every action validated before execution.
- Tamper-evident trace and decision logging.

## Tool Isolation Rules
- Tools run behind wrappers with explicit schemas.
- Least-privilege permissions per tool.
- Side-effect classes declared and audited.
- Optional sandbox profiles for high-risk tools.

## Bypass Prevention
- No direct tool invocation path from orchestration layer.
- Reject unknown action types and unregistered tools.
- Enforce immutable policy bundle hash during run.
- Block execution when monitor enters violation state.

## Attack Surface
- Prompt injection attempts to trigger unsafe actions.
- Malformed/oversized payloads.
- Wrapper misconfiguration.
- Supply-chain compromise of tools/dependencies.
- Replay/tampering of execution traces.

## Assumptions
- Core binaries and policy files are integrity-protected.
- Secrets management is external and correctly configured.
- Operators review and approve policy/spec changes.
