#!/usr/bin/env python3
"""Risk-aware human-gate check: gate only *sensitive* actions, not every workflow.

The naive human-presence check flags any workflow without a HUMAN node. On real
code it fires on ~91% of workflows, but triage showed ~91% of those firings are
intentional (read-only pipelines legitimately need no human review). The
risk-aware variant instead uses the existing sound coverage check
(``human_gate_coverage``): flag a workflow only when a *sensitive* tool is
reachable from entry without passing through a HUMAN node.

Sensitivity is decided by a keyword lexicon grounded in the tool names actually
observed in the corpora (destructive / write / exec / external-comms / financial).

Usage:
    python scripts/risk_aware_gate.py --corpus corpus/curated
    python scripts/risk_aware_gate.py --corpus corpus/real_world/graphs
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentproof.graph.model import graph_from_dict, NodeKind
from agentproof.verify import run_structural_checks

# Grounded in observed tool names; each key is a risk category, values are
# case-insensitive substrings that mark a genuinely side-effecting operation.
SENSITIVE_KEYWORDS: dict[str, list[str]] = {
    "destructive": ["delete", "drop", "remove", "rm_", "truncate", "purge",
                    "restart", "rollback", "revert", "kill", "terminate",
                    "shutdown", "revoke", "wipe", "reset"],
    "write":       ["insert", "update", "write", "create", "save", "commit",
                    "upsert", "put_", "_put", "persist"],
    "exec":        ["execute", "exec", "run_code", "run_pytest", "pytest",
                    "shell", "bash", "kubectl", "deploy", "apply", "provision"],
    "comms":       ["smtp", "send", "email", "mail", "sms", "slack", "tweet",
                    "post_", "publish", "social_media", "notify", "cms"],
    "financial":   ["bank", "trading", "trade", "brokerage", "payment", "pay_",
                    "charge", "refund", "transfer", "wire", "withdraw",
                    "credit_bureau", "invoice"],
}


def risk_category(tool: str) -> str | None:
    t = tool.lower()
    for cat, kws in SENSITIVE_KEYWORDS.items():
        if any(k in t for k in kws):
            return cat
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus/real_world/graphs")
    ap.add_argument("--output", default="corpus/real_world/risk_aware_gate.json")
    args = ap.parse_args()

    files = sorted(Path(args.corpus).glob("*.json"))
    n = 0
    naive_flag = 0             # no HUMAN node at all (require_human=True)
    has_sensitive = 0          # workflow declares >=1 sensitive tool
    risk_flag = 0              # sensitive tool reachable without a HUMAN gate
    gated_ok = 0               # has sensitive tool, but every sensitive path is gated
    cat_counts: dict[str, int] = {}
    flagged_examples: list[dict] = []

    for f in files:
        n += 1
        data = json.loads(f.read_text())
        graph = graph_from_dict(data)

        # sensitive tool names present in this workflow
        sens: set[str] = set()
        for node in graph.nodes:
            for t in node.tools:
                cat = risk_category(t)
                if cat:
                    sens.add(t)
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1

        # naive check: any HUMAN node present?
        naive = run_structural_checks(graph, require_human=True)
        naive_missing = not next(c for c in naive["checks"]
                                 if c["check_id"] == "human_presence")["passed"]
        if naive_missing:
            naive_flag += 1

        # risk-aware check: only if the workflow has a sensitive tool
        if sens:
            has_sensitive += 1
            rep = run_structural_checks(graph, require_human=False, sensitive_tools=sens)
            cov = next((c for c in rep["checks"] if c["check_id"] == "human_gate_coverage"), None)
            if cov and not cov["passed"]:
                risk_flag += 1
                if len(flagged_examples) < 12:
                    flagged_examples.append({
                        "workflow": graph.name, "framework": graph.framework,
                        "sensitive_tools": sorted(sens),
                        "ungated": cov["ungated_tools"],
                    })
            else:
                gated_ok += 1

    summary = {
        "corpus": args.corpus,
        "n_workflows": n,
        "naive_human_gate_flags": naive_flag,
        "naive_flag_pct": round(naive_flag * 100 / n, 1) if n else 0,
        "workflows_with_sensitive_tool": has_sensitive,
        "risk_aware_flags": risk_flag,
        "risk_aware_flag_pct": round(risk_flag * 100 / n, 1) if n else 0,
        "sensitive_gated_ok": gated_ok,
        "reduction_factor": round(naive_flag / risk_flag, 1) if risk_flag else None,
        "sensitive_by_category": cat_counts,
        "flagged_examples": flagged_examples,
    }
    Path(args.output).write_text(json.dumps(summary, indent=2))

    print("=" * 60)
    print(f"RISK-AWARE HUMAN-GATE  ({args.corpus}, {n} workflows)")
    print(f"  naive check (no HUMAN node):        {naive_flag:4d}  ({summary['naive_flag_pct']}%)")
    print(f"  workflows with a sensitive tool:    {has_sensitive:4d}")
    print(f"    - sensitive path is gated (pass): {gated_ok:4d}")
    print(f"    - sensitive path UNGATED (flag):  {risk_flag:4d}  ({summary['risk_aware_flag_pct']}%)")
    if summary["reduction_factor"]:
        print(f"  false-alarm reduction: {naive_flag} -> {risk_flag}  ({summary['reduction_factor']}x fewer flags)")
    print(f"  sensitive tools by category: {cat_counts}")
    if flagged_examples:
        print("  genuinely-flagged examples:")
        for e in flagged_examples[:6]:
            print(f"    {e['workflow']} ({e['framework']}): ungated {e['ungated']}")
    print(f"\nWritten to {summary and args.output}")


if __name__ == "__main__":
    main()
