"""Tri-valued product-checker behaviour (Paper 2, plan §7, §11).

Asserts the three verdict regimes precisely:

* ``SAFE`` only on a certifiable region — a single non-exact or unsupported
  node forces ``UNKNOWN`` (never a silent ``SAFE``);
* definite ``UNSAFE`` on a must-path forced violation; and
* ``UNKNOWN`` on a may-only candidate (a possible violation no MUST trace
  forces).
"""

from __future__ import annotations

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
    Never,
    RequireBefore,
    Tool,
)
from agentproof.cegar.product import check, check_all

_EXACT = Provenance("ast_explicit", "exact", "f:1:1")
_MAY = Provenance("ast_inferred", "may", "f:2:2")


def _node(nid, *, effect=EffectKind.NONE, tool="", prov=_EXACT, unsupported=(),
          capability="", sp=()):
    return EffectNode(
        id=nid, effect=effect, tool=tool, provenance=prov,
        modeling_confidence=prov.confidence, unsupported=unsupported,
        capability=capability, state_predicates=sp,
    )


def _line(*node_ids, modality=Modality.MUST, prov=_EXACT):
    return tuple(
        ModalEdge(node_ids[i], node_ids[i + 1], modality=modality, provenance=prov)
        for i in range(len(node_ids) - 1)
    )


# ---------------------------------------------------------------------------
# SAFE only on certifiable regions
# ---------------------------------------------------------------------------

def test_safe_on_clean_exact_region():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry"), _node("send", effect=EffectKind.COMMUNICATE, tool="send_email"),
               _node("exit")),
        edges=_line("entry", "send", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    r = check(g, Never(Tool("wire_transfer"), rule_id="no_wire"))
    assert r.verdict is Verdict.SAFE
    assert r.certified is True
    assert r.witness is None


def test_non_exact_node_forces_unknown_not_safe():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry"),
               _node("send", effect=EffectKind.COMMUNICATE, tool="send_email", prov=_MAY),
               _node("exit")),
        edges=_line("entry", "send", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    r = check(g, Never(Tool("wire_transfer"), rule_id="no_wire"))
    assert r.verdict is Verdict.UNKNOWN
    assert r.verdict is not Verdict.SAFE
    assert r.unknown_reason == "uncertified_extraction"
    assert r.certified is False


def test_unsupported_fact_forces_unknown_not_safe():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry"),
               _node("send", effect=EffectKind.COMMUNICATE, tool="send_email",
                     unsupported=(UnsupportedFact(UnsupportedKind.REFLECTION, "getattr"),)),
               _node("exit")),
        edges=_line("entry", "send", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    r = check(g, Never(Tool("wire_transfer"), rule_id="no_wire"))
    assert r.verdict is Verdict.UNKNOWN
    assert r.unknown_reason == "unsupported_region"
    assert r.unsupported_facts


def test_graph_level_unsupported_forces_unknown():
    from dataclasses import replace

    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry"), _node("send", effect=EffectKind.COMMUNICATE, tool="send_email"),
               _node("exit")),
        edges=_line("entry", "send", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    g = replace(g, unsupported=(UnsupportedFact(UnsupportedKind.DYNAMIC_LOAD, "importlib"),))
    r = check(g, Never(Tool("wire_transfer"), rule_id="no_wire"))
    assert r.verdict is Verdict.UNKNOWN
    assert r.unknown_reason == "unsupported_region"


def test_assume_trace_conservative_allows_safe_on_weak_region():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry"),
               _node("send", effect=EffectKind.COMMUNICATE, tool="send_email", prov=_MAY),
               _node("exit")),
        edges=_line("entry", "send", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    r = check(g, Never(Tool("wire_transfer")), assume_trace_conservative=True)
    assert r.verdict is Verdict.SAFE


# ---------------------------------------------------------------------------
# Definite UNSAFE on must-paths
# ---------------------------------------------------------------------------

def test_unsafe_on_must_path_forbidden_tool():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry"),
               _node("call", effect=EffectKind.FINANCIAL, tool="wire_transfer"),
               _node("exit")),
        edges=_line("entry", "call", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    r = check(g, Never(Tool("wire_transfer"), rule_id="no_wire"))
    assert r.verdict is Verdict.UNSAFE
    assert r.violation_kind == "bad_prefix"
    assert r.witness is not None
    assert r.witness.modality == "must"
    assert r.witness.product_path == ["entry", "call"]


def test_unsafe_requirebefore_missing_approval_on_must_path():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry"),
               _node("pay", effect=EffectKind.FINANCIAL, tool="wire_transfer"),
               _node("exit")),
        edges=_line("entry", "pay", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    pol = RequireBefore(Approval(), Effect(EffectKind.FINANCIAL), strict=True,
                        rule_id="approve_before_pay")
    r = check(g, pol)
    assert r.verdict is Verdict.UNSAFE
    assert r.violation_kind == "bad_prefix"


def test_unsafe_bounded_quota_on_must_path():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry"), _node("r1", tool="retry"), _node("r2", tool="retry"),
               _node("exit")),
        edges=_line("entry", "r1", "r2", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    r = check(g, Bounded(Tool("retry"), 1, rule_id="max_retry"))
    assert r.verdict is Verdict.UNSAFE
    # within the bound the same graph is SAFE
    assert check(g, Bounded(Tool("retry"), 2)).verdict is Verdict.SAFE


# ---------------------------------------------------------------------------
# UNKNOWN on may-only candidates
# ---------------------------------------------------------------------------

def test_unknown_on_may_only_branch_candidate():
    """A forbidden tool reachable only via a MAY branch -> UNKNOWN candidate."""
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry"), _node("branch"),
               _node("bad", effect=EffectKind.FINANCIAL, tool="wire_transfer"),
               _node("exit")),
        edges=(
            ModalEdge("entry", "branch", modality=Modality.MUST, provenance=_EXACT),
            ModalEdge("branch", "bad", modality=Modality.MAY, provenance=_EXACT),
            ModalEdge("branch", "exit", modality=Modality.MAY, provenance=_EXACT),
            ModalEdge("bad", "exit", modality=Modality.MAY, provenance=_EXACT),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    r = check(g, Never(Tool("wire_transfer"), rule_id="no_wire"))
    assert r.verdict is Verdict.UNKNOWN
    assert r.unknown_reason == "may_violation_candidate"
    assert r.violation_kind == "bad_prefix"
    assert r.witness is not None and r.witness.modality == "may"


def test_unknown_leadsto_may_branch_skips_response():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry"), _node("open", tool="open"), _node("close", tool="close"),
               _node("exit1"), _node("exit2")),
        edges=(
            ModalEdge("entry", "open", modality=Modality.MUST, provenance=_EXACT),
            ModalEdge("open", "exit1", modality=Modality.MAY, provenance=_EXACT),
            ModalEdge("open", "close", modality=Modality.MAY, provenance=_EXACT),
            ModalEdge("close", "exit2", modality=Modality.MAY, provenance=_EXACT),
        ),
        entry_id="entry", exit_ids=("exit1", "exit2"),
    )
    from agentproof.cegar.policy import LeadsTo

    r = check(g, LeadsTo(Tool("open"), Tool("close"), rule_id="close_it"))
    assert r.verdict is Verdict.UNKNOWN
    assert r.violation_kind == "unfulfilled"
    assert r.unknown_reason == "may_violation_candidate"


# ---------------------------------------------------------------------------
# check_all evaluates each policy independently
# ---------------------------------------------------------------------------

def test_check_all_independent_verdicts():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry"), _node("retry", tool="retry"), _node("exit")),
        edges=_line("entry", "retry", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    results = check_all(g, [Never(Tool("wire_transfer")), Bounded(Tool("retry"), 0)])
    assert [r.verdict for r in results] == [Verdict.SAFE, Verdict.UNSAFE]


def test_result_serializes_for_every_verdict():
    import json

    safe = MayMustGraph(
        "g", "t",
        nodes=(_node("entry"), _node("send", tool="send_email"), _node("exit")),
        edges=_line("entry", "send", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    unsafe = MayMustGraph(
        "g", "t",
        nodes=(_node("entry"), _node("call", tool="wire_transfer"), _node("exit")),
        edges=_line("entry", "call", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    for g in (safe, unsafe):
        r = check(g, Never(Tool("wire_transfer")))
        json.dumps(r.to_dict())  # must be JSON-serializable
