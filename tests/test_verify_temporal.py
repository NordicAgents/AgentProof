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


def test_multi_tool_node_non_first_tool_is_caught():
    """A forbidden-tool rule must flag a node even when the tool is not tools[0].

    Previously only tools[0] was mapped to the event, so rm_rf at index 1
    was silently skipped and the static check produced a false negative.
    """
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("agent", NodeKind.TOOL, tools=("fetch", "rm_rf")),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "agent"),
            GraphEdge("agent", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    rule = compile_monitor_rule(
        MonitorRuleSpec(rule_id="no_rm_rf", dsl="G !tool:rm_rf", on_violation="block")
    )

    result = check_temporal_property(graph, rule)
    assert result["violated"] is True, (
        "rm_rf is available on the agent node but was not flagged — "
        "multi-tool event mapping is broken"
    )
    assert "agent" in result["violation_path"]


def test_multi_tool_node_liveness_not_self_discharged():
    """A response rule must not self-discharge on a node that declares both tools.

    For a node with tools=("write", "audit_log"), the rule
    ``tool:write -> F tool:audit_log`` means: every write must eventually
    be followed by an audit_log step.  If the agent calls only write and
    then exits, that is a violation.

    The OR-based approach (emitting a single event with all tools true) let
    the antecedent fire AND the consequent simultaneously satisfy itself,
    producing a false 'verified' verdict.  The branching fix generates one
    DFA symbol per tool, so the write-only branch remains pending at exit.
    """
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("agent", NodeKind.TOOL, tools=("write", "audit_log")),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "agent"),
            GraphEdge("agent", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    rule = compile_monitor_rule(
        MonitorRuleSpec(
            rule_id="audit_after_write",
            dsl="tool:write -> F tool:audit_log",
            on_violation="block",
        )
    )

    result = check_temporal_property(graph, rule)
    assert result["violated"] is True, (
        "A node with tools=(write, audit_log) and no separate audit step "
        "should violate tool:write -> F tool:audit_log, but the check "
        "reported 'verified' — liveness self-discharge is not fixed"
    )


def test_multi_tool_node_preserves_custom_event_mapper_fields():
    """Per-tool branching must preserve fields supplied by a custom mapper."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(GraphNode("agent", NodeKind.TOOL, tools=("A", "B")),),
        edges=(),
        entry_id="agent",
        exit_ids=("agent",),
    )

    rule = compile_monitor_rule(
        MonitorRuleSpec(
            rule_id="no_dangerous_action",
            dsl="G !action:dangerous",
            on_violation="block",
        )
    )

    def custom_event_mapper(node_id, _graph):
        return {"node_id": node_id, "action_type": "dangerous"}

    result = check_temporal_property(graph, rule, event_mapper=custom_event_mapper)
    assert result["violated"] is True
