"""CEGAR loop behaviour (Paper 2, plan §7, §11; Theorem 5).

Covers: refinement removes a spurious may-candidate (no false UNSAFE); a
feasible may-candidate is upgraded to ``UNSAFE`` with a concrete witness the
independent oracle confirms; and the refinement budget yields ``UNKNOWN`` (never
``SAFE``) on timeout.
"""

from __future__ import annotations

from agentproof.cegar import cegar, oracle
from agentproof.cegar.cegar import analyze
from agentproof.cegar.ir import (
    AbstractValue,
    EffectKind,
    EffectNode,
    MayMustGraph,
    ModalEdge,
    Modality,
    Provenance,
    Verdict,
)
from agentproof.cegar.policy import ArgConstraint, Never, Op, Tool
from agentproof.cegar.product import check

_EXACT = Provenance("ast_explicit", "exact", "f:1:1")


def _node(nid, *, effect=EffectKind.NONE, tool="", args=(), sp=()):
    return EffectNode(
        id=nid, effect=effect, tool=tool, abstract_args=args, state_predicates=sp,
        provenance=_EXACT, modeling_confidence="exact",
    )


def _e(u, v, modality=Modality.MUST, guard=""):
    return ModalEdge(u, v, modality=modality, guard=guard, provenance=_EXACT)


# ---------------------------------------------------------------------------
# Feasible candidate -> UNSAFE with an oracle-confirmed concrete witness
# ---------------------------------------------------------------------------

def test_feasible_candidate_upgraded_to_unsafe():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry", sp=("kind:entry",)),
               _node("call", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                     args=(("amount", AbstractValue.top()),), sp=("kind:tool",)),
               _node("exit", sp=("kind:exit",))),
        edges=(_e("entry", "call"), _e("call", "exit")),
        entry_id="entry", exit_ids=("exit",),
    )
    pol = Never(ArgConstraint("wire_transfer", "amount", Op.GT, 10000), rule_id="amount_cap")
    # The product alone can only say UNKNOWN (may-violation candidate).
    assert check(g, pol).verdict is Verdict.UNKNOWN
    r = analyze(g, pol)
    assert r.verdict is Verdict.UNSAFE
    assert r.concrete_witness is not None
    # The witness must ACTUALLY violate per the independent oracle.
    assert not oracle.satisfies(pol, r.concrete_witness)
    amount = r.concrete_witness[1].arg("amount")
    assert amount is not None and amount > 10000
    assert r.iterations == 0 and not r.timed_out


# ---------------------------------------------------------------------------
# Spurious may-candidate is refined away (no false UNSAFE)
# ---------------------------------------------------------------------------

def test_spurious_branch_refined_away_to_safe():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry", sp=("kind:entry",)), _node("branch"),
               _node("badcall", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                     sp=("kind:tool",)),
               _node("exit", sp=("kind:exit",))),
        edges=(_e("entry", "branch"),
               _e("branch", "badcall", Modality.MAY, guard="false"),
               _e("branch", "exit", Modality.MAY),
               _e("badcall", "exit", Modality.MAY)),
        entry_id="entry", exit_ids=("exit",),
    )
    pol = Never(Tool("wire_transfer"), rule_id="no_wire")
    assert check(g, pol).verdict is Verdict.UNKNOWN
    r = analyze(g, pol)
    # The dead branch (guard=false) is proven spurious and removed; the fully
    # exact remainder then clears to SAFE. Never a false UNSAFE.
    assert r.verdict is Verdict.SAFE
    assert r.verdict is not Verdict.UNSAFE
    assert r.iterations >= 1
    assert r.refinements


def test_spurious_refinement_never_reports_unsafe():
    """Even if refinement cannot fully clear it, it must not fabricate UNSAFE."""
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry", sp=("kind:entry",)), _node("branch"),
               _node("badcall", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                     sp=("kind:tool",)),
               _node("exit", sp=("kind:exit",))),
        edges=(_e("entry", "branch"),
               _e("branch", "badcall", Modality.MAY, guard="false"),
               _e("branch", "exit", Modality.MAY),
               _e("badcall", "exit", Modality.MAY)),
        entry_id="entry", exit_ids=("exit",),
    )
    r = analyze(g, Never(Tool("wire_transfer")))
    assert r.verdict is not Verdict.UNSAFE


# ---------------------------------------------------------------------------
# Already-SAFE graph short-circuits with no refinement
# ---------------------------------------------------------------------------

def test_clean_graph_safe_zero_refinements():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry", sp=("kind:entry",)),
               _node("send", effect=EffectKind.COMMUNICATE, tool="send_email",
                     sp=("kind:tool",)),
               _node("exit", sp=("kind:exit",))),
        edges=(_e("entry", "send"), _e("send", "exit")),
        entry_id="entry", exit_ids=("exit",),
    )
    r = analyze(g, Never(Tool("wire_transfer"), rule_id="no_wire"))
    assert r.verdict is Verdict.SAFE
    assert r.iterations == 0 and r.refinements == [] and not r.timed_out


# ---------------------------------------------------------------------------
# Timeout -> UNKNOWN, never SAFE
# ---------------------------------------------------------------------------

def test_timeout_returns_unknown_never_safe():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry", sp=("kind:entry",)), _node("branch"),
               _node("badcall", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                     sp=("kind:tool",)),
               _node("exit", sp=("kind:exit",))),
        edges=(_e("entry", "branch"),
               _e("branch", "badcall", Modality.MAY, guard="false"),
               _e("branch", "exit", Modality.MAY),
               _e("badcall", "exit", Modality.MAY)),
        entry_id="entry", exit_ids=("exit",),
    )
    r = analyze(g, Never(Tool("wire_transfer")), max_refinements=0)
    assert r.verdict is Verdict.UNKNOWN
    assert r.verdict is not Verdict.SAFE
    assert r.timed_out is True
    assert r.iterations == 0


# ---------------------------------------------------------------------------
# Unsupported region stays UNKNOWN (never refined into SAFE/UNSAFE)
# ---------------------------------------------------------------------------

def test_unsupported_region_stays_unknown():
    from agentproof.cegar.ir import UnsupportedFact, UnsupportedKind

    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry", sp=("kind:entry",)),
               EffectNode(id="sub", effect=EffectKind.UNKNOWN, provenance=_EXACT,
                          modeling_confidence="exact", state_predicates=("kind:subgraph",),
                          unsupported=(UnsupportedFact(UnsupportedKind.NESTED_AGENT, "sub"),)),
               _node("exit", sp=("kind:exit",))),
        edges=(_e("entry", "sub"), _e("sub", "exit")),
        entry_id="entry", exit_ids=("exit",),
    )
    r = analyze(g, Never(Tool("danger")))
    assert r.verdict is Verdict.UNKNOWN


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_analyze_is_deterministic():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry", sp=("kind:entry",)),
               _node("call", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                     args=(("amount", AbstractValue.top()),), sp=("kind:tool",)),
               _node("exit", sp=("kind:exit",))),
        edges=(_e("entry", "call"), _e("call", "exit")),
        entry_id="entry", exit_ids=("exit",),
    )
    pol = Never(ArgConstraint("wire_transfer", "amount", Op.GT, 10000))
    first = analyze(g, pol)
    second = analyze(g, pol)
    assert first.verdict is second.verdict
    assert first.to_dict() == second.to_dict()
