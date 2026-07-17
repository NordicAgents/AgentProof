"""Regression tests for the flat-AgentGraph -> may/must IR lift.

Both bugs guarded here were found by running the analyzer on the 912 real mined
workflows: on a lifted graph, ``Approval()`` silently never matched, because
(1) ``state_predicates`` was built as ``tuple("kind:...")`` — a tuple of single
characters — and (2) lifted nodes inherited no ``capability`` from their
NodeKind. Together those made human-approval nodes invisible, inflating the
"UNSAFE candidate" counts on real data.
"""

from __future__ import annotations

from agentproof.graph.model import AgentGraph, EdgeKind, GraphEdge, GraphNode, NodeKind
from agentproof.cegar.ir import EffectKind, MayMustGraph
from agentproof.cegar.policy import Action, Approval, Capability


def _exact(node_id, kind, **kw):
    return GraphNode(node_id, kind, origin="ast_explicit", confidence="exact", **kw)


def _lift_human_router_graph() -> MayMustGraph:
    g = AgentGraph(
        name="t", framework="langgraph",
        nodes=(
            _exact("e", NodeKind.ENTRY),
            _exact("h", NodeKind.HUMAN),
            _exact("r", NodeKind.ROUTER),
            _exact("z", NodeKind.EXIT),
        ),
        edges=(
            GraphEdge("e", "h", EdgeKind.DIRECT, origin="ast_explicit", confidence="exact"),
            GraphEdge("h", "r", EdgeKind.DIRECT, origin="ast_explicit", confidence="exact"),
            GraphEdge("r", "z", EdgeKind.CONDITIONAL, origin="ast_explicit", confidence="exact"),
        ),
        entry_id="e", exit_ids=("z",),
    )
    return MayMustGraph.from_agent_graph(g)


def test_state_predicates_is_single_kind_predicate_not_char_tuple():
    mm = _lift_human_router_graph()
    human = mm.node_by_id("h")
    # Exactly one predicate, "kind:human" — not ('k','i','n','d',':', ...).
    assert human.state_predicates == ("kind:human",)
    assert all(len(sp) > 1 for sp in human.state_predicates)


def test_lifted_kind_confers_capability():
    mm = _lift_human_router_graph()
    assert "human_pause" in mm.node_by_id("h").capability
    assert "routes" in mm.node_by_id("r").capability


def test_approval_and_action_predicates_match_lifted_nodes():
    mm = _lift_human_router_graph()
    human, router = mm.node_by_id("h"), mm.node_by_id("r")
    # Approval must see the lifted HUMAN node (via either capability or kind).
    assert Approval().abstract_eval(human) == (True, True)
    assert Approval().abstract_eval(router) == (False, False)
    # Action("human") / Action("router") must match the right lifted nodes.
    assert Action("human").abstract_eval(human) == (True, True)
    assert Action("router").abstract_eval(router) == (True, True)
    assert Action("router").abstract_eval(human) == (False, False)
    # Capability predicate works off the derived capability.
    assert Capability("routes").abstract_eval(router) == (True, True)
