#!/usr/bin/env python3
"""Runtime-extractor vs AST-fallback fidelity, on trusted runnable workflows.

The runtime extractors read the *compiled* framework object (the true topology
the framework will execute), so on a runnable workflow they are faithful by
construction. The AST fallback (used for large-scale mining of untrusted code)
approximates the same graph from source. This script quantifies the gap by
treating the runtime extraction as the reference and measuring how many of its
edges/nodes the AST fallback recovers.

SAFETY: this runs only the repository's own author-written examples, never
untrusted mined code. Measuring runtime fidelity on the mined corpus would
require executing arbitrary GitHub code in a sandbox (future work).

Usage:
    python scripts/runtime_fidelity.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from agentproof.graph import extract_langgraph, extract_crewai, extract_adk
from agentproof.graph.model import graph_to_dict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ast_extractor import extract_graph_from_source  # noqa: E402
from extractor_accuracy import compute_accuracy  # noqa: E402

# (source, build-function, runtime-extractor, framework)
EXPERIMENTS = [
    ("examples/langgraph_incident_response.py", "build_incident_response_graph", extract_langgraph, "langgraph"),
    ("examples/langgraph_customer_support.py", "build_customer_support_graph", extract_langgraph, "langgraph"),
    ("examples/crewai_research_crew.py", "build_research_crew", extract_crewai, "crewai"),
    ("examples/adk_compliance_pipeline.py", "build_compliance_pipeline", extract_adk, "adk"),
    ("examples/adk_pipeline.py", "build_pipeline", extract_adk, "adk"),
]


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> None:
    rows = []
    for src, fn, extractor, fw in EXPERIMENTS:
        p = Path(src)
        try:
            m = load_module(p)
            obj = getattr(m, fn)()
            runtime = graph_to_dict(extractor(obj))          # faithful reference
        except Exception as e:  # noqa: BLE001
            print(f"[skip] {src}: runtime build failed: {type(e).__name__}: {str(e)[:120]}")
            continue
        ast = extract_graph_from_source(p, fw)
        if ast is None:
            print(f"[skip] {src}: AST extraction returned nothing")
            continue
        acc = compute_accuracy(ast, runtime)   # ast vs runtime-as-ground-truth
        rt_ids = {n["id"] for n in runtime["nodes"]}
        ast_ids = {n["id"] for n in ast["nodes"]}
        rows.append({
            "workflow": p.stem, "framework": fw,
            "runtime_nodes": len(runtime["nodes"]), "runtime_edges": len(runtime["edges"]),
            "ast_nodes": len(ast["nodes"]), "ast_edges": len(ast["edges"]),
            "node_id_overlap": len(rt_ids & ast_ids), "node_id_union": len(rt_ids | ast_ids),
            "ast_edge_recall": acc["edge_detection"]["recall"],
            "ast_edge_precision": acc["edge_detection"]["precision"],
            "ast_node_recall": acc["node_detection"]["recall"],
            "ast_kind_acc": acc["node_kind_accuracy"],
        })
        print(f"[ok] {p.stem} ({fw}): runtime {len(runtime['edges'])} edges, "
              f"AST recovers edge-R={acc['edge_detection']['recall']:.2f} "
              f"node-R={acc['node_detection']['recall']:.2f} kind={acc['node_kind_accuracy']:.2f} "
              f"(id-overlap {len(rt_ids & ast_ids)}/{len(rt_ids | ast_ids)})")

    if not rows:
        print("no runnable workflows succeeded")
        return

    # aggregate only over workflows whose node-ids align (else edge comparison is meaningless)
    aligned = [r for r in rows if r["node_id_overlap"] / max(1, r["node_id_union"]) >= 0.6]
    def mean(xs):
        return round(sum(xs) / len(xs), 3) if xs else None
    summary = {
        "n_runnable": len(rows),
        "n_id_aligned": len(aligned),
        "runtime_is_reference": "runtime extractor reads the compiled object; fidelity 1.0 by construction",
        "ast_vs_runtime_aligned": {
            "edge_recall": mean([r["ast_edge_recall"] for r in aligned]),
            "edge_precision": mean([r["ast_edge_precision"] for r in aligned]),
            "node_recall": mean([r["ast_node_recall"] for r in aligned]),
            "kind_accuracy": mean([r["ast_kind_acc"] for r in aligned]),
        },
        "rows": rows,
    }
    Path("corpus/real_world/runtime_fidelity.json").write_text(json.dumps(summary, indent=2))
    a = summary["ast_vs_runtime_aligned"]
    print("=" * 62)
    print(f"RUNTIME (reference, faithful by construction): edge recall = 1.0")
    print(f"AST FALLBACK vs runtime ({len(aligned)} id-aligned workflows):")
    print(f"  edge recall {a['edge_recall']}  edge precision {a['edge_precision']}  "
          f"node recall {a['node_recall']}  kind acc {a['kind_accuracy']}")
    print("Written to corpus/real_world/runtime_fidelity.json")


if __name__ == "__main__":
    main()
