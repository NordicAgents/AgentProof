"""Tests for trace generation."""

from __future__ import annotations

from agentproof.api import generate_traces
from agentproof.graph.model import (
    AgentGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
    adjacency,
)


def _simple_graph() -> AgentGraph:
    return AgentGraph(
        name="simple",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("llm", NodeKind.LLM),
            GraphNode("tool", NodeKind.TOOL, tools=("search",)),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "llm"),
            GraphEdge("llm", "tool"),
            GraphEdge("tool", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )


def _branching_graph() -> AgentGraph:
    return AgentGraph(
        name="branching",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("router", NodeKind.ROUTER),
            GraphNode("a", NodeKind.LLM),
            GraphNode("b", NodeKind.TOOL, tools=("write",)),
            GraphNode("human", NodeKind.HUMAN),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "router"),
            GraphEdge("router", "a", kind=EdgeKind.CONDITIONAL, condition="path_a"),
            GraphEdge("router", "b", kind=EdgeKind.CONDITIONAL, condition="path_b"),
            GraphEdge("a", "human"),
            GraphEdge("b", "human"),
            GraphEdge("human", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )


def test_traces_start_at_entry():
    graph = _simple_graph()
    traces = generate_traces(graph, n_traces=3)
    assert len(traces) == 3
    for trace in traces:
        assert trace[0]["node_id"] == "entry"


def test_traces_end_at_exit():
    graph = _simple_graph()
    traces = generate_traces(graph, n_traces=3)
    for trace in traces:
        assert trace[-1]["node_id"] == "exit"


def test_traces_follow_edges():
    graph = _simple_graph()
    adj = adjacency(graph)
    traces = generate_traces(graph, n_traces=5)
    for trace in traces:
        for i in range(len(trace) - 1):
            src = trace[i]["node_id"]
            dst = trace[i + 1]["node_id"]
            assert dst in adj[src], f"edge {src}->{dst} not in graph"


def test_event_has_action_type():
    graph = _simple_graph()
    traces = generate_traces(graph, n_traces=1)
    for event in traces[0]:
        assert "action_type" in event
        assert "node_id" in event


def test_tool_event_has_tool_name():
    graph = _simple_graph()
    traces = generate_traces(graph, n_traces=1)
    tool_events = [e for e in traces[0] if e["action_type"] == "tool"]
    assert len(tool_events) > 0
    for e in tool_events:
        assert e["tool_name"] == "search"


def test_human_event_has_tag():
    graph = _branching_graph()
    traces = generate_traces(graph, n_traces=10)
    human_events = [
        e for trace in traces for e in trace if e["action_type"] == "human"
    ]
    assert len(human_events) > 0
    for e in human_events:
        assert "human" in e["tags"]


def test_deterministic_with_same_seed():
    graph = _branching_graph()
    traces1 = generate_traces(graph, n_traces=5, seed=123)
    traces2 = generate_traces(graph, n_traces=5, seed=123)
    assert traces1 == traces2


def test_different_seeds_may_differ():
    graph = _branching_graph()
    traces1 = generate_traces(graph, n_traces=10, seed=1)
    traces2 = generate_traces(graph, n_traces=10, seed=2)
    # With a branching graph and different seeds, at least some traces should differ
    assert traces1 != traces2


def _multi_tool_graph() -> AgentGraph:
    return AgentGraph(
        name="multi_tool",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("tool", NodeKind.TOOL, tools=("t1", "t2", "t3")),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "tool"),
            GraphEdge("tool", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )


def test_multi_tool_node_samples_all_declared_tools():
    """A multi-tool node must sample tool_name uniformly per visit, not pin
    tools[0]. With 60 seeded visits over 3 tools, missing one tool would
    have probability ~3*(2/3)^60 under uniform sampling; the fixed seed
    makes the assertion deterministic."""
    traces = generate_traces(_multi_tool_graph(), n_traces=60, seed=7)
    names = {
        e["tool_name"] for trace in traces for e in trace if e["action_type"] == "tool"
    }
    assert names == {"t1", "t2", "t3"}


def test_multi_tool_sampling_deterministic_with_seed():
    """Tool sampling threads through the seeded rng: same seed, same traces."""
    graph = _multi_tool_graph()
    traces1 = generate_traces(graph, n_traces=10, seed=5)
    traces2 = generate_traces(graph, n_traces=10, seed=5)
    assert traces1 == traces2


def test_toolless_tool_node_emits_bare_visit_event():
    """A TOOL node with NO declared tools still emits an event on every
    visit: the bare visit event {'node_id', 'action_type': 'tool'} with no
    tool_name and no tags. This is the runtime half of the static/runtime
    event-model invariant (see agentproof.verify.temporal): the static
    closure covers exactly this event for tool-less TOOL nodes, so the two
    sides cannot contradict each other (Finding 1 regression)."""
    graph = AgentGraph(
        name="toolless",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("bare", NodeKind.TOOL, tools=()),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "bare"),
            GraphEdge("bare", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )
    traces = generate_traces(graph, n_traces=1)
    bare_events = [e for e in traces[0] if e["node_id"] == "bare"]
    assert bare_events == [{"node_id": "bare", "action_type": "tool"}]


def test_max_steps_limits_trace_length():
    """Traces should not exceed max_steps even in cyclic graphs."""
    graph = AgentGraph(
        name="cycle",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("a", NodeKind.LLM),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "a"),
            GraphEdge("a", "a"),  # self-loop
            GraphEdge("a", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )
    traces = generate_traces(graph, n_traces=3, max_steps=10)
    for trace in traces:
        assert len(trace) <= 10
