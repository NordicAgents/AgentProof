# AgentProof-CEGAR — Implementation Status

**Branch:** `paper2-cegar-impl` · **Built:** 2026-07-16 · maps to
[`EXPERIMENT_PLAN.md`](EXPERIMENT_PLAN.md) and [`README.md`](README.md).

This is a **research prototype of the software system** (build-order items 1–5,
plan §1.1a) with runnable benchmark scaffolding and experiment harnesses. It is
**not** a claim of final experimental results: the LLM-repair sweeps, real-defect
mining, and human study need models / data / recruitment and are staged as
runnable harnesses that honestly report which arms are not executed here.

## What is built (`src/agentproof/cegar/`, ~7.6k LOC)

| Module | Plan § | Role |
|---|---|---|
| `ir.py` | §4.1 | May/must effect IR: tri-valued `Verdict`; `EffectKind`; `Modality` (must/may/unknown); `ControlKind`; the `AbstractValue` lattice (`contains`/`join`/`leq`, finite-by-construction for CEGAR termination); `EffectNode`/`ModalEdge`/`MayMustGraph`; the `UnsupportedFact` taxonomy; `region_is_certifiable` SAFE-gate; concrete `EffectEvent`/`Trace`; non-destructive lift to/from Paper 1's flat `AgentGraph`. |
| `policy.py` | §4.3 | Typed recursive policy language. Predicate atoms with **dual** `eval(event)` (concrete) and `abstract_eval(node)→(may,must)` (sound). Operators `Never`/`RequireBefore`/`Forbid`/`Bounded`/`LeadsTo`/`All`. `typecheck` + `classify` → shield-enforceable / termination-time / unsupported. JSON round-trip. |
| `oracle.py` | §4.3 | Slow, independent, denotational finite-trace evaluator + distinguishing-trace search. The E0 differential backbone. |
| `product.py` | §3, §4.4 | Tri-valued may/must product checker → SAFE / UNSAFE / UNKNOWN with source-level witnesses. SAFE only on a certifiable region (mirrors the reviewer-#6 gate). |
| `cegar.py` | §4.4, Thm 5 | CEGAR loop: symbolic (offline, no code-exec) concretizer, oracle-confirmed feasibility, monotone domain refinement over a finite candidate pool, `UNKNOWN`-on-timeout. Conditional-termination argument in the docstring. `Concretizer` Protocol leaves a real sandbox as a drop-in. |
| `repair.py` | §4.5, Thm 3/4 | Proof-carrying repair: the 10-operator finite edit grammar, published weighted cost model, `GrammarProposer` optimizer (LLM proposer is an injectable Protocol, **outside the TCB**), and a re-verify loop that accepts a patch **only** when the independent checker admits its certificate. |
| `certificate.py` | §4.6 | Certificate schema (program/policy hashes, deps, assumptions, abstract transitions, repair cost, regression manifest) + emitter. |
| `checker.py` | §4.6, Thm 2 | Deliberately small **independent** checker. Imports only `ir`/`policy`/`certificate`; re-derives the SAFE claim by its own reachability over the recorded graph+policy — it does **not** trust the analyzer or the recorded verdict. |
| `frontend/langgraph.py` | §4.2 | Enriched LangGraph → may/must lift: resolves tool effects from schemas, records conservative `UnsupportedFact`s (nested agents, dynamic dispatch, unresolved parallelism, guessed structure). Never drops a node/edge. |

Public API (`agentproof.cegar`): `analyze`, `repair`, `certify`,
`check_certificate`, `analyze_and_repair`.

## Benchmark (`benchmarks/ap_repairbench/`, ~1.6k LOC) — plan §5

`schema.py` (`RepairTask` + JSON I/O), `mutations.py` (**9 frozen** mutation
operators, each the inverse of a §4.5 edit, each guaranteed to yield UNSAFE **or**
UNKNOWN — never a false SAFE), `splits.py` (repository-level split + leakage
guard, framework holdout → OOD), `seed_tasks.py` (**10 self-contained synthetic
seed tasks** mirroring `examples/*.py` across LangGraph/AutoGen/CrewAI/ADK).
`tasks/` holds the 10 generated `seed__*.json`.

> **Honesty (per plan §5):** *all* current tasks are **synthetic seeds**. The
> `real` / `mutated_real` / `adversarial` slices require repository mining plus
> two-person validation and are **not populated**. The E3 flagship gate is not
> satisfiable from synthetic seeds alone.

## Experiment harnesses (`scripts/cegar/`, ~1.9k LOC) — plan §7

`e0_semantic_conformance.py`, `e2_diagnosis.py`, `e3_repair.py`,
`e5_partition.py`, `e8_ablation.py`, `reproduce_cegar.sh`. Each writes JSON to
`scripts/cegar/results/` and prints which arms are offline-only. Current
offline/solver-only numbers on the seed suite (illustrative, **not** headline
claims):

- **E0** — 0 mismatches over 32,208 (policy, trace) pairs; 6/6 malformed
  certificates rejected.
- **E2** — 0 false SAFE; UNSAFE precision 1.0; 18/18 concrete witnesses
  oracle-confirmed; UNKNOWN reduced by CEGAR.
- **E3** — solver-only: 22/22 verified repairs independently re-checked, 0
  calibration errors vs. task labels. *LLM-repair arms not run (no model).*
- **E5** — offline partition simulation: 17/20 expensive decisions avoided
  (0.85) on the seed suite.

## Tests (`tests/cegar/`, ~3.0k LOC, 112 tests)

Differential E0, abstraction-soundness properties, tri-valued product,
mutation, CEGAR, repair end-to-end, certificate rejection, benchmark, frontend.
**Full suite: 385 passed** (273 Paper 1 unchanged + 112 new).

## Load-bearing soundness invariants (independently re-probed)

1. `SAFE` is emitted only through the product certification gate on an
   exact/certifiable region — a guessed-provenance graph returns `UNKNOWN`,
   never a false `SAFE`.
2. Concretization upgrades to `UNSAFE` only when the **independent oracle**
   confirms a concrete violating trace.
3. The independent checker rejects every tampered certificate, including a
   graph tamper with a **consistent recomputed hash** (it re-derives the
   product rather than trusting the recorded verdict).
4. Repair reports `success` only when the independent checker accepts the
   patched program's certificate — a lying proposer cannot force a false
   success.

## Not done here (needs data / models / people)

- Real-defect and mutated-real-workflow benchmark slices (mining + 2-person
  validation, plan §5).
- LLM patch-proposer and multi-model repair sweeps (plan §6.2) — injection
  point exists (`repair.PatchProposer`), no model wired.
- Framework-native runtime-trace conformance for E1 containment (needs the
  frameworks installed to run untrusted code).
- Human repair study E6, NL-policy translation ablation E7 with a real model.
- A real sandboxed `Concretizer` (the symbolic IR-only default ships now).
