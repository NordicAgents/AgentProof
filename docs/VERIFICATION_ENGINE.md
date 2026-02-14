# Verification Engine

## SMT Solver Usage
- Primary backend: SMT solver (e.g., Z3-compatible API).
- Queries generated per proposed step and optional k-step bounded analysis.
- Solver runs with deterministic options (seed, timeout, tactic profile pinned).

## Constraint Encoding
- Action schema -> typed sorts and field constraints.
- Permissions/preconditions/invariants -> boolean formulas.
- Budgets -> linear arithmetic constraints.
- Info-flow -> label lattice and sink admissibility constraints.
- Temporal guards -> monitor state consistency constraints.

## Bounded Model Checking Strategy
- Unroll transition relation `k` steps.
- Assert property negation to search counterexample.
- If SAT: extract minimal counterexample trace candidate.
- If UNSAT within bound: property holds for explored horizon.

## Runtime Monitoring Algorithm
- Maintain monitor automata state per temporal rule.
- On each event append, compute next automata states.
- If accepting-violation state reached, emit violation and enforce policy (halt/escalate).

## Performance Characteristics
- Step verification scales with rule count and formula complexity.
- Budget and invariant checks are typically O(r) before solver call.
- Temporal monitoring is O(t) per event where `t` = active temporal rules.
- BMC complexity grows exponentially with bound and branching assumptions.

## Known Limitations
- Bounded proofs do not imply unbounded correctness.
- External side effects cannot be fully modeled when third-party systems are opaque.
- Rich string and regex constraints can degrade solver performance.
- Large traces may require checkpointing for efficient replay.
