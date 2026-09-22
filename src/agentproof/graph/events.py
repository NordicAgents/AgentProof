"""Shared graph-node to event mapping helpers."""

from __future__ import annotations

from typing import Any

from agentproof.graph.model import AgentGraph, NodeKind, node_by_id


def event_for_node(
    node_id: str,
    graph: AgentGraph,
    *,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Map a graph node to one event representing one executed step.

    ``tool_name`` selects the executed tool for a multi-tool node.  When it is
    omitted, the first declared tool is used for backward compatibility.
    """
    node = node_by_id(graph, node_id)
    if node is None:
        return {"node_id": node_id, "action_type": "unknown"}

    event: dict[str, Any] = {"node_id": node.id, "action_type": node.kind.value}
    if node.kind == NodeKind.TOOL and node.tools:
        event["tool_name"] = tool_name if tool_name is not None else node.tools[0]
        event["tags"] = ["tool"]
    elif node.kind == NodeKind.LLM:
        event["tags"] = ["llm_step"]
    elif node.kind == NodeKind.HUMAN:
        event["tags"] = ["human"]
    elif node.kind == NodeKind.ROUTER:
        event["tags"] = ["router"]
    return event
