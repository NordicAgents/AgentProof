"""LangGraph semantic front-end for AgentProof-CEGAR (plan §4.2).

This module turns a LangGraph agent program into a provenance-carrying
:class:`~agentproof.cegar.ir.MayMustGraph` that is *richer* than the plain
:meth:`MayMustGraph.from_agent_graph` compatibility lift. It starts from that
lift and then **enriches** it with framework-aware knowledge while keeping every
scrap of uncertainty visible:

* **Tool resolution.** When a :class:`~agentproof.cegar.ir.ToolSchema` is known
  for a bound tool, the front-end attaches the schema to the TOOL node, resolves
  the node's :class:`~agentproof.cegar.ir.EffectKind` from it, imports the
  authority the tool demands, and *removes* the placeholder
  ``INCOMPLETE_SCHEMA`` unsupported fact — the effect is now known.

* **Conservative unsupported facts.** Constructs the front-end cannot model
  precisely are recorded as explicit
  :class:`~agentproof.cegar.ir.UnsupportedFact` s rather than silently dropped
  (plan §2.3, §4.1):

  ``UNKNOWN_DISPATCH``
      dynamic-dispatch edges — :class:`ControlKind.DYNAMIC` or edges whose
      provenance origin is ``"unknown"`` (target resolved at runtime).
  ``NESTED_AGENT``
      :class:`NodeKind.SUBGRAPH` nodes — an unmediated sub-agent.
  ``UNRESOLVED_PARALLEL``
      a parallel fan-out whose branches share no common join descendant, so the
      interleaving / reconvergence is not statically resolved.
  ``GUESSED_STRUCTURE``
      any node/edge whose confidence is not ``exact`` (kind/binding guessed).

  ``GUESSED_STRUCTURE`` and the base ``NESTED_AGENT`` / ``INCOMPLETE_SCHEMA``
  facts already originate in :meth:`MayMustGraph.from_agent_graph`; this
  front-end preserves them and adds the dispatch / parallel facts the flat lift
  does not compute.

Nothing is ever removed to make the graph "cleaner": the sole subtraction is the
``INCOMPLETE_SCHEMA`` fact once a complete schema actually resolves the effect.

The public surface is :func:`lift`, :func:`extract_and_lift`, and
:func:`default_tool_schemas`.
"""

from __future__ import annotations

from dataclasses import replace

from agentproof.cegar.ir import (
    ControlKind,
    EffectKind,
    EffectNode,
    MayMustGraph,
    ModalEdge,
    ParamSpec,
    ToolSchema,
    UnsupportedFact,
    UnsupportedKind,
)
from agentproof.graph.model import AgentGraph, GraphNode, NodeKind


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lift(
    graph: AgentGraph,
    *,
    tool_schemas: dict[str, ToolSchema] | None = None,
) -> MayMustGraph:
    """Lift a flat LangGraph :class:`AgentGraph` into an enriched may/must IR.

    The result is :meth:`MayMustGraph.from_agent_graph` refined with framework
    semantics: tool schemas resolve TOOL-node effects (dropping the
    ``INCOMPLETE_SCHEMA`` placeholder), and conservative
    :class:`UnsupportedFact` s are attached for constructs the front-end cannot
    model (dynamic dispatch, nested agents, unresolved parallelism, guessed
    structure). No node or edge is ever dropped — uncertainty stays visible.

    Parameters
    ----------
    graph:
        A flat :class:`AgentGraph` (typically from the LangGraph extractor, but
        any hand-built graph works — the smoke test relies on this).
    tool_schemas:
        Optional mapping ``tool_name -> ToolSchema``. When a bound tool is
        present here, its effect/authority/irreversibility are attached to the
        node. Absent tools keep their ``INCOMPLETE_SCHEMA`` fact.
    """
    schemas = dict(tool_schemas or {})
    base = MayMustGraph.from_agent_graph(graph)

    flat_by_id: dict[str, GraphNode] = {n.id: n for n in graph.nodes}

    nodes = tuple(
        _enrich_node(node, flat_by_id.get(node.id), schemas) for node in base.nodes
    )
    edges = tuple(_enrich_edge(edge) for edge in base.edges)

    enriched = replace(base, nodes=nodes, edges=edges)
    # Parallel-join resolution needs the whole (enriched) edge set.
    return _mark_unresolved_parallel(enriched)


def extract_and_lift(
    source: str,
    *,
    tool_schemas: dict[str, ToolSchema] | None = None,
) -> MayMustGraph:
    """Extract a LangGraph program from ``source`` and :func:`lift` it.

    Convenience wrapper that runs the existing LangGraph extractor on ``source``
    (which requires the ``langgraph`` framework installed) and then lifts the
    resulting flat graph. If the framework is unavailable the underlying
    ``ImportError`` is turned into a clear :class:`RuntimeError` instructing the
    caller to pass a pre-extracted :class:`AgentGraph` to :func:`lift` instead —
    :func:`lift` itself never needs the framework and works fully on a
    hand-built graph.
    """
    try:
        flat = _extract_from_source(source)
    except ImportError as exc:  # framework (or a dependency) not installed
        raise RuntimeError(
            "LangGraph is not installed, so the source-level extractor is "
            "unavailable. Build or extract an AgentGraph yourself and call "
            "agentproof.cegar.frontend.lift(graph, tool_schemas=...) directly; "
            "lift() does not require the framework."
        ) from exc
    return lift(flat, tool_schemas=tool_schemas)


def default_tool_schemas() -> dict[str, ToolSchema]:
    """A small library of common sensitive tool schemas.

    Usable by benchmark tasks and tests to resolve TOOL-node effects. Each
    schema is ``complete`` so that :func:`lift` can drop the
    ``INCOMPLETE_SCHEMA`` placeholder. Irreversible tools (financial / delete /
    execute / communicate) advertise ``reversible=False`` so downstream
    approval-before policies can key off it.
    """
    return {
        "wire_transfer": ToolSchema(
            name="wire_transfer",
            params=(
                ParamSpec("amount", type="float", sensitive=True),
                ParamSpec("recipient", type="str", sensitive=True),
                ParamSpec("account", type="str", sensitive=True),
            ),
            effect=EffectKind.FINANCIAL,
            authority_required="finance",
            reversible=False,
            complete=True,
        ),
        "place_trade": ToolSchema(
            name="place_trade",
            params=(
                ParamSpec("symbol", type="str", sensitive=True),
                ParamSpec("quantity", type="int", sensitive=True),
                ParamSpec("side", type="str", sensitive=True),
            ),
            effect=EffectKind.FINANCIAL,
            authority_required="trading",
            reversible=False,
            complete=True,
        ),
        "send_email": ToolSchema(
            name="send_email",
            params=(
                ParamSpec("to", type="str", sensitive=True),
                ParamSpec("subject", type="str"),
                ParamSpec("body", type="str", sensitive=True),
            ),
            effect=EffectKind.COMMUNICATE,
            authority_required="messaging",
            reversible=False,
            complete=True,
        ),
        "delete_record": ToolSchema(
            name="delete_record",
            params=(
                ParamSpec("table", type="str", sensitive=True),
                ParamSpec("record_id", type="str", sensitive=True),
            ),
            effect=EffectKind.DELETE,
            authority_required="admin",
            reversible=False,
            complete=True,
        ),
        "run_shell": ToolSchema(
            name="run_shell",
            params=(ParamSpec("command", type="str", sensitive=True),),
            effect=EffectKind.EXECUTE,
            authority_required="shell",
            reversible=False,
            complete=True,
        ),
        "read_database": ToolSchema(
            name="read_database",
            params=(ParamSpec("query", type="str"),),
            effect=EffectKind.READ,
            reversible=True,
            complete=True,
        ),
        "write_record": ToolSchema(
            name="write_record",
            params=(
                ParamSpec("table", type="str"),
                ParamSpec("payload", type="str"),
            ),
            effect=EffectKind.WRITE,
            authority_required="writer",
            reversible=True,
            complete=True,
        ),
    }


# ---------------------------------------------------------------------------
# Node enrichment
# ---------------------------------------------------------------------------

def _enrich_node(
    node: EffectNode,
    flat: GraphNode | None,
    schemas: dict[str, ToolSchema],
) -> EffectNode:
    """Attach schema-resolved effect/authority and conservative facts to a node.

    ``flat`` is the originating :class:`GraphNode` (or ``None`` if the node has
    no flat counterpart). We consult the flat descriptor directly for ``kind``,
    ``effects`` and ``capabilities`` rather than trusting the projected
    ``state_predicates`` string.
    """
    unsupported = list(node.unsupported)

    # -- tool schema resolution --------------------------------------------
    if node.tool and node.tool in schemas:
        schema = schemas[node.tool]
        node = replace(node, tool_schema=schema)
        if schema.authority_required and not node.authority:
            node = replace(node, authority=schema.authority_required)
        if schema.complete and schema.effect is not EffectKind.UNKNOWN:
            # Effect is now known: adopt it and retire the placeholder fact.
            node = replace(node, effect=schema.effect)
            unsupported = [
                u for u in unsupported if u.kind is not UnsupportedKind.INCOMPLETE_SCHEMA
            ]
        else:
            # Schema present but partial: keep the region non-certifiable.
            _ensure(
                unsupported,
                UnsupportedKind.INCOMPLETE_SCHEMA,
                detail=f"tool {node.tool} schema incomplete",
                source_span=node.provenance.source_span,
            )

    # -- nested agents (SUBGRAPH) ------------------------------------------
    if flat is not None and flat.kind is NodeKind.SUBGRAPH:
        _ensure(
            unsupported,
            UnsupportedKind.NESTED_AGENT,
            detail=f"subgraph node {node.id}",
            source_span=node.provenance.source_span,
        )

    if tuple(unsupported) != node.unsupported:
        node = replace(node, unsupported=tuple(unsupported))
    return node


# ---------------------------------------------------------------------------
# Edge enrichment
# ---------------------------------------------------------------------------

def _enrich_edge(edge: ModalEdge) -> ModalEdge:
    """Mark dynamic-dispatch edges with an ``UNKNOWN_DISPATCH`` fact.

    An edge is dynamic dispatch when its control shape is
    :class:`ControlKind.DYNAMIC` or its provenance origin is ``"unknown"`` (the
    front-end could not statically resolve the transition target).
    """
    is_dynamic = (
        edge.control is ControlKind.DYNAMIC or edge.provenance.origin == "unknown"
    )
    if not is_dynamic:
        return edge
    unsupported = list(edge.unsupported)
    _ensure(
        unsupported,
        UnsupportedKind.UNKNOWN_DISPATCH,
        detail=f"dynamic dispatch {edge.source}->{edge.target}",
        source_span=edge.provenance.source_span,
    )
    if tuple(unsupported) != edge.unsupported:
        return replace(edge, unsupported=tuple(unsupported))
    return edge


# ---------------------------------------------------------------------------
# Parallel-join resolution
# ---------------------------------------------------------------------------

def _mark_unresolved_parallel(graph: MayMustGraph) -> MayMustGraph:
    """Flag parallel fan-outs whose branches share no common join descendant.

    A node with two or more outgoing :class:`ControlKind.PARALLEL` edges is a
    fan-out. If the parallel branch targets have *no* common reachable
    descendant, the front-end cannot resolve where (or whether) they
    reconverge, so the interleaving is outside the abstraction contract:
    the fan-out node gets an ``UNRESOLVED_PARALLEL`` fact. This is conservative
    — when in doubt we keep the region non-certifiable.
    """
    adj = graph.adjacency()

    fanout_targets: dict[str, list[str]] = {}
    for e in graph.edges:
        if e.control is ControlKind.PARALLEL:
            fanout_targets.setdefault(e.source, []).append(e.target)

    to_flag: dict[str, str] = {}
    for source, targets in fanout_targets.items():
        if len(targets) < 2:
            continue  # a single parallel edge is not a fan-out
        descendant_sets = [_descendants(adj, t) for t in targets]
        common = set.intersection(*descendant_sets) if descendant_sets else set()
        if not common:
            to_flag[source] = ",".join(sorted(set(targets)))

    if not to_flag:
        return graph

    nodes = []
    for node in graph.nodes:
        if node.id in to_flag:
            unsupported = list(node.unsupported)
            _ensure(
                unsupported,
                UnsupportedKind.UNRESOLVED_PARALLEL,
                detail=f"parallel fan-out {node.id} -> [{to_flag[node.id]}] has no common join",
                source_span=node.provenance.source_span,
            )
            node = replace(node, unsupported=tuple(unsupported))
        nodes.append(node)
    return replace(graph, nodes=tuple(nodes))


def _descendants(adj: dict[str, list[str]], start: str) -> set[str]:
    """All nodes reachable from ``start`` (excluding ``start`` itself)."""
    seen: set[str] = set()
    stack = list(adj.get(start, ()))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(adj.get(cur, ()))
    return seen


# ---------------------------------------------------------------------------
# Source extraction (framework-gated)
# ---------------------------------------------------------------------------

def _extract_from_source(source: str) -> AgentGraph:
    """Execute LangGraph ``source`` and extract a flat :class:`AgentGraph`.

    Requires the ``langgraph`` framework (``import langgraph`` raises
    :class:`ImportError` when absent, which :func:`extract_and_lift` turns into
    a helpful :class:`RuntimeError`). The source is executed in a fresh
    namespace; a ``StateGraph`` / ``CompiledStateGraph`` bound to ``graph``,
    ``app``, or ``workflow`` (or the first object exposing ``get_graph`` /
    ``compile``) is handed to the existing extractor.
    """
    import langgraph  # noqa: F401  # gate: ImportError if the framework is absent

    from agentproof.graph.extract import extract_langgraph

    namespace: dict[str, object] = {}
    exec(compile(source, "<langgraph-source>", "exec"), namespace)  # noqa: S102

    candidate = None
    for key in ("graph", "app", "workflow"):
        if key in namespace:
            candidate = namespace[key]
            break
    if candidate is None:
        for value in namespace.values():
            if hasattr(value, "get_graph") or hasattr(value, "compile"):
                candidate = value
                break
    if candidate is None:
        raise RuntimeError(
            "no LangGraph StateGraph/CompiledStateGraph found in source; expose "
            "it as `graph`, `app`, or `workflow`."
        )
    return extract_langgraph(candidate)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _ensure(
    facts: list[UnsupportedFact],
    kind: UnsupportedKind,
    *,
    detail: str = "",
    source_span: str = "",
) -> None:
    """Append an :class:`UnsupportedFact` of ``kind`` iff none is present yet."""
    if any(f.kind is kind for f in facts):
        return
    facts.append(UnsupportedFact(kind, detail=detail, source_span=source_span))


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def _smoke() -> None:
    from agentproof.cegar.ir import region_is_certifiable
    from agentproof.graph.model import EdgeKind, GraphEdge

    # (1) entry -> tool(wire_transfer) -> exit, all exact.
    pay_nodes = (
        GraphNode("__start__", NodeKind.ENTRY, origin="runtime", confidence="exact"),
        GraphNode(
            "pay",
            NodeKind.TOOL,
            label="pay",
            tools=("wire_transfer",),
            origin="runtime",
            confidence="exact",
            capabilities=("invokes_tool",),
        ),
        GraphNode("__end__", NodeKind.EXIT, origin="runtime", confidence="exact"),
    )
    pay_edges = (
        GraphEdge("__start__", "pay", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
        GraphEdge("pay", "__end__", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
    )
    pay_graph = AgentGraph(
        name="pay-flow",
        framework="langgraph",
        nodes=pay_nodes,
        edges=pay_edges,
        entry_id="__start__",
        exit_ids=("__end__",),
    )

    mm = lift(pay_graph, tool_schemas=default_tool_schemas())
    tool_node = mm.node_by_id("pay")
    assert tool_node is not None
    assert tool_node.effect is EffectKind.FINANCIAL, tool_node.effect
    assert tool_node.tool_schema is not None and not tool_node.tool_schema.reversible
    assert not any(
        u.kind is UnsupportedKind.INCOMPLETE_SCHEMA for u in tool_node.unsupported
    ), tool_node.unsupported
    assert tool_node.is_certifiable, tool_node.unsupported
    assert region_is_certifiable(mm, ("pay",), (("__start__", "pay"), ("pay", "__end__")))

    # (2) entry -> subgraph -> exit: NESTED_AGENT, not certifiable.
    sub_nodes = (
        GraphNode("__start__", NodeKind.ENTRY, origin="runtime", confidence="exact"),
        GraphNode(
            "sub",
            NodeKind.SUBGRAPH,
            label="sub",
            origin="runtime",
            confidence="exact",
            capabilities=("subgraph",),
        ),
        GraphNode("__end__", NodeKind.EXIT, origin="runtime", confidence="exact"),
    )
    sub_edges = (
        GraphEdge("__start__", "sub", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
        GraphEdge("sub", "__end__", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
    )
    sub_graph = AgentGraph(
        name="sub-flow",
        framework="langgraph",
        nodes=sub_nodes,
        edges=sub_edges,
        entry_id="__start__",
        exit_ids=("__end__",),
    )

    mm2 = lift(sub_graph)
    sub_node = mm2.node_by_id("sub")
    assert sub_node is not None
    assert any(
        u.kind is UnsupportedKind.NESTED_AGENT for u in sub_node.unsupported
    ), sub_node.unsupported
    assert not sub_node.is_certifiable

    # (2b) tool resolution imports the schema's required authority.
    pay_node = mm.node_by_id("pay")
    assert pay_node is not None and pay_node.authority == "finance", pay_node.authority

    # (3) unknown-origin edge -> UNKNOWN_DISPATCH on that edge.
    dyn_nodes = (
        GraphNode("__start__", NodeKind.ENTRY, origin="runtime", confidence="exact"),
        GraphNode("route", NodeKind.ROUTER, label="route", origin="runtime",
                  confidence="exact", capabilities=("routes",)),
        GraphNode("__end__", NodeKind.EXIT, origin="runtime", confidence="exact"),
    )
    dyn_edges = (
        GraphEdge("__start__", "route", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
        # Origin "unknown" => target resolved at runtime => dynamic dispatch.
        GraphEdge("route", "__end__", EdgeKind.DIRECT, origin="unknown", confidence="may"),
    )
    dyn_graph = AgentGraph(
        name="dyn-flow", framework="langgraph", nodes=dyn_nodes, edges=dyn_edges,
        entry_id="__start__", exit_ids=("__end__",),
    )
    mm3 = lift(dyn_graph)
    route_out = [e for e in mm3.edges if e.source == "route"]
    assert route_out and any(
        u.kind is UnsupportedKind.UNKNOWN_DISPATCH
        for e in route_out for u in e.unsupported
    ), route_out
    assert not all(e.is_certifiable for e in route_out)

    # (4) parallel fan-out with NO common join descendant -> UNRESOLVED_PARALLEL;
    #     the same shape WITH a join descendant must NOT be flagged.
    def _parallel(join: bool) -> MayMustGraph:
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
            # Disjoint terminal leaves: the branches never reconverge.
            nodes += [
                GraphNode("x", NodeKind.EXIT, origin="runtime", confidence="exact"),
                GraphNode("y", NodeKind.EXIT, origin="runtime", confidence="exact"),
            ]
            edges += [
                GraphEdge("a", "x", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
                GraphEdge("b", "y", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
            ]
            exits = ("x", "y")
        return lift(AgentGraph(
            name="par", framework="langgraph", nodes=tuple(nodes), edges=tuple(edges),
            entry_id="s", exit_ids=exits,
        ))

    disjoint = _parallel(join=False).node_by_id("s")
    joined = _parallel(join=True).node_by_id("s")
    assert disjoint is not None and joined is not None
    assert any(
        u.kind is UnsupportedKind.UNRESOLVED_PARALLEL for u in disjoint.unsupported
    ), disjoint.unsupported
    assert not any(
        u.kind is UnsupportedKind.UNRESOLVED_PARALLEL for u in joined.unsupported
    ), joined.unsupported

    # (5) a present-but-incomplete tool schema keeps INCOMPLETE_SCHEMA and stays
    #     non-certifiable (uncertainty is never silently dropped).
    inc_schemas = {"myt": ToolSchema(name="myt", effect=EffectKind.UNKNOWN, complete=False)}
    inc_nodes = (
        GraphNode("__start__", NodeKind.ENTRY, origin="runtime", confidence="exact"),
        GraphNode("t", NodeKind.TOOL, tools=("myt",), origin="runtime",
                  confidence="exact", capabilities=("invokes_tool",)),
        GraphNode("__end__", NodeKind.EXIT, origin="runtime", confidence="exact"),
    )
    inc_edges = (
        GraphEdge("__start__", "t", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
        GraphEdge("t", "__end__", EdgeKind.DIRECT, origin="runtime", confidence="exact"),
    )
    mm5 = lift(
        AgentGraph(name="inc", framework="langgraph", nodes=inc_nodes, edges=inc_edges,
                   entry_id="__start__", exit_ids=("__end__",)),
        tool_schemas=inc_schemas,
    )
    t_node = mm5.node_by_id("t")
    assert t_node is not None and t_node.tool_schema is not None
    assert any(
        u.kind is UnsupportedKind.INCOMPLETE_SCHEMA for u in t_node.unsupported
    ), t_node.unsupported
    assert not t_node.is_certifiable

    # (6) extract_and_lift raises a clear RuntimeError when the framework is
    #     absent (langgraph is not installed in this venv).
    try:
        extract_and_lift("graph = None")
    except RuntimeError:
        pass
    except ImportError as exc:  # must be wrapped, not surfaced raw
        raise AssertionError("ImportError leaked from extract_and_lift") from exc
    else:
        # If langgraph IS installed the extractor may succeed or raise something
        # else; only a leaked bare ImportError is a contract violation.
        pass

    print("FRONTEND SMOKE OK")


if __name__ == "__main__":
    _smoke()
