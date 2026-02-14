# Error Handling

## Verification Failure Behavior
When verification fails, no side effects are executed and state is advanced only with a rejection event.

## Rejection Format
```json
{
  "decision": "rejected",
  "rule_id": "email_requires_consent",
  "reason": "Precondition failed",
  "step_index": 12,
  "retryable": false
}
```

## Counterexample Trace Format
For BMC/runtime violations:
- property id
- bound/horizon
- sequence of `(state, action)` pairs
- first violating index
- solver/model metadata

## Retry Logic
- Allowed only for retryable classes (e.g., transient tool errors).
- Retry budget decremented deterministically.
- Retries must preserve idempotency guarantees.

## Escalation Policies
- Soft policy violations: reject + telemetry.
- Hard safety violation: reject + halt.
- Repeated transients beyond threshold: halt + operator escalation.

## Safe Termination Behavior
On terminal fault:
- mark state `halted`
- flush trace/report artifacts
- disable further `step()` execution except administrative recovery path
