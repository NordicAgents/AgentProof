#!/usr/bin/env python3
"""
Agentproof Example: Full Verification Walkthrough
==================================================

End-to-end example demonstrating agentproof's complete workflow
without any framework dependency. Builds a graph by hand, defines
multiple LTL safety rules, simulates event streams, and shows
how violations are detected and decisions escalated.

This is the reference example for understanding agentproof.

Graph:
    entry → fetch → [route] → (transform | human_review) → store → exit

Rules:
    1. G !tool:rm_rf              — never run destructive shell commands
    2. G !tool:eval               — never execute arbitrary code
    3. action:fetch -> F action:validate  — fetched data must be validated
    4. action:pii_detected -> F action:human_review — PII requires human review

Run:
    python examples/full_verification.py
"""

from __future__ import annotations

from agentproof.graph.model import (
    AgentGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
    adjacency,
    node_by_id,
    predecessors,
    successors,
)
from agentproof.monitor.ltl import (
    MonitorRuleSpec,
    compile_monitor_rule,
    evaluate_monitors,
    MonitorDecision,
)


# ---------------------------------------------------------------------------
# 1. Build graph by hand
# ---------------------------------------------------------------------------

def build_data_pipeline_graph() -> AgentGraph:
    """Construct an AgentGraph manually (no framework needed)."""

    nodes = (
        GraphNode(id="entry", kind=NodeKind.ENTRY, label="start"),
        GraphNode(
            id="fetch", kind=NodeKind.TOOL, label="Data Fetcher",
            tools=("http_get", "s3_download"),
        ),
        GraphNode(id="route", kind=NodeKind.ROUTER, label="Classifier"),
        GraphNode(
            id="transform", kind=NodeKind.LLM, label="LLM Transform",
        ),
        GraphNode(
            id="human_review", kind=NodeKind.HUMAN, label="Human Review",
        ),
        GraphNode(
            id="store", kind=NodeKind.TOOL, label="Data Store",
            tools=("db_insert", "s3_upload"),
        ),
        GraphNode(id="exit", kind=NodeKind.EXIT, label="end"),
    )

    edges = (
        GraphEdge(source="entry", target="fetch"),
        GraphEdge(source="fetch", target="route"),
        GraphEdge(
            source="route", target="transform",
            kind=EdgeKind.CONDITIONAL, condition="no_pii",
        ),
        GraphEdge(
            source="route", target="human_review",
            kind=EdgeKind.CONDITIONAL, condition="contains_pii",
        ),
        GraphEdge(source="transform", target="store"),
        GraphEdge(source="human_review", target="store"),
        GraphEdge(source="store", target="exit"),
    )

    return AgentGraph(
        name="data_pipeline",
        framework="manual",
        nodes=nodes,
        edges=edges,
        entry_id="entry",
        exit_ids=("exit",),
    )


# ---------------------------------------------------------------------------
# 2. Graph inspection
# ---------------------------------------------------------------------------

def inspect(graph: AgentGraph):
    print("=" * 65)
    print(f"  Graph: {graph.name}")
    print("=" * 65)

    print(f"\n  Nodes ({len(graph.nodes)}):")
    for node in graph.nodes:
        tools = f"  tools={list(node.tools)}" if node.tools else ""
        print(f"    [{node.kind.value:>11}] {node.id:<16} {node.label}{tools}")

    print(f"\n  Edges ({len(graph.edges)}):")
    for edge in graph.edges:
        kind = f" ({edge.kind.value})" if edge.kind != EdgeKind.DIRECT else ""
        cond = f" [{edge.condition}]" if edge.condition else ""
        print(f"    {edge.source:<16} -> {edge.target}{kind}{cond}")

    print(f"\n  Entry:  {graph.entry_id}")
    print(f"  Exits:  {list(graph.exit_ids)}")

    print(f"\n  Adjacency list:")
    for nid, targets in adjacency(graph).items():
        if targets:
            print(f"    {nid:<16} -> {targets}")


# ---------------------------------------------------------------------------
# 3. Structural analysis
# ---------------------------------------------------------------------------

def analyze_structure(graph: AgentGraph):
    print("\n" + "-" * 65)
    print("  Structural Analysis")
    print("-" * 65)

    adj = adjacency(graph)
    checks_passed = 0
    checks_total = 0

    # Check 1: all paths from entry reach exit
    checks_total += 1
    reachable = set()
    frontier = [graph.entry_id]
    while frontier:
        n = frontier.pop()
        if n in reachable:
            continue
        reachable.add(n)
        frontier.extend(adj.get(n, []))

    if all(eid in reachable for eid in graph.exit_ids):
        print("  [PASS] Exit reachable from entry")
        checks_passed += 1
    else:
        print("  [FAIL] Exit NOT reachable from entry")

    # Check 2: no dead-end nodes (except exit)
    checks_total += 1
    dead_ends = [
        n.id for n in graph.nodes
        if n.kind != NodeKind.EXIT and not adj.get(n.id)
    ]
    if not dead_ends:
        print("  [PASS] No dead-end nodes")
        checks_passed += 1
    else:
        print(f"  [FAIL] Dead-end nodes: {dead_ends}")

    # Check 3: router has only conditional outgoing edges
    checks_total += 1
    routers = [n for n in graph.nodes if n.kind == NodeKind.ROUTER]
    router_ok = True
    for r in routers:
        out_edges = [e for e in graph.edges if e.source == r.id]
        if not all(e.kind == EdgeKind.CONDITIONAL for e in out_edges):
            print(f"  [FAIL] Router '{r.id}' has non-conditional edges")
            router_ok = False
    if router_ok:
        for r in routers:
            branches = len([e for e in graph.edges if e.source == r.id])
            print(f"  [PASS] Router '{r.id}' has {branches} conditional branch(es)")
        checks_passed += 1

    # Check 4: human-in-the-loop path exists
    checks_total += 1
    human_nodes = [n for n in graph.nodes if n.kind == NodeKind.HUMAN]
    if human_nodes:
        names = [n.id for n in human_nodes]
        print(f"  [PASS] Human-in-the-loop: {names}")
        checks_passed += 1
    else:
        print("  [WARN] No human-in-the-loop nodes")

    # Check 5: tool nodes declare their tools
    checks_total += 1
    tool_nodes = [n for n in graph.nodes if n.kind == NodeKind.TOOL]
    all_declared = all(n.tools for n in tool_nodes)
    if all_declared:
        total_tools = sum(len(n.tools) for n in tool_nodes)
        print(f"  [PASS] {len(tool_nodes)} tool node(s) declare {total_tools} tool(s) total")
        checks_passed += 1
    else:
        missing = [n.id for n in tool_nodes if not n.tools]
        print(f"  [FAIL] Tool nodes without tools: {missing}")

    # Check 6: entry/exit counts
    checks_total += 1
    entries = sum(1 for n in graph.nodes if n.kind == NodeKind.ENTRY)
    exits = sum(1 for n in graph.nodes if n.kind == NodeKind.EXIT)
    if entries == 1 and exits >= 1:
        print(f"  [PASS] Valid entry/exit structure ({entries} entry, {exits} exit)")
        checks_passed += 1
    else:
        print(f"  [FAIL] Invalid: {entries} entries, {exits} exits")

    print(f"\n  Result: {checks_passed}/{checks_total} structural checks passed")
    return checks_passed == checks_total


# ---------------------------------------------------------------------------
# 4. Compile safety rules
# ---------------------------------------------------------------------------

def compile_rules():
    print("\n" + "-" * 65)
    print("  Safety Rule Compilation (LTL -> DFA)")
    print("-" * 65)

    rules = [
        MonitorRuleSpec(
            rule_id="no_rm_rf",
            dsl="G !tool:rm_rf",
            on_violation="halt",
        ),
        MonitorRuleSpec(
            rule_id="no_eval",
            dsl="G !tool:eval",
            on_violation="block",
        ),
        MonitorRuleSpec(
            rule_id="fetch_then_validate",
            dsl="action:fetch -> F action:validate",
            on_violation="block",
        ),
        MonitorRuleSpec(
            rule_id="pii_needs_review",
            dsl="action:pii_detected -> F action:human_review",
            on_violation="escalate",
        ),
    ]

    compiled = []
    for rule in rules:
        c = compile_monitor_rule(rule)
        compiled.append(c)
        print(f"  Compiled: {c.rule_id}")
        print(f"    DSL:        \"{c.dsl}\"")
        print(f"    Predicates: {c.predicates}")
        print(f"    States:     init={c.initial_state}, violations={set(c.violation_states)}")
        print(f"    On violate: {c.on_violation}")

    return tuple(compiled)


# ---------------------------------------------------------------------------
# 5. Simulate event traces
# ---------------------------------------------------------------------------

def simulate_traces(compiled):
    print("\n" + "-" * 65)
    print("  Event Trace Simulation")
    print("-" * 65)

    traces = {
        "normal_flow": {
            "description": "Fetch, validate, transform, store (clean data)",
            "events": [
                {"tool_name": "http_get", "action_type": "fetch", "tags": []},
                {"action_type": "validate", "tags": ["check"]},
                {"action_type": "transform", "tags": ["llm"]},
                {"tool_name": "db_insert", "action_type": "store", "tags": []},
            ],
        },
        "pii_with_review": {
            "description": "PII detected, human reviews, then stored",
            "events": [
                {"tool_name": "http_get", "action_type": "fetch", "tags": []},
                {"action_type": "validate", "tags": ["check"]},
                {"action_type": "pii_detected", "tags": ["sensitive"]},
                {"action_type": "human_review", "tags": ["approval"]},
                {"tool_name": "db_insert", "action_type": "store", "tags": []},
            ],
        },
        "pii_without_review": {
            "description": "PII detected but no human review before next PII event",
            "events": [
                {"tool_name": "http_get", "action_type": "fetch", "tags": []},
                {"action_type": "validate", "tags": ["check"]},
                {"action_type": "pii_detected", "tags": ["sensitive"]},
                {"action_type": "transform", "tags": ["llm"]},
                # Another PII detection without review triggers escalation
                {"action_type": "pii_detected", "tags": ["sensitive"]},
            ],
        },
        "fetch_without_validate": {
            "description": "Data fetched but never validated before next fetch",
            "events": [
                {"tool_name": "http_get", "action_type": "fetch", "tags": []},
                {"action_type": "transform", "tags": ["llm"]},
                {"tool_name": "db_insert", "action_type": "store", "tags": []},
                # Fetch again without validation
                {"action_type": "fetch", "tags": []},
            ],
        },
        "destructive_command": {
            "description": "Attacker tries to execute rm -rf via tool",
            "events": [
                {"tool_name": "http_get", "action_type": "fetch", "tags": []},
                {"tool_name": "rm_rf", "tags": ["destructive"]},
            ],
        },
        "code_injection": {
            "description": "Attempt to call eval() tool",
            "events": [
                {"action_type": "fetch", "tags": []},
                {"tool_name": "eval", "tags": ["injection"]},
            ],
        },
    }

    results: dict[str, str] = {}
    for trace_name, trace_data in traces.items():
        print(f"\n  Trace: {trace_name}")
        print(f"    {trace_data['description']}")

        state: dict[str, int] = {}
        all_violations: list[str] = []
        final_decision: MonitorDecision | None = None

        for i, event in enumerate(trace_data["events"]):
            state, snapshots, decision = evaluate_monitors(compiled, state, event)
            final_decision = decision

            event_desc = event.get("tool_name") or event.get("action_type") or str(event)
            violations_here = [s for s in snapshots if s.violation]

            if violations_here:
                for s in violations_here:
                    all_violations.append(s.rule_id)
                    print(f"    Step {i}: {event_desc} -> VIOLATION ({s.rule_id}, {s.handling})")
            else:
                print(f"    Step {i}: {event_desc} -> ok")

        assert final_decision is not None

        if final_decision.escalate:
            status = "ESCALATE"
        elif final_decision.halt:
            status = "HALT"
        elif final_decision.denied:
            status = "BLOCKED"
        else:
            status = "PASS"

        results[trace_name] = status
        marker = ">>>" if status != "PASS" else "   "
        print(f"  {marker} Decision: [{status}] denied={final_decision.denied} halt={final_decision.halt} escalate={final_decision.escalate}")

    return results


# ---------------------------------------------------------------------------
# 6. Summary report
# ---------------------------------------------------------------------------

def print_summary(structure_ok: bool, trace_results: dict[str, str]):
    print("\n" + "=" * 65)
    print("  Verification Summary")
    print("=" * 65)

    print(f"\n  Structural analysis: {'PASS' if structure_ok else 'FAIL'}")

    print(f"\n  Trace results:")
    for name, status in trace_results.items():
        icon = "ok" if status == "PASS" else status
        print(f"    {name:<30} [{icon}]")

    safe = sum(1 for s in trace_results.values() if s == "PASS")
    total = len(trace_results)
    blocked = total - safe

    print(f"\n  {safe}/{total} traces passed, {blocked} blocked/halted/escalated")

    if structure_ok and blocked > 0:
        print("\n  Conclusion: Graph structure is valid. Temporal monitors")
        print("  correctly detected unsafe event sequences. Ready to deploy")
        print("  with monitors active.")
    elif structure_ok:
        print("\n  Conclusion: All checks passed. Safe to deploy.")
    else:
        print("\n  Conclusion: Structural issues found. Fix before deploying.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Build
    graph = build_data_pipeline_graph()

    # Inspect
    inspect(graph)

    # Structural analysis
    structure_ok = analyze_structure(graph)

    # Compile temporal rules
    compiled = compile_rules()

    # Simulate
    results = simulate_traces(compiled)

    # Summary
    print_summary(structure_ok, results)


if __name__ == "__main__":
    main()
