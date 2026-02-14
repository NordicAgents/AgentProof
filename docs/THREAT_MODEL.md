# Threat Model (STRIDE)

## Scope
VAC execution boundary, wrapper layer, policy compiler, and integration adapters.

## STRIDE Summary
- **Spoofing**: forged proposals/tool identities.
  - Mitigation: signed metadata, authenticated callers.
- **Tampering**: trace/state/spec modification.
  - Mitigation: immutable logs, hash chaining, integrity checks.
- **Repudiation**: denial of unsafe action origin.
  - Mitigation: correlation IDs, auditable decision reports.
- **Information Disclosure**: secret leakage via tool outputs/logs.
  - Mitigation: info-flow labels, redaction, sink controls.
- **Denial of Service**: oversized proposals/solver exhaustion.
  - Mitigation: quotas, payload limits, solver timeouts.
- **Elevation of Privilege**: bypass wrappers/policy checks.
  - Mitigation: complete mediation in `step()`, least privilege.

## Residual Risk
Residual risks are tracked in security reviews and reduced via hardened wrappers, continuous fuzzing, and operational controls.
