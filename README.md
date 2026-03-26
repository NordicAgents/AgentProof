# Agentproof

Static graph verification for agent workflows. Prove safety properties on your workflow graph **before deployment** — no runtime overhead, no gatekeeping layer.

Supports **LangGraph**, **Google ADK**, **AutoGen**, and **CrewAI**.

## Install

```bash
pip install agentproofx
```

With framework extractors:

```bash
pip install agentproofx[langgraph]
pip install agentproofx[adk]
pip install agentproofx[autogen]
pip install agentproofx[crewai]
pip install agentproofx[all-frameworks]
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
| LangGraph | `agentproofx[langgraph]` | `agentproof.graph.extract._langgraph` |
| Google ADK | `agentproofx[adk]` | `agentproof.graph.extract._adk` |
| AutoGen | `agentproofx[autogen]` | `agentproof.graph.extract._autogen` |
| CrewAI | `agentproofx[crewai]` | `agentproof.graph.extract._crewai` |

You can also construct an `AgentGraph` directly without any framework dependency.

## Examples

### Structural verification (no framework needed)

```python
from agentproof import verify
from agentproof.graph.model import AgentGraph, GraphNode, GraphEdge, NodeKind

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
for check in report["structural"]["checks"]:
    status = "PASS" if check["passed"] else "FAIL"
    print(f"[{status}] {check['check_id']}")
```

### Temporal safety rules (LTL)

```python
from agentproof import verify
from agentproof.monitor.ltl import MonitorRuleSpec

# Define rules: "never call rm_rf" and "fetch must be followed by validate"
rules = [
    MonitorRuleSpec(rule_id="no_rm_rf", dsl="G !tool:rm_rf", on_violation="halt"),
    MonitorRuleSpec(rule_id="fetch_then_validate", dsl="action:fetch -> F action:validate", on_violation="block"),
]

# Simulate an event trace and check violations
trace = [
    {"tool_name": "http_get", "action_type": "fetch"},
    {"action_type": "validate"},
    {"tool_name": "db_insert", "action_type": "store"},
]

report = verify(graph, monitor_rules=rules, event_trace=trace)
print(report["monitor"]["final_decision"])  # status, denied, halt, escalate
```

### Extract from LangGraph

```python
from langgraph.graph import StateGraph, END
from agentproof.graph import extract_langgraph
from agentproof import verify

# Build your LangGraph as usual
workflow = StateGraph(dict)
workflow.add_node("agent", agent_fn)
workflow.add_node("tool", tool_fn)
workflow.set_entry_point("agent")
workflow.add_edge("tool", "agent")
workflow.add_conditional_edges("agent", router, {"continue": "tool", "end": END})

# Extract and verify
graph = extract_langgraph(workflow.compile())
report = verify(graph, require_human=True)
```

### Extract from Google ADK

```python
from google.adk.agents import LlmAgent, SequentialAgent
from agentproof.graph import extract_adk
from agentproof import verify

pipeline = SequentialAgent(
    name="pipeline",
    sub_agents=[
        LlmAgent(name="ingest", model="gemini-2.0-flash"),
        LlmAgent(name="process", model="gemini-2.0-flash"),
        LlmAgent(name="publish", model="gemini-2.0-flash"),
    ],
)

graph = extract_adk(pipeline)
report = verify(graph)
```

### Extract from CrewAI

```python
from crewai import Agent, Task, Crew, Process
from agentproof.graph import extract_crewai
from agentproof import verify

researcher = Agent(role="Researcher", goal="Find data", backstory="...")
writer = Agent(role="Writer", goal="Write report", backstory="...")

crew = Crew(
    agents=[researcher, writer],
    tasks=[
        Task(description="Gather data", agent=researcher, expected_output="Data"),
        Task(description="Write report", agent=writer, expected_output="Report"),
    ],
    process=Process.sequential,
)

graph = extract_crewai(crew)
report = verify(graph)
```

See [`examples/`](examples/) for full runnable versions of each example.

## License

MIT

## Citation

If you find this work useful, please cite:

```bibtex
@article{xavier2026agentproof,
  title={Agentproof: Static Verification of Agent Workflow Graphs},
  author={Xavier, Melwin and Jolly, Melveena and Xavier, Midhun and others},
  journal={arXiv preprint arXiv:2603.20356},
  year={2026}
}
