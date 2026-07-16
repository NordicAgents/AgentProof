#!/usr/bin/env python
"""E3 — Verified repair (AgentProof-CEGAR, plan §7 E3).

Question (plan §7): *does verifier-guided repair produce policy-safe,
certificate-accepted patches?* This runner runs the proof-carrying repair loop
:func:`agentproof.cegar.repair.repair` (solver-side
:class:`~agentproof.cegar.repair.GrammarProposer` only) over the seed suite and
reports the primary outcome — the **policy-safe AND certificate-accepted repair
rate** — plus the secondary cost/edit/iteration means.

Every reported success is double-checked here, independently of the repair
loop's own gate: the patched graph is re-analyzed to ``SAFE`` and the emitted
certificate is re-run through :func:`agentproof.cegar.checker.check_certificate`.

HONESTY — baselines NOT run here
--------------------------------
The plan's E3 headline compares the full loop against LLM-only repair baselines
(one-shot frontier model, iterative-with-tests, LLM+witness, etc.). **None of
those LLM arms are executed in this script** — no model or API is available in
this environment, and no numbers are fabricated for them. Only the offline,
solver-only ``GrammarProposer`` arm is measured. The head-to-head +15pp gate
(plan §7 E3) therefore cannot be evaluated here and is reported as ``null``.

Run: ``.venv/bin/python scripts/cegar/e3_repair.py``
"""

from __future__ import annotations

import argparse
from statistics import mean
from typing import Any

import _seedsuite as seed
from _seedsuite import add_common_args, load_seed_suite, results_path, write_results

from agentproof.cegar.cegar import analyze
from agentproof.cegar.checker import check_certificate
from agentproof.cegar.ir import Verdict
from agentproof.cegar.repair import RepairConfig, repair


def _run(suite: list[seed.SeedTask], config: RepairConfig) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    need_repair = 0          # tasks not already SAFE on first analysis
    repaired = 0             # successful, checker-accepted repairs
    already_safe = 0
    calibration_errors = 0   # repair success disagreed with the `repairable` label
    calibration_checked = 0  # tasks that actually carry a `repairable` label
    independent_confirms = 0 # re-verified SAFE + cert accepted, independently

    for t in suite:
        base = analyze(t.graph, t.policy,
                       assume_trace_conservative=t.assume_trace_conservative)
        starts_safe = base.verdict is Verdict.SAFE
        rr = repair(t.graph, t.policy, config=config,
                    assume_trace_conservative=t.assume_trace_conservative)

        if not starts_safe:
            need_repair += 1
        else:
            already_safe += 1

        # Independent re-verification of a claimed success (do not trust the loop).
        indep_ok: bool | None = None
        if rr.success:
            re_analysis = analyze(rr.patched_graph, t.policy,
                                  assume_trace_conservative=t.assume_trace_conservative)
            cert_ok = rr.certificate is not None and check_certificate(rr.certificate).accepted
            indep_ok = (re_analysis.verdict is Verdict.SAFE) and cert_ok
            if indep_ok:
                independent_confirms += 1
            if not starts_safe:
                repaired += 1

        # Calibration is only meaningful for tasks that carry an explicit
        # `repairable` label (the synthetic tasks); external benchmark tasks omit
        # it (repairable is None) and are skipped here.
        if t.repairable is not None:
            calibration_checked += 1
            if rr.success != t.repairable:
                calibration_errors += 1

        rows.append({
            "task_id": t.task_id,
            "expected_verdict": t.expected_verdict,
            "starts_safe": starts_safe,
            "labeled_repairable": t.repairable,
            "repair_success": rr.success,
            "final_verdict": rr.verdict.value,
            "edits": rr.edits,
            "n_edits": len(rr.edits),
            "cost": rr.cost,
            "iterations": rr.iterations,
            "candidates_tried": rr.candidates_tried,
            "certificate_accepted": (rr.certificate is not None
                                     and check_certificate(rr.certificate).accepted),
            "independent_reverify_safe": indep_ok,
        })

    successes = [r for r in rows if r["repair_success"]]
    repair_targets = [r for r in rows if not r["starts_safe"]]
    repaired_targets = [r for r in repair_targets if r["repair_success"]]

    # Means over successful repairs that actually changed the graph (edits > 0),
    # so the "already SAFE, cost 0" tasks don't deflate the cost/edit means.
    nontrivial = [r for r in successes if r["n_edits"] > 0]

    def _mean(vals: list[float]) -> float | None:
        return float(mean(vals)) if vals else None

    return {
        "n_tasks": len(suite),
        "already_safe": already_safe,
        "tasks_needing_repair": need_repair,
        "repairs_succeeded": repaired,
        "repair_rate_over_targets": (len(repaired_targets) / len(repair_targets)
                                     if repair_targets else None),
        "repair_rate_over_all_tasks": (len(successes) / len(rows)) if rows else None,
        "independent_reverify_confirmed": independent_confirms,
        "successes_total": len(successes),
        "calibration_labeled_tasks": calibration_checked,
        "calibration_errors_vs_label": calibration_errors,
        "mean_cost_nontrivial": _mean([r["cost"] for r in nontrivial]),
        "mean_edits_nontrivial": _mean([float(r["n_edits"]) for r in nontrivial]),
        "mean_iterations_success": _mean([float(r["iterations"]) for r in successes]),
        "mean_candidates_tried_success": _mean(
            [float(r["candidates_tried"]) for r in successes]),
        "per_task": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    parser.add_argument("--max-edits", type=int, default=3,
                        help="max edit-sequence length the GrammarProposer explores "
                             "(default: 3)")
    args = parser.parse_args(argv)

    suite = load_seed_suite(args.tasks_dir)
    config = RepairConfig(max_edits=args.max_edits)
    res = _run(suite, config)

    # Sanity gate for THIS offline arm: every claimed success independently
    # re-verifies SAFE + certificate-accepted, and calibration matches labels.
    arm_ok = (
        res["successes_total"] == res["independent_reverify_confirmed"]
        and res["calibration_errors_vs_label"] == 0
    )

    payload = {
        "experiment": "E3_verified_repair",
        "arm": "solver_only_grammar_proposer",
        "honesty": {
            "llm_repair_baselines_run": False,
            "note": "LLM-only / iterative / LLM+witness repair baselines are NOT "
                    "run here (no model or API available); no numbers are "
                    "fabricated for them. Only the offline solver-only "
                    "GrammarProposer arm is measured.",
            "e3_plus15pp_gate": None,
        },
        "repair_config": {"l1": config.l1, "l2": config.l2, "l3": config.l3,
                          "l4": config.l4, "max_edits": config.max_edits},
        "offline_arm_self_consistent": arm_ok,
        **res,
    }
    out = results_path("e3_repair.json", args.out)
    write_results(out, payload)

    # -- human summary ---------------------------------------------------
    def _fmt(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.3f}"

    print("=" * 70)
    print("E3 — Verified repair (offline, SOLVER-ONLY GrammarProposer)")
    print("=" * 70)
    print("HONESTY: LLM-only / iterative / LLM+witness repair baselines are NOT")
    print("         run here (no model available). No numbers are invented for")
    print("         them; the +15pp head-to-head E3 gate is not evaluable here.")
    print("-" * 70)
    print(f"seed tasks:               {res['n_tasks']} "
          f"(already SAFE: {res['already_safe']}, need repair: {res['tasks_needing_repair']})")
    print(f"repairs succeeded:        {res['repairs_succeeded']}/{res['tasks_needing_repair']}"
          f"  (rate over targets: {_fmt(res['repair_rate_over_targets'])})")
    print(f"policy-safe + cert-accepted (independently re-verified): "
          f"{res['independent_reverify_confirmed']}/{res['successes_total']}")
    print(f"mean cost (nontrivial):   {_fmt(res['mean_cost_nontrivial'])}")
    print(f"mean edits (nontrivial):  {_fmt(res['mean_edits_nontrivial'])}")
    print(f"mean iterations:          {_fmt(res['mean_iterations_success'])}")
    print(f"mean candidates tried:    {_fmt(res['mean_candidates_tried_success'])}")
    print("-" * 70)
    print(f"offline arm self-consistent (all successes re-verify, labels match): "
          f"{'PASS' if arm_ok else 'FAIL'}")
    print(f"results -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
