#!/usr/bin/env python3
"""
Agentproof Case Study: LangGraph Incident Response Triage & Mitigation
=====================================================================

Builds a real LangGraph StateGraph for incident response triage, extracts an
AgentGraph, runs structural checks, and evaluates temporal policy monitors over
representative traces.

Workflow (high level):
    __start__ → intake → triage_router → (auto_mitigate | human_approval)
        → mitigate_tools → postmortem_tools → __end__

Temporal policies (Agentproof DSL):
  1) G !tool:drop_database                          (halt)
  2) decision:mitigate -> F action:human_approval   (escalate)

Traces (uniform keys used by paper scripts):
  - happy_path       (PASS)
  - forbidden_tool   (HALT)
  - policy_violation (ESCALATE)
"""

from __future__ import annotations

from typing import Literal, TypedDict

try:
    from langgraph.graph import StateGraph
except ImportError:
    raise SystemExit(
        "LangGraph is not installed.\n"
        "Install with:  pip install -e '.[langgraph]'"
    )

from agentproof.graph import AgentGraph, extract_langgraph
from agentproof.monitor.ltl import MonitorRuleSpec, compile_monitor_rule, evaluate_monitors
from agentproof.verify import run_structural_checks


class State(TypedDict):
    incident_id: str
    summary: str


def intake(state: State) -> State:
    return state


def triage_router(state: State) -> State:
    return state


def auto_mitigate(state: State) -> State:
    return state


def human_approval(state: State) -> State:
    return state


def mitigate_tools(state: State) -> State:
    return state


def postmortem_tools(state: State) -> State:
    return state


def triage_decision(_state: State) -> Literal["auto", "needs_human"]:
    return "auto"


def restart_service() -> str:
    return "ok"


def rollback_deploy() -> str:
    return "ok"


def create_ticket() -> str:
    return "ok"


def page_oncall() -> str:
    return "ok"


TEMPORAL_RULES: tuple[MonitorRuleSpec, ...] = (
    MonitorRuleSpec("lg_forbid_drop_db", "G !tool:drop_database", on_violation="halt"),
    MonitorRuleSpec(
        "lg_mitigate_requires_approval_between",
        "decision:mitigate -> F action:human_approval",
        on_violation="escalate",
    ),
)

TEMPORAL_TRACES: dict[str, list[dict]] = {
    "happy_path": [
        {"decision": "mitigate", "tags": ["decision"]},
        {"action_type": "human_approval", "tags": ["approval"]},
        {"tool_name": "restart_service", "tags": ["mitigation"]},
        {"decision": "mitigate", "tags": ["decision"]},
        {"action_type": "human_approval", "tags": ["approval"]},
        {"tool_name": "rollback_deploy", "tags": ["mitigation"]},
        {"tool_name": "create_ticket", "tags": ["audit"]},
    ],
    "forbidden_tool": [
        {"decision": "mitigate", "tags": ["decision"]},
        {"action_type": "human_approval", "tags": ["approval"]},
        {"tool_name": "drop_database", "tags": ["destructive"]},
    ],
    "policy_violation": [
        {"decision": "mitigate", "tags": ["decision"]},
        {"tool_name": "restart_service", "tags": ["mitigation"]},
        {"decision": "mitigate", "tags": ["decision"]},
    ],
}


def build_incident_response_graph():
    graph = StateGraph(State)

    graph.add_node("intake", intake)
    graph.add_node("triage_router", triage_router)
    graph.add_node("auto_mitigate", auto_mitigate)
    graph.add_node("human_approval", human_approval)

    graph.add_node(
        "mitigate_tools",
        mitigate_tools,
        metadata={"tools": [restart_service, rollback_deploy]},
    )
    graph.add_node(
        "postmortem_tools",
        postmortem_tools,
        metadata={"tools": [create_ticket, page_oncall]},
    )

    graph.add_edge("__start__", "intake")
    graph.add_edge("intake", "triage_router")
    graph.add_conditional_edges(
        "triage_router",
        triage_decision,
        {"auto": "auto_mitigate", "needs_human": "human_approval"},
    )
    graph.add_edge("auto_mitigate", "mitigate_tools")
    graph.add_edge("human_approval", "mitigate_tools")
    graph.add_edge("mitigate_tools", "postmortem_tools")
    graph.add_edge("postmortem_tools", "__end__")

    return graph.compile()


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
    print("Agentproof Case Study: LangGraph Incident Response")
    print("=" * 72)

    compiled = build_incident_response_graph()
    graph: AgentGraph = extract_langgraph(compiled)

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

