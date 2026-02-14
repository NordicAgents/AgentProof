# Test Strategy

Verification software requires layered, adversarial testing.

## Unit Tests
- Schema validation (valid/invalid action payloads).
- Invariant checking (positive + violating cases).
- SMT encoding sanity (expected SAT/UNSAT fixtures).

## Property-Based Testing
- Randomized action/state generation under schema constraints.
- Check transition determinism and invariant preservation.

## Counterexample Generation Tests
- Ensure violating specs produce minimal, reproducible traces.
- Validate counterexample serialization and replayability.

## Deterministic Replay Tests
- Re-run recorded traces with stubbed tool outputs.
- Assert decision stream and final state hash equality.

## Adversarial Tests
- Prompt-injection-shaped proposals.
- Payload fuzzing (deep nesting, unicode, oversized fields).
- Permission escalation and wrapper bypass attempts.

## CI Recommendations
- Fast deterministic suite on every PR.
- Nightly bounded model checks at larger horizons.
- Artifact retention for failed verification cases.
