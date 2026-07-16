"""Synthetic seed tasks for AP-RepairBench (Paper 2, plan §5).

This module builds a small, self-contained set of **synthetic** repair tasks
programmatically. Each seed:

1. hand-builds a small *flat* :class:`~agentproof.graph.model.AgentGraph` that
   mirrors the shape of one of the ``examples/*.py`` workflows (customer
   support, incident response, change control, debate, research crew, ADK
   pipelines, …) — no framework install required;
2. lifts it to a may/must :class:`~agentproof.cegar.ir.MayMustGraph` with
   :func:`~agentproof.cegar.frontend.default_tool_schemas`;
3. attaches a realistic, type-checked policy and **verifies the graph is
   ``SAFE``** against it;
4. applies exactly one **frozen** mutation operator
   (:mod:`benchmarks.ap_repairbench.mutations`) to introduce a defect and
   **verifies the mutant is ``UNSAFE`` or ``UNKNOWN``** (never a false ``SAFE``).

Every task produced here is therefore synthetic and machine-labelled
(``validation.status == "synthetic_auto"``). None is a mined, human-confirmed
real defect. See ``README.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from agentproof.cegar.frontend import default_tool_schemas
from agentproof.cegar.ir import (
    AbstractValue,
    EffectKind,
    MayMustGraph,
    Modality,
    ToolSchema,
    Verdict,
)
from agentproof.cegar.policy import (
    Approval,
    ArgConstraint,
    Bounded,
    Capability,
    DataLabelIn,
    Effect,
    Never,
    Op,
    Policy,
    PolicyContext,
    RequireBefore,
    Tag,
    Tool,
    typecheck,
)
from agentproof.cegar.product import ProductResult, check
from agentproof.graph.model import AgentGraph, EdgeKind, GraphEdge, GraphNode, NodeKind

from benchmarks.ap_repairbench.mutations import mutate
from benchmarks.ap_repairbench.schema import RepairTask, save_task

TASKS_DIR = Path(__file__).resolve().parent / "tasks"

# Pinned framework versions the seed workflows are modelled against. These are
# the versions the front-end semantics target (plan §4.2 "pinned framework
# versions"); the synthetic graphs are framework-agnostic in construction.
_FRAMEWORK_VERSIONS = {
    "langgraph": "0.2.60",
    "autogen": "0.4.0",
    "crewai": "0.80.0",
    "adk": "0.3.0",
}


# ---------------------------------------------------------------------------
# Flat-graph construction helpers
# ---------------------------------------------------------------------------

def _n(node_id: str, kind: NodeKind, **kw: Any) -> GraphNode:
    return GraphNode(
        id=node_id,
        kind=kind,
        label=kw.get("label", node_id),
        tools=tuple(kw.get("tools", ())),
        origin="ast_explicit",
        confidence="exact",
        source_span=kw.get("span", f"seed:{node_id}:0:0"),
        effects=tuple(kw.get("effects", ())),
        capabilities=tuple(kw.get("caps", ())),
    )


def _e(src: str, dst: str, kind: EdgeKind = EdgeKind.DIRECT, cond: str = "") -> GraphEdge:
    return GraphEdge(
        source=src,
        target=dst,
        kind=kind,
        condition=cond,
        origin="ast_explicit",
        confidence="exact",
        source_span=f"seed:{src}->{dst}:0:0",
    )


def _flat(name: str, framework: str, nodes, edges, exit_id: str = "__end__") -> AgentGraph:
    return AgentGraph(
        name=name,
        framework=framework,
        nodes=tuple(nodes),
        edges=tuple(edges),
        entry_id="__start__",
        exit_ids=(exit_id,),
    )


def _set_args(mm: MayMustGraph, node_id: str, args: dict[str, Any]) -> MayMustGraph:
    node = mm.node_by_id(node_id)
    assert node is not None, node_id
    av = {k: AbstractValue.const(v) for k, v in args.items()}
    return mm.with_node(replace(node, abstract_args=tuple(av.items())))


def _set_out_labels(mm: MayMustGraph, node_id: str, labels: tuple[str, ...]) -> MayMustGraph:
    node = mm.node_by_id(node_id)
    assert node is not None, node_id
    return mm.with_node(replace(node, out_labels=labels))


def _add_state_pred(mm: MayMustGraph, node_id: str, pred: str) -> MayMustGraph:
    node = mm.node_by_id(node_id)
    assert node is not None, node_id
    if pred in node.state_predicates:
        return mm
    return mm.with_node(replace(node, state_predicates=node.state_predicates + (pred,)))


# ---------------------------------------------------------------------------
# Serialization helpers (self-contained; no private imports from the analyzer)
# ---------------------------------------------------------------------------

def _toolschema_to_dict(ts: ToolSchema) -> dict[str, Any]:
    return {
        "name": ts.name,
        "params": [
            {"name": p.name, "type": p.type, "sensitive": p.sensitive} for p in ts.params
        ],
        "effect": ts.effect.value,
        "authority_required": ts.authority_required,
        "reversible": ts.reversible,
        "complete": ts.complete,
    }


def _action_type(state_predicates: tuple[str, ...]) -> str:
    for sp in state_predicates:
        if sp.startswith("kind:"):
            return sp.split(":", 1)[1]
    return ""


def _event_from_node(mm: MayMustGraph, node_id: str) -> dict[str, Any] | None:
    n = mm.node_by_id(node_id)
    if n is None:
        return None
    ev: dict[str, Any] = {
        "node_id": n.id,
        "effect": n.effect.value,
        "action_type": _action_type(n.state_predicates),
    }
    if n.tool:
        ev["tool_name"] = n.tool
    args = {k: v.value for k, v in n.abstract_args if v.kind.value == "const"}
    if args:
        ev["args"] = args
    if n.authority:
        ev["authority"] = n.authority
    if n.capability:
        ev["capability"] = n.capability
    if n.in_labels:
        ev["in_labels"] = list(n.in_labels)
    if n.out_labels:
        ev["out_labels"] = list(n.out_labels)
    tags = [sp for sp in n.state_predicates if not sp.startswith("kind:")]
    if tags:
        ev["tags"] = tags
    return ev


def _trace_from_result(mm: MayMustGraph, result: ProductResult) -> list[dict[str, Any]] | None:
    """Serialize the product witness path into a feasible violating trace."""
    w = result.witness
    if w is None or not getattr(w, "product_path", None):
        return None
    trace: list[dict[str, Any]] = []
    for nid in w.product_path:
        ev = _event_from_node(mm, nid)
        if ev is not None:
            trace.append(ev)
    return trace or None


def _happy_path_trace(mm: MayMustGraph) -> list[dict[str, Any]]:
    """A benign MUST-path from entry to an exit (regression witness)."""
    trace: list[dict[str, Any]] = []
    seen: set[str] = set()
    cur = mm.entry_id
    while cur is not None and cur not in seen:
        seen.add(cur)
        ev = _event_from_node(mm, cur)
        if ev is not None:
            trace.append(ev)
        if cur in mm.exit_ids:
            break
        succs = mm.successors(cur, modality=Modality.MUST)
        cur = succs[0] if succs else None
    return trace


def _tool_schemas_for(mm: MayMustGraph, policy: Policy) -> dict[str, Any]:
    schemas = default_tool_schemas()
    names = {n.tool for n in mm.nodes if n.tool}
    for pr in policy.predicates():
        if isinstance(pr, Tool):
            names.add(pr.name)
        if isinstance(pr, ArgConstraint) and pr.tool:
            names.add(pr.tool)
    out: dict[str, Any] = {}
    for name in sorted(names):
        if name in schemas:
            out[name] = _toolschema_to_dict(schemas[name])
    return out


# ---------------------------------------------------------------------------
# Workflow specifications
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _WorkflowSpec:
    family: str                       # workflow family (repository-key stand-in)
    framework: str
    requirement: str
    op: str                           # mutation operator name
    policy: Policy
    human_patch: str
    build_flat: Callable[[], AgentGraph]
    ir_tweak: Callable[[MayMustGraph], MayMustGraph] = lambda mm: mm


def _customer_support() -> AgentGraph:
    # __start__ -> router -> (agent | escalate_human) -> refund_tool -> __end__
    return _flat(
        "customer_support",
        "langgraph",
        [
            _n("__start__", NodeKind.ENTRY),
            _n("router", NodeKind.ROUTER, caps=("routes",)),
            _n("agent", NodeKind.LLM, caps=("llm",)),
            _n("escalate_human", NodeKind.HUMAN, caps=("human_pause",)),
            _n("refund", NodeKind.TOOL, tools=("wire_transfer",)),
            _n("__end__", NodeKind.EXIT),
        ],
        [
            _e("__start__", "router"),
            _e("router", "escalate_human", EdgeKind.CONDITIONAL, "needs_human"),
            _e("router", "agent", EdgeKind.CONDITIONAL, "auto"),
            _e("agent", "escalate_human"),
            _e("escalate_human", "refund"),
            _e("refund", "__end__"),
        ],
    )


def _incident_response() -> AgentGraph:
    return _flat(
        "incident_response",
        "langgraph",
        [
            _n("__start__", NodeKind.ENTRY),
            _n("intake", NodeKind.LLM, caps=("llm",)),
            _n("triage", NodeKind.ROUTER, caps=("routes",)),
            _n("mitigate", NodeKind.TOOL, tools=("read_database",)),
            _n("__end__", NodeKind.EXIT),
        ],
        [
            _e("__start__", "intake"),
            _e("intake", "triage"),
            _e("triage", "mitigate"),
            _e("mitigate", "__end__"),
        ],
    )


def _change_control() -> AgentGraph:
    return _flat(
        "change_control",
        "autogen",
        [
            _n("__start__", NodeKind.ENTRY),
            _n("planner", NodeKind.LLM, caps=("llm",)),
            _n("implementer", NodeKind.LLM, caps=("llm",)),
            _n("apply_change", NodeKind.TOOL, tools=("run_shell",)),
            _n("__end__", NodeKind.EXIT),
        ],
        [
            _e("__start__", "planner"),
            _e("planner", "implementer"),
            _e("implementer", "apply_change"),
            _e("apply_change", "__end__"),
        ],
    )


def _debate() -> AgentGraph:
    return _flat(
        "moderated_debate",
        "autogen",
        [
            _n("__start__", NodeKind.ENTRY),
            _n("moderator", NodeKind.LLM, caps=("llm",)),
            _n("notify", NodeKind.TOOL, tools=("send_email",)),
            _n("__end__", NodeKind.EXIT),
        ],
        [
            _e("__start__", "moderator"),
            _e("moderator", "notify"),
            _e("notify", "__end__"),
        ],
    )


def _research_crew() -> AgentGraph:
    # researcher -> sanitizer -> writer(email). Sanitizer strips untrusted taint.
    return _flat(
        "research_crew",
        "crewai",
        [
            _n("__start__", NodeKind.ENTRY),
            _n("researcher", NodeKind.LLM, caps=("llm",)),
            _n("sanitize", NodeKind.PASSTHROUGH),
            _n("publish", NodeKind.TOOL, tools=("send_email",)),
            _n("__end__", NodeKind.EXIT),
        ],
        [
            _e("__start__", "researcher"),
            _e("researcher", "sanitize"),
            _e("sanitize", "publish"),
            _e("publish", "__end__"),
        ],
    )


def _adk_pipeline() -> AgentGraph:
    # delete requires human sign-off first
    return _flat(
        "adk_pipeline",
        "adk",
        [
            _n("__start__", NodeKind.ENTRY),
            _n("ingest", NodeKind.LLM, caps=("llm",)),
            _n("human_signoff", NodeKind.HUMAN, caps=("human_pause",)),
            _n("purge", NodeKind.TOOL, tools=("delete_record",)),
            _n("__end__", NodeKind.EXIT),
        ],
        [
            _e("__start__", "ingest"),
            _e("ingest", "human_signoff"),
            _e("human_signoff", "purge"),
            _e("purge", "__end__"),
        ],
    )


def _adk_compliance() -> AgentGraph:
    return _flat(
        "adk_compliance",
        "adk",
        [
            _n("__start__", NodeKind.ENTRY),
            _n("collect", NodeKind.LLM, caps=("llm",)),
            _n("redact", NodeKind.TOOL, tools=("write_record",)),
            _n("__end__", NodeKind.EXIT),
        ],
        [
            _e("__start__", "collect"),
            _e("collect", "redact"),
            _e("redact", "__end__"),
        ],
    )


def _treasury_transfer() -> AgentGraph:
    return _flat(
        "treasury_transfer",
        "langgraph",
        [
            _n("__start__", NodeKind.ENTRY),
            _n("prepare", NodeKind.LLM, caps=("llm",)),
            _n("transfer", NodeKind.TOOL, tools=("wire_transfer",)),
            _n("__end__", NodeKind.EXIT),
        ],
        [
            _e("__start__", "prepare"),
            _e("prepare", "transfer"),
            _e("transfer", "__end__"),
        ],
    )


def _payouts() -> AgentGraph:
    return _flat(
        "vendor_payouts",
        "langgraph",
        [
            _n("__start__", NodeKind.ENTRY),
            _n("select_vendor", NodeKind.LLM, caps=("llm",)),
            _n("payout", NodeKind.TOOL, tools=("wire_transfer",)),
            _n("__end__", NodeKind.EXIT),
        ],
        [
            _e("__start__", "select_vendor"),
            _e("select_vendor", "payout"),
            _e("payout", "__end__"),
        ],
    )


def _preview_commit() -> AgentGraph:
    # preview (transactional boundary) must precede the financial commit
    return _flat(
        "preview_commit",
        "langgraph",
        [
            _n("__start__", NodeKind.ENTRY),
            _n("build_batch", NodeKind.LLM, caps=("llm",)),
            _n("preview", NodeKind.PASSTHROUGH),
            _n("commit", NodeKind.TOOL, tools=("wire_transfer",)),
            _n("__end__", NodeKind.EXIT),
        ],
        [
            _e("__start__", "build_batch"),
            _e("build_batch", "preview"),
            _e("preview", "commit"),
            _e("commit", "__end__"),
        ],
    )


# Predicate constructors kept out of the spec literal for clarity.
def _taint_pred():
    from agentproof.cegar.policy import PredAnd

    return PredAnd(Effect(EffectKind.COMMUNICATE), DataLabelIn("untrusted"))


def _unauth_exec_pred():
    from agentproof.cegar.policy import Authority, PredAnd, PredNot

    return PredAnd(Effect(EffectKind.EXECUTE), PredNot(Authority("shell")))


# The full frozen seed suite (one workflow per mutation operator, plus a second
# use of drop_approval_gate on a delete effect).
_SPECS: tuple[_WorkflowSpec, ...] = (
    _WorkflowSpec(
        family="customer_support",
        framework="langgraph",
        requirement="A refund (financial effect) must be preceded by human approval.",
        op="drop_approval_gate",
        policy=RequireBefore(
            Approval(), Effect(EffectKind.FINANCIAL), rule_id="approval_before_refund"
        ),
        human_patch="Re-insert the human escalation/approval node on every path "
        "into the refund (wire_transfer) tool.",
        build_flat=_customer_support,
    ),
    _WorkflowSpec(
        family="adk_pipeline",
        framework="adk",
        requirement="Deleting a record requires human sign-off first.",
        op="drop_approval_gate",
        policy=RequireBefore(
            Approval(), Effect(EffectKind.DELETE), rule_id="approval_before_delete"
        ),
        human_patch="Re-insert the human_signoff node before the delete_record tool.",
        build_flat=_adk_pipeline,
    ),
    _WorkflowSpec(
        family="incident_response",
        framework="langgraph",
        requirement="The workflow must never invoke the destructive run_shell tool.",
        op="widen_tool_binding",
        policy=Never(Tool("run_shell"), rule_id="forbid_shell"),
        human_patch="Restrict the mitigate node's tool binding back to read_database.",
        build_flat=_incident_response,
    ),
    _WorkflowSpec(
        family="research_crew",
        framework="crewai",
        requirement="Untrusted content must be sanitized before it reaches an "
        "outbound email.",
        op="remove_sanitizer",
        policy=Never(_taint_pred(), rule_id="sanitize_before_send"),
        human_patch="Re-insert the sanitize node between researcher and publish so "
        "the untrusted label is cleared before send_email.",
        build_flat=_research_crew,
        ir_tweak=lambda mm: _set_out_labels(mm, "sanitize", ("clean",)),
    ),
    _WorkflowSpec(
        family="moderated_debate",
        framework="autogen",
        requirement="The notifier may send at most two emails per run (quota).",
        op="unbound_retry",
        policy=Bounded(Tool("send_email"), 2, rule_id="email_quota"),
        human_patch="Bound the notify loop to at most two send_email iterations.",
        build_flat=_debate,
    ),
    _WorkflowSpec(
        family="vendor_payouts",
        framework="langgraph",
        requirement="Payouts may only go to allow-listed recipients (never 'attacker').",
        op="swap_recipient",
        policy=Never(
            ArgConstraint("wire_transfer", "recipient", Op.EQ, "attacker"),
            rule_id="recipient_allowlist",
        ),
        human_patch="Constrain the payout recipient argument to the vendor allow-list.",
        build_flat=_payouts,
        ir_tweak=lambda mm: _set_args(
            mm, "payout", {"recipient": "vendor_acme", "amount": 500.0}
        ),
    ),
    _WorkflowSpec(
        family="treasury_transfer",
        framework="langgraph",
        requirement="A single wire transfer must never exceed $10,000.",
        op="swap_argument",
        policy=Never(
            ArgConstraint("wire_transfer", "amount", Op.GT, 10000),
            rule_id="transfer_amount_cap",
        ),
        human_patch="Add a router guard rejecting transfers with amount > 10000.",
        build_flat=_treasury_transfer,
        ir_tweak=lambda mm: _set_args(
            mm, "transfer", {"amount": 2500.0, "recipient": "payroll"}
        ),
    ),
    _WorkflowSpec(
        family="preview_commit",
        framework="langgraph",
        requirement="A financial commit must be preceded by a preview/confirmation "
        "boundary.",
        op="bypass_exit",
        policy=RequireBefore(
            Tag("preview"), Effect(EffectKind.FINANCIAL), rule_id="preview_before_commit"
        ),
        human_patch="Remove the bypass edge so every path to commit goes through "
        "preview.",
        build_flat=_preview_commit,
        ir_tweak=lambda mm: _add_state_pred(mm, "preview", "preview"),
    ),
    _WorkflowSpec(
        family="adk_compliance",
        framework="adk",
        requirement="No node may hold the 'admin' capability (least privilege).",
        op="escalate_capability",
        policy=Never(Capability("admin"), rule_id="least_privilege_admin"),
        human_patch="Drop the 'admin' capability from the redact node.",
        build_flat=_adk_compliance,
    ),
    _WorkflowSpec(
        family="change_control",
        framework="autogen",
        requirement="A shell execution must carry 'shell' authority (authorization "
        "before effect).",
        op="drop_auth_precondition",
        policy=Never(_unauth_exec_pred(), rule_id="authorize_before_shell"),
        human_patch="Add an authorization precondition granting 'shell' authority "
        "before apply_change runs.",
        build_flat=_change_control,
    ),
)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def _policy_context(mm: MayMustGraph) -> PolicyContext:
    # The declared tool vocabulary (plan §2.1) is the full trusted-tool set, not
    # only the tools this particular graph happens to bind — a policy may name a
    # forbidden tool the safe graph never uses (e.g. Never(Tool("run_shell"))).
    schemas = default_tool_schemas()
    return PolicyContext(
        tools=schemas,
        authorities=frozenset({"finance", "trading", "messaging", "admin", "shell", "writer"}),
        data_labels=frozenset({"untrusted", "clean"}),
        capabilities=frozenset(
            {"llm", "invokes_tool", "human_pause", "routes", "state_update", "subgraph", "admin"}
        ),
    )


def _build_one(spec: _WorkflowSpec) -> RepairTask:
    from agentproof.cegar.frontend import lift

    schemas = default_tool_schemas()
    flat = spec.build_flat()
    mm_safe = lift(flat, tool_schemas=schemas)
    mm_safe = spec.ir_tweak(mm_safe)

    # type-check the policy against the graph's declared vocabulary
    issues = typecheck(spec.policy, _policy_context(mm_safe))
    if issues:
        raise ValueError(f"{spec.family}: policy type errors: {issues}")

    # the un-mutated graph must be SAFE
    safe_result = check(mm_safe, spec.policy)
    if safe_result.verdict is not Verdict.SAFE:
        raise ValueError(
            f"{spec.family}: base graph is {safe_result.verdict} not SAFE "
            f"(reason={safe_result.unknown_reason})"
        )

    # apply the frozen mutation and require an UNSAFE/UNKNOWN mutant
    mm_bad, defect, note = mutate(mm_safe, spec.policy, spec.op)
    bad_result = check(mm_bad, spec.policy)
    if bad_result.verdict is Verdict.SAFE:
        raise ValueError(
            f"{spec.family}/{spec.op}: mutation produced a FALSE SAFE graph"
        )
    expected = "unsafe" if bad_result.verdict is Verdict.UNSAFE else "unknown"
    violating_trace = (
        _trace_from_result(mm_bad, bad_result)
        if bad_result.verdict is Verdict.UNSAFE
        else None
    )

    regression = {
        "must_stay_safe": True,
        "benign_traces": [_happy_path_trace(mm_safe)],
        "utility_note": "The certified repair must preserve the benign path shown "
        "in benign_traces and keep the workflow's declared task success.",
    }

    task_id = f"seed__{spec.family}__{spec.op}"
    return RepairTask(
        task_id=task_id,
        slice="official_example",
        framework=spec.framework,
        framework_version=_FRAMEWORK_VERSIONS.get(spec.framework, "unknown"),
        requirement_text=spec.requirement,
        policy=spec.policy.to_dict(),
        defect_category=defect,
        expected_verdict=expected,
        graph=mm_bad.to_dict(),
        repo="",  # synthetic: no upstream repository
        repo_sha="",
        source_path="",  # graph-only; no framework install
        violating_trace=violating_trace,
        tool_schemas=_tool_schemas_for(mm_bad, spec.policy),
        regression=regression,
        human_patch=spec.human_patch,
        validation={
            "status": "synthetic_auto",
            "validators": [],
            "disagreements": [],
            "note": f"machine-built; mutation={spec.op}; edit={note}",
        },
        license="CC-BY-4.0",
        disclosure_status="not_applicable_synthetic",
        redistribute=True,
    )


def build_seed_suite() -> list[RepairTask]:
    """Build the frozen synthetic seed suite (deterministic)."""
    return [_build_one(spec) for spec in _SPECS]


def write_seed_suite(directory: str | Path = TASKS_DIR) -> list[str]:
    """Build the seed suite and write one JSON file per task. Returns paths."""
    tasks = build_seed_suite()
    paths: list[str] = []
    for t in tasks:
        paths.append(save_task(t, Path(directory) / f"{t.task_id}.json"))
    return paths


if __name__ == "__main__":  # pragma: no cover
    written = write_seed_suite()
    print(f"wrote {len(written)} seed tasks to {TASKS_DIR}")
