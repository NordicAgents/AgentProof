"""AP-RepairBench — proof-carrying repair benchmark (Paper 2, plan §5).

This package is *scaffolding*. It defines the task schema, a **frozen** mutation
taxonomy, repository-level split/leakage discipline, and a set of programmatic
**synthetic seed tasks**. It contains **no real, human-confirmed defects yet**:
every task currently produced by :func:`~benchmarks.ap_repairbench.seed_tasks.build_seed_suite`
is a synthetic seed built by applying a reviewed mutation operator to a small,
hand-built agent graph that mirrors one of the ``examples/*.py`` workflows.
Real defects and mutated-real workflows require mining plus two-person
validation and are explicitly out of scope for this scaffolding (see the
package README).

Public surface
--------------
* :mod:`schema`     — :class:`RepairTask` and JSON (de)serialization helpers.
* :mod:`mutations`  — the frozen mutation operators (:data:`MUTATION_OPS`) and
  :func:`mutate`.
* :mod:`splits`     — :func:`split_by_repository` and the leakage assertion.
* :mod:`seed_tasks` — :func:`build_seed_suite` / :func:`write_seed_suite`.
"""

from benchmarks.ap_repairbench.schema import (
    RepairTask,
    load_suite,
    load_task,
    save_task,
)

__all__ = [
    "RepairTask",
    "load_task",
    "load_suite",
    "save_task",
]
