# Claims Audit — AAAI-27 submission (Day-1 gate, plan 3.2 / 3.7)

**Date:** 2026-07-13. **Scope:** every quantitative claim in
`papers/paper1/aaai/main.tex` and `papers/paper1/aaai/sections/*.tex`, plus
every qualitative soundness/guarantee claim, traced to its generating
artifact. `ReproducibilityChecklist.tex` (a yes/no form) was skimmed but not
audited row-by-row.

**Status vocabulary** (one per claim):

- `traced-to-artifact` — value is in a committed artifact produced by a
  documented command.
- `needs-rerun-after-semantics-change` — value is artifact-backed but depends
  on temporal/DSL semantics or corpus definitions still being changed; must be
  regenerated before freeze.
- `hand-written-unverified` — no committed artifact emits the value; it was
  derived by hand (the Note column says whether this audit's independent
  recomputation confirmed it).
- `unknown-origin` — could not find any artifact, script, or recomputation
  path that yields the value.

**Generating commands referenced below** (run from repo root):

| artifact | command |
|---|---|
| `corpus/real_world/validated_results.json` | `python scripts/aggregate_realworld.py` |
| `corpus/real_world/revision_analyses.json` | `python scripts/revision_analyses.py` |
| `corpus/real_world/confidence_intervals.json` | `python scripts/compute_cis.py --validated corpus/real_world/validated_results.json` |
| `corpus/real_world/gt_triage_results.json`, `gt_flags_for_triage.json` | LLM triage workflow: `scripts/wf_validate_triage.js` / `scripts/wf_run_v2.js` over flags emitted by `scripts/revision_analyses.py` |
| `corpus/real_world/defect_results.json` | `python scripts/defect_study.py --corpus corpus/real_world/graphs --output corpus/real_world/defect_results.json` |
| `corpus/real_world/monitor_pruning{,_curated}.json` | `python scripts/monitor_pruning.py [--corpus ...]` |
| `corpus/real_world/risk_aware_gate{,_curated}.json` | `python scripts/risk_aware_gate.py [--corpus ...]` |
| `corpus/real_world/runtime_fidelity.json` | `python scripts/runtime_fidelity.py` |
| `corpus/real_world/metadata*.json` | `python scripts/mine_github_gh.py --search --clone --extract` |
| `scripts/defect_results.json` (curated) | `python scripts/defect_study.py --corpus corpus/curated --output scripts/defect_results.json` |
| `scripts/policy_evaluation_results.json` | `python scripts/evaluate_policies.py` |
| `scripts/scaling_results.json` | `python scripts/benchmark_scale.py` |

---

## 1. Quantitative claims

### 1.1 main.tex (abstract)

| # | Claim (short) | Location | Value | Generating artifact / command | Status | Note |
|---|---|---|---|---|---|---|
| A1 | four frameworks, unified extraction | main.tex:38 | 4 | `src/agentproof/graph/extract/_{langgraph,autogen,crewai,adk}.py` | traced-to-artifact | code |
| A2 | six structural checks | main.tex:39 | 6 | `src/agentproof/verify/structural.py` (6 core + optional gate) | traced-to-artifact | |
| A3 | temporal DSL, seven forms | 01_intro.tex:61; 02_system.tex:50 (S8) — **not** in the abstract, which states no form count | 7 forms | `scripts/policy_evaluation_results.json` `dsl_form_counts` (7 keys) | needs-rerun-after-semantics-change | regenerate if any DSL form is removed per plan 3.4B |
| A4 | 922 workflows / 252 repos | main.tex:44 | 922; 252 | `revision_analyses.json` `composition.mined`; recount of `corpus/real_world/graphs/` minus 8 self-repo files confirms | traced-to-artifact | |
| A5 | 119-workflow validated sample | main.tex:45 | 119 | `revision_analyses.json` `prevalence_gt.n_gt_workflows` | traced-to-artifact | `validated_results.json` has n=120 (pre-exclusion) |
| A6 | flags genuine: 2 of 186 (1.1%) | main.tex:48–49 | 2/186, 1.1% | `revision_analyses.json` `cluster_cis.flag_ppv_after_exclusion` | traced-to-artifact | `confidence_intervals.json` computes the CI on 2/187 (pre-exclusion) |
| A7 | every structural flag an extraction artifact | main.tex:49 | 0 genuine | `validated_results.json` `triage.by_check` (0 real among structural) | traced-to-artifact | |
| A8 | prevalence 4/119 (3.4%, CI [1.3,8.3]%) | main.tex:51–52 | 4/119; CI | counts: `gt_triage_results.json` (2 real) + `validated_results.json` triage (2 real). CI: **no artifact** | hand-written-unverified | audit recompute (Wilson) confirms 3.4% [1.3,8.3]; add to `compute_cis.py` |
| A9 | 7.7% app-like vs 1.3% tutorials | main.tex:53–55 | 3/39; 1/80 | derived from `gt_triage_results.json` `classification` + the 4 defect slugs; **no artifact** | hand-written-unverified | audit confirms 3/39=7.7%; 1/80=1.25% (paper rounds to 1.3%) |
| A10 | edge recall 0.65 real code | main.tex:54 | 0.649 | `revision_analyses.json` `confidence.fidelity_all` | traced-to-artifact | |
| A11 | edge recall 0.38 on ADK | main.tex:55 | 0.382 (n=24) | **no artifact** emits per-framework fidelity after self-repo exclusion; `validated_results.json` says 0.367 (n=25) | hand-written-unverified | audit recompute from `fidelity_details` minus self-repo gives exactly 0.382; commit the recompute |
| A12 | 93% monitors provably inert (curated) | main.tex:58 | 251/270, 93.0% | `monitor_pruning_curated.json` | needs-rerun-after-semantics-change | rerun after any further temporal-semantics fix |
| A13 | all pruning alphabet-level today | main.tex:58–59 | reach-proven 0 | `monitor_pruning_curated.json` (`trivially_inert` 251, `reachability_proven_inert` 0) | needs-rerun-after-semantics-change | prune rule tightened to `verdict == "safe"` this session (item 15); smoke rerun keeps reach-proven 0 but the headline counts change (237/270 vs 251/270) |

### 1.2 sections/01_intro.tex

| # | Claim (short) | Location | Value | Generating artifact / command | Status | Note |
|---|---|---|---|---|---|---|
| I1 | six checks / seven-form DSL | 01_intro.tex:30 (six checks), :61 (seven-form) | 6; 7 | as A2/A3 | traced-to-artifact | |
| I2 | 922 / 252; 119 sample | 01_intro.tex:33–35 | — | as A4/A5 | traced-to-artifact | |
| I3 | flag precision 1.1% (2/186) | 01_intro.tex:42 | — | as A6 | traced-to-artifact | |
| I4 | prevalence 4/119 (3.4%) | 01_intro.tex:43–44 | — | as A8 | hand-written-unverified | CI not restated here |
| I5 | "two genuine defects, **including a payment-adjacent missing-human-gate**, were invisible to the lossy extraction" | 01_intro.tex:44–46 | — | contradicted by artifacts | unknown-origin | **DISCREPANCY:** the payment defect (`Zen7-Labs__Zen7-Payment-Agent`) was extractor-visible (human_presence flag, `validated_results.json`); the two GT-only defects are SQL-related (`gt_triage_results.json`: ADK SQL-agent router mis-wiring; SQL-chatbot ungated tool). Fix the sentence |
| I6 | 3 of 39 vs 1 of 80 | 01_intro.tex:47–49 | — | as A9 | hand-written-unverified | audit-confirmed |
| I7 | one third application-like, two thirds tutorial/demo/test | 01_intro.tex:57–58 | 39/119 = 33% | `gt_triage_results.json` `classification` (39/52/20/8) | traced-to-artifact | |
| I8 | edge recall 0.65 / 0.38; near-perfect on stubs | 01_intro.tex:66–67 | — | as A10/A11; stubs: `scripts/extractor_accuracy.py` | hand-written-unverified | stub-accuracy output not committed as an artifact |
| I9 | structural flags only from the one non-connected-topology extractor | 01_intro.tex:68–71 | LG-only | recomputable from `corpus/real_world/defect_results.json` (LG 314/400 = 78.5%; others 0) | hand-written-unverified | audit-confirmed; no committed script emits the split |
| I10 | 251 of 270 (93%) inert | 01_intro.tex:76–78 | — | as A12 | needs-rerun-after-semantics-change | |

### 1.3 sections/02_system.tex

| # | Claim (short) | Location | Value | Generating artifact / command | Status | Note |
|---|---|---|---|---|---|---|
| S1 | node-kind vocabulary (7 kinds listed) | 02_system.tex:17–20 | 7 kinds | `src/agentproof/graph/model.py` `NodeKind` has **8** (paper omits `passthrough`) | hand-written-unverified | **DISCREPANCY:** GT graphs and kind-accuracy scoring use `passthrough`; paper text should list it or explain the projection |
| S2 | checks each O(\|V\|+\|E\|) | 02_system.tex:31 | complexity | `structural.py` | hand-written-unverified | **imprecise:** `router_shape` scans all edges per router (structural.py:196–197), worst case O(\|V\|·\|E\|); reachability checks are linear |
| S3 | DFA sizes: 2–3 states base, k+2 bounded | 02_system.tex:56–57 | 2–3; k+2 | `src/agentproof/monitor/ltl.py` (states are canonical formulas) | hand-written-unverified | no test asserts state counts; add one or soften |
| S4 | runtime monitors O(1)/event | 02_system.tex:60–61 | O(1) | `monitor/ltl.py` transition lookup | traced-to-artifact | code |
| S5 | abort ⇒ inconclusive (3-valued) | 02_system.tex:62–64 | — | `monitor/ltl.py` (`MonitorDecision`) | traced-to-artifact | verify a test pins the abort case |
| S6 | product bounded by \|V\|·\|Q\|, linear | 02_system.tex:75–76 | — | `src/agentproof/verify/temporal.py` BFS over product | traced-to-artifact | code |
| S7 | soundness under trace containment | 02_system.tex:79–83 | qualitative | `verify/temporal.py` + premise text | see §2 Q1 | conditional pass; multi-tool caveat Q2 now closed (native conservative closure) |
| S8 | "each of the seven DSL forms denotes an LTL$_f$ formula" | 02_system.tex:50 | 7 forms | as A3 (`scripts/policy_evaluation_results.json` `dsl_form_counts`, 7 keys) | needs-rerun-after-semantics-change | occurrence previously missing from this audit (was mis-anchored to the abstract); same basis and rerun condition as A3 |

### 1.4 sections/03_realworld.tex

| # | Claim (short) | Location | Value | Generating artifact / command | Status | Note |
|---|---|---|---|---|---|---|
| R1 | mining window "February–March 2026" | 03_realworld.tex:11 | dates | none | unknown-origin | **DISCREPANCY:** `corpus/real_world/FINDINGS.md` says the study started 2026-07-11, and git history commits the mining artifacts on 2026-07-11 (`728298c`, `e936b1b`). Correct the dates |
| R2 | self-repo contamination: 1 repo, 8 files | 03_realworld.tex:15–16 | 8 | `revision_analyses.json` `composition.excluded_self_repo_workflows` (8 slugs) | traced-to-artifact | |
| R3 | 922 / 252; LG 400, AutoGen 359, CrewAI 113, ADK 50 | 03_realworld.tex:17–18 | — | `composition.mined` + per-framework recount of `graphs/` | traced-to-artifact | per-framework split confirmed by audit recount; add it to `revision_analyses.py` output |
| R4 | median 2 non-sentinel nodes (mean 3.9) | 03_realworld.tex:19 | 2; 3.88 | `composition.mined_nonsentinel_{median,mean}` | traced-to-artifact | |
| R5 | 32% tutorial/test-style names | 03_realworld.tex:20 | 32.3% | `composition.mined.tutorial_test_named_pct` | traced-to-artifact | |
| R6 | 48 duplicate topology groups; 170 redundant | 03_realworld.tex:21–22 | 48; 170 | `composition.duplicate_topology_*` | traced-to-artifact | artifact field is groups with >3 nodes; paper says "byte-identical" — align wording |
| R7 | census 44% / 17% / 7% / 33% | 03_realworld.tex:23–24 | 52/20/8/39 of 119 | `gt_triage_results.json` `classification` | traced-to-artifact | 43.7/16.8/6.7/32.8 rounded |
| R8 | sample: 119 from 87 repos (40/20/35/24) | 03_realworld.tex:28–29 | — | `composition.sample` (n=119, 87 repos); per-framework from `fidelity_details` minus self-repo | traced-to-artifact | ADK 24 = 25−1 excluded |
| R9 | two LLM passes, Claude Opus 4.8, outputs released | 03_realworld.tex:29–31 | provenance | `scripts/wf_run*.js`, `wf_validate_triage.js`; outputs in `corpus/real_world/` | hand-written-unverified | model/harness version not recorded in any artifact; add to metadata |
| R10 | GT confidence 77 / 33 / 9 | 03_realworld.tex:33 | — | `revision_analyses.json` `confidence.gt_confidence_distribution` | traced-to-artifact | |
| R11 | adversarial verifier overturned 4.6% | 03_realworld.tex:36–37 | 4.6% | `FINDINGS.md` (131-flag first pass, 60-workflow sample) | needs-rerun-after-semantics-change | **stale denominator:** current triage has 187 flags; recompute the overturn rate on the current set or date-scope the sentence |
| R12 | edge recall 0.67 high-conf vs 0.65 overall | 03_realworld.tex:42–43 | 0.674 / 0.649 | `confidence.fidelity_high_confidence_only` / `fidelity_all` | traced-to-artifact | |
| R13 | 1 of 16 labels overturned in re-audit | 03_realworld.tex:44–45 | 1/16 | `gt_triage_results.json` (merdandt: primary intentional → final gt_error) | traced-to-artifact | |
| R14 | Wilson CIs; clustered bootstrap 10,000 | 03_realworld.tex:46–48 | 10,000 | `compute_cis.py`, `revision_analyses.py` (`bootstrap_B` 10000) | traced-to-artifact | |
| R15 | Table 1 rows: LG .956/.682/.647; CrewAI .700/.692/.929; AutoGen .957/.770/.900 | 03_realworld.tex:60–62 | — | `validated_results.json` `per_framework` | traced-to-artifact | |
| R16 | Table 1 ADK row: n=24, .420/.382/.940 | 03_realworld.tex:63 | — | **no artifact** (committed per-framework numbers are n=25: .403/.367/.943) | hand-written-unverified | audit recompute (fidelity_details minus self-repo) reproduces .420/.382/.940 exactly; commit the recompute |
| R17 | Table 1 overall .805/.649/.829 + CIs [.72,.89]/[.56,.73]/[.78,.87] | 03_realworld.tex:65–66 | — | precision/recall/CIs: `confidence.fidelity_all` + `cluster_cis.{edge_precision,edge_recall,kind_accuracy}`; kind accuracy .829 traces only to the PRE-exclusion n=120 run (`validated_results.json` `extractor_fidelity_real_code.overall.kind_accuracy`) | hand-written-unverified | **DISCREPANCY:** the post-exclusion artifact says **0.828** (`revision_analyses.json` `confidence.fidelity_all.kind_accuracy`, n=119); change 0.829→0.828 at 03_realworld.tex:65 and :73 (or regenerate on n=119) |
| R18 | node P=0.91, R=0.85 | 03_realworld.tex:72 | 0.907/0.848 | `validated_results.json` `overall` (n=120, includes self-repo) | traced-to-artifact | post-exclusion recompute = 0.909/0.854, same at 2 d.p.; regenerate on n=119 for consistency |
| R19 | ADK edge recall 0.38, cluster CI [0.14,0.62] | 03_realworld.tex:73–74 | CI | **no artifact**; `confidence_intervals.json` ADK CI is [0.20,0.55] (unclustered, n=25) | unknown-origin | per-framework **clustered** CIs are not produced anywhere; generate or cite the unclustered one |
| R20 | AutoGen edge recall 0.77 | 03_realworld.tex:74–75 | 0.770 | `validated_results.json` | traced-to-artifact | |
| R21 | AST recovers 0.71 of runtime LangGraph edges | 03_realworld.tex:84–86 | 0.709 | `runtime_fidelity.json` `ast_vs_runtime_aligned.edge_recall` | traced-to-artifact | caveat: n=2 aligned workflows; state n in paper |
| R22 | ADK runtime graph 16 vs ~5 edges | 03_realworld.tex:86 | 16 vs 6; 13 vs 5 | `runtime_fidelity.json` rows | traced-to-artifact | "~5" blends 6 and 5 AST edges; acceptable but imprecise |
| R23 | Table 2 (triage): rows summing 2/79/93/12, total 186 | 03_realworld.tex:97–111 | — | `validated_results.json` `by_check` **manually re-tabulated**: self-repo flag removed (human_presence artifact 9→8), `router-non-conditional-edges` merged into router_shape (2+1=3), `sensitive-path…` renamed human_gate_coverage | hand-written-unverified | audit confirms the arithmetic; write a table-generating script so no hand merge remains |
| R24 | 2/186 = 1.1%, CI [0.3,3.8]% | 03_realworld.tex:115–116 | — | CI from `confidence_intervals.json` `genuine_of_all_flags` = 2/**187** [0.29,3.82] | traced-to-artifact | recompute on 186 identical at 1 d.p.; regenerate post-exclusion |
| R25 | 42% artifacts, 50% intentional | 03_realworld.tex:117–118 | 42.8 / 49.7 | `confidence_intervals.json` fractions (on 187) | traced-to-artifact | |
| R26 | 72 structural flags, 0 genuine, CI [0,5.1]% | 03_realworld.tex:118–120 | 0/72 | `confidence_intervals.json` `structural_genuine` [0, 5.07] | traced-to-artifact | |
| R27 | structural flags: 78% of LG, 0% others | 03_realworld.tex:121–123 | 78.5% / 0 | recomputable from `corpus/real_world/defect_results.json` | hand-written-unverified | audit-confirmed; add to a committed analysis output |
| R28 | 16 GT flags: 10 intentional, 4 recon errors, 2 genuine | 03_realworld.tex:133–139 | 10/4/2 | `gt_flags_for_triage.json` (16) + `gt_triage_results.json` final labels | traced-to-artifact | primary labels were 11/3/2; final (post-verify) are 10/4/2 — cite final |
| R29 | the 2 originals re-confirmed by second adversarial pass | 03_realworld.tex:140–141 | 2 | `gt_triage_results.json` `reverify` (2 entries) | traced-to-artifact | |
| R30 | 4/119 (3.4%), 4/87 (4.6%) | 03_realworld.tex:141–143 | — | counts traced (A8); proportions/CIs no artifact | hand-written-unverified | audit-confirmed |
| R31 | all 4 defective bind side-effecting tools; 3 of 4 app-like | 03_realworld.tex:144–145 | — | `gt_triage_results.json` `classification` (`has_side_effecting_tools` true for all 4; Zen7 is demo_or_toy, others application_like) | traced-to-artifact | audit-confirmed join; commit the join |
| R32 | Table 3 CIs: 2/119 [0.5,5.9]; 4/119 [1.3,8.3]; 4/87 [1.8,11.2]; 3/39 [2.7,20.3]; 1/80 (1.3%) [0.2,6.8] | 03_realworld.tex:159–163 | — | 2/119 from `cluster_cis.prevalence_per_workflow.wilson_ci_unclustered`; the rest: **no artifact** | hand-written-unverified | audit Wilson recompute confirms all except the last: 1/80 = 1.25% ("1.3" is round-up) and upper bound = **6.7**, not 6.8. Fix or regenerate |
| R33 | human-presence fires on 91% of mined | 03_realworld.tex:169 | 91.0% | `risk_aware_gate.json` `naive_flag_pct` | traced-to-artifact | computed on 930 incl. self-repo; rerun on 922 |
| R34 | 2 of 113 human-presence firings genuine | 03_realworld.tex:169–170 | 2/113 | `validated_results.json` by_check minus self-repo (93+10+8+2) | hand-written-unverified | audit-confirmed arithmetic |
| R35 | risk-aware gate fires on zero of 922 mined | 03_realworld.tex:172–174 | 0 | `risk_aware_gate.json` (`risk_aware_flags` 0, `workflows_with_sensitive_tool` 0) | traced-to-artifact | denominator is 930 in artifact; paper says 922 — rerun post-exclusion |
| R36 | side-effecting tools in 32 of 119 sampled | 03_realworld.tex:176–177 | 32 | `gt_triage_results.json` `classification` (32 true) | traced-to-artifact | |
| R37 | on reconstructions gate fires 3×, 1 genuine | 03_realworld.tex:179–181 | 3; 1 | `revision_analyses.json` `prevalence_gt.workflows_with_risk_aware_gate_flags` (3) + `gt_triage_results.json` (Sujas real; 2 intentional) | traced-to-artifact | |
| R38 | Table 1 caption: "Perfect on stubs" | 03_realworld.tex:53–54 | qualitative | `scripts/extractor_accuracy.py` output — **not committed** | hand-written-unverified | stronger than intro's "near-perfect on stubs" (I8, 01_intro.tex:67); both share the uncommitted-stub-artifact problem (item 12) — commit the artifact or soften both |

### 1.5 sections/04_results.tex

| # | Claim (short) | Location | Value | Generating artifact / command | Status | Note |
|---|---|---|---|---|---|---|
| C1 | curated corpus: 18 workflows, 4 frameworks | 04_results.tex:6–7 | 18 | `corpus/curated/` (18 files); `scripts/defect_results.json` | traced-to-artifact | |
| C2 | detects every injected structural defect | 04_results.tex:7–8 | qualitative | `scripts/defect_results.json` + `corpus/annotations/defect_labels.json` | hand-written-unverified | no committed list of *seeded* defects to check firing against; add a seeded-defect manifest. Also: the committed `scripts/defect_results.json` is stale — it predates the `reverse_reachability` check (item 14) |
| C3 | risk-aware flags 8 vs 10 blunt; declines 2 | 04_results.tex:8–13 | 8; 10; 2 | `risk_aware_gate_curated.json` | traced-to-artifact | |
| C4 | sub-second at 5,000 nodes | 04_results.tex:14–15 | 345 ms | `scripts/scaling_results.json` (structural_check_ms=345.2 @5000) | traced-to-artifact | |
| C5 | multi-tool nodes expanded to complete digraph | 04_results.tex:28–31 | qualitative | **stale:** the `expand_multitool` pre-pass was removed from `scripts/monitor_pruning.py` this session; `check_temporal_property`'s default mapper now expands multi-tool nodes natively (Q2 closed) | needs-rerun-after-semantics-change | rewrite 04_results.tex:28–31 to describe the native multi-tool closure (item 15) |
| C6 | 251/270 (93.0%), mean 13.9/15 skipped | 04_results.tex:33–35 | — | `monitor_pruning_curated.json` | needs-rerun-after-semantics-change | |
| C7 | every proven case alphabet-level; product adds 0 | 04_results.tex:36–40 | reach-proven 0 | `monitor_pruning_curated.json` | needs-rerun-after-semantics-change | prune rule tightened this session (item 15); smoke rerun still gives reach-proven 0, but the artifact must be regenerated |
| C8 | "the single case the earlier semantics 'won' was a live termination-obligation monitor" | 04_results.tex:40–43 | 1 (historical) | none — the pre-fix run is not committed | unknown-origin | keep only if the old result file is restored or the sentence is softened |
| C9 | none of the 922 mined invokes any of the 15 policies' tools | 04_results.tex:44–46 | 0 | `monitor_pruning.json` per_policy (14 policies alphabet-inert on all 930; `analyze_until_decision` kept for liveness) + `policy_evaluation_results.json` | traced-to-artifact | artifact denominator 930 incl. self-repo; rerun on 922 |
| C10 | 15 policies | 04_results.tex:33 | 15 | `corpus/policies/temporal_policies.json`; `policy_evaluation_results.json` dsl_form_counts sums to 15 | traced-to-artifact | |

### 1.6 sections/05_related.tex and 06_conclusion.tex

| # | Claim (short) | Location | Value | Generating artifact / command | Status | Note |
|---|---|---|---|---|---|---|
| X1 | extraction manufactures 42% of flags, hides half the genuine defects | 05_related.tex:34–36 | 42%; 2 of 4 | `confidence_intervals.json` artifact_fraction (42.8); 2 GT-only of 4 total defects | traced-to-artifact | |
| X2 | 922/252; 1.1%; 3.4%; 7.7% vs 1.3%; 0.65/0.38; 93% | 06_conclusion.tex:9–28 | — | duplicates of A4, A6, A8, A9, A10/A11, A12 | mixed | same statuses as the primaries |
| X3 | three of four extractors cannot express the target defects | 06_conclusion.tex:22–23 | qualitative | `scripts/ast_extractor.py` (AutoGen/CrewAI/ADK builders always emit connected sentinel topologies) | traced-to-artifact | code |
| X4 | prevalence CIs wide at n=119 | 06_conclusion.tex:38–39 | qualitative | — | traced-to-artifact | follows from R32 |
| X5 | artifact released under MIT | 06_conclusion.tex:44–46 | commitment | `LICENSE` (MIT) exists; **no anonymized artifact link in paper** | hand-written-unverified | hard gate 7 |
| X6 | four defects will be disclosed to maintainers | 06_conclusion.tex:53–55 (Ethical Statement) | commitment | **no disclosure record found in repo** | unknown-origin | hard gate 8 — currently FAIL |

---

## 2. Qualitative strong claims (soundness / guarantee statements)

| # | Claim | Location | Code that must back it | Assessment |
|---|---|---|---|---|
| Q1 | "no violation reachable" ⇒ property holds on every runtime execution, **given trace containment**; never claimed for lossy AST graphs | 02_system.tex:79–88; 04_results.tex:20–27 | `src/agentproof/verify/temporal.py` (`check_temporal_property`), `scripts/monitor_pruning.py` | Premise is stated and scoped correctly in text. Backing requires Q2 and Q3 to hold. |
| Q2 | product explores every event a node can emit | implied by Q1 | `verify/temporal.py` `check_temporal_property`: the default path natively closes over every finite invocation sequence of a multi-tool node's declared tools, including the empty sequence (docstring temporal.py:139–145; `_tool_symbols` / `_post_states` closure) | **CLOSED this session (uncommitted):** the former `tools[0]` false-proof gap (plan 2.3 item 3) is fixed by the native conservative multi-tool product; `monitor_pruning.py`'s now-redundant `expand_multitool` pre-pass was removed. Regenerate pruning artifacts (item 15). |
| Q3 | product covers bad prefixes, termination obligations, and **divergent obligations** (non-accepting product cycles) | 02_system.tex:66–76; main.tex:42–44 | `verify/temporal.py` (exit check + lasso check) | Implemented, and now scoped explicitly to finite maximal executions with a three-valued verdict — divergence downgraded from a violation to `inconclusive` (temporal.py:127–131, :153–159). Differential reference oracle now exists (`tests/oracles/ltlf_reference.py`, exercised by `tests/semantics/test_differential.py` and `test_required_properties.py`) and passed this session's verification run. Untracked — commit before freeze. |
| Q4 | DSL forms have precise LTL_f semantics | 02_system.tex:47–64 | `src/agentproof/monitor/ltl.py` (recursive `_Parser`, canonical-formula DFA states) | Nested until now parses recursively (audit-verified: `a U (b U c)` → recursive AST) and response-chain re-arming has a regression test (`tests/test_monitor_extended.py::test_rearm_mid_chain_rejected`), addressing plan 2.3 items 1–2. The plan-3.4A finite-trace oracle now exists (`tests/oracles/ltlf_reference.py` + `tests/semantics/`, green this session; untracked) — commit it before freeze. |
| Q5 | six checks run in O(\|V\|+\|E\|) with witness traces | 02_system.tex:31–32 | `structural.py` | Witnesses: yes. Complexity: router_shape is O(routers·\|E\|) — soften or fix (S2). |
| Q6 | monitors evaluate events in O(1); abort ⇒ inconclusive | 02_system.tex:60–64 | `monitor/ltl.py` | Holds (DFA step is a table lookup); pin the abort behavior with a test. |
| Q7 | node kinds are {entry,exit,tool,llm,router,human,subgraph} | 02_system.tex:17–20 | `graph/model.py` `NodeKind` | **Mismatch:** code and GT data also use `passthrough` (S1). |
| Q8 | three extractors emit connected topologies **by construction** (structural checks vacuous there) | 03_realworld.tex:121–126 | `scripts/ast_extractor.py` (CrewAI/AutoGen/ADK builders wire `__start__`…`__end__` chains unconditionally) | Confirmed in code. |
| Q9 | reference labels are LLM reconstructions, not human ground truth (limitation stated) | 03_realworld.tex:38–46; 06_conclusion.tex:33–37 | human protocol now exists: `corpus/annotations/ANNOTATION_GUIDE.md` + `samples_manifest.json` | Honest as written; hard gate 3 requires either executing the protocol or keeping the qualified language. |
| Q10 | witness traces pinpoint the offending path | 02_system.tex:44–46 | `structural.py` `_find_path`, `_find_path_to_frontier` | Confirmed in code. |

---

## 3. Discrepancies and untraceable items (action list)

1. **Mining dates wrong (R1).** Paper: "February–March 2026". Repo: mining
   committed 2026-07-11; FINDINGS.md agrees. Correct the paper.
2. **Intro mischaracterizes a defect (I5).** The "payment-adjacent
   missing-human-gate" was extractor-visible; the extractor-invisible pair is
   SQL-related. Rewrite the sentence.
3. **Stale overturn rate (R11).** 4.6% belongs to the superseded 131-flag /
   60-workflow first pass. Recompute for the 186-flag set or scope the claim.
4. **ADK fidelity row and its clustered CI (A11, R16, R19).** The n=24
   numbers are reproducible but no artifact emits them; the cluster CI
   [0.14,0.62] has no source at all. Extend `revision_analyses.py` to emit
   per-framework post-exclusion fidelity with clustered CIs.
5. **Prevalence CIs not artifact-backed (A8, R30, R32).** All Wilson CIs for
   4/119, 4/87, 3/39, 1/80 are hand-computed; 1/80 upper bound should be
   6.7%, not 6.8%. Add these to `compute_cis.py`.
6. **Triage table is a hand merge (R23).** Post-exclusion, check-name-merged
   table has no generating script.
7. **Denominator drift 930 vs 922/186 vs 187.** `risk_aware_gate.json`,
   `monitor_pruning.json`, and `confidence_intervals.json` still include the
   8 self-repo workflows / 1 self-repo flag; the paper reports post-exclusion
   numbers. Rerun all three post-exclusion so artifacts match the paper.
8. **Historical "single case" anecdote (C8)** has no committed pre-fix run.
9. **Node-kind vocabulary (S1/Q7)** omits `passthrough`.
10. **Multi-tool false-proof gap (Q2): CLOSED this session (uncommitted).**
    `check_temporal_property`'s default event mapper now expands multi-tool
    nodes natively — every finite invocation sequence of the declared tools,
    including the empty one (temporal.py:139–145). Commit
    `src/agentproof/verify/temporal.py`; the redundant `expand_multitool`
    pre-pass was removed from `scripts/monitor_pruning.py`.
11. **Reference oracle (Q3/Q4): RESOLVED this session (untracked).**
    `tests/oracles/ltlf_reference.py` and
    `tests/semantics/{test_differential,test_required_properties}.py` now
    exist and were green in this session's verification run; commit them
    before freeze.
12. **Stub-accuracy artifact (I8, R38):** "near-perfect on stubs"
    (01_intro.tex:67) and the stronger Table-1 caption "Perfect on stubs"
    (03_realworld.tex:53–54) have no committed output from
    `extractor_accuracy.py`.
13. **Extractor instrument drift (NEW, this session).** The committed AST
    extractor that mined the corpus (`scripts/ast_extractor.py` at
    `728298c`/`e936b1b`) drops conditional edges when the LangGraph
    `path_map` dict is passed as the *third positional* argument of
    `add_conditional_edges` (only a second-positional dict or a `path_map=`
    keyword was read); the fix exists only in the uncommitted working tree
    (`scripts/ast_extractor.py:150–151`). `corpus/real_world/graphs/` was
    extracted with the buggy version, so every fidelity number (A10/A11,
    R15–R20, Table 1) describes the OLD instrument. Re-mine/re-extract the
    corpus, or add an explicit instrument-versioning note, before submission.
14. **Stale curated defect artifact (NEW, this session).** The committed
    `scripts/defect_results.json` (cited by C1/C2) predates the
    `reverse_reachability` check: it contains no `reverse_reachability`
    entries and reports 15 total defects, while `scripts/defect_study.py:102`
    now runs that check (a regeneration run yields 17 defects including 2
    reverse_reachability). Regenerate in the rerun phase.
15. **Pruning rule tightened (NEW, this session).**
    `scripts/monitor_pruning.py` now prunes ONLY on `verdict == "safe"` and
    reports `inconclusive` verdicts as their own must-keep category; the
    `expand_multitool` pre-pass was removed (native closure, item 10).
    Committed `monitor_pruning{,_curated}.json` were produced under the old
    "not violated" rule — a smoke rerun on `corpus/curated` gives 237/270
    (87.8%) prunable with 14 inconclusive, vs the committed 251/270 (93.0%) —
    so A12/A13/C5/C6/C7/C8/C9/I10 and the paper's 93% figure (main.tex:58,
    01_intro.tex:76–78, 04_results.tex:33–35) must be regenerated, and
    04_results.tex:28–31 (the pre-expansion description, C5) rewritten to
    describe the native multi-tool closure.

---

## 4. Hard-gate checklist (plan 3.7), assessed 2026-07-13

| Gate | Status | Evidence |
|---|---|---|
| No known semantic counterexample for an advertised DSL form | **PARTIAL — improved this session** | Semantic fixes implemented this session: nested until, response-chain re-arming, conservative multi-tool product (Q2 closed, item 10), finite-maximal-execution scope with three-valued verdict (temporal.py:127–131, :153–159); differential oracle suite present and green (`tests/oracles/ltlf_reference.py` + `tests/semantics/`, item 11) but untracked. Remaining: commit the fixes/tests and regenerate the semantics-dependent artifacts (item 15) |
| Every number generated from committed artifacts by one documented command | **FAIL** | Items A8, A9, A11, R16, R17, R19, R23, R27, R30, R32, R34 are hand-derived or trace to the wrong (pre-exclusion) artifact; denominator drift item 7 above; instrument drift item 13; stale artifacts items 14–15 |
| Human validation reported OR "ground truth" language removed | **PARTIAL** | Paper already qualifies labels as LLM reconstructions (Q9); human protocol + samples now committed (`corpus/annotations/`), not yet executed |
| Supplement contains exact mining queries, dates, commits, exclusions, annotation instructions | **FAIL** | No supplement document in `papers/paper1/aaai/`; mining dates in the paper are wrong (R1); annotation instructions now exist (this repo) but are not packaged |
| Monitor-pruning claim includes alphabet-only baseline | **PASS** | `monitor_pruning*.json` separates `trivially_inert` from `reachability_proven_inert`; paper states "all alphabet-level" prominently (A13, C7) |
| Static soundness conditioned on conservative extraction; no guarantee claimed for lossy AST corpus | **PASS (conditional)** | 02_system.tex:79–88 and 04_results.tex:20–27 state the premise; the Q2 multi-tool condition is now closed (item 10, uncommitted) |
| Code/data available anonymously at submission, not promised later | **FAIL** | 06_conclusion.tex:44–46 promises future release; no anonymized link exists |
| All four real issues have a responsible-disclosure record | **FAIL** | No disclosure record anywhere in the repository (X6) |
| A clean machine can reproduce every main table | **FAIL (untested)** | `scripts/reproduce_all.sh` covers the curated pipeline only; real-world tables require an undocumented sequence plus the hand steps in item 2 above |
| Paper, references, checklist satisfy official page rules | **UNKNOWN** | `main.pdf` builds with aaai2027 kit; not re-verified in this audit |

### Soft gates

| Gate | Status | Evidence |
|---|---|---|
| Dedup moves no headline estimate materially | **FAIL (not run)** | plan 3.5.1 dedup-sensitivity analysis has no artifact |
| ≥32 graphs independently human-reconstructed | **IN PROGRESS** | sample drawn (`samples_manifest.json`: 32, stratified 8/framework, 4+4 per stratum); annotation not started |
| Runtime extraction on ≥10 workflows/framework where feasible | **FAIL** | `runtime_fidelity.json`: n_runnable=5 total, 2 id-aligned |
| External mock Phase-1 review | **UNKNOWN** | no record |

## 5. Session update — 2026-07-13 (post-audit paper revision)

The following audit items were RESOLVED by the paper/tex edits applied after the
fix round (verify against `git diff` of `papers/paper1/aaai/`):

| Item | Resolution |
|---|---|
| R17 (kind accuracy 0.829 vs artifact 0.828) | Paper corrected to 0.828 at `sections/03_realworld.tex` (Table 1 overall row and prose). |
| Intro payment-defect misattribution | `01_intro.tex` now attributes the extraction-invisible defects to the SQL-gate case, matching `gt_triage_results.json`. |
| Curated pruning 251/270 (93.0%), mean 13.9/15 | Paper updated to 237/270 (87.8%), mean 13.2/15, with 19 may-fire + 14 inconclusive, per regenerated `corpus/real_world/monitor_pruning_curated.json` under the tightened `verdict=='safe'` prune rule. Abstract/intro/conclusion round to 88%. |
| Divergent-obligation violation mechanism (abstract, intro C2, 02_system, 04_results, 06_conclusion) | Rescoped everywhere to finite maximal executions; divergence now described as an explicit `inconclusive` verdict, never a violation or a proof. |
| "Ground truth" phrasing | All occurrences now say "reference graphs" with the LLM-reconstruction qualification retained in 03_realworld and the conclusion limitations. |
| "byte-identical duplicates" | Corrected to "topologically identical" per `sensitivity_analyses.json` gap note. |
| Missing concurrent-work comparison | `05_related.tex` gained a "Concurrent agent-policy systems" paragraph citing Agent-C, ClawGuard, SecureClaw, PolicyGuard, AgentFlow (entries added to `references.bib` from primary sources). |
| Extractor path_map blocker disclosure | `03_realworld.tex` now discloses the fixed conditional-edge extractor defect and states that fidelity/flag numbers describe the instrument as run during mining. |
| Sensitivity analyses (plan 3.5 items 1, 2, 5) | New sentence in `03_realworld.tex` citing supplement; artifacts: `scripts/sensitivity_analyses.py`, `corpus/real_world/sensitivity_analyses.json`. |
| Theory checklist mismatch (tex "partial" vs md "yes") | `ReproducibilityChecklist.tex` now answers "no" to theoretical contributions (measurement paper; soundness statement is premise-conditioned application of standard results, verified empirically); md updated to match. |
| Title | Retitled per plan 3.1: "When Can Static Verification Help Agent Workflows? A Base-Rate and Model-Fidelity Study". |

Still OPEN after this session (unchanged from Section 3/4): mining-window date
question (Feb–Mar 2026 vs repo history — needs author confirmation, do NOT edit
without evidence); ADK cluster CI [0.14,0.62] origin; stale 4.6% overturn rate
mention; hard gates 7 (responsible disclosure records) and 8 (anonymous
artifact link); human annotation execution (protocol + samples are ready in
`corpus/annotations/`); corpus re-mining with the fixed extractor.

## 6. Session update — 2026-07-13 (re-mine, disclosure, artifact round)

Open items from Section 5 now RESOLVED with evidence:

| Item | Resolution |
|---|---|
| Mining-window date (was "February–March 2026") | **Corrected to "July 2026"** in `03_realworld.tex`. Forensics (`corpus/real_world/MINING_DATE_FORENSICS.md`): 51 of 318 pinned repo snapshots are committed after 2026-03-31 (newest `faresrafat3/ai-earth` @ 2026-07-11), and no `corpus/real_world/` path exists in any pre-July git commit; `FINDINGS.md` says "Started 2026-07-11". A Feb–Mar search could not have returned those SHAs. Independently corroborated by the re-mine's `pinned_commit_date_max` = 2026-07-11. |
| Corpus re-mine with fixed extractor | **Done.** `scripts/remine_pinned.py` re-fetched every record at its pinned SHA (912/930 re-extracted; 13 repos now unreachable, 5 files no longer yield a graph — all categorized in `corpus/real_world/metadata_v2.json`). v2 graphs in `corpus/real_world/graphs_v2/`; v1 untouched. |
| Corrected-instrument fidelity/flag delta | **Measured** (`scripts/corrected_fidelity.py` → `corpus/real_world/corrected_fidelity.json`): overall edge recall 0.649→0.679; **LangGraph edge recall 0.682→0.819**; structural-flagged workflows 314→239 (exit-reachability flags 86→32). Reported in `03_realworld.tex` as causal confirmation of the extraction-bottleneck thesis. Table 1/Table 2 remain the as-mined (v1) instrument the study ran on; the delta is additive evidence, not a table swap. |
| Hard gate 7 (responsible disclosure) | **Records drafted** (not sent). `corpus/real_world/DISCLOSURES.md` + four maintainer-ready drafts in `corpus/real_world/disclosures/`. All four repo@SHA verified against provenance records; the two reference-graph-only defects match the paper's `real_defect` triage labels exactly. Sending is gated on user go-ahead + real sender identity (kept paper-anonymous). |
| Hard gate 8 (anonymous artifact) | **Built.** `papers/paper1/aaai/artifact/agentproof-anonymized.zip` (1.77 MB). Independent anonymity audit: zero author-identity hits, zero live API keys, no `.git`/`.venv`; self-repo pseudonymized to `ANONYMIZED__SELFREPO`; bundle test suite 255/255; sensitivity/CI artifacts regenerate byte-identically inside the bundle. Third-party `sources/` excluded (contains third-party secrets; ethics statement forbids source redistribution) and is re-fetchable via `remine_pinned.py`. |

Still OPEN: human annotation execution (protocol + samples + pinned source snapshots now all staged in `corpus/annotations/` and `corpus/real_world/sources/`); actually sending the four disclosures (needs user approval + identity); arXiv-variant sync (`papers/paper1/arxiv/` not updated this session).

## 7. Reviewer-response revision — 2026-07-14

The paper was rewritten to the repositioned thesis ("model extraction dominates
static analysis of agent workflows"). This section maps every reviewer problem
(#1–#12) and the smaller fixes to the paper location(s) that address it and to
the committed artifact that generates each new number. Line numbers are the
post-rewrite state of `papers/paper1/aaai/{main.tex,sections/*.tex}`.

**Cross-reference integrity (this audit's own pass).** Grepped every
`\label{}` and `\ref{}`/`\cref{}` across `main.tex` + `sections/*.tex`:
17 labels defined, each exactly once; every `\ref` target resolves; no
referenced-but-undefined and no defined-twice labels. `ReproducibilityChecklist.tex`
contains no `\ref`/`\label`. Referenced labels: `sec:realworld`, `sec:results`,
`sec:pruning`, `sec:system`, `tab:estimands`, `tab:realworld_fidelity`,
`tab:related`, `tab:pruning`. Defined-but-unreferenced (harmless):
`sec:graph_model`, `sec:verification_methods`, `fig:pipeline`, `par:ontology`,
`thm:soundness`, `par:threats`, `sec:conclusion`, `sec:introduction`,
`sec:related`.

**New source artifacts (regenerable, committed under `corpus/real_world/`):**

| artifact | supplies |
|---|---|
| `reviewer_analyses.json` | §1 estimands (k/n/Wilson), §2 post-stratification, §3 Fisher, §4 flag PPV/dedup/bounds, §5 v1↔v2 fidelity table |
| `corrected_fidelity.json` | v1 as-mined vs v2 corrected per-framework fidelity; flag-volume delta (314→239 structural-flagged; exit 86→32) |
| `pruning_experiment.json` | path-sensitive experiment: alphabet 1 / node-reach 3 / product 10 / runtime 0; +9 over alphabet, +7 over reachability; 5 curated + 4 synthetic; 50 executions, 0 false prunes |
| `monitor_pruning_curated.json` | curated gate: 237/270 (87.8%) prunable, 14 `inconclusive`, 19 `may_violate`; 18 wf × 15 pol = 270 |
| `monitor_pruning.json` | mined gate: 0/13950 certified-sound (all may-provenance, refused); 13950 alphabet-inert descriptively |

### 7.1 Reviewer problems

| # | Reviewer problem | Paper location(s) | New number(s) → source |
|---|---|---|---|
| 1 | Pooled 4/119 conflates distinct quantities — separate estimands | `03_realworld.tex:123–181` (Defining a defect; Three estimands; Table `tab:estimands`); `01_intro.tex:60–73`; `main.tex:44–48`; `06_conclusion.tex:19–26` | structural 1/119 (0.84%, Wilson [0.15,4.61]); policy 3/119 (2.52%, [0.86,7.15]); composite 4/119 (3.36%, [1.31,8.32]) → `reviewer_analyses.json` `1_separate_estimands.{structural,policy,composite_any}.{k,n,rate,wilson_ci}` |
| 2 | Sample over-represents ADK — post-stratify to corpus mix | `03_realworld.tex:146–155` + Table `tab:estimands` Post-strat column (`:174–176`); `01_intro.tex:69–70`; `main.tex:47`; `06_conclusion.tex:25–26` | post-strat structural 0.23% [0.00,0.80], policy 1.92% [0.00,4.85], composite **2.15%** [0.20,5.12]; per-framework composite LG 1/40, CrewAI 1/20, AutoGen 0/35, ADK 2/24; ADK 5.4% of corpus (50/922) → `reviewer_analyses.json` `2_post_stratification.*.{post_stratified_point,post_stratified_cluster_bootstrap_ci,per_framework}` |
| 3 | Undefined "workflow" unit | `03_realworld.tex:8–11` (unit = one source file → one *extracted file-level graph*; executable-workflow-root unit is future work); denominators renamed "extracted file-level graph" throughout; `06_conclusion.tex:42–43` | definitional; corpus size 922 extracted file-level graphs → `reviewer_analyses.json` `_meta.corpus_composition` |
| 4 | "Ground truth"/human-validation overclaim | `main.tex:40–41`; `01_intro.tex:48–51`; `03_realworld.tex:12,31–51` ("LLM-reconstructed reference graphs"; "Two-annotator independent human validation was not performed… protocol and samples are staged"); `06_conclusion.tex:44–48`; `par:threats` `03_realworld.tex:211–214` | qualitative (no new number). Reconstruction-confidence 77/33/9 is pre-existing (`revision_analyses.json` `confidence.gt_confidence_distribution`); protocol staged in `corpus/annotations/` |
| 5 | "Concentrate exactly where they matter" overreach | `03_realworld.tex:155–160`; `01_intro.tex:71–73`; `06_conclusion.tex:26–28` | app-like 3/39 (7.7%) vs 1/80 (1.3%); Fisher two-sided **p=0.10**; OR 6.58, Wald [0.66,65.5] (spans 1) → `reviewer_analyses.json` `3_fisher_exact.{table,two_sided_p,odds_ratio_sample}` |
| 6 | Soundness stated over graph paths, not event traces; no gate against false `safe` | `02_system.tex:94–144` (Static temporal verification; Soundness gated on certified extraction, `thm:soundness`); `04_results.tex:22–35`; `01_intro.tex:93–97`; `main.tex:48–52` | qualitative theorem over labeled event traces; gate returns `inconclusive`/`uncertified_extraction`, stamps `certified` key → code `src/agentproof/verify/temporal.py`. Gate yields on lossy graphs: mined 0/13950 certified → `monitor_pruning.json` |
| 7 | Exclusive NodeKind/EdgeKind ontology mislabels multi-faceted nodes; PASSTHROUGH omitted | `02_system.tex:36–51` (`par:ontology`: orthogonal effect/capability sets + edge back_edge flag; full vocabulary in supplement); `02_system.tex:19` (PASSTHROUGH added to kind list) | qualitative → code `src/agentproof/graph/model.py` |
| 8 | Monitor pruning was zero-value (all alphabet-level / claimed 93% on graphs pruning can't apply to) | `04_results.tex:18–84` (three paragraphs + Table `tab:pruning`); `01_intro.tex:96–97`; `main.tex:48–52`; `06_conclusion.tex:33–36` | curated 237/270 (87.8%) certified-sound, 14 `inconclusive`, 19 `may_violate` → `monitor_pruning_curated.json`; mined 0/13950 certified (all may-provenance) → `monitor_pruning.json`; incremental experiment alphabet 1 / node-reach 3 / product 10 / runtime 0, +9 over alphabet (+7 over reachability), 5 curated + 4 synthetic, 50 executions / 0 false prunes → `pruning_experiment.json` `{strategies,incremental,false_pruning}` |
| 9 | Fidelity numbers describe an uncorrected instrument | `03_realworld.tex:53–99` (Table `tab:realworld_fidelity` v2 primary + v1 ablation column; "Extraction fidelity is the bottleneck"); `main.tex:41–43`; `01_intro.tex:74–76,80–83`; `06_conclusion.tex:28–32` | v2 overall edge R **0.679** (v1 0.649), LangGraph edge R **0.682→0.819**, ADK 0.355; structural-flagged 314→239, exit flags 86→32 → `corrected_fidelity.json` `{fidelity_v1_asmined,fidelity_v2_corrected,flags_v1_asmined,flags_v2_corrected}` and `reviewer_analyses.json` `5_fidelity_v2_table` |
| 10 | Flags treated as independent; single PPV point | `03_realworld.tex:101–121` (Flag precision); `01_intro.tex:84–85`; `06_conclusion.tex:19–21` | workflow-level PPV 2/114 (1.75%, [0.48,6.17], cluster [0.00,4.59]); confirmed flag PPV 2/186 (1.08%, [0.30,3.84]); root-cause dedup 186→161 (25 collapsed), 2/161 (1.24%); pessimistic 14/186 (7.53%, [4.54,12.24]), 14/161 (8.70%); identification range [1.08%,7.53%] → `reviewer_analyses.json` `4_flag_ppv.{workflow_level_ppv,root_cause_dedup,ppv_bounds}` |
| 11 | "No analogous measurement exists"; missing related work + comparison | `05_related.tex:15–73` (Concurrent agent-policy systems; Empirical characterizations; comparison Table `tab:related`); `01_intro.tex:89–92` | cited counts ~1026 bugs / 9 root causes (`xue2025bugs`), 221 vulns / 14 types (`shen2025securitydebt`), 5399 programs (`wang2026agentflow`); also `ning2024agentable`, `wang2025agentspec`, `kamath2026agentc` → primary sources in `../references.bib` |
| 12 | Threats to validity not stated | `03_realworld.tex:199–214` (`par:threats`: construct/internal/external/sampling/label-reliability) | qualitative synthesis of #1–#4, #9; no new number (facts block did not assign an explicit reviewer number to this ask) |

### 7.2 Smaller fixes

| Fix | Paper location | Source |
|---|---|---|
| Mining window corrected to "July 2026", newest pinned commit 2026-07-11 | `03_realworld.tex:15–16` | `corpus/real_world/MINING_DATE_FORENSICS.md`; `metadata_v2.json` `pinned_commit_date_max` |
| AgentProof = prior, publicly available instrument (not the contribution) | `01_intro.tex:38–42` | qualitative repositioning |
| "Finite-trace semantics cannot decide cycles" → decidable; `inconclusive` is an engineering-scope choice | `02_system.tex:108–111`; `04_results.tex:32–35` | qualitative |
| `router_shape` complexity now genuinely O(\|V\|+\|E\|) | `02_system.tex:54` | code `src/agentproof/verify/structural.py` (edges grouped by source once) |
| Keyword lexicon: "the check's logic is sound" → "correct relative to its declared-tool abstraction" | `03_realworld.tex:195–197` | qualitative |
| "faithful reconstructions" → "LLM-reconstructed reference graphs" | `06_conclusion.tex:55` and throughout | label-language rule |
| Abstract shortened to 208 words (target 180–220) | `main.tex:33–54` | word count |
| **Cross-section unit mismatch (fixed this pass):** conclusion said "270 curated workflows" but §4 says 18 workflows / 270 monitor instances (18×15) | `06_conclusion.tex:35` → "270 curated monitor instances" | `monitor_pruning_curated.json` `{n_workflows:18,n_policies:15,n_monitor_instances:270}` |

### 7.3 Consistency verification (headline numbers across sections)

Every headline number was checked for cross-section agreement against the facts
block; all match:

- Estimands **1/119, 3/119, 4/119** — abstract (`main.tex:45–46`), intro
  (`:65–68`), §3 prose (`03_realworld.tex:141–146`) and Table (`:174–176`),
  conclusion (0.84% / 2.52% / composite, `:23–26`). ✓
- Post-stratified composite **2.15%** — `main.tex:47`, `01_intro.tex:70`,
  `03_realworld.tex:152,176`; conclusion rounds to 2.2% (`:26`). ✓
- Fisher **p=0.10**, OR 6.58 [0.66,65.5] — `01_intro.tex:73`,
  `03_realworld.tex:158`, `06_conclusion.tex:27–28`. ✓
- PPV identification range **[1.08%, 7.53%]** — `03_realworld.tex:114–115`;
  conclusion "1.1–7.5%" (`:20`). ✓
- v2 edge recall **0.679** overall / **0.819** LangGraph — Table 1
  (`03_realworld.tex:66,71`); abstract/intro "0.68 → 0.82"
  (`main.tex:43`, `01_intro.tex:75,83`); conclusion "0.68 on real code, 0.36 on
  ADK" (`:28–29`). ✓
- Pruning **237/270** (87.8% → 88%) + incremental **9** — §4
  (`04_results.tex:29,56`, Table `tab:pruning`); conclusion 237/270 (88%)
  (`:35`); abstract/intro "nonzero gain over alphabet-only." ✓
- Mining **July 2026** — `03_realworld.tex:15`. ✓
- Corpus **922 / 252 repos**; sample **119** — abstract, intro, §3, conclusion
  all agree. ✓

### 7.4 Residual notes (not papered over)

1. **Mined-instance denominator drift (facts-block-endorsed, not fixed).**
   `04_results.tex:41–42` reports **13,950** mined (workflow, policy) instances
   (= 930 workflows × 15 policies, `monitor_pruning.json` `n_monitor_instances`),
   while the corpus census reports **922** workflows (`03_realworld.tex:19`).
   13950/15 = 930 ≠ 922: the pruning artifact still includes the 8 self-repo
   graphs the census excludes. The facts block explicitly sanctions both
   "476/13950 (3.4%)" and "922", so I left it as-is; flagging for the freeze
   pass in case the pruning artifact should be regenerated post-exclusion (would
   become 922×15 = 13,830).
2. **`04_results.tex:29–31` phrasing.** "certifies 237 of 270 (87.8%)… declines
   14 as `inconclusive`, leaving the remaining 12.2% (19 that may fire)": the
   12.2% (= 33/270) is the complement of 87.8% and correctly spans the 14
   `inconclusive` **plus** the 19 `may_violate`; the parenthetical highlights
   only the 19. Numerically self-consistent (237+14+19=270) but the dense
   phrasing can read as "12.2% = 19" (which would be 7.0%). Within-section prose,
   each constituent number matches the facts block, so not rewritten here.
3. **`02_system.tex:141` cites "edge recall 0.65"** for the mining fallback —
   this is the as-mined v1 instrument (0.649), correct for that context and not
   in conflict with the v2-primary "0.68" used elsewhere (different instrument,
   explicitly the "AST fallback used for mining"). No fix needed.
