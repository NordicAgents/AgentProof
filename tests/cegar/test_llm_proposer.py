"""Offline tests for the untrusted LLM patch proposer.

No network and no ``anthropic`` SDK are required: a fake ``complete`` callable
stands in for the model. The load-bearing test is
:func:`test_wrong_llm_suggestion_is_not_admitted` — a *valid but wrong* model
suggestion must never yield a reported repair, because only the independent
certificate checker admits a patch (the LLM is outside the TCB).
"""

from __future__ import annotations

import os

import pytest

from agentproof.cegar.checker import check_certificate
from agentproof.cegar.ir import (
    EffectKind,
    EffectNode,
    MayMustGraph,
    ModalEdge,
    Modality,
    Provenance,
    ToolSchema,
    Verdict,
)
from agentproof.cegar.llm_proposer import (
    CombinedProposer,
    LLMProposer,
    build_op,
    parse_edit_sequences,
    render_prompt,
)
from agentproof.cegar.policy import Approval, Effect, RequireBefore
from agentproof.cegar.repair import (
    GrammarProposer,
    InsertApprovalBefore,
    RepairConfig,
    RestrictToolBinding,
    repair,
)
from agentproof.cegar.product import check


# ---------------------------------------------------------------------------
# Fixtures: an unsafe graph (financial effect with no prior approval)
# ---------------------------------------------------------------------------

def _exact() -> Provenance:
    return Provenance(origin="ast_explicit", confidence="exact", source_span="f:1:1")


def _unsafe_graph() -> MayMustGraph:
    nodes = (
        EffectNode(id="entry", effect=EffectKind.NONE, provenance=_exact(),
                   modeling_confidence="exact", state_predicates=("kind:entry",)),
        EffectNode(id="pay", effect=EffectKind.FINANCIAL, tool="wire",
                   tool_schema=ToolSchema("wire", effect=EffectKind.FINANCIAL),
                   provenance=_exact(), modeling_confidence="exact",
                   state_predicates=("kind:tool",)),
        EffectNode(id="exit", effect=EffectKind.NONE, provenance=_exact(),
                   modeling_confidence="exact", state_predicates=("kind:exit",)),
    )
    edges = (
        ModalEdge(source="entry", target="pay", modality=Modality.MUST, provenance=_exact()),
        ModalEdge(source="pay", target="exit", modality=Modality.MUST, provenance=_exact()),
    )
    return MayMustGraph(name="pay", framework="none", nodes=nodes, edges=edges,
                        entry_id="entry", exit_ids=("exit",))


_POLICY = RequireBefore(Approval(), Effect(EffectKind.FINANCIAL), rule_id="approve_before_pay")


def _fake(reply: str):
    """A completer that ignores the prompt and returns a canned reply."""
    def complete(prompt: str) -> str:
        assert isinstance(prompt, str) and prompt
        return reply
    return complete


# ---------------------------------------------------------------------------
# build_op — untrusted (name, params) -> EditOp | None
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,params,cls", [
    ("insert_approval_before", {"effect": "financial"}, InsertApprovalBefore),
    ("restrict_tool_binding", {"node_id": "pay"}, RestrictToolBinding),
])
def test_build_op_valid(name, params, cls):
    op = build_op(name, params)
    assert isinstance(op, cls)


@pytest.mark.parametrize("name,params", [
    ("does_not_exist", {"effect": "financial"}),   # unknown op
    ("insert_approval_before", {"effect": "not_a_kind"}),  # bad enum value
    ("insert_approval_before", {}),                 # missing required param
    ("bound_loop", {"edge_source": "a", "edge_target": "b", "k": "NaN"}),  # bad int
    ("restrict_tool_binding", "not-a-dict"),        # params not a dict
])
def test_build_op_invalid_returns_none(name, params):
    assert build_op(name, params) is None


# ---------------------------------------------------------------------------
# parse_edit_sequences — defensive parsing of an untrusted reply
# ---------------------------------------------------------------------------

def test_parse_drops_malformed_edits_keeps_valid():
    raw = (
        '{"candidates": ['
        '{"edits": [{"op": "insert_approval_before", "params": {"effect": "financial"}},'
        '           {"op": "bogus", "params": {}}]},'      # one valid, one dropped
        '{"edits": [{"op": "nope", "params": {}}]}'          # all invalid -> candidate dropped
        ']}'
    )
    seqs = parse_edit_sequences(raw)
    assert len(seqs) == 1
    assert len(seqs[0]) == 1 and isinstance(seqs[0][0], InsertApprovalBefore)


def test_parse_tolerates_code_fence_and_prose():
    raw = 'Here you go:\n```json\n{"candidates": [{"edits": [{"op": "restrict_tool_binding", "params": {"node_id": "pay"}}]}]}\n```'
    seqs = parse_edit_sequences(raw)
    assert len(seqs) == 1 and isinstance(seqs[0][0], RestrictToolBinding)


def test_parse_garbage_returns_empty():
    assert parse_edit_sequences("not json at all") == []
    assert parse_edit_sequences("") == []
    assert parse_edit_sequences('{"candidates": "wrong type"}') == []


def test_render_prompt_mentions_ops_and_ids():
    prompt = render_prompt(_unsafe_graph(), _POLICY, None, RepairConfig())
    assert "insert_approval_before" in prompt
    assert "pay" in prompt and "approve_before_pay" in prompt


# ---------------------------------------------------------------------------
# End-to-end through repair() — the LLM stays outside the TCB
# ---------------------------------------------------------------------------

def test_correct_llm_suggestion_is_verified_and_certified():
    # Sanity: the graph really is unsafe.
    assert check(_unsafe_graph(), _POLICY).verdict is Verdict.UNSAFE

    reply = ('{"candidates": [{"edits": ['
             '{"op": "insert_approval_before", "params": {"effect": "financial"}}'
             '], "rationale": "approve before paying"}]}')
    result = repair(_unsafe_graph(), _POLICY, proposer=LLMProposer(_fake(reply)))

    assert result.success and result.verdict is Verdict.SAFE
    assert result.edits, "a repair should record its edits"
    # The admission is the INDEPENDENT checker's, not the LLM's.
    assert result.certificate is not None
    assert check_certificate(result.certificate).accepted


def test_wrong_llm_suggestion_is_not_admitted():
    # A VALID op that does not remove the violation: dropping the tool binding
    # leaves the node's FINANCIAL effect (and the missing approval) intact.
    reply = ('{"candidates": [{"edits": ['
             '{"op": "restrict_tool_binding", "params": {"node_id": "pay"}}'
             '], "rationale": "this does not actually fix it"}]}')
    result = repair(_unsafe_graph(), _POLICY, proposer=LLMProposer(_fake(reply)))

    assert result.success is False
    assert result.verdict is not Verdict.SAFE
    assert result.certificate is None


def test_garbage_and_failing_completer_do_not_crash_repair():
    # Garbage reply -> no candidates -> no repair, but no crash.
    r1 = repair(_unsafe_graph(), _POLICY, proposer=LLMProposer(_fake("garbage")))
    assert r1.success is False

    def boom(prompt: str) -> str:
        raise RuntimeError("model unavailable")

    prop = LLMProposer(boom)
    assert prop.propose(_unsafe_graph(), _POLICY, None, RepairConfig()) == []
    r2 = repair(_unsafe_graph(), _POLICY, proposer=prop)
    assert r2.success is False


def test_combined_proposer_unions_and_repairs_via_solver():
    # LLM contributes nothing usable; the grammar solver still fixes it, and the
    # combined proposer's union is admitted by the checker.
    combined = CombinedProposer([LLMProposer(_fake("junk")), GrammarProposer()])
    result = repair(_unsafe_graph(), _POLICY, proposer=combined)
    assert result.success and result.verdict is Verdict.SAFE
    assert check_certificate(result.certificate).accepted


# ---------------------------------------------------------------------------
# Live-API smoke — skipped unless a key AND the SDK are present
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="no ANTHROPIC_API_KEY; live Claude proposer not exercised",
)
def test_live_anthropic_proposer():  # pragma: no cover - network/model gated
    pytest.importorskip("anthropic")
    from agentproof.cegar.llm_proposer import anthropic_completer

    result = repair(_unsafe_graph(), _POLICY, proposer=LLMProposer(anthropic_completer()))
    # Even live, admission is gated by the independent checker.
    if result.success:
        assert check_certificate(result.certificate).accepted
