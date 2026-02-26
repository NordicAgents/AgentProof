"""LangGraph StateGraph extractor."""

from __future__ import annotations

from typing import Any

from agentproof.graph.model import (
    AgentGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)

_ENTRY_SENTINEL = "__start__"
_EXIT_SENTINEL = "__end__"


def _classify_node(node_id: str, data: Any) -> NodeKind:
    if node_id == _ENTRY_SENTINEL:
        return NodeKind.ENTRY
    if node_id == _EXIT_SENTINEL:
        return NodeKind.EXIT

    # Detect tool-calling nodes via metadata or bound tools
    if hasattr(data, "metadata") and isinstance(data.metadata, dict):
        if data.metadata.get("tools"):
            return NodeKind.TOOL

    if hasattr(data, "tools") and data.tools:
        return NodeKind.TOOL

    name = getattr(data, "name", str(node_id)).lower()
    if "human" in name:
        return NodeKind.HUMAN
    if "route" in name or "router" in name:
        return NodeKind.ROUTER

    return NodeKind.LLM


def _get_tools(data: Any) -> tuple[str, ...]:
    tools: list[str] = []
    if hasattr(data, "metadata") and isinstance(data.metadata, dict):
        for t in data.metadata.get("tools", []):
            name = getattr(t, "name", None) or getattr(t, "__name__", str(t))
            tools.append(name)
    if hasattr(data, "tools"):
        for t in data.tools or []:
            name = getattr(t, "name", None) or getattr(t, "__name__", str(t))
            if name not in tools:
                tools.append(name)
    return tuple(tools)


def extract_langgraph(graph: Any) -> AgentGraph:
    """Extract an AgentGraph from a LangGraph CompiledStateGraph or StateGraph."""
    # Compile if needed
    if hasattr(graph, "compile") and not hasattr(graph, "get_graph"):
        graph = graph.compile()

    drawable = graph.get_graph(xray=True)

    nodes: list[GraphNode] = []
    node_ids: set[str] = set()

    raw_nodes = drawable.nodes
    if isinstance(raw_nodes, dict):
        # Real LangGraph Graph: .nodes is dict[str, Node]
        node_items = list(raw_nodes.items())
    elif raw_nodes and isinstance(raw_nodes, (list, tuple)):
        first = raw_nodes[0]
        if isinstance(first, str):
            # List of string IDs (shouldn't normally happen but handle it)
            node_items = [(n, None) for n in raw_nodes]
        else:
            # List of Node objects (stub path)
            node_items = [(getattr(n, "id", str(n)), n) for n in raw_nodes]
    else:
        node_items = []

    for nid, data in node_items:
        # For stub objects, try _nodes dict for richer data
        if hasattr(drawable, "_nodes") and isinstance(getattr(drawable, "_nodes", None), dict):
            data = drawable._nodes.get(nid, data)

        kind = _classify_node(nid, data)
        label = nid
        if nid == _ENTRY_SENTINEL:
            label = "__entry__"
        elif nid == _EXIT_SENTINEL:
            label = "__exit__"

        tools = _get_tools(data) if data is not None else ()
        nodes.append(GraphNode(id=nid, kind=kind, label=label, tools=tools))
        node_ids.add(nid)

    edges: list[GraphEdge] = []
    for edge in drawable.edges:
        source = edge.source if hasattr(edge, "source") else edge[0]
        target = edge.target if hasattr(edge, "target") else edge[1]
        is_conditional = getattr(edge, "conditional", False)
        condition = getattr(edge, "data", "") or ""
        if is_conditional:
            ekind = EdgeKind.CONDITIONAL
        else:
            ekind = EdgeKind.DIRECT
        edges.append(GraphEdge(source=source, target=target, kind=ekind, condition=str(condition)))

    entry_id = _ENTRY_SENTINEL
    exit_ids = tuple(n.id for n in nodes if n.kind == NodeKind.EXIT)

    name = getattr(graph, "name", None) or getattr(drawable, "name", "langgraph")

    return AgentGraph(
        name=str(name),
        framework="langgraph",
        nodes=tuple(nodes),
        edges=tuple(edges),
        entry_id=entry_id,
        exit_ids=exit_ids,
    )
