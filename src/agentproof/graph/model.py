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
