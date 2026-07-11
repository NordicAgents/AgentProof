#!/usr/bin/env python3
"""Generate LaTeX comparison table: Agentproof vs general-purpose model checkers.

Usage:
    python scripts/generate_comparison_table.py [--output papers/paper1/generated/comparison_table.tex]
"""

from __future__ import annotations

import argparse
from pathlib import Path

COMPARISON_DATA = [
    {
        "tool": "SPIN",
        "input": "Promela (manual)",
        "properties": "Full LTL",
        "modeling": "High",
        "time": "Fast (small)",
        "domain": "None",
        "cite": r"\citep{holzmann1997spin}",
    },
    {
        "tool": "NuSMV",
        "input": "SMV (manual)",
        "properties": "CTL + LTL",
        "modeling": "High",
        "time": "Fast (small)",
        "domain": "None",
        "cite": r"\citep{cimatti2002nusmv}",
    },
    {
        "tool": "CBMC",
        "input": "C source",
        "properties": "Assertions",
        "modeling": "Medium",
        "time": "Bounded",
        "domain": "None",
        "cite": r"\citep{cbmc}",
    },
    {
        "tool": r"\textbf{Agentproof}",
        "input": "Auto-extracted",
        "properties": "Safety LTL fragment",
        "modeling": r"\textbf{None}",
        "time": r"$O(|V|{+}|E|)$",
        "domain": r"\textbf{Agent workflows}",
        "cite": "",
    },
]


def generate_latex_table() -> str:
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        r"\caption{Comparison with general-purpose model checkers.}",
        r"\label{tab:comparison_mc}",
        r"\begin{tabular}{@{}lllllll@{}}",
        r"\toprule",
        r"\textbf{Tool} & \textbf{Input} & \textbf{Properties} & "
        r"\textbf{Modeling} & \textbf{Time} & \textbf{Domain} \\",
        r"\midrule",
    ]

    for row in COMPARISON_DATA:
        line = (
            f"{row['tool']} & {row['input']} & {row['properties']} & "
            f"{row['modeling']} & {row['time']} & {row['domain']} \\\\"
        )
        lines.append(line)

    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\par\smallskip",
        r"\raggedright\footnotesize",
        r"SPIN, NuSMV, and CBMC require manual translation of agent workflows into "
        r"their input languages. Agentproof extracts models automatically from "
        r"framework APIs, eliminating the modeling step entirely.",
        r"\end{table}",
    ])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate model checker comparison table")
    parser.add_argument("--output", type=str,
                        default="papers/paper1/generated/comparison_table.tex")
    args = parser.parse_args()

    table = generate_latex_table()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(table)
    print(f"Table written to {output_path}")
    print(table)


if __name__ == "__main__":
    main()
