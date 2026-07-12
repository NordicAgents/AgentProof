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

**Does this paper make theoretical contributions?** **yes** (modest: soundness of the checks and of monitor pruning by over-approximation).

| # | Item | Answer | Justification |
|---|------|--------|---------------|
| 2.1 | Assumptions/restrictions stated clearly and formally | **yes** | The event model σ(v), the static over-approximation (all conditional edges feasible), and fixed-size DFAs are stated. |
| 2.2 | Novel claims stated formally | **partial** | Soundness of pruning ("no reachable violation state ⟹ inert on every runtime path") is argued precisely; not every claim is in theorem form. |
| 2.3 | Proofs of novel claims included | **yes** | Appendix (proofs) — reachability/soundness arguments. |
| 2.4 | Proof sketches / intuitions for complex results | **yes** | The over-approximation soundness intuition is given in the monitor-selection discussion. |
| 2.5 | Citations to theoretical tools | **yes** | Clarke et al. (model checking), Pnueli (LTL), Vardi (automata product). |
| 2.6 | Theoretical claims demonstrated empirically | **yes** | The pruning soundness is exercised on the corpus (monitor-selection result). |
| 2.7 | Code to eliminate/disprove claims included | **NA** | No such claims. |

## 3. Datasets

**Does this paper rely on one or more datasets?** **yes** (930-workflow mined corpus; 18-workflow curated corpus; 120 ground-truth graphs; 187 triage labels).

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
| 4.5 | Seed-setting method described | **yes** | Sampling uses fixed seeds (`random.seed(42)`, `seed(7)`). The LLM-agent validation is non-deterministic, but its raw outputs (`wf_output*.json`) are released and all downstream aggregation is deterministic. |
| 4.6 | Computing infrastructure specified (HW/SW, versions) | **yes** | §Real-World Study, Validation: pure Python 3.12 on a commodity laptop (no GPU); ground-truth/triage agents were Claude Opus 4.8 via a workflow harness. |
| 4.7 | Evaluation metrics formally described + motivated | **yes** | Node/edge precision–recall, node-kind accuracy, triage label distribution, and monitor-pruning rate are defined and motivated. |
| 4.8 | Number of algorithm runs per result stated | **yes** | §Real-World Study, Validation: 1 ground-truth + 1 triage + 1 adversarial-verify pass per workflow; scalability timings are the median of 10 trials. |
| 4.9 | Analysis beyond single-dimensional summaries | **partial** | Per-framework and per-check distributional breakdowns are reported; confidence intervals are **not** (explicitly flagged as future work — scaling the sample). |
| 4.10 | Statistical significance tests | **NA** | Descriptive base-rate study; no trained-model performance comparison for which a significance test applies. |
| 4.11 | Final (hyper-)parameters listed | **yes** | No trained models. All experimental parameters are listed: sample sizes (120 / 60+60), seeds, the sensitive-tool keyword lexicon, and the 15 policy DSL strings. |
| 4.12 | Number/range of values tried per hyper-parameter | **NA** | No hyper-parameter search. |

---

## Remaining `partial`s (honest gaps, not blockers)

- **2.2** — some soundness claims are argued precisely but not in theorem form.
- **3.2** — derived graphs + provenance are released; raw third-party source is not
  redistributed (licensing).
- **4.4** — code is commented but not every step back-references a paper section.
- **4.9** — distributional breakdowns are reported but **confidence intervals are
  not** (flagged in the paper as future work: scale the 120-workflow sample and
  add a second human annotator for Cohen's κ). This is the one worth closing before
  a camera-ready.

*(4.6 and 4.8 were upgraded to `yes` by adding the infrastructure + run-count
sentences to §Real-World Study, Validation.)*

## Note on responsible data use (for the ethics/impact statement, not the checklist)

The study mines only **public** GitHub repositories, records exact provenance
(repo@SHA + path), and does **not** redistribute third-party source, only the
derived graph abstractions and analysis. No personal data is processed.
