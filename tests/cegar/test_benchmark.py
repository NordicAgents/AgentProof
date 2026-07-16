"""AP-RepairBench seed-suite contract (Paper 2, plan §5.1, §7).

Asserts the loader / repository-split / analyze contract over the seed suite
(:mod:`tests.cegar._seeds`): every seed round-trips through serialization, the
repository split has no repository overlap between train and test (leakage
audit), and every seed analyzes to exactly its ``expected_verdict`` — and,
crucially, NO defect seed ever analyzes to a false ``SAFE``.
"""

from __future__ import annotations

from agentproof.cegar.cegar import analyze
from agentproof.cegar.ir import MayMustGraph, Verdict
from agentproof.cegar.policy import policy_from_dict

from tests.cegar._seeds import SeedTask, build_seed_suite, split_by_repository


def test_seed_suite_loads_nonempty():
    suite = build_seed_suite()
    assert suite
    assert all(isinstance(t, SeedTask) for t in suite)
    # task ids are unique
    ids = [t.task_id for t in suite]
    assert len(ids) == len(set(ids))


def test_seed_suite_covers_multiple_repositories():
    suite = build_seed_suite()
    repos = {t.repository for t in suite}
    assert len(repos) >= 3  # a repository-split benchmark needs several repos


def test_every_seed_graph_roundtrips():
    for t in build_seed_suite():
        assert MayMustGraph.from_dict(t.graph.to_dict()) == t.graph


def test_every_seed_policy_roundtrips():
    for t in build_seed_suite():
        restored = policy_from_dict(t.policy.to_dict())
        assert restored.to_dict() == t.policy.to_dict()


def test_split_has_no_repository_overlap():
    suite = build_seed_suite()
    train, test = split_by_repository(suite)
    train_repos = {t.repository for t in train}
    test_repos = {t.repository for t in test}
    assert train_repos and test_repos
    assert train_repos.isdisjoint(test_repos)
    # the split partitions the suite (no task lost or duplicated)
    assert len(train) + len(test) == len(suite)
    assert {t.task_id for t in train}.isdisjoint({t.task_id for t in test})


def test_split_is_deterministic():
    suite = build_seed_suite()
    a = split_by_repository(suite)
    b = split_by_repository(suite)
    assert [t.task_id for t in a[0]] == [t.task_id for t in b[0]]
    assert [t.task_id for t in a[1]] == [t.task_id for t in b[1]]


def test_every_seed_analyzes_to_expected_verdict():
    for t in build_seed_suite():
        result = analyze(t.graph, t.policy)
        assert result.verdict is t.expected_verdict, (
            t.task_id, t.repository, "got", result.verdict, "expected", t.expected_verdict
        )


def test_no_defect_seed_is_a_false_safe():
    """The cardinal invariant: a seed whose expected verdict is not SAFE must
    never analyze to SAFE."""
    for t in build_seed_suite():
        if t.expected_verdict is Verdict.SAFE:
            continue
        result = analyze(t.graph, t.policy)
        assert result.verdict is not Verdict.SAFE, (
            "FALSE SAFE on defect seed", t.task_id, t.defect_kind
        )


def test_analyze_is_deterministic_over_suite():
    for t in build_seed_suite():
        first = analyze(t.graph, t.policy)
        second = analyze(t.graph, t.policy)
        assert first.verdict is second.verdict
