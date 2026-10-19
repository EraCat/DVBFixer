"""Fail-closed checks for offline CUDA evidence analysis (no GPU required)."""

from __future__ import annotations

import importlib.util
import json
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/analyze_a100_calibration.py"
SPEC = importlib.util.spec_from_file_location("cuda_analysis", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


@dataclass
class Metric:
    name: str
    value: float
    unit: str


@dataclass
class Validation:
    passed: bool
    metrics: list[Metric]


def test_validation_roundoff_tolerance_preserves_exact_counts_and_decisions():
    current = Validation(False, [Metric("distance", 1.0, "angstrom"), Metric("clashes", 2, "count")])
    recorded = {"passed": False, "metrics": [
        {"name": "distance", "value": 1.0 + 3e-15, "unit": "angstrom"},
        {"name": "clashes", "value": 2, "unit": "count"},
    ]}
    assert analysis.equivalent_validation(current, recorded)
    recorded["metrics"][1]["value"] += 1e-13
    assert not analysis.equivalent_validation(current, recorded)
    recorded["metrics"][1]["value"] = 2
    recorded["passed"] = True
    assert not analysis.equivalent_validation(current, recorded)


def test_incomplete_analysis_requires_explicit_opt_in_and_keeps_pending_membership(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"cases": [{"case_id": "one", "arms": ["static-local"], "artifacts": {}}],
        "screening": [], "scope": "test", "leakage": {}}))
    args = Namespace(manifest=manifest, cohort=tmp_path, outcomes=tmp_path, output=tmp_path / "analysis.json",
        allow_incomplete=False)
    with pytest.raises(FileNotFoundError):
        analysis.analyze(args)
    args.allow_incomplete = True
    analysis.analyze(args)
    report = json.loads(args.output.read_text())
    assert report["complete"] is False
    assert report["pending"] == [{"case_id": "one", "arm": "static-local"}]
    assert report["cases"] == []
    assert report["public_promotion"] is False


def test_incomplete_mode_still_rejects_corrupt_completed_inventory(tmp_path):
    import hashlib

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"cases": [{"case_id": "one", "arms": ["static-local"], "artifacts": {}}]}))
    root = tmp_path / "one/static-local"
    root.mkdir(parents=True)
    (root / "candidate.pdb").write_text("tampered")
    (root / "complete.json").write_text(json.dumps({
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "artifacts": {"candidate.pdb": "0" * 64},
    }))
    args = Namespace(manifest=manifest, cohort=tmp_path, outcomes=tmp_path, output=tmp_path / "analysis.json",
        allow_incomplete=True)
    with pytest.raises(ValueError, match="artifact digest changed"):
        analysis.analyze(args)
