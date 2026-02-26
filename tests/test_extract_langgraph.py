"""Tests for LangGraph extractor using stub objects."""

from types import SimpleNamespace

from agentproof.graph.model import EdgeKind, NodeKind, node_by_id, successors
from agentproof.graph.extract._langgraph import extract_langgraph


def _make_drawable(nodes_data, edges_data):
    """Build a stub mimicking LangGraph's DrawableGraph."""
    nodes = []
    _nodes = {}
    for nid, data in nodes_data:
        attrs = {"id": nid, "name": nid}
        attrs.update(data)
        node = SimpleNamespace(**attrs)
        nodes.append(node)
        _nodes[nid] = node

    edges = []
    for src, tgt, conditional in edges_data:
        edges.append(SimpleNamespace(source=src, target=tgt, conditional=conditional, data=""))

    return SimpleNamespace(nodes=nodes, edges=edges, _nodes=_nodes, name="test_graph")


def _make_compiled_graph(drawable):
    """Stub for CompiledStateGraph that returns a drawable."""
    return SimpleNamespace(
        get_graph=lambda xray=False: drawable,
        name="test_graph",
    )


class TestBasicExtraction:
    def test_simple_chain(self):
        drawable = _make_drawable(
            nodes_data=[
                ("__start__", {}),
                ("agent", {"name": "agent"}),
                ("tool_node", {"name": "tool_node", "tools": [SimpleNamespace(name="search")]}),
                ("__end__", {}),
            ],
            edges_data=[
                ("__start__", "agent", False),
                ("agent", "tool_node", False),
                ("tool_node", "__end__", False),
            ],
        )
        graph = extract_langgraph(_make_compiled_graph(drawable))

        assert graph.framework == "langgraph"
        assert graph.name == "test_graph"
        assert graph.entry_id == "__start__"
        assert "__end__" in graph.exit_ids

        entry = node_by_id(graph, "__start__")
        assert entry is not None
        assert entry.kind == NodeKind.ENTRY

        exit_node = node_by_id(graph, "__end__")
        assert exit_node is not None
        assert exit_node.kind == NodeKind.EXIT

    def test_tool_detection(self):
        drawable = _make_drawable(
            nodes_data=[
                ("__start__", {}),
                ("tool_node", {"name": "tool_node", "tools": [SimpleNamespace(name="calculator")]}),
                ("__end__", {}),
            ],
            edges_data=[
                ("__start__", "tool_node", False),
                ("tool_node", "__end__", False),
            ],
        )
        graph = extract_langgraph(_make_compiled_graph(drawable))
        tool = node_by_id(graph, "tool_node")
        assert tool is not None
        assert tool.kind == NodeKind.TOOL
        assert tool.tools == ("calculator",)

    def test_conditional_edges(self):
        drawable = _make_drawable(
            nodes_data=[
                ("__start__", {}),
                ("router", {"name": "router"}),
                ("a", {"name": "a"}),
                ("b", {"name": "b"}),
                ("__end__", {}),
            ],
            edges_data=[
                ("__start__", "router", False),
                ("router", "a", True),
                ("router", "b", True),
                ("a", "__end__", False),
                ("b", "__end__", False),
            ],
        )
        graph = extract_langgraph(_make_compiled_graph(drawable))
        cond_edges = [e for e in graph.edges if e.kind == EdgeKind.CONDITIONAL]
        assert len(cond_edges) == 2
        sources = {e.source for e in cond_edges}
        assert sources == {"router"}

    def test_human_node_detection(self):
        drawable = _make_drawable(
            nodes_data=[
                ("__start__", {}),
                ("human_review", {"name": "human_review"}),
                ("__end__", {}),
            ],
            edges_data=[
                ("__start__", "human_review", False),
                ("human_review", "__end__", False),
            ],
        )
        graph = extract_langgraph(_make_compiled_graph(drawable))
        human = node_by_id(graph, "human_review")
        assert human is not None
        assert human.kind == NodeKind.HUMAN


class TestCompileOnDemand:
    def test_state_graph_gets_compiled(self):
        """If the object has compile() but no get_graph(), we compile first."""
        drawable = _make_drawable(
            nodes_data=[
                ("__start__", {}),
                ("node_a", {"name": "node_a"}),
                ("__end__", {}),
            ],
            edges_data=[
                ("__start__", "node_a", False),
                ("node_a", "__end__", False),
            ],
        )
        compiled = _make_compiled_graph(drawable)
        # StateGraph stub: has compile() but no get_graph()
        state_graph = SimpleNamespace(compile=lambda: compiled, name="state_graph")

        graph = extract_langgraph(state_graph)
        assert graph.entry_id == "__start__"
        assert len(graph.nodes) == 3
