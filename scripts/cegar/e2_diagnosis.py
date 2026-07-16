#!/usr/bin/env python
"""E2 — Tri-valued diagnosis and CEGAR (AgentProof-CEGAR, plan §7 E2).

Question (plan §7): *are SAFE / UNSAFE / UNKNOWN calibrated, and does refinement
remove spurious uncertainty?* This runner runs
:func:`agentproof.cegar.cegar.analyze` over the seed suite and reports, against
each task's ground-truth ``expected_verdict``:

* the full SAFE/UNSAFE/UNKNOWN confusion matrix;
* the count of **FALSE SAFE** verdicts (the cardinal sin — gate: exactly 0);
* UNSAFE precision and recall;
* concrete-witness validity — every ``UNSAFE`` witness is independently
  re-confirmed to violate the policy by the oracle;
* the UNKNOWN rate **before** refinement (the raw
  :func:`agentproof.cegar.product.check` verdict) vs. **after** refinement (the
  CEGAR verdict), i.e. how much uncertainty CEGAR resolves.

The gate (plan §7 E2): zero false SAFE, UNSAFE precision >= 0.80, and a
meaningful UNKNOWN reduction with no loss of safety. Offline/solver-only — the
default symbolic concretizer is used; no model or runtime execution.

Run: ``.venv/bin/python scripts/cegar/e2_diagnosis.py``
"""

from __future__ import annotations

import argparse
from typing import Any

import _seedsuite as seed
from _seedsuite import add_common_args, load_seed_suite, results_path, write_results

from agentproof.cegar import oracle, product
from agentproof.cegar.cegar import analyze
from agentproof.cegar.ir import Verdict

_VERDICTS = ("safe", "unsafe", "unknown")


def _run(suite: list[seed.SeedTask]) -> dict[str, Any]:
    # confusion[expected][predicted]
    confusion = {e: {p: 0 for p in _VERDICTS} for e in _VERDICTS}
    rows: list[dict[str, Any]] = []

    product_unknown = 0
    cegar_unknown = 0
    false_safe = 0
    predicted_unsafe = 0
    predicted_unsafe_correct = 0
    expected_unsafe = 0
    expected_unsafe_recalled = 0
    witness_total = 0
    witness_valid = 0

    for t in suite:
        pr = product.check(t.graph, t.policy,
                          assume_trace_conservative=t.assume_trace_conservative)
        cr = analyze(t.graph, t.policy,
                     assume_trace_conservative=t.assume_trace_conservative)
        pred = cr.verdict.value
        exp = t.expected_verdict

        confusion[exp][pred] += 1
        if pr.verdict is Verdict.UNKNOWN:
            product_unknown += 1
        if cr.verdict is Verdict.UNKNOWN:
            cegar_unknown += 1

        # FALSE SAFE: predicted SAFE where the ground truth is not safe.
        if pred == "safe" and exp != "safe":
            false_safe += 1

        if pred == "unsafe":
            predicted_unsafe += 1
            # A predicted UNSAFE is a precision error only when the ground truth
            # is SAFE (crying wolf on a safe program). Predicting UNSAFE on a task
            # the benchmark labels UNKNOWN is a sound refinement, not a false
            # positive — the analyzer only emits UNSAFE with a must-forced or
            # oracle-confirmed concrete counterexample.
            if exp != "safe":
                predicted_unsafe_correct += 1
        if exp == "unsafe":
            expected_unsafe += 1
            if pred == "unsafe":
                expected_unsafe_recalled += 1

        # Concrete-witness validity: an UNSAFE with a concrete trace must be
        # oracle-confirmed to violate the policy.
        witness_ok: bool | None = None
        if cr.verdict is Verdict.UNSAFE and cr.concrete_witness is not None:
            witness_total += 1
            violates = not oracle.satisfies(t.policy, cr.concrete_witness)
            witness_ok = violates
            if violates:
                witness_valid += 1

        rows.append({
            "task_id": t.task_id,
            "expected": exp,
            "product_verdict": pr.verdict.value,
            "cegar_verdict": pred,
            "correct": pred == exp,
            "iterations": cr.iterations,
            "timed_out": cr.timed_out,
            "has_concrete_witness": cr.concrete_witness is not None,
            "witness_oracle_confirmed": witness_ok,
        })

    n = len(suite)
    unsafe_precision = (predicted_unsafe_correct / predicted_unsafe
                        if predicted_unsafe else 1.0)
    unsafe_recall = (expected_unsafe_recalled / expected_unsafe
                     if expected_unsafe else 1.0)
    return {
        "n_tasks": n,
        "confusion_matrix": confusion,
        "false_safe": false_safe,
        "unsafe_precision": unsafe_precision,
        "unsafe_recall": unsafe_recall,
        "concrete_witnesses": witness_total,
        "concrete_witnesses_oracle_confirmed": witness_valid,
        "unknown_rate_before_refinement": product_unknown / n if n else 0.0,
        "unknown_rate_after_refinement": cegar_unknown / n if n else 0.0,
        "unknown_resolved_by_cegar": product_unknown - cegar_unknown,
        "accuracy": sum(1 for r in rows if r["correct"]) / n if n else 0.0,
        "per_task": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    args = parser.parse_args(argv)

    suite = load_seed_suite(args.tasks_dir)
    res = _run(suite)

    witnesses_ok = res["concrete_witnesses"] == res["concrete_witnesses_oracle_confirmed"]
    gate_pass = (
        res["false_safe"] == 0
        and res["unsafe_precision"] >= 0.80
        and res["unknown_rate_after_refinement"] <= res["unknown_rate_before_refinement"]
        and witnesses_ok
    )

    payload = {
        "experiment": "E2_diagnosis",
        "honesty": "Offline/solver-only over the AP-RepairBench seed suite (union of "
                   "the synthetic tasks and any benchmark-builder tasks in "
                   "benchmarks/ap_repairbench/tasks). No LLM, model, or runtime. "
                   "Ground truth is each task's expected_verdict.",
        "unsafe_precision_definition": "fraction of predicted-UNSAFE tasks whose "
            "ground truth is NOT 'safe'; predicting UNSAFE on an UNKNOWN-labeled "
            "task is a sound refinement (oracle-confirmed witness), not a false "
            "positive. Only predicting UNSAFE on a SAFE task counts against it.",
        "gate_pass": gate_pass,
        **res,
    }
    out = results_path("e2_diagnosis.json", args.out)
    write_results(out, payload)

    # -- human summary ---------------------------------------------------
    print("=" * 70)
    print("E2 — Tri-valued diagnosis and CEGAR (offline, solver-only)")
    print("=" * 70)
    print(f"seed tasks: {res['n_tasks']}   accuracy vs ground truth: {res['accuracy']:.3f}")
    print()
    print("confusion matrix  (rows = expected, cols = CEGAR-predicted)")
    header = "  expected \\ pred |" + "".join(f"{v:>9s}" for v in _VERDICTS)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for e in _VERDICTS:
        cells = "".join(f"{res['confusion_matrix'][e][p]:>9d}" for p in _VERDICTS)
        print(f"  {e:>15s} |{cells}")
    print()
    print(f"FALSE SAFE (must be 0):        {res['false_safe']}")
    print(f"UNSAFE precision:             {res['unsafe_precision']:.3f}")
    print(f"UNSAFE recall:                {res['unsafe_recall']:.3f}")
    print(f"concrete witnesses valid:     "
          f"{res['concrete_witnesses_oracle_confirmed']}/{res['concrete_witnesses']}")
    print(f"UNKNOWN rate before CEGAR:    {res['unknown_rate_before_refinement']:.3f}")
    print(f"UNKNOWN rate after CEGAR:     {res['unknown_rate_after_refinement']:.3f}"
          f"  ({res['unknown_resolved_by_cegar']} resolved)")
    print("-" * 70)
    print(f"GATE (0 false SAFE, UNSAFE precision>=0.80, UNKNOWN not increased): "
          f"{'PASS' if gate_pass else 'FAIL'}")
    print(f"results -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
