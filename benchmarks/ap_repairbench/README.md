# AP-RepairBench (scaffolding)

Proof-carrying repair benchmark for **AgentProof-CEGAR** (Paper 2). This
directory is the *scaffolding* described in `papers/paper2/EXPERIMENT_PLAN.md`
§5: the task schema, a **frozen** mutation taxonomy, repository-level
split/leakage discipline, and a set of programmatic **synthetic seed tasks**.

> **Status — everything here is synthetic.** Every task currently produced by
> `build_seed_suite()` is a synthetic seed: a small hand-built agent graph that
> mirrors an `examples/*.py` workflow, lifted to the may/must IR, verified
> `SAFE` against a realistic policy, then broken by exactly one reviewed
> mutation operator and verified `UNSAFE`/`UNKNOWN`. **No task here is a mined,
> human-confirmed real defect.** Real defects and mutated-real workflows require
> repository mining plus two-person validation and are deliberately **out of
> scope** for this scaffolding (see *Synthetic vs. real* below). Per plan §5 we
> never relabel a mutation as a real defect.

## Layout

| File | Purpose |
|---|---|
| `schema.py` | `RepairTask` dataclass + JSON (de)serialization (`to_dict`/`from_dict`, `load_task`, `load_suite`, `save_task`). |
| `mutations.py` | The **frozen** mutation taxonomy: `MUTATION_OPS`, `mutate(graph, policy, op_name, *, seed=0)`. |
| `splits.py` | `split_by_repository(...)`, `repo_key(...)`, `assert_no_repo_overlap(...)`. |
| `seed_tasks.py` | `build_seed_suite()`, `write_seed_suite(dir)`. |
| `tasks/*.json` | The written seed tasks (`seed__<family>__<op>.json`). |

Run from the repository root (so `benchmarks` is importable):

```bash
.venv/bin/python -c "from benchmarks.ap_repairbench.seed_tasks import build_seed_suite; \
    s=build_seed_suite(); print(len(s), 'seed tasks')"
.venv/bin/python -m benchmarks.ap_repairbench.seed_tasks   # writes tasks/*.json
```

## Task schema (`schema.py`)

A `RepairTask` is immutable and JSON-round-trippable. Fields mirror plan §5
("Each task requires …"):

- `task_id` — stable unique id (`seed__<family>__<op>` for seeds).
- `slice` — one of `real` | `mutated_real` | `official_example` | `adversarial`.
  Seeds use `official_example` (they mirror official-framework example workflows
  with semantic mutations); real / mutated-real / adversarial results are always
  reported **separately** (plan §5.1). Slice is validated on construction.
- `repo` / `repo_sha` — upstream repository provenance (`""` for synthetic).
- `framework` / `framework_version` — pinned framework identity.
- `source_path` — runnable source path (`""` for graph-only tasks; all seeds are
  graph-only, no framework install needed).
- `requirement_text` — natural-language requirement.
- `policy` — authoritative formal policy (`Policy.to_dict()` shape).
- `defect_category` — the defect class induced by the mutation (see taxonomy).
- `expected_verdict` — `unsafe` or `unknown`. **Never `safe`**: a benchmark task
  the analyzer certifies `SAFE` is a benchmark failure (plan §7, E2).
- `violating_trace` — a feasible violating event trace (list of event dicts), or
  `None` when the mutant only exhibits an `UNKNOWN` region.
- `graph` — the policy-violating may/must graph (`MayMustGraph.to_dict()` shape).
- `tool_schemas` — declared tool schemas referenced by graph/policy.
- `regression` — benign regression tasks / utility note (must stay `SAFE` after
  any repair).
- `human_patch` — a human repair description (not assumed uniquely correct).
- `validation` — `{status, validators, disagreements}`. Seeds are
  `status="synthetic_auto"` (machine-built, **not** two-person validated).
- `license` / `disclosure_status` / `redistribute` — licensing, disclosure, and
  redistribution decision.

`load_suite(dir)` loads only files carrying the full RepairTask key set and
silently skips unrelated JSON that may share the directory.

## Frozen mutation taxonomy (`mutations.py`)

The operator set, their semantics, and their defect labels are **frozen** before
final evaluation (plan §5). Adding an operator is a benchmark-versioning event,
not an in-place edit. Each operator takes a `SAFE` may/must graph plus the
policy it must make violable, and returns `(mutated_graph, defect_category,
note)`. Each is the inverse of one edit-grammar repair (plan §4.5), so a correct
repair is exactly the inverse edit.

| operator | defect_category | typical verdict | inverse repair (plan §4.5) |
|---|---|---|---|
| `drop_approval_gate` | `missing_approval_gate` | UNSAFE / UNKNOWN | (1) insert approval before effect |
| `widen_tool_binding` | `over_broad_tool_binding` | UNSAFE | (3) restrict tool binding |
| `remove_sanitizer` | `missing_sanitizer` | UNSAFE | (6) add sanitizer / declassifier |
| `unbound_retry` | `unbounded_retry` | UNKNOWN | (8) bound a loop / retry count |
| `swap_recipient` | `illegal_recipient` | UNSAFE | (3)/(2) restrict argument / guard |
| `swap_argument` | `illegal_argument_value` | UNSAFE | (2) strengthen router guard |
| `bypass_exit` | `commit_boundary_bypass` | UNKNOWN | (7) repair bypass / incorrect exit |
| `escalate_capability` | `capability_escalation` | UNSAFE | (3) restrict capability |
| `drop_auth_precondition` | `missing_authorization` | UNSAFE | (5) add auth state + precondition |

**Soundness contract.** A mutation must never yield a graph the analyzer can
certify `SAFE`. `seed_tasks.py` re-runs `agentproof.cegar.product.check` after
each mutation and raises if the result is `SAFE`. Some operators intentionally
produce `UNKNOWN` (an unbounded loop for `unbound_retry`, a may-only bypass edge
for `bypass_exit`, or a conditional branch for `drop_approval_gate` on a routed
workflow) — that is honest tri-valued ground truth, and those tasks carry
`expected_verdict="unknown"` with `violating_trace=None`.

## Split and leakage discipline (`splits.py`)

Per plan §5.1:

- **Split by repository, never by file, trace, or mutation.** All mutations of
  one workflow share a `repo_key` and land in the same split.
- Real tasks key on `repo`; synthetic seeds (which have `repo == ""`) key on the
  **workflow family** — `task_id` up to the last `__` — so every
  `seed__customer_support__*` stays together. Forks / near-duplicates should be
  given the same upstream `repo` string so they collapse to one key.
- **Framework / version holdouts → OOD.** `holdout_frameworks=(...)` routes those
  tasks to the `ood` split for out-of-distribution testing.
- `assert_no_repo_overlap(train, test)` is the leakage guard — call it after
  every split. Assignment is deterministic in `seed` (a seeded shuffle; no
  wall-clock, no unseeded randomness).

```python
from benchmarks.ap_repairbench.schema import load_suite
from benchmarks.ap_repairbench.splits import split_by_repository, assert_no_repo_overlap

tasks = load_suite("benchmarks/ap_repairbench/tasks")
s = split_by_repository(tasks, seed=7, holdout_frameworks=("adk",))
assert_no_repo_overlap(s["train"], s["test"])
```

## Synthetic vs. real

**All current tasks are synthetic seeds.** They exist so the analyzer, CEGAR,
repair, and certificate loops have runnable, self-contained ground truth *now*,
and so the schema / mutation / split machinery is exercised end-to-end. They are
**not** evidence of real-world defect prevalence and must never be reported as
such.

The three remaining slices are **not populated here** and require work outside
this scaffolding:

- `real` — mined, human-confirmed defects (plan §5: 20+ sought), each with
  runnable source, disclosure handling, and **two-person validation**.
- `mutated_real` — real workflows with policy-breaking mutations from these same
  frozen operators, in pinned containers.
- `adversarial` — aliasing / callbacks / parallelism / exceptions / nested
  agents / reflection stress programs.

When those are added, keep their results **separate** from the synthetic seeds
(plan §5.1), freeze policies before generating held-out attacks, and do not let
evaluation models retrieve the gold issue or patch.

## How the experiments (E0–E8) use this

- **E0 — semantic conformance:** each task's `policy` + `violating_trace` is a
  differential check between the direct oracle and the product checker (the
  concrete trace must be judged a violation by both).
- **E1 — conservative extraction:** the `graph` (may/must IR) plus
  `tool_schemas` feed extraction-fidelity / containment measurements.
- **E2 — tri-valued diagnosis & CEGAR:** `expected_verdict` is the label for
  false-SAFE / UNSAFE-precision / UNKNOWN-rate accounting. **No task may come
  back `SAFE`.**
- **E3 — verified repair (flagship):** the mutant `graph` is the input; the
  frozen operator's inverse edit (and `human_patch`) is the reference repair; the
  `regression` bundle is the benign-utility gate. Repair success = policy-safe
  **and** regression-passing on held-out repositories.
- **E4 — generalization:** `split_by_repository(..., holdout_frameworks=...)`
  produces the unseen-repository and framework-holdout (OOD) evaluations.
- **E5 — static/runtime partition:** `expected_verdict` partitions effects into
  the SAFE / UNSAFE / UNKNOWN regions the runtime layer must handle.
- **E7 — policy translation ablation:** `requirement_text` ↔ `policy` pairs are
  the NL-to-policy targets.
- **E8 — ablations & scalability:** `defect_category` and per-slice grouping
  drive the per-category failure breakdowns; the seed suite is the smoke corpus.

Because every task is synthetic, the E3 flagship gate (plan §7) is **not**
satisfiable from this directory alone — the mutated-real and real slices must be
mined and validated first.
