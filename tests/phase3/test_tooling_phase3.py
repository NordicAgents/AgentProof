from __future__ import annotations

from copy import deepcopy

from vac.forensics.replay import replay_proposals, summarize_trace
from vac.verification.report import generate_report


def test_replay_tooling_generates_deterministic_hashes(base_state, deterministic_registry, valid_proposal) -> None:
    proposals = [valid_proposal, deepcopy(valid_proposal)]

    run_a = replay_proposals(base_state, proposals, deterministic_registry)
    run_b = replay_proposals(base_state, proposals, deterministic_registry)

    assert run_a.decision_sequence == ("allowed", "allowed")
    assert run_a.decision_hash == run_b.decision_hash
    assert run_a.state_hash == run_b.state_hash


def test_forensic_summary_and_report_certificate_shapes(base_state, deterministic_registry, valid_proposal) -> None:
    result = replay_proposals(base_state, [valid_proposal], deterministic_registry)
    summary = summarize_trace(result.final_state)

    assert summary["decision_summary"]["allowed"] == 1
    assert summary["decision_summary"]["rejected"] == 0

    report = generate_report(
        final_state=result.final_state,
        run_id=result.final_state.run_id,
        spec_hash="spec-hash-fixed",
        engine_version="vac-0.3.0",
        assumptions=["deterministic wrappers"],
        bounds={"bmc_k": 2, "timeouts_ms": 250},
        tool_versions={"email.send": "1.0.0"},
        nondeterminism_controls=["stubbed_tool_outputs"],
    )

    assert report["contract_family"] == "vac.verification_report"
    assert report["hashes"]["decision_hash"]
    assert report["hashes"]["state_hash"] == report["artifacts"]["state_hash_final"]
    assert report["hashes"]["report_hash"]
