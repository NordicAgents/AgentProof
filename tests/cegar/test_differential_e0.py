"""The E0 differential test (Paper 2, plan §7, E0 — the headline).

Enumerates ALL traces up to length 4 over a small concrete event alphabet, for
a battery of policies covering every operator, and asserts THREE independent
implementations of the shared finite-trace semantics agree with zero mismatches:

1. an **independent reference** evaluator written fresh in this file
   (:func:`_ref_evaluate`), transcribed from the authoritative prose in the
   plan / :mod:`agentproof.cegar.oracle` docstring;
2. the production **oracle** (:func:`agentproof.cegar.oracle.evaluate`) — status
   AND earliest bad-index must match the reference; and
3. the production **product checker** (:func:`agentproof.cegar.product.check`)
   run on the single-path may/must graph built from each concrete trace — its
   tri-valued verdict must agree with the reference on *violation* (SAFE iff the
   reference says satisfied, UNSAFE otherwise).

Any behavioural divergence between the oracle's denotational semantics and the
product checker's monitor automaton is a real bug in one of them; this test is
the cross-check that makes that redundancy pay off.
"""

from __future__ import annotations

import itertools

import pytest

from agentproof.cegar import oracle, product
from agentproof.cegar.ir import (
    EffectEvent,
    EffectKind,
    EffectNode,
    MayMustGraph,
    ModalEdge,
    Modality,
    Provenance,
    Verdict,
)
from agentproof.cegar.policy import (
    Action,
    All,
    ArgConstraint,
    Approval,
    Bounded,
    Effect,
    Forbid,
    LeadsTo,
    Never,
    Op,
    Policy,
    PredAnd,
    PredNot,
    PredOr,
    Predicate,
    RequireBefore,
    Tag,
    Tool,
)

# Status constants (mirror oracle's, redeclared so this file is self-contained).
SATISFIED = "satisfied"
BAD_PREFIX = "bad_prefix"
UNFULFILLED = "unfulfilled"

_EXACT = Provenance(origin="ast_explicit", confidence="exact", source_span="e0.py:1:1")


# ---------------------------------------------------------------------------
# The concrete event alphabet
# ---------------------------------------------------------------------------

def _alphabet() -> list[EffectEvent]:
    """A small, deterministic alphabet exercising every predicate family."""
    return [
        EffectEvent(node_id="_"),  # neutral: satisfies no atom
        EffectEvent(node_id="read", tool_name="read", effect=EffectKind.READ,
                    action_type="tool", tags=("a",)),
        EffectEvent(node_id="send", tool_name="send", effect=EffectKind.COMMUNICATE,
                    action_type="tool", tags=("b",)),
        EffectEvent(node_id="pay_big", tool_name="wire", effect=EffectKind.FINANCIAL,
                    action_type="tool", args=(("amount", 20000),)),
        EffectEvent(node_id="approve", action_type="human", tags=("approval",)),
        # a single event satisfying BOTH approval and a financial effect (probes
        # strict vs. non-strict RequireBefore)
        EffectEvent(node_id="approve_pay", tool_name="wire", effect=EffectKind.FINANCIAL,
                    action_type="human", tags=("approval",), args=(("amount", 20000),)),
        EffectEvent(node_id="delete", effect=EffectKind.DELETE),
    ]


# ---------------------------------------------------------------------------
# The policy battery (>= 15 policies covering every operator)
# ---------------------------------------------------------------------------

def _policies() -> list[Policy]:
    return [
        Never(Effect(EffectKind.DELETE), rule_id="never_delete"),
        Never(Tool("wire"), rule_id="never_wire"),
        Never(ArgConstraint("wire", "amount", Op.GT, 10000), rule_id="never_big_amount"),
        Never(PredNot(Tool("read")), rule_id="never_not_read"),
        Never(PredAnd(Tool("wire"), Effect(EffectKind.FINANCIAL)), rule_id="never_wire_fin"),
        Never(PredOr(Tag("a"), Tag("b")), rule_id="never_a_or_b"),
        RequireBefore(Approval(), Effect(EffectKind.FINANCIAL), strict=True, rule_id="rb_strict"),
        RequireBefore(Approval(), Effect(EffectKind.FINANCIAL), strict=False, rule_id="rb_loose"),
        RequireBefore(Approval(), Tool("wire"), strict=True, rule_id="rb_tool"),
        Forbid((Tool("read"), Tool("send")), contiguous=False, rule_id="forbid_scatter"),
        Forbid((Tag("a"), Tag("b")), contiguous=True, rule_id="forbid_contig"),
        Forbid((Tag("a"), Tag("a")), contiguous=True, rule_id="forbid_aa"),
        Bounded(Tool("send"), 0, rule_id="bounded0"),
        Bounded(Tool("send"), 1, rule_id="bounded1"),
        Bounded(Effect(EffectKind.FINANCIAL), 2, rule_id="bounded_fin2"),
        LeadsTo(Tool("read"), Tool("send"), rule_id="leadsto"),
        LeadsTo(Effect(EffectKind.FINANCIAL), Approval(), rule_id="leadsto_fin"),
        All((Never(Effect(EffectKind.DELETE)), Bounded(Tool("send"), 1)), rule_id="all_a"),
        All((RequireBefore(Approval(), Effect(EffectKind.FINANCIAL)),
             Forbid((Tool("read"), Tool("send")))), rule_id="all_b"),
        All((LeadsTo(Tool("read"), Tool("send")),
             Never(Effect(EffectKind.DELETE))), rule_id="all_c"),
    ]


# ---------------------------------------------------------------------------
# The INDEPENDENT reference (fresh transcription of the shared semantics)
# ---------------------------------------------------------------------------

def _ref_evaluate(policy: Policy, trace: tuple[EffectEvent, ...]) -> tuple[str, int | None]:
    """Independent reference: returns ``(status, bad_index)``.

    A dead-simple, second implementation of the authoritative prose — it does
    NOT call the oracle. ``bad_index`` is the earliest violating index for a
    bad prefix, else ``None``.
    """
    if isinstance(policy, Never):
        for i, e in enumerate(trace):
            if policy.pred.eval(e):
                return (BAD_PREFIX, i)
        return (SATISFIED, None)

    if isinstance(policy, RequireBefore):
        seen = False
        for i, e in enumerate(trace):
            if policy.strict:
                if policy.guarded.eval(e) and not seen:
                    return (BAD_PREFIX, i)
                if policy.required.eval(e):
                    seen = True
            else:
                if policy.required.eval(e):
                    seen = True
                if policy.guarded.eval(e) and not seen:
                    return (BAD_PREFIX, i)
        return (SATISFIED, None)

    if isinstance(policy, Forbid):
        steps = policy.steps
        if not steps:
            return (BAD_PREFIX, 0) if trace else (SATISFIED, None)
        idx = 0
        for i, e in enumerate(trace):
            if policy.contiguous:
                if steps[idx].eval(e):
                    idx += 1
                else:
                    idx = 1 if steps[0].eval(e) else 0
            else:
                if idx < len(steps) and steps[idx].eval(e):
                    idx += 1
            if idx == len(steps):
                return (BAD_PREFIX, i)
        return (SATISFIED, None)

    if isinstance(policy, Bounded):
        count = 0
        for i, e in enumerate(trace):
            if policy.pred.eval(e):
                count += 1
            if count > policy.k:
                return (BAD_PREFIX, i)
        return (SATISFIED, None)

    if isinstance(policy, LeadsTo):
        pending = False
        for e in trace:
            if policy.trigger.eval(e):
                pending = True
            if policy.response.eval(e):
                pending = False
        return (UNFULFILLED, None) if pending else (SATISFIED, None)

    if isinstance(policy, All):
        best_status = SATISFIED
        best_idx: int | None = None
        severity = {BAD_PREFIX: 0, UNFULFILLED: 1, SATISFIED: 2}
        best_key = (severity[SATISFIED], float("inf"), 0)
        for pos, sub in enumerate(policy.policies):
            status, idx = _ref_evaluate(sub, trace)
            key = (severity[status], idx if idx is not None else float("inf"), pos)
            if key < best_key:
                best_key = key
                best_status, best_idx = status, idx
        return (best_status, best_idx)

    raise TypeError(f"reference cannot evaluate {type(policy).__name__}")


# ---------------------------------------------------------------------------
# Build a single-path may/must graph reproducing a concrete trace
# ---------------------------------------------------------------------------

def _node_for_event(nid: str, e: EffectEvent) -> EffectNode:
    """An exact node whose *forced* (must) abstract evaluation reproduces ``e``.

    Every atom family used in the alphabet evaluates definitely (may == must) on
    this node, so the product's forced assignment equals the concrete truth of
    the event — making the single MUST path a faithful reproduction of the trace.
    """
    from agentproof.cegar.ir import AbstractValue

    sp: list[str] = []
    if e.action_type:
        sp.append(f"kind:{e.action_type}")
    sp.extend(e.tags)
    capability = e.capability
    if e.action_type == "human" and "human_pause" not in capability:
        capability = (capability + ",human_pause").strip(",")
    abstract_args = tuple((k, AbstractValue.const(v)) for k, v in e.args)
    return EffectNode(
        id=nid, effect=e.effect, tool=e.tool_name or "",
        authority=e.authority, identity=e.identity, capability=capability,
        in_labels=e.in_labels, out_labels=e.out_labels,
        abstract_args=abstract_args, state_predicates=tuple(sp),
        provenance=_EXACT, modeling_confidence="exact",
    )


def _linear_graph(trace: tuple[EffectEvent, ...]) -> MayMustGraph:
    """n0 -> n1 -> ... -> n_last, all MUST, all exact — one node per event.

    The path nodes are EXACTLY the trace events (no synthetic entry/exit): a
    neutral no-op node is *not* semantically transparent for negated predicates
    (``not Tool(x)`` is true on it), so the graph must reproduce the trace event
    for event. ``entry_id`` is the first event node and the last is the sole
    exit. The empty trace has no faithful single-node graph, so callers skip it
    (the reference declares every operator satisfied on the empty trace anyway).
    """
    assert trace, "empty trace has no event-only graph; caller must skip it"
    nodes = tuple(_node_for_event(f"n{i}", e) for i, e in enumerate(trace))
    edges = tuple(
        ModalEdge(f"n{i}", f"n{i + 1}", modality=Modality.MUST, provenance=_EXACT)
        for i in range(len(trace) - 1)
    )
    return MayMustGraph(name="e0", framework="test", nodes=nodes, edges=edges,
                        entry_id="n0", exit_ids=(f"n{len(trace) - 1}",))


def _all_traces(alphabet, max_len):
    for length in range(max_len + 1):
        for combo in itertools.product(alphabet, repeat=length):
            yield combo


# ---------------------------------------------------------------------------
# THE tests
# ---------------------------------------------------------------------------

def test_e0_oracle_matches_independent_reference():
    """Oracle status AND bad-index match the fresh reference over ALL traces<=4."""
    alphabet = _alphabet()
    policies = _policies()
    pairs = 0
    mismatches: list[str] = []
    for policy in policies:
        for trace in _all_traces(alphabet, 4):
            ref_status, ref_idx = _ref_evaluate(policy, trace)
            ov = oracle.evaluate(policy, trace)
            pairs += 1
            if ov.status != ref_status:
                mismatches.append(
                    f"status: {policy.__class__.__name__}/{ov.rule_id} "
                    f"ref={ref_status} oracle={ov.status} "
                    f"trace={[e.node_id for e in trace]}"
                )
            elif ref_status == BAD_PREFIX and ov.bad_index != ref_idx:
                mismatches.append(
                    f"index: {policy.__class__.__name__}/{ov.rule_id} "
                    f"ref={ref_idx} oracle={ov.bad_index} "
                    f"trace={[e.node_id for e in trace]}"
                )
    assert pairs >= 2000, f"expected thousands of pairs, got {pairs}"
    assert not mismatches, f"{len(mismatches)} oracle/reference mismatches:\n" + \
        "\n".join(mismatches[:20])


def test_e0_product_agrees_on_violation():
    """Product verdict on the single-path graph agrees with the reference.

    SAFE iff the reference says satisfied; UNSAFE otherwise (bad prefix or an
    unfulfilled obligation forced on the sole MUST trace). Never UNKNOWN — the
    path is fully exact and forced.
    """
    alphabet = _alphabet()
    policies = _policies()
    pairs = 0
    mismatches: list[str] = []
    for policy in policies:
        for trace in _all_traces(alphabet, 3):
            if not trace:
                continue  # empty trace has no event-only graph (see _linear_graph)
            ref_status, _ = _ref_evaluate(policy, trace)
            graph = _linear_graph(trace)
            result = product.check(graph, policy)
            pairs += 1
            expected_safe = ref_status == SATISFIED
            got_safe = result.verdict is Verdict.SAFE
            if result.verdict is Verdict.UNKNOWN:
                mismatches.append(
                    f"UNKNOWN: {policy.__class__.__name__}/{result.rule_id} "
                    f"reason={result.unknown_reason} "
                    f"trace={[e.node_id for e in trace]}"
                )
            elif expected_safe != got_safe:
                mismatches.append(
                    f"{policy.__class__.__name__}/{result.rule_id} "
                    f"ref={ref_status} product={result.verdict.value} "
                    f"trace={[e.node_id for e in trace]}"
                )
    assert pairs >= 2000, f"expected thousands of pairs, got {pairs}"
    assert not mismatches, f"{len(mismatches)} product/reference mismatches:\n" + \
        "\n".join(mismatches[:20])


def test_e0_product_violation_kind_matches_reference():
    """When the reference flags a violation, the product's kind matches it."""
    alphabet = _alphabet()
    for policy in _policies():
        for trace in _all_traces(alphabet, 3):
            if not trace:
                continue
            ref_status, _ = _ref_evaluate(policy, trace)
            if ref_status == SATISFIED:
                continue
            result = product.check(_linear_graph(trace), policy)
            assert result.verdict is Verdict.UNSAFE
            assert result.violation_kind == ref_status, (
                policy.__class__.__name__, [e.node_id for e in trace],
                ref_status, result.violation_kind,
            )
