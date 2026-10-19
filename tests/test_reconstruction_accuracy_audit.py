"""Audit denominators and frozen-input custody must survive failures/rejects."""

import hashlib
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def audit_module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("audit_clean_reconstruction_accuracy")


def test_accuracy_denominators_keep_rejects_missing_results_and_shared_sources(audit_module):
    def candidate(passed, rmsd, lddt):
        return {"validation_passed": passed, "quality": {"gap_backbone_rmsd_angstrom": rmsd,
            "reference_metrics": {"generated_lddt": {"value": lddt}}}}

    rows = [
        {"source_id": "same", "relaxed": candidate(True, 8.7, 0.5)},
        {"source_id": "same", "relaxed": candidate(False, 2.0, None)},
        {"source_id": "other", "relaxed": None},
    ]
    summary = audit_module.summarize(rows, "relaxed")
    assert summary["planned_attempts"] == 3 and summary["sources"] == 2
    assert summary["available"] == 2 and summary["missing"] == 1
    assert summary["geometry_accepted"] == 1 and summary["geometry_rejected"] == 1
    assert summary["median_backbone_rmsd_all_candidates_angstrom"] == pytest.approx(5.35)
    assert summary["geometry_accepted_backbone_rmsd_bins_angstrom"][">4"] == 1
    assert summary["undefined_generated_lddt_count"] == 1
    assert audit_module.summarize([], "raw")["median_generated_lddt_defined_candidates"] is None


def test_accuracy_audit_rejects_a_different_cohort_before_reading_outcomes(tmp_path, audit_module):
    manifest = tmp_path / "cohort.json"
    protocol = tmp_path / "protocol.json"
    manifest.write_text(json.dumps({"cases": []}))
    protocol.write_text(json.dumps({"cohort_sha256": "0" * 64, "no_outcome_replacement": True}))
    with pytest.raises(ValueError, match="exact frozen"):
        audit_module.audit(manifest, protocol, tmp_path / "missing")


def test_accuracy_audit_rejects_duplicate_case_ids(tmp_path, audit_module):
    manifest = tmp_path / "cohort.json"
    protocol = tmp_path / "protocol.json"
    manifest.write_text(json.dumps({"cases": [{"case_id": "a"}, {"case_id": "a"}]}))
    protocol.write_text(json.dumps({"cohort_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(), "no_outcome_replacement": True}))
    with pytest.raises(ValueError, match="duplicate case"):
        audit_module.audit(manifest, protocol, tmp_path / "missing")


def test_accuracy_audit_detects_modified_archived_request(tmp_path, audit_module):
    manifest = tmp_path / "cohort.json"
    protocol = tmp_path / "protocol.json"
    manifest.write_text(json.dumps({"cases": [{"case_id": "a"}]}))
    protocol.write_text(json.dumps({"cohort_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(), "no_outcome_replacement": True}))
    root = tmp_path / "a"
    root.mkdir()
    (root / "request.json").write_text("changed after archival")
    (root / "complete.json").write_text(json.dumps({"protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest(),
        "artifacts": {"request.json": "0" * 64}}))
    with pytest.raises(ValueError, match="frozen artifact changed"):
        audit_module.audit(manifest, protocol, tmp_path)


def test_self_consistent_archive_cannot_be_swapped_between_frozen_cases(tmp_path, audit_module):
    manifest = tmp_path / "cohort.json"
    protocol = tmp_path / "protocol.json"
    manifest.write_text(json.dumps({"cases": [{"case_id": "a", "artifacts": {"request.json": "0" * 64}}]}))
    protocol.write_text(json.dumps({"cohort_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(), "no_outcome_replacement": True}))
    root = tmp_path / "a"
    root.mkdir()
    payload = b"another case's request"
    (root / "request.json").write_bytes(payload)
    (root / "complete.json").write_text(json.dumps({"protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest(),
        "artifacts": {"request.json": hashlib.sha256(payload).hexdigest()}}))
    with pytest.raises(ValueError, match="frozen artifact changed"):
        audit_module.audit(manifest, protocol, tmp_path)
