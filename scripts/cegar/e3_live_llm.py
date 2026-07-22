#!/usr/bin/env python
"""E3 (verified repair) live experiment: solver vs LLM vs combined arms.

Runs proof-carrying repair over the AP-RepairBench seed suite with a real,
UNTRUSTED language model as the patch proposer, across one or more models, and
compares three arms per repairable task:

  - solver   : GrammarProposer (deterministic, no API call)
  - llm      : LLMProposer(model)                  (one API call per model, task)
  - combined : LLM candidates UNION grammar candidates (reuses that same call)

A "success" for any arm requires repair() to reach SAFE AND the INDEPENDENT
certificate checker (agentproof.cegar.checker) to accept the certificate. The
script asserts **zero false certificates** across every arm and model — the
load-bearing soundness property (the LLM is outside the TCB).

Provider: any OpenAI-compatible chat endpoint. Set OPENAI_BASE_URL and
OPENAI_API_KEY in the environment (e.g. via a local .env), then:

    python scripts/cegar/e3_live_llm.py                    # default 3 models
    python scripts/cegar/e3_live_llm.py z-ai/glm-5.2       # one model

Results (JSON) are written to scripts/cegar/results/ (git-ignored, regenerable).
This is a PILOT on 10 synthetic seed tasks, not the frozen E3 flagship (which
needs repository-split real defects, >=2 model families, >=5 seeds, and frozen
prompts — see papers/paper2/EXPERIMENT_PLAN.md §7).
"""
from __future__ import annotations

import json
import os
import sys
import time

# Make the repo root (holding the top-level ``benchmarks`` package) importable.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from agentproof.cegar.checker import check_certificate
from agentproof.cegar.ir import MayMustGraph, Verdict
from agentproof.cegar.llm_proposer import LLMProposer, openai_completer
from agentproof.cegar.policy import policy_from_dict
from agentproof.cegar.product import check
from agentproof.cegar.repair import GrammarProposer, RepairConfig, repair
from benchmarks.ap_repairbench.seed_tasks import build_seed_suite

DEFAULT_MODELS = [
    "z-ai/glm-5.2",
    "deepseek-ai/deepseek-v4-pro",
    "qwen/qwen3.5-397b-a17b",
]
CFG = RepairConfig()


class _Fixed:
    """Return a precomputed candidate list, so one cached LLM proposal feeds both
    the llm-only and combined arms without a second API call."""

    def __init__(self, seqs):
        self._seqs = seqs

    def propose(self, graph, policy, witness, config):
        return self._seqs


def _cert_ok(res) -> bool:
    return bool(res.success) and check_certificate(res.certificate).accepted


def main(models: list[str]) -> int:
    import openai

    client = openai.OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL"),
        api_key=os.environ.get("OPENAI_API_KEY"),
        timeout=300.0,
        max_retries=2,
    )

    tasks = []
    for t in build_seed_suite():
        g = MayMustGraph.from_dict(t.graph)
        p = policy_from_dict(t.policy)
        if check(g, p).verdict is not Verdict.SAFE:  # repairable
            tasks.append((t.task_id, t.defect_category, g, p, check(g, p).verdict.value))
    n = len(tasks)
    print(f"E3 LIVE  models={models}  repairable_tasks={n}\n" + "=" * 78, flush=True)

    false_certs = 0

    # Arm 1 — solver-only (model-independent).
    solver = {}
    for tid, _defect, g, p, _bv in tasks:
        r = repair(g, p, proposer=GrammarProposer())
        if r.success and not check_certificate(r.certificate).accepted:
            false_certs += 1
        solver[tid] = {"ok": _cert_ok(r), "cost": r.cost, "edits": r.edits}
    print(f"[solver]  verified+certified: {sum(v['ok'] for v in solver.values())}/{n}", flush=True)

    # Arms 2 & 3 — per model.
    per_model: dict[str, dict] = {m: {} for m in models}
    for model in models:
        llm = LLMProposer(openai_completer(client=client, model=model), max_candidates=8)
        print(f"\n--- model: {model} ---", flush=True)
        for tid, _defect, g, p, _bv in tasks:
            t0 = time.time()
            witness = check(g, p).witness
            try:
                llm_seqs = llm.propose(g, p, witness, CFG)
                err = ""
            except Exception as e:  # endpoint hiccup: record, keep going
                llm_seqs, err = [], f"{type(e).__name__}: {e}"
            grammar_seqs = GrammarProposer().propose(g, p, witness, CFG)
            r_llm = repair(g, p, proposer=_Fixed(llm_seqs))
            r_comb = repair(g, p, proposer=_Fixed(llm_seqs + grammar_seqs))
            for r in (r_llm, r_comb):
                if r.success and not check_certificate(r.certificate).accepted:
                    false_certs += 1
            per_model[model][tid] = {
                "llm_ok": _cert_ok(r_llm), "llm_cost": r_llm.cost, "llm_edits": r_llm.edits,
                "comb_ok": _cert_ok(r_comb), "comb_cost": r_comb.cost, "comb_edits": r_comb.edits,
                "n_llm_candidates": len(llm_seqs), "seconds": round(time.time() - t0, 1),
                "error": err,
            }
            row = per_model[model][tid]
            print(f"  {tid:44s} llm={'Y' if row['llm_ok'] else 'n'} "
                  f"comb={'Y' if row['comb_ok'] else 'n'} cand={row['n_llm_candidates']} "
                  f"{row['seconds']:5.0f}s" + (f"  ERR {err[:60]}" if err else ""), flush=True)

    # Summary.
    def _rate(oks, costs):
        k = sum(oks)
        mc = round(sum(c for c, o in zip(costs, oks) if o) / k, 2) if k else None
        return f"{k}/{n} ({k / n:.0%})", mc

    print("\n" + "=" * 78, flush=True)
    print(f"{'arm':34s} {'verified+certified':>18s}  {'mean cost':>10s}", flush=True)
    r, mc = _rate([v["ok"] for v in solver.values()], [v["cost"] or 0 for v in solver.values()])
    print(f"{'solver-only':34s} {r:>18s}  {str(mc):>10s}", flush=True)
    for model in models:
        d = per_model[model]
        r, mc = _rate([v["llm_ok"] for v in d.values()], [v["llm_cost"] or 0 for v in d.values()])
        print(f"{('llm-only [' + model + ']'):34.34s} {r:>18s}  {str(mc):>10s}", flush=True)
        r, mc = _rate([v["comb_ok"] for v in d.values()], [v["comb_cost"] or 0 for v in d.values()])
        print(f"{('combined [' + model + ']'):34.34s} {r:>18s}  {str(mc):>10s}", flush=True)

    print("\ncomplementarity (verified repairs unique to each proposer, per model):", flush=True)
    for model in models:
        d = per_model[model]
        lns = sum(d[t]["llm_ok"] and not solver[t]["ok"] for t in d)
        snl = sum(solver[t]["ok"] and not d[t]["llm_ok"] for t in d)
        print(f"  {model}: LLM-only\\solver={lns}  solver\\LLM-only={snl}", flush=True)

    print(f"\nFALSE certificates across ALL arms/models (must be 0): {false_certs}", flush=True)
    assert false_certs == 0, "SOUNDNESS FAILURE: a reported repair failed independent certification"

    out = {
        "experiment": "E3_live_llm_arms",
        "note": "PILOT on synthetic seed tasks; not the frozen E3 flagship.",
        "models": models,
        "repairable": n,
        "false_certificates": false_certs,
        "solver": solver,
        "per_model": per_model,
    }
    os.makedirs(os.path.join(_REPO, "scripts/cegar/results"), exist_ok=True)
    path = os.path.join(_REPO, "scripts/cegar/results/e3_live_llm.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"results -> {path}\nE3 LIVE OK (zero false certificates)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or DEFAULT_MODELS))
