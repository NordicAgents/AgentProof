"""AP-RepairBench seed suite (test fixture for Paper 2, plan §5.1).

A small, deterministic, repository-split benchmark of human-confirmed defect
graphs used by :mod:`tests.cegar.test_benchmark`. It lives under ``tests`` (not
``src``) because it is a *test artifact*: a hand-built stand-in for the runnable
AP-RepairBench tasks, sufficient to exercise the loader / repository-split /
analyze contract without pulling in framework extraction.

Each :class:`SeedTask` carries a provenance-complete
:class:`~agentproof.cegar.ir.MayMustGraph`, the :class:`~agentproof.cegar.policy.Policy`
it is judged against, its ``repository`` (for the leakage-audited split), and the
``expected_verdict`` a sound analyzer must return. The cardinal invariant the
benchmark test enforces is *never a false SAFE*: no seed whose expected verdict
is ``UNSAFE`` / ``UNKNOWN`` may analyze to ``SAFE``.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentproof.cegar.ir import (
    EffectKind,
    EffectNode,
    MayMustGraph,
    ModalEdge,
    Modality,
    Provenance,
    UnsupportedFact,
    UnsupportedKind,
    Verdict,
)
from agentproof.cegar.policy import (
    Approval,
    Bounded,
    Effect,
    Forbid,
    Never,
    Policy,
    RequireBefore,
    Tool,
)

_EXACT = Provenance(origin="ast_explicit", confidence="exact", source_span="seed.py:1:1")
_MUST = Modality.MUST


def _node(nid: str, **kwargs: object) -> EffectNode:
    """Exact-provenance node so certifiable regions can reach SAFE."""
    return EffectNode(
        id=nid,
        provenance=_EXACT,
        modeling_confidence="exact",
        **kwargs,  # type: ignore[arg-type]
    )


def _line(*node_ids: str) -> tuple[ModalEdge, ...]:
    return tuple(
        ModalEdge(node_ids[i], node_ids[i + 1], modality=_MUST, provenance=_EXACT)
        for i in range(len(node_ids) - 1)
    )


@dataclass(frozen=True)
class SeedTask:
    """One human-confirmed defect (or control) in AP-RepairBench."""

    task_id: str
    repository: str
    defect_kind: str
    graph: MayMustGraph
    policy: Policy
    expected_verdict: Verdict


def build_seed_suite() -> list[SeedTask]:
    """The deterministic seed suite (repository-split, leakage-audited).

    Returns tasks across four distinct repositories. Verdicts are pinned to what
    a sound tri-valued analyzer must produce; the benchmark test asserts each
    seed analyzes to exactly its ``expected_verdict`` and never a false SAFE.
    """
    tasks: list[SeedTask] = []

    # -- repo-finance: unguarded financial effect (defect) vs approval control --
    fin_defect = MayMustGraph(
        name="finance-pay-unguarded",
        framework="langgraph",
        nodes=(
            _node("entry", state_predicates=("kind:entry",)),
            _node("pay", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                  capability="invokes_tool", state_predicates=("kind:tool",)),
            _node("exit", state_predicates=("kind:exit",)),
        ),
        edges=_line("entry", "pay", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    approve_before_pay = RequireBefore(
        Approval(), Effect(EffectKind.FINANCIAL), strict=True,
        rule_id="approve_before_financial",
    )
    tasks.append(SeedTask(
        task_id="finance-001", repository="repo-finance",
        defect_kind="missing_approval",
        graph=fin_defect, policy=approve_before_pay,
        expected_verdict=Verdict.UNSAFE,
    ))

    fin_control = MayMustGraph(
        name="finance-pay-approved",
        framework="langgraph",
        nodes=(
            _node("entry", state_predicates=("kind:entry",)),
            _node("approve", capability="human_pause",
                  state_predicates=("kind:human", "approval")),
            _node("pay", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                  capability="invokes_tool", state_predicates=("kind:tool",)),
            _node("exit", state_predicates=("kind:exit",)),
        ),
        edges=_line("entry", "approve", "pay", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    tasks.append(SeedTask(
        task_id="finance-002", repository="repo-finance",
        defect_kind="control_safe",
        graph=fin_control, policy=approve_before_pay,
        expected_verdict=Verdict.SAFE,
    ))

    # -- repo-messaging: read-then-send exfiltration (defect) -------------------
    exfil = MayMustGraph(
        name="messaging-exfil",
        framework="langgraph",
        nodes=(
            _node("entry", state_predicates=("kind:entry",)),
            _node("read", effect=EffectKind.READ, tool="read_database",
                  state_predicates=("kind:tool",)),
            _node("send", effect=EffectKind.COMMUNICATE, tool="send_email",
                  state_predicates=("kind:tool",)),
            _node("exit", state_predicates=("kind:exit",)),
        ),
        edges=_line("entry", "read", "send", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    no_exfil = Forbid((Tool("read_database"), Tool("send_email")),
                      contiguous=False, rule_id="no_exfil")
    tasks.append(SeedTask(
        task_id="messaging-001", repository="repo-messaging",
        defect_kind="exfiltration",
        graph=exfil, policy=no_exfil,
        expected_verdict=Verdict.UNSAFE,
    ))

    # -- repo-data: forbidden delete tool (defect) ------------------------------
    delete = MayMustGraph(
        name="data-delete",
        framework="langgraph",
        nodes=(
            _node("entry", state_predicates=("kind:entry",)),
            _node("rm", effect=EffectKind.DELETE, tool="delete_record",
                  state_predicates=("kind:tool",)),
            _node("exit", state_predicates=("kind:exit",)),
        ),
        edges=_line("entry", "rm", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    tasks.append(SeedTask(
        task_id="data-001", repository="repo-data",
        defect_kind="forbidden_tool",
        graph=delete, policy=Never(Tool("delete_record"), rule_id="no_delete"),
        expected_verdict=Verdict.UNSAFE,
    ))

    # -- repo-data: unmodeled nested agent -> genuinely UNKNOWN -----------------
    nested = MayMustGraph(
        name="data-nested-agent",
        framework="langgraph",
        nodes=(
            _node("entry", state_predicates=("kind:entry",)),
            _node("sub", effect=EffectKind.UNKNOWN,
                  state_predicates=("kind:subgraph",),
                  unsupported=(UnsupportedFact(UnsupportedKind.NESTED_AGENT,
                                               detail="subgraph sub"),)),
            _node("exit", state_predicates=("kind:exit",)),
        ),
        edges=_line("entry", "sub", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    tasks.append(SeedTask(
        task_id="data-002", repository="repo-data",
        defect_kind="nested_agent_unknown",
        graph=nested, policy=Never(Tool("delete_record"), rule_id="no_delete"),
        expected_verdict=Verdict.UNKNOWN,
    ))

    # -- repo-devops: retry quota exceeded (defect) -----------------------------
    retries = MayMustGraph(
        name="devops-retry",
        framework="langgraph",
        nodes=(
            _node("entry", state_predicates=("kind:entry",)),
            _node("r1", effect=EffectKind.EXECUTE, tool="run_shell",
                  state_predicates=("kind:tool",)),
            _node("r2", effect=EffectKind.EXECUTE, tool="run_shell",
                  state_predicates=("kind:tool",)),
            _node("exit", state_predicates=("kind:exit",)),
        ),
        edges=_line("entry", "r1", "r2", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    tasks.append(SeedTask(
        task_id="devops-001", repository="repo-devops",
        defect_kind="retry_quota",
        graph=retries, policy=Bounded(Tool("run_shell"), 1, rule_id="max_retry"),
        expected_verdict=Verdict.UNSAFE,
    ))

    return tasks


def split_by_repository(
    suite: list[SeedTask],
) -> tuple[list[SeedTask], list[SeedTask]]:
    """Deterministic repository-disjoint train/test split (leakage audit).

    Repositories are sorted and assigned alternately to train (even index) and
    test (odd index), so no repository's tasks straddle the split. Returns
    ``(train, test)``.
    """
    repos = sorted({t.repository for t in suite})
    test_repos = {r for i, r in enumerate(repos) if i % 2 == 1}
    train = [t for t in suite if t.repository not in test_repos]
    test = [t for t in suite if t.repository in test_repos]
    return train, test
