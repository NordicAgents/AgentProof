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

        # Task objects (and their declared tool bindings) are read from the
        # live Crew: runtime/exact.
        kind = _classify_task(task)
        tools = _get_tools(task)
        nodes.append(
            GraphNode(
                id=tid, kind=kind, label=tid, tools=tools,
                origin="runtime", confidence="exact",
            )
        )
        task_ids.append(tid)
        task_obj_to_id[id(task)] = tid

    if process_name == "hierarchical":
        # Manager node routes to each task. Judgment call: a manager LLM does
        # exist in hierarchical crews, but this node (and its routing edges)
        # is fabricated by the extractor -> synthesized/may.
        manager = GraphNode(
            id="__manager__", kind=NodeKind.ROUTER, label="manager",
            origin="synthesized", confidence="may",
        )
        nodes.append(manager)
        for tid in task_ids:
            edges.append(
                GraphEdge(
                    source="__manager__", target=tid, kind=EdgeKind.CONDITIONAL,
                    origin="synthesized", confidence="may",
                )
            )
    else:
        # Sequential: chain tasks in order. The ordering is derived from
        # Process.sequential semantics, not a declared edge; the information
        # source is the live Crew object (no AST involved) -> runtime/may.
        for i in range(len(task_ids) - 1):
            edges.append(
                GraphEdge(
                    source=task_ids[i], target=task_ids[i + 1],
                    origin="runtime", confidence="may",
                )
            )

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
                    # Judgment call: task.context is declared on the live task
                    # (runtime), but it is a data dependency, not necessarily a
                    # direct control-flow step -> confidence "may".
                    edges.append(
                        GraphEdge(
                            source=dep_id, target=tid,
                            origin="runtime", confidence="may",
                        )
                    )

    # Synthesize entry/exit: CrewAI declares no such nodes.
    entry = GraphNode(
        id="__entry__", kind=NodeKind.ENTRY, label="__entry__",
        origin="synthesized", confidence="may",
    )
    exit_node = GraphNode(
        id="__exit__", kind=NodeKind.EXIT, label="__exit__",
        origin="synthesized", confidence="may",
    )
    nodes.insert(0, entry)
    nodes.append(exit_node)

    if process_name == "hierarchical":
        edges.insert(
            0,
            GraphEdge(
                source="__entry__", target="__manager__",
                origin="synthesized", confidence="may",
            ),
        )
        # Guessed connectivity: any task might be the one that terminates.
        for tid in task_ids:
            edges.append(
                GraphEdge(
                    source=tid, target="__exit__",
                    origin="synthesized", confidence="heuristic",
                )
            )
    else:
        if task_ids:
            # Sequential process starts at the first task and ends at the
            # last, but both edges touch fabricated nodes -> synthesized/may.
            edges.insert(
                0,
                GraphEdge(
                    source="__entry__", target=task_ids[0],
                    origin="synthesized", confidence="may",
                ),
            )
            edges.append(
                GraphEdge(
                    source=task_ids[-1], target="__exit__",
                    origin="synthesized", confidence="may",
                )
            )

    name = getattr(crew, "name", None) or "crewai"

    return AgentGraph(
        name=str(name),
        framework="crewai",
        nodes=tuple(nodes),
        edges=tuple(edges),
        entry_id="__entry__",
        exit_ids=("__exit__",),
    )
