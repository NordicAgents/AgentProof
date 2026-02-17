from __future__ import annotations

from copy import deepcopy

from vac.engine.step import step
from vac.enterprise import build_compliance_summary
from vac.verification.report import generate_report


def test_phase4_step_allows_with_valid_enterprise_controls(base_state, enterprise_registry, valid_proposal) -> None:
    next_state = step(base_state, valid_proposal, enterprise_registry)

    assert next_state.status == "ready"
    assert next_state.trace[-1]["decision"] == "allowed"


def test_phase4_rejects_label_downgrade_without_declassify(base_state, enterprise_registry, valid_proposal) -> None:
    proposal = deepcopy(valid_proposal)
    proposal["infoflow_labels"] = {
        "source_labels": ["restricted"],
        "sink_label": "internal",
    }

    next_state = step(base_state, proposal, enterprise_registry)

    assert next_state.status == "halted"
    assert next_state.trace[-1]["rejection"]["rule_id"] == "INFOFLOW-LABELS"


def test_phase4_rejects_insufficient_sandbox_profile(base_state, enterprise_registry, valid_proposal) -> None:
    proposal = deepcopy(valid_proposal)
    proposal["sandbox_profile"] = "standard"

    next_state = step(base_state, proposal, enterprise_registry)

    assert next_state.status == "halted"
    assert next_state.trace[-1]["rejection"]["rule_id"] == "SANDBOX-PROFILE"


def test_phase4_rejects_unauthorized_cross_agent_call(base_state, enterprise_registry, valid_proposal) -> None:
    proposal = deepcopy(valid_proposal)
    proposal["multi_agent"] = {
        "actor_id": "agent-exec",
        "target_id": "agent-finance",
        "allowed_targets": ["agent-review"],
        "require_approval": False,
    }

    next_state = step(base_state, proposal, enterprise_registry)

    assert next_state.status == "halted"
    assert next_state.trace[-1]["rejection"]["rule_id"] == "MULTIAGENT-ACCESS"


def test_phase4_report_includes_compliance_mappings(base_state, enterprise_registry, valid_proposal) -> None:
    failed = deepcopy(valid_proposal)
    failed["sandbox_profile"] = "standard"
    state = step(base_state, failed, enterprise_registry)

    compliance = build_compliance_summary(state.trace)
    report = generate_report(
        final_state=state,
        run_id=state.run_id,
        spec_hash="phase4-spec",
        engine_version="vac-0.4.0",
    )

    assert "controls" in compliance
    assert report["compliance"]["frameworks"] == ["soc2", "iso27001"]
    assert report["compliance"]["coverage"]
