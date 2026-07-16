#!/usr/bin/env python
"""E5 — Static/runtime partition (AgentProof-CEGAR, plan §7 E5, §4.7).

Question (plan §7): *can certificates reduce expensive oversight at matched
safety?* This runner simulates the static/runtime partition of plan §4.7:

    SAFE   effect -> execute WITHOUT an expensive judge/human
    UNSAFE effect -> statically deny / repair / require approval (resolved offline)
    UNKNOWN effect -> deterministic runtime guard, human approval, or LLM judge

For every effect-bearing node in the seed suite it classifies the effect using
the tri-valued analysis, then compares two oversight strategies:

* **guard-everything baseline** — every effect incurs an expensive (judge/human)
  runtime decision;
* **AgentProof partition** — only ``UNKNOWN`` effects reach expensive runtime
  oversight; ``SAFE`` effects run under their certificate and ``UNSAFE`` effects
  are resolved statically (deny/repair).

The reported reduction fraction is the share of effects for which the expensive
runtime decision is *avoided* (``SAFE`` + ``UNSAFE``). The classification is
sound-by-construction: an effect is called ``SAFE`` only when the whole analyzed
region verifies ``SAFE`` **and** the node is certifiable (exact provenance, no
unsupported facts), so attack success is matched — nothing unsafe is silently
waved through.

HONESTY: this is an *offline simulation* of the decision partition over synthetic
seed tasks. It counts avoided expensive decisions; it does **not** run a real
LLM judge, human study, or live runtime, and reports no latency/utility/dollar
numbers for those un-run arms.

Run: ``.venv/bin/python scripts/cegar/e5_partition.py``
"""

from __future__ import annotations

import argparse
from typing import Any

import _seedsuite as seed
from _seedsuite import add_common_args, load_seed_suite, results_path, write_results

from agentproof.cegar.cegar import analyze
from agentproof.cegar.ir import EffectKind, Verdict

# Effect kinds that constitute a guardable side effect (NONE = pure routing).
_EFFECTFUL = frozenset(
    e for e in EffectKind if e is not EffectKind.NONE
)


def _witness_path(cr) -> set[str]:
    w = cr.product_result.witness
    return set(w.product_path) if w is not None else set()


def _classify(suite: list[seed.SeedTask]) -> dict[str, Any]:
    counts = {"safe": 0, "unsafe": 0, "unknown": 0}
    total_effects = 0
    rows: list[dict[str, Any]] = []

    for t in suite:
        cr = analyze(t.graph, t.policy,
                     assume_trace_conservative=t.assume_trace_conservative)
        wpath = _witness_path(cr)
        task_effects = []
        for n in t.graph.nodes:
            if n.effect not in _EFFECTFUL:
                continue
            total_effects += 1
            if cr.verdict is Verdict.SAFE and n.is_certifiable:
                cls = "safe"       # execute under certificate, no judge
            elif cr.verdict is Verdict.UNSAFE and n.id in wpath:
                cls = "unsafe"     # statically denied / repaired
            else:
                cls = "unknown"    # runtime guard / human / judge
            counts[cls] += 1
            task_effects.append({"node_id": n.id, "effect": n.effect.value,
                                 "certifiable": n.is_certifiable, "class": cls})
        rows.append({
            "task_id": t.task_id,
            "task_verdict": cr.verdict.value,
            "effects": task_effects,
        })

    # guard-everything: every effect is an expensive decision.
    baseline_expensive = total_effects
    # AgentProof: only UNKNOWN effects reach expensive oversight.
    agentproof_expensive = counts["unknown"]
    avoided = baseline_expensive - agentproof_expensive
    reduction = (avoided / baseline_expensive) if baseline_expensive else 0.0

    return {
        "total_effects": total_effects,
        "effect_class_counts": counts,
        "expensive_decisions_guard_everything": baseline_expensive,
        "expensive_decisions_agentproof": agentproof_expensive,
        "expensive_decisions_avoided": avoided,
        "reduction_fraction": reduction,
        "certified_safe_effects": counts["safe"],
        "statically_denied_unsafe_effects": counts["unsafe"],
        "residual_runtime_effects": counts["unknown"],
        "per_task": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    args = parser.parse_args(argv)

    suite = load_seed_suite(args.tasks_dir)
    res = _classify(suite)

    # The plan's E5 gate is >=30% fewer expensive decisions (at matched safety).
    gate_pass = res["reduction_fraction"] >= 0.30

    payload = {
        "experiment": "E5_static_runtime_partition",
        "honesty": "Offline simulation of the §4.7 decision partition over a "
                   "synthetic seed suite. No real LLM judge, human study, or live "
                   "runtime is executed; no latency/utility/dollar numbers are "
                   "reported for those un-run arms. Attack success is matched by "
                   "construction (SAFE effects are certifiable; UNSAFE effects are "
                   "denied).",
        "gate_reduction_ge_30pct_pass": gate_pass,
        **res,
    }
    out = results_path("e5_partition.json", args.out)
    write_results(out, payload)

    # -- human summary ---------------------------------------------------
    c = res["effect_class_counts"]
    print("=" * 70)
    print("E5 — Static/runtime partition (offline simulation)")
    print("=" * 70)
    print(f"total guardable effects across seed suite: {res['total_effects']}")
    print(f"  SAFE    (execute under certificate, no judge): {c['safe']}")
    print(f"  UNSAFE  (statically denied / repaired):        {c['unsafe']}")
    print(f"  UNKNOWN (runtime guard / human / LLM judge):   {c['unknown']}")
    print("-" * 70)
    print(f"expensive decisions, guard-everything baseline: "
          f"{res['expensive_decisions_guard_everything']}")
    print(f"expensive decisions, AgentProof partition:      "
          f"{res['expensive_decisions_agentproof']}")
    print(f"expensive decisions avoided:                    "
          f"{res['expensive_decisions_avoided']}")
    print(f"reduction fraction:                             "
          f"{res['reduction_fraction']:.3f}")
    print("-" * 70)
    print(f"GATE (>=30% fewer expensive decisions at matched safety): "
          f"{'PASS' if gate_pass else 'FAIL'}")
    print(f"results -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
