#!/usr/bin/env python
"""E8 — Ablations and scalability (AgentProof-CEGAR, plan §7 E8).

Ablates the three load-bearing mechanisms of the analyzer over the seed suite
and reports what each one buys, plus a timing breakdown:

1. **May/must modality.** Rebuild each graph with every edge forced to ``MAY``
   (no ``MUST`` edges) and re-run the product checker. Definite (``must``-forced)
   ``UNSAFE`` verdicts collapse to ``UNKNOWN`` — showing that modality is what
   lets the checker cheaply *decide* a violation without concretization.

2. **CEGAR refinement.** Compare the raw
   :func:`agentproof.cegar.product.check` verdict (no refinement) with the
   :func:`agentproof.cegar.cegar.analyze` verdict (with refinement/concretization)
   per task — how many ``UNKNOWN`` candidates CEGAR resolves.

3. **Certificate gate.** The gate forbids ``SAFE`` on a region with non-exact
   provenance or an unsupported fact. **Disabling it** (running with
   ``assume_trace_conservative=True``) is shown to admit **FALSE SAFE** verdicts
   on genuinely-uncertified seed graphs whose ground truth is *not* safe — a
   direct demonstration of why the gate is necessary (plan §4.1, §2.3).

4. **Timing.** Extraction (flat->may/must lift), product check, CEGAR
   refinement, and repair are timed over the suite. Timings are
   environment-dependent (they are the only non-deterministic output; the
   verdict/ablation counts are fully deterministic).

Offline/solver-only; no model or runtime execution.

Run: ``.venv/bin/python scripts/cegar/e8_ablation.py``
"""

from __future__ import annotations

import argparse
import time
from dataclasses import replace
from statistics import mean
from typing import Any

import _seedsuite as seed
from _seedsuite import add_common_args, load_seed_suite, results_path, write_results

from agentproof.cegar import product
from agentproof.cegar.cegar import analyze
from agentproof.cegar.ir import MayMustGraph, Modality, Verdict
from agentproof.cegar.repair import repair


def _all_may(graph: MayMustGraph) -> MayMustGraph:
    """A copy of ``graph`` with every edge modality downgraded to MAY."""
    return graph.with_edges(tuple(replace(e, modality=Modality.MAY) for e in graph.edges))


def _ablate_modality(suite: list[seed.SeedTask]) -> dict[str, Any]:
    base_unsafe = 0
    ablated_unsafe = 0
    lost = []
    for t in suite:
        r_base = product.check(t.graph, t.policy,
                               assume_trace_conservative=t.assume_trace_conservative)
        r_abl = product.check(_all_may(t.graph), t.policy,
                              assume_trace_conservative=t.assume_trace_conservative)
        if r_base.verdict is Verdict.UNSAFE:
            base_unsafe += 1
            if r_abl.verdict is not Verdict.UNSAFE:
                lost.append({"task_id": t.task_id,
                            "ablated_verdict": r_abl.verdict.value})
        if r_abl.verdict is Verdict.UNSAFE:
            ablated_unsafe += 1
    return {
        "product_unsafe_with_modality": base_unsafe,
        "product_unsafe_all_may": ablated_unsafe,
        "definite_unsafe_lost_without_must_edges": len(lost),
        "lost_examples": lost,
    }


def _ablate_cegar(suite: list[seed.SeedTask]) -> dict[str, Any]:
    changed = []
    product_unknown = 0
    cegar_unknown = 0
    for t in suite:
        pr = product.check(t.graph, t.policy,
                          assume_trace_conservative=t.assume_trace_conservative)
        cr = analyze(t.graph, t.policy,
                     assume_trace_conservative=t.assume_trace_conservative)
        if pr.verdict is Verdict.UNKNOWN:
            product_unknown += 1
        if cr.verdict is Verdict.UNKNOWN:
            cegar_unknown += 1
        if pr.verdict is not cr.verdict:
            changed.append({"task_id": t.task_id,
                           "without_cegar": pr.verdict.value,
                           "with_cegar": cr.verdict.value})
    return {
        "product_unknown_no_cegar": product_unknown,
        "cegar_unknown_after_refinement": cegar_unknown,
        "unknown_resolved_by_cegar": product_unknown - cegar_unknown,
        "verdicts_changed_by_cegar": changed,
    }


def _ablate_certificate_gate(suite: list[seed.SeedTask]) -> dict[str, Any]:
    """Disabling the gate admits FALSE SAFE on uncertified, not-safe graphs."""
    false_safe_admitted = []
    for t in suite:
        gated = product.check(t.graph, t.policy)  # gate on (conservative=False)
        ungated = product.check(t.graph, t.policy, assume_trace_conservative=True)
        # A false SAFE: the gate held it at UNKNOWN, removing the gate flips it to
        # SAFE, yet the task's ground truth is NOT safe.
        if (gated.verdict is not Verdict.SAFE
                and ungated.verdict is Verdict.SAFE
                and t.expected_verdict != "safe"):
            false_safe_admitted.append({
                "task_id": t.task_id,
                "expected_verdict": t.expected_verdict,
                "gated_verdict": gated.verdict.value,
                "ungated_verdict": ungated.verdict.value,
                "unsupported_facts": ungated.unsupported_facts,
            })
    return {
        "false_safe_admitted_without_gate": len(false_safe_admitted),
        "false_safe_examples": false_safe_admitted,
        "gate_necessary": bool(false_safe_admitted),
    }


def _timings(suite: list[seed.SeedTask], repeats: int) -> dict[str, Any]:
    """Wall-clock breakdown (environment-dependent; not part of any gate)."""
    ext, prod, refine, rep = [], [], [], []
    for t in suite:
        flat = t.graph.to_agent_graph()
        for _ in range(repeats):
            s = time.perf_counter()
            MayMustGraph.from_agent_graph(flat)         # extraction / lift proxy
            ext.append(time.perf_counter() - s)

            s = time.perf_counter()
            product.check(t.graph, t.policy,
                         assume_trace_conservative=t.assume_trace_conservative)
            prod.append(time.perf_counter() - s)

            s = time.perf_counter()
            analyze(t.graph, t.policy,
                    assume_trace_conservative=t.assume_trace_conservative)
            refine.append(time.perf_counter() - s)

            s = time.perf_counter()
            repair(t.graph, t.policy,
                   assume_trace_conservative=t.assume_trace_conservative)
            rep.append(time.perf_counter() - s)

    def _stats(xs: list[float]) -> dict[str, float]:
        xs_sorted = sorted(xs)
        p95 = xs_sorted[min(len(xs_sorted) - 1, int(0.95 * len(xs_sorted)))]
        return {"mean_s": float(mean(xs)), "max_s": float(max(xs)),
                "p95_s": float(p95), "total_s": float(sum(xs))}

    return {
        "repeats_per_task": repeats,
        "note": "Wall-clock; environment-dependent; NOT part of any correctness "
                "gate. Verdict/ablation counts above are deterministic.",
        "extraction_lift": _stats(ext),
        "product_check": _stats(prod),
        "cegar_refinement": _stats(refine),
        "repair": _stats(rep),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    parser.add_argument("--timing-repeats", type=int, default=3,
                        help="repeats per task for the timing breakdown (default: 3)")
    args = parser.parse_args(argv)

    suite = load_seed_suite(args.tasks_dir)

    modality = _ablate_modality(suite)
    cegar = _ablate_cegar(suite)
    cert_gate = _ablate_certificate_gate(suite)
    timing = _timings(suite, args.timing_repeats)

    # The key demonstration: removing the certificate gate admits false SAFE.
    demonstration_pass = (
        cert_gate["gate_necessary"]
        and modality["definite_unsafe_lost_without_must_edges"] > 0
    )

    payload = {
        "experiment": "E8_ablation",
        "honesty": "Offline/solver-only over a synthetic seed suite; no LLM, model, "
                   "or runtime. Timings are wall-clock and environment-dependent.",
        "ablation_modality": modality,
        "ablation_cegar": cegar,
        "ablation_certificate_gate": cert_gate,
        "timing": timing,
        "demonstrations_hold": demonstration_pass,
    }
    out = results_path("e8_ablation.json", args.out)
    write_results(out, payload)

    # -- human summary ---------------------------------------------------
    print("=" * 70)
    print("E8 — Ablations and scalability (offline, solver-only)")
    print("=" * 70)
    print("[1] may/must modality ablation (all edges -> MAY):")
    print(f"    product UNSAFE with modality: {modality['product_unsafe_with_modality']}"
          f"  ->  all-MAY: {modality['product_unsafe_all_may']}")
    print(f"    definite UNSAFE lost without MUST edges: "
          f"{modality['definite_unsafe_lost_without_must_edges']}")
    print("[2] CEGAR refinement ablation:")
    print(f"    UNKNOWN without CEGAR: {cegar['product_unknown_no_cegar']}"
          f"  ->  after CEGAR: {cegar['cegar_unknown_after_refinement']}"
          f"  ({cegar['unknown_resolved_by_cegar']} resolved)")
    print("[3] certificate-gate ablation (disable the SAFE gate):")
    print(f"    FALSE SAFE admitted on uncertified not-safe graphs: "
          f"{cert_gate['false_safe_admitted_without_gate']}")
    for ex in cert_gate["false_safe_examples"]:
        print(f"      - {ex['task_id']}: gated={ex['gated_verdict']} -> "
              f"ungated=SAFE (ground truth: {ex['expected_verdict']})")
    print("[4] timing (wall-clock, environment-dependent):")
    for key in ("extraction_lift", "product_check", "cegar_refinement", "repair"):
        s = timing[key]
        print(f"    {key:18s} mean={s['mean_s']*1e3:7.3f} ms  "
              f"p95={s['p95_s']*1e3:7.3f} ms  max={s['max_s']*1e3:7.3f} ms")
    print("-" * 70)
    print("demonstrations (gate necessary AND modality buys definite UNSAFE): "
          f"{'HOLD' if demonstration_pass else 'DO NOT HOLD'}")
    print(f"results -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
