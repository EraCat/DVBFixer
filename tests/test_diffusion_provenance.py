"""Tests for separate, credential-free diffusion provenance manifests."""

from __future__ import annotations

import json
from pathlib import Path

from dvbfixer import __version__
from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    ArtifactReference,
    AtomIdentity,
    BackendOption,
    BackendProvenance,
    DiffusionCandidate,
    DiffusionRequest,
    GapRegion,
    ResidueIdentity,
    RunnerDiagnostics,
    SequencePlacement,
    TargetInterval,
    TargetSequence,
    ValidationSummary,
)
from dvbfixer.model.diffusion.provenance import (
    DIFFUSION_PROVENANCE_SCHEMA_VERSION,
    PublicationArtifact,
    build_provenance_manifest,
)

DIGEST = "a" * 64


def _request() -> DiffusionRequest:
    left = ResidueIdentity("D", "10")
    generated = tuple(
        ResidueIdentity("D", str(number))
        for number in range(11, 14)
    )
    right = ResidueIdentity("D", "14")
    return DiffusionRequest(
        schema_version=DIFFUSION_SCHEMA_VERSION,
        normalized_pdb=ArtifactReference("input/normalized.pdb", DIGEST),
        target_sequences=(TargetSequence("D", "FSGSK"),),
        sequence_placements=(
            SequencePlacement(
                chain="D",
                target_length=5,
                observed_target_indices=(0, 4),
                observed_residues=(left, right),
            ),
        ),
        gaps=(
            GapRegion(
                chain="D",
                target_interval=TargetInterval(1, 4),
                left_anchor=left,
                right_anchor=right,
                generated_residues=generated,
                movable_junction_residues=(left, *generated, right),
            ),
        ),
        fixed_atoms=(
            AtomIdentity("D", "10", "", "CA"),
            AtomIdentity("D", "14", "", "CA"),
        ),
        generated_atoms=tuple(
            AtomIdentity("D", residue.residue_number, "", "CA")
            for residue in generated
        ),
        retained_explicit_links=(),
        candidate_count=1,
        seeds=(7,),
        backend_options=(BackendOption("profile", "protenix-v1-cuda"),),
    )


def test_manifest_records_auditable_evidence_without_raw_diagnostics(
    tmp_path: Path,
) -> None:
    request = _request()
    candidate = DiffusionCandidate(
        candidate_id="candidate-0001",
        seed=7,
        coordinate_artifact=ArtifactReference("candidate.pdb", "b" * 64),
        sampler_trace_artifact=ArtifactReference("candidate.trace.json", "c" * 64),
        generated_atoms=request.generated_atoms,
        generated_residues=request.gaps[0].generated_residues,
        raw_backend_score=0.75,
        score_provenance="engine:score-v1",
    )
    backend = BackendProvenance(
        backend="test",
        runner_protocol_version=2,
        engine_repository="https://example.invalid/engine",
        engine_revision="pinned",
        source_license="BSD-3-Clause",
        device="cpu",
        deterministic_algorithms=True,
    )
    manifest = build_provenance_manifest(
        request,
        candidate,
        ValidationSummary(passed=True),
        backend,
        RunnerDiagnostics(
            exit_code=0,
            timed_out=False,
            stdout="secret-looking-token",
            stderr="private path",
        ),
        (
            PublicationArtifact("pdb", "candidate.pdb", "b" * 64),
            PublicationArtifact("dat", "candidate.dat", "c" * 64),
        ),
        repository_root=tmp_path,
    )

    payload = json.loads(manifest.to_json())

    assert payload["schema_version"] == DIFFUSION_PROVENANCE_SCHEMA_VERSION
    assert payload["diffusion_contract_schema_version"] == DIFFUSION_SCHEMA_VERSION
    assert payload["dvbfixer"] == {
        "version": __version__,
        "commit": "unknown",
    }
    assert payload["candidate"]["seed"] == 7
    assert payload["requested_profile"] == "protenix-v1-cuda"
    assert payload["profile_status"] == "production-wrapper-frozen-cohort-replayed-deployment-pending"
    assert payload["profile_evidence_labels"] == [
        "experimental",
        "confirmatory-selected-in-frozen-scope",
        "public-cli-frozen-cohort-replayed",
    ]
    assert payload["training_membership_status"] == (
        "temporally-eligible-frozen-cohort"
    )
    assert payload["runner_diagnostics"] == {
        "exit_code": 0,
        "timed_out": False,
        "stdout_bytes": len("secret-looking-token"),
        "stderr_bytes": len("private path"),
    }
    encoded = manifest.to_json()
    assert "secret-looking-token" not in encoded
    assert "private path" not in encoded
    assert payload["request_sha256"]


def test_manifest_uses_current_repository_commit() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    request = _request()
    candidate = DiffusionCandidate(
        candidate_id="candidate-0001",
        seed=7,
        coordinate_artifact=ArtifactReference("candidate.pdb", "b" * 64),
        sampler_trace_artifact=ArtifactReference("candidate.trace.json", "c" * 64),
        generated_atoms=request.generated_atoms,
        generated_residues=request.gaps[0].generated_residues,
        raw_backend_score=None,
        score_provenance="none",
    )

    manifest = build_provenance_manifest(
        request,
        candidate,
        ValidationSummary(passed=True),
        BackendProvenance(
            backend="test",
            runner_protocol_version=2,
            engine_repository="builtin://test",
            engine_revision="test",
        ),
        RunnerDiagnostics(exit_code=0, timed_out=False),
        (PublicationArtifact("pdb", "candidate.pdb", "b" * 64),),
        repository_root=repository_root,
    )

    assert len(manifest.dvbfixer_commit) == 40
    int(manifest.dvbfixer_commit, 16)
