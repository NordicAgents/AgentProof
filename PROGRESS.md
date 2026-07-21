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
- **Prevalence with the correct estimand.** The pooled 4/119 (3.4%) headline is
  **superseded**: a reviewer showed it conflates distinct quantities, so it is
  now reported as three separated estimands (`reviewer_analyses.json`
  `1_separate_estimands`) — structural **1/119** (0.84%, Wilson [0.15, 4.61]%),
  human-gate policy **3/119** (2.52%, [0.86, 7.15]%), composite-any **4/119**
  (3.36%, [1.31, 8.32]%, secondary). Post-stratified to the corpus framework
  mix: composite **2.15%**, repo-clustered bootstrap [0.20, 5.12]%.
  **Caveat: the human-gate estimand is under revision** pending a uniform
  re-audit of the gate labels, so the policy and composite rows may move; the
  structural row is stable. Flag precision reported separately (2/186 = 1.1%).
  Stratified: 3/39 application-like (7.7%) vs 1/80 tutorials/demos/tests (1.3%),
  Fisher two-sided p=0.10.
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

### Code fixes (temporal semantics; `uv run pytest` → 405 passed, 1 skipped)
- `src/agentproof/monitor/ltl.py`: real LTLf semantics — per-form accepting
  states, `finalize_monitors()` end-of-trace check, strong until, response
  forms without the bogus retrigger-violation; semantics documented per form.
- `src/agentproof/verify/temporal.py`: product now covers all three violation
  mechanisms — bad prefix, unfulfilled obligation at exit, divergent
  obligation (non-accepting lasso for infinite runs).
- `src/agentproof/api.py`: finalize applied at end of replayed traces.
- `scripts/monitor_pruning.py`: soundness premise (trace containment)
  documented; prune rule tightened to `verdict == "safe"`. Multi-tool closure
  is no longer done here — the `expand_multitool` pre-pass was **removed** (it
  no longer exists anywhere in the tree) because `check_temporal_property`'s
  default event mapper now closes over every finite invocation sequence of a
  multi-tool node's declared tools natively. **Re-run**: 237/270 (87.8%)
  certified-sound, all alphabet-level, with 14 `inconclusive` and 19
  `may_violate` — the previous single "reachability-proven" case was a live
  termination-obligation monitor under correct semantics
  (`corpus/real_world/monitor_pruning_curated.json` regenerated).
- `scripts/benchmark_scale.py` re-run: 5,000-node graphs still sub-second.

### Paper rewrite (`papers/paper1/aaai/`, compiles clean, content ≤ 6 pp)
- Title (current, `main.tex:26`): "Two Failure Modes, Not One: Extraction Error
  and Policy Misspecification in Static Analysis of Agent Workflows".
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
| Prevalence — structural estimand | 1/119 = 0.84% [0.15, 4.61]% |
| Prevalence — human-gate policy estimand | 3/119 = 2.52% [0.86, 7.15]% *(under revision — uniform re-audit pending)* |
| Prevalence — composite any (secondary) | 4/119 = 3.36% [1.31, 8.32]% *(supersedes the old pooled "4/119 = 3.4%" headline)* |
| Post-stratified composite | 2.15%, repo-clustered bootstrap [0.20, 5.12]% |
| Prevalence, application-like | 3/39 = 7.7% [2.7, 20.3]% |
| Edge recall (collision-free matched set, n=106) | overall v1 **0.652** → v2 **0.709**; ADK **0.343** |
| Monitor pruning (curated) | 237/270 = 87.8%, all alphabet-level (14 inconclusive, 19 may-fire) |

**Sources for the table above.** Prevalence estimands and post-stratification:
`corpus/real_world/reviewer_analyses.json` (`1_separate_estimands`,
`2_post_stratification`). Edge recall: `corpus/real_world/matched_fidelity.json`
→ `provenance_collisions.collision_free_fidelity` — the **n=106** collision-free
set, not the n=115 matched set. The 9 excluded rows are slug collisions where the
v1 miner (last-wins) and the v2 re-miner (first-wins) resolved the same
`repo__basename` key to *different source files*, so those rows would compare two
programs rather than two instrument versions. Monitor pruning:
`corpus/real_world/monitor_pruning_curated.json`. See
`papers/paper1/aaai/CLAIMS_AUDIT.md` §8 for the full derivation of each.
