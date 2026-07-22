"""Regression tests for the reviewer-response analysis scripts.

`scripts/human_agreement.py` produces inter-annotator statistics that go
straight into the paper, so the estimators are pinned against textbook values
here.  `scripts/fp_fn_decomposition.py` produces the survival-test attribution,
whose rule ordering (guard before R1) is the part that is easy to break.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from human_agreement import (  # noqa: E402
    cohens_kappa,
    compare_graphs,
    krippendorff_alpha,
    raw_agreement,
)


class TestCohensKappa:
    def test_perfect_agreement_is_one(self):
        pairs = [("a", "a"), ("b", "b"), ("a", "a"), ("b", "b")]
        assert cohens_kappa(pairs) == pytest.approx(1.0)

    def test_chance_level_agreement_is_zero(self):
        pairs = [("a", "a"), ("a", "b"), ("b", "a"), ("b", "b")]
        assert cohens_kappa(pairs) == pytest.approx(0.0)

    def test_textbook_value(self):
        # Standard 2x2 worked example: cells 20 / 5 / 10 / 15 -> kappa = 0.4.
        pairs = ([("y", "y")] * 20 + [("y", "n")] * 5
                 + [("n", "y")] * 10 + [("n", "n")] * 15)
        assert raw_agreement(pairs) == pytest.approx(0.7)
        assert cohens_kappa(pairs) == pytest.approx(0.4, abs=1e-9)

    def test_degenerate_single_label_is_nan(self):
        # Both coders used one identical label: kappa is undefined, and must
        # not silently report 1.0.
        assert math.isnan(cohens_kappa([("a", "a")] * 10))

    def test_empty_is_nan(self):
        assert math.isnan(cohens_kappa([]))


class TestKrippendorffAlpha:
    def test_perfect_agreement_is_one(self):
        pairs = [("a", "a"), ("b", "b"), ("c", "c"), ("b", "b")]
        assert krippendorff_alpha(pairs) == pytest.approx(1.0)

    def test_high_agreement_is_below_one(self):
        pairs = [("a", "a"), ("b", "b"), ("b", "b"), ("b", "b"), ("c", "c"),
                 ("c", "c"), ("c", "c"), ("d", "d"), ("d", "d"), ("a", "b")]
        alpha = krippendorff_alpha(pairs)
        assert 0.8 < alpha < 1.0

    def test_small_sample_correction_is_present(self):
        # alpha carries an (n-1) correction in D_e, so replicating the same
        # units moves it toward the uncorrected value rather than leaving it
        # fixed.  This pins the correction: drop it and the two agree exactly.
        pairs = [("a", "a"), ("a", "b"), ("b", "a"), ("b", "b")]
        small, large = krippendorff_alpha(pairs), krippendorff_alpha(pairs * 25)
        assert small != pytest.approx(large)
        assert abs(large) < abs(small)

    def test_empty_is_nan(self):
        assert math.isnan(krippendorff_alpha([]))


class TestCompareGraphs:
    def test_identical_graphs_score_one(self):
        g = {"nodes": [{"id": "x", "kind": "llm"}, {"id": "y", "kind": "tool"}],
             "edges": [{"source": "x", "target": "y"}]}
        r = compare_graphs(g, g)
        assert r["nodes"]["f1"] == pytest.approx(1.0)
        assert r["edges"]["f1"] == pytest.approx(1.0)
        assert r["kind_accuracy"] == pytest.approx(1.0)

    def test_renamed_node_costs_precision_and_recall(self):
        a = {"nodes": [{"id": "x", "kind": "llm"}, {"id": "y", "kind": "tool"}],
             "edges": [{"source": "x", "target": "y"}]}
        b = {"nodes": [{"id": "x", "kind": "llm"}, {"id": "z", "kind": "tool"}],
             "edges": [{"source": "x", "target": "z"}]}
        r = compare_graphs(a, b)
        assert r["nodes"]["f1"] == pytest.approx(0.5)
        assert r["edges"]["tp"] == 0
        assert r["n_shared_nodes"] == 1

    def test_kind_accuracy_only_over_shared_nodes(self):
        a = {"nodes": [{"id": "x", "kind": "llm"}], "edges": []}
        b = {"nodes": [{"id": "x", "kind": "tool"}, {"id": "q", "kind": "llm"}],
             "edges": []}
        r = compare_graphs(a, b)
        assert r["n_shared_nodes"] == 1
        assert r["kind_accuracy"] == pytest.approx(0.0)

    def test_edgeless_graphs_report_none_not_zero(self):
        g = {"nodes": [{"id": "x", "kind": "llm"}], "edges": []}
        assert compare_graphs(g, g)["edges"]["f1"] is None


class TestSurvivalTestRuleOrdering:
    """The validity guard must be consulted before the oracle survival test."""

    def test_guard_precedes_r1(self):
        from fp_fn_decomposition import decompose_false_positives

        # One workflow, one structural flag that SURVIVES on the reference
        # graph.  Without the guard this is CHECKER (R2); with the guard
        # tripped it must be REFERENCE_ERROR.
        gt = {"w": {"name": "w", "framework": "langgraph",
                    "nodes": [{"id": "__start__", "kind": "entry"},
                              {"id": "a", "kind": "llm"}],
                    "edges": [{"source": "__start__", "target": "a"}],
                    "entry_id": "__start__", "exit_ids": []}}
        validated = {"triage_details": [
            {"slug": "w", "check": "dead_ends",
             "label": "extraction_artifact", "confidence": "high"}]}

        unguarded = decompose_false_positives(
            validated, gt, set(), {"w": "langgraph"}, set(), set())
        guarded = decompose_false_positives(
            validated, gt, set(), {"w": "langgraph"}, {("w", "dead_ends")},
            set())

        assert unguarded["rows"][0]["cause"] == "CHECKER"
        assert guarded["rows"][0]["cause"] == "REFERENCE_ERROR"

    def test_arguable_label_wins_over_graph_evidence(self):
        from fp_fn_decomposition import decompose_false_positives

        gt = {"w": {"name": "w", "framework": "langgraph",
                    "nodes": [{"id": "a", "kind": "llm"}], "edges": [],
                    "entry_id": "a", "exit_ids": []}}
        validated = {"triage_details": [
            {"slug": "w", "check": "dead_ends", "label": "arguable",
             "confidence": "low"}]}
        out = decompose_false_positives(
            validated, gt, set(), {"w": "langgraph"}, set(), set())
        assert out["rows"][0]["cause"] == "LABEL"
        assert out["rows"][0]["rule"] == "R4"
