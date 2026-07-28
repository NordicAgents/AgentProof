from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_prospective_validation_sample.py"
MANIFEST = (
    ROOT / "corpus" / "annotations" / "prospective_validation_manifest.json"
)
SOURCE_SNAPSHOTS = ROOT / "corpus" / "real_world" / "sources"
SOURCE_SNAPSHOTS_AVAILABLE = any(SOURCE_SNAPSHOTS.glob("*.py"))


def load_sampler():
    spec = importlib.util.spec_from_file_location("prospective_sampler", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    not SOURCE_SNAPSHOTS_AVAILABLE,
    reason="third-party source snapshots are not redistributed in the artifact",
)
def test_prospective_sample_is_deterministic_and_matches_manifest():
    sampler = load_sampler()
    regenerated = sampler.sample_manifest(
        seed=sampler.DEFAULT_SEED,
        repos_per_framework=sampler.DEFAULT_REPOS_PER_FRAMEWORK,
        human_per_framework=sampler.DEFAULT_HUMAN_PER_FRAMEWORK,
    )
    committed = json.loads(MANIFEST.read_text())
    assert regenerated == committed


def test_prospective_sample_has_declared_design():
    sampler = load_sampler()
    manifest = json.loads(MANIFEST.read_text())
    sample = manifest["audit_sample"]

    assert manifest["_meta"]["status"] == "frozen_before_annotation"
    assert len(sample) == 96
    assert len({item["workflow_id"] for item in sample}) == 96
    assert len(
        {(item["framework"], item["repository"]) for item in sample}
    ) == 96
    assert Counter(item["framework"] for item in sample) == {
        framework: 24 for framework in sampler.FRAMEWORKS
    }
    assert Counter(
        item["framework"]
        for item in sample
        if item["independent_human_reconstruction"]
    ) == {framework: 8 for framework in sampler.FRAMEWORKS}


def test_prospective_sample_has_valid_probabilities_and_integrity():
    sampler = load_sampler()
    manifest = json.loads(MANIFEST.read_text())
    for item in manifest["audit_sample"]:
        expected = (
            item["repository_selection_probability"]
            * item["within_repository_selection_probability"]
        )
        assert abs(item["workflow_inclusion_probability"] - expected) < 1e-10
        assert abs(
            item["design_weight"]
            * item["workflow_inclusion_probability"]
            - 1
        ) < 1e-9
        assert (
            item["workflow_id"]
            == f"{item['repository']}@{item['commit_sha']}:{item['source_path']}"
        )

    if not SOURCE_SNAPSHOTS_AVAILABLE:
        pytest.skip(
            "source-hash checks require third-party snapshots omitted from the artifact"
        )

    for item in manifest["audit_sample"]:
        source = ROOT / item["source_snapshot_path"]
        assert source.is_file()
        assert sampler.sha256(source) == item["source_sha256"]
