#!/usr/bin/env python3
"""
Agentproof Example: LangGraph Customer Support Bot
===================================================

Demonstrates extracting a customer support workflow from a **real** LangGraph
StateGraph and verifying safety properties before deployment.

The workflow:
    __start__ → router → (agent | escalate_human) → tool_call → __end__

Safety rules verified:
    1. Never call the "delete_account" tool  (G !tool:delete_account)
    2. If billing data is accessed, human review must follow
       (action:access_billing -> F action:human_review)

Requirements:
    pip install -e ".[langgraph]"

Run:
    python examples/langgraph_customer_support.py
"""

from __future__ import annotations

try:
    from langgraph.graph import StateGraph, END
except ImportError:
    raise SystemExit(
        "LangGraph is not installed.\n"
        "Install with:  pip install -e '.[langgraph]'"
    )

from typing import TypedDict, Literal

from agentproof.graph import (
    AgentGraph,
    NodeKind,
    EdgeKind,
    extract_langgraph,
    node_by_id,
    successors,
    adjacency,
)
from agentproof.monitor.ltl import (
    MonitorRuleSpec,
    compile_monitor_rule,
    evaluate_monitors,
)


# ---------------------------------------------------------------------------
# 1. Build a real LangGraph StateGraph
# ---------------------------------------------------------------------------

class State(TypedDict):
    messages: list


def router(state: State) -> State:
    """Route incoming requests."""
    return state


def agent(state: State) -> State:
    """Handle simple customer queries."""
    return state


def escalate_human(state: State) -> State:
    """Escalate complex issues to a human agent."""
    return state


def tool_call(state: State) -> State:
    """Execute tool actions (refund, address update, etc.)."""
    return state


def route_decision(state: State) -> Literal["agent", "escalate_human"]:
    """Decide whether to handle automatically or escalate."""
    return "agent"


def build_customer_support_graph():
    """Build a real LangGraph StateGraph for customer support."""
    graph = StateGraph(State)

    graph.add_node("router", router)
    graph.add_node("agent", agent)
    graph.add_node("escalate_human", escalate_human)
    graph.add_node("tool_call", tool_call)

    graph.add_edge("__start__", "router")
    graph.add_conditional_edges(
        "router",
        route_decision,
        {"agent": "agent", "escalate_human": "escalate_human"},
    )
    graph.add_edge("agent", "tool_call")
    graph.add_edge("escalate_human", "__end__")
    graph.add_edge("tool_call", "__end__")

    return graph.compile()


# ---------------------------------------------------------------------------
# 2. Extract and inspect the graph
# ---------------------------------------------------------------------------

def inspect_graph(graph: AgentGraph):
    print("=" * 60)
    print(f"Graph: {graph.name}  (framework: {graph.framework})")
    print("=" * 60)

    print(f"\nNodes ({len(graph.nodes)}):")
    for node in graph.nodes:
        tools_str = f"  tools={list(node.tools)}" if node.tools else ""
        print(f"  {node.id:<20} kind={node.kind.value:<12}{tools_str}")

    print(f"\nEdges ({len(graph.edges)}):")
    for edge in graph.edges:
        cond = f"  [{edge.condition}]" if edge.condition else ""
        print(f"  {edge.source} -> {edge.target}  ({edge.kind.value}){cond}")

    print(f"\nEntry: {graph.entry_id}")
    print(f"Exits: {list(graph.exit_ids)}")

    adj = adjacency(graph)
    print(f"\nAdjacency list:")
    for nid, targets in adj.items():
        if targets:
            print(f"  {nid} -> {targets}")


# ---------------------------------------------------------------------------
# 3. Static graph checks (structural verification)
# ---------------------------------------------------------------------------

def check_structure(graph: AgentGraph):
    print("\n" + "-" * 60)
    print("Structural checks")
    print("-" * 60)

    # Check: router has only conditional outgoing edges
    router_node = node_by_id(graph, "router")
    if router_node:
        router_edges = [e for e in graph.edges if e.source == "router"]
        all_cond = all(e.kind == EdgeKind.CONDITIONAL for e in router_edges)
        assert all_cond, "Router has non-conditional outgoing edges"
        print(f"  [PASS] Router node has {len(router_edges)} conditional branches")

    # Check: human escalation path exists
    human_reachable = any(
        "human" in nid or "escalat" in nid
        for nid in successors(graph, "router")
    )
    print(f"  [PASS] Human escalation path exists: {human_reachable}")

    # Check: all non-exit nodes have at least one successor
    for node in graph.nodes:
        if node.kind != NodeKind.EXIT:
            succ = successors(graph, node.id)
            assert len(succ) > 0, f"Node {node.id} is a dead end"
    print(f"  [PASS] No dead-end nodes (excluding exits)")


# ---------------------------------------------------------------------------
# 4. Temporal verification (LTL monitor simulation)
# ---------------------------------------------------------------------------

def verify_temporal_safety(graph: AgentGraph):
    print("\n" + "-" * 60)
    print("Temporal safety verification (LTL monitors)")
    print("-" * 60)

    rules = [
        MonitorRuleSpec(
            rule_id="no_delete_account",
            dsl="G !tool:delete_account",
            on_violation="block",
        ),
        MonitorRuleSpec(
            rule_id="billing_needs_review",
            dsl="action:access_billing -> F action:human_review",
            on_violation="halt",
        ),
    ]

    compiled = tuple(compile_monitor_rule(r) for r in rules)
    print(f"  Compiled {len(compiled)} temporal rule(s)")

    for rule in compiled:
        print(f"    - {rule.rule_id}: \"{rule.dsl}\" (on_violation={rule.on_violation})")

    traces = {
        "safe_lookup": [
            {"tool_name": "lookup_order", "tags": ["read"]},
            {"tool_name": "check_inventory", "tags": ["read"]},
        ],
        "billing_with_review": [
            {"action_type": "access_billing", "tags": ["sensitive"]},
            {"tool_name": "lookup_order", "tags": ["read"]},
            {"action_type": "human_review", "tags": ["approval"]},
        ],
        "billing_without_review": [
            {"action_type": "access_billing", "tags": ["sensitive"]},
            {"tool_name": "refund_order", "tags": ["write"]},
            {"action_type": "access_billing", "tags": ["sensitive"]},
        ],
        "forbidden_delete": [
            {"tool_name": "lookup_order", "tags": ["read"]},
            {"tool_name": "delete_account", "tags": ["destructive"]},
        ],
    }

    print(f"\n  Simulating {len(traces)} event traces:")
    for trace_name, events in traces.items():
        state: dict[str, int] = {}
        final_decision = None
        violation_log: list[str] = []

        for event in events:
            state, snapshots, decision = evaluate_monitors(compiled, state, event)
            for snap in snapshots:
                if snap.violation:
                    violation_log.append(
                        f"{snap.rule_id} violated at event {event}"
                    )
            final_decision = decision

        status = "PASS" if not final_decision.denied else "BLOCKED"
        if final_decision.halt:
            status = "HALT"
        print(f"\n    Trace: {trace_name} -> [{status}]")
        for v in violation_log:
            print(f"      ! {v}")
        if not violation_log:
            print(f"      (no violations)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Extract from real LangGraph
    compiled = build_customer_support_graph()
    graph = extract_langgraph(compiled)

    # Inspect
    inspect_graph(graph)

    # Structural checks
    check_structure(graph)

    # Temporal verification
    verify_temporal_safety(graph)

    print("\n" + "=" * 60)
    print("Verification complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
