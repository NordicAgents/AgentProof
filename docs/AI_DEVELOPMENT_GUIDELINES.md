# AI Development Guidelines

## Purpose
Ensure AI assistance accelerates delivery without degrading formal assurance.

## Mandatory Rules
- No auto-generated core verification logic without human review and approval.
- All formal encodings (SMT/temporal) must be manually validated.
- Deterministic replay tests are required for verification engine changes.
- AI-generated specs must pass lint, compile, and semantic review.

## Review Expectations
- Every safety-critical change includes rationale and threat impact.
- At least one reviewer validates logical equivalence of encoding changes.
- Counterexample quality must be checked for readability and reproducibility.

## Allowed AI Usage
- Drafting docs and non-critical boilerplate.
- Generating test scaffolding reviewed by maintainers.
- Suggesting refactors that preserve formal semantics.

## Disallowed AI Usage
- Blind acceptance of solver encodings.
- Auto-merging policy updates affecting production guarantees.
- Introducing nondeterministic behavior without explicit design approval.
