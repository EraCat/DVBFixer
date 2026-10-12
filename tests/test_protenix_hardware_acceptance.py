"""Portable verification of the manual NVIDIA smoke evidence gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from dvbfixer.model.diffusion.contract import AtomIdentity, ResidueIdentity, RunnerResourceMetrics
from dvbfixer.model.diffusion.trace import build_sampler_trace

ROOT = Path(__file__).resolve().parents[1]


def _checker(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "hardware_checker", ROOT / "scripts/check_protenix_hardware_acceptance.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "EXPECTED_PDB_SHA256", hashlib.sha256(b"test pdb").hexdigest())
    return module


def _bundle(path: Path, *, problem: str | None = None) -> None:
    path.mkdir()
    lock_path = ROOT / "deploy/protenix-v1/profile-lock.json"
    lock = json.loads(lock_path.read_text())
    atom = AtomIdentity("C", "1", "", "CA")
    trace = build_sampler_trace(
        profile="protenix-v1-cuda",
        engine_repository="https://github.com/bytedance/Protenix",
        engine_revision=lock["protenix_revision"],
        patch_identity="sha256:" + lock["patch_sha256"],
        atom_order=(atom,), fixed_atoms=(atom,), device="cuda:0",
        fallback_disabled=True, denoising_update_count=200,
        projection_errors_angstrom=(0.0,) * 200,
        final_fixed_coordinate_restoration=False,
        resource_metrics=RunnerResourceMetrics(
            wall_time_seconds=10.0, peak_ram_bytes=100, peak_vram_bytes=100,
        ),
    )
    trace = replace(
        trace, refinement_mode="localized-openmm-boundary-refinement",
        localized_refinement_residues=(ResidueIdentity("C", "1"),),
    )
    raw_trace = json.loads(trace.to_json())
    if problem == "cpu":
        raw_trace["device"] = "cpu"
    elif problem == "fallback":
        raw_trace["fallback_disabled"] = False
    elif problem == "callbacks":
        raw_trace["steps"] = raw_trace["steps"][:199]
        raw_trace["callback_update_count"] = 199
    elif problem == "refinement":
        raw_trace["refinement_mode"] = "none"
        raw_trace["localized_refinement_residues"] = []
    provenance = {
        "backend_provenance": {
            "checkpoint_sha256": "0" * 64 if problem == "checkpoint" else lock["checkpoint"]["sha256"],
            "engine_revision": lock["protenix_revision"],
            "environment_identity": "linux-amd64;profile-lock-sha256=" + hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        },
        "validation_summary": {"passed": True, "metrics": [
            {"name": name, "value": 0.0} for name in (
                "fixed-heavy-atom-rmsd", "fixed-heavy-atom-max-displacement", "detectable-d-ca",
            )
        ]},
        "request_sha256": "b" * 64 if problem == "request" else "a" * 64,
    }
    artifacts = {}
    for label, payload in (
        ("pdb", b"test pdb"), ("dat", b"{}"),
        ("sampler_trace", json.dumps(raw_trace).encode()),
        ("provenance", json.dumps(provenance).encode()),
    ):
        artifact = path / label
        artifact.write_bytes(payload)
        artifacts[label] = {"path": label, "sha256": hashlib.sha256(payload).hexdigest()}
    index = {
        "schema_version": 2, "requested_profile": "protenix-v1-cuda", "status": "success",
        "candidates": [{
            "candidate_id": "candidate", "seed": 7, "validation_passed": True,
            "hard_gate_failures": [], **artifacts,
        }],
    }
    (path / "bundle.json").write_text(json.dumps(index))


def test_repeat_evidence_is_portable_and_bounded(tmp_path, monkeypatch):
    checker = _checker(monkeypatch)
    first, repeat = tmp_path / "first", tmp_path / "repeat"
    _bundle(first)
    _bundle(repeat)
    report = checker.verify_repeat(first, repeat)
    assert report["status"] == "passed"
    assert report["full_cohort_acceptance"] is False
    assert str(tmp_path) not in json.dumps(report)


@pytest.mark.parametrize("problem", ["cpu", "fallback", "callbacks", "refinement", "checkpoint", "request"])
def test_repeat_rejects_incomplete_or_incompatible_evidence(tmp_path, monkeypatch, problem):
    checker = _checker(monkeypatch)
    first, repeat = tmp_path / "first", tmp_path / "repeat"
    _bundle(first)
    _bundle(repeat, problem=problem)
    with pytest.raises(checker.PublicCohortError):
        checker.verify_repeat(first, repeat)


def test_same_bundle_cannot_be_an_independent_repeat(tmp_path, monkeypatch):
    checker = _checker(monkeypatch)
    with pytest.raises(checker.PublicCohortError, match="must be distinct"):
        checker.verify_repeat(tmp_path, tmp_path)
