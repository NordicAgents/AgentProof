# Agent Workflow Corpus

Real-world-inspired agent workflow definitions for evaluation.
Each workflow is defined as a standalone AgentGraph JSON in `graphs/`.

## Sources

Workflows are modeled after patterns found in open-source repositories
using LangGraph, CrewAI, AutoGen, and Google ADK. See `sources.json`
for attribution.

## Structure

- `graphs/` — Extracted AgentGraph JSON files
- `ground_truth/` — Manually annotated ground truth for extractor accuracy
- `sources.json` — Source attribution for each workflow
