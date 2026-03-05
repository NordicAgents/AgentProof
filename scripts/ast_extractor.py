#!/usr/bin/env python3
"""AST-based graph extractor for agent workflow source files.

Parses Python source code without executing it to extract AgentGraph
structures.  This is a best-effort fallback for repos where the runtime
extractors cannot be used (missing dependencies, version conflicts, etc.).

Supported patterns:
  - LangGraph: StateGraph().add_node() / .add_edge() / .add_conditional_edges()
  - CrewAI:    Crew(tasks=[...], process=...) with Task(...) definitions
  - AutoGen:   RoundRobinGroupChat / SelectorGroupChat / GroupChat with agents
  - ADK:       SequentialAgent / ParallelAgent / LoopAgent with sub_agents
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any


def _str_value(node: ast.expr) -> str | None:
    """Extract string value from an AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return node.id
    return None


def _list_of_names(node: ast.expr) -> list[str]:
    """Extract a list of identifiers from [a, b, c] or (a, b, c)."""
    names: list[str] = []
    if isinstance(node, (ast.List, ast.Tuple)):
        for elt in node.elts:
            name = _str_value(elt)
            if name:
                names.append(name)
    return names


class _LangGraphVisitor(ast.NodeVisitor):
    """Extract nodes and edges from LangGraph StateGraph calls."""

    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self._node_ids: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func
        method = None
        if isinstance(func, ast.Attribute):
            method = func.attr

        if method == "add_node" and node.args:
            name = _str_value(node.args[0])
            if name and name not in self._node_ids:
                self._node_ids.add(name)
                kind = "llm"
                if "human" in name.lower():
                    kind = "human"
                elif "tool" in name.lower():
                    kind = "tool"
                elif "route" in name.lower() or "router" in name.lower():
                    kind = "router"
                self.nodes.append({"id": name, "kind": kind, "label": name, "tools": []})

        elif method == "add_edge" and len(node.args) >= 2:
            src = _str_value(node.args[0])
            dst = _str_value(node.args[1])
            if src and dst:
                self.edges.append({"source": src, "target": dst, "kind": "direct"})

        elif method == "add_conditional_edges" and node.args:
            src = _str_value(node.args[0])
            if src:
                # Mark source as router if not already
                for n in self.nodes:
                    if n["id"] == src:
                        n["kind"] = "router"
                # Try to extract mapping from second arg
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Dict):
                    for val in node.args[1].values:
                        dst = _str_value(val)
                        if dst:
                            self.edges.append({"source": src, "target": dst, "kind": "conditional"})
                # Also check keyword path_map
                for kw in node.keywords:
                    if kw.arg == "path_map" and isinstance(kw.value, ast.Dict):
                        for val in kw.value.values:
                            dst = _str_value(val)
                            if dst:
                                self.edges.append({"source": src, "target": dst, "kind": "conditional"})

        elif method == "set_entry_point" and node.args:
            src = _str_value(node.args[0])
            if src:
                self.edges.append({"source": "__start__", "target": src, "kind": "direct"})

        elif method == "set_finish_point" and node.args:
            dst = _str_value(node.args[0])
            if dst:
                self.edges.append({"source": dst, "target": "__end__", "kind": "direct"})

        self.generic_visit(node)

    def build_graph(self) -> dict[str, Any]:
        # Add entry/exit sentinels
        all_ids = {n["id"] for n in self.nodes}
        edge_targets = {e["target"] for e in self.edges}
        edge_sources = {e["source"] for e in self.edges}

        if "__start__" not in all_ids:
            self.nodes.insert(0, {"id": "__start__", "kind": "entry", "label": "start", "tools": []})
        if "__end__" not in all_ids and "__end__" in edge_targets:
            self.nodes.append({"id": "__end__", "kind": "exit", "label": "end", "tools": []})

        # Handle END sentinel references in edges
        for e in self.edges:
            if e["target"] == "END":
                e["target"] = "__end__"
            if e["source"] == "START":
                e["source"] = "__start__"

        exit_ids = [n["id"] for n in self.nodes if n["kind"] == "exit"]
        return {
            "name": "extracted",
            "framework": "langgraph",
            "entry_id": "__start__",
            "exit_ids": exit_ids,
            "nodes": self.nodes,
            "edges": self.edges,
        }


class _CrewAIVisitor(ast.NodeVisitor):
    """Extract tasks and agents from CrewAI source."""

    def __init__(self) -> None:
        self.tasks: list[dict[str, Any]] = []
        self.agents: list[str] = []
        self.process: str = "sequential"
        self._var_tasks: dict[str, str] = {}  # variable name -> task name

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        if isinstance(node.value, ast.Call):
            func = node.value.func
            cls_name = None
            if isinstance(func, ast.Name):
                cls_name = func.id
            elif isinstance(func, ast.Attribute):
                cls_name = func.attr

            if cls_name == "Task":
                task_name = None
                tools: list[str] = []
                for kw in node.value.keywords:
                    if kw.arg == "description":
                        task_name = _str_value(kw.value)
                    elif kw.arg == "tools":
                        tools = _list_of_names(kw.value)
                if not task_name and node.targets:
                    task_name = _str_value(node.targets[0])
                if task_name:
                    self.tasks.append({"name": task_name, "tools": tools})
                    if node.targets and isinstance(node.targets[0], ast.Name):
                        self._var_tasks[node.targets[0].id] = task_name

            elif cls_name == "Crew":
                for kw in node.value.keywords:
                    if kw.arg == "process" and isinstance(kw.value, ast.Attribute):
                        self.process = kw.value.attr

        self.generic_visit(node)

    def build_graph(self) -> dict[str, Any]:
        nodes = [{"id": "__start__", "kind": "entry", "label": "start", "tools": []}]
        edges: list[dict[str, Any]] = []

        for i, task in enumerate(self.tasks):
            node_id = task["name"][:50].replace(" ", "_").lower()
            kind = "tool" if task["tools"] else "llm"
            nodes.append({"id": node_id, "kind": kind, "label": task["name"][:50], "tools": task["tools"]})

            if i == 0:
                edges.append({"source": "__start__", "target": node_id, "kind": "direct"})
            else:
                prev_id = nodes[-2]["id"]
                edges.append({"source": prev_id, "target": node_id, "kind": "direct"})

        nodes.append({"id": "__end__", "kind": "exit", "label": "end", "tools": []})
        if nodes:
            edges.append({"source": nodes[-2]["id"], "target": "__end__", "kind": "direct"})

        return {
            "name": "extracted",
            "framework": "crewai",
            "entry_id": "__start__",
            "exit_ids": ["__end__"],
            "nodes": nodes,
            "edges": edges,
        }


class _AutoGenVisitor(ast.NodeVisitor):
    """Extract agent lists from AutoGen GroupChat patterns."""

    def __init__(self) -> None:
        self.agents: list[str] = []
        self.chat_type: str = "groupchat"

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func
        cls_name = None
        if isinstance(func, ast.Name):
            cls_name = func.id
        elif isinstance(func, ast.Attribute):
            cls_name = func.attr

        if cls_name in ("RoundRobinGroupChat", "SelectorGroupChat", "GroupChat"):
            self.chat_type = cls_name.lower()
            # Look for participants/agents arg
            for kw in node.keywords:
                if kw.arg in ("participants", "agents"):
                    self.agents = _list_of_names(kw.value)
            if not self.agents and node.args:
                self.agents = _list_of_names(node.args[0])

        self.generic_visit(node)

    def build_graph(self) -> dict[str, Any]:
        nodes = [{"id": "__start__", "kind": "entry", "label": "start", "tools": []}]
        edges: list[dict[str, Any]] = []

        for i, agent in enumerate(self.agents):
            kind = "human" if "user" in agent.lower() or "human" in agent.lower() else "llm"
            nodes.append({"id": agent, "kind": kind, "label": agent, "tools": []})
            if i == 0:
                edges.append({"source": "__start__", "target": agent, "kind": "direct"})
            else:
                prev = self.agents[i - 1]
                edges.append({"source": prev, "target": agent, "kind": "direct"})

        # For round-robin, add loop edge
        if "roundrobin" in self.chat_type and len(self.agents) >= 2:
            edges.append({"source": self.agents[-1], "target": self.agents[0], "kind": "loop"})

        nodes.append({"id": "__end__", "kind": "exit", "label": "end", "tools": []})
        if self.agents:
            edges.append({"source": self.agents[-1], "target": "__end__", "kind": "direct"})

        return {
            "name": "extracted",
            "framework": "autogen",
            "entry_id": "__start__",
            "exit_ids": ["__end__"],
            "nodes": nodes,
            "edges": edges,
        }


class _ADKVisitor(ast.NodeVisitor):
    """Extract agent hierarchy from Google ADK patterns."""

    def __init__(self) -> None:
        self.agents: list[dict[str, Any]] = []
        self.root_type: str = "sequential"

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func
        cls_name = None
        if isinstance(func, ast.Name):
            cls_name = func.id
        elif isinstance(func, ast.Attribute):
            cls_name = func.attr

        if cls_name in ("SequentialAgent", "ParallelAgent", "LoopAgent"):
            self.root_type = cls_name.lower().replace("agent", "")
            for kw in node.keywords:
                if kw.arg == "sub_agents":
                    self.agents = [
                        {"name": _str_value(elt) or f"agent_{i}", "kind": "llm"}
                        for i, elt in enumerate(kw.value.elts)
                    ] if isinstance(kw.value, (ast.List, ast.Tuple)) else []
                elif kw.arg == "name":
                    pass  # root agent name

        self.generic_visit(node)

    def build_graph(self) -> dict[str, Any]:
        nodes = [{"id": "__start__", "kind": "entry", "label": "start", "tools": []}]
        edges: list[dict[str, Any]] = []

        for i, agent in enumerate(self.agents):
            name = agent["name"]
            nodes.append({"id": name, "kind": agent["kind"], "label": name, "tools": []})
            if self.root_type == "sequential":
                if i == 0:
                    edges.append({"source": "__start__", "target": name, "kind": "direct"})
                else:
                    prev = self.agents[i - 1]["name"]
                    edges.append({"source": prev, "target": name, "kind": "direct"})
            elif self.root_type == "parallel":
                edges.append({"source": "__start__", "target": name, "kind": "parallel"})

        nodes.append({"id": "__end__", "kind": "exit", "label": "end", "tools": []})
        if self.agents:
            if self.root_type == "sequential":
                edges.append({"source": self.agents[-1]["name"], "target": "__end__", "kind": "direct"})
            elif self.root_type == "parallel":
                for agent in self.agents:
                    edges.append({"source": agent["name"], "target": "__end__", "kind": "direct"})

        return {
            "name": "extracted",
            "framework": "adk",
            "entry_id": "__start__",
            "exit_ids": ["__end__"],
            "nodes": nodes,
            "edges": edges,
        }


_VISITORS: dict[str, type] = {
    "langgraph": _LangGraphVisitor,
    "crewai": _CrewAIVisitor,
    "autogen": _AutoGenVisitor,
    "adk": _ADKVisitor,
}


def extract_graph_from_source(file_path: Path, framework: str) -> dict[str, Any] | None:
    """Parse a Python file and extract an AgentGraph dict using AST analysis."""
    try:
        source = file_path.read_text(errors="ignore")
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return None

    visitor_cls = _VISITORS.get(framework)
    if visitor_cls is None:
        return None

    visitor = visitor_cls()
    visitor.visit(tree)
    graph = visitor.build_graph()

    # Validate: must have at least 2 nodes (entry + one real node) and 1 edge
    real_nodes = [n for n in graph["nodes"] if n["kind"] not in ("entry", "exit")]
    if len(real_nodes) < 1 or len(graph["edges"]) < 1:
        return None

    # Set name from filename
    graph["name"] = file_path.stem
    return graph


def main():
    """CLI: extract a single file for testing."""
    if len(sys.argv) < 3:
        print("Usage: python ast_extractor.py <file.py> <framework>")
        print("  framework: langgraph | crewai | autogen | adk")
        sys.exit(1)

    path = Path(sys.argv[1])
    fw = sys.argv[2]
    result = extract_graph_from_source(path, fw)
    if result:
        print(json.dumps(result, indent=2))
    else:
        print("No graph extracted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
