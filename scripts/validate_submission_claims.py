#!/usr/bin/env python3
"""Fail if primary submission artifacts disagree on headline denominators.

This is intentionally small and offline. It protects the upload bundle from
regressions to the withdrawn 3/119 policy union, the pre-exclusion 187-flag
triage, or the collision-contaminated fidelity set.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RW = ROOT / "corpus" / "real_world"
ANNOT = ROOT / "corpus" / "annotations"


def load(name: str) -> dict:
    return json.loads((RW / name).read_text())


def main() -> None:
    hgp = load("human_gate_audit.json")
    reviewer = load("reviewer_analyses.json")
    intervals = load("confidence_intervals.json")
    fidelity = load("matched_fidelity.json")
    decomposition = load("fp_fn_decomposition.json")
    pruning = load("pruning_experiment.json")
    supplement_cis = load("supplement_cis.json")
    prospective = json.loads(
        (ANNOT / "prospective_validation_manifest.json").read_text()
    )

    assert hgp["counts"] == {
        "violation": 12,
        "compliant": 9,
        "arguable": 11,
        "source_unavailable": 0,
    }
    estimands = reviewer["1_separate_estimands"]
    assert (estimands["structural"]["k"], estimands["structural"]["n"]) == (1, 119)
    assert (estimands["policy"]["k"], estimands["policy"]["n"]) == (12, 119)
    assert (
        estimands["composite_any"]["k"],
        estimands["composite_any"]["n"],
    ) == (13, 119)
    assert (
        estimands["superseded_two_graph_check_union"]["status"]
        == "withdrawn; not the current policy estimand"
    )
    weighted = hgp["corpus_share_weighted_sensitivity"]
    for reviewer_key, hgp_key in (
        ("policy", "violations_only"),
        ("composite_any", "composite"),
    ):
        reviewer_ci = reviewer["2_post_stratification"][reviewer_key][
            "post_stratified_cluster_bootstrap_ci"
        ]["ci95"]
        hgp_ci = weighted[hgp_key]["repo_clustered_bootstrap_95"]
        assert [round(value, 4) for value in reviewer_ci] == hgp_ci

    prevalence = intervals["prevalence_ci"]
    assert prevalence["genuine_of_all_flags"][:2] == [2, 186]
    assert prevalence["structural_genuine"][:2] == [0, 72]
    assert prevalence["hgp1_violation"][:2] == [12, 119]
    assert intervals["_meta"]["fidelity_set"].endswith("n=106")

    collision_free = fidelity["provenance_collisions"]["collision_free_fidelity"]
    assert collision_free["n"] == 106
    for instrument in ("v1", "v2"):
        for stratum in ("overall", "langgraph", "crewai", "autogen", "adk"):
            for metric in (
                "node_precision",
                "node_recall",
                "edge_precision",
                "edge_recall",
                "kind_accuracy",
            ):
                current = intervals["fidelity_ci"][instrument][stratum][metric]
                supplement = supplement_cis[f"{instrument}:{stratum}"][metric]
                assert [round(value, 3) for value in current] == supplement
    assert (
        decomposition["false_negatives"][
            "n_source_audited_human_gate_violations"
        ]
        == 12
    )
    collision_fp = decomposition["false_positives"]["collision_exclusion"]
    assert collision_fp["n_ambiguous_legacy_slugs_in_triage"] == 10
    assert collision_fp["n_flags_removed"] == 12
    retained = collision_fp["retained"]
    assert retained["n_flags"] == 174
    assert retained["n_non_actionable"] == 172
    assert retained["by_check_family"]["structural"]["n"] == 70
    assert (
        retained["by_check_family"]["structural"]["dist"]["EXTRACTOR"]["n"]
        == 66
    )
    assert retained["by_check_family"]["human_gate"]["n"] == 102
    assert (
        retained["by_check_family"]["human_gate"]["dist"]["POLICY_SPEC"]["n"]
        == 84
    )
    collision_hgp = hgp["legacy_slug_collision_sensitivity"]
    assert collision_hgp["n_validation_sample_records_excluded"] == 10
    assert collision_hgp["n_effect_bearing_records_excluded"] == 1
    assert collision_hgp["violation_count_unchanged"] is True
    assert collision_hgp["retained_effect_bearing_counts"] == {
        "violation": 12,
        "compliant": 9,
        "arguable": 10,
        "source_unavailable": 0,
    }
    assert pruning["n_pairs"] == 18
    assert pruning["strategies"]["path_sensitive_product"]["pruned"] == 10
    assert prospective["_meta"]["status"] == "frozen_before_annotation"
    assert len(prospective["audit_sample"]) == 96
    assert len(prospective["human_reconstruction_workflow_ids"]) == 32
    assert prospective["frame"]["n_eligible_workflows"] == 904

    print(
        "headline consistency validated: fidelity n=106; triage n=186; "
        "HGP-1 12/119; prospective audit n=96 with 32 dual-human "
        "reconstructions frozen"
    )


if __name__ == "__main__":
    main()
