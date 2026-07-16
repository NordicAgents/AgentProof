"""Differential + end-to-end coverage for the independent certificate checker.

These tests were lifted out of ``checker.py``'s inline ``__main__`` harness so
the checker module stays lean (its runtime job is small and auditable) while the
valuable coverage runs in CI:

* :func:`test_checker_semantics_differential` cross-checks the checker's monitor
  automaton (``_step``/``_accepting``, a *second* implementation of the shared
  finite-trace semantics) against an independent denotational reference
  (``_ref_eval``, a *third* implementation) over every atom-valuation sequence up
  to length 4 for a battery of policies covering all operators. Any deviation of
  the checker's monitor from the authoritative semantics is caught here.
* :func:`test_checker_operator_end_to_end` drives the full
  :func:`check_certificate` path over RequireBefore / Bounded / LeadsTo / All,
  asserting compliant graphs are accepted and each targeted violation rejected.
"""

from __future__ import annotations

import itertools

from agentproof.cegar.certificate import build_certificate
from agentproof.cegar.checker import (
    _accepting,
    _eval_pred,
    _initial_state,
    _step,
    check_certificate,
)
from agentproof.cegar.ir import (
    EffectKind,
    EffectNode,
    MayMustGraph,
    Modality,
    ModalEdge,
    Provenance,
    Verdict,
)
from agentproof.cegar.policy import (
    All,
    Bounded,
    Forbid,
    LeadsTo,
    Never,
    PredAnd,
    PredNot,
    PredOr,
    Policy,
    RequireBefore,
    Tag,
)


# ---------------------------------------------------------------------------
# Independent denotational reference for the shared finite-trace semantics
# ---------------------------------------------------------------------------

def _ref_eval(policy: Policy, seq: list[dict[str, bool]]) -> tuple[int | None, bool]:
    """A third, denotational implementation of the authoritative prose.

    Returns ``(first_bad_index or None, unfulfilled_at_end)``; ``unfulfilled`` is
    only meaningful when there is no bad prefix. Predicate truth reuses
    ``_eval_pred`` so this isolates the *temporal-operator* logic — the part
    implemented independently in the checker's monitor.
    """
    ev = _eval_pred
    if isinstance(policy, Never):
        for i, val in enumerate(seq):
            if ev(policy.pred, val):
                return (i, False)
        return (None, False)

    if isinstance(policy, RequireBefore):
        seen = False
        for i, val in enumerate(seq):
            if policy.strict:
                if ev(policy.guarded, val) and not seen:
                    return (i, False)
                if ev(policy.required, val):
                    seen = True
            else:
                if ev(policy.required, val):
                    seen = True
                if ev(policy.guarded, val) and not seen:
                    return (i, False)
        return (None, False)

    if isinstance(policy, Forbid):
        steps = policy.steps
        idx = 0
        for i, val in enumerate(seq):
            if not policy.contiguous:
                if idx < len(steps) and ev(steps[idx], val):
                    idx += 1
            else:
                if ev(steps[idx], val):
                    idx += 1
                else:
                    idx = 1 if ev(steps[0], val) else 0
            if idx == len(steps):
                return (i, False)
        return (None, False)

    if isinstance(policy, Bounded):
        count = 0
        for i, val in enumerate(seq):
            if ev(policy.pred, val):
                count += 1
            if count > policy.k:
                return (i, False)
        return (None, False)

    if isinstance(policy, LeadsTo):
        pending = False
        for val in seq:
            if ev(policy.trigger, val):
                pending = True
            if ev(policy.response, val):
                pending = False
        return (None, pending)

    if isinstance(policy, All):
        first_bad: int | None = None
        unfulfilled = False
        for sub in policy.policies:
            b, u = _ref_eval(sub, seq)
            if b is not None:
                first_bad = b if first_bad is None else min(first_bad, b)
            unfulfilled = unfulfilled or u
        if first_bad is not None:
            return (first_bad, False)
        return (None, unfulfilled)

    raise ValueError(f"unsupported policy kind: {type(policy).__name__}")


def _mon_eval(policy: Policy, seq: list[dict[str, bool]]) -> tuple[int | None, bool]:
    """Drive the checker's monitor automaton over a valuation sequence."""
    state = _initial_state(policy)
    for i, val in enumerate(seq):
        state, bad = _step(policy, state, val)
        if bad:
            return (i, False)
    return (None, not _accepting(policy, state))


def test_checker_semantics_differential() -> None:
    a, b, c = Tag("a"), Tag("b"), Tag("c")
    keys = ("tag:a", "tag:b", "tag:c")

    policies: list[Policy] = [
        Never(a),
        Never(PredNot(a)),
        Never(PredAnd(a, b)),
        Never(PredOr(a, b)),
        RequireBefore(a, b, strict=True),
        RequireBefore(a, b, strict=False),
        RequireBefore(PredOr(a, c), b, strict=True),
        Forbid((a,), contiguous=False),
        Forbid((a, b), contiguous=False),
        Forbid((a, b, c), contiguous=False),
        Forbid((a, b), contiguous=True),
        Forbid((a, b, c), contiguous=True),
        Forbid((a, a), contiguous=True),
        Bounded(a, 0),
        Bounded(a, 1),
        Bounded(a, 2),
        LeadsTo(a, b),
        LeadsTo(a, PredOr(b, c)),
        All((Never(c), Bounded(a, 1), LeadsTo(a, b))),
        All((RequireBefore(a, b, strict=True), Forbid((b, c), contiguous=False))),
    ]

    symbols = [
        dict(zip(keys, bits))
        for bits in itertools.product((False, True), repeat=len(keys))
    ]
    checked = 0
    for policy in policies:
        for length in range(0, 5):
            for seq in itertools.product(symbols, repeat=length):
                seq_list = list(seq)
                ref = _ref_eval(policy, seq_list)
                mon = _mon_eval(policy, seq_list)
                assert ref == mon, (
                    f"checker monitor disagrees with reference semantics for "
                    f"{policy.__class__.__name__}: seq={seq_list} ref={ref} mon={mon}"
                )
                checked += 1
    # Guard the coverage: 20 policies x sum_{L=0..4} 8**L sequences.
    assert checked == 20 * sum(8 ** length for length in range(0, 5))


# ---------------------------------------------------------------------------
# End-to-end operator coverage through the full check_certificate path
# ---------------------------------------------------------------------------

_EXACT = Provenance(origin="ast_explicit", confidence="exact", source_span="f:1:2")


def _linear_graph(event_nodes) -> MayMustGraph:
    """Straight-line MayMustGraph entry -> n0 -> ... -> exit, all exact."""
    nodes = [
        EffectNode(id="entry", effect=EffectKind.NONE, provenance=_EXACT,
                   modeling_confidence="exact", state_predicates=("kind:entry",)),
    ]
    for nid, kwargs in event_nodes:
        nodes.append(EffectNode(id=nid, provenance=_EXACT, modeling_confidence="exact", **kwargs))
    nodes.append(EffectNode(id="exit", effect=EffectKind.NONE, provenance=_EXACT,
                            modeling_confidence="exact", state_predicates=("kind:exit",)))

    order = ["entry"] + [nid for nid, _ in event_nodes] + ["exit"]
    edges = tuple(
        ModalEdge(source=order[i], target=order[i + 1], modality=Modality.MUST, provenance=_EXACT)
        for i in range(len(order) - 1)
    )
    return MayMustGraph(name="lin", framework="none", nodes=tuple(nodes),
                        edges=edges, entry_id="entry", exit_ids=("exit",))


def _tag_node(nid: str, tag: str):
    # Tag(name).abstract_eval matches the raw name in state_predicates.
    return (nid, dict(effect=EffectKind.NONE, state_predicates=("kind:tool", tag)))


class _Safe:
    verdict = Verdict.SAFE


def test_checker_operator_end_to_end() -> None:
    # RequireBefore: approval must precede the guarded action.
    req = RequireBefore(Tag("appr"), Tag("danger"), strict=True, rule_id="req")
    ok = _linear_graph([_tag_node("approve", "appr"), _tag_node("act", "danger")])
    bad = _linear_graph([_tag_node("act", "danger")])
    assert check_certificate(build_certificate(ok, req, _Safe())).accepted
    r = check_certificate(build_certificate(bad, req, _Safe()))
    assert not r.accepted and any("BAD PREFIX" in x for x in r.reasons), r

    # Bounded: "hit" at most twice.
    bnd = Bounded(Tag("hit"), 2, rule_id="bnd")
    two = _linear_graph([_tag_node("h1", "hit"), _tag_node("h2", "hit")])
    three = _linear_graph([_tag_node("h1", "hit"), _tag_node("h2", "hit"), _tag_node("h3", "hit")])
    assert check_certificate(build_certificate(two, bnd, _Safe())).accepted
    r = check_certificate(build_certificate(three, bnd, _Safe()))
    assert not r.accepted and any("BAD PREFIX" in x for x in r.reasons), r

    # LeadsTo (termination-time): trigger must be answered.
    lt = LeadsTo(Tag("req"), Tag("res"), rule_id="lt")
    answered = _linear_graph([_tag_node("t", "req"), _tag_node("r", "res")])
    unanswered = _linear_graph([_tag_node("t", "req")])
    assert check_certificate(build_certificate(answered, lt, _Safe())).accepted
    r = check_certificate(build_certificate(unanswered, lt, _Safe()))
    assert not r.accepted and any("UNFULFILLED" in x for x in r.reasons), r

    # All: conjunction of a Never and the LeadsTo.
    conj = All((Never(Tag("forbidden")), lt), rule_id="all")
    assert check_certificate(build_certificate(answered, conj, _Safe())).accepted
    r = check_certificate(build_certificate(unanswered, conj, _Safe()))
    assert not r.accepted, r
