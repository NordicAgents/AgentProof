"""CrewAI Crew extractor."""

from __future__ import annotations

from typing import Any

from agentproof.graph.model import (
    AgentGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)


def _task_id(task: Any, index: int) -> str:
    name = getattr(task, "name", None) or getattr(task, "description", None)
    if name:
        return str(name).replace(" ", "_")[:64]
    return f"task_{index}"


def _classify_task(task: Any) -> NodeKind:
    if hasattr(task, "tools") and task.tools:
        return NodeKind.TOOL
    return NodeKind.LLM


def _get_tools(task: Any) -> tuple[str, ...]:
    if not hasattr(task, "tools") or not task.tools:
        return ()
    names: list[str] = []
    for t in task.tools:
        name = getattr(t, "name", None) or getattr(t, "__name__", str(t))
        names.append(name)
    return tuple(names)


def extract_crewai(crew: Any) -> AgentGraph:
    """Extract an AgentGraph from a CrewAI Crew."""
    tasks = getattr(crew, "tasks", []) or []
    process = getattr(crew, "process", None)
    process_name = getattr(process, "value", str(process)) if process else "sequential"

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    # Build task nodes
    task_ids: list[str] = []
    task_obj_to_id: dict[int, str] = {}
    seen_ids: set[str] = set()

    for i, task in enumerate(tasks):
        tid = _task_id(task, i)
        if tid in seen_ids:
            counter = 1
            while f"{tid}_{counter}" in seen_ids:
                counter += 1
            tid = f"{tid}_{counter}"
        seen_ids.add(tid)

        kind = _classify_task(task)
        tools = _get_tools(task)
        nodes.append(GraphNode(id=tid, kind=kind, label=tid, tools=tools))
        task_ids.append(tid)
        task_obj_to_id[id(task)] = tid

    if process_name == "hierarchical":
        # Manager node routes to each task
        manager = GraphNode(id="__manager__", kind=NodeKind.ROUTER, label="manager")
        nodes.append(manager)
        for tid in task_ids:
            edges.append(GraphEdge(source="__manager__", target=tid, kind=EdgeKind.CONDITIONAL))
    else:
        # Sequential: chain tasks in order
        for i in range(len(task_ids) - 1):
            edges.append(GraphEdge(source=task_ids[i], target=task_ids[i + 1]))

    # Context dependencies: task.context lists other tasks this task depends on
    for task in tasks:
        ctx_raw = getattr(task, "context", None)
        # CrewAI uses a NOT_SPECIFIED sentinel that is truthy but not iterable
        try:
            ctx = list(ctx_raw) if ctx_raw else []
        except TypeError:
            ctx = []
        tid = task_obj_to_id[id(task)]
        for dep_task in ctx:
            dep_id = task_obj_to_id.get(id(dep_task))
            if dep_id and dep_id != tid:
                # Only add if not already present
                if not any(e.source == dep_id and e.target == tid for e in edges):
                    edges.append(GraphEdge(source=dep_id, target=tid))

    # Synthesize entry/exit
    entry = GraphNode(id="__entry__", kind=NodeKind.ENTRY, label="__entry__")
    exit_node = GraphNode(id="__exit__", kind=NodeKind.EXIT, label="__exit__")
    nodes.insert(0, entry)
    nodes.append(exit_node)

    if process_name == "hierarchical":
        edges.insert(0, GraphEdge(source="__entry__", target="__manager__"))
        for tid in task_ids:
            edges.append(GraphEdge(source=tid, target="__exit__"))
    else:
        if task_ids:
            edges.insert(0, GraphEdge(source="__entry__", target=task_ids[0]))
            edges.append(GraphEdge(source=task_ids[-1], target="__exit__"))

    name = getattr(crew, "name", None) or "crewai"

    return AgentGraph(
        name=str(name),
        framework="crewai",
        nodes=tuple(nodes),
        edges=tuple(edges),
        entry_id="__entry__",
        exit_ids=("__exit__",),
    )
