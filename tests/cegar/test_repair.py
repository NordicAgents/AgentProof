"""Proof-carrying repair (Paper 2, plan §7, §11; Theorems 3 & 4).

Covers: each applicable edit operator actually applies; end-to-end repair of a
mutated seed turns UNSAFE into SAFE with a certificate the INDEPENDENT checker
accepts; relative minimality (the lowest-cost verified candidate wins); and no
false success — a tampered / unverified patch is rejected by the sole gate (the
checker).
"""

from __future__ import annotations

import pytest

from agentproof.cegar import certificate as certificate_mod
from agentproof.cegar import checker as checker_mod
from agentproof.cegar.cegar import analyze
from agentproof.cegar.checker import CheckResult, check_certificate
from agentproof.cegar.ir import (
    ControlKind,
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
    Effect,
    Never,
    RequireBefore,
    Tool,
)
from agentproof.cegar.repair import (
    AddAuthPrecondition,
    BoundLoop,
    GrammarProposer,
    InsertApprovalBefore,
    InsertSanitizer,
    InsertTransactionBoundary,
    MoveToLeastPrivilege,
    NullProposer,
    RepairConfig,
    RestrictToolBinding,
    RepairExit,
    RouteUnknownToApproval,
    StrengthenRouterGuard,
    edit_cost,
    repair,
)

_EXACT = Provenance("ast_explicit", "exact", "f:1:1")
_MUST = Modality.MUST


def _node(nid, *, effect=EffectKind.NONE, tool="", cap="", sp=(), in_labels=(),
          out_labels=(), unsupported=()):
    return EffectNode(
        id=nid, effect=effect, tool=tool, capability=cap, state_predicates=sp,
        in_labels=in_labels, out_labels=out_labels, unsupported=unsupported,
        provenance=_EXACT, modeling_confidence="exact",
    )


def _line(*ids):
    return tuple(ModalEdge(ids[i], ids[i + 1], modality=_MUST, provenance=_EXACT)
                 for i in range(len(ids) - 1))


def _financial_graph():
    return MayMustGraph(
        "fin", "t",
        nodes=(_node("entry", sp=("kind:entry",)),
               _node("pay", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                     cap="invokes_tool", sp=("kind:tool",)),
               _node("exit", sp=("kind:exit",))),
        edges=_line("entry", "pay", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )


# ---------------------------------------------------------------------------
# Each applicable edit operator applies (changes the graph)
# ---------------------------------------------------------------------------

def test_insert_approval_before_applies():
    g = _financial_graph()
    op = InsertApprovalBefore(EffectKind.FINANCIAL)
    assert op.applicable(g, None, None)
    g2 = op.apply(g, None, None)
    assert g2 != g
    # a human-pause gate now precedes the financial node
    gates = [n for n in g2.nodes if "human_pause" in n.capability]
    assert gates


def test_restrict_tool_binding_applies():
    g = _financial_graph()
    op = RestrictToolBinding("pay")
    assert op.applicable(g, None, None)
    g2 = op.apply(g, None, None)
    assert g2.node_by_id("pay").tool == ""


def test_move_to_least_privilege_applies():
    g = _financial_graph()
    op = MoveToLeastPrivilege("pay")
    assert op.applicable(g, None, None)
    g2 = op.apply(g, None, None)
    assert g2.node_by_id("pay").principal == "least_privilege"


def test_add_auth_precondition_applies():
    g = _financial_graph()
    op = AddAuthPrecondition("pay")
    assert op.applicable(g, None, None)
    g2 = op.apply(g, None, None)
    assert any(n.identity == "authenticated" for n in g2.nodes)


def test_insert_transaction_boundary_applies():
    g = _financial_graph()
    op = InsertTransactionBoundary("pay")
    assert op.applicable(g, None, None)
    g2 = op.apply(g, None, None)
    assert len(g2.nodes) == len(g.nodes) + 1


def test_insert_sanitizer_applies():
    g = MayMustGraph(
        "flow", "t",
        nodes=(_node("entry", sp=("kind:entry",)),
               _node("src", tool="read_database", in_labels=("pii",), out_labels=("pii",),
                     sp=("kind:tool",)),
               _node("sink", tool="send_email", sp=("kind:tool",)),
               _node("exit", sp=("kind:exit",))),
        edges=_line("entry", "src", "sink", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    op = InsertSanitizer("src", "sink")
    assert op.applicable(g, None, None)
    g2 = op.apply(g, None, None)
    assert len(g2.nodes) == len(g.nodes) + 1


def test_strengthen_router_guard_applies():
    g = MayMustGraph(
        "br", "t",
        nodes=(_node("entry", sp=("kind:entry",)), _node("r"),
               _node("a"), _node("b"), _node("exit", sp=("kind:exit",))),
        edges=(ModalEdge("entry", "r", modality=_MUST, provenance=_EXACT),
               ModalEdge("r", "a", modality=Modality.MAY, control=ControlKind.CONDITIONAL,
                         provenance=_EXACT),
               ModalEdge("r", "b", modality=Modality.MAY, control=ControlKind.CONDITIONAL,
                         provenance=_EXACT),
               ModalEdge("a", "exit", modality=Modality.MAY, provenance=_EXACT),
               ModalEdge("b", "exit", modality=Modality.MAY, provenance=_EXACT)),
        entry_id="entry", exit_ids=("exit",),
    )
    op = StrengthenRouterGuard(("r", "a"))
    assert op.applicable(g, None, None)
    g2 = op.apply(g, None, None)
    ra = [e for e in g2.edges if e.source == "r" and e.target == "a"][0]
    assert ra.guard == "false"


def test_repair_exit_applies():
    g = MayMustGraph(
        "de", "t",
        nodes=(_node("entry", sp=("kind:entry",)), _node("stuck"),
               _node("exit", sp=("kind:exit",))),
        edges=(ModalEdge("entry", "stuck", modality=_MUST, provenance=_EXACT),),
        entry_id="entry", exit_ids=("exit",),
    )
    op = RepairExit("stuck")
    assert op.applicable(g, None, None)
    g2 = op.apply(g, None, None)
    assert g2.out_edges("stuck")


def test_bound_loop_applies():
    g = MayMustGraph(
        "loop", "t",
        nodes=(_node("entry", sp=("kind:entry",)), _node("body", tool="retry"),
               _node("exit", sp=("kind:exit",))),
        edges=(ModalEdge("entry", "body", modality=_MUST, provenance=_EXACT),
               ModalEdge("body", "body", modality=Modality.MAY, control=ControlKind.LOOP,
                         provenance=_EXACT),
               ModalEdge("body", "exit", modality=Modality.MAY, provenance=_EXACT)),
        entry_id="entry", exit_ids=("exit",),
    )
    op = BoundLoop(("body", "body"), k=1)
    assert op.applicable(g, None, None)
    g2 = op.apply(g, None, None)
    looped = [e for e in g2.edges if e.control is ControlKind.LOOP][0]
    assert "iterations" in looped.guard


def test_route_unknown_to_approval_applies():
    g = MayMustGraph(
        "unk", "t",
        nodes=(_node("entry", sp=("kind:entry",)),
               _node("x", effect=EffectKind.UNKNOWN,
                     unsupported=(UnsupportedFact(UnsupportedKind.REFLECTION, "getattr"),)),
               _node("exit", sp=("kind:exit",))),
        edges=_line("entry", "x", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    op = RouteUnknownToApproval("x")
    assert op.applicable(g, None, None)
    g2 = op.apply(g, None, None)
    assert len(g2.nodes) == len(g.nodes) + 1


def test_inapplicable_operators_report_false():
    g = _financial_graph()
    # no tool on entry -> RestrictToolBinding not applicable
    assert not RestrictToolBinding("entry").applicable(g, None, None)
    # no unknown/unsupported node -> RouteUnknownToApproval not applicable
    assert not RouteUnknownToApproval("pay").applicable(g, None, None)
    # no loop edge -> BoundLoop not applicable
    assert not BoundLoop(("pay", "exit"), 1).applicable(g, None, None)


# ---------------------------------------------------------------------------
# End-to-end repair -> SAFE + independently-accepted certificate
# ---------------------------------------------------------------------------

def test_end_to_end_repair_requirebefore():
    g = _financial_graph()
    pol = RequireBefore(Approval(), Effect(EffectKind.FINANCIAL),
                        rule_id="approve_before_financial")
    assert analyze(g, pol).verdict is Verdict.UNSAFE
    r = repair(g, pol)
    assert r.success
    assert r.verdict is Verdict.SAFE
    assert r.cost is not None and r.cost > 0
    assert r.edits
    assert r.certificate is not None
    assert check_certificate(r.certificate).accepted
    # the accepted patched graph really re-verifies SAFE
    assert analyze(r.patched_graph, pol).verdict is Verdict.SAFE


def test_end_to_end_repair_never_tool():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry", sp=("kind:entry",)),
               _node("call", effect=EffectKind.EXECUTE, tool="wire_transfer",
                     cap="invokes_tool", sp=("kind:tool",)),
               _node("exit", sp=("kind:exit",))),
        edges=_line("entry", "call", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    pol = Never(Tool("wire_transfer"), rule_id="no_wire")
    assert analyze(g, pol).verdict is Verdict.UNSAFE
    r = repair(g, pol)
    assert r.success and r.verdict is Verdict.SAFE
    assert any("RestrictToolBinding" in e for e in r.edits)
    assert check_certificate(r.certificate).accepted


def test_already_safe_repair_zero_cost():
    g = MayMustGraph(
        "g", "t",
        nodes=(_node("entry", sp=("kind:entry",)),
               _node("send", effect=EffectKind.COMMUNICATE, tool="send_email",
                     cap="invokes_tool", sp=("kind:tool",)),
               _node("exit", sp=("kind:exit",))),
        edges=_line("entry", "send", "exit"),
        entry_id="entry", exit_ids=("exit",),
    )
    r = repair(g, Never(Tool("wire_transfer"), rule_id="no_wire"))
    assert r.success and r.verdict is Verdict.SAFE
    assert r.cost == 0.0 and r.edits == []
    assert check_certificate(r.certificate).accepted


# ---------------------------------------------------------------------------
# Relative minimality (Theorem 4): cheapest verified candidate wins
# ---------------------------------------------------------------------------

def test_minimality_cheaper_candidate_wins():
    g = _financial_graph()
    pol = RequireBefore(Approval(), Effect(EffectKind.FINANCIAL),
                        rule_id="approve_before_financial")

    class TwoCandidateProposer:
        def propose(self, graph, policy, witness, config):
            cheap = [InsertApprovalBefore(EffectKind.FINANCIAL)]
            costly = [InsertApprovalBefore(EffectKind.FINANCIAL),
                      InsertTransactionBoundary("pay")]
            return [costly, cheap]  # costly first; loop must still pick cheap

    r = repair(g, pol, proposer=TwoCandidateProposer())
    assert r.success
    assert r.edits == ["InsertApprovalBefore(effect=financial)"]

    # confirm the costly candidate really is costlier under the published model
    from agentproof.cegar.repair import _apply_edits

    gc, ac = _apply_edits(g, pol, None, [InsertApprovalBefore(EffectKind.FINANCIAL)])
    gk, ak = _apply_edits(g, pol, None,
                          [InsertApprovalBefore(EffectKind.FINANCIAL),
                           InsertTransactionBoundary("pay")])
    assert edit_cost(ac, g, gc, RepairConfig()) == r.cost
    assert edit_cost(ak, g, gk, RepairConfig()) > r.cost


# ---------------------------------------------------------------------------
# No false success: tampered / unverified patch is rejected
# ---------------------------------------------------------------------------

def test_null_proposer_cannot_repair():
    g = _financial_graph()
    pol = RequireBefore(Approval(), Effect(EffectKind.FINANCIAL))
    r = repair(g, pol, proposer=NullProposer())
    assert not r.success
    assert r.verdict is Verdict.UNSAFE
    assert r.certificate is None and r.patched_graph is None


def test_tampered_certificate_is_rejected():
    """A cert whose embedded graph is actually UNSAFE is caught by the checker."""
    g = _financial_graph()
    pol = RequireBefore(Approval(), Effect(EffectKind.FINANCIAL))
    good = repair(g, pol).certificate
    assert good is not None
    tampered = certificate_mod.Certificate(
        program_hash=certificate_mod.canonical_hash(g.to_dict()),  # recompute so hash gate passes
        policy_hash=good.policy_hash,
        policy=good.policy,
        graph=g.to_dict(),           # swap in the still-UNSAFE graph
        verdict="safe",
        supported_semantics=good.supported_semantics,
        dependency_versions=good.dependency_versions,
        assumptions=good.assumptions,
        abstract_transitions=good.abstract_transitions,
        repair_cost=good.repair_cost,
        regression_manifest=good.regression_manifest,
        created_tag=good.created_tag,
    )
    res = check_certificate(tampered)
    assert not res.accepted
    assert any("BAD PREFIX" in r for r in res.reasons)


def test_repair_never_succeeds_when_checker_rejects(monkeypatch):
    """The independent checker is the SOLE gate: reject it and repair fails."""
    g = _financial_graph()
    pol = RequireBefore(Approval(), Effect(EffectKind.FINANCIAL))

    monkeypatch.setattr(
        checker_mod, "check_certificate",
        lambda cert: CheckResult(accepted=False, reasons=["stub reject"]),
    )
    r = repair(g, pol)
    assert not r.success
    assert r.certificate is None and r.patched_graph is None


def test_repair_regression_gate_blocks_success():
    """A failing user regression predicate prevents a claimed repair."""
    g = _financial_graph()
    pol = RequireBefore(Approval(), Effect(EffectKind.FINANCIAL))

    def failing_regression(patched):
        return (False, {"reason": "lost required behaviour"})

    r = repair(g, pol, regression=failing_regression)
    assert not r.success


def test_repair_result_serializable():
    import json

    g = _financial_graph()
    pol = RequireBefore(Approval(), Effect(EffectKind.FINANCIAL))
    r = repair(g, pol)
    json.dumps(r.to_dict())
