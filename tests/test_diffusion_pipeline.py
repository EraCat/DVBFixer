"""Tests for fail-closed diffusion orchestration and one-rename publication."""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

import dvbfixer.model.diffusion.pipeline as diffusion_pipeline
from dvbfixer.ffutils.dat import DatRecord
from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    ArtifactReference,
    AtomIdentity,
    BackendOption,
    BackendProvenance,
    DiffusionCandidate,
    DiffusionRequest,
    DiffusionResult,
    DiffusionStatus,
    GapRegion,
    ResidueIdentity,
    RunnerDiagnostics,
    SequencePlacement,
    TargetInterval,
    TargetSequence,
    ValidationSummary,
)
from dvbfixer.model.diffusion.pipeline import (
    DiffusionPipelineError,
    publish_diffusion_bundle,
    run_diffusion_pipeline,
)
from dvbfixer.model.diffusion.runner import DiffusionRunnerError
from dvbfixer.model.diffusion.trace import build_sampler_trace

FIXTURE = Path(__file__).parent / "fixtures" / "8cz8" / "8cz8_a_u.pdb"
GENERATED_NUMBERS = tuple(str(number) for number in range(65, 70))


def test_lazy_package_reexports_preserve_execution_api() -> None:
    import dvbfixer.model.diffusion as diffusion

    exports = {
        "pipeline": (
            "BUNDLE_INDEX_SCHEMA_VERSION", "DiffusionPipelineError",
            "DiffusionPipelineOutcome", "publish_diffusion_bundle", "run_diffusion_pipeline",
        ),
        "scope": ("DiffusionScopeError", "ScopeAdmission", "assess_diffusion_scope"),
        "validate": (
            "CandidateValidation", "DiffusionValidationError", "ValidationThresholds",
            "build_validated_result", "validate_runner_result",
        ),
    }
    for module_name, names in exports.items():
        module = importlib.import_module(f"dvbfixer.model.diffusion.{module_name}")
        for name in names:
            assert name in diffusion.__all__
            assert getattr(diffusion, name) is getattr(module, name)
    with pytest.raises(AttributeError, match="has no attribute"):
        getattr(diffusion, "not_an_export")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atom_identity(line: str) -> AtomIdentity:
    return AtomIdentity(
        line[21],
        line[22:26].strip(),
        line[26].strip(),
        line[12:16].strip(),
    )


def _residue_identity(line: str) -> ResidueIdentity:
    return ResidueIdentity(line[21], line[22:26].strip(), line[26].strip())


def _source_candidate_request() -> tuple[bytes, bytes, DiffusionRequest]:
    lines = FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True)
    selected_numbers = {str(number) for number in range(61, 74)}
    selected_lines = [
        line
        for line in lines
        if line.startswith("ATOM  ")
        and line[21] == "C"
        and line[22:26].strip() in selected_numbers
    ]
    generated_residues = {
        ResidueIdentity("C", number)
        for number in GENERATED_NUMBERS
    }
    source = (
        "".join(
            line
            for line in selected_lines
            if _residue_identity(line) not in generated_residues
        )
        + "TER\nEND\n"
    ).encode()
    candidate = ("".join(selected_lines) + "TER\nEND\n").encode()
    observed: list[ResidueIdentity] = []
    seen: set[ResidueIdentity] = set()
    for line in source.decode().splitlines():
        if not line.startswith("ATOM  "):
            continue
        residue = _residue_identity(line)
        if residue not in seen:
            observed.append(residue)
            seen.add(residue)
    fixed_atoms = tuple(
        _atom_identity(line)
        for line in source.decode().splitlines()
        if line.startswith("ATOM  ")
        and line[76:78].strip().upper() != "H"
    )
    generated_atoms = tuple(
        _atom_identity(line)
        for line in selected_lines
        if _residue_identity(line) in generated_residues
        and line[76:78].strip().upper() != "H"
    )
    left = ResidueIdentity("C", "64")
    generated = tuple(
        ResidueIdentity("C", number)
        for number in GENERATED_NUMBERS
    )
    right = ResidueIdentity("C", "70")
    request = DiffusionRequest(
        schema_version=DIFFUSION_SCHEMA_VERSION,
        normalized_pdb=ArtifactReference("input/normalized.pdb", _digest(source)),
        target_sequences=(TargetSequence("C", "SNRFSGSKSGNTA"),),
        sequence_placements=(
            SequencePlacement(
                chain="C",
                target_length=13,
                observed_target_indices=(0, 1, 2, 3, 9, 10, 11, 12),
                observed_residues=tuple(observed),
            ),
        ),
        gaps=(
            GapRegion(
                chain="C",
                target_interval=TargetInterval(4, 9),
                left_anchor=left,
                right_anchor=right,
                generated_residues=generated,
                movable_junction_residues=(left, *generated, right),
            ),
        ),
        fixed_atoms=fixed_atoms,
        generated_atoms=generated_atoms,
        retained_explicit_links=(),
        candidate_count=1,
        seeds=(7,),
        backend_options=(BackendOption("profile", "test"),),
    )
    return source, candidate, request


def _validated_result(
    request: DiffusionRequest,
    candidate_bytes: bytes,
) -> DiffusionResult:
    trace_bytes = _trace_bytes(request)
    candidate = DiffusionCandidate(
        candidate_id="candidate-0001",
        seed=7,
        coordinate_artifact=ArtifactReference(
            "candidates/candidate-0001.pdb",
            _digest(candidate_bytes),
        ),
        sampler_trace_artifact=ArtifactReference(
            "candidates/candidate-0001.trace.json",
            _digest(trace_bytes),
        ),
        generated_atoms=request.generated_atoms,
        generated_residues=request.gaps[0].generated_residues,
        raw_backend_score=0.75,
        score_provenance="test-score",
    )
    return DiffusionResult(
        schema_version=DIFFUSION_SCHEMA_VERSION,
        status=DiffusionStatus.SUCCESS,
        candidates=(candidate,),
        validation_summaries=(ValidationSummary(passed=True),),
        runner_diagnostics=RunnerDiagnostics(exit_code=0, timed_out=False),
        backend_provenance=BackendProvenance(
            backend="test",
            runner_protocol_version=2,
            engine_repository="builtin://test",
            engine_revision="test",
            device="cpu",
        ),
    )


def test_publication_marks_validation_failed_candidate_as_rejected(
    tmp_path: Path,
) -> None:
    _source, candidate_bytes, request = _source_candidate_request()
    result = _validated_result(request, candidate_bytes)
    rejected = replace(
        result,
        status=DiffusionStatus.FAILED,
        validation_summaries=(ValidationSummary(
            passed=False,
            hard_gate_failures=("severe-steric-overlap",),
        ),),
        message="candidate requires inspection",
    )
    workspace = _workspace(tmp_path, candidate_bytes)
    destination = tmp_path / "rejected"

    publish_diffusion_bundle(
        request,
        rejected,
        workspace=workspace,
        destination_bundle=destination,
    )

    bundle = json.loads((destination / "bundle.json").read_text(encoding="utf-8"))
    assert bundle["status"] == "validation_failed"
    assert bundle["candidates"][0]["validation_passed"] is False
    assert bundle["candidates"][0]["hard_gate_failures"] == [
        "severe-steric-overlap"
    ]
def _workspace(
    tmp_path: Path,
    candidate_bytes: bytes,
) -> Path:
    _source, _candidate, request = _source_candidate_request()
    workspace = tmp_path / "workspace"
    candidate_path = workspace / "candidates" / "candidate-0001.pdb"
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_bytes(candidate_bytes)
    (workspace / "candidates" / "candidate-0001.trace.json").write_bytes(
        _trace_bytes(request)
    )
    return workspace


def _trace_bytes(
    request: DiffusionRequest,
    *,
    fixed_atoms: tuple[AtomIdentity, ...] | None = None,
) -> bytes:
    active_fixed_atoms = request.fixed_atoms if fixed_atoms is None else fixed_atoms
    return build_sampler_trace(
        profile="test",
        engine_repository="builtin://test",
        engine_revision="test",
        patch_identity="none",
        atom_order=(*request.fixed_atoms, *request.generated_atoms),
        fixed_atoms=active_fixed_atoms,
        device="cpu",
        fallback_disabled=True,
        denoising_update_count=0,
        final_fixed_coordinate_restoration=True,
    ).to_json().encode()


def test_runner_failure_cleans_private_workspace_and_publishes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _candidate, request = _source_candidate_request()
    source_root = tmp_path / "source"
    source_path = source_root / "input" / "normalized.pdb"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(source)
    destination = tmp_path / "published"

    def fail_runner(*_args: object, **_kwargs: object) -> None:
        raise DiffusionRunnerError("injected runner failure")

    monkeypatch.setattr(diffusion_pipeline, "run_diffusion_runner", fail_runner)

    with pytest.raises(DiffusionRunnerError, match="injected runner failure"):
        run_diffusion_pipeline(
            request,
            ("unused-runner",),
            source_root=source_root,
            work_parent=tmp_path,
            destination_bundle=destination,
        )

    assert not destination.exists()
    assert not list(tmp_path.glob(".dvbfixer-diffusion-run.*"))


def test_publish_bundle_writes_candidate_matched_dat_and_manifest(
    tmp_path: Path,
) -> None:
    _source, candidate_bytes, request = _source_candidate_request()
    result = _validated_result(request, candidate_bytes)
    workspace = _workspace(tmp_path, candidate_bytes)
    destination = tmp_path / "published"

    published = publish_diffusion_bundle(
        request,
        result,
        workspace=workspace,
        destination_bundle=destination,
        repository_root=Path(__file__).resolve().parents[1],
    )

    assert published == destination
    assert sorted(path.name for path in destination.iterdir()) == [
        "bundle.json",
        "candidate-0001.dat",
        "candidate-0001.diffusion.json",
        "candidate-0001.pdb",
        "candidate-0001.sampler-trace.json",
    ]
    dat = DatRecord.load(destination / "candidate-0001.dat")
    assert dat.added_keys() == {
        (
            atom.chain,
            atom.residue_number,
            atom.insertion_code,
            atom.atom_name,
        )
        for atom in request.generated_atoms
    }
    bundle = json.loads((destination / "bundle.json").read_text())
    manifest = json.loads(
        (destination / "candidate-0001.diffusion.json").read_text()
    )
    assert bundle["candidates"][0]["seed"] == 7
    assert bundle["requested_profile"] == "test"
    assert manifest["candidate"]["seed"] == 7
    assert manifest["candidate"]["sampler_trace_artifact"] == {
        "path": "candidate-0001.sampler-trace.json",
        "sha256": _digest(_trace_bytes(request)),
    }
    assert manifest["artifacts"][0]["sha256"] == _digest(candidate_bytes)
    assert bundle["candidates"][0]["sampler_trace"]["sha256"] == _digest(
        _trace_bytes(request)
    )
    assert any(
        artifact["role"] == "sampler-trace"
        and artifact["sha256"] == _digest(_trace_bytes(request))
        for artifact in manifest["artifacts"]
    )


@pytest.mark.parametrize("malformed", (True, False))
def test_publication_rejects_invalid_sampler_trace_before_staging(
    tmp_path: Path,
    malformed: bool,
) -> None:
    _source, candidate_bytes, request = _source_candidate_request()
    result = _validated_result(request, candidate_bytes)
    workspace = _workspace(tmp_path, candidate_bytes)
    trace_path = workspace / "candidates" / "candidate-0001.trace.json"
    trace_bytes = (
        b"not-json"
        if malformed
        else _trace_bytes(request, fixed_atoms=request.fixed_atoms[:-1])
    )
    trace_path.write_bytes(trace_bytes)
    candidate = replace(
        result.candidates[0],
        sampler_trace_artifact=ArtifactReference(
            "candidates/candidate-0001.trace.json",
            _digest(trace_bytes),
        ),
    )
    result = replace(result, candidates=(candidate,))
    destination = tmp_path / ("malformed-trace" if malformed else "mismatched-trace")

    with pytest.raises(
        DiffusionPipelineError,
        match="invalid sampler trace",
    ):
        publish_diffusion_bundle(
            request,
            result,
            workspace=workspace,
            destination_bundle=destination,
        )

    assert not destination.exists()
    assert not list(tmp_path.glob(f".{destination.name}.*.tmp"))


def test_publication_rejects_existing_destination_and_cleans_staging(
    tmp_path: Path,
) -> None:
    _source, candidate_bytes, request = _source_candidate_request()
    result = _validated_result(request, candidate_bytes)
    workspace = _workspace(tmp_path, candidate_bytes)
    destination = tmp_path / "published"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("keep")

    with pytest.raises(DiffusionPipelineError, match="already exists"):
        publish_diffusion_bundle(
            request,
            result,
            workspace=workspace,
            destination_bundle=destination,
        )

    assert marker.read_text() == "keep"
    assert not list(tmp_path.glob(".published.*.tmp"))


def test_publication_does_not_replace_destination_created_before_commit(
    tmp_path: Path,
) -> None:
    _source, candidate_bytes, request = _source_candidate_request()
    result = _validated_result(request, candidate_bytes)
    workspace = _workspace(tmp_path, candidate_bytes)
    destination = tmp_path / "published"
    marker = destination / "keep.txt"

    def create_destination(_staging: Path) -> None:
        destination.mkdir()
        marker.write_text("keep")

    with pytest.raises(DiffusionPipelineError, match="already exists"):
        publish_diffusion_bundle(
            request,
            result,
            workspace=workspace,
            destination_bundle=destination,
            before_commit=create_destination,
        )

    assert marker.read_text() == "keep"
    assert not (destination / "bundle.json").exists()
    assert not list(tmp_path.glob(".published.*.tmp"))


def test_publication_failure_leaves_no_public_or_staged_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, candidate_bytes, request = _source_candidate_request()
    result = _validated_result(request, candidate_bytes)
    workspace = _workspace(tmp_path, candidate_bytes)
    destination = tmp_path / "published"

    def fail_rename(_source: Path, _destination: Path) -> None:
        raise OSError("injected rename failure")

    monkeypatch.setattr(diffusion_pipeline, "_rename_bundle", fail_rename)
    with pytest.raises(OSError, match="injected"):
        publish_diffusion_bundle(
            request,
            result,
            workspace=workspace,
            destination_bundle=destination,
        )

    assert not destination.exists()
    assert not list(tmp_path.glob(".published.*.tmp"))


def test_publication_removes_committed_bundle_when_parent_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source, candidate_bytes, request = _source_candidate_request()
    result = _validated_result(request, candidate_bytes)
    workspace = _workspace(tmp_path, candidate_bytes)
    destination = tmp_path / "published"
    real_fsync = diffusion_pipeline._fsync_directory
    calls = 0

    def fail_parent_fsync(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected parent fsync failure")
        real_fsync(path)

    monkeypatch.setattr(
        diffusion_pipeline,
        "_fsync_directory",
        fail_parent_fsync,
    )
    with pytest.raises(OSError, match="injected"):
        publish_diffusion_bundle(
            request,
            result,
            workspace=workspace,
            destination_bundle=destination,
        )

    assert not destination.exists()
    assert not list(tmp_path.glob(".published.*.tmp"))


def test_publication_rechecks_digest_and_private_file_type(tmp_path: Path) -> None:
    _source, candidate_bytes, request = _source_candidate_request()
    result = _validated_result(request, candidate_bytes)
    workspace = _workspace(tmp_path, candidate_bytes)
    candidate_path = workspace / "candidates" / "candidate-0001.pdb"
    candidate_path.write_bytes(candidate_bytes + b"REMARK changed\n")

    with pytest.raises(DiffusionPipelineError, match="SHA-256"):
        publish_diffusion_bundle(
            request,
            result,
            workspace=workspace,
            destination_bundle=tmp_path / "digest-output",
        )
    assert not (tmp_path / "digest-output").exists()

    candidate_path.unlink()
    candidate_path.symlink_to(FIXTURE)
    with pytest.raises(DiffusionPipelineError, match="symlink"):
        publish_diffusion_bundle(
            request,
            result,
            workspace=workspace,
            destination_bundle=tmp_path / "symlink-output",
        )


def test_publication_rejects_hard_link_and_malformed_staging_without_orphans(
    tmp_path: Path,
) -> None:
    _source, candidate_bytes, request = _source_candidate_request()
    result = _validated_result(request, candidate_bytes)
    workspace = _workspace(tmp_path, candidate_bytes)
    candidate_path = workspace / "candidates" / "candidate-0001.pdb"
    hard_link = tmp_path / "candidate-copy.pdb"
    hard_link.hardlink_to(candidate_path)

    with pytest.raises(DiffusionPipelineError, match="private regular file"):
        publish_diffusion_bundle(
            request,
            result,
            workspace=workspace,
            destination_bundle=tmp_path / "hard-link-output",
        )
    assert not (tmp_path / "hard-link-output").exists()
    assert not list(tmp_path.glob(".hard-link-output.*.tmp"))

    hard_link.unlink()
    malformed = b"ATOM      1  CA"
    candidate_path.write_bytes(malformed)
    malformed_result = _validated_result(request, malformed)
    with pytest.raises(DiffusionPipelineError, match="truncated coordinate"):
        publish_diffusion_bundle(
            request,
            malformed_result,
            workspace=workspace,
            destination_bundle=tmp_path / "malformed-output",
        )
    assert not (tmp_path / "malformed-output").exists()
    assert not list(tmp_path.glob(".malformed-output.*.tmp"))


def test_unsupported_scope_does_not_launch_runner_or_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _candidate_bytes, request = _source_candidate_request()
    source_root = tmp_path / "source"
    input_path = source_root / "input" / "normalized.pdb"
    input_path.parent.mkdir(parents=True)
    input_path.write_bytes(source)
    unsupported = replace(
        request,
        target_sequences=(TargetSequence("C", "SNRFSXSKSGNTA"),),
    )

    def should_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("runner launched for unsupported request")

    monkeypatch.setattr(
        diffusion_pipeline,
        "run_diffusion_runner",
        should_not_run,
    )
    destination = tmp_path / "published"
    outcome = run_diffusion_pipeline(
        unsupported,
        ("missing-runner",),
        source_root=source_root,
        work_parent=tmp_path,
        destination_bundle=destination,
    )

    assert outcome.status is DiffusionStatus.UNSUPPORTED
    assert outcome.published_bundle is None
    assert not destination.exists()
    assert not list(tmp_path.glob(".dvbfixer-diffusion-run.*"))


def test_internal_ter_does_not_launch_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _candidate_bytes, request = _source_candidate_request()
    right_line = next(
        line
        for line in source.splitlines(keepends=True)
        if line.startswith(b"ATOM  ") and line[22:26].strip() == b"70"
    )
    source = source.replace(right_line, b"TER\n" + right_line, 1)
    request = replace(
        request,
        normalized_pdb=ArtifactReference("input/normalized.pdb", _digest(source)),
    )
    source_root = tmp_path / "source"
    input_path = source_root / "input" / "normalized.pdb"
    input_path.parent.mkdir(parents=True)
    input_path.write_bytes(source)
    monkeypatch.setattr(
        diffusion_pipeline,
        "run_diffusion_runner",
        lambda *_args, **_kwargs: pytest.fail("runner must not launch"),
    )

    outcome = run_diffusion_pipeline(
        request,
        ("missing-runner",),
        source_root=source_root,
        work_parent=tmp_path,
        destination_bundle=tmp_path / "published",
    )

    assert outcome.status is DiffusionStatus.UNSUPPORTED
    assert "terminator-between-gap-anchors" in outcome.message
