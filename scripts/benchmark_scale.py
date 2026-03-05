#!/usr/bin/env python3
"""Scalability benchmarks: measure structural check and monitor performance at scale.

Generates synthetic AgentGraph instances at various sizes and measures:
  - Structural check time (all 5 checks)
  - Temporal monitor compilation time
  - Temporal monitor evaluation time (per 1000-event trace)

Usage:
    python scripts/benchmark_scale.py [--output results/scaling.json]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from pathlib import Path

from agentproof.graph.model import (
    AgentGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)
from agentproof.monitor.ltl import (
    MonitorRuleSpec,
    compile_monitor_rule,
    evaluate_monitors,
)
from agentproof.verify import run_structural_checks


# ---------------------------------------------------------------------------
# Synthetic graph generation
# ---------------------------------------------------------------------------

NODE_KINDS = [NodeKind.LLM, NodeKind.TOOL, NodeKind.ROUTER, NodeKind.HUMAN]
NODE_KIND_WEIGHTS = [0.4, 0.3, 0.2, 0.1]
EDGE_KINDS = [EdgeKind.DIRECT, EdgeKind.CONDITIONAL]


def generate_random_graph(n_nodes: int, edge_density: float = 2.0, seed: int = 42) -> AgentGraph:
    """Generate a random AgentGraph with *n_nodes* interior nodes.

    Parameters
    ----------
    n_nodes : int
        Number of interior (non-entry/exit) nodes.
    edge_density : float
        Average number of outgoing edges per node.
    seed : int
        Random seed for reproducibility.
    """
    rng = random.Random(seed)

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    entry = GraphNode("__start__", NodeKind.ENTRY)
    exit_node = GraphNode("__end__", NodeKind.EXIT)
    nodes.append(entry)

    interior_ids: list[str] = []
    for i in range(n_nodes):
        kind = rng.choices(NODE_KINDS, weights=NODE_KIND_WEIGHTS, k=1)[0]
        tools = (f"tool_{i}",) if kind == NodeKind.TOOL else ()
        node = GraphNode(f"n{i}", kind, label=f"node_{i}", tools=tools)
        nodes.append(node)
        interior_ids.append(node.id)

    nodes.append(exit_node)

    # Connect entry to first few nodes
    for nid in interior_ids[:min(3, len(interior_ids))]:
        ek = EdgeKind.CONDITIONAL if rng.random() < 0.3 else EdgeKind.DIRECT
        edges.append(GraphEdge("__start__", nid, kind=ek))

    # Create random edges ensuring connectivity
    target_edges = int(n_nodes * edge_density)
    for _ in range(target_edges):
        src = rng.choice(interior_ids)
        tgt = rng.choice(interior_ids + ["__end__"])
        if src != tgt:
            ek = EdgeKind.CONDITIONAL if rng.random() < 0.2 else EdgeKind.DIRECT
            edges.append(GraphEdge(src, tgt, kind=ek))

    # Ensure some nodes connect to exit
    leaves = [nid for nid in interior_ids if not any(e.source == nid for e in edges)]
    for leaf in leaves:
        edges.append(GraphEdge(leaf, "__end__"))

    # Deduplicate edges
    seen: set[tuple[str, str]] = set()
    unique_edges: list[GraphEdge] = []
    for e in edges:
        key = (e.source, e.target)
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)

    return AgentGraph(
        name=f"synthetic_{n_nodes}",
        framework="synthetic",
        nodes=tuple(nodes),
        edges=tuple(unique_edges),
        entry_id="__start__",
        exit_ids=("__end__",),
    )


# ---------------------------------------------------------------------------
# Benchmark runners
# ---------------------------------------------------------------------------

MONITOR_RULES = [
    MonitorRuleSpec("forbidden", "G !tool:dangerous_tool", on_violation="halt"),
    MonitorRuleSpec("response", "decision:deploy -> F action:approve", on_violation="block"),
    MonitorRuleSpec("until", "read_only U action:signoff", on_violation="block"),
    MonitorRuleSpec("bounded", "decision:start -> F[<=5] action:complete", on_violation="warn"),
    MonitorRuleSpec("conj", "(G !tool:drop_db) AND (G !tool:rm_rf)", on_violation="escalate"),
]


def benchmark_structural(graph: AgentGraph, n_trials: int = 10) -> float:
    """Return median structural check time in seconds."""
    times = []
    for _ in range(n_trials):
        start = time.perf_counter()
        run_structural_checks(graph, require_human=True)
        times.append(time.perf_counter() - start)
    return statistics.median(times)


def benchmark_monitor_compile(n_trials: int = 10) -> float:
    """Return median compilation time for all rules in seconds."""
    times = []
    for _ in range(n_trials):
        start = time.perf_counter()
        for rule in MONITOR_RULES:
            compile_monitor_rule(rule)
        times.append(time.perf_counter() - start)
    return statistics.median(times)


def benchmark_monitor_eval(n_events: int = 1000, n_trials: int = 10) -> float:
    """Return median evaluation time for a synthetic event stream in seconds."""
    compiled = tuple(compile_monitor_rule(r) for r in MONITOR_RULES)

    # Pre-generate event stream
    rng = random.Random(123)
    event_pool = [
        {"tool_name": "read"},
        {"tool_name": "write"},
        {"tool_name": "dangerous_tool"},
        {"decision": "deploy"},
        {"action_type": "approve"},
        {"action_type": "signoff"},
        {"tags": ["read_only"]},
        {"decision": "start"},
        {"action_type": "complete"},
        {},
    ]
    events = [rng.choice(event_pool) for _ in range(n_events)]

    times = []
    for _ in range(n_trials):
        state: dict[str, int] = {}
        start = time.perf_counter()
        for event in events:
            state, _, _ = evaluate_monitors(compiled, state, event)
        times.append(time.perf_counter() - start)
    return statistics.median(times)


def run_benchmarks(sizes: list[int], n_trials: int, n_events: int) -> list[dict]:
    results = []

    # Monitor compilation (size-independent)
    compile_time = benchmark_monitor_compile(n_trials=n_trials)
    print(f"Monitor compilation (5 rules): {compile_time*1000:.3f} ms")

    # Monitor evaluation (size-independent)
    eval_time = benchmark_monitor_eval(n_events=n_events, n_trials=n_trials)
    print(f"Monitor evaluation ({n_events} events x 5 rules): {eval_time*1000:.3f} ms "
          f"({n_events/eval_time:.0f} events/s)")

    for n in sizes:
        print(f"\n--- {n} nodes ---")
        graph = generate_random_graph(n)
        print(f"  Nodes: {len(graph.nodes)}, Edges: {len(graph.edges)}")

        struct_time = benchmark_structural(graph, n_trials=n_trials)
        print(f"  Structural checks: {struct_time*1000:.3f} ms")

        results.append({
            "n_nodes": n,
            "actual_nodes": len(graph.nodes),
            "actual_edges": len(graph.edges),
            "structural_check_ms": round(struct_time * 1000, 4),
            "monitor_compile_ms": round(compile_time * 1000, 4),
            "monitor_eval_ms": round(eval_time * 1000, 4),
            "monitor_events_per_sec": round(n_events / eval_time),
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="AgentProof scalability benchmarks")
    parser.add_argument("--output", type=str, default="scripts/scaling_results.json")
    parser.add_argument("--trials", type=int, default=10)
    parser.add_argument("--events", type=int, default=1000)
    args = parser.parse_args()

    sizes = [50, 100, 200, 500, 1000, 2000, 5000]
    results = run_benchmarks(sizes, n_trials=args.trials, n_events=args.events)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2))
    print(f"\nResults written to {output_path}")


if __name__ == "__main__":
    main()
