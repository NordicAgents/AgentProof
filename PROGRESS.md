# Revision progress — AAAI paper (papers/paper1/aaai)

Status as of 2026-07-13. This revision responds to an AAAI-style review
(overall 4/10) whose major concerns were: wrong estimand (flag PPV presented
as prevalence), unmeasured false negatives, extractor-imposed connectivity
predetermining three frameworks' results, incorrect temporal semantics
(not the claimed safety fragment of LTL), unsound monitor-pruning premise,
unexamined corpus composition (tutorials/tests, self-contamination,
duplicates), and insufficiently validated LLM ground truth.

## Done

### New analyses (all outputs in `corpus/real_world/`)
- **Checks re-run on the 119 ground-truth graphs** (`revision_analyses.json`,
  `gt_flags_for_triage.json`): measures the false negatives flag-triage cannot
  see. 16 flags raised; adversarially triaged by a 46-agent workflow
  (`gt_triage_results.json`): 10 intentional, 4 ground-truth errors,
  **2 genuine defects the AST-extracted study missed** (ADK SQL-agent router
  defect; SQL-executing chatbot reachable without human gate). Both original
  real defects re-confirmed by a second adversarial pass.
- **Prevalence with the correct estimand**: 4/119 workflows (3.4%, Wilson
  [1.3, 8.3]%), 4/87 repositories (4.6%); flag precision reported separately
  (2/186 = 1.1%). Stratified: 3/39 application-like (7.7%) vs 1/80
  tutorials/demos/tests (1.3%).
- **Corpus census**: reviewer-spotted self-contamination confirmed and
  excluded (8 `NordicAgents/AgentProof` fixture files, 1 inside the validated
  sample; corpus now 922 workflows / 252 repos). Source-level classification
  of the sample (119 agents-read files): 44% tutorial/course, 17% demo/toy,
  7% test, 33% application-like; 32/119 bind side-effecting tools in-body
  (vs 0 declared in mined graphs). 48 cross-repo duplicate-topology groups
  (170 redundant workflows) detected and reported.
- **Statistics**: repository-clustered bootstrap CIs for all fidelity means
  and prevalence; GT-confidence distribution (77 high / 33 med / 9 low) and
  high-confidence-only sensitivity (edge recall 0.67 vs 0.65 — stable).

### Code fixes (temporal semantics; 103/103 tests pass)
- `src/agentproof/monitor/ltl.py`: real LTLf semantics — per-form accepting
  states, `finalize_monitors()` end-of-trace check, strong until, response
  forms without the bogus retrigger-violation; semantics documented per form.
- `src/agentproof/verify/temporal.py`: product now covers all three violation
  mechanisms — bad prefix, unfulfilled obligation at exit, divergent
  obligation (non-accepting lasso for infinite runs).
- `src/agentproof/api.py`: finalize applied at end of replayed traces.
- `scripts/monitor_pruning.py`: multi-tool nodes expanded to a complete
  digraph (all orders/subsets) instead of one arbitrary chain; soundness
  premise (trace containment) documented; **re-run**: 251/270 (93.0%) inert,
  all alphabet-level — the previous single "reachability-proven" case was a
  live termination-obligation monitor under correct semantics
  (`corpus/real_world/monitor_pruning_curated.json` regenerated).
- `scripts/benchmark_scale.py` re-run: 5,000-node graphs still sub-second.

### Paper rewrite (`papers/paper1/aaai/`, compiles clean, content ≤ 6 pp)
- Title: "... Mined from Public GitHub" (drops "Real-World" overclaim).
- Abstract + all six sections rewritten: two-estimand framing (precision vs
  prevalence), new prevalence table, corpus census, scoped structural
  conclusions (LangGraph-only; connectivity-by-construction stated), LTLf
  semantics + soundness premise sections, honest pruning numbers, expanded
  related work (static-analysis actionability literature, LTLf, ToolEmu /
  AgentDojo), limitations paragraph, defect-disclosure note in ethics.
- Fixed dangling section references (`secnumdepth` 0 → 1; verified zero
  "(Section )" in the compiled PDF).
- `papers/paper1/references.bib`: +6 entries (Bessey 2010, Johnson 2013,
  Sadowski 2018, De Giacomo & Vardi 2013, AgentDojo, ToolEmu).

## Left to do

1. **Adversarial verification pass on the revised paper** (planned multi-agent
   panel): number-vs-artifact audit, semantics-vs-code audit, review-coverage
   audit, LaTeX/page audit. Not yet run (was blocked by the disk-full
   incident).
2. **Human annotation of a GT subsample** — the one review demand that needs
   a human: expert annotation + agreement stats for ~25–30 ground-truth
   graphs. The paper currently states this as next-step; doing it before
   submission would upgrade the rebuttal.
3. **Sync the arxiv version** (`papers/paper1/arxiv/`) with the revised
   content and updated supplementary numbers (policy-evaluation and pruning
   tables changed under LTLf semantics).
4. **Update FINDINGS.md / README** in `corpus/real_world/` to reflect the
   922/252 exclusions and the new GT-graph analysis.
5. **Mining metadata for the paper**: exact GitHub query strings and dates
   are in `scripts/mine_github_gh.py`; consider adding them to the
   supplementary material verbatim.
6. **Responsible disclosure**: notify the four repositories with genuine
   defects before publication (ethics statement now promises this).
7. Optional: dedup-aware sensitivity run (drop the 170 duplicate workflows
   and confirm headline numbers move < 1 pt).

## Key numbers (post-revision, for quick reference)

| Quantity | Value |
|---|---|
| Corpus | 922 workflows / 252 repos (8 self-fixtures excluded) |
| Validated sample | 119 workflows / 87 repos |
| Flag precision (extracted graphs) | 2/186 = 1.1% [0.3, 3.8]% |
| Structural flags genuine | 0/72 [0, 5.1]% (all artifacts/arguable) |
| Prevalence incl. false negatives | 4/119 = 3.4% [1.3, 8.3]% |
| Prevalence, application-like | 3/39 = 7.7% [2.7, 20.3]% |
| Edge recall (AST, overall / ADK) | 0.649 [0.56, 0.73] / 0.382 [0.14, 0.62] |
| Monitor pruning (curated) | 251/270 = 93.0%, all alphabet-level |
