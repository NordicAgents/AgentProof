# Experiment Plan — AgentProof-CEGAR

**Updated:** 2026-07-14
**Working title:** *AgentProof-CEGAR: Proof-Carrying Repairs for Tool-Using
Agent Programs*
**Primary planning target:** NeurIPS 2027; ICML 2027 only if all readiness gates
fit its confirmed schedule; ICSE/FSE/ASE if the contribution is predominantly
program analysis and repair.

## 1. Decision and contribution boundary

Paper 2 is no longer a standalone compiled-shield paper. Runtime interception,
temporal-policy compilation, English-to-policy generation, tau-bench-only
evaluation, and low-latency deterministic checks already have close prior art.
They remain useful components and baselines, but they cannot carry the novelty
claim.

The flagship question is:

> Can a conservative model of a tool-using agent distinguish definite from
> possible policy violations, refine uncertain counterexamples, and synthesize
> a minimal source repair with a machine-checkable safety certificate—while
> routing only unresolved behavior to runtime oversight?

The paper succeeds only if the complete system improves held-out repair success
over the strongest LLM-only baseline without producing a false certificate. A
large implementation with only an extraction or latency result is insufficient.

### 1.1a Product direction and build order

AgentProof-CEGAR will be an effect-aware, tri-valued analyzer rather than a
larger topology checker. The build order is: (1) expose `SAFE`/`UNSAFE`/
`UNKNOWN` with unsupported-feature explanations; (2) add source-level witnesses
and effect/argument/authority annotations; (3) model exceptions, retries,
cancellation, parallel branches, callbacks, and nested agents conservatively;
(4) add typed policies and an independent evaluator; and (5) implement CEGAR,
proof-carrying repair, and certificate checking. The flat `AgentGraph` remains a
compatibility and visualization format and must not erase uncertainty.

### 1.1 Relationship to Paper 1

Paper 1 is the motivating base-rate and extraction-fidelity study. Paper 2 may
reuse its infrastructure, but it must not silently reuse experimental evidence
as a new contribution. Record shared repositories, policies, annotations, and
code in the artifact manifest; cite Paper 1 when permitted; and maintain a
separate flagship benchmark, research questions, and primary outcomes. Check
concurrent-submission and substantial-overlap rules before submitting either
paper.

## 2. Scope and threat model

### 2.1 Trusted components

- deployer-approved formal policies and tool schemas;
- pinned framework semantics for the explicitly supported subset;
- parser, abstract domains, policy compiler, product checker, sandbox, and
  independent certificate checker;
- benchmark manifests, containers, and regression tests.

### 2.2 Untrusted components

- LLM planner and LLM repair proposer;
- user prompts, retrieved content, tool outputs, and indirect instructions;
- candidate source patches until independently checked;
- dynamic behavior that the front-end cannot model precisely.

### 2.3 Guaranteed and non-guaranteed behavior

The guarantee covers concrete effect traces contained by the declared may
abstraction. Unknown dispatch, reflection, native extensions, direct system or
network calls, dynamically loaded code, and unmediated subagents must receive a
conservative summary or an explicit UNKNOWN result. They must never disappear
from the model.

The first formal scope is finite-trace safety:

- authorization and capability constraints;
- authentication or approval required before an external effect;
- bounded quotas and retry limits;
- argument, amount, recipient, path, and identity constraints;
- forbidden effect sequences;
- conservative source-to-sink/data-label policies.

Liveness, eventual completion, and unbounded response obligations are evaluated
as diagnostic or termination-time properties. Blocking cannot guarantee them.

## 3. Formal model and proposed results

Let program `P` induce concrete effect traces `Tr(P)`. Let `M(P)` be a may/must
agent transition system and `A_phi` recognize bad prefixes of safety policy
`phi`. For the supported language subset, establish:

```text
Tr(P) subseteq Tr_may(M(P))
Tr_must(M(P)) subseteq Tr(P)
```

The analyzer returns:

- **SAFE:** no bad state is reachable in `M_may(P) x A_phi`;
- **UNSAFE:** a candidate violation is concretely feasible and reproducible;
- **UNKNOWN:** the candidate depends on imprecise or unsupported behavior.

For UNKNOWN, CEGAR checks path feasibility using framework semantics, symbolic
guards, and sandboxed executions. A spurious path refines the abstraction; a
feasible path becomes an UNSAFE witness. If refinement cannot soundly decide,
the result remains UNKNOWN.

### 3.1 Target theorem set

1. **Abstraction soundness.** Every concrete effect trace in the supported
   subset is represented by the may abstraction.
2. **Certificate soundness.** If the independent checker accepts a SAFE
   certificate, every covered concrete trace satisfies the safety policy.
3. **Repair soundness.** A certified patch satisfies the same policy under the
   stated abstraction assumptions and passes the declared regression suite.
4. **Relative minimality.** The selected repair has minimum configured cost
   among candidates in the finite repair grammar explored by the optimizer.
5. **Conditional CEGAR termination.** For a finite abstraction lattice and
   bounded refinement procedure, analysis terminates with SAFE, UNSAFE, or an
   explicit UNKNOWN/unsupported result.

Do not claim complete Python verification, full intent preservation, absolute
minimality, or liveness enforcement. State assumptions beside each theorem and
put full proofs in the appendix.

## 4. System work

### 4.1 May/must effect IR

Replace the flat graph as the analysis core while retaining it as a compatibility
view. Each node records:

- stable ID, source span, and extraction provenance;
- framework object, call target, and tool schema;
- effect kind: read, write, execute, communicate, financial, delete, or none;
- abstract argument values and state predicates;
- principal, authority, user/session identity, and capability;
- input/output data labels;
- path guards, possible exceptions, cancellation, and abort behavior;
- modeling confidence and unsupported features.

Each edge records modality (`must`, `may`, or `unknown`), control kind (direct,
conditional, loop, parallel, exception, callback, or dynamic dispatch), guard,
source span, framework rule, and refinement history. Cross-event correlations
must not be destroyed merely to obtain a convenient graph.

The IR must preserve proof eligibility: unknown dispatch, direct calls that
bypass declared tools, incomplete schemas, unmodeled exceptions, and unresolved
parallel or nested-agent behavior become explicit unsupported facts. Diagnosis
may use over-approximations, but `SAFE` is forbidden when the relevant region is
outside the declared abstraction contract.

### 4.2 Framework semantic front-ends

Implement LangGraph first, then AutoGen, CrewAI, and ADK if the correctness
gates remain satisfied. Each front-end needs:

- documented supported syntax and pinned framework versions;
- exact rules for declared nodes, tools, routers, state updates, and exits;
- conservative summaries for aliases, callbacks, hidden tool calls, parallel
  paths, exceptions, and dynamic dispatch;
- source-to-IR provenance and an instrumented runtime trace adapter;
- tests derived from official framework semantics and version changes.

### 4.3 Policy semantics

Build a typed recursive policy AST with argument, state, identity, authority,
and data-label predicates. Keep a slow direct finite-trace evaluator independent
of the optimized compiler. Classify each policy as shield-enforceable safety,
termination-time checkable, or unsupported.

Natural-language policy translation is an untrusted front-end: type-check tool
and state references, generate distinguishing traces between candidate meanings,
and require human approval when ambiguity remains. Compilability alone is not a
quality metric.

Initial policies should prioritize authorization before effects, approval before
irreversible actions, least privilege, argument/path restrictions, identity
consistency, data-flow labels, and retry or quota limits.

### 4.4 CEGAR and concretization

- reconstruct a source-level counterexample from the product;
- symbolically check branch and state feasibility;
- replay candidates in a pinned sandbox with deterministic fixtures;
- refine aliases, argument domains, guards, framework summaries, or correlations;
- preserve refinement provenance for diagnosis and certificates;
- return UNKNOWN on timeouts or unsupported behavior rather than SAFE.

Every candidate witness should include the product path, policy state, branch
assumptions, tool arguments, provenance, and source spans. A possible path is
not an `UNSAFE` verdict until concretization or a trusted semantic argument
establishes feasibility.

### 4.5 Proof-carrying repair

Start with a finite, framework-mappable edit grammar:

1. insert confirmation or human approval before an effect;
2. add or strengthen a router guard;
3. restrict an agent's tool binding or capability;
4. move a tool to a least-privilege executor;
5. add authentication/identity state and a precondition;
6. add a sanitizer or explicit declassifier between source and sink;
7. repair a dead end, bypass, or incorrect exit;
8. bound a loop or retry count;
9. insert preview/commit or transactional boundaries;
10. route unresolved behavior to approval or deny-by-default.

Use a published weighted cost model:

```text
cost = changed_lines
     + lambda_1 * added_approvals
     + lambda_2 * lost_capability
     + lambda_3 * added_latency
     + lambda_4 * residual_unknown_behavior
```

Compare solver-generated candidates, LLM-generated candidates, and their
combination. Every patch is applied to source, re-extracted, verified, tested,
and checked. The LLM never belongs to the trusted computing base.

### 4.6 Certificate checker

Implement a small checker with fewer dependencies than the analyzer. A
certificate records program and policy hashes, dependency versions, supported
semantics, abstract states/transitions, product result, assumptions, repair cost,
and regression manifest. Test it independently with malformed certificates,
compiler mutations, differential oracles, and property-based trace generation.

### 4.7 Residual runtime enforcement

Runtime shielding is used only after static partitioning:

```text
SAFE effect      -> execute without an expensive judge
UNSAFE effect    -> deny, repair, or require explicit approval
UNKNOWN effect   -> deterministic runtime guard, human approval, or LLM judge
```

The runtime layer must mediate all claimed tool boundaries and report bypasses.
Measure complete-mediation failures, parallel calls, retries, nested agents,
argument rewriting, policy disclosure, and denial-of-service/retry loops. Do
not present low DFA latency as a primary contribution.

Provide CLI/CI integration with JSON and SARIF output, source-linked findings,
graph visualization, and a diff-aware mode. Reports must answer both “why
unsafe?” and “why not provably safe?”. Runtime enforcement is reserved for the
explicit `UNKNOWN` region.

## 5. AP-RepairBench

Target approximately **240 independently validated repair tasks**, subject to
available real defects and annotation quality. Adjust the number of synthetic
tasks so the final total remains near 240 rather than capping real defects:

| Slice | Target | Purpose |
|---|---:|---|
| Human-confirmed real defects | 20+ sought | Ecological validity; always reported separately |
| Real workflows with policy-breaking mutations | up to 120 | Controlled policy and repair coverage in realistic code |
| Official framework examples with semantic mutations | up to 40 | Exact, version-pinned runtime ground truth |
| Adversarial/dynamic programs | up to 60 | Aliases, callbacks, parallelism, exceptions, nested agents, reflection |

If fewer real defects are found, report the actual count; never relabel mutations
as real defects. Mutation operators must be fixed from an independently reviewed
taxonomy before final evaluation.

Each task requires:

- runnable source and pinned container/dependencies;
- natural-language requirement and authoritative formal policy;
- defect category, feasible violating trace, and expected effect semantics;
- benign regression tasks and utility measurements;
- at least one human patch without assuming it is uniquely correct;
- two-person validation for test data and adjudication of disagreements;
- repository/license provenance, disclosure status, and redistribution decision.

### 5.1 Split and leakage discipline

- Split by repository, never by file, trace, or mutation.
- Place forks and structurally near-duplicate projects in one split.
- Reserve framework-version and framework holdouts for out-of-distribution tests.
- Do not allow evaluation models to retrieve the gold issue or patch.
- Freeze policies before held-out attacks and mutations are generated.
- Report public-model contamination risk and benchmark exclusions.
- Keep real, mutated, official-example, and adversarial results separate.

## 6. Baselines

### 6.1 Extraction and verification

- current AgentProof flat AST extraction;
- framework-native/instrumented runtime traces;
- AgentFlow when a faithful artifact comparison is possible;
- a generic Python static baseline such as CodeQL or an appropriate call graph;
- test-suite-only dynamic monitoring;
- single may-only or must-only graph variants.

### 6.2 Repair

- no repair;
- one-shot frontier LLM with source and policy;
- LLM with tests and concrete witness;
- iterative LLM with test feedback but no formal verifier;
- LLM using the old under-approximating verifier;
- solver-only finite-grammar repair;
- full LLM proposal + CEGAR + optimizer + certificate;
- human reference patch.

Use at least one strong open-weights model and two competitive model families
for final LLM repair experiments, subject to reproducibility and cost. Freeze
prompts and decoding settings before the final sweep.

### 6.3 Residual runtime policy

- unrestricted execution and prompt-only policy;
- AgentSpec or another deterministic rule engine;
- Agent-C when its artifact and license permit a faithful comparison;
- a learned or LLM-based policy judge;
- runtime guard on every effect;
- AgentProof static partition + guard/judge only for UNKNOWN.

Do not rank methods with materially different threat models as though they were
direct substitutes; use separate tables where necessary.

## 7. Experiments and go/no-go gates

### E0 — Semantic conformance

**Question:** Does the implementation match the declared policy semantics?

- differential tests against the direct finite-trace evaluator and an
  established library where applicable;
- exhaustive short traces and property-based random traces;
- compiler mutation testing and malformed-certificate tests.

**Gate:** zero known mismatches for the supported grammar; unsupported syntax
fails explicitly.

### E1 — Conservative extraction

**Question:** Does the may abstraction contain concrete effects without becoming
uselessly dense?

Measure node/edge/effect recall, concrete trace containment, unknown-edge mass,
graph blowup, and analysis time against human models, official semantics, and
instrumented executions.

**Gate:** effect/tool recall 1.00 on the supported benchmark subset; lower 95%
confidence bound for may-edge recall at least 0.95; explicit UNKNOWN elsewhere.

### E2 — Tri-valued diagnosis and CEGAR

**Question:** Are SAFE, UNSAFE, and UNKNOWN calibrated, and does refinement remove
spurious uncertainty?

Measure false SAFE count, UNSAFE precision/recall, concrete-witness validity,
UNKNOWN rate before/after refinement, refinements, and timeouts.

**Gate:** zero false SAFE certificates in the benchmark, UNSAFE precision at
least 0.80, and a meaningful UNKNOWN reduction without loss of safety.

### E3 — Verified repair

**Question:** Does verifier-guided repair beat LLM-only and test-only repair?

Primary outcome: policy-safe **and** regression-passing repair rate on held-out
repositories. Secondary outcomes: runtime task success, changed lines, lost
capability, added approval burden, cost, iterations, and wall time.

**Gate:** at least +15 absolute percentage points over the strongest LLM-only
baseline with a paired 95% confidence interval excluding zero, and no accepted
false certificate. Otherwise remove the flagship repair claim or pivot.

### E4 — Generalization

Evaluate unseen repositories, framework versions, one held-out framework or
front-end, new policy templates, and dynamic-routing cases. Report performance
and failure categories per slice rather than only a pooled average.

### E5 — Static/runtime partition

**Question:** Can certificates reduce expensive oversight at matched safety and
benign utility?

Measure judge calls, human approvals, attack success, benign utility, recovery,
latency, dollars, and complete-mediation failures.

**Gate:** at least 30% fewer expensive decisions at matched attack success, with
benign utility degradation no worse than 2 absolute points. If this fails, keep
runtime fallback for correctness but drop the efficiency claim.

### E6 — Human repair study

If recruitment permits, conduct a preregistered, counterbalanced, blinded
within-subject study with 20–30 developers comparing LLM-only and
AgentProof-CEGAR repairs. Measure acceptance without edits, review time, intent
preservation, unnecessary restriction, trust calibration, and whether witnesses
and certificates improve error detection. A smaller sample is formative and
must be labeled accordingly.

### E7 — Policy translation ablation

Evaluate semantic equivalence or distinguishing-trace accuracy for LLM-proposed
formal policies after type checking and clarification. Compare with hand-written
policies. This remains an ablation, not a headline contribution.

### E8 — Ablations and scalability

Ablate may/must modality, CEGAR, provenance, symbolic feasibility, LLM proposal,
optimizer, regression constraints, certificate checking, and runtime fallback.
Sweep repair-cost weights. Report extraction, product, refinement, solver, patch,
and certificate-checking time, including tails, graph growth, timeouts, policy
count, predicate complexity, and unknown transitions.

## 8. Statistical plan

- Freeze primary hypotheses, endpoints, exclusions, and prompts before the final
  test sweep.
- Use repository-clustered bootstrap confidence intervals.
- Compare paired repair outcomes with McNemar tests or a mixed-effects logistic
  model with repository and task effects.
- Report absolute differences, effect sizes, confidence intervals, failures,
  crashes, exclusions, and timeouts.
- Correct families of secondary comparisons with Holm's method.
- Use at least five independent runs for stochastic LLM configurations and
  publish all seeds and decoding parameters.
- Separate model/API variance from task and repository variance.
- Perform a prospective power analysis from pilot repair rates; add tasks before
  adding expensive model variants when power is inadequate.
- Never treat mutations from the same repository as independent samples.

## 9. Phased roadmap

The schedule begins after the AAAI-27 submission sprint. Dates are deliberately
stage-gated because venue deadlines may change.

| Phase | Duration | Deliverable | Exit criterion |
|---|---:|---|---|
| 0. Scope freeze | 1 week | novelty table, threat model, supported syntax, preregistered pilot questions | no headline duplicates Agent-C/AgentSpec/AgentFlow |
| 1. Semantics | 3 weeks | typed policy AST, direct oracle, differential/property tests | E0 passes |
| 2. May/must front-end | 5 weeks | new IR, LangGraph semantics, provenance, runtime traces | no false SAFE on 40-program pilot |
| 3. Benchmark | 6 weeks | validated AP-RepairBench pilot, containers, mutation taxonomy, splits | at least 120 validated tasks and frozen pilot split |
| 4. CEGAR + certificates | 4 weeks | concretizer, refinement, independent checker, proof drafts | E1/E2 gates pass on development data |
| 5. Repair | 5 weeks | edit grammar, optimizer, patcher, LLM proposer, re-verification loop | at least +10 points over LLM-only on development data |
| 6. Generalization + runtime | 4 weeks | extra frameworks/versions, static-runtime partition, adversarial cases | E4/E5 pilot complete |
| 7. Frozen evaluation | 5 weeks | all baselines, models, seeds, statistics, human study | E3 gate passes; no false certificate |
| 8. Reproduction + review | 4 weeks | anonymous artifact, full draft, external mock reviews | all final submission gates pass |

Do not parallelize additional framework adapters before LangGraph satisfies the
soundness pilot. Prefer one defensible front-end over four unsound ones.

## 10. Risks and precommitted pivots

| Risk | Evidence that triggers it | Response |
|---|---|---|
| Conservative extraction is too imprecise | UNKNOWN remains high or may graph explodes after refinement | Restrict the supported subset; pivot to proof-carrying runtime authorization and drop static SAFE claims |
| Repair does not beat LLM-only | E3 development gain below 10 points | Improve witnesses/grammar once; if still weak, drop the repair headline and publish calibrated benchmark/failure analysis only at an appropriate venue |
| Real defects are too rare | fewer than 20 independently confirmed cases | Report the true count; focus on effect/authority/data-flow policies; never mix mutations with real prevalence |
| Certificate checker shares implementation bugs | differential or mutation tests expose common-mode failures | further separate representations/implementation and shrink the trusted core |
| Runtime fallback is bypassable | direct or nested effects escape mediation | narrow the guarantee, add process/container mediation, or report unsupported; never claim complete enforcement |
| Human study is underpowered | recruitment or power target fails | label it formative and avoid developer-wide utility claims |
| Venue mismatch | strongest result is analysis/repair rather than learned generalization | submit to ICSE/FSE/ASE rather than adding cosmetic ML |
| Novelty shifts before submission | new work covers the full CEGAR/repair/certificate composition | update the comparison, narrow the claim, and require two external novelty reviews before submission |

## 11. Artifact discipline

- Use one immutable manifest containing task ID, repository SHA, framework and
  dependency versions, policy ID, model, prompt hash, seed, container digest,
  and result hash.
- Provide one command to reproduce every main table and figure from raw data.
- Never manually transcribe results into the manuscript.
- Pin lock files and container images and archive permitted model outputs.
- Maintain unit, property, differential, metamorphic, mutation, and end-to-end
  tests.
- Keep the certificate checker standalone and smaller than the main analyzer.
- Publish dataset and model cards covering provenance, licenses, contamination,
  annotation, exclusions, intended use, cost, and limitations.
- Complete responsible disclosure before releasing real vulnerabilities.
- Run a weekly adversarial review that attempts to invalidate the strongest
  current claim or construct a false certificate.

## 12. Paper outline

1. **Introduction:** false safety from under-approximate agent models; one real
   defect and a failed LLM-only repair.
2. **Problem and threat model:** concrete effects, policy scope, supported
   Python/framework subset, and trusted computing base.
3. **May/must agent transition system:** semantics, provenance, unknowns, and
   trace-containment theorem.
4. **Tri-valued verification and CEGAR:** products, witnesses, concretization,
   refinement, and complexity.
5. **Proof-carrying repair:** edit grammar, objective, LLM proposer, optimizer,
   source patching, re-analysis, and certificate checker.
6. **AP-RepairBench:** sources, ground truth, mutations, splits, leakage,
   licensing, and ethics.
7. **Evaluation:** semantics, extraction, diagnosis, repair, generalization,
   static/runtime partition, ablations, scalability, and human study.
8. **Limitations and related work:** AgentFlow, Agent-C, AgentSpec, VIGIL,
   runtime guards, classical abstract interpretation/CEGAR, automated program
   repair, and proof-carrying code.
9. **Conclusion:** precisely what is certified, what remains UNKNOWN, and what
   requires runtime mediation.

## 13. Final submission gates

Submit the flagship only when all are true:

- the advertised policy fragment has zero known semantic mismatches;
- the supported abstraction has no observed false SAFE certificate;
- benchmark tasks are runnable, repository-split, leakage-audited, and
  independently validated;
- the full repair loop beats the strongest LLM-only baseline by the E3 margin;
- results hold on at least three supported frameworks or on two frameworks plus
  a genuinely unseen version/front-end test;
- the static/runtime experiment meets its gate or its efficiency claim is
  removed;
- every guarantee names its assumptions and unsupported behavior returns
  UNKNOWN;
- a fresh researcher can reproduce the main tables from the anonymous artifact;
- the method is clearly distinguished from AgentFlow, Agent-C, AgentSpec, and
  the latest runtime-policy work;
- two mock top-tier reviews cannot defeat the central claim with the same
  obvious counterexample.

No deadline overrides these gates. If they do not pass, choose the documented
pivot or a more suitable venue rather than weakening the evaluation.

## 14. Literature that must remain current

- AgentFlow and agent-program dependency analysis
- Agent-C and temporal/stateful constrained agent execution
- AgentSpec and customizable runtime constraints
- VIGIL and behavioral specifications over agent skills
- ShieldAgent, ClawGuard, SecureClaw, PolicyGuard, and related runtime guards
- classical abstract interpretation, CEGAR, runtime verification, edit/security
  automata, automated program repair, and proof-carrying code

Refresh the related-work and novelty matrix immediately before every internal
go/no-go review and before submission.
