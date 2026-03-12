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
    assert _check(report, "reverse_reachability")["category"] == "structural"
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


# ---------------------------------------------------------------------------
# Phase 1A: Reverse reachability / livelock detection
# ---------------------------------------------------------------------------


def test_reverse_reachability_detects_livelock_cycle():
    """Nodes in a cycle unreachable from exit should be flagged as livelock."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("a", NodeKind.LLM),
            GraphNode("b", NodeKind.LLM),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "a"),
            GraphEdge("a", "b"),
            GraphEdge("b", "a"),
            GraphEdge("entry", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    report = run_structural_checks(graph, require_human=False)
    chk = _check(report, "reverse_reachability")
    assert chk["passed"] is False
    assert "a" in chk["livelock_nodes"]
    assert "b" in chk["livelock_nodes"]


def test_reverse_reachability_passes_clean_graph():
    """Linear graph where all nodes can reach exit should pass."""
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

    report = run_structural_checks(graph, require_human=False)
    chk = _check(report, "reverse_reachability")
    assert chk["passed"] is True
    assert chk["livelock_nodes"] == []


def test_reverse_reachability_suppression():
    """Suppressed livelock nodes should not be flagged."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("a", NodeKind.LLM),
            GraphNode("b", NodeKind.LLM),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "a"),
            GraphEdge("a", "b"),
            GraphEdge("b", "a"),
            GraphEdge("entry", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    report = run_structural_checks(
        graph,
        require_human=False,
        suppressions={"reverse_reachability": {"a", "b"}},
    )
    chk = _check(report, "reverse_reachability")
    assert chk["passed"] is True
    assert chk["livelock_nodes"] == []


def test_reverse_reachability_witness_path():
    """Witness path should start at entry and end at the livelock node."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("a", NodeKind.LLM),
            GraphNode("b", NodeKind.LLM),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "a"),
            GraphEdge("a", "b"),
            GraphEdge("b", "a"),
            GraphEdge("entry", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    report = run_structural_checks(graph, require_human=False)
    chk = _check(report, "reverse_reachability")
    for nid in chk["livelock_nodes"]:
        witness = chk["witnesses"][nid]
        assert witness is not None
        assert witness[0] == "entry"
        assert witness[-1] == nid


# ---------------------------------------------------------------------------
# Phase 1B: Human gate coverage
# ---------------------------------------------------------------------------


def test_human_gate_coverage_detects_bypass():
    """Sensitive tool reachable without passing through HUMAN should fail."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("router", NodeKind.ROUTER),
            GraphNode("human", NodeKind.HUMAN),
            GraphNode("tool_a", NodeKind.TOOL, tools=("tool_a",)),
            GraphNode("tool_b", NodeKind.TOOL, tools=("tool_b",)),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "router"),
            GraphEdge("router", "human", kind=EdgeKind.CONDITIONAL),
            GraphEdge("human", "tool_a"),
            GraphEdge("router", "tool_b", kind=EdgeKind.CONDITIONAL),
            GraphEdge("tool_a", "exit"),
            GraphEdge("tool_b", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    report = run_structural_checks(
        graph, require_human=False, sensitive_tools={"tool_b"},
    )
    chk = _check(report, "human_gate_coverage")
    assert chk["passed"] is False
    assert "tool_b" in chk["ungated_tools"]


def test_human_gate_coverage_passes_when_dominated():
    """All paths to sensitive tool go through HUMAN -> pass."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("human", NodeKind.HUMAN),
            GraphNode("tool_a", NodeKind.TOOL, tools=("tool_a",)),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "human"),
            GraphEdge("human", "tool_a"),
            GraphEdge("tool_a", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    report = run_structural_checks(
        graph, require_human=False, sensitive_tools={"tool_a"},
    )
    chk = _check(report, "human_gate_coverage")
    assert chk["passed"] is True
    assert chk["ungated_tools"] == []


def test_human_gate_coverage_skipped_when_none():
    """When sensitive_tools is None the check should not appear at all."""
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

    report = run_structural_checks(graph, require_human=False, sensitive_tools=None)
    check_ids = [c["check_id"] for c in report["checks"]]
    assert "human_gate_coverage" not in check_ids


def test_human_gate_coverage_witness_has_no_human():
    """Witness path for an ungated tool must not contain any HUMAN node."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("router", NodeKind.ROUTER),
            GraphNode("human", NodeKind.HUMAN),
            GraphNode("tool_a", NodeKind.TOOL, tools=("tool_a",)),
            GraphNode("tool_b", NodeKind.TOOL, tools=("tool_b",)),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "router"),
            GraphEdge("router", "human", kind=EdgeKind.CONDITIONAL),
            GraphEdge("human", "tool_a"),
            GraphEdge("router", "tool_b", kind=EdgeKind.CONDITIONAL),
            GraphEdge("tool_a", "exit"),
            GraphEdge("tool_b", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    report = run_structural_checks(
        graph, require_human=False, sensitive_tools={"tool_b"},
    )
    chk = _check(report, "human_gate_coverage")
    assert chk["passed"] is False
    witness = chk["witnesses"]["tool_b"]
    assert witness is not None
    assert "human" not in witness

