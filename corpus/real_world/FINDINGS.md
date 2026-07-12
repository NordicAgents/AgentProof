# Real-world GitHub mining study — preliminary findings

Started 2026-07-11 for the ICLR 2027 submission. This replaces the circular
"defect rates on an author-built benchmark" evaluation with base rates measured
on independently authored, publicly available agent workflows.

## Pipeline (all reproducible from this repo)

1. `scripts/mine_github_gh.py --search` — GitHub code search via the authenticated
   `gh` CLI (no PyGithub / token env var). **318 unique candidate repos** across
   LangGraph, CrewAI, AutoGen, ADK.
2. `--clone --extract` — shallow-cloned a **180-repo** sample, scanned **383**
   candidate files, AST-extracted **277 workflow graphs** from **149 distinct repos**
   (LangGraph 206, CrewAI 76). *AutoGen/ADK repos fell past the 180 cap because they
   ranked later in the candidate list — balancing them is the first follow-up.*
3. `scripts/defect_study.py` — first-pass structural + policy checks.
4. `scripts/wf_run.js` (180-agent workflow) — independent ground-truth graphs
   (fidelity) + adversarial defect triage on a stratified 60-workflow sample.
5. `scripts/aggregate_realworld.py` — headline numbers → `validated_results.json`.

## Extractor bug fixed along the way

The AST fallback rewrote `END→__end__` edges *after* deciding whether to add the
exit sentinel, leaving **70% of graphs with empty `exit_ids`** and manufacturing
~197 spurious livelock flags. Fixed (`ast_extractor.py`); empty-exit graphs → 32%,
first-pass structural rate 71%→55%. All 100 unit tests still pass.

## Headline results

**Real workflows are small and simple.** Median 2 real nodes (mean 3.1, max 35);
the vast majority are static linear pipelines.

**Extractor fidelity on real code** (AST fallback vs. 60 independent agent
ground-truth graphs):

| metric | overall | LangGraph | CrewAI |
|---|---|---|---|
| node precision | 0.934 | — | — |
| node recall | 0.896 | — | — |
| edge precision | 0.871 | 0.956 | 0.70 |
| **edge recall** | **0.685** | 0.682 | 0.692 |
| node-kind accuracy | 0.741 | 0.647 | 0.929 |

Dominant kind errors: `tool→llm` (35 — nodes that call tools in their body with no
declared bindings), `passthrough→llm` (21), and `{llm,human,tool}→router` (nodes
with conditional edges). Human nodes misclassified 11×, confirming the naming
heuristic's brittleness on real code.

**Defect triage** (131 flagged defects, adversarially verified; verifier overturned
only 4.6%, always toward "arguable"):

| label | count | share |
|---|---|---|
| real_defect | 1 | 0.8% |
| extraction_artifact | 73 | 55.7% |
| intentional | 50 | 38.2% |
| arguable | 7 | 5.3% |

- **Every one of the 65 structural flags is an extraction artifact.** Validated
  real structural-defect rate on the sample: **0%**.
- The `human_presence` policy flag fires on 98% of workflows, but **91% of those
  firings are intentional** (legitimately low-risk workflows) — 1 real, 6 arguable.
- **Cross-check confirms the mechanism:** mean AST edge-recall was 0.51 for
  workflows with artifact-labeled defects vs. 1.0 for the single real defect.
  Structural checks are only as sound as the extracted topology.

## What this means for the paper

The curated-benchmark numbers (27% structural / 55% policy) **do not generalize**:
in the wild, topology defects are rare and most "missing human gate" flags are
intentional. The real bottleneck to static-verification utility is **extraction
fidelity + policy applicability**, not the check algorithms. This is an honest,
defensible, and more interesting story than "defects are common" — but it changes
the paper's framing (see draft `papers/paper1/arxiv/sections/06a_realworld_study.tex`).

## Next steps to make this ICLR-strong

1. **Balance frameworks** — re-mine so AutoGen/ADK are represented (shuffle candidate
   order or raise `--max-repos`).
2. **Runtime-extractor fidelity** — the paper's *main* extractors read the compiled
   graph object and should beat the static AST fallback's 0.68 edge-recall; run them
   in per-repo sandboxes on a subset to show the ceiling.
3. **Risk-aware policy check** — the human-gate check needs a sensitivity signal so
   it stops firing on low-risk workflows (91% intentional today).
4. **Scale triage** — extend from 60 to a few hundred workflows for tight CIs; add a
   second human annotator on a subset for a κ agreement number.
