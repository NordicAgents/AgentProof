# Paper 2 — AgentProof-CEGAR

## Proof-Carrying Repairs for Tool-Using Agent Programs

**Working thesis.** A conservative may/must model of a tool-using agent,
refined with concrete counterexamples and coupled to verifier-checked repair,
can eliminate false safety claims, repair policy violations more reliably than
LLM-only or test-only agents, and route only unresolved behavior to runtime
oversight.

The paper is not about another tool-call interceptor. Its central result must be
an end-to-end method that produces one of three calibrated outcomes:

- **SAFE:** a small independent checker validates a certificate that all
  executions represented by the supported abstraction satisfy the policy;
- **UNSAFE:** the system returns a feasible violating trace and source-level
  witness;
- **UNKNOWN:** unsupported or imprecisely modeled behavior is reported
  explicitly and routed to a runtime guard, human approval, or learned judge.

For an unsafe program, AgentProof-CEGAR searches a finite repair grammar,
optionally uses an LLM as an untrusted patch proposer, re-extracts and verifies
the patched program, runs regression tests, and emits a checked certificate.
The guarantee comes from the abstraction and certificate checker, not from the
LLM.

## Why this is the flagship

Recent systems already intercept tool calls, enforce temporal constraints,
translate natural-language policies, and demonstrate low-overhead runtime
guarding. This paper therefore does **not** claim novelty for:

- compiling a policy into a DFA;
- blocking or rewriting a tool call;
- translating English rules into a policy DSL;
- building a cross-framework dependency graph;
- evaluating only on AgentDojo or tau-bench; or
- showing that deterministic checks are faster than an LLM judge.

The contribution is the composition of conservative program abstraction,
tri-valued verification, counterexample-guided refinement, minimal source
repair, and independently checked safety certificates. Runtime shielding is a
fallback for residual UNKNOWN behavior, not the headline.

## Relationship to Paper 1

Paper 1 provides the empirical motivation: topology defects appear rare in the
current sample, while extraction fidelity and effect-level policy modeling are
the central obstacles to credible verification. Paper 2 turns those limitations
into the research problem rather than presenting the existing extractor as a
sound verifier.

The flagship may reuse the current policy compiler, product checker, framework
extractors, corpus infrastructure, and runtime monitor as prototypes. The new
soundness and repair claims require a new may/must IR, independent semantic
oracle, refinement loop, source patchers, and certificate checker. If Paper 1 is
under review or published, Paper 2 must cite it, disclose reused data/code, and
keep its benchmark, experiments, and central claims scientifically distinct.

The implementation priority is explicit: first make uncertainty visible and
actionable, then add effect-sensitive modeling, and only then build CEGAR and
repair on top. The flat graph remains a compatibility and visualization view;
it is not the proof abstraction. Unknown dispatch, hidden tool calls, guessed
connectivity, incomplete failure semantics, and unmodeled parallelism must
produce `UNKNOWN`, never silently support `SAFE`.

## Research questions

1. **Sound modeling:** Can a framework-aware may abstraction contain every
   concrete effect trace in an explicitly supported Python-agent subset without
   becoming too imprecise to verify?
2. **Calibrated diagnosis:** Can CEGAR reduce UNKNOWN results while preserving
   zero observed false SAFE certificates?
3. **Verified repair:** Does verifier-guided repair produce policy-safe,
   regression-passing patches more often than strong LLM-only, test-only, and
   solver-only baselines on held-out repositories?
4. **Generalization:** Do results hold across repositories, framework versions,
   policy families, and at least one unseen framework or version?
5. **Static/runtime partition:** Can certificates reduce expensive runtime
   judging or human approval at matched safety and benign utility?
6. **Actionability:** Do source-level witnesses and structured `UNKNOWN`
   explanations help developers resolve risks more accurately than graph-only
   reports?

## Formal contract

Let `P` be an agent program, `Tr(P)` its concrete effect traces, `M(P)` a
may/must abstract transition system, and `A_phi` a bad-prefix automaton for a
safety policy `phi`. The supported front-end must establish:

```text
Tr(P) subseteq Tr_may(M(P))
Tr_must(M(P)) subseteq Tr(P)
```

AgentProof-CEGAR reports SAFE only when no violation is reachable in the may
product `M_may(P) x A_phi`. A patch is certified only after re-extraction,
product checking, regression testing, and validation by a deliberately small
certificate checker. The paper will state the supported language subset and
trusted computing base next to every guarantee.

The headline theory is restricted to finite-trace safety properties such as
authorization, required-before constraints, confirmation before external
effects, bounded quotas, argument restrictions, identity consistency, and
forbidden effect sequences. Liveness and eventual completion are diagnosis or
termination-time properties, not veto-enforcement guarantees.

## System at a glance

```text
Python agent program + policy
              |
              v
framework semantic front-end + source provenance
              |
              v
may/must effect transition system
              |
              v
policy product ------> feasible witness / sandbox concretization
              |                         |
       SAFE / UNSAFE / UNKNOWN <--- CEGAR refinement
              |
              v
repair grammar + optimizer + untrusted LLM proposer
              |
              v
source patch -> re-extract -> verify -> regression tests -> certificate
              |
              v
residual UNKNOWN -> formal runtime guard / approval / LLM judge
```

The public API should expose the same three-way contract directly:

```text
SAFE     = no bad state is reachable in the conservative may model
UNSAFE   = a feasible violating trace and source witness are returned
UNKNOWN  = unsupported or imprecisely modeled behavior is identified
```

## Intended contributions

1. A provenance-carrying may/must transition system for the effect, authority,
   argument, identity, state, and data-flow behavior of tool-using agents.
2. Tri-valued policy verification with structured UNKNOWN explanations,
   source-level concrete witnesses, and
   counterexample-guided refinement rather than unsound binary SAFE results.
3. Proof-carrying repair that combines a finite edit grammar, cost-aware
   optimization, optional LLM proposals, source patching, re-analysis, and an
   independent certificate checker.
4. **AP-RepairBench**, a repository-split benchmark of human-confirmed defects,
   policy-breaking mutations in real workflows, official examples, and
   adversarial dynamic cases, with runnable ground truth and benign regression
   tasks.
5. An end-to-end evaluation of repair success, false-certificate risk,
   generalization, developer usefulness, and the reduction in runtime oversight
   achieved by routing only UNKNOWN behavior to expensive guards.

## Threat model and limits

The planner, retrieved content, tool outputs, and LLM repair proposer may be
wrong or adversarial. Policies, tool schemas, framework semantics, dependency
versions, the certificate checker, and the execution sandbox are trusted and
versioned. Calls that bypass all analyzed and monitored boundaries are outside
the guarantee and must be reported as unsupported rather than silently ignored.
Regression tests demonstrate preservation of the declared test suite; they do
not prove full preservation of human intent.

## Venue strategy

The primary goal is a genuinely mature flagship submission, not a deadline-led
submission. **NeurIPS 2027** is the planning target because it provides time for
benchmark construction, theory, multi-framework evaluation, and a human study.
Use **ICML 2027** only if its confirmed deadline leaves at least six weeks after
the benchmark and main results are frozen and the paper has a strong learned or
LLM-repair result. If the strongest contribution remains program analysis and
automated repair, target **ICSE, FSE, or ASE** rather than forcing an ML framing.
All venue dates and concurrent-submission rules must be rechecked before
submission.

See [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md) for the implementation roadmap,
benchmark protocol, experiments, statistical plan, risks, and submission gates.
