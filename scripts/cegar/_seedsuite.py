"""Seed-suite loader for the AgentProof-CEGAR experiment runners.

The offline experiment runners (:mod:`e0_semantic_conformance`,
:mod:`e2_diagnosis`, :mod:`e3_repair`, :mod:`e5_partition`, :mod:`e8_ablation`)
all read the ``AP-RepairBench`` seed suite from
``benchmarks/ap_repairbench/tasks/*.json``. That directory is the shared
benchmark: it holds whatever tasks the benchmark builder has produced (richer
records with ``repo`` / ``human_patch`` / ``regression`` metadata, e.g. the
``seed__*`` files) **plus** a small set of hand-authored synthetic tasks this
module ships (``synthetic__*``) so the runners always exercise the full
SAFE / UNSAFE / UNKNOWN spread — including certifiable, uncertified, and
unsupported-region cases — even before the larger corpus lands.

Honesty note
------------
The ``synthetic__*`` tasks are **synthetic**: hand-authored may/must graphs and
typed policies with a known ground-truth verdict, built from the proven
constructions in the ``agentproof.cegar`` module smoke tests. They are NOT the
human-confirmed real-defect slice or the full mutation corpus of
``papers/paper2/EXPERIMENT_PLAN.md`` §5 (which the plan explicitly sizes to
include a synthetic slice); every synthetic task carries ``slice="synthetic"``
and the runners report which slice each task belongs to.

Coexistence discipline
----------------------
:func:`ensure_materialized` writes ONLY the ``synthetic__*`` files this module
owns; it never deletes or rewrites another builder's task files. Reading is the
union of every ``*.json`` in the directory, sorted by ``task_id`` for a stable
order, round-tripped through the IR/policy serializers.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Allow running the scripts directly from a repo checkout without an editable
# install: put <repo>/src on the path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentproof.cegar.ir import (  # noqa: E402
    AbstractValue,
    ControlKind,
    EffectKind,
    EffectNode,
    MayMustGraph,
    ModalEdge,
    Modality,
    Provenance,
    ToolSchema,
    UnsupportedFact,
    UnsupportedKind,
)
from agentproof.cegar.policy import (  # noqa: E402
    Approval,
    ArgConstraint,
    Bounded,
    Effect,
    Forbid,
    LeadsTo,
    Never,
    Op,
    Policy,
    RequireBefore,
    Tool,
    policy_from_dict,
)

# Default location the runners read from (plan §5, the AP-RepairBench seed).
TASKS_DIR = _REPO_ROOT / "benchmarks" / "ap_repairbench" / "tasks"

# Filename prefix for the synthetic tasks THIS module owns and materializes.
_SYNTH_PREFIX = "synthetic__"

# Provenance stamps reused across tasks.
_EXACT = Provenance(origin="ast_explicit", confidence="exact", source_span="seed.py:1:1")
_MAY = Provenance(origin="ast_inferred", confidence="may", source_span="seed.py:2:2")

_MUST = Modality.MUST
_MAY_MODE = Modality.MAY


# ---------------------------------------------------------------------------
# Task record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SeedTask:
    """One seed repair/diagnosis task.

    Attributes
    ----------
    task_id:
        Stable identifier; also the JSON filename stem.
    slice:
        Provenance slice (always ``"synthetic"`` here — see module docstring).
    description:
        One-line human description of the modelled program/policy.
    framework:
        Framework tag of the modelled program.
    graph:
        The may/must effect graph under analysis.
    policy:
        The typed safety/termination policy to check.
    expected_verdict:
        Ground-truth tri-valued verdict a correct analyzer should return
        (``"safe"`` / ``"unsafe"`` / ``"unknown"``).
    repairable:
        Whether a policy-safe, certificate-accepted repair is expected to exist
        within the finite edit grammar (used by E3). ``False`` for tasks that
        should stay ``UNKNOWN`` (e.g. an unmodeled reflection region). ``None``
        when the task record carries no such label (external benchmark tasks) —
        E3 then omits that task from its label-calibration check.
    assume_trace_conservative:
        Passed through to the analyzer/checker certification gate.
    """

    task_id: str
    slice: str
    description: str
    framework: str
    graph: MayMustGraph
    policy: Policy
    expected_verdict: str
    repairable: bool | None
    assume_trace_conservative: bool = False

    def to_json_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "slice": self.slice,
            "description": self.description,
            "framework": self.framework,
            "expected_verdict": self.expected_verdict,
            "repairable": self.repairable,
            "assume_trace_conservative": self.assume_trace_conservative,
            "policy": self.policy.to_dict(),
            "graph": self.graph.to_dict(),
        }

    @staticmethod
    def from_json_dict(d: dict) -> "SeedTask":
        raw_repairable = d.get("repairable", None)
        repairable = None if raw_repairable is None else bool(raw_repairable)
        return SeedTask(
            task_id=d["task_id"],
            slice=d.get("slice", "synthetic"),
            description=d.get("description", ""),
            framework=d.get("framework", ""),
            graph=MayMustGraph.from_dict(d["graph"]),
            policy=policy_from_dict(d["policy"]),
            expected_verdict=d["expected_verdict"],
            repairable=repairable,
            assume_trace_conservative=bool(d.get("assume_trace_conservative", False)),
        )


# ---------------------------------------------------------------------------
# Small graph-construction helpers
# ---------------------------------------------------------------------------

def _node(
    nid: str,
    *,
    effect: EffectKind = EffectKind.NONE,
    tool: str = "",
    cap: str = "",
    args: tuple = (),
    prov: Provenance = _EXACT,
    sp: tuple = (),
    unsupported: tuple = (),
    tool_schema: ToolSchema | None = None,
) -> EffectNode:
    return EffectNode(
        id=nid,
        effect=effect,
        tool=tool,
        capability=cap,
        abstract_args=args,
        provenance=prov,
        modeling_confidence=prov.confidence,
        state_predicates=sp,
        unsupported=unsupported,
        tool_schema=tool_schema,
    )


def _linear(
    name: str,
    framework: str,
    middle: list[EffectNode],
    *,
    graph_unsupported: tuple = (),
) -> MayMustGraph:
    """entry -> middle[0] -> ... -> exit, all MUST edges with exact provenance."""
    entry = _node("entry", sp=("kind:entry",))
    exit_ = _node("exit", sp=("kind:exit",))
    nodes = (entry, *middle, exit_)
    order = ["entry"] + [n.id for n in middle] + ["exit"]
    edges = tuple(
        ModalEdge(source=order[i], target=order[i + 1], modality=_MUST, provenance=_EXACT)
        for i in range(len(order) - 1)
    )
    return MayMustGraph(
        name=name,
        framework=framework,
        nodes=nodes,
        edges=edges,
        entry_id="entry",
        exit_ids=("exit",),
        unsupported=graph_unsupported,
    )


# ---------------------------------------------------------------------------
# The seed tasks (built from the proven module smoke-test constructions)
# ---------------------------------------------------------------------------

def _build_tasks() -> list[SeedTask]:
    tasks: list[SeedTask] = []

    def add(t: SeedTask) -> None:
        # Namespace every synthetic task id so its file never collides with a
        # benchmark-builder task in the shared directory.
        if not t.task_id.startswith(_SYNTH_PREFIX):
            t = SeedTask(**{**t.__dict__, "task_id": _SYNTH_PREFIX + t.task_id})
        tasks.append(t)

    # --- SAFE tasks -------------------------------------------------------
    add(SeedTask(
        task_id="safe_send_email_never_wire",
        slice="synthetic",
        description="Clean send_email flow vs Never(wire_transfer).",
        framework="langgraph",
        graph=_linear("safe_send", "langgraph", [
            _node("call", effect=EffectKind.COMMUNICATE, tool="send_email",
                  cap="invokes_tool", sp=("kind:tool",)),
        ]),
        policy=Never(Tool("wire_transfer"), rule_id="no_wire"),
        expected_verdict="safe",
        repairable=True,  # already safe -> repair() returns cost-0 success
    ))
    add(SeedTask(
        task_id="safe_approval_before_pay",
        slice="synthetic",
        description="Human approval precedes the financial effect (RequireBefore satisfied).",
        framework="langgraph",
        graph=_linear("safe_approve", "langgraph", [
            _node("approve", cap="human_pause", sp=("kind:human",)),
            _node("pay", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                  cap="invokes_tool", sp=("kind:tool",)),
        ]),
        policy=RequireBefore(Approval(), Effect(EffectKind.FINANCIAL),
                             strict=True, rule_id="approve_before_pay"),
        expected_verdict="safe",
        repairable=True,
    ))
    add(SeedTask(
        task_id="safe_send_without_read",
        slice="synthetic",
        description="send_email with no prior read vs Forbid(read_db -> send_email).",
        framework="langgraph",
        graph=_linear("safe_noexfil", "langgraph", [
            _node("send", tool="send_email", cap="invokes_tool", sp=("kind:tool",)),
        ]),
        policy=Forbid((Tool("read_db"), Tool("send_email")), contiguous=False,
                      rule_id="no_exfil"),
        expected_verdict="safe",
        repairable=True,
    ))
    add(SeedTask(
        task_id="safe_retry_within_bound",
        slice="synthetic",
        description="Two retries within a Bounded(k=2) quota.",
        framework="langgraph",
        graph=_linear("safe_retry", "langgraph", [
            _node("r1", tool="retry", cap="invokes_tool", sp=("kind:tool",)),
            _node("r2", tool="retry", cap="invokes_tool", sp=("kind:tool",)),
        ]),
        policy=Bounded(Tool("retry"), 2, rule_id="max_retry"),
        expected_verdict="safe",
        repairable=True,
    ))
    add(SeedTask(
        task_id="safe_leadsto_answered",
        slice="synthetic",
        description="open is answered by close before end of trace (LeadsTo satisfied).",
        framework="langgraph",
        graph=_linear("safe_leadsto", "langgraph", [
            _node("open", tool="open", cap="invokes_tool", sp=("kind:tool",)),
            _node("close", tool="close", cap="invokes_tool", sp=("kind:tool",)),
        ]),
        policy=LeadsTo(Tool("open"), Tool("close"), rule_id="close_it"),
        expected_verdict="safe",
        repairable=True,
    ))

    # --- UNSAFE tasks -----------------------------------------------------
    add(SeedTask(
        task_id="unsafe_wire_transfer_never",
        slice="synthetic",
        description="Forbidden wire_transfer on a MUST path vs Never(wire_transfer).",
        framework="langgraph",
        graph=_linear("unsafe_wire", "langgraph", [
            _node("call", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                  cap="invokes_tool", sp=("kind:tool",)),
        ]),
        policy=Never(Tool("wire_transfer"), rule_id="no_wire"),
        expected_verdict="unsafe",
        repairable=True,  # RestrictToolBinding
    ))
    add(SeedTask(
        task_id="unsafe_pay_without_approval",
        slice="synthetic",
        description="Financial effect with no prior approval vs RequireBefore(Approval, FINANCIAL).",
        framework="langgraph",
        graph=_linear("unsafe_pay", "langgraph", [
            _node("pay", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                  cap="invokes_tool", sp=("kind:tool",)),
        ]),
        policy=RequireBefore(Approval(), Effect(EffectKind.FINANCIAL),
                             strict=True, rule_id="approve_before_pay"),
        expected_verdict="unsafe",
        repairable=True,  # InsertApprovalBefore
    ))
    add(SeedTask(
        task_id="unsafe_read_then_send_exfil",
        slice="synthetic",
        description="read_db then send_email realises a forbidden exfiltration subsequence.",
        framework="langgraph",
        graph=_linear("unsafe_exfil", "langgraph", [
            _node("read", tool="read_db", cap="invokes_tool", sp=("kind:tool",)),
            _node("send", tool="send_email", cap="invokes_tool", sp=("kind:tool",)),
        ]),
        policy=Forbid((Tool("read_db"), Tool("send_email")), contiguous=False,
                      rule_id="no_exfil"),
        expected_verdict="unsafe",
        repairable=True,  # RestrictToolBinding on read or send
    ))
    add(SeedTask(
        task_id="unsafe_retry_over_bound",
        slice="synthetic",
        description="A second retry exceeds Bounded(k=1).",
        framework="langgraph",
        graph=_linear("unsafe_retry", "langgraph", [
            _node("r1", tool="retry", cap="invokes_tool", sp=("kind:tool",)),
            _node("r2", tool="retry", cap="invokes_tool", sp=("kind:tool",)),
        ]),
        policy=Bounded(Tool("retry"), 1, rule_id="max_retry"),
        expected_verdict="unsafe",
        repairable=True,  # RestrictToolBinding removes the retry tool
    ))
    add(SeedTask(
        task_id="unsafe_leadsto_unfulfilled",
        slice="synthetic",
        description="open with no close before the only (MUST) exit (LeadsTo unfulfilled).",
        framework="langgraph",
        graph=_linear("unsafe_leadsto", "langgraph", [
            _node("open", tool="open", cap="invokes_tool", sp=("kind:tool",)),
        ]),
        policy=LeadsTo(Tool("open"), Tool("close"), rule_id="close_it"),
        expected_verdict="unsafe",
        repairable=True,  # RestrictToolBinding(open) removes the trigger -> vacuously safe
    ))
    add(SeedTask(
        task_id="unsafe_amount_over_cap_const",
        slice="synthetic",
        description="wire_transfer with a constant amount above the cap vs Never(amount>10000).",
        framework="langgraph",
        graph=_linear("unsafe_amount", "langgraph", [
            _node("pay", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                  cap="invokes_tool", sp=("kind:tool",),
                  args=(("amount", AbstractValue.const(20000)),)),
        ]),
        policy=Never(ArgConstraint("wire_transfer", "amount", Op.GT, 10000),
                     rule_id="amount_cap"),
        expected_verdict="unsafe",
        repairable=True,  # RestrictToolBinding
    ))

    # --- UNKNOWN-then-CEGAR-refined tasks --------------------------------
    # product.check reports UNKNOWN (may-violation candidate over a TOP arg),
    # but cegar.analyze concretizes it to a genuine UNSAFE (amount=10001).
    add(SeedTask(
        task_id="cegar_amount_top_refines_to_unsafe",
        slice="synthetic",
        description="wire_transfer with an unbounded amount; CEGAR concretizes the cap violation.",
        framework="langgraph",
        graph=_linear("cegar_amount", "langgraph", [
            _node("pay", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                  cap="invokes_tool", sp=("kind:tool",),
                  args=(("amount", AbstractValue.top()),)),
        ]),
        policy=Never(ArgConstraint("wire_transfer", "amount", Op.GT, 10000),
                     rule_id="amount_cap"),
        expected_verdict="unsafe",
        repairable=True,
    ))
    # A spurious MAY branch guarded by "false": product UNKNOWN, CEGAR refines
    # the dead edge away and proves SAFE.
    add(SeedTask(
        task_id="cegar_spurious_branch_refines_to_safe",
        slice="synthetic",
        description="A dead (guard=false) MAY branch to wire_transfer; CEGAR refutes it -> SAFE.",
        framework="langgraph",
        graph=MayMustGraph(
            name="cegar_spurious", framework="langgraph",
            nodes=(
                _node("entry", sp=("kind:entry",)),
                _node("branch", sp=("kind:router",), cap="routes"),
                _node("badcall", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                      cap="invokes_tool", sp=("kind:tool",)),
                _node("exit", sp=("kind:exit",)),
            ),
            edges=(
                ModalEdge("entry", "branch", modality=_MUST, provenance=_EXACT),
                ModalEdge("branch", "badcall", modality=_MAY_MODE, guard="false",
                          control=ControlKind.CONDITIONAL, provenance=_EXACT),
                ModalEdge("branch", "exit", modality=_MAY_MODE,
                          control=ControlKind.CONDITIONAL, provenance=_EXACT),
                ModalEdge("badcall", "exit", modality=_MAY_MODE, provenance=_EXACT),
            ),
            entry_id="entry", exit_ids=("exit",),
        ),
        policy=Never(Tool("wire_transfer"), rule_id="no_wire"),
        expected_verdict="safe",
        repairable=True,
    ))

    # --- Genuinely UNKNOWN tasks (certification gate holds) ---------------
    add(SeedTask(
        task_id="unknown_nonexact_provenance",
        slice="synthetic",
        description="A structurally clean flow whose effect node has non-exact (guessed) provenance.",
        framework="langgraph",
        graph=_linear("unknown_prov", "langgraph", [
            _node("call", effect=EffectKind.COMMUNICATE, tool="send_email",
                  cap="invokes_tool", sp=("kind:tool",), prov=_MAY),
        ]),
        policy=Never(Tool("wire_transfer"), rule_id="no_wire"),
        expected_verdict="unknown",
        # A least-privilege re-bind resynthesizes the node with exact (trusted)
        # provenance, so the region becomes certifiable and the repair verifies.
        repairable=True,
    ))
    add(SeedTask(
        task_id="unknown_reflection_unsupported",
        slice="synthetic",
        description="An effect node that performs reflection (getattr) — outside the abstraction contract.",
        framework="langgraph",
        graph=_linear("unknown_reflect", "langgraph", [
            _node("call", effect=EffectKind.EXECUTE, tool="dynamic_call",
                  cap="invokes_tool", sp=("kind:tool",),
                  unsupported=(UnsupportedFact(UnsupportedKind.REFLECTION,
                                               detail="getattr(mod, name)()"),)),
        ]),
        policy=Never(Tool("wire_transfer"), rule_id="no_wire"),
        expected_verdict="unknown",
        repairable=False,  # RouteUnknownToApproval cannot erase the unsupported fact
    ))
    add(SeedTask(
        task_id="unknown_unknown_effect",
        slice="synthetic",
        description="A tool node whose effect kind could not be resolved (UNKNOWN effect).",
        framework="langgraph",
        graph=_linear("unknown_effect", "langgraph", [
            _node("call", effect=EffectKind.UNKNOWN, tool="mystery_tool",
                  cap="invokes_tool", sp=("kind:tool",),
                  unsupported=(UnsupportedFact(UnsupportedKind.INCOMPLETE_SCHEMA,
                                               detail="mystery_tool effect unresolved"),)),
        ]),
        policy=Never(Effect(EffectKind.FINANCIAL), rule_id="no_financial"),
        expected_verdict="unknown",
        repairable=False,
    ))
    add(SeedTask(
        task_id="cegar_leadsto_may_skip_unsafe",
        slice="synthetic",
        description="A MAY branch can end after open with no close; CEGAR concretizes the "
                    "unfulfilled-obligation trace (product UNKNOWN -> analysis UNSAFE).",
        framework="langgraph",
        graph=MayMustGraph(
            name="cegar_leadsto", framework="langgraph",
            nodes=(
                _node("entry", sp=("kind:entry",)),
                _node("open", tool="open", cap="invokes_tool", sp=("kind:tool",)),
                _node("close", tool="close", cap="invokes_tool", sp=("kind:tool",)),
                _node("exit1", sp=("kind:exit",)),
                _node("exit2", sp=("kind:exit",)),
            ),
            edges=(
                ModalEdge("entry", "open", modality=_MUST, provenance=_EXACT),
                ModalEdge("open", "exit1", modality=_MAY_MODE,
                          control=ControlKind.CONDITIONAL, provenance=_EXACT),
                ModalEdge("open", "close", modality=_MAY_MODE,
                          control=ControlKind.CONDITIONAL, provenance=_EXACT),
                ModalEdge("close", "exit2", modality=_MAY_MODE, provenance=_EXACT),
            ),
            entry_id="entry", exit_ids=("exit1", "exit2"),
        ),
        policy=LeadsTo(Tool("open"), Tool("close"), rule_id="close_it"),
        expected_verdict="unsafe",
        repairable=True,  # StrengthenRouterGuard closes off the skipping branch
    ))

    return sorted(tasks, key=lambda t: t.task_id)


# ---------------------------------------------------------------------------
# Persistence / loading
# ---------------------------------------------------------------------------

def ensure_materialized(tasks_dir: Path = TASKS_DIR, *, force: bool = False) -> list[Path]:
    """Write the synthetic (``synthetic__*``) tasks this module owns to ``tasks_dir``.

    Deterministic, idempotent, and non-destructive: a ``synthetic__*`` file is
    (re)written only when missing or when its content differs (or ``force`` is
    set); files owned by other benchmark builders (e.g. ``seed__*``) are never
    touched. Returns the list of synthetic task file paths, sorted.
    """
    tasks_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for task in _build_tasks():
        path = tasks_dir / f"{task.task_id}.json"
        payload = json.dumps(task.to_json_dict(), sort_keys=True, indent=2) + "\n"
        if force or not path.exists() or path.read_text(encoding="utf-8") != payload:
            path.write_text(payload, encoding="utf-8")
        paths.append(path)
    return sorted(paths)


def load_seed_suite(tasks_dir: Path = TASKS_DIR) -> list[SeedTask]:
    """Load the whole seed suite from ``tasks_dir`` (the union of every ``*.json``).

    Ensures the synthetic tasks are present (materializing them non-destructively
    first), then reads every ``*.json`` task file — both the synthetic ones and
    any external benchmark tasks — round-tripping through the IR/policy
    serializers, sorted by ``task_id`` for a stable order.
    """
    ensure_materialized(tasks_dir)
    tasks: list[SeedTask] = []
    for path in sorted(tasks_dir.glob("*.json")):
        with open(path, "r", encoding="utf-8") as fh:
            tasks.append(SeedTask.from_json_dict(json.load(fh)))
    return sorted(tasks, key=lambda t: t.task_id)


def synthetic_only(suite: list[SeedTask]) -> list[SeedTask]:
    """The subset of ``suite`` made of this module's synthetic tasks."""
    return [t for t in suite if t.task_id.startswith(_SYNTH_PREFIX)]


def add_common_args(parser) -> None:
    """Attach the shared ``--tasks-dir`` / ``--out`` options to an argparse parser."""
    parser.add_argument(
        "--tasks-dir", type=Path, default=TASKS_DIR,
        help="directory holding the AP-RepairBench seed task JSON files "
             f"(default: {TASKS_DIR})",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="path to write the JSON results (default: scripts/cegar/results/<exp>.json)",
    )


def results_path(default_name: str, override) -> Path:
    """Resolve the results output path (``override`` wins, else the default dir)."""
    if override is not None:
        return Path(override)
    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / default_name


def write_results(path: Path, payload: dict) -> None:
    """Write ``payload`` as pretty, key-sorted JSON (deterministic)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, sort_keys=True, indent=2, default=str)
        fh.write("\n")


if __name__ == "__main__":
    paths = ensure_materialized(force=True)
    print(f"materialized {len(paths)} synthetic seed tasks into {TASKS_DIR}")
    suite = load_seed_suite()
    print(f"seed suite = {len(suite)} tasks (synthetic + benchmark union):")
    for t in suite:
        print(f"  {t.task_id:48s} expect={t.expected_verdict:7s} "
              f"repairable={str(t.repairable):5s} slice={t.slice}")
