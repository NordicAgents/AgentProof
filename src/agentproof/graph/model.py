"""Abstract graph model for agent workflow verification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class NodeKind(Enum):
    ENTRY = "entry"
    EXIT = "exit"
    TOOL = "tool"
    LLM = "llm"
    ROUTER = "router"
    HUMAN = "human"
    SUBGRAPH = "subgraph"
    PASSTHROUGH = "passthrough"


class EdgeKind(Enum):
    DIRECT = "direct"
    CONDITIONAL = "conditional"
    PARALLEL = "parallel"
    LOOP = "loop"


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: NodeKind
    label: str = ""
    tools: tuple[str, ...] = ()
    metadata: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    kind: EdgeKind = EdgeKind.DIRECT
    condition: str = ""
    metadata: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class AgentGraph:
    name: str
    framework: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    entry_id: str
    exit_ids: tuple[str, ...] = ()


def successors(graph: AgentGraph, node_id: str) -> tuple[str, ...]:
    return tuple(e.target for e in graph.edges if e.source == node_id)


def predecessors(graph: AgentGraph, node_id: str) -> tuple[str, ...]:
    return tuple(e.source for e in graph.edges if e.target == node_id)


def node_by_id(graph: AgentGraph, node_id: str) -> GraphNode | None:
    for n in graph.nodes:
        if n.id == node_id:
            return n
    return None


def adjacency(graph: AgentGraph) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = {n.id: [] for n in graph.nodes}
    for e in graph.edges:
        adj.setdefault(e.source, []).append(e.target)
    return adj


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def graph_to_dict(graph: AgentGraph) -> dict[str, Any]:
    """Serialize an AgentGraph to a JSON-compatible dict."""
    return {
        "name": graph.name,
        "framework": graph.framework,
        "entry_id": graph.entry_id,
        "exit_ids": list(graph.exit_ids),
        "nodes": [
            {
                "id": n.id,
                "kind": n.kind.value,
                "label": n.label,
                "tools": list(n.tools),
                "metadata": {k: v for k, v in n.metadata},
            }
            for n in graph.nodes
        ],
        "edges": [
            {
                "source": e.source,
                "target": e.target,
                "kind": e.kind.value,
                "condition": e.condition,
            }
            for e in graph.edges
        ],
    }


def graph_from_dict(data: dict[str, Any]) -> AgentGraph:
    """Deserialize an AgentGraph from a dict (inverse of graph_to_dict)."""
    nodes = tuple(
        GraphNode(
            id=n["id"],
            kind=NodeKind(n["kind"]),
            label=n.get("label", ""),
            tools=tuple(n.get("tools", ())),
            metadata=tuple((k, v) for k, v in n.get("metadata", {}).items()),
        )
        for n in data["nodes"]
    )
    edges = tuple(
        GraphEdge(
            source=e["source"],
            target=e["target"],
            kind=EdgeKind(e.get("kind", "direct")),
            condition=e.get("condition", ""),
        )
        for e in data["edges"]
    )
    return AgentGraph(
        name=data["name"],
        framework=data["framework"],
        nodes=nodes,
        edges=edges,
        entry_id=data["entry_id"],
        exit_ids=tuple(data.get("exit_ids", ())),
    )
