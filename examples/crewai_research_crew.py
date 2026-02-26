#!/usr/bin/env python3
"""
Agentproof Example: CrewAI Research Crew
========================================

Demonstrates extracting a **real** CrewAI research pipeline and verifying
task ordering, tool access policies, and data flow constraints.

The crew (sequential process):
    gather_data -> analyze_data -> write_report -> peer_review

No API keys required — a fake key is set to satisfy CrewAI's validation.

Safety rules:
    1. Never use "execute_code" tool  (G !tool:execute_code)
    2. If raw data is fetched, analysis must follow
       (action:fetch_raw -> F action:analyze)

Requirements:
    pip install -e ".[crewai]"

Run:
    python examples/crewai_research_crew.py
"""

from __future__ import annotations

import os

# CrewAI validates OPENAI_API_KEY at import time; set a dummy value
# so the library loads without error. No LLM calls are made.
os.environ.setdefault("OPENAI_API_KEY", "sk-fake-key-for-construction-only")

try:
    from crewai import Agent, Task, Crew, Process
except ImportError:
    raise SystemExit(
        "CrewAI is not installed.\n"
        "Install with:  pip install -e '.[crewai]'"
    )

from agentproof.graph import (
    AgentGraph,
    NodeKind,
    extract_crewai,
    node_by_id,
    successors,
    predecessors,
    adjacency,
)
from agentproof.monitor.ltl import (
    MonitorRuleSpec,
    compile_monitor_rule,
    evaluate_monitors,
)


# ---------------------------------------------------------------------------
# 1. Build a real CrewAI Crew
# ---------------------------------------------------------------------------

def build_research_crew():
    """Build a sequential research crew with real CrewAI objects."""
    researcher = Agent(
        role="researcher",
        goal="Find relevant papers and datasets",
        backstory="Expert data researcher with years of experience",
    )
    analyst = Agent(
        role="analyst",
        goal="Perform statistical analysis on collected data",
        backstory="PhD statistician specializing in meta-analyses",
    )
    writer = Agent(
        role="writer",
        goal="Produce clear, well-structured research reports",
        backstory="Technical writer with scientific publishing experience",
    )
    reviewer = Agent(
        role="reviewer",
        goal="Review and approve research reports",
        backstory="Senior researcher and peer reviewer",
    )

    gather = Task(
        name="gather_data",
        description="Collect research papers and datasets from academic sources",
        expected_output="List of relevant papers and datasets",
        agent=researcher,
    )
    analyze = Task(
        name="analyze_data",
        description="Run statistical analysis on gathered data",
        expected_output="Statistical analysis results with confidence intervals",
        agent=analyst,
        context=[gather],
    )
    write = Task(
        name="write_report",
        description="Draft the research report from analysis results",
        expected_output="Complete research report draft",
        agent=writer,
        context=[gather, analyze],
    )
    review = Task(
        name="peer_review",
        description="Review and approve the final report",
        expected_output="Approved report with reviewer comments",
        agent=reviewer,
        context=[write],
    )

    crew = Crew(
        agents=[researcher, analyst, writer, reviewer],
        tasks=[gather, analyze, write, review],
        process=Process.sequential,
    )
    return crew


def build_hierarchical_crew():
    """Build a hierarchical crew for comparison."""
    researcher = Agent(
        role="literature_reviewer",
        goal="Survey existing literature",
        backstory="Expert in literature reviews",
    )
    experimenter = Agent(
        role="experimenter",
        goal="Run experiments",
        backstory="Lab scientist",
    )
    synthesizer = Agent(
        role="synthesizer",
        goal="Synthesize findings into coherent conclusions",
        backstory="Senior researcher",
    )

    lit_review = Task(
        name="literature_review",
        description="Survey existing literature on the topic",
        expected_output="Literature review summary",
        agent=researcher,
    )
    experiment = Task(
        name="experiment",
        description="Run experiments based on literature gaps",
        expected_output="Experimental results",
        agent=experimenter,
    )
    synthesis = Task(
        name="synthesis",
        description="Synthesize all findings",
        expected_output="Synthesized research conclusions",
        agent=synthesizer,
        context=[lit_review, experiment],
    )

    crew = Crew(
        agents=[researcher, experimenter, synthesizer],
        tasks=[lit_review, experiment, synthesis],
        process=Process.hierarchical,
        manager_llm="gpt-4o",
    )
    return crew


# ---------------------------------------------------------------------------
# 2. Extract and inspect
# ---------------------------------------------------------------------------

def inspect_graph(graph: AgentGraph):
    print(f"\nGraph: {graph.name}  (framework: {graph.framework})")
    print("-" * 50)

    print(f"  Nodes ({len(graph.nodes)}):")
    for node in graph.nodes:
        tools_str = f"  tools={list(node.tools)}" if node.tools else ""
        print(f"    {node.id:<22} kind={node.kind.value:<8}{tools_str}")

    print(f"  Edges ({len(graph.edges)}):")
    for edge in graph.edges:
        print(f"    {edge.source} -> {edge.target}  ({edge.kind.value})")


# ---------------------------------------------------------------------------
# 3. Structural verification
# ---------------------------------------------------------------------------

def verify_structure(graph: AgentGraph):
    print(f"\nStructural checks for '{graph.name}':")
    print("-" * 50)

    adj = adjacency(graph)

    # Check: gather_data comes before analyze_data
    gather = node_by_id(graph, "gather_data")
    analyze = node_by_id(graph, "analyze_data")
    if gather and analyze:
        reachable = set()
        frontier = [gather.id]
        while frontier:
            current = frontier.pop()
            if current in reachable:
                continue
            reachable.add(current)
            frontier.extend(adj.get(current, []))
        assert analyze.id in reachable, "analyze_data not reachable from gather_data"
        print("  [PASS] gather_data reaches analyze_data")

    # Check: no tool nodes without tools
    for node in graph.nodes:
        if node.kind == NodeKind.TOOL:
            assert node.tools, f"TOOL node {node.id} has no tools"
    tool_count = sum(1 for n in graph.nodes if n.kind == NodeKind.TOOL)
    print(f"  [PASS] All {tool_count} tool node(s) have tools declared")

    # Check: exactly one entry, at least one exit
    entries = [n for n in graph.nodes if n.kind == NodeKind.ENTRY]
    exits = [n for n in graph.nodes if n.kind == NodeKind.EXIT]
    assert len(entries) == 1, f"Expected 1 entry, got {len(entries)}"
    assert len(exits) >= 1, f"Expected at least 1 exit, got {len(exits)}"
    print(f"  [PASS] Entry/exit structure valid ({len(entries)} entry, {len(exits)} exit)")

    # Check: all nodes reachable from entry
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


# ---------------------------------------------------------------------------
# 4. Temporal verification
# ---------------------------------------------------------------------------

def verify_temporal(graph: AgentGraph):
    print(f"\nTemporal verification for '{graph.name}':")
    print("-" * 50)

    rules = [
        MonitorRuleSpec(
            rule_id="no_code_execution",
            dsl="G !tool:execute_code",
            on_violation="block",
        ),
        MonitorRuleSpec(
            rule_id="fetch_then_analyze",
            dsl="action:fetch_raw -> F action:analyze",
            on_violation="halt",
        ),
    ]

    compiled = tuple(compile_monitor_rule(r) for r in rules)

    trace_normal = [
        {"tool_name": "web_search", "action_type": "fetch_raw", "tags": []},
        {"tool_name": "pdf_reader", "tags": ["read"]},
        {"tool_name": "stats_calculator", "action_type": "analyze", "tags": []},
        {"action_type": "write", "tags": ["output"]},
    ]

    trace_bad = [
        {"tool_name": "web_search", "action_type": "fetch_raw", "tags": []},
        {"action_type": "write", "tags": ["output"]},
        {"action_type": "fetch_raw", "tags": []},
    ]

    trace_code = [
        {"tool_name": "web_search", "tags": ["read"]},
        {"tool_name": "execute_code", "tags": ["dangerous"]},
    ]

    for trace_name, events in [
        ("normal_flow", trace_normal),
        ("fetch_without_analysis", trace_bad),
        ("code_execution_attempt", trace_code),
    ]:
        state: dict[str, int] = {}
        violations: list[str] = []

        for event in events:
            state, snapshots, decision = evaluate_monitors(compiled, state, event)
            for snap in snapshots:
                if snap.violation:
                    violations.append(f"{snap.rule_id}")

        status = "PASS" if not decision.denied else "BLOCKED"
        if decision.halt:
            status = "HALT"
        marker = "  " if status == "PASS" else "  !"
        print(f"{marker} Trace '{trace_name}': [{status}]", end="")
        if violations:
            print(f"  (violated: {', '.join(violations)})")
        else:
            print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Agentproof: CrewAI Research Crew Verification")
    print("=" * 60)

    # Sequential crew
    seq_crew = build_research_crew()
    seq_graph = extract_crewai(seq_crew)
    inspect_graph(seq_graph)
    verify_structure(seq_graph)
    verify_temporal(seq_graph)

    # Hierarchical crew
    hier_crew = build_hierarchical_crew()
    hier_graph = extract_crewai(hier_crew)
    inspect_graph(hier_graph)
    verify_structure(hier_graph)

    print("\n" + "=" * 60)
    print("All checks complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
