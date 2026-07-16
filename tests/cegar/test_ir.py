"""Unit + property tests for the may/must IR (Paper 2, plan §7, §11).

Covers the abstract-value lattice soundness (concretization-based
``contains`` / ``join`` / ``leq`` monotonicity via exhaustive enumeration),
``MayMustGraph`` serialization round-trips, the ``region_is_certifiable``
SAFE gate, and that the flat-``AgentGraph`` lift preserves (never drops)
unsupported facts / uncertainty.
"""

from __future__ import annotations

import itertools

import pytest

from agentproof.cegar.ir import (
    AbstractValue,
    AVKind,
    ControlKind,
    EffectKind,
    EffectNode,
    MayMustGraph,
    ModalEdge,
    Modality,
    Provenance,
    ToolSchema,
    UnsupportedFact,
    UnsupportedKind,
    region_is_certifiable,
)
from agentproof.graph.model import (
    AgentGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)


# ---------------------------------------------------------------------------
# Shared pools for the lattice property tests
# ---------------------------------------------------------------------------

def _av_pool() -> list[AbstractValue]:
    """A finite, representative pool of abstract values covering every kind."""
    return [
        AbstractValue.top(),
        AbstractValue.bottom(),
        AbstractValue.const(0),
        AbstractValue.const(1),
        AbstractValue.const(5),
        AbstractValue.const("x"),
        AbstractValue.const(True),
        AbstractValue.one_of([1, 2]),
        AbstractValue.one_of([0, 5]),
        AbstractValue.one_of(["x", "y"]),
        AbstractValue.one_of([1, 2, 3]),
        AbstractValue.interval(0, 5),
        AbstractValue.interval(1, 3),
        AbstractValue.interval(-1, 10),
        AbstractValue.interval(2, 2),
    ]


_CONCRETES = [0, 1, 2, 3, 5, -1, 10, "x", "y", True, False]


# ---------------------------------------------------------------------------
# AbstractValue lattice soundness (concretization semantics)
# ---------------------------------------------------------------------------

def test_join_is_sound_over_approximation():
    """gamma(a) ∪ gamma(b) ⊆ gamma(a.join(b)) for every pair, concretely."""
    pool = _av_pool()
    for a, b in itertools.product(pool, repeat=2):
        j = a.join(b)
        for c in _CONCRETES:
            if a.contains(c) or b.contains(c):
                assert j.contains(c), (a.to_dict(), b.to_dict(), c)


def test_leq_is_sound_subset():
    """a.leq(b) implies gamma(a) ⊆ gamma(b) (soundness; may be incomplete)."""
    pool = _av_pool()
    for a, b in itertools.product(pool, repeat=2):
        if a.leq(b):
            for c in _CONCRETES:
                if a.contains(c):
                    assert b.contains(c), (a.to_dict(), b.to_dict(), c)


def test_leq_reflexive():
    for a in _av_pool():
        assert a.leq(a), a.to_dict()


def test_join_is_upper_bound():
    """Both operands are ≤ their join (the join really is an upper bound)."""
    pool = _av_pool()
    for a, b in itertools.product(pool, repeat=2):
        j = a.join(b)
        assert a.leq(j), (a.to_dict(), b.to_dict())
        assert b.leq(j), (a.to_dict(), b.to_dict())


def test_join_is_commutative_semantically():
    """a.join(b) and b.join(a) have the same concretization."""
    pool = _av_pool()
    for a, b in itertools.product(pool, repeat=2):
        ab, ba = a.join(b), b.join(a)
        for c in _CONCRETES:
            assert ab.contains(c) == ba.contains(c), (a.to_dict(), b.to_dict(), c)


def test_bottom_is_least_top_is_greatest():
    bottom = AbstractValue.bottom()
    top = AbstractValue.top()
    for a in _av_pool():
        assert bottom.leq(a), a.to_dict()
        assert a.leq(top), a.to_dict()
    assert not any(top.contains(c) is False for c in _CONCRETES)
    assert not any(bottom.contains(c) for c in _CONCRETES)


def test_abstractvalue_roundtrip():
    for a in _av_pool():
        restored = AbstractValue.from_dict(a.to_dict())
        for c in _CONCRETES:
            assert restored.contains(c) == a.contains(c), (a.to_dict(), c)


def test_one_of_collapses_and_empties():
    assert AbstractValue.one_of([]).is_bottom
    single = AbstractValue.one_of([7])
    assert single.kind is AVKind.CONST and single.value == 7
    assert AbstractValue.interval(5, 1).is_bottom  # lo > hi


# ---------------------------------------------------------------------------
# MayMustGraph round-trip
# ---------------------------------------------------------------------------

def _rich_graph() -> MayMustGraph:
    exact = Provenance("ast_explicit", "exact", "f.py:1:2")
    mayp = Provenance("ast_inferred", "may", "f.py:3:4")
    schema = ToolSchema(
        name="wire_transfer",
        params=(),
        effect=EffectKind.FINANCIAL,
        authority_required="finance",
        reversible=False,
        complete=True,
    )
    nodes = (
        EffectNode(id="entry", provenance=exact, modeling_confidence="exact",
                   state_predicates=("kind:entry",)),
        EffectNode(
            id="pay", effect=EffectKind.FINANCIAL, tool="wire_transfer",
            tool_schema=schema,
            abstract_args=(("amount", AbstractValue.interval(0, 100)),
                           ("to", AbstractValue.const("acct"))),
            authority="finance", identity="user", capability="invokes_tool",
            in_labels=("pii",), out_labels=("receipt",),
            guards=("amount>0",), possible_exceptions=("Timeout",),
            provenance=mayp, modeling_confidence="may",
            state_predicates=("kind:tool",),
            unsupported=(UnsupportedFact(UnsupportedKind.INCOMPLETE_SCHEMA, "x"),),
        ),
        EffectNode(id="exit", provenance=exact, modeling_confidence="exact",
                   state_predicates=("kind:exit",)),
    )
    edges = (
        ModalEdge("entry", "pay", modality=Modality.MUST, control=ControlKind.DIRECT,
                  provenance=exact),
        ModalEdge("pay", "exit", modality=Modality.MAY, control=ControlKind.CONDITIONAL,
                  guard="ok", provenance=mayp,
                  unsupported=(UnsupportedFact(UnsupportedKind.UNKNOWN_DISPATCH, "d"),)),
    )
    return MayMustGraph(
        name="rich", framework="langgraph", nodes=nodes, edges=edges,
        entry_id="entry", exit_ids=("exit",),
        unsupported=(UnsupportedFact(UnsupportedKind.GUESSED_STRUCTURE, "g"),),
    )


def test_graph_dict_roundtrip_is_exact():
    g = _rich_graph()
    restored = MayMustGraph.from_dict(g.to_dict())
    assert restored == g


def test_graph_dict_roundtrip_json_stable():
    import json

    g = _rich_graph()
    once = json.dumps(g.to_dict(), sort_keys=True)
    twice = json.dumps(MayMustGraph.from_dict(g.to_dict()).to_dict(), sort_keys=True)
    assert once == twice


def test_graph_lookups():
    g = _rich_graph()
    assert g.node_by_id("pay") is not None
    assert g.node_by_id("nope") is None
    assert g.successors("entry") == ("pay",)
    assert g.successors("entry", modality=Modality.MUST) == ("pay",)
    assert g.successors("entry", modality=Modality.MAY) == ()
    assert g.predecessors("pay") == ("entry",)
    assert {u.kind for u in g.all_unsupported()} == {
        UnsupportedKind.GUESSED_STRUCTURE,
        UnsupportedKind.INCOMPLETE_SCHEMA,
        UnsupportedKind.UNKNOWN_DISPATCH,
    }


def test_with_node_and_with_edges():
    g = _rich_graph()
    exact = Provenance("ast_explicit", "exact", "f:9:9")
    replacement = EffectNode(id="pay", effect=EffectKind.NONE, provenance=exact,
                             modeling_confidence="exact")
    g2 = g.with_node(replacement)
    assert g2.node_by_id("pay").effect is EffectKind.NONE
    assert len(g2.nodes) == len(g.nodes)  # replaced, not appended
    appended = EffectNode(id="brand_new", provenance=exact, modeling_confidence="exact")
    g3 = g.with_node(appended)
    assert len(g3.nodes) == len(g.nodes) + 1
    g4 = g.with_edges(())
    assert g4.edges == ()


# ---------------------------------------------------------------------------
# region_is_certifiable: the SAFE gate
# ---------------------------------------------------------------------------

def _certifiable_line() -> MayMustGraph:
    exact = Provenance("ast_explicit", "exact", "f:1:1")
    nodes = (
        EffectNode(id="a", provenance=exact, modeling_confidence="exact"),
        EffectNode(id="b", provenance=exact, modeling_confidence="exact"),
    )
    edges = (ModalEdge("a", "b", modality=Modality.MUST, provenance=exact),)
    return MayMustGraph("g", "t", nodes, edges, entry_id="a", exit_ids=("b",))


def test_region_certifiable_when_all_exact():
    g = _certifiable_line()
    assert region_is_certifiable(g, ("a", "b"), (("a", "b"),))


def test_non_exact_node_breaks_certification():
    g = _certifiable_line()
    mayp = Provenance("ast_inferred", "may")
    g2 = g.with_node(EffectNode(id="b", provenance=mayp, modeling_confidence="may"))
    assert not region_is_certifiable(g2, ("a", "b"), (("a", "b"),))


def test_unsupported_node_breaks_certification():
    g = _certifiable_line()
    exact = Provenance("ast_explicit", "exact")
    bad = EffectNode(
        id="b", provenance=exact, modeling_confidence="exact",
        unsupported=(UnsupportedFact(UnsupportedKind.REFLECTION, "getattr"),),
    )
    g2 = g.with_node(bad)
    assert not region_is_certifiable(g2, ("a", "b"), (("a", "b"),))


def test_non_exact_edge_breaks_certification():
    exact = Provenance("ast_explicit", "exact")
    mayp = Provenance("ast_inferred", "may")
    nodes = (
        EffectNode(id="a", provenance=exact, modeling_confidence="exact"),
        EffectNode(id="b", provenance=exact, modeling_confidence="exact"),
    )
    edges = (ModalEdge("a", "b", modality=Modality.MAY, provenance=mayp),)
    g = MayMustGraph("g", "t", nodes, edges, entry_id="a", exit_ids=("b",))
    assert not region_is_certifiable(g, ("a", "b"), (("a", "b"),))


def test_graph_level_unsupported_breaks_certification():
    g = _certifiable_line()
    from dataclasses import replace as dc_replace

    g2 = dc_replace(g, unsupported=(UnsupportedFact(UnsupportedKind.NATIVE_EXTENSION, "c"),))
    assert not region_is_certifiable(g2, ("a", "b"), (("a", "b"),))


def test_assume_trace_conservative_overrides_gate():
    g = _certifiable_line()
    mayp = Provenance("ast_inferred", "may")
    g2 = g.with_node(EffectNode(id="b", provenance=mayp, modeling_confidence="may"))
    # Without the assertion: not certifiable; with it: unconditionally certifiable.
    assert not region_is_certifiable(g2, ("a", "b"), (("a", "b"),))
    assert region_is_certifiable(g2, ("a", "b"), (("a", "b"),),
                                 assume_trace_conservative=True)


def test_missing_node_is_not_certifiable():
    g = _certifiable_line()
    assert not region_is_certifiable(g, ("a", "ghost"), ())


def test_missing_edge_is_not_certifiable():
    g = _certifiable_line()
    assert not region_is_certifiable(g, ("a", "b"), (("a", "ghost"),))


# ---------------------------------------------------------------------------
# EffectNode / ModalEdge certifiability predicate
# ---------------------------------------------------------------------------

def test_node_is_certifiable_requires_exact_and_no_unsupported():
    exact = Provenance("ast_explicit", "exact")
    assert EffectNode(id="n", provenance=exact, modeling_confidence="exact").is_certifiable
    assert not EffectNode(id="n", provenance=Provenance("ast_inferred", "may")).is_certifiable
    assert not EffectNode(
        id="n", provenance=exact,
        unsupported=(UnsupportedFact(UnsupportedKind.CALLBACK, "cb"),),
    ).is_certifiable


# ---------------------------------------------------------------------------
# Flat-graph lift preserves uncertainty (never silently drops it)
# ---------------------------------------------------------------------------

def test_flat_lift_records_guessed_structure_for_non_exact():
    flat = AgentGraph(
        name="f", framework="langgraph",
        nodes=(
            GraphNode("s", NodeKind.ENTRY, origin="runtime", confidence="exact"),
            GraphNode("g", NodeKind.PASSTHROUGH, origin="ast_inferred", confidence="may"),
            GraphNode("e", NodeKind.EXIT, origin="runtime", confidence="exact"),
        ),
        edges=(
            GraphEdge("s", "g", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
            GraphEdge("g", "e", EdgeKind.DIRECT, origin="ast_inferred", confidence="may"),
        ),
        entry_id="s", exit_ids=("e",),
    )
    mm = MayMustGraph.from_agent_graph(flat)
    guessed = mm.node_by_id("g")
    assert any(u.kind is UnsupportedKind.GUESSED_STRUCTURE for u in guessed.unsupported)
    assert not guessed.is_certifiable
    # the non-exact edge also carries a guessed-structure fact
    weak_edges = [e for e in mm.edges if e.source == "g"]
    assert any(u.kind is UnsupportedKind.GUESSED_STRUCTURE
               for e in weak_edges for u in e.unsupported)


def test_flat_lift_tool_node_incomplete_schema():
    flat = AgentGraph(
        name="f", framework="langgraph",
        nodes=(
            GraphNode("s", NodeKind.ENTRY, origin="runtime", confidence="exact"),
            GraphNode("t", NodeKind.TOOL, tools=("mystery",), origin="runtime",
                      confidence="exact", capabilities=("invokes_tool",)),
            GraphNode("e", NodeKind.EXIT, origin="runtime", confidence="exact"),
        ),
        edges=(
            GraphEdge("s", "t", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
            GraphEdge("t", "e", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
        ),
        entry_id="s", exit_ids=("e",),
    )
    mm = MayMustGraph.from_agent_graph(flat)
    t = mm.node_by_id("t")
    # A bound tool with an unresolved effect must carry INCOMPLETE_SCHEMA and be
    # non-certifiable — uncertainty is never silently dropped.
    assert t.effect is EffectKind.UNKNOWN
    assert any(u.kind is UnsupportedKind.INCOMPLETE_SCHEMA for u in t.unsupported)
    assert not t.is_certifiable


def test_flat_lift_subgraph_is_nested_agent():
    flat = AgentGraph(
        name="f", framework="langgraph",
        nodes=(
            GraphNode("s", NodeKind.ENTRY, origin="runtime", confidence="exact"),
            GraphNode("sub", NodeKind.SUBGRAPH, origin="runtime", confidence="exact"),
            GraphNode("e", NodeKind.EXIT, origin="runtime", confidence="exact"),
        ),
        edges=(
            GraphEdge("s", "sub", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
            GraphEdge("sub", "e", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
        ),
        entry_id="s", exit_ids=("e",),
    )
    mm = MayMustGraph.from_agent_graph(flat)
    sub = mm.node_by_id("sub")
    assert any(u.kind is UnsupportedKind.NESTED_AGENT for u in sub.unsupported)
    assert not sub.is_certifiable


def test_flat_lift_modality_assignment():
    """Sole DIRECT successor -> MUST; multi-successor/branch -> MAY; unknown -> UNKNOWN."""
    flat = AgentGraph(
        name="f", framework="langgraph",
        nodes=(
            GraphNode("s", NodeKind.ENTRY, origin="runtime", confidence="exact"),
            GraphNode("r", NodeKind.ROUTER, origin="runtime", confidence="exact",
                      capabilities=("routes",)),
            GraphNode("a", NodeKind.PASSTHROUGH, origin="runtime", confidence="exact"),
            GraphNode("b", NodeKind.PASSTHROUGH, origin="runtime", confidence="exact"),
            GraphNode("e", NodeKind.EXIT, origin="runtime", confidence="exact"),
        ),
        edges=(
            GraphEdge("s", "r", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
            GraphEdge("r", "a", EdgeKind.CONDITIONAL, origin="runtime", confidence="exact"),
            GraphEdge("r", "b", EdgeKind.CONDITIONAL, origin="runtime", confidence="exact"),
            GraphEdge("a", "e", EdgeKind.DIRECT, origin="unknown", confidence="may"),
            GraphEdge("b", "e", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
        ),
        entry_id="s", exit_ids=("e",),
    )
    mm = MayMustGraph.from_agent_graph(flat)
    by = {(e.source, e.target): e for e in mm.edges}
    assert by[("s", "r")].modality is Modality.MUST     # sole direct successor
    assert by[("r", "a")].modality is Modality.MAY       # conditional branch
    assert by[("b", "e")].modality is Modality.MUST      # sole direct successor
    assert by[("a", "e")].modality is Modality.UNKNOWN   # unknown origin


def test_flat_lift_then_project_back_preserves_topology():
    g = _certifiable_line()
    flat = g.to_agent_graph()
    assert {n.id for n in flat.nodes} == {n.id for n in g.nodes}
    assert {(e.source, e.target) for e in flat.edges} == {
        (e.source, e.target) for e in g.edges
    }
