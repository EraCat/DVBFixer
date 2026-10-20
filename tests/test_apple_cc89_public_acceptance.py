"""The operational harness must exercise immutable replay, not CLI overrides."""

import importlib
import json
from pathlib import Path

import pytest


def test_frozen_public_command_has_no_fasta_or_seed_overrides(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    helper = importlib.import_module("run_apple_cc89_public_acceptance")
    protocol = {"core_python": "/core/venv/bin/python"}
    job = {"tool": "model", "inputs": str(tmp_path), "seeds": [7, 19], "request": str(tmp_path / "request.json")}
    argv = helper.command(protocol, job, tmp_path / "bundle", resume=True, frozen=True)
    assert argv[0] == protocol["core_python"]
    assert "--diffusion-request" in argv and "--diffusion-resume" in argv
    assert "--diffusion-seed" not in argv and "--fasta" not in argv
    normal = helper.command(protocol, job, tmp_path / "bundle")
    assert normal.count("--diffusion-seed") == 2 and "--fasta" in normal
    with pytest.raises(ValueError, match="model CLI"):
        helper.command(protocol, {**job, "tool": "homology"}, tmp_path / "bundle", frozen=True)


def test_public_reports_retain_failed_protocol_and_bind_exact_two_seed_replay():
    research = Path(__file__).resolve().parents[1] / "docs/research"
    failed = json.loads((research / "cc89-public-apple-acceptance-v1.json").read_text())
    execution1 = json.loads((research / "cc89-public-apple-execution-v1.json").read_text())
    execution2 = json.loads((research / "cc89-public-apple-execution-v2.json").read_text())
    accepted = json.loads((research / "cc89-public-apple-acceptance-v2.json").read_text())
    replay = json.loads((research / "cc89-public-apple-frozen-replay-v2.json").read_text())
    assert failed["accepted"] == 0
    assert all(row["execution"]["status"] == "failed" for row in failed["workflows"])
    assert execution2["supersedes_failed_execution_sha256"] == execution1["execution_protocol_sha256"]
    assert execution2["execution_protocol_sha256"] == accepted["execution_protocol_sha256"] == replay["execution_protocol_sha256"]
    expected = {(job["case_id"], seed) for job in execution2["jobs"] for seed in job["seeds"]}
    assert {(row["case_id"], row["seed"]) for row in accepted["rows"]} == expected
    assert len(expected) == accepted["accepted"] == 5
    assert not accepted["reference_rmsd_used"] and not accepted["wider_operational_acceptance"]
    assert replay["exit_code"] == 0 and replay["request_bytes_unchanged"] and replay["bundle_unchanged"]
    assert not replay["backend_invoked"] and replay["poisoned_backend_exit_code_if_invoked"] == 88
    for row in accepted["rows"]:
        assert row["d_ca"] == row["fixed_max_displacement_angstrom"] == row["callback_updates"] == 0
        assert row["denoising_updates"] == 500 and row["outside_gap_atom_records_identical"]
        if row["tool"] == "model":
            assert row["request_sha256"] == replay["request_sha256"]
