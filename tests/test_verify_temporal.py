"""Tests for static temporal verification (graph x DFA product).

The checker's claim is scoped to FINITE MAXIMAL EXECUTIONS (LTLf): paths
from entry to a termination point (exit node or dead end). TOOL nodes are
by default resolved conservatively — any finite sequence of invocations of
their declared tools, including the empty sequence. Expectations below are
derived per test from those semantics.
"""

from __future__ import annotations

from agentproof.api import generate_traces, verify
from agentproof.graph.model import (
    AgentGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
from agentproof.monitor.ltl import MonitorRuleSpec, compile_monitor_rule
from agentproof.verify.temporal import _default_event_mapper, check_temporal_property


def _rule(rule_id: str, dsl: str):
    return compile_monitor_rule(
        MonitorRuleSpec(rule_id=rule_id, dsl=dsl, on_violation="block")
    )


RESULT_KEYS = {
    # Legacy keys consumed by scripts (scripts read result["violated"]):
    "rule_id",
    "violated",
    "violation_kind",
    "violation_path",
    "product_states_explored",
    # New contract keys:
    "verdict",
    "witness_confidence",
    "inconclusive_reason",
    "divergence_witness",
    "graph_warnings",
}


def test_forbidden_tool_detected_statically():
    """A forbidden-tool rule flags a graph containing the tool (bad prefix)."""
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

    result = check_temporal_property(graph, _rule("no_X", "G !tool:X"))
    assert result["verdict"] == "may_violate"
    assert result["violated"] is True
    assert result["violation_kind"] == "bad_prefix"
    assert result["violation_path"] is not None
    assert "tool_x" in result["violation_path"]
    assert RESULT_KEYS <= set(result.keys())


def test_forbidden_tool_not_present_passes():
    """A forbidden-tool rule is safe when the tool is absent: every finite
    maximal execution (entry -> step -> exit) keeps the DFA accepting."""
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

    result = check_temporal_property(graph, _rule("no_X", "G !tool:X"))
    assert result["verdict"] == "safe"
    assert result["violated"] is False
    assert result["violation_kind"] is None
    assert result["violation_path"] is None
    assert result["witness_confidence"] is None
    assert result["inconclusive_reason"] is None
    assert result["divergence_witness"] is None
    assert result["graph_warnings"] == []


def test_multi_tool_node_forbidden_tool_regression():
    """Multi-tool false-proof regression (BUG 1): a node declaring
    (safe_tool, forbidden_tool) must be checked against EVERY declared tool.

    The old tools[0] event mapper only saw "safe_tool" and reported 'not
    violated' — a false proof. Under the conservative closure, one
    resolution of the node invokes forbidden_tool, driving G !forbidden
    into its absorbing FALSE state => may_violate / bad_prefix.
    """
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("multi", NodeKind.TOOL, tools=("safe_tool", "forbidden_tool")),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "multi"),
            GraphEdge("multi", "exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )

    result = check_temporal_property(
        graph, _rule("no_forbidden", "G !tool:forbidden_tool")
    )
    assert result["verdict"] == "may_violate"
    assert result["violated"] is True
    assert result["violation_kind"] == "bad_prefix"
    assert "multi" in result["violation_path"]


def test_optional_invocation_makes_response_may_violate():
    """Optional-invocation conservativeness (BUG 1, empty resolution):
    on entry -> a -> b -> exit with policy "tool:A -> F tool:B", AST-level
    extraction cannot prove the b node actually calls B. The resolution
    where a invokes A and b invokes NOTHING (empty sequence) reaches exit
    with the F tool:B obligation pending => may_violate /
    unfulfilled_obligation. (Before the fix this graph was 'not violated'.)
    """
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

    result = check_temporal_property(graph, _rule("a_then_b", "tool:A -> F tool:B"))
    assert result["verdict"] == "may_violate"
    assert result["violated"] is True
    assert result["violation_kind"] == "unfulfilled_obligation"
    assert result["violation_path"] == ["entry", "tool_a", "tool_b", "exit"]
    # Default-constructed nodes/edges carry confidence="may", so the
    # witness cannot be certified exact.
    assert result["witness_confidence"] == "may"


def test_explicit_event_mapper_preserves_exact_single_event_semantics():
    """An explicitly passed event_mapper is caller-asserted exact: each node
    emits exactly one event (tools[0] for TOOL nodes), no conservative
    expansion. On entry -> a -> b -> exit, a emits A once and b emits B
    once, discharging the F tool:B obligation before the exit => safe.
    """
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

    result = check_temporal_property(
        graph,
        _rule("a_then_b", "tool:A -> F tool:B"),
        event_mapper=_default_event_mapper,
    )
    assert result["verdict"] == "safe"
    assert result["violated"] is False
    assert result["violation_kind"] is None
    assert result["inconclusive_reason"] is None


def test_cycle_without_consequent_is_inconclusive():
    """Cycle-without-b graph (BUG 2 scope reduction): entry -> a with a
    self-loop and no reachable termination point. No FINITE maximal
    execution exists, so nothing violates under LTLf semantics; the
    reachable product cycle that stays non-accepting (A invoked, F tool:B
    forever pending) is only a heuristic signal. Old behavior was
    violated=True ("divergent_obligation"); new behavior: verdict
    inconclusive / divergent_obligation_possible, violated False, with a
    divergence witness path.
    """
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

    result = check_temporal_property(graph, _rule("a_then_b", "tool:A -> F tool:B"))
    assert result["verdict"] == "inconclusive"
    assert result["violated"] is False
    assert result["violation_kind"] is None
    assert result["violation_path"] is None
    assert result["witness_confidence"] is None
    assert result["inconclusive_reason"] == "divergent_obligation_possible"
    assert result["divergence_witness"] is not None
    assert "tool_a" in result["divergence_witness"]


def test_no_exit_reachable_without_pending_cycle_is_inconclusive():
    """A pure loop with no termination point and no pending obligation:
    all maximal executions are infinite, so the finite-trace checker has
    nothing to certify => inconclusive / no_exit_reachable (not "safe",
    and not a divergence signal since the DFA stays accepting)."""
    graph = AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("a", NodeKind.LLM),
        ),
        edges=(
            GraphEdge("entry", "a"),
            GraphEdge("a", "a", kind=EdgeKind.LOOP),
        ),
        entry_id="entry",
        exit_ids=(),
    )

    result = check_temporal_property(graph, _rule("no_X", "G !tool:X"))
    assert result["verdict"] == "inconclusive"
    assert result["violated"] is False
    assert result["inconclusive_reason"] == "no_exit_reachable"
    assert result["divergence_witness"] is None
    assert result["violation_path"] is None


def _dead_end_graph() -> AgentGraph:
    """entry -> tool_a(A) -> dead (LLM with no successors, NOT in exit_ids)."""
    return AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("tool_a", NodeKind.TOOL, tools=("A",)),
            GraphNode("dead", NodeKind.LLM),
        ),
        edges=(
            GraphEdge("entry", "tool_a"),
            GraphEdge("tool_a", "dead"),
        ),
        entry_id="entry",
        exit_ids=(),
    )


def test_dead_end_counts_as_trace_end_for_obligations():
    """Dead-end termination: a node with no successors that is not in
    exit_ids ends the trace (the execution MUST stop there), so it gets the
    same LTLf unfulfilled-obligation check as an exit. The resolution where
    tool_a invokes A leaves F tool:B pending at the dead end =>
    may_violate / unfulfilled_obligation. (The old code silently skipped
    the end-of-trace check at dead ends.)
    """
    result = check_temporal_property(
        _dead_end_graph(), _rule("a_then_b", "tool:A -> F tool:B")
    )
    assert result["verdict"] == "may_violate"
    assert result["violated"] is True
    assert result["violation_kind"] == "unfulfilled_obligation"
    assert result["violation_path"] == ["entry", "tool_a", "dead"]


def test_dead_end_without_pending_obligation_is_safe():
    """Dead ends count as termination points: with no obligation pending
    (G !tool:X, X absent) the same dead-end graph is certifiably safe —
    NOT inconclusive/no_exit_reachable — because a finite maximal run
    exists (entry -> tool_a -> dead) and it satisfies the policy."""
    result = check_temporal_property(_dead_end_graph(), _rule("no_X", "G !tool:X"))
    assert result["verdict"] == "safe"
    assert result["violated"] is False
    assert result["inconclusive_reason"] is None


def _forbidden_witness_graph(edge_kwargs: dict, node_kwargs: dict) -> AgentGraph:
    return AgentGraph(
        name="g",
        framework="manual",
        nodes=(
            GraphNode("entry", NodeKind.ENTRY),
            GraphNode("tool_x", NodeKind.TOOL, tools=("X",), **node_kwargs),
            GraphNode("exit", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("entry", "tool_x", **edge_kwargs),
            GraphEdge("tool_x", "exit", **edge_kwargs),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )


def test_witness_confidence_exact_when_all_exact():
    """Witness confidence is "exact" when every edge on the witness path
    has confidence "exact" and the TOOL nodes' bindings are exact: the
    bad-prefix path entry -> tool_x traverses only exact provenance."""
    graph = _forbidden_witness_graph(
        edge_kwargs={"origin": "runtime", "confidence": "exact"},
        node_kwargs={"origin": "runtime", "confidence": "exact"},
    )
    result = check_temporal_property(graph, _rule("no_X", "G !tool:X"))
    assert result["verdict"] == "may_violate"
    assert result["violation_path"] == ["entry", "tool_x"]
    assert result["witness_confidence"] == "exact"


def test_witness_confidence_may_with_synthesized_edge():
    """Witness confidence degrades to "may" when the witness path uses a
    synthesized/heuristic edge, even if the tool binding itself is exact."""
    graph = _forbidden_witness_graph(
        edge_kwargs={"origin": "synthesized", "confidence": "heuristic"},
        node_kwargs={"origin": "runtime", "confidence": "exact"},
    )
    result = check_temporal_property(graph, _rule("no_X", "G !tool:X"))
    assert result["verdict"] == "may_violate"
    assert result["violation_path"] == ["entry", "tool_x"]
    assert result["witness_confidence"] == "may"


def test_product_state_count():
    """Product states explored stay bounded by |nodes| * |DFA states|."""
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

    # G !tool:X compiles to a 2-state DFA; graph has 3 nodes => <=6 product states
    result = check_temporal_property(graph, _rule("no_X", "G !tool:X"))
    assert result["verdict"] == "safe"
    assert result["violated"] is False
    assert result["product_states_explored"] <= 3 * 2


# ---------------------------------------------------------------------------
# Static/runtime event-model agreement (Findings 1 and 2, 2026-07 audit)
# ---------------------------------------------------------------------------


def _toolless_tool_node_graph() -> AgentGraph:
    """A single TOOL node with NO declared tools; entry == exit."""
    return AgentGraph(
        name="toolless",
        framework="manual",
        nodes=(GraphNode(id="n0", kind=NodeKind.TOOL, tools=()),),
        edges=(),
        entry_id="n0",
        exit_ids=("n0",),
    )


def test_toolless_tool_node_static_runtime_agreement_via_verify():
    """Finding 1 regression (end-to-end via verify()): a TOOL node with NO
    declared tools. api._event_for_node emits {'action_type': 'tool'} for
    every visit of such a node, so a trace generated from the graph
    violates 'G !action:tool' at runtime. The static closure must consider
    that same bare visit event (superset invariant), yielding
    'may_violate' — before the fix it treated the node as event-free and
    returned 'safe', contradicting the runtime verdict inside a single
    verify() call.
    """
    graph = _toolless_tool_node_graph()
    rule = MonitorRuleSpec(
        rule_id="no_tool_actions", dsl="G !action:tool", on_violation="block"
    )
    trace = generate_traces(graph, n_traces=1, max_steps=5, seed=0)[0]
    report = verify(
        graph, monitor_rules=[rule], event_trace=trace, static_temporal=True
    )

    static = report["static_temporal"][0]
    assert static["verdict"] == "may_violate"
    assert static["violated"] is True
    assert static["violation_kind"] == "bad_prefix"
    assert static["violation_path"] == ["n0"]
    assert static["graph_warnings"] == []
    # Runtime monitoring on the API's own generated trace agrees.
    assert report["monitor"]["violations"], "expected runtime violation"


def test_toolless_tool_node_bare_event_does_not_match_tool_predicates():
    """Counterpart to the Finding 1 fix: the bare visit event of a
    tool-less TOOL node carries no tool_name, so a tool:NAME policy is NOT
    flagged — the conservative expansion must not over-approximate beyond
    what api._event_for_node can emit."""
    result = check_temporal_property(
        _toolless_tool_node_graph(), _rule("no_X", "G !tool:X")
    )
    assert result["verdict"] == "safe"
    assert result["violated"] is False


def _duplicate_id_graph() -> AgentGraph:
    """Malformed graph: two nodes share id 'x'; the FIRST declares
    drop_table, the second declares nothing."""
    return AgentGraph(
        name="dup",
        framework="manual",
        nodes=(
            GraphNode(id="x", kind=NodeKind.TOOL, tools=("drop_table",)),
            GraphNode(id="x", kind=NodeKind.TOOL, tools=()),  # duplicate id
            GraphNode(id="out", kind=NodeKind.PASSTHROUGH),
        ),
        edges=(GraphEdge(source="x", target="out"),),
        entry_id="x",
        exit_ids=("out",),
    )


def test_duplicate_node_ids_first_wins_and_warned():
    """Finding 2 regression: duplicate node ids must resolve FIRST-wins in
    the static checker, consistent with graph.model.node_by_id (used by
    api._event_for_node). Before the fix the checker resolved last-wins,
    so this graph got static 'safe' while the API's own trace invoked
    drop_table. Now both sides see the drop_table binding => static
    may_violate + runtime violation, and the duplicate ids are surfaced as
    verdict-independent metadata in graph_warnings.
    """
    graph = _duplicate_id_graph()
    rule = MonitorRuleSpec(
        rule_id="no_drop", dsl="G !tool:drop_table", on_violation="halt"
    )
    trace = generate_traces(graph, n_traces=1, max_steps=5, seed=0)[0]
    report = verify(
        graph, monitor_rules=[rule], event_trace=trace, static_temporal=True
    )

    static = report["static_temporal"][0]
    assert static["verdict"] == "may_violate"
    assert static["violated"] is True
    assert static["violation_kind"] == "bad_prefix"
    assert static["violation_path"] == ["x"]
    assert static["graph_warnings"] == ["duplicate_node_ids: ['x']"]
    # Runtime monitoring on the API's own generated trace agrees.
    assert report["monitor"]["violations"], "expected runtime violation"


def test_duplicate_node_ids_warning_is_verdict_independent():
    """graph_warnings reports duplicates even when the verdict is safe:
    it is metadata about graph well-formedness, not about the policy."""
    result = check_temporal_property(
        _duplicate_id_graph(), _rule("no_X", "G !tool:X")
    )
    assert result["verdict"] == "safe"
    assert result["graph_warnings"] == ["duplicate_node_ids: ['x']"]
