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


# Provenance vocabulary mirrors agentproof.graph.model.VALID_ORIGINS /
# VALID_CONFIDENCES:
#   ast_explicit/exact   - parsed from an explicit call (add_edge, Task(...), ...)
#   ast_inferred/may     - real element, ordering/connectivity inferred
#   synthesized/heuristic - fabricated entry/exit sentinels and their hookups
# For nodes, confidence covers the WEAKEST attribute claim (kind, tool
# bindings), not existence: a kind guessed from a name substring makes the
# node ast_explicit/may even though the add_node call itself is explicit.


def _span(filename: str, node: ast.AST) -> str:
    """Format a "file:start_line:end_line" span for an AST node, or ""."""
    lineno = getattr(node, "lineno", None)
    if not filename or lineno is None:
        return ""
    end_lineno = getattr(node, "end_lineno", None) or lineno
    return f"{filename}:{lineno}:{end_lineno}"


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


def _metadata_tools(call: ast.Call) -> list[str]:
    """Extract tool names declared syntactically in an add_node call.

    Recognizes only the explicit literal shape
    ``add_node(..., metadata={"tools": [name1, "name2"]})`` where each entry
    is a Name node or a string literal.  Deeper inference (bind_tools /
    ToolNode dataflow) is deliberately out of scope.
    """
    for kw in call.keywords:
        if kw.arg == "metadata" and isinstance(kw.value, ast.Dict):
            for key, val in zip(kw.value.keys, kw.value.values):
                if isinstance(key, ast.Constant) and key.value == "tools":
                    return _list_of_names(val)
    return []


class _LangGraphVisitor(ast.NodeVisitor):
    """Extract nodes and edges from LangGraph StateGraph calls."""

    def __init__(self, filename: str = "") -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self._node_ids: set[str] = set()
        self._filename = filename

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func
        method = None
        if isinstance(func, ast.Attribute):
            method = func.attr
        span = _span(self._filename, node)

        if method == "add_node" and node.args:
            name = _str_value(node.args[0])
            if name and name not in self._node_ids:
                self._node_ids.add(name)
                # Tool bindings declared syntactically in the call itself:
                # add_node(..., metadata={"tools": [...]}).
                tools = _metadata_tools(node)
                kind_guessed = False
                if tools:
                    # Kind derived from a declared tool binding, not a guess.
                    kind = "tool"
                else:
                    kind = "llm"
                    if "human" in name.lower():
                        kind, kind_guessed = "human", True
                    elif "tool" in name.lower():
                        kind, kind_guessed = "tool", True
                    elif "route" in name.lower() or "router" in name.lower():
                        kind, kind_guessed = "router", True
                # Node existence is explicit in an add_node call (hence
                # origin=ast_explicit), but confidence covers the WEAKEST
                # attribute claim -- kind and tool bindings -- not existence.
                # A kind guessed from a name substring downgrades the node to
                # "may"; a kind derived from a declared binding stays "exact".
                self.nodes.append({
                    "id": name, "kind": kind, "label": name, "tools": tools,
                    "origin": "ast_explicit",
                    "confidence": "may" if kind_guessed else "exact",
                    "source_span": span,
                })

        elif method == "add_edge" and len(node.args) >= 2:
            src = _str_value(node.args[0])
            dst = _str_value(node.args[1])
            if src and dst:
                self.edges.append({
                    "source": src, "target": dst, "kind": "direct",
                    "origin": "ast_explicit", "confidence": "exact", "source_span": span,
                })

        elif method == "add_conditional_edges" and node.args:
            src = _str_value(node.args[0])
            if src:
                # Mark source as router if not already.  The
                # add_conditional_edges call declares the routing role, so
                # the kind now comes from declared structure (not a name
                # guess) -> the node can be exact again.
                for n in self.nodes:
                    if n["id"] == src:
                        n["kind"] = "router"
                        n["confidence"] = "exact"
                # Collect the path map from any of its accepted spellings:
                #   add_conditional_edges(src, {...})              2-arg dict
                #   add_conditional_edges(src, path, {...})        standard 3-arg form
                #   add_conditional_edges(src, path, path_map={...})
                path_maps: list[ast.Dict] = []
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Dict):
                    path_maps.append(node.args[1])
                if len(node.args) >= 3 and isinstance(node.args[2], ast.Dict):
                    path_maps.append(node.args[2])
                for kw in node.keywords:
                    if kw.arg == "path_map" and isinstance(kw.value, ast.Dict):
                        path_maps.append(kw.value)
                # Targets listed in an explicit dict/path_map are declared in
                # source -> ast_explicit/exact.  Deliberate asymmetry with the
                # runtime extractor, which tags conditional edges "may": the
                # AST sees the literal path_map dict the author declared,
                # while a compiled graph object cannot distinguish declared
                # targets from LangGraph's own over-approximation to all nodes.
                for pm in path_maps:
                    for val in pm.values:
                        dst = _str_value(val)
                        if dst:
                            self.edges.append({
                                "source": src, "target": dst, "kind": "conditional",
                                "origin": "ast_explicit", "confidence": "exact",
                                "source_span": span,
                            })

        elif method == "set_entry_point" and node.args:
            src = _str_value(node.args[0])
            if src:
                self.edges.append({
                    "source": "__start__", "target": src, "kind": "direct",
                    "origin": "ast_explicit", "confidence": "exact", "source_span": span,
                })

        elif method == "set_finish_point" and node.args:
            dst = _str_value(node.args[0])
            if dst:
                self.edges.append({
                    "source": dst, "target": "__end__", "kind": "direct",
                    "origin": "ast_explicit", "confidence": "exact", "source_span": span,
                })

        self.generic_visit(node)

    def build_graph(self) -> dict[str, Any]:
        # Normalize sentinel references in edges FIRST so exit detection sees them.
        # LangGraph code commonly writes add_edge(node, END) / add_edge(START, node),
        # where END/START are imported names that stringify to "END"/"START".
        for e in self.edges:
            if e["target"] in ("END", "__end__"):
                e["target"] = "__end__"
            if e["source"] in ("START", "__start__"):
                e["source"] = "__start__"

        # Add entry/exit sentinels
        all_ids = {n["id"] for n in self.nodes}
        edge_targets = {e["target"] for e in self.edges}
        edge_sources = {e["source"] for e in self.edges}

        # Sentinel entry/exit nodes are fabricated by the extractor (even if
        # START/END are referenced by explicit edges) -> synthesized/heuristic.
        if "__start__" not in all_ids:
            self.nodes.insert(0, {
                "id": "__start__", "kind": "entry", "label": "start", "tools": [],
                "origin": "synthesized", "confidence": "heuristic", "source_span": "",
            })
        if "__end__" not in all_ids and "__end__" in edge_targets:
            self.nodes.append({
                "id": "__end__", "kind": "exit", "label": "end", "tools": [],
                "origin": "synthesized", "confidence": "heuristic", "source_span": "",
            })

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

    def __init__(self, filename: str = "") -> None:
        self.tasks: list[dict[str, Any]] = []
        self.agents: list[str] = []
        self.process: str = "sequential"
        self._var_tasks: dict[str, str] = {}  # variable name -> task name
        self._filename = filename

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
                    self.tasks.append({
                        "name": task_name,
                        "tools": tools,
                        "span": _span(self._filename, node),
                    })
                    if node.targets and isinstance(node.targets[0], ast.Name):
                        self._var_tasks[node.targets[0].id] = task_name

            elif cls_name == "Crew":
                for kw in node.value.keywords:
                    if kw.arg == "process" and isinstance(kw.value, ast.Attribute):
                        self.process = kw.value.attr

        self.generic_visit(node)

    def build_graph(self) -> dict[str, Any]:
        nodes = [{
            "id": "__start__", "kind": "entry", "label": "start", "tools": [],
            "origin": "synthesized", "confidence": "heuristic", "source_span": "",
        }]
        edges: list[dict[str, Any]] = []

        for i, task in enumerate(self.tasks):
            node_id = task["name"][:50].replace(" ", "_").lower()
            kind = "tool" if task["tools"] else "llm"
            # Task nodes are parsed from explicit Task(...) constructor calls.
            nodes.append({
                "id": node_id, "kind": kind, "label": task["name"][:50],
                "tools": task["tools"],
                "origin": "ast_explicit", "confidence": "exact",
                "source_span": task.get("span", ""),
            })

            if i == 0:
                # Connection to the fabricated entry sentinel.
                edges.append({
                    "source": "__start__", "target": node_id, "kind": "direct",
                    "origin": "synthesized", "confidence": "heuristic", "source_span": "",
                })
            else:
                # Ordering assumed from task declaration order (sequential
                # process is not verified) -> inferred.
                prev_id = nodes[-2]["id"]
                edges.append({
                    "source": prev_id, "target": node_id, "kind": "direct",
                    "origin": "ast_inferred", "confidence": "may", "source_span": "",
                })

        nodes.append({
            "id": "__end__", "kind": "exit", "label": "end", "tools": [],
            "origin": "synthesized", "confidence": "heuristic", "source_span": "",
        })
        if nodes:
            edges.append({
                "source": nodes[-2]["id"], "target": "__end__", "kind": "direct",
                "origin": "synthesized", "confidence": "heuristic", "source_span": "",
            })

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

    def __init__(self, filename: str = "") -> None:
        self.agents: list[str] = []
        self.chat_type: str = "groupchat"
        self._filename = filename
        self._span: str = ""

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func
        cls_name = None
        if isinstance(func, ast.Name):
            cls_name = func.id
        elif isinstance(func, ast.Attribute):
            cls_name = func.attr

        if cls_name in ("RoundRobinGroupChat", "SelectorGroupChat", "GroupChat"):
            self.chat_type = cls_name.lower()
            self._span = _span(self._filename, node)
            # Look for participants/agents arg
            for kw in node.keywords:
                if kw.arg in ("participants", "agents"):
                    self.agents = _list_of_names(kw.value)
            if not self.agents and node.args:
                self.agents = _list_of_names(node.args[0])

        self.generic_visit(node)

    def build_graph(self) -> dict[str, Any]:
        nodes = [{
            "id": "__start__", "kind": "entry", "label": "start", "tools": [],
            "origin": "synthesized", "confidence": "heuristic", "source_span": "",
        }]
        edges: list[dict[str, Any]] = []

        for i, agent in enumerate(self.agents):
            kind = "human" if "user" in agent.lower() or "human" in agent.lower() else "llm"
            # Agent names are listed explicitly in the group-chat constructor.
            nodes.append({
                "id": agent, "kind": kind, "label": agent, "tools": [],
                "origin": "ast_explicit", "confidence": "exact",
                "source_span": self._span,
            })
            if i == 0:
                edges.append({
                    "source": "__start__", "target": agent, "kind": "direct",
                    "origin": "synthesized", "confidence": "heuristic", "source_span": "",
                })
            else:
                # Speaking order assumed from participant declaration order.
                prev = self.agents[i - 1]
                edges.append({
                    "source": prev, "target": agent, "kind": "direct",
                    "origin": "ast_inferred", "confidence": "may", "source_span": "",
                })

        # For round-robin, add loop edge (cyclic order inferred from semantics)
        if "roundrobin" in self.chat_type and len(self.agents) >= 2:
            edges.append({
                "source": self.agents[-1], "target": self.agents[0], "kind": "loop",
                "origin": "ast_inferred", "confidence": "may", "source_span": "",
            })

        nodes.append({
            "id": "__end__", "kind": "exit", "label": "end", "tools": [],
            "origin": "synthesized", "confidence": "heuristic", "source_span": "",
        })
        if self.agents:
            edges.append({
                "source": self.agents[-1], "target": "__end__", "kind": "direct",
                "origin": "synthesized", "confidence": "heuristic", "source_span": "",
            })

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

    def __init__(self, filename: str = "") -> None:
        self.agents: list[dict[str, Any]] = []
        self.root_type: str = "sequential"
        self._filename = filename

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
                        {
                            "name": _str_value(elt) or f"agent_{i}",
                            "kind": "llm",
                            "span": _span(self._filename, elt),
                        }
                        for i, elt in enumerate(kw.value.elts)
                    ] if isinstance(kw.value, (ast.List, ast.Tuple)) else []
                elif kw.arg == "name":
                    pass  # root agent name

        self.generic_visit(node)

    def build_graph(self) -> dict[str, Any]:
        nodes = [{
            "id": "__start__", "kind": "entry", "label": "start", "tools": [],
            "origin": "synthesized", "confidence": "heuristic", "source_span": "",
        }]
        edges: list[dict[str, Any]] = []

        for i, agent in enumerate(self.agents):
            name = agent["name"]
            # Sub-agents are listed explicitly in the composite constructor.
            nodes.append({
                "id": name, "kind": agent["kind"], "label": name, "tools": [],
                "origin": "ast_explicit", "confidence": "exact",
                "source_span": agent.get("span", ""),
            })
            if self.root_type in ("sequential", "loop"):
                # LoopAgent children run in declared order like a
                # SequentialAgent's, then repeat (loop-back edge added below).
                if i == 0:
                    edges.append({
                        "source": "__start__", "target": name, "kind": "direct",
                        "origin": "synthesized", "confidence": "heuristic", "source_span": "",
                    })
                else:
                    # Ordering inferred from Sequential/LoopAgent child order.
                    prev = self.agents[i - 1]["name"]
                    edges.append({
                        "source": prev, "target": name, "kind": "direct",
                        "origin": "ast_inferred", "confidence": "may", "source_span": "",
                    })
            elif self.root_type == "parallel":
                # Fan-out from the fabricated entry sentinel.
                edges.append({
                    "source": "__start__", "target": name, "kind": "parallel",
                    "origin": "synthesized", "confidence": "heuristic", "source_span": "",
                })

        nodes.append({
            "id": "__end__", "kind": "exit", "label": "end", "tools": [],
            "origin": "synthesized", "confidence": "heuristic", "source_span": "",
        })
        if self.agents:
            if self.root_type == "loop":
                # LoopAgent semantics: children run in order, repeating.
                # Loop-back from the last child to the first (a self-loop for
                # a single child) is inferred from those semantics.
                edges.append({
                    "source": self.agents[-1]["name"],
                    "target": self.agents[0]["name"], "kind": "loop",
                    "origin": "ast_inferred", "confidence": "may", "source_span": "",
                })
            if self.root_type in ("sequential", "loop"):
                edges.append({
                    "source": self.agents[-1]["name"], "target": "__end__", "kind": "direct",
                    "origin": "synthesized", "confidence": "heuristic", "source_span": "",
                })
            elif self.root_type == "parallel":
                for agent in self.agents:
                    edges.append({
                        "source": agent["name"], "target": "__end__", "kind": "direct",
                        "origin": "synthesized", "confidence": "heuristic", "source_span": "",
                    })

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

    visitor = visitor_cls(str(file_path))
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
