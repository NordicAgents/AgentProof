"""Structural verification checks over AgentGraph topology."""

from __future__ import annotations

from typing import Any

from agentproof.graph.model import AgentGraph, EdgeKind, NodeKind, adjacency


def run_structural_checks(graph: AgentGraph, *, require_human: bool) -> dict[str, Any]:
    """Run the standard structural checks described in the paper.

    Checks implemented (exactly five):
      1) Exit reachability
      2) Dead-end detection (excluding EXIT)
      3) Router shape (ROUTER outgoing edges must be CONDITIONAL)
      4) Human-in-the-loop presence (optional, controlled by require_human)
      5) Tool declaration checks (TOOL nodes must declare tools)

    Returns a JSON-serializable report.
    """

    adj = adjacency(graph)

    checks: list[dict[str, Any]] = []

    # 1) Exit reachability
    reachable: set[str] = set()
    frontier: list[str] = [graph.entry_id]
    while frontier:
        node_id = frontier.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        frontier.extend(adj.get(node_id, []))

    missing_exits = sorted(eid for eid in graph.exit_ids if eid not in reachable)
    checks.append(
        {
            "check_id": "exit_reachability",
            "passed": len(missing_exits) == 0,
            "missing_exits": missing_exits,
        }
    )

    # 2) Dead-end detection (excluding EXIT)
    dead_ends = sorted(
        n.id
        for n in graph.nodes
        if n.kind != NodeKind.EXIT and len(adj.get(n.id, [])) == 0
    )
    checks.append(
        {
            "check_id": "dead_ends",
            "passed": len(dead_ends) == 0,
            "dead_ends": dead_ends,
        }
    )

    # 3) Router shape checks
    router_ids = sorted(n.id for n in graph.nodes if n.kind == NodeKind.ROUTER)
    router_violations: list[dict[str, Any]] = []
    for rid in router_ids:
        outgoing = [e for e in graph.edges if e.source == rid]
        bad_edges = [
            {"target": e.target, "kind": e.kind.value}
            for e in outgoing
            if e.kind != EdgeKind.CONDITIONAL
        ]
        if bad_edges:
            router_violations.append({"router": rid, "bad_edges": bad_edges})
    checks.append(
        {
            "check_id": "router_shape",
            "passed": len(router_violations) == 0,
            "router_count": len(router_ids),
            "violations": router_violations,
        }
    )

    # 4) Human-in-the-loop presence
    human_nodes = sorted(n.id for n in graph.nodes if n.kind == NodeKind.HUMAN)
    checks.append(
        {
            "check_id": "human_presence",
            "passed": (not require_human) or len(human_nodes) > 0,
            "required": bool(require_human),
            "human_nodes": human_nodes,
        }
    )

    # 5) Tool declaration checks
    tool_nodes = [n for n in graph.nodes if n.kind == NodeKind.TOOL]
    missing_tool_decls = sorted(n.id for n in tool_nodes if not n.tools)
    checks.append(
        {
            "check_id": "tool_declarations",
            "passed": len(missing_tool_decls) == 0,
            "tool_node_count": len(tool_nodes),
            "tool_nodes_missing_tools": missing_tool_decls,
        }
    )

    passed_count = sum(1 for c in checks if c.get("passed") is True)
    return {
        "passed_count": int(passed_count),
        "total": int(len(checks)),
        "checks": checks,
    }

