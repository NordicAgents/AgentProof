"""Tests for static temporal verification (graph x DFA product)."""

from __future__ import annotations

from agentproof.graph.model import (
    AgentGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
from agentproof.monitor.ltl import MonitorRuleSpec, compile_monitor_rule
from agentproof.verify.temporal import check_temporal_property


def test_forbidden_tool_detected_statically():
    """A forbidden-tool rule should flag a graph that contains the tool."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("tool_x", NodeKind.TOOL, tools=("X",)),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "tool_x"),
            GraphEdge("tool_x", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    rule = compile_monitor_rule(
        MonitorRuleSpec(rule_id="no_X", dsl="G !tool:X", on_violation="block")
    )

    result = check_temporal_property(graph, rule)
    assert result["violated"] is True
    assert result["violation_path"] is not None
    assert "tool_x" in result["violation_path"]


def test_forbidden_tool_not_present_passes():
    """A forbidden-tool rule should pass when the tool is absent."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("step", NodeKind.LLM),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "step"),
            GraphEdge("step", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    rule = compile_monitor_rule(
        MonitorRuleSpec(rule_id="no_X", dsl="G !tool:X", on_violation="block")
    )

    result = check_temporal_property(graph, rule)
    assert result["violated"] is False
    assert result["violation_path"] is None


def test_implication_future_violation():
    """An implication-future rule should detect a cycle that never fulfils the consequent."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("tool_a", NodeKind.TOOL, tools=("A",)),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "tool_a"),
            GraphEdge("tool_a", "tool_a", kind=EdgeKind.LOOP),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    rule = compile_monitor_rule(
        MonitorRuleSpec(
            rule_id="a_then_b",
            dsl="tool:A -> F tool:B",
            on_violation="block",
        )
    )

    result = check_temporal_property(graph, rule)
    assert result["violated"] is True
    assert result["violation_path"] is not None


def test_implication_future_satisfied():
    """An implication-future rule should pass when the consequent is eventually reached."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("tool_a", NodeKind.TOOL, tools=("A",)),
            GraphNode("tool_b", NodeKind.TOOL, tools=("B",)),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "tool_a"),
            GraphEdge("tool_a", "tool_b"),
            GraphEdge("tool_b", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    rule = compile_monitor_rule(
        MonitorRuleSpec(
            rule_id="a_then_b",
            dsl="tool:A -> F tool:B",
            on_violation="block",
        )
    )

    result = check_temporal_property(graph, rule)
    assert result["violated"] is False
    assert result["violation_path"] is None


def test_product_state_count():
    """Product states explored should be bounded by |nodes| * |DFA states|."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("mid", NodeKind.LLM),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "mid"),
            GraphEdge("mid", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    rule = compile_monitor_rule(
        MonitorRuleSpec(rule_id="no_X", dsl="G !tool:X", on_violation="block")
    )

    # G !tool:X compiles to a 2-state DFA; graph has 3 nodes => <=6 product states
    result = check_temporal_property(graph, rule)
    assert result["violated"] is False
    assert result["product_states_explored"] <= 3 * 2
