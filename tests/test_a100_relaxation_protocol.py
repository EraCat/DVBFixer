"""Frozen membership and custody checks for the paired relaxation study."""

import importlib.util
import json
from argparse import Namespace
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_a100_relaxation.py"
SPEC = importlib.util.spec_from_file_location("a100_relaxation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
relaxation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relaxation)


def test_freeze_includes_raw_passing_and_failing_arms_and_rejects_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(relaxation, "check_cuda_runtime", lambda: None)
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "failure-analysis.json").write_text("{}")
    raw_manifest = tmp_path / "raw-manifest.json"
    raw_manifest.write_text(json.dumps({"cases": [{"case_id": "case", "arms": ["passing", "failing"],
        "source_id": "source", "length": 5, "split": "validation"}]}))
    for arm, passed in (("passing", True), ("failing", False)):
        root = raw / "case" / arm
        root.mkdir(parents=True)
        outcome = root / "outcome.json"
        outcome.write_text(json.dumps({"validation": {"passed": passed}}))
        (root / "complete.json").write_text(json.dumps({"manifest_sha256": relaxation.sha(raw_manifest),
            "artifacts": {"outcome.json": relaxation.sha(outcome)}}))
    args = Namespace(raw=raw, raw_manifest=raw_manifest, manifest=tmp_path / "frozen.json")
    relaxation.freeze(args)
    manifest = json.loads(args.manifest.read_text())
    assert [case["raw_passed"] for case in manifest["cases"]] == [True, False]
    assert manifest["protocol"]["solvent"] is False
    assert manifest["validation_policy_changed"] is False
    assert manifest["protocol"]["platform"] == "CUDA"
    with pytest.raises(ValueError, match="must be new"):
        relaxation.freeze(args)
    (raw / "case/failing/outcome.json").write_text("changed")
    args.manifest = tmp_path / "second-freeze.json"
    with pytest.raises(ValueError, match="artifact changed"):
        relaxation.freeze(args)


def test_pair_analysis_keeps_execution_errors_without_calling_them_geometry_regressions(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("a100_relaxation_analysis", SCRIPT.parent / "analyze_a100_relaxation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = []
    for before, after in ((False, True), (True, False), (True, True), (False, False)):
        rows.append({"source_id": "one", "status": "evaluated", "raw_passed": before, "relaxed_passed": after,
            "raw_quality": {"gap_backbone_rmsd_angstrom": 1.0}, "relaxed_quality": {"gap_backbone_rmsd_angstrom": 1.2},
            "raw_failed_gates": [] if before else ["junction"], "relaxed_failed_gates": [] if after else ["steric"],
            "refinement_wall_time_seconds": 2})
    rows.append({"source_id": "two", "status": "execution-error", "raw_passed": True, "relaxed_passed": False})
    summary = module.summarize(rows)
    assert summary["outcome_count"] == 5
    assert summary["evaluated_count"] == 4
    assert summary["execution_error_count"] == 1
    assert summary["raw_accepted"] == 3
    assert summary["relaxed_accepted"] == 2
    assert summary["pass_to_fail"] == 1
    assert summary["fail_to_pass"] == 1
    assert summary["execution_errors_among_raw_accepted"] == 1
    assert summary["gate_transitions_evaluated_only"]["junction"]["resolved"] == 2
    assert module.equivalent({"pairs": (("H", "L"),), "rmsd": 1.0},
        {"pairs": [["H", "L"]], "rmsd": 1.0 + 3e-15})
    assert not module.equivalent({"rmsd": 1.0}, {"rmsd": 1.001})


def test_cuda_force_kernel_failure_prevents_freezing_a_protocol(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "failure-analysis.json").write_text("{}")
    raw_manifest = tmp_path / "raw-manifest.json"
    raw_manifest.write_text('{"cases": []}')
    args = Namespace(raw=raw, raw_manifest=raw_manifest, manifest=tmp_path / "frozen.json")

    def unavailable():
        raise RuntimeError("unsupported PTX")

    monkeypatch.setattr(relaxation, "check_cuda_runtime", unavailable)
    with pytest.raises(RuntimeError, match="unsupported PTX"):
        relaxation.freeze(args)
    assert not args.manifest.exists()
