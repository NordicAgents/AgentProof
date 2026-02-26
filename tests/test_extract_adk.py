"""Tests for Google ADK extractor using stub objects."""

from agentproof.graph.model import EdgeKind, NodeKind, node_by_id, successors
from agentproof.graph.extract._adk import extract_adk


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
