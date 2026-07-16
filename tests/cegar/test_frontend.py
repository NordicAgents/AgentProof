"""LangGraph front-end lift (Paper 2, plan §4.2, §7).

Asserts the front-end resolves tool effects from schemas (dropping the
INCOMPLETE_SCHEMA placeholder), flags SUBGRAPH nodes as NESTED_AGENT, marks
dynamic / unknown-origin edges UNKNOWN_DISPATCH, flags unresolved parallel
fan-outs, and — the throughline — NEVER drops uncertainty: any construct it
cannot model precisely leaves an explicit UnsupportedFact that keeps the region
non-certifiable.
"""

from __future__ import annotations

from agentproof.cegar.frontend import default_tool_schemas, extract_and_lift, lift
from agentproof.cegar.ir import (
    EffectKind,
    ToolSchema,
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


def _flat(nodes, edges, entry="__start__", exits=("__end__",), name="f"):
    return AgentGraph(name=name, framework="langgraph", nodes=nodes, edges=edges,
                      entry_id=entry, exit_ids=exits)


# ---------------------------------------------------------------------------
# Tool schema resolution
# ---------------------------------------------------------------------------

def test_lift_resolves_tool_effect_from_schema():
    flat = _flat(
        nodes=(
            GraphNode("__start__", NodeKind.ENTRY, origin="runtime", confidence="exact"),
            GraphNode("pay", NodeKind.TOOL, tools=("wire_transfer",), origin="runtime",
                      confidence="exact", capabilities=("invokes_tool",)),
            GraphNode("__end__", NodeKind.EXIT, origin="runtime", confidence="exact"),
        ),
        edges=(
            GraphEdge("__start__", "pay", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
            GraphEdge("pay", "__end__", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
        ),
    )
    mm = lift(flat, tool_schemas=default_tool_schemas())
    pay = mm.node_by_id("pay")
    assert pay.effect is EffectKind.FINANCIAL
    assert pay.tool_schema is not None and not pay.tool_schema.reversible
    assert pay.authority == "finance"  # imported from the schema
    assert not any(u.kind is UnsupportedKind.INCOMPLETE_SCHEMA for u in pay.unsupported)
    assert pay.is_certifiable
    assert region_is_certifiable(mm, ("pay",),
                                 (("__start__", "pay"), ("pay", "__end__")))


def test_lift_incomplete_schema_keeps_uncertainty():
    schemas = {"myt": ToolSchema(name="myt", effect=EffectKind.UNKNOWN, complete=False)}
    flat = _flat(
        nodes=(
            GraphNode("__start__", NodeKind.ENTRY, origin="runtime", confidence="exact"),
            GraphNode("t", NodeKind.TOOL, tools=("myt",), origin="runtime",
                      confidence="exact", capabilities=("invokes_tool",)),
            GraphNode("__end__", NodeKind.EXIT, origin="runtime", confidence="exact"),
        ),
        edges=(
            GraphEdge("__start__", "t", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
            GraphEdge("t", "__end__", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
        ),
    )
    mm = lift(flat, tool_schemas=schemas)
    t = mm.node_by_id("t")
    assert t.tool_schema is not None
    assert any(u.kind is UnsupportedKind.INCOMPLETE_SCHEMA for u in t.unsupported)
    assert not t.is_certifiable  # uncertainty is never silently dropped


def test_lift_unknown_tool_keeps_incomplete_schema():
    """A bound tool with no schema stays INCOMPLETE_SCHEMA / non-certifiable."""
    flat = _flat(
        nodes=(
            GraphNode("__start__", NodeKind.ENTRY, origin="runtime", confidence="exact"),
            GraphNode("t", NodeKind.TOOL, tools=("nowhere",), origin="runtime",
                      confidence="exact", capabilities=("invokes_tool",)),
            GraphNode("__end__", NodeKind.EXIT, origin="runtime", confidence="exact"),
        ),
        edges=(
            GraphEdge("__start__", "t", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
            GraphEdge("t", "__end__", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
        ),
    )
    mm = lift(flat, tool_schemas={})  # no schema for "nowhere"
    t = mm.node_by_id("t")
    assert t.effect is EffectKind.UNKNOWN
    assert any(u.kind is UnsupportedKind.INCOMPLETE_SCHEMA for u in t.unsupported)
    assert not t.is_certifiable


# ---------------------------------------------------------------------------
# SUBGRAPH -> NESTED_AGENT
# ---------------------------------------------------------------------------

def test_subgraph_is_nested_agent_and_not_certifiable():
    flat = _flat(
        nodes=(
            GraphNode("__start__", NodeKind.ENTRY, origin="runtime", confidence="exact"),
            GraphNode("sub", NodeKind.SUBGRAPH, origin="runtime", confidence="exact",
                      capabilities=("subgraph",)),
            GraphNode("__end__", NodeKind.EXIT, origin="runtime", confidence="exact"),
        ),
        edges=(
            GraphEdge("__start__", "sub", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
            GraphEdge("sub", "__end__", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
        ),
    )
    mm = lift(flat)
    sub = mm.node_by_id("sub")
    assert any(u.kind is UnsupportedKind.NESTED_AGENT for u in sub.unsupported)
    assert not sub.is_certifiable
    assert not region_is_certifiable(mm, ("sub",), ())


# ---------------------------------------------------------------------------
# Dynamic / unknown edges -> UNKNOWN_DISPATCH
# ---------------------------------------------------------------------------

def test_unknown_origin_edge_is_unknown_dispatch():
    flat = _flat(
        nodes=(
            GraphNode("__start__", NodeKind.ENTRY, origin="runtime", confidence="exact"),
            GraphNode("route", NodeKind.ROUTER, origin="runtime", confidence="exact",
                      capabilities=("routes",)),
            GraphNode("__end__", NodeKind.EXIT, origin="runtime", confidence="exact"),
        ),
        edges=(
            GraphEdge("__start__", "route", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
            GraphEdge("route", "__end__", EdgeKind.DIRECT, origin="unknown", confidence="may"),
        ),
    )
    mm = lift(flat)
    route_out = [e for e in mm.edges if e.source == "route"]
    assert route_out
    assert any(u.kind is UnsupportedKind.UNKNOWN_DISPATCH
               for e in route_out for u in e.unsupported)
    assert not all(e.is_certifiable for e in route_out)


# ---------------------------------------------------------------------------
# Unresolved parallel fan-out
# ---------------------------------------------------------------------------

def _parallel(join: bool):
    nodes = [
        GraphNode("s", NodeKind.ENTRY, origin="runtime", confidence="exact"),
        GraphNode("a", NodeKind.PASSTHROUGH, origin="runtime", confidence="exact"),
        GraphNode("b", NodeKind.PASSTHROUGH, origin="runtime", confidence="exact"),
    ]
    edges = [
        GraphEdge("s", "a", EdgeKind.PARALLEL, origin="runtime", confidence="exact"),
        GraphEdge("s", "b", EdgeKind.PARALLEL, origin="runtime", confidence="exact"),
    ]
    if join:
        nodes += [
            GraphNode("j", NodeKind.PASSTHROUGH, origin="runtime", confidence="exact"),
            GraphNode("e", NodeKind.EXIT, origin="runtime", confidence="exact"),
        ]
        edges += [
            GraphEdge("a", "j", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
            GraphEdge("b", "j", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
            GraphEdge("j", "e", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
        ]
        exits = ("e",)
    else:
        nodes += [
            GraphNode("x", NodeKind.EXIT, origin="runtime", confidence="exact"),
            GraphNode("y", NodeKind.EXIT, origin="runtime", confidence="exact"),
        ]
        edges += [
            GraphEdge("a", "x", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
            GraphEdge("b", "y", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
        ]
        exits = ("x", "y")
    return lift(_flat(tuple(nodes), tuple(edges), entry="s", exits=exits, name="par"))


def test_parallel_without_join_is_unresolved():
    disjoint = _parallel(join=False).node_by_id("s")
    assert any(u.kind is UnsupportedKind.UNRESOLVED_PARALLEL for u in disjoint.unsupported)


def test_parallel_with_join_is_not_flagged():
    joined = _parallel(join=True).node_by_id("s")
    assert not any(u.kind is UnsupportedKind.UNRESOLVED_PARALLEL for u in joined.unsupported)


# ---------------------------------------------------------------------------
# Uncertainty is never dropped (guessed structure survives)
# ---------------------------------------------------------------------------

def test_non_exact_node_keeps_guessed_structure():
    flat = _flat(
        nodes=(
            GraphNode("__start__", NodeKind.ENTRY, origin="runtime", confidence="exact"),
            GraphNode("g", NodeKind.PASSTHROUGH, origin="ast_inferred", confidence="may"),
            GraphNode("__end__", NodeKind.EXIT, origin="runtime", confidence="exact"),
        ),
        edges=(
            GraphEdge("__start__", "g", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
            GraphEdge("g", "__end__", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
        ),
    )
    mm = lift(flat)
    g = mm.node_by_id("g")
    assert any(u.kind is UnsupportedKind.GUESSED_STRUCTURE for u in g.unsupported)
    assert not g.is_certifiable


# ---------------------------------------------------------------------------
# extract_and_lift gracefully degrades without the framework
# ---------------------------------------------------------------------------

def test_extract_and_lift_without_framework_raises_runtimeerror():
    """When langgraph is absent the ImportError is wrapped as a clear RuntimeError
    (never a leaked bare ImportError)."""
    try:
        import langgraph  # noqa: F401
        installed = True
    except ImportError:
        installed = False

    if installed:
        return  # extractor may succeed/fail differently when installed; not our contract

    import pytest

    with pytest.raises(RuntimeError):
        extract_and_lift("graph = None")
