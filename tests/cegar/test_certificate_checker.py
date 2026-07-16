"""Independent certificate-checker acceptance / rejection (Paper 2, §4.6; Thm 2).

Builds a genuine SAFE certificate the independent checker accepts, then applies
a battery of mutations — flipped hash, tampered graph introducing a forbidden
tool, verdict flip, uncertified (non-exact) region — and asserts EVERY mutation
is rejected. The checker is the last line of defence against a false-SAFE proof,
so a mutation slipping through would be a soundness break.
"""

from __future__ import annotations

import copy

from agentproof.cegar.certificate import (
    Certificate,
    build_certificate,
    canonical_hash,
)
from agentproof.cegar.checker import check_certificate
from agentproof.cegar.ir import (
    EffectKind,
    EffectNode,
    MayMustGraph,
    ModalEdge,
    Modality,
    Provenance,
    Verdict,
)
from agentproof.cegar.policy import Never, RequireBefore, Approval, Effect, Tool

_EXACT = Provenance("ast_explicit", "exact", "f:1:2")
_MUST = Modality.MUST


class _SafeResult:
    verdict = Verdict.SAFE
    visited = [("entry", "None"), ("t1", "None"), ("exit", "None")]


def _clean_graph():
    nodes = (
        EffectNode(id="entry", provenance=_EXACT, modeling_confidence="exact",
                   state_predicates=("kind:entry",)),
        EffectNode(id="t1", effect=EffectKind.READ, tool="safe_reader",
                   provenance=_EXACT, modeling_confidence="exact",
                   state_predicates=("kind:tool",)),
        EffectNode(id="exit", provenance=_EXACT, modeling_confidence="exact",
                   state_predicates=("kind:exit",)),
    )
    edges = (
        ModalEdge("entry", "t1", modality=_MUST, provenance=_EXACT),
        ModalEdge("t1", "exit", modality=_MUST, provenance=_EXACT),
    )
    return MayMustGraph("clean", "none", nodes, edges, entry_id="entry", exit_ids=("exit",))


def _clean_cert():
    return build_certificate(_clean_graph(), Never(Tool("danger"), rule_id="no-danger"),
                             _SafeResult(), created_tag="test")


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------

def test_clean_certificate_accepted():
    res = check_certificate(_clean_cert())
    assert res.accepted, res.reasons
    assert res.reasons == []


def test_roundtrip_preserves_acceptance():
    cert = _clean_cert()
    reparsed = Certificate.from_dict(cert.to_dict())
    assert check_certificate(reparsed).accepted


def test_write_read_json_roundtrip(tmp_path):
    cert = _clean_cert()
    path = tmp_path / "cert.json"
    cert.write_json(str(path))
    back = Certificate.read_json(str(path))
    assert check_certificate(back).accepted
    assert back.to_dict() == cert.to_dict()


# ---------------------------------------------------------------------------
# Mutations — every one must be REJECTED
# ---------------------------------------------------------------------------

def test_reject_flipped_program_hash():
    cert = _clean_cert()
    mutated = copy.deepcopy(cert)
    object.__setattr__(mutated, "program_hash", "0" * 64)
    res = check_certificate(mutated)
    assert not res.accepted
    assert any("program_hash" in r for r in res.reasons)


def test_reject_flipped_policy_hash():
    cert = _clean_cert()
    mutated = copy.deepcopy(cert)
    object.__setattr__(mutated, "policy_hash", "0" * 64)
    res = check_certificate(mutated)
    assert not res.accepted
    assert any("policy_hash" in r for r in res.reasons)


def test_reject_verdict_flip():
    cert = _clean_cert()
    mutated = copy.deepcopy(cert)
    object.__setattr__(mutated, "verdict", "unknown")
    res = check_certificate(mutated)
    assert not res.accepted
    assert any("not 'safe'" in r for r in res.reasons)


def test_reject_graph_tampered_with_forbidden_tool():
    """A forbidden-tool node reachable from entry (hash recomputed) is caught by
    the checker's own re-derivation — not by the hash gate."""
    cert = _clean_cert()
    g = _clean_graph()
    tampered = g.with_node(
        EffectNode(id="bad", effect=EffectKind.EXECUTE, tool="danger",
                   provenance=_EXACT, modeling_confidence="exact",
                   state_predicates=("kind:tool",))
    )
    tampered = tampered.with_edges(
        tampered.edges + (
            ModalEdge("entry", "bad", modality=Modality.MAY, provenance=_EXACT),
            ModalEdge("bad", "exit", modality=Modality.MAY, provenance=_EXACT),
        )
    )
    mutated = copy.deepcopy(cert)
    object.__setattr__(mutated, "graph", tampered.to_dict())
    object.__setattr__(mutated, "program_hash", canonical_hash(tampered.to_dict()))
    res = check_certificate(mutated)
    assert not res.accepted
    assert any("BAD PREFIX" in r for r in res.reasons)


def test_reject_uncertified_region():
    """Non-exact provenance in a reachable node fails the certification gate."""
    cert = _clean_cert()
    weak = Provenance("ast_inferred", "may")
    g = _clean_graph()
    weak_graph = g.with_node(
        EffectNode(id="t1", effect=EffectKind.READ, tool="safe_reader",
                   provenance=weak, modeling_confidence="may",
                   state_predicates=("kind:tool",))
    )
    mutated = copy.deepcopy(cert)
    object.__setattr__(mutated, "graph", weak_graph.to_dict())
    object.__setattr__(mutated, "program_hash", canonical_hash(weak_graph.to_dict()))
    res = check_certificate(mutated)
    assert not res.accepted
    assert any("certification gate" in r for r in res.reasons)


def test_reject_graph_swap_without_hash_update():
    """Swapping the embedded graph but NOT the hash trips the hash gate."""
    cert = _clean_cert()
    other = _clean_graph().with_node(
        EffectNode(id="t1", effect=EffectKind.EXECUTE, tool="danger",
                   provenance=_EXACT, modeling_confidence="exact",
                   state_predicates=("kind:tool",))
    )
    mutated = copy.deepcopy(cert)
    object.__setattr__(mutated, "graph", other.to_dict())  # hash left stale
    res = check_certificate(mutated)
    assert not res.accepted
    assert any("program_hash" in r for r in res.reasons)


def test_reject_missing_entry_node():
    cert = _clean_cert()
    from dataclasses import replace

    g = _clean_graph()
    broken = replace(g, entry_id="ghost")
    mutated = copy.deepcopy(cert)
    object.__setattr__(mutated, "graph", broken.to_dict())
    object.__setattr__(mutated, "program_hash", canonical_hash(broken.to_dict()))
    res = check_certificate(mutated)
    assert not res.accepted


# ---------------------------------------------------------------------------
# trace-conservative assumption path
# ---------------------------------------------------------------------------

def test_assumed_conservative_accepts_weak_region():
    weak = Provenance("ast_inferred", "may")
    g = _clean_graph()
    weak_graph = g.with_node(
        EffectNode(id="t1", effect=EffectKind.READ, tool="safe_reader",
                   provenance=weak, modeling_confidence="may",
                   state_predicates=("kind:tool",))
    )
    assumed = build_certificate(weak_graph, Never(Tool("danger"), rule_id="no-danger"),
                                _SafeResult(), assume_trace_conservative=True)
    assert check_certificate(assumed).accepted
    # ... and WITHOUT the assumption the same weak graph is rejected.
    not_assumed = build_certificate(weak_graph, Never(Tool("danger"), rule_id="no-danger"),
                                    _SafeResult())
    assert not check_certificate(not_assumed).accepted


# ---------------------------------------------------------------------------
# Operator coverage: unfulfilled-obligation rejection
# ---------------------------------------------------------------------------

def test_reject_unfulfilled_requirebefore():
    """RequireBefore with the guarded effect but no prior approval -> rejected."""
    g = MayMustGraph(
        "rb", "none",
        nodes=(
            EffectNode(id="entry", provenance=_EXACT, modeling_confidence="exact",
                       state_predicates=("kind:entry",)),
            EffectNode(id="pay", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                       provenance=_EXACT, modeling_confidence="exact",
                       state_predicates=("kind:tool",)),
            EffectNode(id="exit", provenance=_EXACT, modeling_confidence="exact",
                       state_predicates=("kind:exit",)),
        ),
        edges=(ModalEdge("entry", "pay", modality=_MUST, provenance=_EXACT),
               ModalEdge("pay", "exit", modality=_MUST, provenance=_EXACT)),
        entry_id="entry", exit_ids=("exit",),
    )
    pol = RequireBefore(Approval(), Effect(EffectKind.FINANCIAL), rule_id="rb")
    # Force a SAFE-looking certificate over an actually-UNSAFE graph.
    forged = build_certificate(g, pol, _SafeResult())
    res = check_certificate(forged)
    assert not res.accepted
    assert any("BAD PREFIX" in r for r in res.reasons)
