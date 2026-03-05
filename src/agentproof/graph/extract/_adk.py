"""Google ADK agent tree extractor."""

from __future__ import annotations

from typing import Any

from agentproof.graph.model import (
    AgentGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)


def _agent_type_name(agent: Any) -> str:
    return type(agent).__name__


def _classify_agent(agent: Any) -> NodeKind:
    type_name = _agent_type_name(agent)
    if type_name in ("SequentialAgent", "ParallelAgent", "LoopAgent"):
        return NodeKind.SUBGRAPH
    agent_name = getattr(agent, "name", "") or ""
    if isinstance(agent_name, str) and "human" in agent_name.lower():
        return NodeKind.HUMAN
    if hasattr(agent, "tools") and agent.tools:
        return NodeKind.TOOL
    if hasattr(agent, "model") and agent.model:
        return NodeKind.LLM
    return NodeKind.LLM


def _get_tools(agent: Any) -> tuple[str, ...]:
    if not hasattr(agent, "tools") or not agent.tools:
        return ()
    names: list[str] = []
    for t in agent.tools:
        name = getattr(t, "name", None) or getattr(t, "__name__", str(t))
        names.append(name)
    return tuple(names)


def _walk(
    agent: Any,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    seen: set[str],
) -> str:
    """Walk the agent tree and return the agent's node id."""
    agent_name = getattr(agent, "name", None) or _agent_type_name(agent)
    nid = agent_name
    # Deduplicate ids
    if nid in seen:
        counter = 1
        while f"{nid}_{counter}" in seen:
            counter += 1
        nid = f"{nid}_{counter}"
    seen.add(nid)

    type_name = _agent_type_name(agent)
    sub_agents = getattr(agent, "sub_agents", None) or []

    if type_name == "SequentialAgent" and sub_agents:
        nodes.append(GraphNode(id=nid, kind=NodeKind.SUBGRAPH, label=agent_name))
        child_ids: list[str] = []
        for child in sub_agents:
            cid = _walk(child, nodes, edges, seen)
            child_ids.append(cid)
        # Chain children sequentially
        for i in range(len(child_ids) - 1):
            edges.append(GraphEdge(source=child_ids[i], target=child_ids[i + 1]))
        # Parent connects to first child
        edges.append(GraphEdge(source=nid, target=child_ids[0]))
        return nid

    if type_name == "ParallelAgent" and sub_agents:
        nodes.append(GraphNode(id=nid, kind=NodeKind.SUBGRAPH, label=agent_name))
        for child in sub_agents:
            cid = _walk(child, nodes, edges, seen)
            edges.append(GraphEdge(source=nid, target=cid, kind=EdgeKind.PARALLEL))
        return nid

    if type_name == "LoopAgent" and sub_agents:
        nodes.append(GraphNode(id=nid, kind=NodeKind.SUBGRAPH, label=agent_name))
        child_ids = []
        for child in sub_agents:
            cid = _walk(child, nodes, edges, seen)
            child_ids.append(cid)
        # Chain children sequentially
        for i in range(len(child_ids) - 1):
            edges.append(GraphEdge(source=child_ids[i], target=child_ids[i + 1]))
        # Parent to first child
        edges.append(GraphEdge(source=nid, target=child_ids[0]))
        # Back-edge: last child to first child
        if len(child_ids) >= 2:
            edges.append(GraphEdge(source=child_ids[-1], target=child_ids[0], kind=EdgeKind.LOOP))
        else:
            edges.append(GraphEdge(source=child_ids[0], target=child_ids[0], kind=EdgeKind.LOOP))
        return nid

    # Leaf agent
    kind = _classify_agent(agent)
    tools = _get_tools(agent)
    nodes.append(GraphNode(id=nid, kind=kind, label=agent_name, tools=tools))

    # Recurse into any sub_agents even for non-composite types
    for child in sub_agents:
        cid = _walk(child, nodes, edges, seen)
        edges.append(GraphEdge(source=nid, target=cid))

    return nid


def extract_adk(agent: Any) -> AgentGraph:
    """Extract an AgentGraph from a Google ADK Agent tree."""
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    seen: set[str] = set()

    root_id = _walk(agent, nodes, edges, seen)

    # Synthesize entry/exit
    entry = GraphNode(id="__entry__", kind=NodeKind.ENTRY, label="__entry__")
    exit_node = GraphNode(id="__exit__", kind=NodeKind.EXIT, label="__exit__")
    nodes.insert(0, entry)
    nodes.append(exit_node)
    edges.insert(0, GraphEdge(source="__entry__", target=root_id))

    # Find leaf nodes (no outgoing edges) and connect to exit
    outgoing = {e.source for e in edges}
    all_ids = {n.id for n in nodes} - {"__entry__", "__exit__"}
    leaves = all_ids - outgoing
    for leaf_id in sorted(leaves):
        edges.append(GraphEdge(source=leaf_id, target="__exit__"))

    name = getattr(agent, "name", "adk_agent")

    return AgentGraph(
        name=str(name),
        framework="adk",
        nodes=tuple(nodes),
        edges=tuple(edges),
        entry_id="__entry__",
        exit_ids=("__exit__",),
    )
