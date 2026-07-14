"""Tests for the abstract graph model and utility functions."""

import json
from pathlib import Path

from agentproof.graph.model import (
    VALID_CAPABILITIES,
    VALID_CONFIDENCES,
    VALID_EFFECTS,
    VALID_ORIGINS,
    AgentGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
    adjacency,
    graph_from_dict,
    graph_to_dict,
    node_by_id,
    predecessors,
    successors,
)


def _simple_graph() -> AgentGraph:
    """A -> B -> C linear graph with entry/exit."""
    return AgentGraph(
        name="test",
        framework="test",
        nodes=(
            GraphNode(id="entry", kind=NodeKind.ENTRY, label="entry"),
            GraphNode(id="a", kind=NodeKind.LLM, label="A"),
            GraphNode(id="b", kind=NodeKind.TOOL, label="B", tools=("search",)),
            GraphNode(id="c", kind=NodeKind.LLM, label="C"),
            GraphNode(id="exit", kind=NodeKind.EXIT, label="exit"),
        ),
        edges=(
            GraphEdge(source="entry", target="a"),
            GraphEdge(source="a", target="b"),
            GraphEdge(source="b", target="c"),
            GraphEdge(source="c", target="exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )


def _branching_graph() -> AgentGraph:
    """Entry -> router --(cond)--> A or B --> exit."""
    return AgentGraph(
        name="branching",
        framework="test",
        nodes=(
            GraphNode(id="entry", kind=NodeKind.ENTRY),
            GraphNode(id="router", kind=NodeKind.ROUTER, label="router"),
            GraphNode(id="a", kind=NodeKind.LLM, label="A"),
            GraphNode(id="b", kind=NodeKind.TOOL, label="B"),
            GraphNode(id="exit", kind=NodeKind.EXIT),
        ),
        edges=(
            GraphEdge(source="entry", target="router"),
            GraphEdge(source="router", target="a", kind=EdgeKind.CONDITIONAL, condition="is_text"),
            GraphEdge(source="router", target="b", kind=EdgeKind.CONDITIONAL, condition="needs_tool"),
            GraphEdge(source="a", target="exit"),
            GraphEdge(source="b", target="exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )


class TestGraphConstruction:
    def test_frozen(self):
        g = _simple_graph()
        try:
            g.name = "other"  # type: ignore[misc]
            assert False, "should be frozen"
        except AttributeError:
            pass

    def test_node_kinds(self):
        g = _simple_graph()
        kinds = [n.kind for n in g.nodes]
        assert kinds == [NodeKind.ENTRY, NodeKind.LLM, NodeKind.TOOL, NodeKind.LLM, NodeKind.EXIT]

    def test_edge_kinds_default(self):
        g = _simple_graph()
        assert all(e.kind == EdgeKind.DIRECT for e in g.edges)

    def test_conditional_edges(self):
        g = _branching_graph()
        cond_edges = [e for e in g.edges if e.kind == EdgeKind.CONDITIONAL]
        assert len(cond_edges) == 2
        assert {e.condition for e in cond_edges} == {"is_text", "needs_tool"}

    def test_tools_tuple(self):
        g = _simple_graph()
        b = node_by_id(g, "b")
        assert b is not None
        assert b.tools == ("search",)

    def test_metadata_tuple(self):
        node = GraphNode(
            id="x", kind=NodeKind.LLM,
            metadata=(("framework_key", "val"),),
        )
        assert dict(node.metadata) == {"framework_key": "val"}


class TestSuccessors:
    def test_linear(self):
        g = _simple_graph()
        assert successors(g, "a") == ("b",)
        assert successors(g, "b") == ("c",)

    def test_branching(self):
        g = _branching_graph()
        succ = successors(g, "router")
        assert set(succ) == {"a", "b"}

    def test_exit_has_none(self):
        g = _simple_graph()
        assert successors(g, "exit") == ()


class TestPredecessors:
    def test_linear(self):
        g = _simple_graph()
        assert predecessors(g, "b") == ("a",)

    def test_exit_multiple(self):
        g = _branching_graph()
        preds = predecessors(g, "exit")
        assert set(preds) == {"a", "b"}

    def test_entry_has_none(self):
        g = _simple_graph()
        assert predecessors(g, "entry") == ()


class TestNodeById:
    def test_found(self):
        g = _simple_graph()
        n = node_by_id(g, "b")
        assert n is not None
        assert n.kind == NodeKind.TOOL

    def test_missing(self):
        g = _simple_graph()
        assert node_by_id(g, "nonexistent") is None


class TestAdjacency:
    def test_simple(self):
        g = _simple_graph()
        adj = adjacency(g)
        assert adj["entry"] == ["a"]
        assert adj["a"] == ["b"]
        assert adj["b"] == ["c"]
        assert adj["c"] == ["exit"]
        assert adj["exit"] == []

    def test_branching(self):
        g = _branching_graph()
        adj = adjacency(g)
        assert set(adj["router"]) == {"a", "b"}


class TestProvenance:
    def test_vocabulary(self):
        assert VALID_ORIGINS == {
            "runtime", "ast_explicit", "ast_inferred", "synthesized", "unknown",
        }
        assert VALID_CONFIDENCES == {"exact", "may", "heuristic"}

    def test_node_defaults(self):
        n = GraphNode(id="x", kind=NodeKind.LLM)
        assert n.origin == "unknown"
        assert n.confidence == "may"
        assert n.source_span == ""
        assert n.origin in VALID_ORIGINS
        assert n.confidence in VALID_CONFIDENCES

    def test_edge_defaults(self):
        e = GraphEdge(source="a", target="b")
        assert e.origin == "unknown"
        assert e.confidence == "may"
        assert e.source_span == ""

    def test_frozen_with_provenance(self):
        n = GraphNode(id="x", kind=NodeKind.LLM, origin="runtime", confidence="exact")
        try:
            n.origin = "synthesized"  # type: ignore[misc]
            assert False, "should be frozen"
        except AttributeError:
            pass


def _provenance_graph() -> AgentGraph:
    return AgentGraph(
        name="prov",
        framework="test",
        nodes=(
            GraphNode(id="entry", kind=NodeKind.ENTRY,
                      origin="synthesized", confidence="may"),
            GraphNode(id="a", kind=NodeKind.LLM, label="A",
                      origin="runtime", confidence="exact"),
            GraphNode(id="b", kind=NodeKind.TOOL, label="B", tools=("search",),
                      origin="ast_explicit", confidence="exact",
                      source_span="wf.py:12:14"),
            GraphNode(id="exit", kind=NodeKind.EXIT,
                      origin="synthesized", confidence="heuristic"),
        ),
        edges=(
            GraphEdge(source="entry", target="a",
                      origin="synthesized", confidence="may"),
            GraphEdge(source="a", target="b",
                      origin="ast_explicit", confidence="exact",
                      source_span="wf.py:20:20"),
            GraphEdge(source="b", target="exit",
                      origin="synthesized", confidence="heuristic"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )


class TestSerializationProvenance:
    def test_to_dict_emits_provenance_for_all_elements(self):
        d = graph_to_dict(_provenance_graph())
        for n in d["nodes"]:
            assert "origin" in n and "confidence" in n and "source_span" in n
        for e in d["edges"]:
            assert "origin" in e and "confidence" in e and "source_span" in e

    def test_round_trip_preserves_provenance(self):
        g = _provenance_graph()
        # Through JSON to prove serializability of the plain-string fields.
        g2 = graph_from_dict(json.loads(json.dumps(graph_to_dict(g))))
        assert g2.nodes == g.nodes
        assert g2.edges == g.edges
        b = node_by_id(g2, "b")
        assert b is not None
        assert (b.origin, b.confidence, b.source_span) == (
            "ast_explicit", "exact", "wf.py:12:14",
        )
        ab = next(e for e in g2.edges if e.source == "a" and e.target == "b")
        assert (ab.origin, ab.confidence, ab.source_span) == (
            "ast_explicit", "exact", "wf.py:20:20",
        )

    def test_legacy_dict_defaults(self):
        """Corpus JSON written before provenance existed must still load."""
        legacy = {
            "name": "legacy",
            "framework": "test",
            "entry_id": "s",
            "exit_ids": ["t"],
            "nodes": [
                {"id": "s", "kind": "entry", "label": "", "tools": [], "metadata": {}},
                {"id": "t", "kind": "exit", "label": "", "tools": [], "metadata": {}},
            ],
            "edges": [
                {"source": "s", "target": "t", "kind": "direct", "condition": ""},
            ],
        }
        g = graph_from_dict(legacy)
        for n in g.nodes:
            assert (n.origin, n.confidence, n.source_span) == ("unknown", "may", "")
        for e in g.edges:
            assert (e.origin, e.confidence, e.source_span) == ("unknown", "may", "")

    def test_corpus_graphs_still_load(self):
        """Smoke: real pre-provenance corpus files load with defaulted fields."""
        corpus = Path(__file__).resolve().parent.parent / "corpus" / "graphs"
        files = sorted(corpus.glob("*.json"))[:5]
        assert len(files) >= 5, f"expected corpus graphs in {corpus}"
        for f in files:
            g = graph_from_dict(json.loads(f.read_text()))
            assert g.nodes and g.edges
            for n in g.nodes:
                assert n.origin in VALID_ORIGINS
                assert n.confidence in VALID_CONFIDENCES
            for e in g.edges:
                assert e.origin in VALID_ORIGINS
                assert e.confidence in VALID_CONFIDENCES


# ---------------------------------------------------------------------------
# Orthogonal ontology (reviewer #7): effects / capabilities / back_edge
# ---------------------------------------------------------------------------


class TestOntologyVocabulary:
    def test_effect_vocabulary(self):
        assert VALID_EFFECTS == {
            "read", "write", "execute", "communicate", "financial", "delete",
        }

    def test_capability_vocabulary(self):
        assert VALID_CAPABILITIES == {
            "llm", "invokes_tool", "human_pause", "routes", "state_update",
            "subgraph",
        }

    def test_node_ontology_defaults_empty(self):
        n = GraphNode(id="x", kind=NodeKind.LLM)
        assert n.effects == ()
        assert n.capabilities == ()

    def test_edge_back_edge_defaults_false(self):
        e = GraphEdge(source="a", target="b")
        assert e.back_edge is False

    def test_effects_capabilities_are_orthogonal_to_kind(self):
        # A single node may be kind=LLM yet carry several capabilities and an
        # effect -- NodeKind is unchanged, the descriptors are additive.
        n = GraphNode(
            id="x", kind=NodeKind.LLM,
            capabilities=("llm", "invokes_tool", "routes"),
            effects=("read", "write"),
        )
        assert n.kind == NodeKind.LLM
        assert set(n.capabilities) <= VALID_CAPABILITIES
        assert set(n.effects) <= VALID_EFFECTS

    def test_conditional_back_edge_expresses_loop(self):
        # reviewer #7: an edge may be BOTH conditional and a back edge.
        e = GraphEdge(source="router", target="earlier",
                      kind=EdgeKind.CONDITIONAL, back_edge=True)
        assert e.kind == EdgeKind.CONDITIONAL
        assert e.back_edge is True


def _ontology_graph() -> AgentGraph:
    return AgentGraph(
        name="ont",
        framework="test",
        nodes=(
            GraphNode(id="entry", kind=NodeKind.ENTRY),
            GraphNode(id="llm", kind=NodeKind.LLM, label="L",
                      capabilities=("llm", "routes")),
            GraphNode(id="tool", kind=NodeKind.TOOL, label="T",
                      tools=("delete_records",),
                      capabilities=("invokes_tool",), effects=("delete", "write")),
            GraphNode(id="exit", kind=NodeKind.EXIT),
        ),
        edges=(
            GraphEdge(source="entry", target="llm"),
            GraphEdge(source="llm", target="tool", kind=EdgeKind.CONDITIONAL,
                      condition="go", back_edge=False),
            GraphEdge(source="tool", target="llm", kind=EdgeKind.CONDITIONAL,
                      condition="retry", back_edge=True),
            GraphEdge(source="tool", target="exit"),
        ),
        entry_id="entry",
        exit_ids=("exit",),
    )


class TestSerializationOntology:
    def test_to_dict_emits_ontology_fields(self):
        d = graph_to_dict(_ontology_graph())
        for n in d["nodes"]:
            assert "effects" in n and "capabilities" in n
        for e in d["edges"]:
            assert "back_edge" in e

    def test_round_trip_preserves_ontology(self):
        g = _ontology_graph()
        g2 = graph_from_dict(json.loads(json.dumps(graph_to_dict(g))))
        assert g2.nodes == g.nodes
        assert g2.edges == g.edges
        tool = node_by_id(g2, "tool")
        assert tool is not None
        assert tool.effects == ("delete", "write")
        assert tool.capabilities == ("invokes_tool",)
        loop = next(e for e in g2.edges if e.source == "tool" and e.target == "llm")
        assert loop.kind == EdgeKind.CONDITIONAL and loop.back_edge is True
        fwd = next(e for e in g2.edges if e.source == "llm" and e.target == "tool")
        assert fwd.back_edge is False

    def test_legacy_dict_defaults_ontology(self):
        """Dicts written before the ontology fields existed must still load."""
        legacy = {
            "name": "legacy",
            "framework": "test",
            "entry_id": "s",
            "exit_ids": ["t"],
            "nodes": [
                {"id": "s", "kind": "entry", "label": "", "tools": [],
                 "metadata": {}, "origin": "unknown", "confidence": "may",
                 "source_span": ""},
                {"id": "t", "kind": "exit", "label": "", "tools": [],
                 "metadata": {}, "origin": "unknown", "confidence": "may",
                 "source_span": ""},
            ],
            "edges": [
                {"source": "s", "target": "t", "kind": "direct", "condition": "",
                 "origin": "unknown", "confidence": "may", "source_span": ""},
            ],
        }
        g = graph_from_dict(legacy)
        for n in g.nodes:
            assert n.effects == () and n.capabilities == ()
        for e in g.edges:
            assert e.back_edge is False


class TestCuratedProvenance:
    """Curated corpus is authored ground truth => exact provenance so the
    verifier's certification gate can certify it."""

    CURATED = Path(__file__).resolve().parent.parent / "corpus" / "curated"

    def test_three_curated_graphs_are_exact(self):
        names = [
            "lg_customer_support.json",
            "adk_compliance_review.json",
            "lg_financial_advisor.json",
        ]
        for name in names:
            path = self.CURATED / name
            g = graph_from_dict(json.loads(path.read_text()))
            assert g.nodes and g.edges
            for n in g.nodes:
                assert n.confidence == "exact", f"{name}:{n.id}"
                assert n.origin == "ast_explicit", f"{name}:{n.id}"
                assert n.source_span == ""
                assert set(n.effects) <= VALID_EFFECTS
                assert set(n.capabilities) <= VALID_CAPABILITIES
            for e in g.edges:
                assert e.confidence == "exact", f"{name}:{e.source}->{e.target}"
                assert e.origin == "ast_explicit"

    def test_all_curated_files_load_and_are_exact(self):
        files = sorted(self.CURATED.glob("*.json"))
        assert len(files) == 18, f"expected 18 curated files, found {len(files)}"
        for f in files:
            g = graph_from_dict(json.loads(f.read_text()))
            assert g.nodes and g.edges
            for n in g.nodes:
                assert n.confidence == "exact"
                assert n.origin == "ast_explicit"
            for e in g.edges:
                assert e.confidence == "exact"
                assert e.origin == "ast_explicit"

    def test_curated_has_a_conditional_back_edge(self):
        """The corpus expresses conditional loops (router back to an earlier
        node) as kind=CONDITIONAL + back_edge=True."""
        path = self.CURATED / "lg_multi_agent_research.json"
        g = graph_from_dict(json.loads(path.read_text()))
        loop = next(
            e for e in g.edges
            if e.source == "review_router" and e.target == "researcher"
        )
        assert loop.kind == EdgeKind.CONDITIONAL
        assert loop.back_edge is True
