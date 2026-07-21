# AAAI-27 Reproducibility Checklist — Agentproof

Draft answers, filled honestly against the current paper (`aaai/main.tex`) and the
released artifact. Transcribe into the official AAAI submission form. Legend:
**yes** / **partial** / **no** / **NA**. Items marked ⚠ need a one-line addition
to the paper (drafted at the bottom) to move from `partial` → `yes`.

## 1. General (all papers)

| # | Item | Answer | Justification |
|---|------|--------|---------------|
| 1.1 | Conceptual outline / pseudocode of AI methods introduced | **yes** | §"The Agentproof System" describes the graph model, six checks, DSL→DFA compilation, and the graph×DFA product; formal grammar/proofs in appendix. |
| 1.2 | Delineates opinion/hypothesis/speculation from objective facts | **yes** | Results are stated with measured numbers; interpretation is explicitly marked ("we read this as…", "we leave to future work"), and negative/limiting findings are called out. |
| 1.3 | Well-marked pedagogical references for background | **yes** | Cites model checking (Clarke et al.), LTL (Pnueli), runtime verification, and BPM soundness for less-familiar readers. |

## 2. Theoretical contributions

**Does this paper make theoretical contributions?** **no.**

This is a measurement paper. Its formal content — LTL$_f$ semantics (De Giacomo
& Vardi), DFA compilation by formula progression, and the soundness of monitor
pruning under an explicitly stated trace-containment premise — is an
application of standard automata-theoretic results, not novel theory. The
premise-conditioned soundness statement is stated precisely in the paper
(Section 2), verified empirically by an independent differential reference
oracle (exhaustive traces to length 6) and by a bounded no-false-prune check
(`corpus/real_world/pruning_experiment.json` `false_pruning`: 10 product-pruned
pairs, 50 concrete executions, 0 false prunes), and the artifact ships the test
suites. All sub-items are therefore NA (matching `ReproducibilityChecklist.tex`).

## 3. Datasets

**Does this paper rely on one or more datasets?** **yes** (**922**-workflow mined corpus; 18-workflow curated corpus; **119** LLM-reconstructed reference graphs; **186** triage labels). These are the post-exclusion analyzed counts: 8 `NordicAgents/AgentProof` self-repo fixture files are removed from the mined corpus (930 → 922), one of which also sat inside the reference-graph set (120 files on disk → 119 analyzed) and contributed one triage flag (187 → 186).

| # | Item | Answer | Justification |
|---|------|--------|---------------|
| 3.1 | Motivation for selected datasets | **yes** | Real base rates require independently authored workflows (the mined corpus); the curated corpus is a controlled detection test. |
| 3.2 | Novel datasets included in a data appendix | **partial** | Extracted graphs, ground-truth graphs, and triage labels are released; raw third-party source is **not** redistributed (licensing) but full provenance (repo @ commit-SHA + path) is recorded so any workflow can be re-fetched. |
| 3.3 | Novel datasets public upon publication, research license | **yes** | Corpora + provenance + pipeline released under MIT. |
| 3.4 | Datasets from existing literature cited | **NA** | No standard benchmark datasets are used; workflows are self-mined. |
| 3.5 | Datasets from existing literature publicly available | **NA** | (See 3.4.) The underlying source repositories are themselves public and identified by URL@SHA. |
| 3.6 | Non-public datasets described + justified | **NA** | All sources are public GitHub repositories. |

## 4. Computational experiments

**Does this paper include computational experiments?** **yes**.

| # | Item | Answer | Justification |
|---|------|--------|---------------|
| 4.1 | Pre-processing code included | **yes** | `scripts/mine_github_gh.py`, `scripts/ast_extractor.py`. |
| 4.2 | All experiment/analysis code included | **yes** | `defect_study.py`, `aggregate_realworld.py`, `monitor_pruning.py`, `risk_aware_gate.py`, plus the validation-workflow scripts. |
| 4.3 | Code public upon publication, research license | **yes** | MIT. |
| 4.4 | New-method code commented with paper references | **partial** | Modules carry docstrings/comments; not every step back-references a paper section. |
| 4.5 | Seed-setting method described | **partial** | Downstream analyses use fixed seeds (`random.seed(42)`, `seed(7)`; the clustered bootstrap uses B=10,000 with seed 20260714), and although the LLM-agent validation is non-deterministic its raw outputs (`wf_output*.json`) are released and all aggregation over them is deterministic. **However, the 119-workflow validation sample itself was not drawn under a seed.** The slugs are hard-coded literal lists inside `scripts/wf_run.js` and `scripts/wf_run_v2.js`; no script draws the sample, no seed is recorded, and no written inclusion rule exists. The sample is therefore not demonstrably random, and generalization from the 119 to the 922 rests on an unverifiable assumption. Reported as a limitation, not repaired. |
| 4.6 | Computing infrastructure specified (HW/SW, versions) | **yes** | §Real-World Study, Validation: pure Python 3.12 on a commodity laptop (no GPU); ground-truth/triage agents were Claude Opus 4.8 via a workflow harness. |
| 4.7 | Evaluation metrics formally described + motivated | **yes** | Node/edge precision–recall, node-kind accuracy, triage label distribution, and monitor-pruning rate are defined and motivated. |
| 4.8 | Number of algorithm runs per result stated | **yes** | §Real-World Study, Validation: 1 ground-truth + 1 triage + 1 adversarial-verify pass per workflow; scalability timings are the median of 10 trials. |
| 4.9 | Analysis beyond single-dimensional summaries | **yes** | Per-framework/per-check distributional breakdowns plus 95% CIs on every headline number: repository-clustered bootstrap (B=10,000) for fidelity means, Wilson for prevalence proportions (`scripts/compute_cis.py`, `scripts/reviewer_analyses.py`). Current figures: edge recall on the collision-free matched set (n=106) **0.652** as-mined → **0.709** corrected, ADK **0.343** (`corpus/real_world/matched_fidelity.json` `provenance_collisions.collision_free_fidelity`); structural genuine 0/72 [0, 5.1]%. The previously quoted "0.64 [0.57,0.71]" was the superseded pre-exclusion n=120 first pass. |
| 4.10 | Statistical significance tests | **NA** | Descriptive base-rate study; no trained-model performance comparison for which a significance test applies. |
| 4.11 | Final (hyper-)parameters listed | **partial** | No trained models. Experimental parameters listed: analyzed sample size **119** (post-exclusion; 120 reference-graph files on disk), curated corpus 18 workflows × 15 policies = 270 monitor instances, bootstrap B=10,000 with seed 20260714, the sensitive-tool keyword lexicon, and the 15 policy DSL strings. The earlier "120 / 60+60" described the superseded pre-exclusion first pass. **Gap:** the 119-workflow validation sample has no seed and no documented selection rule — see 4.5. |
| 4.12 | Number/range of values tried per hyper-parameter | **NA** | No hyper-parameter search. |

---

## Remaining `partial`s (honest gaps, not blockers)

- **2.2** — some soundness claims are argued precisely but not in theorem form.
- **3.2** — derived graphs + provenance are released; raw third-party source is not
  redistributed (licensing).
- **4.4** — code is commented but not every step back-references a paper section.
- **4.5 / 4.11** — the 119-workflow validation sample has no seed and no documented
  selection rule (hard-coded slug lists in `scripts/wf_run*.js`). This is the one
  genuine sampling-design gap; it also removes the justification for any
  design-based (SRSWOR / finite-population-corrected) interval, which is why
  `scripts/reviewer_analyses.py` now quotes the repository-clustered bootstrap
  instead. See `CLAIMS_AUDIT.md` §8.3–§8.4.

*(4.6, 4.8, and 4.9 were upgraded to `yes`: infrastructure + run-count sentences
and 95% confidence intervals were added to §Real-World Study. A second human
annotator for Cohen's κ remains a nice-to-have for camera-ready but is not a
checklist item.)*

## Note on responsible data use (for the ethics/impact statement, not the checklist)

The study mines only **public** GitHub repositories, records exact provenance
(repo@SHA + path), and does **not** redistribute third-party source, only the
derived graph abstractions and analysis. No personal data is processed.
