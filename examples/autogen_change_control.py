#!/usr/bin/env python3
"""
Agentproof Case Study: AutoGen AgentChat Change-Control Board
=============================================================

Builds a real AutoGen AgentChat team topology with a human approver, extracts an
AgentGraph, runs structural checks, and evaluates temporal policy monitors over
representative traces.

Topology (speaker transitions):
  planner → implementer → risk_officer → human_approver → __exit__

Temporal policies (Agentproof DSL):
  1) G !tool:send_email                          (halt)
  2) decision:deploy -> F action:human_approval  (halt)

Traces (uniform keys used by paper scripts):
  - happy_path       (PASS)
  - forbidden_tool   (HALT)
  - policy_violation (HALT)
"""

from __future__ import annotations

try:
    from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
except ImportError:
    raise SystemExit(
        "AutoGen AgentChat is not installed.\n"
        "Install with:  pip install -e '.[autogen]'"
    )

from unittest.mock import MagicMock

from agentproof.graph import AgentGraph, extract_autogen
from agentproof.monitor.ltl import MonitorRuleSpec, compile_monitor_rule, evaluate_monitors
from agentproof.verify import run_structural_checks


def _mock_client():
    return MagicMock()


TEMPORAL_RULES: tuple[MonitorRuleSpec, ...] = (
    MonitorRuleSpec("ag_forbid_email", "G !tool:send_email", on_violation="halt"),
    MonitorRuleSpec(
        "ag_deploy_needs_human_between",
        "decision:deploy -> F action:human_approval",
        on_violation="halt",
    ),
)

TEMPORAL_TRACES: dict[str, list[dict]] = {
    "happy_path": [
        {"decision": "deploy", "tags": ["proposal"]},
        {"action_type": "human_approval", "tags": ["approval"]},
        {"decision": "deploy", "tags": ["proposal"]},
        {"action_type": "human_approval", "tags": ["approval"]},
    ],
    "forbidden_tool": [
        {"decision": "deploy", "tags": ["proposal"]},
        {"tool_name": "send_email", "tags": ["exfiltration"]},
    ],
    "policy_violation": [
        {"decision": "deploy", "tags": ["proposal"]},
        {"tags": ["discussion"]},
        {"decision": "deploy", "tags": ["proposal"]},
    ],
}


def build_change_control_team():
    client = _mock_client()

    planner = AssistantAgent(name="planner", model_client=client)
    implementer = AssistantAgent(name="implementer", model_client=client)
    risk_officer = AssistantAgent(name="risk_officer", model_client=client)
    human_approver = UserProxyAgent(name="human_approver")

    transitions = {
        planner: [implementer],
        implementer: [risk_officer],
        risk_officer: [human_approver],
    }

    return [planner, implementer, risk_officer, human_approver], transitions


def _severity(decision) -> int:
    if decision.escalate:
        return 3
    if decision.halt:
        return 2
    if decision.denied:
        return 1
    return 0


def _severity_label(level: int) -> str:
    return {0: "PASS", 1: "BLOCKED", 2: "HALT", 3: "ESCALATE"}[level]


def _evaluate_trace(compiled_rules, events: list[dict]) -> tuple[str, list[str]]:
    state: dict[str, int] = {}
    worst = 0
    violated: set[str] = set()

    for ev in events:
        state, snapshots, decision = evaluate_monitors(compiled_rules, state, ev)
        worst = max(worst, _severity(decision))
        for snap in snapshots:
            if snap.violation:
                violated.add(snap.rule_id)

    return _severity_label(worst), sorted(violated)


def main() -> None:
    print("=" * 72)
    print("Agentproof Case Study: AutoGen Change-Control Board")
    print("=" * 72)

    agents, transitions = build_change_control_team()
    graph: AgentGraph = extract_autogen(agents, allowed_transitions=transitions)

    print(f"\nExtracted graph: {graph.name} (framework={graph.framework})")
    print(f"  |V|={len(graph.nodes)}  |E|={len(graph.edges)}")

    struct = run_structural_checks(graph, require_human=True)
    print(f"\nStructural checks: {struct['passed_count']}/{struct['total']} passed")
    for chk in struct["checks"]:
        marker = "PASS" if chk["passed"] else "FAIL"
        print(f"  [{marker}] {chk['check_id']}")

    compiled_rules = tuple(compile_monitor_rule(r) for r in TEMPORAL_RULES)
    print(f"\nTemporal rules: {len(compiled_rules)} compiled")
    for r in TEMPORAL_RULES:
        print(f"  - {r.rule_id}: {r.dsl} (on_violation={r.on_violation})")

    print("\nTrace evaluation:")
    for trace_id, events in TEMPORAL_TRACES.items():
        status, violated = _evaluate_trace(compiled_rules, events)
        msg = f"  {trace_id}: [{status}]"
        if violated:
            msg += f"  violated={violated}"
        print(msg)


if __name__ == "__main__":
    main()

