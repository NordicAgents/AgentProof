# Agentproof Examples

Example projects demonstrating pre-deployment verification of agent workflows
using **real framework APIs** (LangGraph, Google ADK, AutoGen, CrewAI).

No LLM execution or API keys required — agents are constructed but never run.

## Quick Start

```bash
# From the repo root — install with all frameworks
pip install -e ".[all-frameworks]"

# Or install individual frameworks
pip install -e ".[langgraph]"
pip install -e ".[adk]"
pip install -e ".[autogen]"
pip install -e ".[crewai]"

# Run any example
python examples/full_verification.py          # no deps needed
python examples/langgraph_customer_support.py
python examples/adk_pipeline.py
python examples/autogen_debate.py
python examples/crewai_research_crew.py
```

## Examples

### `full_verification.py` — Start Here

End-to-end walkthrough with no framework dependency. Builds a data pipeline graph
by hand, compiles LTL safety rules into DFA monitors, simulates event traces, and
reports violations.

Demonstrates: graph construction, structural analysis, LTL compilation, event simulation.

```bash
python examples/full_verification.py
```

### `langgraph_customer_support.py` — LangGraph

Customer support bot built with a real `StateGraph`. Uses `add_node`, `add_edge`,
`add_conditional_edges`, and `compile()`. Extracts the graph from the compiled
state graph, verifies structural properties (router branches, dead-end detection),
and runs temporal checks (no account deletion, billing access requires review).

```bash
pip install -e ".[langgraph]"
python examples/langgraph_customer_support.py
```

### `adk_pipeline.py` — Google ADK

Hierarchical agent tree using real `LlmAgent`, `SequentialAgent`, `ParallelAgent`,
and `LoopAgent` from `google.adk.agents`. Tools are plain Python functions.
Verifies parallel fork structure, loop back-edges, subgraph containment, and
temporal properties (no database drops, ingest-then-validate).

```bash
pip install -e ".[adk]"
python examples/adk_pipeline.py
```

### `autogen_debate.py` — AutoGen

Multi-agent debate using real AutoGen v0.4 `AssistantAgent` and
`RoundRobinGroupChat`. Agents use a `MagicMock()` model client (no API key needed).
Shows three topologies: moderated (advocate/critic isolated through moderator),
round-robin, and direct list with transitions. Checks self-loop absence, speaker
isolation, and temporal rules (no email sending, decisions require review).

```bash
pip install -e ".[autogen]"
python examples/autogen_debate.py
```

### `crewai_research_crew.py` — CrewAI

Research pipeline using real CrewAI `Agent`, `Task`, `Crew`, and `Process` objects.
Sets a dummy `OPENAI_API_KEY` env var to satisfy CrewAI validation (no LLM calls).
Covers both sequential and hierarchical process modes. Verifies task ordering,
reachability, and temporal rules (no code execution, fetch-before-analyze).

```bash
pip install -e ".[crewai]"
python examples/crewai_research_crew.py
```

## What Each Example Covers

| Example | Graph Extraction | Structural Checks | LTL Monitors | Event Simulation |
|---------|:---:|:---:|:---:|:---:|
| `full_verification.py` | manual | yes | yes | yes |
| `langgraph_customer_support.py` | `extract_langgraph` | yes | yes | yes |
| `adk_pipeline.py` | `extract_adk` | yes | yes | yes |
| `autogen_debate.py` | `extract_autogen` | yes | yes | yes |
| `crewai_research_crew.py` | `extract_crewai` | yes | yes | yes |

## Common Patterns

### Extract a graph

```python
from agentproof.graph import extract_langgraph
graph = extract_langgraph(my_compiled_state_graph)
```

### Inspect structure

```python
from agentproof.graph import adjacency, successors, node_by_id, NodeKind

adj = adjacency(graph)
for node in graph.nodes:
    if node.kind == NodeKind.TOOL:
        print(f"{node.id} uses tools: {node.tools}")
```

### Define and compile safety rules

```python
from agentproof.monitor.ltl import MonitorRuleSpec, compile_monitor_rule

rule = MonitorRuleSpec("no_delete", "G !tool:delete", on_violation="block")
compiled = compile_monitor_rule(rule)
```

### Simulate events

```python
from agentproof.monitor.ltl import evaluate_monitors

state = {}
for event in event_stream:
    state, snapshots, decision = evaluate_monitors((compiled,), state, event)
    if decision.denied:
        print(f"Blocked: {[s.rule_id for s in snapshots if s.violation]}")
```
