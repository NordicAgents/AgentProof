#!/usr/bin/env python3
"""Generate synthetic execution traces from corpus workflow graphs.

Uses random walks on each graph to produce event traces suitable for
temporal policy evaluation.

Usage:
    python scripts/generate_traces.py [--corpus corpus/curated] [--output corpus/traces] [--n-traces 10]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentproof.api import generate_traces
from agentproof.graph.model import graph_from_dict


def main():
    parser = argparse.ArgumentParser(description="Generate execution traces from workflows")
    parser.add_argument("--corpus", type=str, default="corpus/curated")
    parser.add_argument("--output", type=str, default="corpus/traces")
    parser.add_argument("--n-traces", type=int, default=10,
                        help="Number of traces per workflow")
    parser.add_argument("--max-steps", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    corpus_dir = Path(args.corpus)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    total_traces = 0

    for path in sorted(corpus_dir.glob("*.json")):
        data = json.loads(path.read_text())
        graph = graph_from_dict(data)

        traces = generate_traces(
            graph,
            n_traces=args.n_traces,
            max_steps=args.max_steps,
            seed=args.seed,
        )

        out_path = output_dir / f"{path.stem}_traces.json"
        out_path.write_text(json.dumps({
            "workflow": graph.name,
            "framework": graph.framework,
            "n_traces": len(traces),
            "traces": traces,
        }, indent=2))

        total_traces += len(traces)
        avg_len = sum(len(t) for t in traces) / len(traces) if traces else 0
        print(f"  {graph.name}: {len(traces)} traces, avg length {avg_len:.1f}")

    print(f"\nGenerated {total_traces} traces → {output_dir}/")


if __name__ == "__main__":
    main()
