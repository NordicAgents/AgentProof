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


# ---------------------------------------------------------------------------
# Provenance vocabulary (research plan 3.4D)
# ---------------------------------------------------------------------------
# Convention: the two axes are independent.
#   origin     = the information SOURCE the element was derived from
#                (live runtime object | source AST | fabricated by us).
#   confidence = the STRENGTH of the structural claim
#                (exact = declared, may = plausible inference, heuristic = guess).
# In particular, an ordering/relation that a runtime extractor infers from a
# LIVE object (e.g. chaining a Crew's task list, expanding a round-robin team)
# is origin="runtime" with a non-exact confidence -- NOT "ast_inferred",
# which is reserved for inferences made over source AST.
#
# ``origin`` values:
#   runtime      - derived from a live framework object: declared nodes,
#                  add_edge edges, declared tool bindings, and also relations
#                  the extractor infers from that object's semantics
#   ast_explicit - parsed from an explicit source-code call (add_edge/add_node/...)
#   ast_inferred - derived from source AST; the element is real, but the
#                  relation/ordering was inferred rather than declared in code
#   synthesized  - element fabricated by the extractor (entry/exit sentinels,
#                  guessed hookups); corresponds to nothing in the source
#   unknown      - provenance was not recorded (legacy data)
VALID_ORIGINS = frozenset(
    {"runtime", "ast_explicit", "ast_inferred", "synthesized", "unknown"}
)

# ``confidence`` records how strong the structural claim is:
#   exact     - the element is exactly as declared in the framework/source
#   may       - plausible inference; may over- or under-approximate structure
#   heuristic - the element rests on a guess (naming, connectivity, ordering)
#
# For nodes, confidence covers the WEAKEST attribute claim (kind, tool
# bindings) -- not mere existence: a node whose kind was guessed from a name
# substring is emitted with confidence="may" even when its existence is
# certain.
VALID_CONFIDENCES = frozenset({"exact", "may", "heuristic"})


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: NodeKind
    label: str = ""
    tools: tuple[str, ...] = ()
    metadata: tuple[tuple[str, Any], ...] = ()
    # Provenance (plain strings for JSON simplicity; see VALID_ORIGINS /
    # VALID_CONFIDENCES for the vocabulary).
    origin: str = "unknown"
    confidence: str = "may"
    source_span: str = ""  # "file:start_line:end_line" or "" when unavailable


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    kind: EdgeKind = EdgeKind.DIRECT
    condition: str = ""
    metadata: tuple[tuple[str, Any], ...] = ()
    # Provenance (see VALID_ORIGINS / VALID_CONFIDENCES).
    origin: str = "unknown"
    confidence: str = "may"
    source_span: str = ""  # "file:start_line:end_line" or "" when unavailable


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
                "origin": n.origin,
                "confidence": n.confidence,
                "source_span": n.source_span,
            }
            for n in graph.nodes
        ],
        "edges": [
            {
                "source": e.source,
                "target": e.target,
                "kind": e.kind.value,
                "condition": e.condition,
                "origin": e.origin,
                "confidence": e.confidence,
                "source_span": e.source_span,
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
            # Legacy corpus JSON predates provenance: default to unknown/may.
            origin=n.get("origin", "unknown"),
            confidence=n.get("confidence", "may"),
            source_span=n.get("source_span", ""),
        )
        for n in data["nodes"]
    )
    edges = tuple(
        GraphEdge(
            source=e["source"],
            target=e["target"],
            kind=EdgeKind(e.get("kind", "direct")),
            condition=e.get("condition", ""),
            origin=e.get("origin", "unknown"),
            confidence=e.get("confidence", "may"),
            source_span=e.get("source_span", ""),
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
