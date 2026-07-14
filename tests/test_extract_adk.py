"""Tests for Google ADK extractor using stub objects."""

import importlib.util
from pathlib import Path

from agentproof.graph.model import EdgeKind, NodeKind, node_by_id, successors
from agentproof.graph.extract._adk import extract_adk


def _load_ast_extractor():
    """Import scripts/ast_extractor.py (not an installed package)."""
    path = Path(__file__).resolve().parent.parent / "scripts" / "ast_extractor.py"
    spec = importlib.util.spec_from_file_location("_ast_extractor_adk", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _StubAgent:
    """Base stub mimicking an ADK agent."""

    def __init__(self, name, sub_agents=None, tools=None, model=None):
        self.name = name
        self.sub_agents = sub_agents or []
        self.tools = tools or []
        self.model = model


class SequentialAgent(_StubAgent):
    pass


class ParallelAgent(_StubAgent):
    pass


class LoopAgent(_StubAgent):
    pass


class LlmAgent(_StubAgent):
    pass


class TestLeafAgent:
    def test_single_llm(self):
        agent = LlmAgent("chat", model="gemini-pro")
        graph = extract_adk(agent)

        assert graph.framework == "adk"
        assert graph.entry_id == "__entry__"
        assert graph.exit_ids == ("__exit__",)

        chat = node_by_id(graph, "chat")
        assert chat is not None
        assert chat.kind == NodeKind.LLM

    def test_single_tool_agent(self):
        tool = type("Tool", (), {"name": "web_search"})()
        agent = LlmAgent("searcher", tools=[tool])
        graph = extract_adk(agent)

        searcher = node_by_id(graph, "searcher")
        assert searcher is not None
        assert searcher.kind == NodeKind.TOOL
        assert searcher.tools == ("web_search",)

    def test_human_name_is_classified_as_human(self):
        agent = LlmAgent("human_signoff", model="gemini-pro")
        graph = extract_adk(agent)

        human = node_by_id(graph, "human_signoff")
        assert human is not None
        assert human.kind == NodeKind.HUMAN
        # The HUMAN kind rests on a name-substring guess -> may, not exact.
        assert human.origin == "runtime"
        assert human.confidence == "may"


class TestSequentialAgent:
    def test_chain(self):
        a = LlmAgent("step_1", model="gemini")
        b = LlmAgent("step_2", model="gemini")
        c = LlmAgent("step_3", model="gemini")
        seq = SequentialAgent("pipeline", sub_agents=[a, b, c])

        graph = extract_adk(seq)

        # entry -> pipeline -> step_1 -> step_2 -> step_3 -> exit
        assert successors(graph, "__entry__") == ("pipeline",)
        assert "step_1" in successors(graph, "pipeline")

        # Check sequential chaining
        edges = {(e.source, e.target) for e in graph.edges}
        assert ("step_1", "step_2") in edges
        assert ("step_2", "step_3") in edges


class TestParallelAgent:
    def test_fork(self):
        a = LlmAgent("branch_a", model="gemini")
        b = LlmAgent("branch_b", model="gemini")
        par = ParallelAgent("fork", sub_agents=[a, b])

        graph = extract_adk(par)

        par_edges = [e for e in graph.edges if e.source == "fork" and e.kind == EdgeKind.PARALLEL]
        assert len(par_edges) == 2
        targets = {e.target for e in par_edges}
        assert targets == {"branch_a", "branch_b"}


class TestLoopAgent:
    def test_back_edge(self):
        a = LlmAgent("check", model="gemini")
        b = LlmAgent("act", model="gemini")
        loop = LoopAgent("retry", sub_agents=[a, b])

        graph = extract_adk(loop)

        loop_edges = [e for e in graph.edges if e.kind == EdgeKind.LOOP]
        assert len(loop_edges) == 1
        assert loop_edges[0].source == "act"
        assert loop_edges[0].target == "check"


class TestProvenance:
    def test_agent_nodes_are_runtime_exact(self):
        a = LlmAgent("step_1", model="gemini")
        b = LlmAgent("step_2", model="gemini")
        seq = SequentialAgent("pipeline", sub_agents=[a, b])
        graph = extract_adk(seq)

        for nid in ("pipeline", "step_1", "step_2"):
            n = node_by_id(graph, nid)
            assert n is not None
            assert n.origin == "runtime"
            assert n.confidence == "exact"

    def test_synthesized_entry_exit_tagged_non_exact(self):
        agent = LlmAgent("root", model="gemini")
        graph = extract_adk(agent)

        for nid in ("__entry__", "__exit__"):
            n = node_by_id(graph, nid)
            assert n is not None
            assert n.origin == "synthesized"
            assert n.confidence != "exact"
        # Every edge that touches a fabricated node is synthesized.
        for e in graph.edges:
            if "__entry__" in (e.source, e.target) or "__exit__" in (e.source, e.target):
                assert e.origin == "synthesized"
                assert e.confidence != "exact"

    def test_sequential_ordering_is_inferred(self):
        a = LlmAgent("step_1", model="gemini")
        b = LlmAgent("step_2", model="gemini")
        seq = SequentialAgent("pipeline", sub_agents=[a, b])
        graph = extract_adk(seq)

        chain = next(e for e in graph.edges if (e.source, e.target) == ("step_1", "step_2"))
        # Inferred from the LIVE agent tree (no AST involved): origin is
        # "runtime" (the information source), confidence stays non-exact.
        assert chain.origin == "runtime"
        assert chain.confidence == "may"

    def test_leaf_to_exit_is_heuristic(self):
        agent = LlmAgent("root", model="gemini")
        graph = extract_adk(agent)

        exit_edges = [e for e in graph.edges if e.target == "__exit__"]
        assert exit_edges
        assert all(e.origin == "synthesized" for e in exit_edges)
        assert all(e.confidence == "heuristic" for e in exit_edges)

    def test_loop_back_edge_is_inferred(self):
        a = LlmAgent("check", model="gemini")
        b = LlmAgent("act", model="gemini")
        loop = LoopAgent("retry", sub_agents=[a, b])
        graph = extract_adk(loop)

        back = next(e for e in graph.edges if e.kind == EdgeKind.LOOP)
        # Inferred from LoopAgent semantics on the live object -> runtime.
        assert back.origin == "runtime"
        assert back.confidence != "exact"


class TestEntryExit:
    def test_entry_exit_present(self):
        agent = LlmAgent("root", model="gemini")
        graph = extract_adk(agent)

        entry = node_by_id(graph, "__entry__")
        exit_n = node_by_id(graph, "__exit__")
        assert entry is not None and entry.kind == NodeKind.ENTRY
        assert exit_n is not None and exit_n.kind == NodeKind.EXIT

    def test_leaves_connect_to_exit(self):
        a = LlmAgent("leaf", model="gemini")
        seq = SequentialAgent("wrapper", sub_agents=[a])
        graph = extract_adk(seq)

        exit_edges = [e for e in graph.edges if e.target == "__exit__"]
        assert len(exit_edges) >= 1


class TestASTExtractorADK:
    """Unit tests for scripts/ast_extractor.py ADK handling."""

    def _extract(self, tmp_path, source: str):
        mod = _load_ast_extractor()
        f = tmp_path / "wf.py"
        f.write_text(source)
        return mod.extract_graph_from_source(f, "adk")

    def test_loop_agent_emits_chain_and_loop_back(self, tmp_path):
        """LoopAgent workflows were silently dropped (no edges emitted).

        ADK LoopAgent semantics: children run in declared order, repeating.
        Expect the sequential chain over sub-agents plus a loop-back edge
        from last to first, all ast_inferred/may.
        """
        graph = self._extract(tmp_path, (
            'loop = LoopAgent(name="retry", sub_agents=[checker, fixer])\n'
        ))
        assert graph is not None, "LoopAgent workflow must not be dropped"

        edges = {(e["source"], e["target"]): e for e in graph["edges"]}
        # Sequential chain over sub-agents.
        chain = edges.get(("checker", "fixer"))
        assert chain is not None
        assert chain["origin"] == "ast_inferred"
        assert chain["confidence"] == "may"
        # Loop-back from last to first.
        back = edges.get(("fixer", "checker"))
        assert back is not None
        assert back["kind"] == "loop"
        assert back["origin"] == "ast_inferred"
        assert back["confidence"] == "may"
        # Entry/exit hookups follow the synthesized-sentinel convention.
        assert ("__start__", "checker") in edges
        assert ("fixer", "__end__") in edges

    def test_loop_agent_single_child_self_loop(self, tmp_path):
        graph = self._extract(tmp_path, (
            'loop = LoopAgent(name="retry", sub_agents=[worker])\n'
        ))
        assert graph is not None
        loops = [e for e in graph["edges"] if e["kind"] == "loop"]
        assert [(e["source"], e["target"]) for e in loops] == [("worker", "worker")]
