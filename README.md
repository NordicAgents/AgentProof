# Agentproof

Static graph verification for agent workflows. Prove safety properties on your workflow graph **before deployment** — no runtime overhead, no gatekeeping layer.

Supports **LangGraph**, **Google ADK**, **AutoGen**, and **CrewAI**.

## Install

```bash
pip install agentproof
```

With framework extractors:

```bash
pip install agentproof[langgraph]
pip install agentproof[adk]
pip install agentproof[autogen]
pip install agentproof[crewai]
pip install agentproof[all-frameworks]
```

## Quick Start

```python
from agentproof import verify
from agentproof.graph.model import (
    AgentGraph, GraphNode, GraphEdge, NodeKind, EdgeKind,
)

# Build a graph (or extract one from a framework — see below)
graph = AgentGraph(
    name="my_pipeline",
    framework="manual",
    nodes=(
        GraphNode(id="entry", kind=NodeKind.ENTRY, label="start"),
        GraphNode(id="fetch", kind=NodeKind.TOOL, label="Fetch", tools=("http_get",)),
        GraphNode(id="review", kind=NodeKind.HUMAN, label="Human Review"),
        GraphNode(id="store", kind=NodeKind.TOOL, label="Store", tools=("db_insert",)),
        GraphNode(id="exit", kind=NodeKind.EXIT, label="end"),
    ),
    edges=(
        GraphEdge(source="entry", target="fetch"),
        GraphEdge(source="fetch", target="review"),
        GraphEdge(source="review", target="store"),
        GraphEdge(source="store", target="exit"),
    ),
    entry_id="entry",
    exit_ids=("exit",),
)

report = verify(graph, require_human=True)
print(report["structural"])
```

## Features

- **Structural checks** — reachability, dead-end detection, human-in-the-loop enforcement, tool declaration coverage, router edge validation, entry/exit structure
- **Temporal verification (LTL)** — define safety rules in a lightweight LTL DSL (e.g. `G !tool:rm_rf`), compile to DFA monitors, and verify against simulated traces or statically via graph-DFA product construction
- **Framework extractors** — convert native workflow objects from LangGraph, ADK, AutoGen, and CrewAI into Agentproof's framework-agnostic `AgentGraph`
- **Trace generation** — random-walk trace generator for temporal policy testing
- **Typed** — full type annotations, `py.typed` marker

## Supported Frameworks

| Framework | Extra | Extractor |
|-----------|-------|-----------|
| LangGraph | `agentproof[langgraph]` | `agentproof.graph.extract._langgraph` |
| Google ADK | `agentproof[adk]` | `agentproof.graph.extract._adk` |
| AutoGen | `agentproof[autogen]` | `agentproof.graph.extract._autogen` |
| CrewAI | `agentproof[crewai]` | `agentproof.graph.extract._crewai` |

You can also construct an `AgentGraph` directly without any framework dependency.

## Examples

See the [`examples/`](examples/) directory for complete walkthroughs:

- `full_verification.py` — end-to-end structural + temporal verification (no framework needed)
- `langgraph_customer_support.py` — extract and verify a LangGraph agent
- `adk_pipeline.py` — Google ADK extraction
- `autogen_debate.py` — AutoGen team verification
- `crewai_research_crew.py` — CrewAI crew verification

## License

MIT
