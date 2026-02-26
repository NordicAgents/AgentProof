"""Tests for the abstract graph model and utility functions."""

from agentproof.graph.model import (
    AgentGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
    adjacency,
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
