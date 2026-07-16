"""Frozen mutation taxonomy for AP-RepairBench (Paper 2, plan §5).

Every operator here maps a **policy-satisfying** (``SAFE``) may/must graph to a
**policy-violating** graph and names the ``defect_category`` it induces. The
taxonomy is *frozen*: the operator set, their semantics, and their defect
labels are fixed here and must not change once evaluation begins (plan §5:
"Mutation operators must be fixed from an independently reviewed taxonomy
before final evaluation."). Adding an operator is a benchmark-versioning event,
not an in-place edit.

Soundness contract
------------------
A mutation must never yield a graph the analyzer can certify ``SAFE`` w.r.t. the
task policy. Each operator is designed so the mutated graph is diagnosed
``UNSAFE`` (a concretely feasible violation) or ``UNKNOWN`` (the violation
depends on an unbounded loop or a may-only bypass edge). Both outcomes are
acceptable ground truth; a ``SAFE`` result is a mutation bug. The seed-task
builder re-runs :mod:`agentproof.cegar.product` after every mutation and rejects
any that come back ``SAFE`` (see :mod:`benchmarks.ap_repairbench.seed_tasks`).

Each operator inverts one edit-grammar repair from plan §4.5, so a correct
repair is exactly the inverse edit:

===========================  =========================  ===============================
operator                     defect_category            inverse repair (plan §4.5)
===========================  =========================  ===============================
``drop_approval_gate``       ``missing_approval_gate``   (1) insert approval before effect
``widen_tool_binding``       ``over_broad_tool_binding`` (3) restrict tool binding
``remove_sanitizer``         ``missing_sanitizer``       (6) add sanitizer/declassifier
``unbound_retry``            ``unbounded_retry``         (8) bound a loop/retry count
``swap_recipient``           ``illegal_recipient``       (3)/(2) restrict argument/guard
``swap_argument``            ``illegal_argument_value``  (2) strengthen router guard
``bypass_exit``              ``commit_boundary_bypass``  (7) repair bypass/incorrect exit
``escalate_capability``      ``capability_escalation``   (3) restrict capability
``drop_auth_precondition``   ``missing_authorization``   (5) add auth state + precondition
===========================  =========================  ===============================
"""

from __future__ import annotations

import random
from dataclasses import replace

from agentproof.cegar.frontend import default_tool_schemas
from agentproof.cegar.ir import (
    AbstractValue,
    ControlKind,
    EffectKind,
    MayMustGraph,
    Modality,
    ModalEdge,
    Provenance,
)
from agentproof.cegar.policy import (
    All,
    ArgConstraint,
    Bounded,
    Capability,
    DataLabelIn,
    Op,
    Policy,
    PredAnd,
    PredNot,
    PredOr,
    Predicate,
    RequireBefore,
    Tool,
)

# The frozen, ordered list of operator names. Order is stable so seeds and
# splits are reproducible.
MUTATION_OPS: tuple[str, ...] = (
    "drop_approval_gate",
    "widen_tool_binding",
    "remove_sanitizer",
    "unbound_retry",
    "swap_recipient",
    "swap_argument",
    "bypass_exit",
    "escalate_capability",
    "drop_auth_precondition",
)


class MutationError(ValueError):
    """Raised when a graph does not contain the structure an operator needs."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def mutate(
    graph: MayMustGraph,
    policy: Policy,
    op_name: str,
    *,
    seed: int = 0,
) -> tuple[MayMustGraph, str, str]:
    """Apply mutation ``op_name`` to ``graph`` w.r.t. ``policy``.

    Parameters
    ----------
    graph:
        A ``SAFE`` may/must graph to break.
    policy:
        The authoritative policy the mutation must make violable. The operator
        reads the policy to locate its target (the forbidden tool, the guarded
        effect, the bad argument value, …).
    op_name:
        One of :data:`MUTATION_OPS`.
    seed:
        Deterministic tie-break seed (no wall-clock, no unseeded randomness).

    Returns
    -------
    ``(mutated_graph, defect_category, note)`` — the broken graph, its defect
    label, and a short human-readable description of the edit.
    """
    if op_name not in MUTATION_OPS:
        raise MutationError(
            f"unknown mutation {op_name!r}; expected one of {MUTATION_OPS}"
        )
    rng = random.Random(seed)
    return _DISPATCH[op_name](graph, policy, rng)


# ---------------------------------------------------------------------------
# Policy / graph inspection helpers
# ---------------------------------------------------------------------------

def _leaf_policies(policy: Policy) -> list[Policy]:
    """Flatten :class:`All` into its leaf sub-policies."""
    if isinstance(policy, All):
        out: list[Policy] = []
        for p in policy.policies:
            out.extend(_leaf_policies(p))
        return out
    return [policy]


def _iter_preds(pred: Predicate):
    """Yield every predicate node in ``pred``'s tree (pre-order)."""
    yield pred
    if isinstance(pred, PredNot):
        yield from _iter_preds(pred.inner)
    elif isinstance(pred, (PredAnd, PredOr)):
        yield from _iter_preds(pred.left)
        yield from _iter_preds(pred.right)


def _all_preds(policy: Policy):
    for p in _leaf_policies(policy):
        for atom in p.predicates():
            yield from _iter_preds(atom)


def _exact() -> Provenance:
    return Provenance(origin="ast_explicit", confidence="exact")


def _splice_node(graph: MayMustGraph, node_id: str) -> MayMustGraph:
    """Remove ``node_id`` and rewire each predecessor to each successor.

    The replacement edges are ``MUST`` when the predecessor ends up with a
    single successor (a forced transition) and ``MAY`` otherwise, mirroring the
    front-end's modality rule so certifiability is preserved.
    """
    preds = [e.source for e in graph.edges if e.target == node_id]
    succs = [e.target for e in graph.edges if e.source == node_id]
    kept = [e for e in graph.edges if e.source != node_id and e.target != node_id]

    # out-degree of each predecessor after the splice
    out_deg: dict[str, int] = {}
    for e in kept:
        out_deg[e.source] = out_deg.get(e.source, 0) + 1
    for p in preds:
        out_deg[p] = out_deg.get(p, 0) + len(succs)

    new_edges = list(kept)
    for p in preds:
        for s in succs:
            modality = Modality.MUST if out_deg.get(p, 0) == 1 else Modality.MAY
            new_edges.append(
                ModalEdge(
                    source=p,
                    target=s,
                    modality=modality,
                    control=ControlKind.DIRECT,
                    framework_rule="mutation:splice",
                    provenance=_exact(),
                )
            )
    nodes = tuple(n for n in graph.nodes if n.id != node_id)
    return replace(graph, nodes=nodes, edges=tuple(new_edges))


def _first(seq, pred, what: str):
    for x in seq:
        if pred(x):
            return x
    raise MutationError(f"no {what} found in graph")


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

def _mut_drop_approval_gate(graph, policy, rng):
    """Remove the human-approval node guarding an irreversible effect.

    Inverse of edit (1). Breaks a ``RequireBefore(Approval, guarded)`` rule by
    splicing out the approval/human node so the guarded effect becomes
    reachable with the obligation unmet.
    """
    approval = _first(
        graph.nodes,
        lambda n: (
            "human_pause" in n.capability
            or "kind:human" in n.state_predicates
        ),
        "human/approval node",
    )
    mutated = _splice_node(graph, approval.id)
    note = f"spliced out approval node {approval.id!r} before an irreversible effect"
    return mutated, "missing_approval_gate", note


def _mut_widen_tool_binding(graph, policy, rng):
    """Rebind a least-privilege tool node to a forbidden tool.

    Inverse of edit (3). Breaks a ``Never(Tool(x))`` rule by rebinding some
    existing tool node to the forbidden tool ``x`` (adopting its schema/effect).
    """
    forbidden = None
    for pr in _all_preds(policy):
        if isinstance(pr, Tool):
            forbidden = pr.name
            break
    if forbidden is None:
        raise MutationError("policy has no Tool(...) atom to widen toward")
    schemas = default_tool_schemas()
    schema = schemas.get(forbidden)
    victim = _first(
        graph.nodes,
        lambda n: n.tool and n.tool != forbidden,
        "reboundable tool node",
    )
    new_node = replace(
        victim,
        tool=forbidden,
        tool_schema=schema,
        effect=schema.effect if schema else victim.effect,
        authority=(schema.authority_required if schema else victim.authority)
        or victim.authority,
    )
    mutated = graph.with_node(new_node)
    note = f"widened tool binding of {victim.id!r}: {victim.tool!r} -> {forbidden!r}"
    return mutated, "over_broad_tool_binding", note


def _mut_remove_sanitizer(graph, policy, rng):
    """Remove a sanitizer node between a tainted source and an effect sink.

    Inverse of edit (6). Splices out the node whose ``out_labels`` clear a taint
    label, then re-taints the downstream sink's ``in_labels`` so a
    ``Never(effect AND in_label:taint)`` rule fires.
    """
    taint = None
    for pr in _all_preds(policy):
        if isinstance(pr, DataLabelIn):
            taint = pr.label
            break
    if taint is None:
        raise MutationError("policy has no DataLabelIn(...) atom (no taint label)")
    sanitizer = _first(
        graph.nodes,
        lambda n: any(
            "sanitizer" in sp for sp in n.state_predicates
        )
        or n.out_labels,
        "sanitizer node",
    )
    succs = [e.target for e in graph.edges if e.source == sanitizer.id]
    mutated = _splice_node(graph, sanitizer.id)
    # Re-taint the sinks that the sanitizer used to protect.
    for sid in succs:
        sink = mutated.node_by_id(sid)
        if sink is not None and taint not in sink.in_labels:
            mutated = mutated.with_node(
                replace(sink, in_labels=sink.in_labels + (taint,))
            )
    note = f"removed sanitizer {sanitizer.id!r}; re-tainted sinks {succs} with {taint!r}"
    return mutated, "missing_sanitizer", note


def _mut_unbound_retry(graph, policy, rng):
    """Add an unbounded loop back-edge over a bounded action.

    Inverse of edit (8). Breaks a ``Bounded(pred, k)`` rule by adding a
    self-loop (``ControlKind.LOOP``) over a node satisfying ``pred``, so the
    action's occurrence count is no longer bounded. The analyzer reports this
    ``UNKNOWN`` (the loop's iteration count is not statically bounded).
    """
    bounded = _first(
        _leaf_policies(policy),
        lambda p: isinstance(p, Bounded),
        "Bounded(...) rule",
    )
    target_atom = bounded.pred  # type: ignore[attr-defined]
    target = _first(
        graph.nodes,
        lambda n: any(pr.abstract_eval(n)[0] for pr in target_atom.atoms())
        if target_atom.atoms()
        else False,
        "node matching the bounded predicate",
    )
    loop = ModalEdge(
        source=target.id,
        target=target.id,
        modality=Modality.MAY,
        control=ControlKind.LOOP,
        framework_rule="mutation:unbound_retry",
        provenance=_exact(),
    )
    mutated = replace(graph, edges=graph.edges + (loop,))
    note = f"added unbounded self-loop on {target.id!r} (retry no longer bounded)"
    return mutated, "unbounded_retry", note


def _mut_swap_recipient(graph, policy, rng):
    """Point a message/transfer recipient at a forbidden value.

    Inverse of edits (2)/(3). Breaks a ``Never(ArgConstraint(tool, recipient, …))``
    rule by rewriting the target node's abstract recipient argument to a value
    that satisfies the forbidden constraint.
    """
    return _swap_arg(
        graph,
        policy,
        prefer_args=("recipient", "to", "account"),
        defect="illegal_recipient",
        label="recipient",
    )


def _mut_swap_argument(graph, policy, rng):
    """Rewrite a numeric/argument value into the forbidden region.

    Inverse of edit (2). Breaks a ``Never(ArgConstraint(tool, arg, op, value))``
    rule (e.g. ``amount > 10000``) by setting the node's abstract argument to a
    concrete value that violates it.
    """
    return _swap_arg(
        graph,
        policy,
        prefer_args=("amount", "quantity", "command", "query"),
        defect="illegal_argument_value",
        label="argument",
    )


def _swap_arg(graph, policy, *, prefer_args, defect, label):
    constraints = [
        pr for pr in _all_preds(policy) if isinstance(pr, ArgConstraint)
    ]
    if not constraints:
        raise MutationError("policy has no ArgConstraint(...) atom to swap")
    # Prefer a constraint whose argument matches the operator's arg family.
    chosen = None
    for want in prefer_args:
        for c in constraints:
            if c.arg == want:
                chosen = c
                break
        if chosen is not None:
            break
    if chosen is None:
        chosen = constraints[0]

    bad_value = _violating_value(chosen.op, chosen.value)
    victim = _first(
        graph.nodes,
        lambda n: (chosen.tool is None and n.tool) or n.tool == chosen.tool,
        f"tool node bound to {chosen.tool!r}",
    )
    args = dict(victim.abstract_args)
    args[chosen.arg] = AbstractValue.const(bad_value)
    new_node = replace(victim, abstract_args=tuple(args.items()))
    mutated = graph.with_node(new_node)
    note = (
        f"swapped {label} {chosen.arg!r} of {victim.id!r} to {bad_value!r} "
        f"(violates {chosen.op.value} {chosen.value!r})"
    )
    return mutated, defect, note


def _violating_value(op: Op, value):
    """A concrete value that makes ``x op value`` true (for a ``Never`` rule)."""
    if op is Op.GT:
        return value + 1 if isinstance(value, (int, float)) else value
    if op is Op.GE:
        return value
    if op is Op.LT:
        return value - 1 if isinstance(value, (int, float)) else value
    if op is Op.LE:
        return value
    if op in (Op.EQ, Op.REGEX):
        return value
    if op is Op.NE:
        # forbidden: x != value  =>  pick anything other than value
        return "__mutant__" if value != "__mutant__" else "__other__"
    if op is Op.IN:
        # forbidden: x in value  => pick a member
        try:
            return next(iter(value))
        except TypeError:
            return value
    if op is Op.NIN:
        # forbidden: x not in value => pick something outside the allow-set
        return "__not_in_allowlist__"
    return value


def _mut_bypass_exit(graph, policy, rng):
    """Add a control edge that bypasses a required commit/preview boundary.

    Inverse of edit (7). Breaks a ``RequireBefore(gate, guarded)`` rule by
    adding a *may* edge from the gate's predecessor straight to the guarded
    node, creating a path where the effect commits without the transactional
    boundary. The analyzer reports this ``UNKNOWN`` (a may-only bypass path).
    """
    rb = _first(
        _leaf_policies(policy),
        lambda p: isinstance(p, RequireBefore),
        "RequireBefore(...) rule",
    )
    gate_atom = rb.required  # type: ignore[attr-defined]
    guarded_atom = rb.guarded  # type: ignore[attr-defined]
    gate = _first(
        graph.nodes,
        lambda n: gate_atom.abstract_eval(n)[0],
        "gate/commit node",
    )
    guarded = _first(
        graph.nodes,
        lambda n: guarded_atom.abstract_eval(n)[0],
        "guarded effect node",
    )
    preds = [e.source for e in graph.edges if e.target == gate.id]
    if not preds:
        raise MutationError(f"gate node {gate.id!r} has no predecessor to bypass from")
    src = preds[0]
    bypass = ModalEdge(
        source=src,
        target=guarded.id,
        modality=Modality.MAY,
        control=ControlKind.CONDITIONAL,
        framework_rule="mutation:bypass_exit",
        provenance=_exact(),
    )
    mutated = replace(graph, edges=graph.edges + (bypass,))
    note = (
        f"added bypass edge {src!r} -> {guarded.id!r}, skipping commit gate "
        f"{gate.id!r}"
    )
    return mutated, "commit_boundary_bypass", note


def _mut_escalate_capability(graph, policy, rng):
    """Grant a node a forbidden capability.

    Inverse of edit (3). Breaks a ``Never(Capability(x))`` rule by adding the
    forbidden capability ``x`` to an effectful node's capability set.
    """
    forbidden = None
    for pr in _all_preds(policy):
        if isinstance(pr, Capability):
            forbidden = pr.name
            break
    if forbidden is None:
        raise MutationError("policy has no Capability(...) atom to escalate")
    victim = _first(
        graph.nodes,
        lambda n: n.effect not in (EffectKind.NONE,) and n.id != graph.entry_id,
        "effectful node",
    )
    caps = [c for c in victim.capability.split(",") if c]
    if forbidden not in caps:
        caps.append(forbidden)
    new_node = replace(victim, capability=",".join(sorted(caps)))
    mutated = graph.with_node(new_node)
    note = f"escalated capability of {victim.id!r}: granted {forbidden!r}"
    return mutated, "capability_escalation", note


def _mut_drop_auth_precondition(graph, policy, rng):
    """Strip the authority a forbidden-without-authorization rule requires.

    Inverse of edit (5). Breaks a ``Never(effect AND NOT Authority(a))`` rule by
    clearing the ``authority`` field of the effect node so the effect executes
    without the required authorization.
    """
    required_auth = None
    for pr in _all_preds(policy):
        # look for Authority inside a negation guarding an effect
        if pr.__class__.__name__ == "Authority":
            required_auth = pr.name  # type: ignore[attr-defined]
            break
    victim = _first(
        graph.nodes,
        lambda n: n.authority != "" and n.effect not in (EffectKind.NONE,),
        "authorized effect node",
    )
    new_node = replace(victim, authority="", tool_schema=None)
    mutated = graph.with_node(new_node)
    note = (
        f"dropped authorization precondition of {victim.id!r} "
        f"(cleared authority {victim.authority!r}"
        + (f", required {required_auth!r}" if required_auth else "")
        + ")"
    )
    return mutated, "missing_authorization", note


_DISPATCH = {
    "drop_approval_gate": _mut_drop_approval_gate,
    "widen_tool_binding": _mut_widen_tool_binding,
    "remove_sanitizer": _mut_remove_sanitizer,
    "unbound_retry": _mut_unbound_retry,
    "swap_recipient": _mut_swap_recipient,
    "swap_argument": _mut_swap_argument,
    "bypass_exit": _mut_bypass_exit,
    "escalate_capability": _mut_escalate_capability,
    "drop_auth_precondition": _mut_drop_auth_precondition,
}

# The declared defect category each operator induces (for documentation / tests).
DEFECT_CATEGORIES: dict[str, str] = {
    "drop_approval_gate": "missing_approval_gate",
    "widen_tool_binding": "over_broad_tool_binding",
    "remove_sanitizer": "missing_sanitizer",
    "unbound_retry": "unbounded_retry",
    "swap_recipient": "illegal_recipient",
    "swap_argument": "illegal_argument_value",
    "bypass_exit": "commit_boundary_bypass",
    "escalate_capability": "capability_escalation",
    "drop_auth_precondition": "missing_authorization",
}
