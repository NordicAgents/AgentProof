# Limitations

## What Cannot Be Formally Verified
- Internal reasoning correctness of LLMs.
- Truthfulness/factuality of generated content.
- Behavior of external systems beyond declared contracts.

## Probabilistic Limitations
- Model outputs are inherently probabilistic pre-verification.
- Statistical risk remains for proposal quality and coverage.

## Bounded Verification Constraints
- Bounded model checking proves properties only within chosen horizon `k`.
- Large/complex bounds may be computationally expensive.

## External System Assumptions
- APIs/services must honor documented semantics.
- Network and dependency failures can violate liveness assumptions.

## Known Failure Modes
- Mis-specified policies causing false allow/reject outcomes.
- Wrapper metadata drift from true tool behavior.
- Incomplete labeling for info-flow controls.
- Operational misconfiguration (timeouts, version mismatch).
