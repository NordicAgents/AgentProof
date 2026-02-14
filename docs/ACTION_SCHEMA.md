# Action Schema

## Action Format
```json
{
  "schema_version": "1.0",
  "action_type": "SendEmail",
  "tool_name": "email.send",
  "input": {"to": "user@example.com", "subject": "Hello", "body": "..."},
  "metadata": {
    "proposal_id": "uuid",
    "proposed_by": "orchestrator",
    "timestamp": "2026-01-01T00:00:00Z",
    "idempotency_key": "optional"
  }
}
```

## Tool Call Structure
- `tool_name`: registered wrapper identifier.
- `input`: validated against tool input schema.
- `expected_effects`: optional declared effect classes.
- `cost_hint`: optional estimator for preflight budget checks.

## Validation Rules
- `schema_version` must be supported.
- `action_type` must map to known schema.
- `tool_name` must be registered and enabled.
- `input` must satisfy JSON schema constraints.
- Metadata must include stable correlation identifiers.

## Versioning Strategy
- Semantic versioning for schema (`major.minor`).
- Major bump for breaking field/type changes.
- Minor bump for backward-compatible additions.

## Schema Evolution Policy
- Additive fields must be optional with defaults.
- Deprecated fields supported for one major cycle.
- Migration transforms must be deterministic and auditable.
