"""Tests for CrewAI extractor using stub objects."""

from types import SimpleNamespace

from agentproof.graph.model import EdgeKind, NodeKind, node_by_id, successors
from agentproof.graph.extract._crewai import extract_crewai


def _make_task(name, tools=None, context=None):
    return SimpleNamespace(name=name, description=name, tools=tools or [], context=context or [])


def _make_crew(tasks, process="sequential", name="test_crew"):
    return SimpleNamespace(
        tasks=tasks,
        process=SimpleNamespace(value=process),
        name=name,
    )


class TestSequentialProcess:
    def test_chain(self):
        t1 = _make_task("research")
        t2 = _make_task("write")
        t3 = _make_task("review")
        crew = _make_crew([t1, t2, t3])

        graph = extract_crewai(crew)

        assert graph.framework == "crewai"
        assert graph.name == "test_crew"
        assert graph.entry_id == "__entry__"

        # Sequential chain
        assert "research" in successors(graph, "__entry__")
        assert "write" in successors(graph, "research")
        assert "review" in successors(graph, "write")
        assert "__exit__" in successors(graph, "review")

    def test_single_task(self):
        t = _make_task("only_task")
        crew = _make_crew([t])
        graph = extract_crewai(crew)

        assert "only_task" in successors(graph, "__entry__")
        assert "__exit__" in successors(graph, "only_task")


class TestHierarchicalProcess:
    def test_manager_routes(self):
        t1 = _make_task("task_a")
        t2 = _make_task("task_b")
        crew = _make_crew([t1, t2], process="hierarchical")

        graph = extract_crewai(crew)

        manager = node_by_id(graph, "__manager__")
        assert manager is not None
        assert manager.kind == NodeKind.ROUTER

        # Manager connects to both tasks
        mgr_succ = successors(graph, "__manager__")
        assert "task_a" in mgr_succ
        assert "task_b" in mgr_succ

        # All edges from manager are conditional
        mgr_edges = [e for e in graph.edges if e.source == "__manager__"]
        assert all(e.kind == EdgeKind.CONDITIONAL for e in mgr_edges)

        # Tasks connect to exit
        assert "__exit__" in successors(graph, "task_a")
        assert "__exit__" in successors(graph, "task_b")


class TestToolDetection:
    def test_task_with_tools(self):
        tool = SimpleNamespace(name="web_search")
        t = _make_task("search_task", tools=[tool])
        crew = _make_crew([t])

        graph = extract_crewai(crew)

        node = node_by_id(graph, "search_task")
        assert node is not None
        assert node.kind == NodeKind.TOOL
        assert node.tools == ("web_search",)

    def test_task_without_tools(self):
        t = _make_task("think_task")
        crew = _make_crew([t])
        graph = extract_crewai(crew)

        node = node_by_id(graph, "think_task")
        assert node is not None
        assert node.kind == NodeKind.LLM


class TestContextDependencies:
    def test_context_adds_edges(self):
        t1 = _make_task("gather")
        t2 = _make_task("analyze", context=[t1])
        t3 = _make_task("report", context=[t1, t2])
        crew = _make_crew([t1, t2, t3])

        graph = extract_crewai(crew)

        # Sequential edges: gather -> analyze -> report
        edges = {(e.source, e.target) for e in graph.edges}
        assert ("gather", "analyze") in edges
        assert ("analyze", "report") in edges

        # Context edges: gather -> analyze (already exists), gather -> report
        assert ("gather", "report") in edges


class TestEntryExit:
    def test_synthetic_nodes(self):
        t = _make_task("task")
        crew = _make_crew([t])
        graph = extract_crewai(crew)

        entry = node_by_id(graph, "__entry__")
        exit_n = node_by_id(graph, "__exit__")
        assert entry is not None and entry.kind == NodeKind.ENTRY
        assert exit_n is not None and exit_n.kind == NodeKind.EXIT
