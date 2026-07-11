#!/usr/bin/env python3
"""Collect case study graph stats and microbenchmarks for the paper.

Outputs (JSON):
  - paper/generated/case_study_stats.json
  - paper/generated/bench_stats.json
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Callable

from agentproof.graph.model import AgentGraph, EdgeKind, NodeKind
from agentproof.monitor.ltl import MonitorRuleSpec, compile_monitor_rule, evaluate_monitors
from agentproof.verify import run_structural_checks


PAPER_DIR = Path(__file__).resolve().parents[1]
GENERATED_DIR = PAPER_DIR / "generated"
REPO_ROOT = PAPER_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _median_time_ms(fn: Callable[[], Any], runs: int, warmup: int) -> float:
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return float(statistics.median(samples))


def _kind_counts(items: list[Any], attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        key = getattr(it, attr)
        if hasattr(key, "value"):
            key = key.value
        out[str(key)] = out.get(str(key), 0) + 1
    return out


def _graph_stats(graph: AgentGraph) -> dict[str, Any]:
    return {
        "framework": graph.framework,
        "name": graph.name,
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "node_kind_counts": _kind_counts(list(graph.nodes), "kind"),
        "edge_kind_counts": _kind_counts(list(graph.edges), "kind"),
    }


@dataclass(frozen=True)
class CaseStudy:
    study_id: str
    label: str
    build_native: Callable[[], Any]
    extract_graph: Callable[[Any], AgentGraph]
    temporal_rules: tuple[MonitorRuleSpec, ...] = ()
    temporal_traces: dict[str, list[dict[str, Any]]] | None = None
    require_human: bool = True
    notes: str = ""


def _safe_import(module: str):
    try:
        return importlib.import_module(module)
    except Exception as e:  # noqa: BLE001 - treat any import failure as skip
        return e


def _case_studies() -> list[CaseStudy]:
    studies: list[CaseStudy] = []

    # LangGraph: incident response triage.
    ex_lg = _safe_import("examples.langgraph_incident_response")
    if not isinstance(ex_lg, Exception):
        from agentproof.graph import extract_langgraph

        compiled = ex_lg.build_incident_response_graph()
        studies.append(
            CaseStudy(
                study_id="langgraph_incident_response",
                label="LangGraph (incident)",
                build_native=lambda: compiled,
                extract_graph=extract_langgraph,
                temporal_rules=tuple(ex_lg.TEMPORAL_RULES),
                temporal_traces=dict(ex_lg.TEMPORAL_TRACES),
                notes="Incident triage StateGraph with tool metadata + human approval node.",
            )
        )

    # Google ADK: compliance pipeline.
    ex_adk = _safe_import("examples.adk_compliance_pipeline")
    if not isinstance(ex_adk, Exception):
        from agentproof.graph import extract_adk

        pipeline = ex_adk.build_compliance_pipeline()
        studies.append(
            CaseStudy(
                study_id="adk_compliance_pipeline",
                label="ADK (compliance)",
                build_native=lambda: pipeline,
                extract_graph=extract_adk,
                temporal_rules=tuple(ex_adk.TEMPORAL_RULES),
                temporal_traces=dict(ex_adk.TEMPORAL_TRACES),
                notes="Sequential+parallel+loop compliance pipeline with human signoff gate.",
            )
        )

    # AutoGen AgentChat: change-control board.
    ex_ag = _safe_import("examples.autogen_change_control")
    if not isinstance(ex_ag, Exception):
        from agentproof.graph import extract_autogen

        agents, transitions = ex_ag.build_change_control_team()
        studies.append(
            CaseStudy(
                study_id="autogen_change_control",
                label="AutoGen (change-control)",
                build_native=lambda: (agents, transitions),
                extract_graph=lambda payload: extract_autogen(payload[0], allowed_transitions=payload[1]),
                temporal_rules=tuple(ex_ag.TEMPORAL_RULES),
                temporal_traces=dict(ex_ag.TEMPORAL_TRACES),
                notes="Acyclic speaker transitions with UserProxyAgent approver gate.",
            )
        )

    return studies


def _decision_severity(decision: Any) -> int:
    if bool(getattr(decision, "escalate", False)):
        return 3
    if bool(getattr(decision, "halt", False)):
        return 2
    if bool(getattr(decision, "denied", False)):
        return 1
    return 0


def _severity_label(level: int) -> str:
    return {0: "PASS", 1: "BLOCKED", 2: "HALT", 3: "ESCALATE"}[int(level)]


def _verify_temporal(
    rules: tuple[MonitorRuleSpec, ...],
    traces: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    compiled = tuple(compile_monitor_rule(r) for r in rules)

    trace_results: dict[str, Any] = {}
    summary = {"PASS": 0, "BLOCKED": 0, "HALT": 0, "ESCALATE": 0}

    for trace_id in sorted(traces.keys()):
        events = traces[trace_id]
        state: dict[str, int] = {}
        worst = 0
        violated: set[str] = set()

        for ev in events:
            state, snapshots, decision = evaluate_monitors(compiled, state, ev)
            worst = max(worst, _decision_severity(decision))
            for snap in snapshots:
                if snap.violation:
                    violated.add(snap.rule_id)

        status = _severity_label(worst)
        summary[status] = int(summary.get(status, 0)) + 1
        trace_results[trace_id] = {
            "status": status,
            "violated_rules": sorted(violated),
        }

    return {
        "rule_count": len(rules),
        "trace_count": len(traces),
        "rules": [
            {"rule_id": r.rule_id, "dsl": r.dsl, "on_violation": r.on_violation}
            for r in rules
        ],
        "traces": trace_results,
        "summary": summary,
    }


def collect_case_study_stats() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for study in _case_studies():
        entry: dict[str, Any] = {
            "study_id": study.study_id,
            "label": study.label,
            "status": "ok",
            "notes": study.notes,
        }

        try:
            native = study.build_native()
            graph = study.extract_graph(native)
            entry["graph"] = _graph_stats(graph)
            entry["extract_median_ms"] = _median_time_ms(lambda: study.extract_graph(native), runs=200, warmup=20)
            entry["extract_runs"] = 200
            entry["extract_warmup"] = 20

            verification: dict[str, Any] = {}
            verification["structural"] = run_structural_checks(graph, require_human=study.require_human)
            if study.temporal_rules and study.temporal_traces is not None:
                verification["temporal"] = _verify_temporal(study.temporal_rules, study.temporal_traces)
            entry["verification"] = verification
        except Exception as e:  # noqa: BLE001
            entry["status"] = "skipped"
            entry["error"] = f"{type(e).__name__}: {e}"
        results.append(entry)

    return results


def collect_bench_stats() -> dict[str, Any]:
    # Representative rules (cover supported DSL forms).
    rules = [
        MonitorRuleSpec("forbidden_tool", "G !tool:rm_rf", on_violation="halt"),
        MonitorRuleSpec("interleave", "action:fetch -> F action:validate", on_violation="block"),
        MonitorRuleSpec("until_like", "action:ingest U action:validate", on_violation="block"),
    ]

    compile_rows: list[dict[str, Any]] = []
    for rule in rules:
        def _compile():
            compile_monitor_rule(rule)

        median_ms = _median_time_ms(_compile, runs=500, warmup=50)
        compiled = compile_monitor_rule(rule)
        compile_rows.append(
            {
                "rule_id": rule.rule_id,
                "dsl": rule.dsl,
                "on_violation": rule.on_violation,
                "predicate_count": len(compiled.predicates),
                "compile_median_ms": median_ms,
                "compiled_states": sorted(set(compiled.transition_table.keys())),
                "violation_states": sorted(set(compiled.violation_states)),
            }
        )

    # Evaluation throughput: fixed 1,000-event synthetic stream.
    suite = tuple(compile_monitor_rule(r) for r in rules)
    events: list[dict[str, Any]] = []
    for i in range(1000):
        if i % 4 == 0:
            events.append({"tool_name": "http_get", "action_type": "fetch", "tags": []})
        elif i % 4 == 1:
            events.append({"action_type": "validate", "tags": ["check"]})
        elif i % 4 == 2:
            events.append({"action_type": "transform", "tags": ["llm"]})
        else:
            events.append({"tool_name": "db_insert", "action_type": "store", "tags": []})

    def _eval_once() -> None:
        state: dict[str, int] = {}
        for ev in events:
            state, _snaps, _decision = evaluate_monitors(suite, state, ev)

    # Measure elapsed time and convert to events/s.
    for _ in range(10):
        _eval_once()
    eval_samples: list[float] = []
    for _ in range(50):
        start = time.perf_counter()
        _eval_once()
        elapsed = time.perf_counter() - start
        eval_samples.append(1000.0 / elapsed)

    return {
        "compile": compile_rows,
        "evaluate": {
            "rules": [r.rule_id for r in rules],
            "monitor_count": len(suite),
            "event_count": len(events),
            "median_events_per_sec": float(statistics.median(eval_samples)),
        },
    }


def main() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    case_stats = collect_case_study_stats()
    bench_stats = collect_bench_stats()

    (GENERATED_DIR / "case_study_stats.json").write_text(json.dumps(case_stats, indent=2, sort_keys=True) + "\n")
    (GENERATED_DIR / "bench_stats.json").write_text(json.dumps(bench_stats, indent=2, sort_keys=True) + "\n")

    print(f"Wrote {GENERATED_DIR / 'case_study_stats.json'}")
    print(f"Wrote {GENERATED_DIR / 'bench_stats.json'}")


if __name__ == "__main__":
    main()
