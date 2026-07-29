"""Structural verification checks over AgentGraph topology."""

from __future__ import annotations

from collections import deque
from typing import Any

from agentproof.graph.model import AgentGraph, EdgeKind, GraphEdge, NodeKind, adjacency


def _reverse_adj(graph: AgentGraph) -> dict[str, list[str]]:
    """Build reverse adjacency mapping: target -> list of sources."""
    rev: dict[str, list[str]] = {n.id: [] for n in graph.nodes}
    for e in graph.edges:
        rev.setdefault(e.target, []).append(e.source)
    return rev


def _bfs_tree(
    adj: dict[str, list[str]], start: str
) -> tuple[set[str], dict[str, str], list[str]]:
    """Return the reachable set, BFS parents, and visitation order from *start*.

    One shared tree supports every entry-rooted witness in output-sensitive
    time. Re-running BFS once per finding would make report construction
    quadratic even though each structural predicate is linear.
    """
    visited: set[str] = {start}
    parent: dict[str, str] = {}
    order: list[str] = []
    queue: deque[str] = deque([start])
    while queue:
        current = queue.popleft()
        order.append(current)
        for neighbor in adj.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            parent[neighbor] = current
            queue.append(neighbor)
    return visited, parent, order


def _tree_path(
    parent: dict[str, str], start: str, target: str
) -> list[str] | None:
    """Reconstruct a path in a precomputed BFS tree."""
    if target == start:
        return [start]
    if target not in parent:
        return None
    path = [target]
    while path[-1] != start:
        path.append(parent[path[-1]])
    path.reverse()
    return path


def _unreachable_witness(
    parent: dict[str, str], order: list[str], start: str, target: str
) -> list[str]:
    """Return an explanatory path for an unreachable target.

    There cannot be an actual edge from the reachable set to *target*—otherwise
    it would be reachable. The report therefore shows a path to the final
    visited reachable node and appends the missing target as an explicit gap.
    """
    end = order[-1] if order else start
    path = _tree_path(parent, start, end) or [start]
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
    entry_reachable, entry_parent, entry_order = _bfs_tree(
        adj, graph.entry_id
    )

    checks: list[dict[str, Any]] = []

    # 1) Exit reachability
    missing_exits = sorted(
        eid for eid in graph.exit_ids if eid not in entry_reachable
    )
    witnesses_exit: dict[str, list[str] | None] = {}
    for eid in missing_exits:
        witnesses_exit[eid] = _unreachable_witness(
            entry_parent, entry_order, graph.entry_id, eid
        )
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
        nid for nid in entry_reachable
        if nid not in can_reach_exit
        and nid not in suppressed_reverse
    )
    witnesses_livelock: dict[str, list[str] | None] = {}
    for nid in livelock_nodes:
        witnesses_livelock[nid] = _tree_path(
            entry_parent, graph.entry_id, nid
        )
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
        witnesses_dead[de] = _tree_path(
            entry_parent, graph.entry_id, de
        )
    checks.append(
        {
            "check_id": "dead_ends",
            "category": "structural",
            "passed": len(dead_ends) == 0,
            "dead_ends": dead_ends,
            "witnesses": witnesses_dead,
        }
    )

    # 4) Router shape checks. Group edges by source in one pass so the whole
    # check is O(|V|+|E|) rather than rescanning every edge per router.
    router_ids = sorted(n.id for n in graph.nodes if n.kind == NodeKind.ROUTER)
    router_id_set = set(router_ids)
    outgoing_by_router: dict[str, list[GraphEdge]] = {rid: [] for rid in router_ids}
    for e in graph.edges:
        if e.source in router_id_set:
            outgoing_by_router[e.source].append(e)
    router_violations: list[dict[str, Any]] = []
    for rid in router_ids:
        bad_edges = [
            {"target": e.target, "kind": e.kind.value}
            for e in outgoing_by_router[rid]
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

        # BFS from entry on human-free adjacency. Reuse its parent tree for
        # every ungated-tool witness.
        if graph.entry_id in human_ids:
            reachable_no_human: set[str] = set()
            no_human_parent: dict[str, str] = {}
        else:
            reachable_no_human, no_human_parent, _ = _bfs_tree(
                adj_no_human, graph.entry_id
            )

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
            witnesses_gate[nid] = _tree_path(
                no_human_parent, graph.entry_id, nid
            )
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
