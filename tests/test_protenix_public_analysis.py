"""Denominator and fail-closed membership checks for completed replay analysis."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _analyzer(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "public_analysis", ROOT / "scripts/analyze_protenix_public_cohort.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rejected_cases_stay_in_denominator_but_not_valid_rmsd_median(monkeypatch):
    analyzer = _analyzer(monkeypatch)
    rows = [
        {"validation_passed": passed, "quality": {"gap_backbone_rmsd_angstrom": rmsd},
         "resource_metrics": {"wall_time_seconds": time, "peak_ram_bytes": ram, "peak_vram_bytes": vram}}
        for passed, rmsd, time, ram, vram in (
            (True, 0.2, 10, 100, 200), (True, 0.4, 20, 150, 250),
            (False, 10.0, 30, 300, 500),
        )
    ]
    result = analyzer.summarize(rows)
    assert result["case_count"] == 3
    assert result["pass_rate"] == pytest.approx(2 / 3)
    assert result["median_valid_gap_backbone_rmsd_angstrom"] == pytest.approx(0.3)
    assert result["summed_runner_wall_time_seconds"] == 60
    assert result["peak_ram_bytes"] == 300


@pytest.mark.parametrize("problem", ["incomplete", "duplicate", "reordered", "wrong-seed"])
def test_analysis_rejects_invalid_completion_membership(monkeypatch, problem):
    analyzer = _analyzer(monkeypatch)
    members = ({"case_id": "one"}, {"case_id": "two"})
    report = {"complete": True, "manifest_sha256": analyzer.FROZEN_MANIFEST_SHA256,
              "seed": 7, "cases": list(members)}
    analyzer.validate_completion(report, members)
    if problem == "incomplete":
        report["complete"] = False
    elif problem == "duplicate":
        report["cases"] = [members[0], members[0]]
    elif problem == "reordered":
        report["cases"] = list(reversed(members))
    else:
        report["seed"] = 11
    with pytest.raises(analyzer.PublicCohortError):
        analyzer.validate_completion(report, members)
