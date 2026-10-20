"""Withheld atoms must never remain in the template or conditioning input."""

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dvbfixer.model.diffusion.contract import DiffusionRequest


@pytest.fixture
def materializer(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("materialize_cc89_known_sequence_holdout")


def test_first_hash_window_is_cys_free_internal_and_within_declared_cdr(materializer):
    sequence = "AACAAAAAAAAAAAA"
    permitted = set(range(4, 12))
    index = materializer.choose_start(sequence, 5, "frozen-source", permitted)
    assert index == materializer.choose_start(sequence, 5, "frozen-source", permitted)
    assert index > 0 and index + 5 < len(sequence)
    assert set(range(index, index + 5)) <= permitted
    assert "C" not in sequence[index:index + 5]
    assert materializer.choose_start(sequence, 10, "frozen-source", permitted) is None


def test_homology_materialization_preserves_known_sequence_but_withholds_gap_coordinates(tmp_path, monkeypatch, materializer):
    fixture = Path(__file__).parent / "fixtures/8cz8/8cz8_a_u.pdb"
    source = "".join(line for line in fixture.read_text().splitlines(keepends=True)
        if line.startswith("ATOM  ") and line[21] == "C" and 61 <= int(line[22:26]) <= 73).encode() + b"TER\nEND\n"
    monkeypatch.setattr(materializer, "ROOT", tmp_path)
    directory = tmp_path / "case"
    directory.mkdir()
    record = materializer.write_case(directory, source, {"chain": "C", "start": 4, "length": 5})
    assert record["source_observed_sequences"] == {"C": "SNRFSGSKSGNTA"}
    assert record["known_gap_sequence"] == "SGSKS"
    original_keys = {("C", str(i), "") for i in range(65, 70)}
    materializer.assert_mask_only(source, (directory / "masked-template.pdb").read_bytes(), original_keys)
    request = DiffusionRequest.from_json((directory / "requests/cc89-seed19.json").read_text())
    assert request.seeds == (19,)
    assert request.target_sequences[0].sequence == "SNRFSGSKSGNTA"
    assert (request.gaps[0].target_interval.start, request.gaps[0].target_interval.stop) == (4, 9)
    dense_keys = {(r.chain, r.residue_number, r.insertion_code) for r in request.gaps[0].generated_residues}
    masked = (directory / "input/normalized.pdb").read_bytes()
    materializer.assert_mask_only((directory / "reference.pdb").read_bytes(), masked, dense_keys)
    with pytest.raises(ValueError, match="source-minus-declared-gap"):
        materializer.assert_mask_only((directory / "reference.pdb").read_bytes(),
            (directory / "reference.pdb").read_bytes(), dense_keys)


def test_sampling_worker_rejects_a_visible_withheld_reference_before_importing_model(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    runner = importlib.import_module("run_cc89_known_sequence_holdout")
    (tmp_path / "reference.pdb").write_text("withheld coordinates")
    with pytest.raises(ValueError, match="must not be present"):
        runner.worker(SimpleNamespace(workspace=tmp_path))


def test_resume_keeps_a_terminal_failure_without_another_sampler_launch(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    runner = importlib.import_module("run_cc89_known_sequence_holdout")
    cohort = tmp_path / "cohort"
    (cohort / "case").mkdir(parents=True)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"cases": [{"case_id": "case", "source_id": "source", "length": 5,
        "stratum": "general-protein", "artifacts": {}}]}))
    protocol = tmp_path / "protocol.json"
    job = {"case_id": "case", "seed": 7}
    protocol.write_text(json.dumps({"status": "frozen-before-known-sequence-holdout-execution", "manifest_sha256": runner.sha(manifest),
        "code_sha256": {}, "jobs": {"raw": [job]}}))
    output = tmp_path / "outcomes"
    destination = output / "raw/case/seed7"
    destination.mkdir(parents=True)
    outcome = destination / "outcome.json"
    outcome.write_text(json.dumps({"status": "execution-error", "message": "original failure"}))
    (destination / "complete.json").write_text(json.dumps({"protocol_sha256": runner.sha(protocol), "raw_complete_sha256": None,
        "job": job, "artifacts": {"outcome.json": runner.sha(outcome)}}))
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **kw: pytest.fail("terminal failure must not trigger resampling"))
    runner.run(SimpleNamespace(protocol=protocol, manifest=manifest, cohort=cohort, output=output, stage="raw", max_new=0))
    assert json.loads((output / "raw-report.json").read_text())["complete"] is True
    assert json.loads(outcome.read_text())["message"] == "original failure"


def test_holdout_summary_keeps_guarded_and_pending_outcomes_in_denominator(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    analyzer = importlib.import_module("analyze_cc89_known_sequence_holdout")
    rows = [
        {"source_id": "same", "status": "evaluated", "validation": {"passed": True, "hard_gate_failures": []},
         "quality": {"gap_backbone_rmsd_angstrom": 4.1}},
        {"source_id": "same", "status": "evaluated", "validation": {"passed": False, "hard_gate_failures": ["junction"]},
         "quality": {"gap_backbone_rmsd_angstrom": 8.0}},
        {"source_id": "other", "status": "guarded-chirality-rejection"},
        {"source_id": "other", "status": "pending"},
    ]
    result = analyzer.summarize(rows)
    assert result["planned_outcomes"] == 4 and result["sources"] == 2
    assert result["strict_accepted"] == 1 and result["evaluated"] == 2
    assert result["statuses"]["pending"] == 1
    assert result["accepted_rmsd_bins_angstrom"][">4"] == 1


def test_frozen_source_snapshot_copies_code_but_never_checkpoint_weights(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    analyzer = importlib.import_module("analyze_cc89_known_sequence_holdout")
    monkeypatch.setattr(analyzer, "ROOT", tmp_path)
    source = tmp_path / "producer.py"
    source.write_text("# frozen source\n")
    (tmp_path / "checkpoint.pth").write_bytes(b"not distributable model weights")
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps({"code_sha256": {"producer.py": analyzer.sha(source)}, "checkpoint_sha256": "a" * 64}))
    destination = tmp_path / "snapshot"
    analyzer.snapshot(SimpleNamespace(protocol=protocol, output=destination))
    assert (destination / "producer.py").read_bytes() == source.read_bytes()
    assert not (destination / "checkpoint.pth").exists()
    assert json.loads((destination / "snapshot.json").read_text())["checkpoint_copied"] is False
