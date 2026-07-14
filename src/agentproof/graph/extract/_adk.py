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


def _classify_agent(agent: Any) -> tuple[NodeKind, bool]:
    """Classify an agent.

    Returns ``(kind, guessed)`` where ``guessed`` is True when the kind rests
    on a name-substring heuristic rather than declared structure (framework
    class, bound tools, declared model).
    """
    type_name = _agent_type_name(agent)
    if type_name in ("SequentialAgent", "ParallelAgent", "LoopAgent"):
        return NodeKind.SUBGRAPH, False
    agent_name = getattr(agent, "name", "") or ""
    if isinstance(agent_name, str) and "human" in agent_name.lower():
        return NodeKind.HUMAN, True
    if hasattr(agent, "tools") and agent.tools:
        return NodeKind.TOOL, False
    if hasattr(agent, "model") and agent.model:
        return NodeKind.LLM, False
    return NodeKind.LLM, False


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
        # The composite agent object is read from the live tree: runtime/exact.
        nodes.append(
            GraphNode(
                id=nid, kind=NodeKind.SUBGRAPH, label=agent_name,
                origin="runtime", confidence="exact",
            )
        )
        child_ids: list[str] = []
        for child in sub_agents:
            cid = _walk(child, nodes, edges, seen)
            child_ids.append(cid)
        # Chain children sequentially: the ordering is derived from
        # SequentialAgent semantics, not a declared edge.  The information
        # source is still the live object (no AST involved) -> runtime/may.
        for i in range(len(child_ids) - 1):
            edges.append(
                GraphEdge(
                    source=child_ids[i], target=child_ids[i + 1],
                    origin="runtime", confidence="may",
                )
            )
        # Parent connects to first child (containment turned into an edge).
        edges.append(
            GraphEdge(
                source=nid, target=child_ids[0],
                origin="runtime", confidence="may",
            )
        )
        return nid

    if type_name == "ParallelAgent" and sub_agents:
        nodes.append(
            GraphNode(
                id=nid, kind=NodeKind.SUBGRAPH, label=agent_name,
                origin="runtime", confidence="exact",
            )
        )
        for child in sub_agents:
            cid = _walk(child, nodes, edges, seen)
            # Fan-out derived from ParallelAgent containment semantics.
            edges.append(
                GraphEdge(
                    source=nid, target=cid, kind=EdgeKind.PARALLEL,
                    origin="runtime", confidence="may",
                )
            )
        return nid

    if type_name == "LoopAgent" and sub_agents:
        nodes.append(
            GraphNode(
                id=nid, kind=NodeKind.SUBGRAPH, label=agent_name,
                origin="runtime", confidence="exact",
            )
        )
        child_ids = []
        for child in sub_agents:
            cid = _walk(child, nodes, edges, seen)
            child_ids.append(cid)
        # Chain children sequentially (derived from LoopAgent semantics).
        for i in range(len(child_ids) - 1):
            edges.append(
                GraphEdge(
                    source=child_ids[i], target=child_ids[i + 1],
                    origin="runtime", confidence="may",
                )
            )
        # Parent to first child (containment turned into an edge).
        edges.append(
            GraphEdge(
                source=nid, target=child_ids[0],
                origin="runtime", confidence="may",
            )
        )
        # Back-edge: real nodes, but the loop repetition edge is inferred
        # from LoopAgent semantics (live object, no AST) -> runtime/may.
        if len(child_ids) >= 2:
            edges.append(
                GraphEdge(
                    source=child_ids[-1], target=child_ids[0], kind=EdgeKind.LOOP,
                    origin="runtime", confidence="may",
                )
            )
        else:
            edges.append(
                GraphEdge(
                    source=child_ids[0], target=child_ids[0], kind=EdgeKind.LOOP,
                    origin="runtime", confidence="may",
                )
            )
        return nid

    # Leaf agent: read directly from the live tree, including declared tools.
    # A kind assigned by a name-substring heuristic (e.g. HUMAN from "human"
    # in the name) is only a plausible inference -> confidence "may"; kinds
    # from declared structure (tools, model, framework class) stay "exact".
    kind, kind_guessed = _classify_agent(agent)
    tools = _get_tools(agent)
    nodes.append(
        GraphNode(
            id=nid, kind=kind, label=agent_name, tools=tools,
            origin="runtime", confidence="may" if kind_guessed else "exact",
        )
    )

    # Recurse into any sub_agents even for non-composite types.
    # Judgment call: the delegation edge is inferred from containment, the
    # framework declares no explicit transfer edge -> runtime/may (the
    # inference is made from the live object, no AST involved).
    for child in sub_agents:
        cid = _walk(child, nodes, edges, seen)
        edges.append(
            GraphEdge(
                source=nid, target=cid,
                origin="runtime", confidence="may",
            )
        )

    return nid


def extract_adk(agent: Any) -> AgentGraph:
    """Extract an AgentGraph from a Google ADK Agent tree."""
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    seen: set[str] = set()

    root_id = _walk(agent, nodes, edges, seen)

    # Synthesize entry/exit: ADK declares no such nodes, they are fabricated.
    entry = GraphNode(
        id="__entry__", kind=NodeKind.ENTRY, label="__entry__",
        origin="synthesized", confidence="may",
    )
    exit_node = GraphNode(
        id="__exit__", kind=NodeKind.EXIT, label="__exit__",
        origin="synthesized", confidence="may",
    )
    nodes.insert(0, entry)
    nodes.append(exit_node)
    # Judgment call: execution certainly starts at the root agent, but the
    # edge touches a fabricated node -> synthesized/may.
    edges.insert(
        0,
        GraphEdge(
            source="__entry__", target=root_id,
            origin="synthesized", confidence="may",
        ),
    )

    # Find leaf nodes (no outgoing edges) and connect to exit: this is guessed
    # connectivity (a leaf is not necessarily where the workflow terminates).
    outgoing = {e.source for e in edges}
    all_ids = {n.id for n in nodes} - {"__entry__", "__exit__"}
    leaves = all_ids - outgoing
    for leaf_id in sorted(leaves):
        edges.append(
            GraphEdge(
                source=leaf_id, target="__exit__",
                origin="synthesized", confidence="heuristic",
            )
        )

    name = getattr(agent, "name", "adk_agent")

    return AgentGraph(
        name=str(name),
        framework="adk",
        nodes=tuple(nodes),
        edges=tuple(edges),
        entry_id="__entry__",
        exit_ids=("__exit__",),
    )
