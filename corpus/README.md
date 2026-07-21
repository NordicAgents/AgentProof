# Agent Workflow Corpus

Real-world-inspired agent workflow definitions for evaluation.
Each workflow is defined as a standalone AgentGraph JSON in `graphs/`.

## Sources

Workflows are modeled after patterns found in open-source repositories
using LangGraph, CrewAI, AutoGen, and Google ADK. See `sources.json`
for attribution.

## Structure

- `graphs/` — the 18 curated AgentGraph JSON files (this directory)
- `curated/` — curated workflow sources used by the defect study
- `policies/` — the 15 temporal policy DSL strings
- `traces/` — generated execution traces
- `annotations/` — human-annotation protocol and sample manifests
- `comparisons/` — cross-tool comparison inputs
- `sources.json` — source attribution for each workflow
- `real_world/` — the mined corpus (922 analyzed extracted graphs, 252 repos)
  and all real-world analysis artifacts

## Reference graphs (extractor accuracy)

Reference graphs used to score extractor accuracy live in
**`real_world/ground_truth/`** — there is no top-level `corpus/ground_truth/`
directory.

**These reference graphs are LLM reconstructions, not human annotations.**
Each was reconstructed from the workflow's source alone, blind to the
extractor's output, by an LLM pass (`scripts/wf_run.js` / `wf_run_v2.js`);
reconstruction confidence is recorded per graph (77 high / 33 medium / 9 low).
Two-annotator independent human validation has **not** been performed — the
protocol and drawn samples are staged in `annotations/` but not executed.

The directory name `ground_truth/` is retained for path compatibility with
existing artifacts and scripts; it is a misnomer. The paper deliberately says
"LLM-reconstructed reference graphs" and never "ground truth", and any
description of these files as *manually* or *human* annotated is incorrect.

The directory holds 120 files; **119** are analyzed. The excluded file is the
`NordicAgents__AgentProof` self-repo fixture that also accounts for 8 of the
930 mined graphs (930 → 922).
