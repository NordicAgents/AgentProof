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

    For single-tool (or non-TOOL) nodes this returns one event; multi-tool
    nodes are handled by :func:`_node_dfa_symbols`, which clones the mapped
    event once per tool so each event carries exactly one live tool name.
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


def _node_dfa_symbols(
    node_id: str,
    graph: AgentGraph,
    predicates: tuple[str, ...],
    event_mapper: Callable[[str, AgentGraph], dict[str, Any]],
) -> frozenset[int]:
    """Return the set of possible DFA input symbols for a graph node.

    For a multi-tool TOOL node, one symbol is produced per declared tool,
    modelling the non-deterministic "may call one of these" semantics.
    Branching here keeps both safety and liveness forms sound:
    - ``G !tool:rm_rf`` catches the tool on any branch.
    - ``tool:write -> F tool:audit_log`` stays pending on the write-only
      branch, so the obligation is not self-discharged on a node that
      happens to also declare ``audit_log``.
    For single-tool and non-TOOL nodes, exactly one symbol is returned.
    """
    base_event = event_mapper(node_id, graph)
    node = node_by_id(graph, node_id)
    if node is not None and node.kind == NodeKind.TOOL and len(node.tools) > 1:
        symbols: set[int] = set()
        for tool in node.tools:
            event = dict(base_event)
            event["tool_name"] = tool
            symbols.add(_event_symbol(predicates, event))
        return frozenset(symbols)
    return frozenset({_event_symbol(predicates, base_event)})


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
    # Post-transition product graph edges for the lasso (cycle) check.
    product_succ: dict[tuple[str, int], list[tuple[str, int]]] = {}
    # All possible post-transition DFA states per product state.  For multi-tool
    # nodes this is a set (one element per tool choice); single-tool nodes yield
    # a singleton.  The lasso check flags a state as pending if ANY branch is
    # non-accepting, preserving the existential "there exists a violating run"
    # semantics used throughout.
    post_states: dict[tuple[str, int], frozenset[int]] = {}

    violation_product_state: tuple[str, int] | None = None
    violation_kind: str | None = None

    while queue:
        v, q = queue.popleft()

        transition_row = rule.transition_table.get(q)
        if transition_row is None:
            # Malformed rule — skip this state
            continue

        # One DFA symbol per possible tool choice (single symbol for non-TOOL /
        # single-tool nodes).  Branching here is what keeps liveness forms
        # sound: each branch carries exactly one live tool name, so an
        # antecedent cannot simultaneously discharge its own consequent.
        symbols = _node_dfa_symbols(v, graph, rule.predicates, event_mapper)
        q_primes = frozenset(transition_row[s] for s in symbols)
        post_states[(v, q)] = q_primes

        # Safety check: any tool choice drives DFA into a violation state.
        if q_primes & rule.violation_states:
            violation_product_state = (v, q)
            violation_kind = "bad_prefix"
            break

        # LTLf termination check: any tool choice leaves an obligation pending
        # at an exit node — obligation can never be fulfilled on that branch.
        if v in exit_ids and not q_primes <= rule.accepting_states:
            violation_product_state = (v, q)
            violation_kind = "unfulfilled_obligation"
            break

        # Enqueue successors: cross product of graph successors × DFA next-states.
        succs = []
        for u in adj.get(v, []):
            for q_prime in q_primes:
                product_next = (u, q_prime)
                succs.append(product_next)
                if product_next not in visited:
                    visited.add(product_next)
                    parent[product_next] = (v, q)
                    queue.append(product_next)
        product_succ[(v, q)] = succs

    # Lasso check for infinite executions: a cycle in the reachable product
    # restricted to states whose post-transition DFA state is non-accepting
    # witnesses an infinite run on which the obligation is never fulfilled.
    if violation_product_state is None and post_states:
        pending = {s for s, qps in post_states.items()
                   if any(qp not in rule.accepting_states for qp in qps)}
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
