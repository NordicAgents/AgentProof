#!/usr/bin/env python3
"""Generate scaling plots from benchmark results.

Usage:
    python scripts/plot_scaling.py [--input scripts/scaling_results.json] [--output paper/figures/scaling_plot.pdf]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    print("matplotlib not installed. Install with: pip install matplotlib")
    raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description="Plot AgentProof scaling results")
    parser.add_argument("--input", type=str, default="scripts/scaling_results.json")
    parser.add_argument("--output", type=str, default="paper/figures/scaling_plot.pdf")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text())

    nodes = [d["n_nodes"] for d in data]
    struct_ms = [d["structural_check_ms"] for d in data]

    fig, ax = plt.subplots(1, 1, figsize=(5, 3.5))

    ax.plot(nodes, struct_ms, "o-", color="#2563eb", linewidth=2, markersize=6, label="Structural checks")
    ax.set_xlabel("Number of nodes", fontsize=11)
    ax.set_ylabel("Time (ms)", fontsize=11)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_title("AgentProof Verification Time vs. Graph Size", fontsize=12)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=300, bbox_inches="tight")
    print(f"Plot saved to {output_path}")


if __name__ == "__main__":
    main()
