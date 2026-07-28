# Prospective Validation Protocol

**Status:** frozen before any annotation or model reconstruction on this sample

**Manifest:** `corpus/annotations/prospective_validation_manifest.json`

**Generator:** `scripts/make_prospective_validation_sample.py`
**Seed:** `20260728`

## 1. Why this protocol exists

The paper's historical 119-file audit is useful as an exploratory failure-mode
study, but its selection mechanism cannot be recovered: the identifiers exist
only as hard-coded lists, with no sampler or seed. No wording change can repair
that fact. This protocol creates a prospective replacement whose inclusion
rule, probabilities, exclusions, and human-validation subset are fixed before
any outcome is observed.

The prospective results replace the historical 119-file quantities in the main
paper once all locked annotation stages below are complete. Until then, the
historical audit must remain explicitly labeled exploratory, and the
prospective sample must not be used for headline claims.

## 2. Sampling frame and unit

The frame is the 904 non-self-repository records in
`corpus/real_world/metadata_v2.json` for which:

- corrected-v2 extraction succeeded;
- framework is LangGraph, CrewAI, AutoGen, or Google ADK;
- repository, pinned commit, and exact source path are recorded; and
- the corrected graph and local pinned source snapshot exist.

The unit key is `(repository, commit_sha, source_path)`, not the historical
`repository + basename` slug. This removes the non-unique-key ambiguity.
Historically colliding slugs remain marked in the manifest and are never joined
to the v1 graph by slug.

This is still a file-level frame derived from a search-ranked GitHub convenience
corpus. Probability statements therefore apply only to these 904 records—not
to GitHub, complete repositories, private code, or deployed systems.

## 3. Frozen two-stage design

Sampling is independent within framework:

1. sample 24 eligible repositories uniformly without replacement; then
2. sample one eligible workflow file uniformly within each selected
   repository.

This gives 96 files: 24 per framework. For workflow \(i\) in repository \(r\)
and framework \(f\),

\[
  \pi_i = \frac{24}{R_f}\frac{1}{N_{rf}},
  \qquad w_i = \pi_i^{-1},
\]

where \(R_f\) is the number of eligible repositories in the framework and
\(N_{rf}\) the number of eligible files in that repository. Both values and the
resulting weight are stored per item.

The sampler reads no reference graph, checker output, triage label, source-level
policy verdict, or paper result. Running

```bash
python scripts/make_prospective_validation_sample.py --check
```

must reproduce the committed manifest byte for byte.

## 4. Locked evidence stages

### Stage A: independent source audits over all 96 files

Two auditors independently inspect the pinned source. They are blinded to the
extractor, prior 119-file labels, the other audit, and all checker outputs.
For every file they record:

- whether the submitted file defines an executable workflow root, only a
  fragment, or is insufficient to decide;
- source type: application-like, tutorial/demo, test, or insufficient;
- nodes, control edges, exits, declared tool bindings, and body-level effects;
- every side effect under the fixed HGP definitions;
- every candidate human gate and whether it can block and dominates the effect;
- source citations and a rationale for each nontrivial judgment.

The 32 workflows marked `independent_human_reconstruction=true` receive full
graph reconstructions from both auditors. The operational definitions and
locking rules in `corpus/annotations/ANNOTATION_GUIDE.md` apply.

### Stage B: predictions are locked

Only after both Stage-A files are committed:

- run the corrected extractor and all checks on the 96 files;
- generate each finding and witness;
- run two source-reconstruction model families independently, without showing
  either model the extracted graph or the other reconstruction; and
- freeze all outputs by content hash.

### Stage C: independent defect labeling

Both auditors label:

- every structural and human-gate finding on the 96 files;
- every source-audited violation that the graph pipeline missed; and
- a seeded sample of at least 32 repository-disjoint files on which neither
  source audit nor graph pipeline reports a defect.

Allowed labels are `actionable`, `extraction_artifact`, `policy_inapplicable`,
`abstraction_miss`, `checker_error`, and `insufficient_evidence`. Every label
requires source citations. The no-finding sample is selected only after Stage B
is frozen, by a committed deterministic script that reads prediction presence
but not labels.

### Stage D: agreement, then adjudication

No disagreement is discussed until both auditors' initial files are committed.
Report before adjudication:

- node and edge precision/recall/F1 between humans;
- node-kind and tool/effect agreement;
- raw defect-label agreement, Cohen's kappa, and Krippendorff's alpha;
- each human's agreement with each model reconstruction; and
- agreement stratified by framework and application-like versus other code.

Adjudication produces a separate file; initial labels are immutable. Main
results use adjudicated labels, while all headline conclusions receive
sensitivity analyses under each auditor separately and with every
`insufficient_evidence` case placed on both bounding arms.

## 5. Predeclared primary quantities

The prospective paper reports these quantities separately:

1. corrected-extractor node/edge fidelity and kind/effect fidelity;
2. flag-level actionability by check family;
3. observed structural defects;
4. HGP policy outcomes among source-confirmed side-effecting workflows;
5. false negatives found by the source audit; and
6. the extraction/policy/abstraction decomposition in both directions.

Framework-specific estimates are primary. Corpus-wide descriptive estimates use
the recorded inverse-probability weights. Intervals respect framework strata
and repository sampling. No finite-population correction or GitHub-population
language is used outside an estimator derived for this design.

## 6. Stop/go rules for the manuscript

- **No completed double annotation:** do not submit prospective numeric claims.
- **Low or framework-dependent agreement:** report the disagreement as a result;
  do not call adjudicated labels ground truth.
- **Fewer than 32 complete graph reconstructions:** fidelity remains
  exploratory.
- **Source files are fragments rather than executable roots:** retain the
  file-level title and estimand; do not generalize to deployed workflows.
- **Event completeness is not independently established:** monitor selection
  remains a supplementary conditional implication and never an operational
  safety claim.

These rules are intentionally asymmetric: an unfavorable result changes the
paper's claim rather than the inclusion rule or the evidence.
