"""Repository-level split and leakage discipline for AP-RepairBench (plan §5.1).

The cardinal rule (plan §5.1): **split by repository, never by file, trace, or
mutation.** Every task derived from the same upstream repository — and every
fork or structural near-duplicate of it — must land in the *same* split, so a
model cannot memorize a repository in ``train`` and be scored on a sibling
mutation in ``test``. Framework and framework-version holdouts are reserved for
the out-of-distribution (``ood``) split.

Repository key
--------------
Real tasks carry a non-empty :attr:`~benchmarks.ap_repairbench.schema.RepairTask.repo`;
that string is the repository key directly. Synthetic seed tasks have ``repo == ""``
(they have no upstream repository), so their key falls back to the **workflow
family** encoded in the ``task_id`` — everything up to the last ``"__"`` (the
mutation suffix). All mutations of one synthetic workflow therefore share a key
and are kept in one split, exactly as forks of a real repository would be.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from benchmarks.ap_repairbench.schema import RepairTask


def repo_key(task: RepairTask) -> str:
    """Return the repository-level grouping key for ``task``.

    Uses the upstream ``repo`` when present; otherwise the workflow family
    (``task_id`` up to the last ``"__"``). Forks / near-duplicates should be
    given the *same* ``repo`` string upstream so they collapse to one key here.
    """
    if task.repo:
        return task.repo
    tid = task.task_id
    return tid.rsplit("__", 1)[0] if "__" in tid else tid


def split_by_repository(
    tasks: Sequence[RepairTask],
    *,
    seed: int,
    holdout_frameworks: Sequence[str] = (),
    test_fraction: float = 0.25,
) -> dict[str, list[RepairTask]]:
    """Partition ``tasks`` into ``{"train", "test", "ood"}`` by repository.

    * Every task whose ``framework`` is in ``holdout_frameworks`` goes to
      ``ood`` (framework holdout), regardless of its repository.
    * The remaining tasks are grouped by :func:`repo_key`; each *group* is
      assigned wholesale to ``train`` or ``test`` (never split), so no
      repository straddles the boundary.
    * Assignment is deterministic in ``seed`` (a seeded shuffle of the sorted
      group keys), never wall-clock or unseeded.

    ``test_fraction`` is the target share of non-holdout groups placed in
    ``test`` (rounded; at least one group in each of train/test when there are
    at least two groups).
    """
    if not 0.0 < test_fraction < 1.0:
        raise ValueError("test_fraction must be in (0, 1)")

    holdout = set(holdout_frameworks)
    ood: list[RepairTask] = []
    groups: dict[str, list[RepairTask]] = {}
    for t in tasks:
        if t.framework in holdout:
            ood.append(t)
            continue
        groups.setdefault(repo_key(t), []).append(t)

    keys = sorted(groups)  # deterministic base order
    rng = random.Random(seed)
    rng.shuffle(keys)

    n = len(keys)
    n_test = round(n * test_fraction)
    if n >= 2:
        n_test = min(max(n_test, 1), n - 1)  # keep both splits non-empty
    test_keys = set(keys[:n_test])

    train: list[RepairTask] = []
    test: list[RepairTask] = []
    for k in sorted(groups):  # stable output order
        (test if k in test_keys else train).extend(groups[k])

    return {"train": train, "test": test, "ood": ood}


def assert_no_repo_overlap(
    train: Sequence[RepairTask],
    test: Sequence[RepairTask],
) -> None:
    """Raise ``AssertionError`` if any repository key appears in both splits.

    This is the leakage guard for plan §5.1; call it after every split.
    """
    train_keys = {repo_key(t) for t in train}
    test_keys = {repo_key(t) for t in test}
    overlap = train_keys & test_keys
    assert not overlap, (
        "repository leakage between train and test splits: "
        f"{sorted(overlap)}"
    )
