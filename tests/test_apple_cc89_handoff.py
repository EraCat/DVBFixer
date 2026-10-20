"""Portable Apple controls preserve sources and withhold gap coordinates."""

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dvbfixer.model.diffusion.contract import DiffusionRequest


def test_fresh_clone_controls_need_no_linux_archives_or_checkpoint(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    helper = importlib.import_module("prepare_apple_cc89_handoff")
    masking = importlib.import_module("materialize_cc89_known_sequence_holdout")
    output = tmp_path / "controls"
    helper.materialize(output)
    report = json.loads((output / "inputs.json").read_text())
    assert len(report["requests"]) == 8
    assert report["inference_executed"] is False
    assert report["corrected_mps_port_status"] == "research-mode-requires-explicit-opt-in"
    for row in report["requests"]:
        directory = output / row["case_id"]
        request = DiffusionRequest.from_json((directory / f"request-seed{row['seed']}.json").read_text())
        generated = {(r.chain, r.residue_number, r.insertion_code) for gap in request.gaps for r in gap.generated_residues}
        assert not (directory / "reference.pdb").exists()
        reference = (output / "evaluation" / row["case_id"] / "reference.pdb").read_bytes()
        masking.assert_mask_only(reference, (directory / request.normalized_pdb.path).read_bytes(), generated)
        masking.assert_mask_only(reference, (directory / "masked-template.pdb").read_bytes(), generated)
        assert row["request_sha256"] == helper.sha(directory / f"request-seed{row['seed']}.json")
        assert any(option.name == "profile" and option.value == "protpardelle-1c-mps-source-physical-research-v1"
            for option in request.backend_options)
    pilot = importlib.import_module("run_apple_cc89_pilot")
    workspace = tmp_path / "worker"
    pilot.prepare_workspace(workspace, {
        "request": str(directory / f"request-seed{row['seed']}.json"),
        "source": str(directory / request.normalized_pdb.path),
    })
    assert {p.relative_to(workspace).as_posix() for p in workspace.rglob("*") if p.is_file()} == {
        "request.json", request.normalized_pdb.path,
    }
    assert (workspace / request.normalized_pdb.path).read_bytes() == (directory / request.normalized_pdb.path).read_bytes()


def _pilot(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("run_apple_cc89_pilot")


def test_pilot_environment_disables_fallback_and_clears_tuning(monkeypatch):
    pilot = _pilot(monkeypatch)
    monkeypatch.setenv("PYTORCH_MPS_FAST_MATH", "1")
    monkeypatch.setenv("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    protocol = {"checkpoint": "/private/weights/cc89.pth", "engine_root": "/private/engine"}
    env = pilot.environment(protocol)
    assert env["PYTORCH_ENABLE_MPS_FALLBACK"] == "0"
    assert env["OPENMM_CPU_THREADS"] == "1"
    assert not any(key in env for key in pilot.MPS_TUNING)
    assert env["PYTHONPATH"].split(":")[0] == "/private/engine/src"


def test_pilot_archives_failure_and_resume_never_resamples(tmp_path, monkeypatch):
    pilot = _pilot(monkeypatch)
    job = {"case_id": "one", "seed": 7}
    protocol = tmp_path / "protocol.json"
    pilot.dump_new(protocol, {"sha256": {}, "jobs": [job]})
    calls = []

    def prepare(workspace, _job):
        workspace.mkdir(parents=True)

    def stage(_protocol, _path, workspace, stage):
        calls.append(stage)
        (workspace / "raw.log").write_text("terminal failure\n")
        return {"status": "failed", "exit_code": 1}

    monkeypatch.setattr(pilot, "prepare_workspace", prepare)
    monkeypatch.setattr(pilot, "run_stage", stage)
    args = SimpleNamespace(protocol=protocol, output=tmp_path / "outputs", stage="probe")
    pilot.execute(args)
    pilot.execute(args)
    assert calls == ["probe"]
    (args.output / "one/seed7/raw.log").write_text("tampered")
    with pytest.raises(ValueError, match="archive identity"):
        pilot.execute(args)


def test_pilot_refuses_incomplete_archive_instead_of_replacing_it(tmp_path, monkeypatch):
    pilot = _pilot(monkeypatch)
    protocol = tmp_path / "protocol.json"
    pilot.dump_new(protocol, {"sha256": {}, "jobs": [{"case_id": "one", "seed": 7}]})
    (tmp_path / "outputs/one/seed7").mkdir(parents=True)
    with pytest.raises(ValueError, match="interrupted outcome remains terminal"):
        pilot.execute(SimpleNamespace(protocol=protocol, output=tmp_path / "outputs", stage="probe"))


def test_tracked_pilot_report_covers_all_frozen_masks_and_both_seeds():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "tests/fixtures/cc89_apple_handoff/manifest.json").read_text())
    execution = json.loads((root / "docs/research/cc89-apple-corrected-execution-v1.json").read_text())
    report = json.loads((root / "docs/research/cc89-apple-corrected-pilot-v1.json").read_text())
    expected = {(case["case_id"], seed) for case in manifest["cases"] for seed in manifest["seeds"]}
    assert {(job["case_id"], job["seed"]) for job in execution["jobs"]} == expected
    assert {(row["case_id"], row["seed"]) for row in report["rows"]} == expected
    assert execution["execution_protocol_sha256"] == report["protocol_sha256"]
    assert report["accepted"] == report["planned_outcomes"] == 8
    assert execution["public_promotion"] is report["public_promotion"] is False
    assert report["reference_rmsd_used"] is False
    for row in report["rows"]:
        assert row["profile"] == execution["profile"]
        assert row["validation"]["passed"]
        assert row["outside_gap_atom_records_identical"]
        assert not row["postprocessing_failures"]
        assert row["dat_generated_atom_count"] > 0
        metrics = {metric["name"]: metric["value"] for metric in row["validation"]["metrics"]}
        assert metrics["detectable-d-ca"] == metrics["fixed-heavy-atom-max-displacement"] == 0
