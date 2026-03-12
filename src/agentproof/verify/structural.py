"""Structural verification checks over AgentGraph topology."""

from __future__ import annotations

from collections import deque
from typing import Any

from agentproof.graph.model import AgentGraph, EdgeKind, NodeKind, adjacency


def _find_path(adj: dict[str, list[str]], start: str, target: str) -> list[str] | None:
    """BFS path finder returning a witness path from *start* to *target*, or None."""
    if start == target:
        return [start]
    visited: set[str] = {start}
    parent: dict[str, str] = {}
    queue: deque[str] = deque([start])
    while queue:
        current = queue.popleft()
        for neighbor in adj.get(current, []):
            if neighbor in visited:
                continue
            parent[neighbor] = current
            if neighbor == target:
                path = [neighbor]
                while path[-1] != start:
                    path.append(parent[path[-1]])
                path.reverse()
                return path
            visited.add(neighbor)
            queue.append(neighbor)
    return None


def _find_path_to_frontier(adj: dict[str, list[str]], start: str, reachable: set[str], target: str) -> list[str]:
    """Find a witness path showing why *target* is unreachable from *start*.

    Returns a path from *start* to the last reachable node (the frontier),
    with the unreachable *target* appended at the end.
    """
    if start not in reachable:
        return [start, target]
    # BFS from start, find a reachable node with an edge toward unreachable territory
    visited: set[str] = {start}
    parent: dict[str, str] = {}
    queue: deque[str] = deque([start])
    frontier_node: str | None = None
    last_visited: str = start
    while queue:
        current = queue.popleft()
        last_visited = current
        for neighbor in adj.get(current, []):
            if neighbor == target or neighbor not in reachable:
                frontier_node = current
                break
            if neighbor not in visited:
                visited.add(neighbor)
                parent[neighbor] = current
                queue.append(neighbor)
        if frontier_node is not None:
            break

    # Use frontier_node if found, otherwise the last visited node
    end = frontier_node if frontier_node is not None else last_visited
    path = [end]
    while path[-1] != start:
        path.append(parent[path[-1]])
    path.reverse()
    path.append(target)
    return path


def run_structural_checks(
    graph: AgentGraph,
    *,
    require_human: bool,
    suppressions: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Run the standard structural checks described in the paper.

    Checks implemented (exactly five):
      1) Exit reachability
      2) Dead-end detection (excluding EXIT)
      3) Router shape (ROUTER outgoing edges must be CONDITIONAL)
      4) Human-in-the-loop presence (optional, controlled by require_human)
      5) Tool declaration checks (TOOL nodes must declare tools)

    Args:
        suppressions: Optional mapping of check_id to node IDs to ignore.
            For example, ``{"dead_ends": {"intentional_halt"}}`` suppresses
            the dead-end finding for the *intentional_halt* node.

    Returns a JSON-serializable report with witness traces for failures.
    """
    if suppressions is None:
        suppressions = {}

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
    witnesses_exit: dict[str, list[str] | None] = {}
    for eid in missing_exits:
        witnesses_exit[eid] = _find_path_to_frontier(adj, graph.entry_id, reachable, eid)
    checks.append(
        {
            "check_id": "exit_reachability",
            "category": "structural",
            "passed": len(missing_exits) == 0,
            "missing_exits": missing_exits,
            "witnesses": witnesses_exit,
        }
    )

    # 2) Dead-end detection (excluding EXIT)
    suppressed_dead = suppressions.get("dead_ends", set())
    dead_ends = sorted(
        n.id
        for n in graph.nodes
        if n.kind != NodeKind.EXIT
        and len(adj.get(n.id, [])) == 0
        and n.id not in suppressed_dead
    )
    witnesses_dead: dict[str, list[str] | None] = {}
    for de in dead_ends:
        witnesses_dead[de] = _find_path(adj, graph.entry_id, de)
    checks.append(
        {
            "check_id": "dead_ends",
            "category": "structural",
            "passed": len(dead_ends) == 0,
            "dead_ends": dead_ends,
            "witnesses": witnesses_dead,
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
            "category": "structural",
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
            "category": "policy",
            "passed": (not require_human) or len(human_nodes) > 0,
            "required": bool(require_human),
            "human_nodes": human_nodes,
        }
    )

    # 5) Tool declaration checks
    suppressed_tools = suppressions.get("tool_declarations", set())
    tool_nodes = [n for n in graph.nodes if n.kind == NodeKind.TOOL]
    missing_tool_decls = sorted(
        n.id for n in tool_nodes if not n.tools and n.id not in suppressed_tools
    )
    checks.append(
        {
            "check_id": "tool_declarations",
            "category": "structural",
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

