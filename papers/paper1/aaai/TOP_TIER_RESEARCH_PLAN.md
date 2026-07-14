# AgentProof: Top-Tier Research and Submission Plan

**Prepared:** 2026-07-13  
**Starting point:** `papers/paper1/aaai/`, AgentProof v0.3.1, 103 passing tests  
**Immediate opportunity:** AAAI-27 abstract 2026-07-21, paper 2026-07-28,
supplement/code 2026-07-31 (all AoE)  
**Long-horizon goal:** a genuinely new, defensible paper for ICML/NeurIPS/ICLR,
not a cosmetic resubmission

## 1. Executive decision

There are two papers here, with two different jobs.

1. **Submit the current base-rate study to the AAAI-27 AI Alignment track after
   a strict correctness and human-validation sprint.** The track explicitly
   welcomes safe-by-design engineering and formal safety cases. The paper's
   strongest contribution is the negative but useful measurement result: naïve
   workflow verification produces mostly non-actionable findings because model
   extraction is the error bottleneck. Do not recast the result as a strong
   detector paper.
2. **Build a separate flagship paper around sound abstraction and
   counterexample-guided, proof-carrying workflow repair.** A plain runtime DFA
   shield is no longer a sufficiently new contribution. Recent Agent-C,
   ClawGuard, SecureClaw, and related systems already enforce policies at tool
   boundaries; Agent-C also covers stateful temporal constraints, natural-
   language policy translation, tau-bench, multiple models, and formal claims.
   AgentFlow now provides a richer static dependency graph over 5,399 agent
   programs. The open research gap is not another interceptor. It is:

   > Can we construct a conservative model of an agent program, distinguish
   > definite from possible violations, and synthesize a minimal source-code
   > repair that carries a machine-checkable safety certificate—while routing
   > only unresolved behavior to runtime enforcement?

The recommended flagship working title is:

> **AgentProof-CEGAR: Proof-Carrying Repairs for Tool-Using Agent Programs**

The thesis is:

> A may/must abstraction of an agent program, refined by counterexamples and
> coupled to verifier-checked LLM repair proposals, can eliminate false proofs,
> improve repair success over LLM-only and test-only agents, and reduce the
> amount of behavior requiring runtime oversight.

No plan can guarantee acceptance. This plan maximizes scientific credibility
and creates explicit stop/go gates so that weak results are not papered over.

## 2. Audit of the current paper

### 2.1 What is already strong

- The paper separates flag precision from defect prevalence. This is the right
  statistical distinction for an imperfect measurement instrument.
- It openly reports the failure of the original premise: 2/186 extracted-graph
  flags are genuine, while ground-truth analysis finds 4/119 defective
  workflows.
- It identifies a concrete mechanism: edge recall is 0.649 overall and 0.382
  for ADK; some extractors construct connected graphs and thereby predetermine
  structural-check outcomes.
- The corpus has provenance, repository clustering, confidence intervals,
  framework strata, source-type classification, and contamination analysis.
- The implementation is compact, typed, reproducible, and currently has 103
  passing tests.
- The paper is already within the AAAI page budget and uses the 2027 style.

### 2.2 Why the present version is still high-risk

| Risk | Evidence in the repository | Likely reviewer conclusion |
|---|---|---|
| Reference labels are not human ground truth | 119 graphs and triage labels come from two passes using one model family | The prevalence and fidelity numbers are not adequately validated |
| Extraction invalidates strong static guarantees | AST edge recall is 0.65 and is an under-approximation | “No violation” cannot imply runtime safety |
| Structural checks are shallow | Reachability, dead ends, router shape, human presence, and declarations | The algorithms are standard graph checks rather than a major AI contribution |
| Real defects are rare | 4/119 workflows; every extracted structural flag is non-genuine | The practical value of topology-only detection is unclear |
| Monitor pruning is vacuous on the evaluated corpus | All 251/270 pruned monitors are alphabet-level | Product construction adds no measured pruning benefit |
| Public GitHub is tutorial-heavy | Only 39/119 validated workflows are application-like | External validity to deployed systems is weak |
| Theory is asserted more strongly than presented | Checklist says theoretical contribution “yes,” but formal claims and proofs are “partial” | Technical correctness becomes a Phase-1 rejection risk |
| New work overlaps the positioning | AgentFlow, Agent-C, ClawGuard, SecureClaw appeared in 2026 | Novelty claims can age badly even if the work was concurrent |

### 2.3 Code-level release blockers found in this audit

Passing unit tests do not cover the following semantic problems.

1. **Nested until is not implemented compositionally.** `_parse_dsl` turns the
   right side of `a U (b U c)` into the literal predicate string `"(b U c)"`.
   Remove the advertised form or implement a real recursive automaton.
2. **Response chains can lose obligations.** For `G(a -> F(b AND F c))`, a new
   `a` between the first `b` and `c` creates another obligation. The current
   automaton ignores that trigger. The trace `a,b,a,c` can therefore be
   accepted although the second `a` lacks a following `b,c` chain.
3. **Static checking sees only one tool per multi-tool node.** The default event
   mapper uses `node.tools[0]`. The separate pruning script expands such nodes,
   but the public `check_temporal_property` API does not. This can produce a
   false proof.
4. **The infinite-run claim needs a correct omega-automaton.** An LTLf DFA plus
   “non-accepting product cycle” is not a correct general decision procedure
   for arbitrary infinite-trace conjunctions/disjunctions. For example,
   conjunctions of recurrence obligations require a generalized Büchi/parity
   acceptance condition; requiring both component DFAs to be accepting at the
   same instant can be too strong.
5. **Unknown and inferred topology is represented as fact.** Synthesized exits,
   leaf connections, fully connected selectors, and inferred agent ordering
   need provenance and may/must semantics. Otherwise the checker cannot state
   what its result actually guarantees.

These must be fixed or explicitly scoped out before the AAAI submission.

## 3. Immediate AAAI-27 submission plan

### 3.1 Track and positioning

Submit to **AAAI-27 AI Alignment**, not AI for Social Impact. Use keywords close
to safety constraints, evaluation, controllability, and robustness. The paper
is a critical evaluation/formal-safety-case paper, not a claim that static graph
checks solve agent safety.

Recommended title:

> **When Can Static Verification Help Agent Workflows? A Base-Rate and Model-Fidelity Study**

Recommended one-sentence claim:

> Static workflow verification is useful only when the extracted model is
> trace-conservative and the policy applies to real actions; on public agent
> code, extraction error dominates detector error and reverses the apparent
> defect rate.

The title and abstract must lead with the scientific question and finding, not
the package name.

### 3.2 Eight-day critical path

| Date | Required outcome |
|---|---|
| 2026-07-13 | Freeze the current artifacts; create an issue/checklist for every number and claim |
| 2026-07-14 | Finish temporal semantic fixes or remove unsupported forms/claims; add exhaustive oracle tests |
| 2026-07-15 | Complete two-human annotation protocol and pilot it on 5 workflows |
| 2026-07-16 to 17 | Independently annotate the validation subset and every claimed genuine defect; adjudicate after labels are locked |
| 2026-07-18 | Rerun all analyses, dedup sensitivity, confidence intervals, and paper tables from one manifest |
| 2026-07-19 to 20 | Rewrite abstract, contributions, formal claim, limitations, and new-related-work comparison |
| 2026-07-21 | Submit a final, non-placeholder title and abstract to OpenReview |
| 2026-07-22 to 24 | Finish supplement, proofs, annotation guide, datasheet, and artifact README |
| 2026-07-25 | Independent claim-to-artifact audit; no author edits numbers by hand afterward |
| 2026-07-26 | Fresh-environment reproduction and PDF compliance check |
| 2026-07-27 | Freeze submission candidate; only desk-rejection fixes allowed |
| 2026-07-28 | Submit paper before the deadline |
| 2026-07-29 to 31 | Upload anonymized code/data and technical supplement |

If independent human annotation cannot be completed by July 18, submit only if
the paper explicitly downgrades the ground-truth claims to LLM-assisted labels
and presents the human pilot separately. Do not call LLM reconstructions
“ground truth” without qualification.

### 3.3 Minimum human-validation protocol

Use two annotators who did not create the original LLM labels. Prefer people
with Python and at least one agent-framework background. If authors annotate,
state that and keep them blinded to extractor output and prior labels.

Create a fixed annotation guide with:

- exact definitions of a workflow node, control edge, data dependency, tool
  binding, exit, deliberate wait state, human gate, and genuine defect;
- examples and counterexamples for all four frameworks;
- an “insufficient evidence/unknown” option;
- a rule that disagreement is not resolved until both initial labels are
  committed;
- source-line citations and a short rationale for every defect label.

Perform two validation tasks:

1. **Graph reconstruction:** stratified 32-workflow sample: 8/framework,
   balanced as far as possible between application-like and tutorial/demo/test.
   Each annotator independently reconstructs nodes, edges, kinds, tool bindings,
   entry, and exits. Report pairwise node/edge F1 and kind agreement, followed
   by adjudicated extractor precision/recall.
2. **Defect labeling:** independently review all 16 flags raised on reconstructed
   graphs, all four claimed genuine defects, and a repository-stratified random
   sample of at least 30 no-flag workflows. Report raw agreement and Krippendorff
   alpha or Cohen kappa with a bootstrap interval. Also report agreement before
   adjudication.

Do not use agreement on a cherry-picked set as validation of prevalence. The
random no-flag audit is necessary to probe false negatives.

### 3.4 Mandatory code and semantics work for AAAI

#### A. Build a finite-trace reference oracle

Add `tests/oracles/ltlf_reference.py`, a deliberately slow direct evaluator for
the exact supported formulas. Exhaustively enumerate valuations for all traces
up to length 6 for two atoms (longer randomized property tests after that) and
differentially compare the compiled monitor's final verdict.

Required properties:

- empty-trace semantics;
- repeated antecedents;
- simultaneous antecedent/consequent;
- obligations at normal termination versus abort;
- conjunction/disjunction truth tables;
- bounded-response boundary at exactly `k`;
- response-chain overlap;
- strong-until termination.

For the AAAI version, choose one of these safe scopes:

- **Preferred short-term scope:** finite maximal executions only. Treat a run
  that hits a configured step/time bound as inconclusive. Remove the
  standard-LTL/infinite-lasso theorem from the main claim.
- **Longer-term scope:** compile infinite-trace properties to a proper Büchi or
  parity automaton and verify the product with the appropriate acceptance
  algorithm. Do not improvise this in the submission week.

#### B. Fix or delete unsupported DSL forms

- Represent nested formulas with recursive AST nodes; never encode a formula as
  an atomic string.
- Either construct a correct automaton for overlapping response chains or
  remove the response-chain form for this submission.
- Add negative regression tests containing minimal counterexample traces.
- State the exact grammar and denotational semantics in the supplement.

#### C. Make multi-tool behavior conservative

Change a graph node event from one selected tool to nondeterministic possible
events. The static product must explore every declared tool and the “no tool
called” case when invocation is optional. Preserve ordering only when the
framework guarantees it. A false alarm is acceptable; a false proof is not.

#### D. Add provenance to extraction

At minimum add metadata fields:

```text
origin = runtime | ast_explicit | ast_inferred | synthesized | unknown
confidence = exact | may | heuristic
source_span = file:start_line:end_line
```

The AAAI paper can continue reporting the existing numbers, but the tool output
must distinguish observed edges from guessed edges.

### 3.5 Analyses that must be rerun

1. **Deduplicated sensitivity:** remove the 170 redundant workflows and report
   changes in all headline corpus-level rates.
2. **Repository weighting:** report both workflow-weighted and repository-
   weighted estimates.
3. **Application-only analysis:** report the 39 application-like workflows as a
   prespecified stratum, without claiming it represents production.
4. **Human-label sensitivity:** compute headline results using only
   human-adjudicated labels, then using the full LLM-assisted set.
5. **Unknown-as-positive sensitivity:** for safety claims, count uncertain
   topology/tool bindings pessimistically and show the bound.
6. **Policy applicability:** denominator is workflows to which the policy
   actually applies, not every mined workflow.
7. **Monitor-pruning baseline:** put alphabet filtering beside product checking.
   State “0 extra cases over alphabet filtering” prominently if that remains
   the result.
8. **Runtime-extractor ceiling:** on a safe, dependency-installable subset, run
   native framework extraction in a network-disabled container. Report the
   subset selection and failures, not only successful executions.

### 3.6 Paper rewrite order

The seven content pages should be allocated approximately as follows:

1. Introduction and research questions: 0.8 page
2. Instrument and formal scope: 1.2 pages
3. Corpus, sampling, and human/LLM annotation: 1.3 pages
4. Extraction fidelity: 1.0 page
5. Precision and prevalence results: 1.2 pages
6. Policy applicability and monitor-selection negative result: 0.7 page
7. Related work, limitations, and conclusion: 0.8 page

Move implementation details, per-framework tables, complete policy grammar,
proofs, queries, annotation guide, all label rationales, and additional plots to
the supplement. Any fact needed to believe the headline result remains in the
main paper.

Use explicit research questions:

- **RQ1:** How faithfully can agent workflow behavior be recovered from source
  and runtime objects?
- **RQ2:** What fraction of static findings are genuine and actionable?
- **RQ3:** What is the prevalence of the target defects after auditing false
  negatives?
- **RQ4:** When can static analysis soundly reduce runtime enforcement?

### 3.7 AAAI submission go/no-go checklist

Submit only if all “hard” gates pass.

#### Hard gates

- [ ] No known semantic counterexample remains for an advertised DSL form.
- [ ] Every number in the paper is generated from committed artifacts by one
      documented command.
- [ ] Human validation is reported or “ground truth” language is removed.
- [ ] The supplement contains exact mining queries, dates, commits, exclusions,
      and annotation instructions.
- [ ] The monitor-pruning claim includes the alphabet-only baseline.
- [ ] Static soundness is conditioned on a conservative extraction, with no
      guarantee claimed for the lossy AST corpus.
- [ ] Code/data are available anonymously at submission, not promised later.
- [ ] All four real issues have a responsible-disclosure record.
- [ ] A clean machine can reproduce every main table.
- [ ] The paper, references, and checklist satisfy the official page rules.

#### Soft gates

- [ ] Deduplication moves no headline estimate materially; otherwise the change
      is explained.
- [ ] At least 32 graphs have independent human reconstructions.
- [ ] Runtime extraction is evaluated on at least 10 workflows/framework where
      technically feasible.
- [ ] A domain expert not involved in the project has conducted a mock Phase-1
      review.

## 4. Flagship paper: AgentProof-CEGAR

### 4.1 Novel contribution boundary

The flagship must not claim novelty for:

- intercepting tool calls;
- compiling a temporal policy to an automaton;
- using an LLM to translate English policy text;
- evaluating only on tau-bench or AgentDojo;
- creating a cross-framework static dependency graph;
- showing that deterministic policy checks have low latency.

Those areas already have strong contemporary work. The new contribution must be
the composition of **conservative program abstraction, counterexample-guided
refinement, minimal repair synthesis, source patching, and a checked
certificate**, evaluated end to end.

### 4.2 Formal problem

Let program `P` induce a set of possible effect traces `Tr(P)`. Let policy
automaton `A_phi` recognize policy-violating finite prefixes for a safety policy
`phi`. Build an abstract transition system `M(P)` with must transitions and may
transitions such that:

```text
Tr(P) subseteq Tr_may(M(P))
Tr_must(M(P)) subseteq Tr(P)
```

The analyzer returns one of:

- **SAFE:** no accepting violation state is reachable in `M_may x A_phi`;
- **UNSAFE:** a violation exists on a must path and is concretely reproducible;
- **UNKNOWN:** a counterexample uses may/unknown behavior not yet validated.

For UNKNOWN, a CEGAR loop checks feasibility using framework semantics,
symbolic guards, and sandboxed execution. It either promotes the path to a
concrete witness or refines the abstraction.

A repair is an edit sequence `r` from a finite grammar. It is certified when:

```text
tests(P + r) pass
and
no violation is reachable in M_may(P + r) x A_phi
```

The trusted computing base is the parser/extractor, automaton compiler, product
checker, and certificate checker—not the LLM proposing a repair.

### 4.3 Restrict the first theorem to enforceable safety

Do not mix safety and liveness in the headline guarantee. Veto-based runtime
enforcement can prevent a bad prefix but cannot force an eventual action. Use:

- authorization and capability constraints;
- required-before constraints such as authenticate before read;
- confirmation before external effect;
- bounded quotas/rate policies;
- taint/noninterference approximations;
- argument constraints and identity consistency;
- forbidden tool sequences.

Treat liveness, eventual completion, and unbounded response as diagnosis or
termination-time checks, not shield-enforceable safety guarantees.

### 4.4 Proposed theorems

1. **Abstraction soundness:** for the explicitly supported framework subset,
   every concrete effect trace is contained in the may abstraction.
2. **Safety-certificate soundness:** if the may product contains no violation,
   every concrete trace satisfies the safety policy.
3. **Repair soundness:** a certified patch satisfies the policy under the same
   abstraction assumptions and preserves the declared regression suite.
4. **Relative minimality:** the selected repair has minimum configured cost
   among repairs in the edit grammar considered by the solver.
5. **CEGAR termination:** for a finite abstraction lattice and finite edit
   grammar, refinement terminates with SAFE, UNSAFE, or an explicit unsupported
   feature/UNKNOWN result.

State assumptions next to every theorem. Put complete proofs in the appendix and
property-based tests against an independent checker in the artifact.

### 4.5 System architecture

```text
Python agent program
        |
        v
framework semantic front-end ---- source spans / provenance
        |
        v
May/Must Agent Transition System (MM-ATS)
        |                         \
        |                          \ unknown paths
        v                           v
policy automaton product       sandbox concretizer
        |                           |
 SAFE / UNSAFE / UNKNOWN <---------- refinement
        |
        v
repair grammar + MaxSAT/SMT optimizer
        |
        v
LLM proposes source patch -> extract again -> verify -> certificate
        |
        v
residual UNKNOWN behavior -> runtime approval/formal guard/LLM judge
```

### 4.6 Intermediate representation

Replace the current flat `AgentGraph` as the analysis IR while retaining it as
a compatibility view.

Each node should carry:

- stable ID and source span;
- framework object and call target;
- effect kind: read, write, execute, communicate, financial, delete, none;
- tool schema and abstract argument values;
- principal/authority and user/session identity;
- input/output data labels;
- state predicates and path guard;
- extraction origin and confidence;
- possible exception/abort behavior.

Each edge should carry:

- `must`, `may`, or `unknown` modality;
- direct, conditional, loop, parallel, exception, callback, or dynamic-dispatch
  kind;
- guard formula;
- framework rule that produced it;
- source span and refinement history.

Unknown dynamic dispatch must add conservative summary behavior. Never silently
drop it.

### 4.7 Repair grammar

Start with edits that can be verified and mapped back to all four frameworks:

1. insert a confirmation/human-approval node before an effect;
2. add or strengthen a router guard;
3. restrict a tool binding/capability for one agent;
4. move a tool from a general agent to a least-privilege executor;
5. add identity/authentication state and a precondition;
6. add a sanitizer/declassifier between untrusted read and external write;
7. rewire a dead end or incorrect exit;
8. bound a loop/retry count;
9. insert a transactional preview/commit boundary;
10. route unresolved cases to a human or deny-by-default branch.

Use a weighted objective:

```text
cost = changed_lines
     + lambda_1 * added_human_approvals
     + lambda_2 * lost_capability
     + lambda_3 * added_latency
     + lambda_4 * unknown_behavior
```

Publish the weights and sweep them. Do not call a patch “minimal” without
specifying the cost model.

## 5. Benchmark design

### 5.1 Build AP-RepairBench

Target **240 repair tasks** with repository-level train/dev/test splits:

| Slice | Target | Purpose |
|---|---:|---|
| Human-confirmed real defects | 20+ | Ecological validity; expand beyond the current four through targeted mining and disclosure |
| Real workflows with policy-breaking mutations | 120 | Controlled coverage while retaining realistic code context |
| Official framework examples with semantic mutations | 40 | Exact runtime ground truth across versions |
| Hand-built adversarial/dynamic cases | 60 | Closures, aliases, callbacks, nested agents, dynamic routing, parallelism, exceptions |

If fewer than 20 real defects are found, report the actual number and do not
inflate it with mutations. Real and mutated results must always be separate.

Mutation operators must be derived from an independently created defect
taxonomy, not chosen after observing which cases AgentProof solves. Examples:

- remove an approval edge;
- swap two state-changing actions;
- add a bypass edge;
- bind a write tool to an untrusted agent;
- erase an identity guard;
- route a tool result into an external sender;
- remove an exit/error path;
- replace bounded retry with an unbounded loop;
- weaken an argument predicate;
- introduce dynamic dispatch that a naïve AST analyzer misses.

Every test task needs:

- runnable source at a pinned dependency version;
- natural-language policy and authoritative formal policy;
- defect category and concrete violating trace;
- benign regression tasks;
- at least one human patch, but not the assumption that it is the only valid
  patch;
- independent reviewer approval;
- repository license/provenance and a redistribution decision.

### 5.2 Data-split discipline

- Split by repository, never by file or mutation.
- Put forks/duplicate topology in one split using clone and graph similarity.
- Keep framework versions separated in an out-of-distribution evaluation.
- Hold out at least one framework from any learned repair-ranking component.
- Prevent the LLM from retrieving the gold patch or issue during evaluation.
- Release a contamination report for public models and public repositories.

### 5.3 Human study

Recruit 20–30 developers if possible, with a preregistered within-subject design.
Each participant reviews counterbalanced repairs from LLM-only and
AgentProof-CEGAR, without method labels. Measure:

- acceptance without edits;
- time to understand and apply;
- perceived intent preservation;
- unnecessary restriction;
- trust calibration after seeing the certificate and witness;
- inter-rater agreement.

If recruitment is too small, label the result a formative study and avoid broad
developer-utility claims.

## 6. Baselines

### 6.1 Extraction and analysis baselines

- Current AgentProof AST extraction
- Framework-native runtime extraction
- AgentFlow, if its artifact supports the target framework/version
- A generic Python call/control graph baseline such as PyCG or CodeQL queries
- Alphabet-only policy filtering
- Trace-only dynamic monitoring on the benchmark test suite

### 6.2 Repair baselines

- No repair / original program
- One-shot frontier LLM with source + policy
- LLM with failing tests and concrete witness
- Iterative LLM with test feedback but no formal verifier
- LLM with the current under-approximating AgentProof verifier
- Solver-only repair from the fixed grammar
- Full LLM proposal + CEGAR + certificate
- Human reference patch

### 6.3 Runtime-policy baselines

Only for the residual-runtime experiment:

- Unrestricted agent
- Prompt policy only
- AgentSpec or another deterministic rule baseline
- Agent-C when code and licenses permit a faithful comparison
- A learned/LLM judge such as DynaGuard or PolicyGuard
- Full static partition + cheap formal guard + judge only for UNKNOWN

ClawGuard and SecureClaw should be discussed and included when comparable; do
not force incomparable threat models into one ranking.

## 7. Experiments and decision thresholds

### E0. Semantic conformance

**Question:** Does the policy implementation match its stated semantics?

- Differential testing against a direct finite-trace evaluator and, where
  possible, an established LTLf/automata library.
- Exhaustive short traces plus property-based random traces.
- Mutate the compiler itself to demonstrate that tests catch seeded semantic
  bugs.

**Gate:** zero mismatches for supported grammar; every unsupported construct
returns an explicit error.

### E1. Conservative extraction

**Question:** Does the may graph contain concrete framework behavior without
becoming uselessly dense?

Metrics: node/edge precision and recall; effect/tool recall; trace containment;
unknown-edge mass; graph-size blowup; analysis time. Ground truth comes from
human reconstructions plus instrumented executions and official semantics.

**Gate:** effect/tool recall 1.00 on the supported benchmark subset; lower 95%
bound for may-edge recall at least 0.95; explicitly return UNKNOWN outside the
supported subset.

### E2. Defect detection and tri-valued calibration

**Question:** Are SAFE/UNSAFE/UNKNOWN judgments calibrated?

Metrics: false SAFE count, precision/recall for UNSAFE, UNKNOWN rate, witness
validity, coverage by defect class.

**Gate:** zero false SAFE certificates in the benchmark; at least 0.80 UNSAFE
precision and a useful reduction in UNKNOWN after refinement.

### E3. Repair success

**Question:** Does verifier-guided repair outperform LLM-only and test-only
repair?

Primary metric: policy-safe plus regression-passing patch rate on held-out
repositories. Secondary: compile rate, runtime task success, lines changed,
approval burden, solver/LLM cost, iterations, and wall time.

**Gate:** at least +15 absolute percentage points over the strongest LLM-only
baseline, with a paired confidence interval excluding zero; no false
certificate.

### E4. Generalization

Evaluate unseen repositories, framework versions, one held-out framework, new
policy templates, and dynamic-routing cases. Report failure categories rather
than only average success.

### E5. Static-runtime partition

**Question:** Can static proofs reduce expensive oversight while preserving
safety and utility?

Route SAFE effects directly, definite violations to deny/repair, and UNKNOWN to
approval or a learned judge. Compare judge calls, human approvals, attack
success, benign utility, latency, and dollars.

**Gate:** at least 30% fewer expensive judge/approval decisions at matched
attack success, with benign utility degradation no worse than 2 absolute points.
If this fails, remove the optimization claim; correctness remains the result.

### E6. Policy-to-formal translation

Use the LLM only as an untrusted proposal generator. Verify syntax, type-check
tool/state references, generate distinguishing traces between candidate
policies, and ask a human to resolve ambiguity.

Report semantic equivalence/coverage on a policy test suite—not merely
compilability or downstream utility. This is an ablation, not the headline,
because Agent-C already studies natural-language specification generation.

### E7. Ablations

- may/must versus single graph;
- no CEGAR;
- no provenance;
- no symbolic feasibility;
- no LLM proposal;
- no repair optimizer;
- no regression constraint;
- no runtime fallback;
- different repair cost weights.

### E8. Scalability

Measure extraction, product checking, refinement, solver time, certificate
checking, and graph blowup against nodes, edges, policies, predicates, and
unknown transitions. Report tails and timeouts, not only means.

## 8. Statistical plan

- Declare primary outcomes before the final sweep.
- Use repository-clustered bootstrap confidence intervals.
- Compare paired binary repair outcomes with McNemar tests or a mixed-effects
  logistic model with repository and task as random effects.
- Report absolute differences, odds ratios, and confidence intervals.
- Correct families of secondary comparisons with Holm's method.
- Use at least five independent runs for stochastic LLM configurations; report
  all seeds and decoding parameters.
- Estimate API/model variance separately from task variance.
- Conduct a prospective power analysis using pilot repair rates; increase tasks
  before models if power is inadequate.
- Never treat multiple mutations of one repository as independent samples.
- Report failures, exclusions, crashes, and timeouts in denominators.

## 9. Concrete code roadmap

Keep old APIs stable while introducing a new analysis core.

```text
src/agentproof/
  ir/
    ats.py                 # may/must transition system and provenance
    effects.py             # effect, authority, data-label abstractions
    guards.py              # finite abstract domains and predicates
  extract/
    common.py              # source spans, aliases, conservative summaries
    langgraph_static.py
    autogen_static.py
    crewai_static.py
    adk_static.py
    runtime_trace.py       # instrumented native extraction
  logic/
    ast.py                 # typed recursive policy AST
    ltlf.py                # finite-trace semantics
    safety_automata.py     # bad-prefix automata only for enforcement
    reference.py           # slow independent oracle
  verify/
    product.py             # tri-valued may/must product
    certificate.py         # small trusted certificate checker
    counterexample.py
  cegar/
    feasibility.py
    refine.py
    sandbox.py
  repair/
    grammar.py
    optimize.py
    patch_langgraph.py
    patch_autogen.py
    patch_crewai.py
    patch_adk.py
    llm_proposer.py        # untrusted proposal interface
  runtime/
    guard.py               # residual UNKNOWN enforcement
    adapters/
benchmarks/
  manifest.jsonl
  policies/
  tasks/
  harness/
tests/
  oracles/
  semantics/
  extraction/
  certificates/
  repair/
```

### Phase 1: correctness foundation, 3 weeks

- typed recursive policy AST;
- direct finite-trace semantics;
- differential/property tests;
- safety versus liveness classification;
- conservative multi-tool events;
- remove any unsupported grammar.

Exit criterion: E0 passes.

### Phase 2: may/must abstraction, 5 weeks

- new IR and provenance;
- LangGraph front-end first;
- exact handling of explicit edges and declared tools;
- conservative summaries for dynamic routers and hidden calls;
- human-labeled 40-program pilot.

Exit criterion: no false SAFE on the pilot.

### Phase 3: benchmark and additional frameworks, 6 weeks

- AP-RepairBench manifest and validation UI;
- AutoGen, CrewAI, ADK front-ends;
- mutation engine and runnable containers;
- duplicate/leakage audit;
- baseline integrations.

Exit criterion: 120 validated tasks and frozen pilot split.

### Phase 4: CEGAR and certificates, 4 weeks

- counterexample feasibility;
- refinement lattice;
- small standalone certificate checker;
- formal theorem statements and proof drafts.

Exit criterion: E1/E2 gates pass on dev.

### Phase 5: repair, 5 weeks

- edit grammar and optimizer;
- LangGraph source patcher, then remaining frameworks;
- LLM proposal interface;
- regression and re-extraction loop.

Exit criterion: full system beats LLM-only by at least 10 points on dev.

### Phase 6: final evaluation, 5 weeks

- freeze code and benchmark;
- preregister primary outcomes;
- run all models/baselines/seeds;
- human study;
- artifact reproduction and paper writing.

Exit criterion: E3 gate passes and no false certificate exists.

## 10. Venue strategy

### AAAI-27 now

- Submit the base-rate paper to AI Alignment after the eight-day hardening
  sprint.
- Official dates: abstract July 21, paper July 28, supplement July 31, 2026 AoE.
- AAAI permits arXiv preprints but forbids concurrent archival review of the same
  or substantially similar work.
- Do not submit this same paper to ICLR while AAAI review is active.

### ICLR 2027

- The official 2027 CFP/deadline was not posted as of this plan; only the future
  meeting location is official.
- The flagship cannot be ready to top-tier quality on a short historical ICLR
  schedule. Do not rush a two-month system into submission.
- Consider ICLR only if the paper becomes primarily about verifier-guided LLM
  repair/generalization and all E0–E4 gates pass before the confirmed deadline.

### ICML 2027

- The official conference announcement was still scheduled for August 2026;
  do not present a historical January deadline as confirmed.
- Use ICML only if the flagship has a strong learned/LLM repair result, rigorous
  generalization, and a frozen benchmark at least six weeks before its confirmed
  deadline.

### NeurIPS 2027

- Recommended primary flagship target because it gives enough time for a real
  benchmark, human study, theory, and broad model evaluation.
- If an Evaluations & Datasets track exists with appropriate rules, the
  benchmark could be a separate contribution only if it is scientifically
  distinct and venue policies permit it. Do not thin-slice one result.

### Software-engineering alternative

If the strongest result remains extraction, static analysis, and automated
program repair rather than machine learning, ICSE/FSE/ASE is a better scientific
fit than forcing it into an ML venue. These are top-tier venues, not a fallback
in research quality.

## 11. Paper outline for the flagship

1. **Introduction:** false proofs from under-approximate agent graphs; one
   motivating real defect and failed LLM-only repair.
2. **Problem and threat model:** untrusted planner, trusted policies/tool
   schemas, supported language subset, concrete effect traces.
3. **May/must agent transition system:** framework semantics, unknowns, trace
   containment theorem.
4. **Tri-valued verification and CEGAR:** product construction, witnesses,
   refinement, complexity.
5. **Proof-carrying repair:** repair grammar, optimization, LLM proposer, source
   patch, certificate checker.
6. **AP-RepairBench:** sources, annotation, mutations, splits, leakage, ethics.
7. **Evaluation:** extraction, detection, repair, generalization,
   static-runtime partition, ablations, scaling, human study.
8. **Limitations and related work:** AgentFlow, Agent-C, AgentSpec, ClawGuard,
   SecureClaw, PolicyGuard, classical CEGAR/APR/runtime verification.
9. **Conclusion:** exactly what is guaranteed, what is UNKNOWN, and what remains
   runtime-dependent.

## 12. Artifact and project discipline

- One immutable experiment manifest with task IDs, repository SHA, framework
  version, policy ID, model, seed, container digest, and result hash.
- One command to reproduce each table and figure.
- Machine-readable raw results; never transcribe numbers into LaTeX manually.
- Lock files and container images for framework versions.
- Unit tests, property tests, differential tests, and metamorphic tests.
- A small standalone certificate checker with fewer dependencies than the main
  analyzer.
- Anonymous artifact for review, public archival release after policy permits.
- Dataset card covering GitHub sampling, tutorials, forks, licenses,
  contamination, annotators, and intended use.
- Responsible disclosure before publishing real vulnerabilities.
- Cost and carbon/API accounting for model sweeps.
- Weekly “kill your claim” meeting: one person tries to find a counterexample to
  the strongest current statement.

## 13. Final go/no-go rules for a top-tier submission

Do **not** submit the flagship merely because a deadline arrives. Submit when:

- the advertised formal fragment has zero known semantic mismatches;
- the supported abstraction has no observed false SAFE certificates;
- the benchmark has repository-level splits and independent validation;
- the full repair loop beats the strongest LLM-only baseline by a meaningful,
  statistically supported margin;
- results hold on at least three frameworks and one unseen version/framework
  setting;
- the new method is clearly distinct from AgentFlow and Agent-C;
- the paper reports UNKNOWN rather than hiding unsupported dynamic behavior;
- a fresh team member can reproduce the main tables from the artifact;
- two mock reviewers cannot defeat the central claim with the same obvious
  counterexample.

If sound extraction is too imprecise, pivot the flagship to **proof-carrying
runtime repair/authorization** and drop static SAFE claims. If repair does not
beat LLM-only, publish the benchmark and calibrated failure analysis in an
appropriate venue after checking distinct-contribution policies. If topology
defects remain too rare, focus on effect, authority, argument, and data-flow
policies—the evidence already says that is where the consequential behavior is.

## 14. Relevant current sources to track

- [AAAI-27 main technical call](https://aaai.org/conference/aaai/aaai-27/main-technical-track-call/)
- [AAAI-27 submission instructions](https://aaai.org/conference/aaai/aaai-27/submission-instructions/)
- [ICLR future meetings](https://iclr.cc/Conferences/FutureMeetings)
- [ICML future meetings](https://icml.cc/Conferences/FutureMeetings)
- [AgentFlow](https://arxiv.org/abs/2607.01640)
- [Agent-C: Enforcing Temporal Constraints for LLM Agents](https://adharshkamath.github.io/papers/agentc.pdf)
- [ClawGuard](https://arxiv.org/abs/2604.11790)
- [SecureClaw](https://arxiv.org/abs/2606.09549)
- [Towards Practically-Secure Tools for AI Agents](https://cs.brown.edu/people/malte/pub/papers/2026-euromlsys-toolsafety.pdf)
- [PolicyGuardBench / PolicyGuard](https://huggingface.co/papers/2510.03485)

