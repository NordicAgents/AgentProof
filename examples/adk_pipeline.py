#!/usr/bin/env python3
"""
Agentproof Example: Google ADK Hierarchical Pipeline
=====================================================

Demonstrates extracting a **real** Google ADK agent tree with Sequential,
Parallel, and Loop compositions, then verifying structural and
temporal properties.

Agent tree:
    pipeline (SequentialAgent)
    +-- ingest (LlmAgent with tools)
    +-- process (ParallelAgent)
    |   +-- analyze_text (LlmAgent)
    |   +-- analyze_images (LlmAgent with tool)
    +-- validate (LoopAgent)
    |   +-- check_quality (LlmAgent)
    |   +-- fix_issues (LlmAgent with tool)
    +-- publish (LlmAgent)

No API keys required — agents are constructed but never executed.

Safety rules:
    1. Never call "drop_database" tool  (G !tool:drop_database)
    2. If data is ingested, validation must eventually happen
       (action:ingest -> F action:validate)

Requirements:
    pip install -e ".[adk]"

Run:
    python examples/adk_pipeline.py
"""

from __future__ import annotations

try:
    from google.adk.agents import LlmAgent, SequentialAgent, ParallelAgent, LoopAgent
except ImportError:
    raise SystemExit(
        "Google ADK is not installed.\n"
        "Install with:  pip install -e '.[adk]'"
    )

from agentproof.graph import (
    AgentGraph,
    NodeKind,
    EdgeKind,
    extract_adk,
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
# 1. Build the pipeline with real ADK agents
# ---------------------------------------------------------------------------

def fetch_url() -> str:
    """Fetch content from a URL."""
    return ""


def parse_document() -> str:
    """Parse a document into structured data."""
    return ""


def vision_api() -> str:
    """Analyze images using vision API."""
    return ""


def auto_fix() -> str:
    """Automatically fix detected issues."""
    return ""


def build_pipeline():
    """Build a multi-stage ADK pipeline with varied compositions."""
    ingest = LlmAgent(
        name="ingest",
        model="gemini-2.0-flash",
        tools=[fetch_url, parse_document],
    )

    analyze_text = LlmAgent(name="analyze_text", model="gemini-2.0-flash")
    analyze_images = LlmAgent(
        name="analyze_images",
        model="gemini-2.0-flash",
        tools=[vision_api],
    )
    process = ParallelAgent(name="process", sub_agents=[analyze_text, analyze_images])

    check_quality = LlmAgent(name="check_quality", model="gemini-2.0-flash")
    fix_issues = LlmAgent(
        name="fix_issues",
        model="gemini-2.0-flash",
        tools=[auto_fix],
    )
    validate = LoopAgent(name="validate", sub_agents=[check_quality, fix_issues])

    publish = LlmAgent(name="publish", model="gemini-2.0-flash")

    pipeline = SequentialAgent(
        name="pipeline",
        sub_agents=[ingest, process, validate, publish],
    )
    return pipeline


# ---------------------------------------------------------------------------
# 2. Inspect
# ---------------------------------------------------------------------------

def inspect_graph(graph: AgentGraph):
    print(f"\nGraph: {graph.name}  (framework: {graph.framework})")
    print("-" * 55)

    print(f"  Nodes ({len(graph.nodes)}):")
    for node in graph.nodes:
        tools_str = f"  tools={list(node.tools)}" if node.tools else ""
        print(f"    {node.id:<20} kind={node.kind.value:<12}{tools_str}")

    print(f"\n  Edges ({len(graph.edges)}):")
    for edge in graph.edges:
        kind_str = f"  ({edge.kind.value})" if edge.kind != EdgeKind.DIRECT else ""
        print(f"    {edge.source} -> {edge.target}{kind_str}")


# ---------------------------------------------------------------------------
# 3. Structural checks
# ---------------------------------------------------------------------------

def verify_structure(graph: AgentGraph):
    print(f"\nStructural checks:")
    print("-" * 55)

    adj = adjacency(graph)

    # Check: parallel branches exist
    par_edges = [e for e in graph.edges if e.kind == EdgeKind.PARALLEL]
    if par_edges:
        sources = {e.source for e in par_edges}
        for src in sources:
            targets = [e.target for e in par_edges if e.source == src]
            print(f"  [PASS] Parallel fork at '{src}' -> {targets}")
    else:
        print(f"  [INFO] No parallel branches")

    # Check: loop back-edges exist
    loop_edges = [e for e in graph.edges if e.kind == EdgeKind.LOOP]
    if loop_edges:
        for edge in loop_edges:
            print(f"  [PASS] Loop back-edge: {edge.source} -> {edge.target}")
    else:
        print(f"  [INFO] No loop structures")

    # Check: subgraph nodes correctly contain children
    subgraphs = [n for n in graph.nodes if n.kind == NodeKind.SUBGRAPH]
    for sg in subgraphs:
        children = successors(graph, sg.id)
        print(f"  [PASS] Subgraph '{sg.id}' has {len(children)} child connection(s)")

    # Check: all tool nodes have tools
    tool_nodes = [n for n in graph.nodes if n.kind == NodeKind.TOOL]
    for tn in tool_nodes:
        assert tn.tools, f"TOOL node {tn.id} missing tools"
    print(f"  [PASS] All {len(tool_nodes)} tool nodes have declared tools")

    # Check: reachability from entry
    reachable = set()
    frontier = [graph.entry_id]
    while frontier:
        current = frontier.pop()
        if current in reachable:
            continue
        reachable.add(current)
        frontier.extend(adj.get(current, []))
    all_ids = {n.id for n in graph.nodes}
    unreachable = all_ids - reachable
    if unreachable:
        print(f"  [WARN] Unreachable nodes: {unreachable}")
    else:
        print(f"  [PASS] All {len(all_ids)} nodes reachable from entry")

    # Check: at least one path reaches exit
    if "__exit__" in reachable:
        print(f"  [PASS] Exit node is reachable")
    else:
        print(f"  [FAIL] Exit node is NOT reachable")


# ---------------------------------------------------------------------------
# 4. Temporal verification
# ---------------------------------------------------------------------------

def verify_temporal(graph: AgentGraph):
    print(f"\nTemporal verification:")
    print("-" * 55)

    rules = [
        MonitorRuleSpec(
            rule_id="no_drop_db",
            dsl="G !tool:drop_database",
            on_violation="halt",
        ),
        MonitorRuleSpec(
            rule_id="ingest_then_validate",
            dsl="action:ingest -> F action:validate",
            on_violation="block",
        ),
    ]

    compiled = tuple(compile_monitor_rule(r) for r in rules)

    traces = {
        "happy_path": [
            {"tool_name": "fetch_url", "action_type": "ingest", "tags": []},
            {"tool_name": "parse_document", "tags": ["read"]},
            {"tool_name": "vision_api", "tags": ["analyze"]},
            {"action_type": "validate", "tags": ["check"]},
            {"action_type": "publish", "tags": ["output"]},
        ],
        "ingest_skip_validate": [
            {"tool_name": "fetch_url", "action_type": "ingest", "tags": []},
            {"tags": ["analyze"]},
            {"action_type": "publish", "tags": ["output"]},
            {"action_type": "ingest", "tags": []},
        ],
        "database_attack": [
            {"tool_name": "fetch_url", "tags": []},
            {"tool_name": "drop_database", "tags": ["destructive"]},
        ],
    }

    for trace_name, events in traces.items():
        state: dict[str, int] = {}
        violations: list[str] = []

        for event in events:
            state, snapshots, decision = evaluate_monitors(compiled, state, event)
            for snap in snapshots:
                if snap.violation:
                    violations.append(snap.rule_id)

        if decision.halt:
            status = "HALT"
        elif decision.denied:
            status = "BLOCKED"
        else:
            status = "PASS"

        print(f"  Trace '{trace_name}': [{status}]", end="")
        if violations:
            print(f"  (violated: {', '.join(violations)})")
        else:
            print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Agentproof: Google ADK Pipeline Verification")
    print("=" * 60)

    pipeline = build_pipeline()
    graph = extract_adk(pipeline)

    inspect_graph(graph)
    verify_structure(graph)
    verify_temporal(graph)

    print("\n" + "=" * 60)
    print("All checks complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
