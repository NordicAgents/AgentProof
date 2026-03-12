"""Structural verification checks over AgentGraph topology."""

from __future__ import annotations

from collections import deque
from typing import Any

from agentproof.graph.model import AgentGraph, EdgeKind, NodeKind, adjacency


def _reverse_adj(graph: AgentGraph) -> dict[str, list[str]]:
    """Build reverse adjacency mapping: target -> list of sources."""
    rev: dict[str, list[str]] = {n.id: [] for n in graph.nodes}
    for e in graph.edges:
        rev.setdefault(e.target, []).append(e.source)
    return rev


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
    sensitive_tools: set[str] | None = None,
) -> dict[str, Any]:
    """Run the standard structural checks described in the paper.

    Checks implemented (six core, plus optional policy checks):
      1) Exit reachability
      2) Reverse reachability / livelock detection
      3) Dead-end detection (excluding EXIT)
      4) Router shape (ROUTER outgoing edges must be CONDITIONAL)
      5) Human-in-the-loop presence (optional, controlled by require_human)
      5b) Human gate coverage (optional, controlled by sensitive_tools)
      6) Tool declaration checks (TOOL nodes must declare tools)

    Args:
        suppressions: Optional mapping of check_id to node IDs to ignore.
            For example, ``{"dead_ends": {"intentional_halt"}}`` suppresses
            the dead-end finding for the *intentional_halt* node.
        sensitive_tools: Optional set of tool names that require a HUMAN gate.
            When provided, adds a ``human_gate_coverage`` check verifying
            that every sensitive tool node is dominated by a HUMAN node.

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

    # 2) Reverse reachability / livelock detection
    rev = _reverse_adj(graph)
    can_reach_exit: set[str] = set()
    rev_frontier: list[str] = list(graph.exit_ids)
    while rev_frontier:
        node_id = rev_frontier.pop()
        if node_id in can_reach_exit:
            continue
        can_reach_exit.add(node_id)
        rev_frontier.extend(rev.get(node_id, []))

    suppressed_reverse = suppressions.get("reverse_reachability", set())
    livelock_nodes = sorted(
        nid for nid in reachable
        if nid not in can_reach_exit
        and nid not in suppressed_reverse
    )
    witnesses_livelock: dict[str, list[str] | None] = {}
    for nid in livelock_nodes:
        witnesses_livelock[nid] = _find_path(adj, graph.entry_id, nid)
    checks.append(
        {
            "check_id": "reverse_reachability",
            "category": "structural",
            "passed": len(livelock_nodes) == 0,
            "livelock_nodes": livelock_nodes,
            "witnesses": witnesses_livelock,
        }
    )

    # 3) Dead-end detection (excluding EXIT)  [was check 2]
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

    # 4) Router shape checks
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

    # 5) Human-in-the-loop presence
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

    # 5b) Human gate coverage (optional)
    if sensitive_tools is not None:
        # Build adjacency excluding HUMAN nodes
        human_ids = {n.id for n in graph.nodes if n.kind == NodeKind.HUMAN}
        adj_no_human: dict[str, list[str]] = {
            n.id: [] for n in graph.nodes if n.id not in human_ids
        }
        for e in graph.edges:
            if e.source not in human_ids and e.target not in human_ids:
                adj_no_human.setdefault(e.source, []).append(e.target)

        # BFS from entry on human-free adjacency
        reachable_no_human: set[str] = set()
        nh_frontier: list[str] = [graph.entry_id] if graph.entry_id not in human_ids else []
        while nh_frontier:
            nid = nh_frontier.pop()
            if nid in reachable_no_human:
                continue
            reachable_no_human.add(nid)
            nh_frontier.extend(adj_no_human.get(nid, []))

        # Find sensitive tool nodes reachable without passing through HUMAN
        node_map = {n.id: n for n in graph.nodes}
        ungated_tools = sorted(
            nid for nid in reachable_no_human
            if nid in node_map
            and node_map[nid].kind == NodeKind.TOOL
            and any(t in sensitive_tools for t in node_map[nid].tools)
        )
        witnesses_gate: dict[str, list[str] | None] = {}
        for nid in ungated_tools:
            witnesses_gate[nid] = _find_path(adj_no_human, graph.entry_id, nid)
        checks.append(
            {
                "check_id": "human_gate_coverage",
                "category": "policy",
                "passed": len(ungated_tools) == 0,
                "ungated_tools": ungated_tools,
                "witnesses": witnesses_gate,
            }
        )

    # 6) Tool declaration checks
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

