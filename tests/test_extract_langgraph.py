"""Tests for LangGraph extractor using stub objects."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from agentproof.graph.model import EdgeKind, NodeKind, node_by_id, successors
from agentproof.graph.extract._langgraph import extract_langgraph


def _load_ast_extractor():
    """Import scripts/ast_extractor.py (not an installed package)."""
    path = Path(__file__).resolve().parent.parent / "scripts" / "ast_extractor.py"
    spec = importlib.util.spec_from_file_location("_ast_extractor_lg", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
        # The HUMAN kind rests on a name-substring guess -> may, not exact.
        assert human.origin == "runtime"
        assert human.confidence == "may"


class TestProvenance:
    def test_declared_structure_is_runtime_exact(self):
        drawable = _make_drawable(
            nodes_data=[
                ("__start__", {}),
                ("agent", {"name": "agent"}),
                ("__end__", {}),
            ],
            edges_data=[
                ("__start__", "agent", False),
                ("agent", "__end__", False),
            ],
        )
        graph = extract_langgraph(_make_compiled_graph(drawable))

        # Everything comes straight from the compiled framework graph.
        assert all(n.origin == "runtime" for n in graph.nodes)
        assert all(n.confidence == "exact" for n in graph.nodes)
        assert all(e.origin == "runtime" for e in graph.edges)
        assert all(e.confidence == "exact" for e in graph.edges)

    def test_name_heuristic_kind_is_may(self):
        """HUMAN/ROUTER kinds guessed from name substrings are not exact."""
        drawable = _make_drawable(
            nodes_data=[
                ("__start__", {}),
                ("router", {"name": "router"}),
                ("human_gate", {"name": "human_gate"}),
                ("plain_agent", {"name": "plain_agent"}),
                ("tool_node", {"name": "tool_node", "tools": [SimpleNamespace(name="search")]}),
                ("__end__", {}),
            ],
            edges_data=[
                ("__start__", "router", False),
                ("router", "human_gate", True),
                ("router", "plain_agent", True),
                ("human_gate", "tool_node", False),
                ("plain_agent", "tool_node", False),
                ("tool_node", "__end__", False),
            ],
        )
        graph = extract_langgraph(_make_compiled_graph(drawable))

        # Guessed kinds: existence is runtime, but the claim is only "may".
        for nid in ("router", "human_gate"):
            n = node_by_id(graph, nid)
            assert n is not None
            assert n.origin == "runtime"
            assert n.confidence == "may"
        # Declared structure stays exact: sentinels, bound tools, default llm.
        for nid in ("__start__", "plain_agent", "tool_node", "__end__"):
            n = node_by_id(graph, nid)
            assert n is not None
            assert n.confidence == "exact"

    def test_conditional_edges_are_may(self):
        drawable = _make_drawable(
            nodes_data=[
                ("__start__", {}),
                ("router", {"name": "router"}),
                ("a", {"name": "a"}),
                ("__end__", {}),
            ],
            edges_data=[
                ("__start__", "router", False),
                ("router", "a", True),
                ("a", "__end__", False),
            ],
        )
        graph = extract_langgraph(_make_compiled_graph(drawable))

        cond = [e for e in graph.edges if e.kind == EdgeKind.CONDITIONAL]
        assert cond, "expected a conditional edge"
        # LangGraph enumerates conditional targets itself: real but not exact.
        assert all(e.origin == "runtime" for e in cond)
        assert all(e.confidence == "may" for e in cond)
        direct = [e for e in graph.edges if e.kind == EdgeKind.DIRECT]
        assert all(e.confidence == "exact" for e in direct)


class TestASTExtractorLangGraph:
    """Unit tests for scripts/ast_extractor.py LangGraph handling."""

    def _extract(self, tmp_path, source: str):
        mod = _load_ast_extractor()
        f = tmp_path / "wf.py"
        f.write_text(source)
        return mod.extract_graph_from_source(f, "langgraph")

    def test_three_positional_path_map(self, tmp_path):
        """Standard signature add_conditional_edges(source, path, path_map).

        Regression: dict literals in the THIRD positional slot were dropped,
        turning routers into dead ends (false-proof channel).
        """
        graph = self._extract(tmp_path, (
            'g.add_node("triage_router", triage_router)\n'
            'g.add_node("auto_mitigate", auto_mitigate)\n'
            'g.add_node("human_approval", human_approval)\n'
            'g.add_conditional_edges(\n'
            '    "triage_router",\n'
            '    triage_decision,\n'
            '    {"auto": "auto_mitigate", "needs_human": "human_approval"},\n'
            ')\n'
            'g.set_entry_point("triage_router")\n'
        ))
        assert graph is not None
        cond = [e for e in graph["edges"] if e["kind"] == "conditional"]
        targets = {(e["source"], e["target"]) for e in cond}
        assert ("triage_router", "auto_mitigate") in targets
        assert ("triage_router", "human_approval") in targets
        # Declared path_map dict -> ast_explicit/exact.
        assert all(e["origin"] == "ast_explicit" for e in cond)
        assert all(e["confidence"] == "exact" for e in cond)

    def test_keyword_path_map_still_works(self, tmp_path):
        graph = self._extract(tmp_path, (
            'g.add_node("router_x", fn)\n'
            'g.add_node("a", fa)\n'
            'g.add_conditional_edges("router_x", decide, path_map={"go": "a"})\n'
            'g.set_entry_point("router_x")\n'
        ))
        assert graph is not None
        cond = [e for e in graph["edges"] if e["kind"] == "conditional"]
        assert {(e["source"], e["target"]) for e in cond} == {("router_x", "a")}

    def test_metadata_tools_binding_extracted(self, tmp_path):
        """add_node(..., metadata={"tools": [...]}) dict literals are recovered."""
        graph = self._extract(tmp_path, (
            'g.add_node(\n'
            '    "mitigate_tools",\n'
            '    mitigate_tools,\n'
            '    metadata={"tools": [restart_service, "rollback_deploy"]},\n'
            ')\n'
            'g.set_entry_point("mitigate_tools")\n'
        ))
        assert graph is not None
        node = next(n for n in graph["nodes"] if n["id"] == "mitigate_tools")
        assert node["tools"] == ["restart_service", "rollback_deploy"]
        # Kind derived from the declared binding, not the name -> stays exact.
        assert node["kind"] == "tool"
        assert node["origin"] == "ast_explicit"
        assert node["confidence"] == "exact"

    def test_name_heuristic_kind_is_may(self, tmp_path):
        """Kinds guessed from name substrings downgrade node confidence."""
        graph = self._extract(tmp_path, (
            'g.add_node("human_approval", human_approval)\n'
            'g.add_node("intake", intake)\n'
            'g.add_edge("human_approval", "intake")\n'
        ))
        assert graph is not None
        by_id = {n["id"]: n for n in graph["nodes"]}
        human = by_id["human_approval"]
        assert human["kind"] == "human"
        assert human["origin"] == "ast_explicit"  # existence is explicit
        assert human["confidence"] == "may"  # kind is a name guess
        plain = by_id["intake"]
        assert plain["kind"] == "llm"
        assert plain["confidence"] == "exact"


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
