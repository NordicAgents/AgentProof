"""Tests for structural verification checks."""

from __future__ import annotations

from agentproof.graph.model import (
    AgentGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
from agentproof.verify import run_structural_checks


def _check(report: dict, check_id: str) -> dict:
    for chk in report.get("checks", []):
        if chk.get("check_id") == check_id:
            return chk
    raise AssertionError(f"missing check_id={check_id}")


def test_exit_reachability_detects_missing_exit():
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("a", NodeKind.LLM),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(GraphEdge("entry", "a"),),
        entry_id="entry",
        exit_ids=("exit",),
    )

    report = run_structural_checks(graph, require_human=False)
    chk = _check(report, "exit_reachability")
    assert chk["passed"] is False
    assert chk["missing_exits"] == ["exit"]
    # Witness: path from entry to reachability frontier + unreachable exit
    assert "witnesses" in chk
    witness = chk["witnesses"]["exit"]
    assert witness is not None
    assert witness[0] == "entry"
    assert witness[-1] == "exit"


def test_dead_end_detection_flags_non_exit_nodes():
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("dead", NodeKind.LLM),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(GraphEdge("entry", "exit"),),
        entry_id="entry",
        exit_ids=("exit",),
    )

    report = run_structural_checks(graph, require_human=False)
    chk = _check(report, "dead_ends")
    assert chk["passed"] is False
    assert chk["dead_ends"] == ["dead"]
    # Dead-end witness: no path from entry to dead (unreachable dead-end)
    assert "witnesses" in chk


def test_dead_end_witness_path():
    """A reachable dead-end should have a witness path from entry."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("mid", NodeKind.LLM),
            GraphNode("dead", NodeKind.LLM),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "mid"),
            GraphEdge("mid", "dead"),
            GraphEdge("mid", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    report = run_structural_checks(graph, require_human=False)
    chk = _check(report, "dead_ends")
    assert chk["passed"] is False
    witness = chk["witnesses"]["dead"]
    assert witness == ["entry", "mid", "dead"]


def test_router_shape_requires_conditional_edges():
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("router", NodeKind.ROUTER),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "router"),
            GraphEdge("router", "exit", kind=EdgeKind.DIRECT),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    report = run_structural_checks(graph, require_human=False)
    chk = _check(report, "router_shape")
    assert chk["passed"] is False
    assert chk["router_count"] == 1
    assert chk["violations"][0]["router"] == "router"


def test_human_presence_is_enforced_when_required():
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

    report = run_structural_checks(graph, require_human=True)
    chk = _check(report, "human_presence")
    assert chk["passed"] is False
    assert chk["human_nodes"] == []


def test_tool_declarations_flag_empty_tool_lists():
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("tool", NodeKind.TOOL, tools=()),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "tool"),
            GraphEdge("tool", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    report = run_structural_checks(graph, require_human=False)
    chk = _check(report, "tool_declarations")
    assert chk["passed"] is False
    assert chk["tool_nodes_missing_tools"] == ["tool"]


def test_checks_include_category_field():
    """Every check result must include a 'category' field."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(GraphEdge("entry", "exit"),),
        entry_id="entry",
        exit_ids=("exit",),
    )

    report = run_structural_checks(graph, require_human=False)
    for chk in report["checks"]:
        assert "category" in chk, f"check {chk['check_id']} missing category"
        assert chk["category"] in ("structural", "policy")

    # Verify specific categories
    assert _check(report, "exit_reachability")["category"] == "structural"
    assert _check(report, "dead_ends")["category"] == "structural"
    assert _check(report, "router_shape")["category"] == "structural"
    assert _check(report, "human_presence")["category"] == "policy"
    assert _check(report, "tool_declarations")["category"] == "structural"


def test_suppression_dead_ends():
    """Suppressed dead-end nodes should not be flagged."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("mid", NodeKind.LLM),
            GraphNode("halt", NodeKind.LLM),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "mid"),
            GraphEdge("mid", "halt"),
            GraphEdge("mid", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    # Without suppression — halt is a dead end
    report = run_structural_checks(graph, require_human=False)
    chk = _check(report, "dead_ends")
    assert chk["passed"] is False
    assert "halt" in chk["dead_ends"]

    # With suppression — halt is ignored
    report = run_structural_checks(
        graph, require_human=False, suppressions={"dead_ends": {"halt"}}
    )
    chk = _check(report, "dead_ends")
    assert chk["passed"] is True
    assert "halt" not in chk["dead_ends"]


def test_suppression_tool_declarations():
    """Suppressed tool nodes should not be flagged for missing declarations."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("tool", NodeKind.TOOL, tools=()),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "tool"),
            GraphEdge("tool", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    report = run_structural_checks(
        graph, require_human=False, suppressions={"tool_declarations": {"tool"}}
    )
    chk = _check(report, "tool_declarations")
    assert chk["passed"] is True

