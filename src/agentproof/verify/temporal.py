"""Static temporal verification via graph x DFA product construction.

Given an :class:`AgentGraph` and a :class:`CompiledMonitorRule`, this module
performs a BFS over the product of the graph's node space and the DFA state
space to detect temporal property violations *statically* — without requiring
a runtime event trace.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Callable

from agentproof.graph.model import AgentGraph, NodeKind, adjacency, node_by_id
from agentproof.monitor.ltl import CompiledMonitorRule, _event_symbol


def _default_event_mapper(node_id: str, graph: AgentGraph) -> dict[str, Any]:
    """Generate a synthetic event dict for a graph node.

    Mirrors the ``_event_for_node`` logic in :mod:`agentproof.api`.
    """
    node = node_by_id(graph, node_id)
    if node is None:
        return {"node_id": node_id, "action_type": "unknown"}
    event: dict[str, Any] = {"node_id": node.id, "action_type": node.kind.value}
    if node.kind == NodeKind.TOOL and node.tools:
        event["tool_name"] = node.tools[0]
        event["tags"] = ["tool"]
    elif node.kind == NodeKind.LLM:
        event["tags"] = ["llm_step"]
    elif node.kind == NodeKind.HUMAN:
        event["tags"] = ["human"]
    elif node.kind == NodeKind.ROUTER:
        event["tags"] = ["router"]
    return event


def check_temporal_property(
    graph: AgentGraph,
    rule: CompiledMonitorRule,
    event_mapper: Callable[[str, AgentGraph], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check a temporal property against a graph using product construction.

    Parameters
    ----------
    graph : AgentGraph
        The agent workflow graph to verify.
    rule : CompiledMonitorRule
        A compiled temporal monitor rule (from :mod:`agentproof.monitor.ltl`).
    event_mapper : callable, optional
        A function ``(node_id, graph) -> event_dict`` used to compute the
        DFA input symbol for each graph node.  Defaults to
        :func:`_default_event_mapper`.

    Returns
    -------
    dict
        A JSON-serializable result containing:
        - ``rule_id``: the rule identifier
        - ``violated``: whether a violation was found
        - ``violation_kind``: ``"bad_prefix"`` (a reachable path drives the
          DFA into a violation state) or ``"unfulfilled_obligation"`` (a
          path can terminate at an exit node while the DFA is in a
          non-accepting state — an LTLf violation at trace end), or ``None``
        - ``violation_path``: list of node IDs leading to the violation,
          or ``None`` if no violation was found
        - ``product_states_explored``: number of ``(node, dfa_state)``
          pairs explored during BFS

    Executions are modeled as *maximal* paths: finite ones ending at exit
    nodes (evaluated under LTLf) and infinite ones that never leave the
    graph (evaluated under standard LTL). Three violation mechanisms are
    covered: a reachable bad prefix, a complete trace ending in a
    non-accepting DFA state, and a reachable product cycle that stays
    non-accepting forever (an eventuality that can be postponed
    indefinitely). "Not violated" therefore means no maximal path in the
    graph can violate the property.
    """
    if event_mapper is None:
        event_mapper = _default_event_mapper

    adj = adjacency(graph)
    exit_ids = set(graph.exit_ids)

    # BFS over product states (node_id, dfa_state)
    initial_product = (graph.entry_id, rule.initial_state)
    queue: deque[tuple[str, int]] = deque()
    queue.append(initial_product)

    visited: set[tuple[str, int]] = {initial_product}
    parent: dict[tuple[str, int], tuple[str, int] | None] = {initial_product: None}
    # Post-transition product graph edges, for the lasso (cycle) check:
    # (v, q') -> (u, q') successors recorded as (v,q) pairs keyed by the
    # pre-transition states so witness paths reconstruct via `parent`.
    product_succ: dict[tuple[str, int], list[tuple[str, int]]] = {}
    # DFA state *after* processing node v, per visited product state.
    post_state: dict[tuple[str, int], int] = {}

    violation_product_state: tuple[str, int] | None = None
    violation_kind: str | None = None

    while queue:
        v, q = queue.popleft()

        # Compute the DFA symbol for the current node
        event = event_mapper(v, graph)
        symbol = _event_symbol(rule.predicates, event)

        # Transition in the DFA
        transition_row = rule.transition_table.get(q)
        if transition_row is None:
            # Malformed rule — skip this state
            continue
        q_prime = transition_row[symbol]
        post_state[(v, q)] = q_prime

        # Check for violation
        if q_prime in rule.violation_states:
            # Record the violation: the path ends at v (the node that caused it)
            # We need to reconstruct the path to v, then note that q_prime is
            # the violation state reached *after processing* v.
            violation_product_state = (v, q)
            violation_kind = "bad_prefix"
            break

        # LTLf termination check: a complete execution ends here, so a
        # non-accepting DFA state at an exit node is a violation.
        if v in exit_ids and q_prime not in rule.accepting_states:
            violation_product_state = (v, q)
            violation_kind = "unfulfilled_obligation"
            break

        # Enqueue successors
        succs = []
        for u in adj.get(v, []):
            product_next = (u, q_prime)
            succs.append(product_next)
            if product_next not in visited:
                visited.add(product_next)
                parent[product_next] = (v, q)
                queue.append(product_next)
        product_succ[(v, q)] = succs

    # Lasso check for infinite executions: a cycle in the reachable product
    # restricted to states whose post-transition DFA state is non-accepting
    # witnesses an infinite run on which the obligation is never fulfilled
    # (an LTL violation, e.g. G(a -> F b) on an infinite loop without b).
    if violation_product_state is None and post_state:
        pending = {s for s, qp in post_state.items()
                   if qp not in rule.accepting_states}
        if pending:
            # Iteratively strip states with no pending successor; anything
            # left lies on or leads to a pending-only cycle.
            core = set(pending)
            changed = True
            while changed:
                changed = False
                for s in list(core):
                    if not any(t in core for t in product_succ.get(s, [])):
                        core.discard(s)
                        changed = True
            if core:
                violation_product_state = min(core)  # deterministic witness
                violation_kind = "divergent_obligation"

    explored = len(visited)

    if violation_product_state is None:
        return {
            "rule_id": rule.rule_id,
            "violated": False,
            "violation_kind": None,
            "violation_path": None,
            "product_states_explored": explored,
        }

    # Reconstruct violation path (sequence of node IDs)
    path_nodes: list[str] = []
    current: tuple[str, int] | None = violation_product_state
    while current is not None:
        path_nodes.append(current[0])
        current = parent.get(current)
    path_nodes.reverse()

    return {
        "rule_id": rule.rule_id,
        "violated": True,
        "violation_kind": violation_kind,
        "violation_path": path_nodes,
        "product_states_explored": explored,
    }
