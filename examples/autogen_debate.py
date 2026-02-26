#!/usr/bin/env python3
"""
Agentproof Example: AutoGen Multi-Agent Debate
===============================================

Demonstrates extracting **real** AutoGen v0.4 team topologies and verifying
speaker transition safety properties.

Topologies demonstrated:
    1. Moderated debate: moderator <-> advocate, moderator <-> critic
       (advocate and critic never talk directly to each other)
    2. Round-robin: alice -> bob -> charlie -> alice
    3. Direct list with explicit transitions

No API keys required — agents use a mock model client.

Safety rules:
    1. Never call "send_email" tool  (G !tool:send_email)
    2. If a decision is proposed, human review must eventually follow
       (decision:proposed -> F action:human_review)

Requirements:
    pip install -e ".[autogen]"

Run:
    python examples/autogen_debate.py
"""

from __future__ import annotations

try:
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.teams import RoundRobinGroupChat
except ImportError:
    raise SystemExit(
        "AutoGen is not installed.\n"
        "Install with:  pip install -e '.[autogen]'"
    )

from unittest.mock import MagicMock

from agentproof.graph import (
    AgentGraph,
    NodeKind,
    extract_autogen,
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
# 1. Build debate topologies with real AutoGen v0.4 agents
# ---------------------------------------------------------------------------

def _mock_client():
    """Create a mock model client (no API key needed)."""
    return MagicMock()


def build_moderated_debate():
    """Moderator controls who speaks; advocate and critic never talk directly.

    Uses a plain agent list + explicit transitions dict, since AutoGen v0.4
    teams don't expose allowed_speaker_transitions_dict.
    """
    client = _mock_client()
    moderator = AssistantAgent(name="moderator", model_client=client)
    advocate = AssistantAgent(name="advocate", model_client=client)
    critic = AssistantAgent(name="critic", model_client=client)

    transitions = {
        moderator: [advocate, critic],
        advocate: [moderator],
        critic: [moderator],
    }

    return [moderator, advocate, critic], transitions


def build_round_robin():
    """Three agents take turns in order using real RoundRobinGroupChat."""
    client = _mock_client()
    alice = AssistantAgent(name="alice", model_client=client)
    bob = AssistantAgent(name="bob", model_client=client)
    charlie = AssistantAgent(name="charlie", model_client=client)

    return RoundRobinGroupChat(participants=[alice, bob, charlie])


def build_direct_list():
    """Pass agents as a plain list with explicit transitions."""
    client = _mock_client()
    planner = AssistantAgent(name="planner", model_client=client)
    executor = AssistantAgent(name="executor", model_client=client)
    reviewer = AssistantAgent(name="reviewer", model_client=client)

    transitions = {
        planner: [executor],
        executor: [reviewer],
        reviewer: [planner],
    }
    return [planner, executor, reviewer], transitions


# ---------------------------------------------------------------------------
# 2. Inspect
# ---------------------------------------------------------------------------

def inspect_graph(graph: AgentGraph):
    print(f"\nGraph: {graph.name}  (framework: {graph.framework})")
    print("-" * 50)

    for node in graph.nodes:
        print(f"  {node.id:<16} kind={node.kind.value}")

    for edge in graph.edges:
        print(f"  {edge.source} -> {edge.target}")

    adj = adjacency(graph)
    print(f"  Adjacency:")
    for nid, targets in adj.items():
        if targets:
            print(f"    {nid} -> {targets}")


# ---------------------------------------------------------------------------
# 3. Structural checks
# ---------------------------------------------------------------------------

def verify_structure(graph: AgentGraph):
    print(f"\nStructural checks for '{graph.name}':")
    print("-" * 50)

    adj = adjacency(graph)

    # Check: no self-loops (no agent talks to itself)
    self_loops = [
        nid for nid, targets in adj.items()
        if nid in targets
    ]
    if self_loops:
        print(f"  [WARN] Self-loops detected: {self_loops}")
    else:
        print(f"  [PASS] No agent talks to itself")

    # Check: every non-synthetic node has at least one outgoing edge
    real_nodes = [n for n in graph.nodes if n.kind not in (NodeKind.ENTRY, NodeKind.EXIT)]
    dead_ends = [n.id for n in real_nodes if not adj.get(n.id)]
    if dead_ends:
        print(f"  [WARN] Dead-end agents (no outgoing): {dead_ends}")
    else:
        print(f"  [PASS] All agents have outgoing transitions")

    # Check: advocate and critic never talk directly (moderated debate specific)
    advocate_succ = set(adj.get("advocate", []))
    critic_succ = set(adj.get("critic", []))
    if "advocate" in adj and "critic" in adj:
        if "critic" not in advocate_succ and "advocate" not in critic_succ:
            print(f"  [PASS] Advocate and critic isolated (must go through moderator)")
        else:
            print(f"  [WARN] Advocate and critic can talk directly!")


# ---------------------------------------------------------------------------
# 4. Temporal verification
# ---------------------------------------------------------------------------

def verify_temporal(graph: AgentGraph):
    print(f"\nTemporal verification for '{graph.name}':")
    print("-" * 50)

    rules = [
        MonitorRuleSpec(
            rule_id="no_email",
            dsl="G !tool:send_email",
            on_violation="block",
        ),
        MonitorRuleSpec(
            rule_id="decision_needs_review",
            dsl="decision:proposed -> F action:human_review",
            on_violation="escalate",
        ),
    ]

    compiled = tuple(compile_monitor_rule(r) for r in rules)

    traces = {
        "safe_debate": [
            {"tags": ["moderator_speaks"]},
            {"tags": ["advocate_argues"]},
            {"tags": ["moderator_speaks"]},
            {"tags": ["critic_rebuts"]},
            {"decision": "proposed", "tags": ["conclusion"]},
            {"action_type": "human_review", "tags": ["approval"]},
        ],
        "decision_without_review": [
            {"tags": ["moderator_speaks"]},
            {"decision": "proposed", "tags": ["conclusion"]},
            {"tags": ["advocate_argues"]},
            {"decision": "proposed", "tags": ["escalation"]},
        ],
        "email_attempt": [
            {"tags": ["moderator_speaks"]},
            {"tool_name": "send_email", "tags": ["unauthorized"]},
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

        if decision.escalate:
            status = "ESCALATE"
        elif decision.halt:
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
    print("Agentproof: AutoGen Multi-Agent Debate Verification")
    print("=" * 60)

    # Moderated debate (agent list + transitions)
    agents, transitions = build_moderated_debate()
    graph = extract_autogen(agents, allowed_transitions=transitions)
    inspect_graph(graph)
    verify_structure(graph)
    verify_temporal(graph)

    # Round-robin (real RoundRobinGroupChat)
    rr = build_round_robin()
    rr_graph = extract_autogen(rr)
    inspect_graph(rr_graph)
    verify_structure(rr_graph)

    # Direct list
    agents, transitions = build_direct_list()
    list_graph = extract_autogen(agents, allowed_transitions=transitions)
    inspect_graph(list_graph)
    verify_structure(list_graph)

    print("\n" + "=" * 60)
    print("All checks complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
