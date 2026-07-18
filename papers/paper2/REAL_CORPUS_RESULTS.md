# AgentProof-CEGAR — Real-Corpus Findings (912 mined agent workflows)

**Branch:** `paper2-cegar-impl` · **Date:** 2026-07-17 · Companion to
[`README.md`](README.md), [`EXPERIMENT_PLAN.md`](EXPERIMENT_PLAN.md),
[`IMPLEMENTATION.md`](IMPLEMENTATION.md).

> **Data guardrail.** Every number in this document is taken verbatim from the
> single real-corpus run record. No confidence intervals, precision/recall,
> per-framework outcome splits, or population rates are reported, because the run
> did not produce them and this document does not manufacture them. Where a
> quantity does not exist in the run record, the text says so explicitly.

---

## 1. The one honest headline

> On a real, GitHub-mined corpus of **912** agent workflows across four
> frameworks, **tool-effect resolvability — not graph topology — is the binding
> constraint on static certifiability**, and it is a small-cardinality,
> hand-labelable problem: **157 of 180** tool bindings (87%) carry UNKNOWN effect
> and by construction may-match *any* effect predicate, which mechanically forces
> **5462 / 5472 = 99.8%** of policy/graph pairs to UNKNOWN and **0** graphs to
> SAFE under the sound default. The analysis stays sound (no false SAFE) and
> cheap (**0.38 ms/graph**). Those 157 unknown bindings collapse to just **25
> distinct tool names** and **3** genuinely sensitive tools, so the entire
> certifiability gap is gated by a dictionary a human could label in an afternoon.

This is an empirical quantification of Paper 1's extraction-fidelity thesis on a
new axis (effect resolution), measured at corpus scale. **It is a
measurement / negative result.** It is *not* an efficacy result for certification
or for proof-carrying repair, both of which produce **zero** positive output on
this corpus (§5, §6).

Everything below either supports this single claim or is explicitly marked as
**NULL**, **VACUOUS**, or **ARTIFACT**.

---

## 2. What was run

| Field | Value |
|---|---|
| Graphs | **912** real, GitHub-mined agent workflows |
| Frameworks | langgraph **401**, autogen **345**, crewai **115**, adk **51** |
| Sampling | GitHub-mined; **skews to tutorials / demos / chatbots** |
| Node provenance | **3385** exact / **1690** heuristic (synthesized entry/exit sentinels) / **164** may |
| Edge provenance | **4560** exact / **1022** heuristic / **972** may |
| Total wall time | **1.2 s** |
| Mean analysis / graph | **0.38 ms** |

Half the nodes (1690 + 164 = 1854 of 3385+1690+164 = 5239) are non-exact
provenance, and 1690 of them are **harness-synthesized entry/exit sentinels that
do not exist in the mined source**. Keep this in mind for §5.2 — it is the crux
of the only non-zero certification number in the run.

---

## 3. Per-policy verdicts (the raw table)

Six deployer policies, each evaluated against all 912 graphs → **5472 pairs**.
`[unsafe, unknown, applicable]` are from the run record; `safe = 912 − unsafe −
unknown` is derived. "applicable" = graphs the policy is judged relevant to.

| Policy | unsafe | unknown | **safe** | applicable |
|---|---:|---:|---:|---:|
| approval_before_financial | 1 | 911 | **0** | 98 |
| approval_before_delete | 0 | 912 | **0** | 97 |
| approval_before_execute | 4 | 908 | **0** | 102 |
| never_dangerous_tool | 0 | 912 | **0** | 1 |
| human_before_sensitive | 5 | 907 | **0** | 103 |
| bounded_router | 0 | 912 | **0** | 229 |
| **Aggregate** | **10** | **5462** | **0** | — |

Read the table two ways:

- **safe = 0 in every row.** Under the sound default there is not a single
  certified-safe (policy, graph) pair anywhere in the corpus.
- **Applicable ≠ decided.** For `bounded_router`, 229 graphs are applicable yet
  **all 912** resolve to UNKNOWN (0 unsafe, 0 safe). The over-approximation
  swamps even the graphs the policy was designed to speak to.

---

## 4. Tool-effect landscape — the actual finding, with its own artifact caveat

| Effect class | Distinct tool names |
|---|---:|
| unknown | **25** |
| read | 22 |
| financial | 4 |
| execute | 1 |
| write | 1 |

- **180** total tool nodes; **157** of the 180 *bindings* (87%) are effect-UNKNOWN.
- A binding of UNKNOWN effect **may-match any effect predicate** — this is the
  correct, conservative over-approximation, and it is exactly what drives the
  99.8% UNKNOWN rate.
- Genuinely sensitive distinct tools across all 912 graphs: **3** —
  `restart_service`, `rollback_deploy`, `read_financial_document`.

**Why this is genuine.** The resolvability distribution (25 distinct unknown
names covering all 157 unknown bindings; 23 of 180 with a resolved effect) is a
real measurement of mined agent code. It says the certifiability gap is *small
and structured*: a bounded dictionary, not an open-ended modeling problem.

**Why the UNKNOWN-domination it produces is an artifact, not a discovery.** The
99.8% UNKNOWN and 0.0 strict certification are consequences of the **effect
classifier**, not of workflow topology. This re-confirms Paper 1's stated binding
constraint (extraction/effect fidelity, not topology). It sharpens that thesis on
a new axis; it does not overturn or newly discover it.

---

## 5. Certification: 0.0 under the sound default; 0.492 only by assumption

Denominator: **252** graphs with at least one applicable policy.

| Setting | Certified safe | Rate |
|---|---:|---:|
| **Strict sound default** | **0 / 252** | **0.000** |
| Sentinel-exempt (ASSUMPTION) | 124 / 252 | **0.492** |

### 5.1 Strict rate = 0.0 is the real number

Under the analyzer's actual sound default, **zero** graphs certify. This is the
number that describes the shipped system on real data.

### 5.2 The 0.492 is knob-dependent and certifies fictitious nodes

`sentinel_exempt_rate = 0.492` comes entirely from **treating synthesized
entry/exit/passthrough NONE-effect sentinels as certifiable regardless of
provenance** — the run record itself flags this as *"an ASSUMPTION, not the
default."* Those sentinels are among the **1690 heuristic-synthesized nodes that
do not exist in the mined source**. So the single number that makes the system
look like it "works" (49.2%) is produced by certifying behavior-free, fictitious
nodes by fiat. It is **provenance-blind by design** and must not carry a headline.

**Bottom line:** the honest certification result on real data is **0.0**. The
0.492 is an assumption knob, reported for transparency, not as a result.

---

## 6. Repair substrate: NULL on real data

| Quantity | Value |
|---|---:|
| definite_unsafe_targets | **10** |
| repaired_to_checkable_safe | **0** |
| checker_accepted | **0** |

The detect → repair → certify loop — the paper's core mechanism — **closes zero
times** on 912 real graphs. Reason from the run note: *a lossy extraction region
is not proof-eligible, so no repair yields a checkable certificate.* This was
solver-only (LLM proposer not exercised on this corpus).

**Proof-carrying repair carries no proof on any of the 912 graphs.** Its only
positive evidence remains the synthetic seed suite, which is circular (§9).

---

## 7. Static/runtime partition (E5): nothing certified, everything routed

| Quantity | Value |
|---|---:|
| effect_node_visits | **1080** |
| certified_safe | **0** |
| runtime_routed_unknown | **1070** |
| certifiable_fraction | **0.0** |

Of 1080 effect-node visits, **0** are statically certified and **1070** are
routed to runtime as UNKNOWN. The RQ5 promise — certificates *reduce* expensive
runtime oversight — is **unrealized on real data**: the static layer discharges
none of the runtime burden here.

---

## 8. "Zero false certificates" holds VACUOUSLY

| Quantity | Value |
|---|---:|
| safe_results_audited | **0** |
| violations | **0** |
| passed | **true** |

The run record annotates this itself: *"holds VACUOUSLY — 0 SAFE results exist at
all under the sound default."*

You cannot mint a *false* certificate when you mint **no** certificates. On this
corpus "zero false SAFE" is **indistinguishable from "the analyzer always says
UNKNOWN"**: strict_rate = 0.0, certifiable_fraction = 0.0, 0/1080 visits
certified. Soundness is a *by-construction* property of tri-valued
over-approximation; this run demonstrates conservatism-under-loss, **not** that
the certificate mechanism adds verified value on real code. The safety headline
is empty in the wild.

---

## 9. Prior synthetic + live-LLM results carry no real-data efficacy

- Benchmark: **10 synthetic seed tasks**; mutations are the **inverses of the
  repair operators** → circular by construction.
- LLM-only silent policy-violation rate: **40%** glm-5.2, **50%**
  deepseek-v4-pro, **62%** qwen3.5-397b. The certificate checker caught them with
  **0 false certificates** across all models.
- Verified-repair **yield delta over LLM-only**: **+0 to +1 tasks**, exact
  **McNemar p = 1.0, n ≤ 10.**

The checker-catches-silent-failures signal (40–62% caught, 0 false certificates)
is genuine but *on synthetic data*. The **yield** claim is null (+0..+1, p=1.0)
and rests on a benchmark engineered to be repairable. No efficacy claim survives
to the real corpus.

---

## 10. Genuine vs. artifact — the adjudication

| Result | Status | Why |
|---|---|---|
| Effect-resolvability distribution (25 unknown names, 3 sensitive tools, 157/180 unknown bindings) | **GENUINE** | Real measurement of mined agent code; bounds the gap |
| Extraction fidelity (not topology) is the binding constraint | **GENUINE** (confirmatory) | Re-derives Paper 1's thesis on the effect axis at corpus scale |
| Soundness direction (10 definite-unsafe are one-directional; no false SAFE) | **GENUINE** but by-construction | Over-approximation is correct; not *validated* by a positive certificate |
| Cost: 0.38 ms/graph, 1.2 s total | **GENUINE** but low-value | Speed of a near-no-op; near-everything reduces to UNKNOWN |
| 99.8% UNKNOWN / strict rate 0.0 | **ARTIFACT** of the effect classifier | 157/180 unknown bindings may-match anything |
| sentinel_exempt 0.492 | **ARTIFACT / knob** | Certifies 1690 fictitious synthesized sentinels; "an ASSUMPTION, not the default" |
| zero-false-SAFE audit passed | **VACUOUS** | 0 SAFE audited |
| repaired_to_checkable_safe = 0 | **NULL** | Loop closes zero times on real code |
| 299 may-violation candidates | **UNVALIDATED** | No ground truth; dominated by unknown-effect over-approximation (see §11) |

---

## 11. What the data explicitly does NOT support

1. **No efficacy of certification on real data** — 0 SAFE, strict rate 0.0.
2. **No efficacy of proof-carrying repair on real data** — 0/10 repaired to
   checkable-safe, 0 checker-accepted.
3. **No validated true positive** — the **299** may-violation candidates are
   self-labeled **UNVALIDATED**, dominated by unknown-effect nodes that may-match
   anything; they are **not** ground-truth defects and must not be reported as
   found bugs. The 10 UNSAFE are raw analyzer verdicts, unlabeled.
4. **No prevalence / population claim** — the corpus is a GitHub convenience
   sample skewed to tutorials/demos/chatbots; only **3** sensitive distinct tools
   and **10** total UNSAFE pairs. Sensitive behavior is near-absent by
   construction of the sample; no population parameter is being estimated.
5. **No inferential statistics** — no CIs, no per-framework outcome
   stratification (adk n=51 supports no inference), no precision/recall (no
   labels).
6. **No non-vacuous safety guarantee** — see §8.

---

## 12. Threats to validity

- **Sample bias.** Tutorials/demos/chatbots dominate; the near-zero base rate of
  sensitive behavior is a property of *where we mined*, not of agents in
  production.
- **Effect-classifier ceiling.** 157/180 unknown bindings set the over-approximation
  floor; the analyzer's verdicts are a joint function of (sample composition) ×
  (classifier coverage), not of the verification logic in isolation.
- **Extraction loss.** 1690 heuristic + 164 may nodes; 1022 heuristic + 972 may
  edges. Non-exact provenance regions are not proof-eligible, which is *why*
  repair never certifies.
- **No ground truth.** Nothing (299 candidates, 10 UNSAFE) is human-validated, so
  no precision/recall/yield is computable even in principle from this run.
- **Pipeline fragility (disclosed).** See §14 — a prior IR-lift bug inflated
  candidate counts; the harness has a demonstrated history of artifact-driven
  numbers, so unvalidated counts inherit suspicion.

---

## 13. The decisive experiment — RUN, and its result

The panel's #1 threatening re-analysis (hand-label the unknown tool names and
re-run — "if certification jumps off 0.0 it is a classifier artifact") **was
executed**. There turned out to be only **12** distinct unknown tool names (30
bindings), hand-labelable in minutes (`page_oncall`→communicate; the rest read;
generic `tool` left unknown). Re-running all 6 policies × 912 graphs with the
labels applied:

| metric | baseline | hand-labeled | Δ |
|---|---:|---:|---:|
| SAFE | 0 | **0** | **+0** |
| UNSAFE | 10 | 10 | 0 |
| UNKNOWN | 5462 | 5462 | 0 |
| may-violation candidates | 299 | **251** | **−48** |

Plus the **effect-independent structural ceiling**: the number of graphs whose
*entire reachable structure* is exact-provenance (the necessary condition for any
SAFE proof) is **0 / 912**.

**Result — the two bottlenecks are now cleanly separated:**

1. **Strict certification 0% is NOT an effect-classifier artifact.** Labeling
   every effect left SAFE at **0** — it did not move at all — because **0/912**
   graphs have a fully-exact reachable structure. Every mined graph carries at
   least one heuristic/`may`/synthesized element (chiefly the synthesized
   entry/exit sentinels inherent to AST extraction), so **no graph can *ever*
   certify SAFE regardless of effect labels.** The 0% is a **structural
   provenance/extraction constraint**, not a dictionary gap. *(This refines the
   §10 adjudication: the panel attributed strict-rate-0.0 to the effect
   classifier; the experiment shows the SAFE=0 outcome specifically is
   provenance-driven. The effect classifier drives the UNKNOWN-vs-UNSAFE split,
   not the absence of SAFE.)*
2. **The candidate count WAS partly an effect artifact.** may-candidates fell
   299 → 251 from just **11** labels, confirming the panel's suspicion that the
   candidate total is inflated by unknown-effect over-approximation — and it would
   fall further with a full corpus dictionary.

So the honest decomposition is: **effect resolvability gates the *candidate
noise*; provenance/extraction fidelity gates *certifiability itself* — and on
this corpus the latter is 0/912, a hard structural ceiling.** That is a sharper,
stronger version of §1, and it survived the decisive test.

**Still needed to make any of this publishable** (unchanged): a **human-labeled
sub-sample** so the 251 may-candidates and 10 UNSAFE acquire precision/recall;
per-framework stratified reporting with Wilson/Clopper–Pearson intervals; a
corpus slice with production-grade sensitive operations (or explicit scoping to
tutorials); and — to lift certification off the structural 0% — a
higher-fidelity front-end (runtime-trace or instrumented extraction) that yields
exact provenance, since AST extraction provably cannot.

---

## 14. Engineering note — disclosed bug (why prior candidate counts were inflated)

Running on real data exposed and fixed a real bug in the IR lift:
`state_predicates` was built as a **char-tuple**, so lifted nodes received **no
capability** and `Approval()` was **invisible on lifted graphs**. Pre-fix
candidate counts were **inflated artifacts**. The corrected numbers in this
document are, if anything, **conservative** (the fix *removed* spurious
candidates). This is a genuine finding about pipeline fragility and is the reason
the 299 unvalidated candidates are treated with suspicion, not as defects.

---

## 15. Reviewer consensus and venue implication

Four independent hostile reviews (artifact-hunter, novelty-venue, statistician,
soundness-auditor):

- **Verdicts:** 3 × major-revision, 1 × reject. Unanimous on the substance.
- **Unanimous positive:** exactly one honest claim survives — the
  **extraction/effect-fidelity ceiling** measured over 912 real graphs (§1).
- **Unanimous negative:** certification and repair **efficacy** are unsupported on
  real data (0 and 0); the safety headline is **vacuous** (§8); the 0.492 is a
  **knob** on fictitious nodes (§5.2); the 299 candidates are **unvalidated**;
  the synthetic yield is **circular** (§9).

**Implication for framing.** As a *proof-carrying-repair / certification efficacy*
paper this is **not** submittable to top-ML or ICSE/FSE/ASE main track on these
numbers: the system yields **0** certificates and **0** checkable repairs on its
target domain. Reframed **honestly as a measurement / negative-result study** it
is publishable and defensible — MSR (it is literally a mining study of 912 GitHub
workflows), an SE empirical/measurement or experience track, or an
LLM-agent-safety / SE-for-agents workshop. Working reframe:

> *"Mined agent workflows are not yet proof-eligible: measuring the
> extraction-fidelity ceiling on sound static verification of tool-using
> agents."* Under a sound tri-valued analyzer, 99.8% of policy/node pairs across
> 912 real workflows resolve to UNKNOWN and 0% certify under a strict sound
> default because 157/180 tool effects are unresolved — establishing effect
> resolution, not topology, as the binding constraint, and motivating
> effect-annotation / runtime attestation as the necessary next layer.

To clear even MSR: drop the verifier/repair headline claims, foreground the
fidelity ceiling as the measured object, and add a validated sub-sample so
true/false may-violations acquire precision/recall (§13).

---

## 16. Independent self-validation (re-derived from raw files, core API only)

The §1–§15 numbers came partly from an agent-built harness
(`benchmarks/real_corpus/`). They were independently re-derived from the raw
corpus JSON using **only** the core `graph_from_dict` → `MayMustGraph.from_agent_graph`
→ `product.check` / `region_is_certifiable` path (no harness), and cross-checked:

- **Confirmed:** 912/912 UNKNOWN, **0 SAFE**, and **0/912 graphs with a fully-exact
  reachable structure**. The one difference from the harness — the single UNSAFE
  under `approval_before_financial` — is **fully explained**: the harness tags tool
  effects by name (`read_financial_document`→FINANCIAL), which the plain core lift
  leaves UNKNOWN; that tag turns one may-financial into a must-financial on a MUST
  path. Every difference is accounted for; the 0-SAFE headline is identical either way.

- **Refined (and a self-correction).** The 0% is provenance-driven, but it further
  decomposes — and this partly **vindicates the panel's "knob" critique** that §13
  understated:
  - **302 / 912** graphs are blocked **solely by the synthesized `__start__`/`__end__`
    sentinel nodes** (heuristic, effect-none, no policy atom). These are structural
    markers AST extraction inserts, not guessed source; exempting them is defensible,
    and doing so is exactly what lifts the "sentinel-exempt" number off 0. So for a
    third of the corpus, uncertifiability is a **sentinel-modeling choice**, not a
    real extraction failure. (My earlier §13 framing — "purely structural, the knob
    doesn't matter" — was too strong; the sentinel knob is load-bearing for ~33%.)
  - **610 / 912** have **genuine deeper loss**: 511 carry non-exact (`may`/heuristic)
    edges, 99 carry guessed non-sentinel nodes. No sentinel exemption fixes these —
    this is the real extraction-fidelity ceiling.

- **Mechanism, on one real graph** (`NordicAgents…langgraph_customer_support`, 6
  nodes): `router`/`agent` extract **exact**; `__start__`/`__end__` are
  synthesized-heuristic; `escalate_human` is `may`; `tool_call` is `may` + effect
  **UNKNOWN** + `incomplete_schema`. The analyzer returns UNKNOWN with a may-witness
  ending at `tool_call` — a **correct, sound** verdict (it cannot prove
  approval-before-financial when the tool's effect is unknown on a guessed path).

- **Candidates are over-approximation, verified by trace.** A sampled
  `may_violation_candidate` witness ends at `yt_tool` with effect **UNKNOWN**, which
  may-matches *any* effect predicate — i.e. "this graph has an unresolved tool," not
  "this graph violates a financial policy." Confirms §11's caveat directly.

**Net:** the reported results hold under independent re-derivation; the mechanism is
understood; the honest ceiling is *"≤ ~33% certifiable even if you trust your own
sentinels, and far lower otherwise,"* with effect resolvability a separate, smaller
issue affecting only candidate noise.

---

### Appendix A — Full number ledger (as cited)

Corpus: n=912; langgraph 401 / autogen 345 / crewai 115 / adk 51. Nodes 3385
exact / 1690 heuristic / 164 may. Edges 4560 exact / 1022 heuristic / 972 may.
Tools: 180 nodes; distinct-by-effect unknown 25 / read 22 / financial 4 /
execute 1 / write 1; 157/180 bindings unknown-effect; 3 genuinely sensitive
(`restart_service`, `rollback_deploy`, `read_financial_document`).
Per-policy [unsafe, unknown, applicable]: financial [1, 911, 98]; delete
[0, 912, 97]; execute [4, 908, 102]; never_dangerous [0, 912, 1]; human_sensitive
[5, 907, 103]; bounded_router [0, 912, 229]. Aggregate: safe 0, unsafe 10,
unknown 5462, pairs 5472. Certification: denom 252; strict safe 0 (rate 0.0);
sentinel-exempt safe 124 (rate 0.492). may-candidates 299 (unvalidated). Repair:
targets 10, repaired-to-checkable-safe 0, checker-accepted 0. E5: visits 1080,
certified 0, runtime-routed-unknown 1070, certifiable-fraction 0.0.
Zero-false-safe: audited 0, violations 0, passed (vacuous). Timing: 1.2 s total,
0.38 ms/graph. Synthetic/LLM: 10 circular seed tasks; silent-failure 40% glm-5.2
/ 50% deepseek-v4-pro / 62% qwen3.5-397b; 0 false certificates; yield delta
+0..+1, McNemar p=1.0, n≤10.
