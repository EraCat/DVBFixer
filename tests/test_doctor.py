import json
from pathlib import Path

import pytest

from dvbfixer.doctor import collect_capabilities, main, parse_args
from dvbfixer.model.diffusion.contract import DIFFUSION_SCHEMA_VERSION
from dvbfixer.model.diffusion.preflight import (
    DIFFUSION_PROFILES,
    RunnerPreflightFacts,
    RunnerPreflightReport,
)
from dvbfixer.model.diffusion.runner import DIFFUSION_RUNNER_PROTOCOL_VERSION


def test_capability_report_has_stable_sections():
    report = collect_capabilities()
    assert set(report) == {"python_packages", "executables", "openmm_platforms", "diffusion"}
    assert "OpenMM" in report["python_packages"]
    assert report["python_packages"]["Gemmi"]["available"] is True
    assert report["python_packages"]["Open Babel Python"]["available"] is True
    assert "tleap" in report["executables"]
    assert "MAFFT" in report["executables"]
    assert "MUSCLE" in report["executables"]
    assert "Clustal Omega" in report["executables"]
    assert set(report["diffusion"]) == {"profiles", "selected_profile"}
    assert report["diffusion"]["selected_profile"] is None


def test_static_diffusion_profiles_publish_required_labels_and_metadata():
    profiles = collect_capabilities()["diffusion"]["profiles"]
    assert profiles["protenix-v1-cuda"]["evidence_labels"] == [
        "experimental",
        "confirmatory-selected-in-frozen-scope",
        "public-cli-frozen-cohort-replayed",
    ]
    assert (
        profiles["protenix-v1-cuda"]["status"]
        == "production-wrapper-frozen-cohort-replayed-deployment-pending"
    )
    assert profiles["protpardelle-1c-mps"]["evidence_labels"] == [
        "experimental",
        "descriptive-evidence",
        "training-membership-unresolved",
        "no-per-step-reinjection",
    ]
    assert profiles["protpardelle-1c-mps"]["status"] == (
        "production-wrapper-frozen-cohort-accepted"
    )
    required = {
        "profile", "status", "evidence_labels", "engine", "source_revision",
        "patch_identity", "expected_checkpoint_sha256", "sampling_platform",
        "refinement_platform", "runner_protocol_version", "contract_schema_version",
        "fallback_policy", "training_membership_status",
    }
    assert all(set(profile) == required for profile in profiles.values())


def test_selected_profile_omissions_are_structured_issues():
    selected = collect_capabilities(diffusion_profile="protenix-v1-cuda")["diffusion"][
        "selected_profile"
    ]
    assert selected["passed"] is False
    assert {issue["code"] for issue in selected["issues"]} == {"missing-runner"}


def test_successful_handshake_is_sanitized(
    tmp_path: Path,
    monkeypatch,
):
    runner = tmp_path / "runner"
    checkpoint = tmp_path / "private-checkpoint.pt"
    runner.write_text("#!/bin/sh\nexit 0\n")
    runner.chmod(0o755)
    checkpoint.write_bytes(b"secret checkpoint content")
    profile = DIFFUSION_PROFILES["protenix-v1-cuda"]
    mocked = RunnerPreflightReport(
        profile=profile.profile,
        runner_protocol_version=DIFFUSION_RUNNER_PROTOCOL_VERSION,
        contract_schema_version=DIFFUSION_SCHEMA_VERSION,
        facts=RunnerPreflightFacts(
            engine_revision=profile.source_revision,
            patch_identity=profile.patch_identity,
            checkpoint_sha256=profile.expected_checkpoint_sha256,
            fallback_disabled=True,
            refinement_platform=profile.refinement_platform,
        ),
    )
    monkeypatch.setattr("dvbfixer.doctor.invoke_runner_preflight", lambda **_kwargs: mocked)

    report = collect_capabilities(
        diffusion_profile=profile.profile,
        diffusion_runner=str(runner),
        diffusion_checkpoint=str(checkpoint),
    )
    rendered = json.dumps(report)

    assert report["diffusion"]["selected_profile"]["passed"] is True
    assert str(runner) not in rendered
    assert str(checkpoint) not in rendered
    assert "secret checkpoint content" not in rendered
    assert "stdout" not in rendered and "stderr" not in rendered


def test_json_output_is_machine_readable(capsys):
    main(["--format", "json"])
    assert '"python_packages"' in capsys.readouterr().out


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf"])
def test_diffusion_timeout_must_be_positive_and_finite(timeout):
    with pytest.raises(SystemExit):
        parse_args(["--diffusion-timeout", timeout])


def test_doctor_accepts_optional_diffusion_model():
    assert parse_args(["--diffusion-model", "protpardelle"]).diffusion_model == "protpardelle"
