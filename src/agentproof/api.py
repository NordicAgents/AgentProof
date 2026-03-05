"""Stable public API for AgentProof verification.

Example usage::

    from agentproof.api import verify
    report = verify(graph, require_human=True, monitor_rules=[...])
"""

from __future__ import annotations

import random
from typing import Any

from agentproof.graph.model import AgentGraph, NodeKind, adjacency, node_by_id
from agentproof.monitor.ltl import (
    CompiledMonitorRule,
    MonitorRuleSpec,
    compile_monitor_rule,
    evaluate_monitors,
)
from agentproof.verify import run_structural_checks


def verify(
    graph: AgentGraph,
    *,
    require_human: bool = False,
    monitor_rules: list[MonitorRuleSpec] | None = None,
    event_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run structural checks and optional temporal monitoring.

    Parameters
    ----------
    graph : AgentGraph
        The agent workflow graph to verify.
    require_human : bool
        Whether to require a human-in-the-loop node.
    monitor_rules : list[MonitorRuleSpec] | None
        Temporal policy rules to compile and evaluate.
    event_trace : list[dict] | None
        Simulated event trace for temporal monitoring.

    Returns
    -------
    dict
        A JSON-serializable report containing structural check results
        and, if rules/trace are provided, temporal monitoring results.
    """
    report: dict[str, Any] = {}

    # Structural checks
    report["structural"] = run_structural_checks(graph, require_human=require_human)

    # Temporal monitoring
    if monitor_rules:
        compiled: list[CompiledMonitorRule] = []
        compile_errors: list[dict[str, str]] = []
        for rule in monitor_rules:
            try:
                compiled.append(compile_monitor_rule(rule))
            except Exception as e:
                compile_errors.append({"rule_id": rule.rule_id, "error": str(e)})

        report["monitor"] = {
            "rules_compiled": len(compiled),
            "compile_errors": compile_errors,
        }

        if event_trace is not None and compiled:
            state: dict[str, int] = {}
            all_snapshots: list[list[dict]] = []
            final_decision = None
            for event in event_trace:
                state, snapshots, decision = evaluate_monitors(
                    tuple(compiled), state, event
                )
                all_snapshots.append([s.to_trace_entry() for s in snapshots])
                final_decision = decision

            report["monitor"]["trace_length"] = len(event_trace)
            report["monitor"]["final_decision"] = {
                "status": final_decision.status,
                "denied": final_decision.denied,
                "halt": final_decision.halt,
                "escalate": final_decision.escalate,
            } if final_decision else None
            report["monitor"]["violations"] = [
                snap
                for step in all_snapshots
                for snap in step
                if snap.get("violation")
            ]

    return report


def _event_for_node(node_id: str, graph: AgentGraph) -> dict[str, Any]:
    """Generate a synthetic event dict for a graph node."""
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


def generate_traces(
    graph: AgentGraph,
    *,
    n_traces: int = 5,
    max_steps: int = 50,
    seed: int = 42,
) -> list[list[dict[str, Any]]]:
    """Generate synthetic execution traces via random walks on the graph.

    Each trace is a list of event dicts, one per node visited.  The walk
    starts at ``graph.entry_id`` and follows random outgoing edges until
    an exit node is reached or *max_steps* is exceeded.
    """
    rng = random.Random(seed)
    adj = adjacency(graph)
    exit_set = set(graph.exit_ids)
    traces: list[list[dict[str, Any]]] = []

    for _ in range(n_traces):
        trace: list[dict[str, Any]] = []
        current = graph.entry_id
        for _step in range(max_steps):
            trace.append(_event_for_node(current, graph))
            if current in exit_set:
                break
            neighbors = adj.get(current, [])
            if not neighbors:
                break
            current = rng.choice(neighbors)
        traces.append(trace)

    return traces
