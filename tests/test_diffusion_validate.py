"""Tests for independent DVBFixer diffusion candidate validation and ranking."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from openmm.app import PDBFile

import dvbfixer.model.diffusion.validate as diffusion_validate
from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    ArtifactReference,
    AtomIdentity,
    BackendProvenance,
    DiffusionRequest,
    DiffusionStatus,
    ExplicitLink,
    GapRegion,
    ResidueIdentity,
    RunnerCandidate,
    RunnerDiagnostics,
    RunnerResourceMetrics,
    RunnerResult,
    SequencePlacement,
    TargetInterval,
    TargetSequence,
)
from dvbfixer.model.diffusion.trace import build_sampler_trace
from dvbfixer.model.diffusion.validate import (
    build_validated_result,
    validate_runner_result,
)

FIXTURE = Path(__file__).parent / "fixtures" / "8cz8" / "8cz8_a_u.pdb"
GENERATED_NUMBERS = tuple(str(number) for number in range(65, 70))
GENERATED_NAMES = {"65": "SER", "66": "GLY", "67": "SER", "68": "LYS", "69": "SER"}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atom_identity(line: str) -> AtomIdentity:
    return AtomIdentity(line[21], line[22:26].strip(), line[26].strip(), line[12:16].strip())


def _residue_identity(line: str) -> ResidueIdentity:
    return ResidueIdentity(line[21], line[22:26].strip(), line[26].strip())


def _heavy(line: str) -> bool:
    element = line[76:78].strip()
    return element.upper() != "H"


def _source_and_candidate() -> tuple[str, str, tuple[AtomIdentity, ...], tuple[AtomIdentity, ...]]:
    source_lines = FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True)
    generated_residues = {ResidueIdentity("C", number) for number in GENERATED_NUMBERS}
    generated_atoms = tuple(
        _atom_identity(line)
        for line in source_lines
        if line.startswith(("ATOM  ", "HETATM"))
        and _residue_identity(line) in generated_residues
        and _heavy(line)
    )
    fixed_atoms = tuple(
        _atom_identity(line)
        for line in source_lines
        if line.startswith(("ATOM  ", "HETATM"))
        and _residue_identity(line) not in generated_residues
        and _heavy(line)
    )
    source = "".join(
        line
        for line in source_lines
        if not (
            line.startswith(("ATOM  ", "HETATM"))
            and _residue_identity(line) in generated_residues
        )
    )
    return source, "".join(source_lines), fixed_atoms, generated_atoms


def _request(
    source_bytes: bytes,
    fixed_atoms: tuple[AtomIdentity, ...],
    generated_atoms: tuple[AtomIdentity, ...],
    *,
    retained_explicit_links: tuple[ExplicitLink, ...] = (),
) -> DiffusionRequest:
    left = ResidueIdentity("C", "64")
    generated = tuple(ResidueIdentity("C", number) for number in GENERATED_NUMBERS)
    right = ResidueIdentity("C", "70")
    return DiffusionRequest(
        schema_version=DIFFUSION_SCHEMA_VERSION,
        normalized_pdb=ArtifactReference("input/normalized.pdb", _digest(source_bytes)),
        target_sequences=(TargetSequence("C", "FSGSKSG"),),
        sequence_placements=(
            SequencePlacement(
                chain="C",
                target_length=7,
                observed_target_indices=(0, 6),
                observed_residues=(left, right),
            ),
        ),
        gaps=(
            GapRegion(
                chain="C",
                target_interval=TargetInterval(1, 6),
                left_anchor=left,
                right_anchor=right,
                generated_residues=generated,
                movable_junction_residues=(left, *generated, right),
            ),
        ),
        fixed_atoms=fixed_atoms,
        generated_atoms=generated_atoms,
        retained_explicit_links=retained_explicit_links,
        candidate_count=2,
        seeds=(7, 11),
    )


def _runner_result(candidates: tuple[RunnerCandidate, ...]) -> RunnerResult:
    return RunnerResult(
        schema_version=DIFFUSION_SCHEMA_VERSION,
        status=DiffusionStatus.SUCCESS,
        candidates=candidates,
        runner_diagnostics=RunnerDiagnostics(exit_code=0, timed_out=False),
        backend_provenance=BackendProvenance(
            backend="fake",
            runner_protocol_version=2,
            engine_repository="https://example.invalid/fake",
            engine_revision="test-revision",
            device="cpu",
        ),
        resource_metrics=RunnerResourceMetrics(
            wall_time_seconds=1.5,
            peak_vram_bytes=4096,
        ),
    )


def _candidate(
    candidate_id: str,
    path: str,
    data: bytes,
    generated_atoms: tuple[AtomIdentity, ...],
    *,
    score: float,
) -> RunnerCandidate:
    fixed_atoms = _source_and_candidate()[2]
    trace_bytes = _trace_bytes(fixed_atoms, generated_atoms)
    return RunnerCandidate(
        candidate_id=candidate_id,
        seed=7,
        coordinate_artifact=ArtifactReference(path, _digest(data)),
        sampler_trace_artifact=ArtifactReference(
            "sampler-trace.json",
            _digest(trace_bytes),
        ),
        generated_atoms=generated_atoms,
        generated_residues=tuple(ResidueIdentity("C", number) for number in GENERATED_NUMBERS),
        raw_backend_score=score,
        score_provenance="fake-runner:test-score-v1",
    )


def _workspace(tmp_path: Path) -> tuple[Path, DiffusionRequest, bytes, tuple[AtomIdentity, ...]]:
    source, candidate, fixed_atoms, generated_atoms = _source_and_candidate()
    source_bytes = source.encode()
    candidate_bytes = candidate.encode()
    workspace = tmp_path / "workspace"
    (workspace / "input").mkdir(parents=True)
    (workspace / "candidates").mkdir()
    (workspace / "input" / "normalized.pdb").write_bytes(source_bytes)
    request = _request(source_bytes, fixed_atoms, generated_atoms)
    trace_bytes = _trace_bytes(fixed_atoms, generated_atoms)
    (workspace / "sampler-trace.json").write_bytes(trace_bytes)
    return workspace, request, candidate_bytes, generated_atoms


def _trace_bytes(
    fixed_atoms: tuple[AtomIdentity, ...],
    generated_atoms: tuple[AtomIdentity, ...],
) -> bytes:
    return build_sampler_trace(
        profile="test",
        engine_repository="https://example.invalid/fake",
        engine_revision="test-revision",
        patch_identity="none",
        atom_order=(*fixed_atoms, *generated_atoms),
        fixed_atoms=fixed_atoms,
        device="cpu",
        fallback_disabled=True,
        denoising_update_count=0,
        final_fixed_coordinate_restoration=True,
    ).to_json().encode()


def _rewrite_coordinate(
    data: bytes,
    identity: AtomIdentity,
    *,
    dx: float = 0.0,
    dy: float = 0.0,
    dz: float = 0.0,
) -> bytes:
    output: list[str] = []
    for line in data.decode().splitlines(keepends=True):
        if line.startswith(("ATOM  ", "HETATM")) and _atom_identity(line) == identity:
            x = float(line[30:38]) + dx
            y = float(line[38:46]) + dy
            z = float(line[46:54]) + dz
            line = line[:30] + f"{x:8.3f}{y:8.3f}{z:8.3f}" + line[54:]
        output.append(line)
    return "".join(output).encode()


def _remove_atom(data: bytes, identity: AtomIdentity) -> bytes:
    return "".join(
        line
        for line in data.decode().splitlines(keepends=True)
        if not (
            line.startswith(("ATOM  ", "HETATM"))
            and _atom_identity(line) == identity
        )
    ).encode()


def _append_conect(data: bytes, atom1: AtomIdentity, atom2: AtomIdentity) -> bytes:
    serials: dict[AtomIdentity, int] = {}
    lines = data.decode().splitlines(keepends=True)
    for line in lines:
        if line.startswith(("ATOM  ", "HETATM")):
            serials[_atom_identity(line)] = int(line[6:11])
    record = f"CONECT{serials[atom1]:5d}{serials[atom2]:5d}\n"
    insert_at = next((index for index, line in enumerate(lines) if line.startswith("END")), len(lines))
    lines.insert(insert_at, record)
    return "".join(lines).encode()


def _rotate_lysine_chi12_to_zero(data: bytes, residue_number: str) -> bytes:
    import math

    import numpy as np

    lines = data.decode().splitlines(keepends=True)
    coordinates: dict[str, np.ndarray] = {}
    for line in lines:
        if (
            line.startswith("ATOM  ")
            and line[21] == "C"
            and line[22:26].strip() == residue_number
        ):
            coordinates[line[12:16].strip()] = np.asarray(
                (
                    float(line[30:38]),
                    float(line[38:46]),
                    float(line[46:54]),
                ),
                dtype=float,
            )

    def dihedral(names: tuple[str, str, str, str]) -> float:
        first, second, third, fourth = (coordinates[name] for name in names)
        central = third - second
        central /= np.linalg.norm(central)
        left = first - second
        right = fourth - third
        left -= np.dot(left, central) * central
        right -= np.dot(right, central) * central
        return math.degrees(
            math.atan2(
                float(np.dot(np.cross(central, left), right)),
                float(np.dot(left, right)),
            )
        )

    def rotate(
        origin_name: str,
        axis_name: str,
        rotated_names: tuple[str, ...],
        angle_degrees: float,
    ) -> None:
        origin = coordinates[origin_name]
        axis = coordinates[axis_name] - origin
        axis /= np.linalg.norm(axis)
        angle = math.radians(angle_degrees)
        cosine = math.cos(angle)
        sine = math.sin(angle)
        for name in rotated_names:
            vector = coordinates[name] - origin
            coordinates[name] = origin + (
                vector * cosine
                + np.cross(axis, vector) * sine
                + axis * np.dot(axis, vector) * (1.0 - cosine)
            )

    rotate(
        "CA",
        "CB",
        ("CG", "CD", "CE", "NZ"),
        -dihedral(("N", "CA", "CB", "CG")),
    )
    rotate(
        "CB",
        "CG",
        ("CD", "CE", "NZ"),
        -dihedral(("CA", "CB", "CG", "CD")),
    )

    output: list[str] = []
    for line in lines:
        if (
            line.startswith("ATOM  ")
            and line[21] == "C"
            and line[22:26].strip() == residue_number
            and line[12:16].strip() in coordinates
        ):
            atom_name = line[12:16].strip()
            if atom_name in {"CG", "CD", "CE", "NZ"}:
                point = coordinates[atom_name]
                line = (
                    line[:30]
                    + f"{point[0]:8.3f}{point[1]:8.3f}{point[2]:8.3f}"
                    + line[54:]
                )
        output.append(line)
    return "".join(output).encode()


def _mirror_cb(data: bytes, residue_number: str) -> bytes:
    lines = data.decode().splitlines(keepends=True)
    coordinates: dict[str, tuple[float, float, float]] = {}
    for line in lines:
        if line.startswith("ATOM  ") and line[21] == "C" and line[22:26].strip() == residue_number:
            coordinates[line[12:16].strip()] = (
                float(line[30:38]),
                float(line[38:46]),
                float(line[46:54]),
            )
    import numpy as np

    n = np.asarray(coordinates["N"])
    ca = np.asarray(coordinates["CA"])
    c = np.asarray(coordinates["C"])
    cb = np.asarray(coordinates["CB"])
    normal = np.cross(n - ca, c - ca)
    mirrored = cb - 2.0 * np.dot(cb - ca, normal) / np.dot(normal, normal) * normal
    output: list[str] = []
    for line in lines:
        if (
            line.startswith("ATOM  ")
            and line[21] == "C"
            and line[22:26].strip() == residue_number
            and line[12:16].strip() == "CB"
        ):
            line = (
                line[:30]
                + f"{mirrored[0]:8.3f}{mirrored[1]:8.3f}{mirrored[2]:8.3f}"
                + line[54:]
            )
        output.append(line)
    return "".join(output).encode()


def test_validation_parses_openmm_from_verified_text(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    candidate_path = workspace / "candidates" / "passing.pdb"
    candidate_path.write_bytes(candidate_bytes)
    runner_result = _runner_result(
        (_candidate("passing", "candidates/passing.pdb", candidate_bytes, generated_atoms, score=4.0),)
    )
    parsed_inputs: list[object] = []

    def parse_verified_text(file, extraParticleIdentifier: str = "EP"):
        parsed_inputs.append(file)
        return PDBFile(file, extraParticleIdentifier=extraParticleIdentifier)

    monkeypatch.setattr(diffusion_validate, "PDBFile", parse_verified_text)

    validation = validate_runner_result(request, runner_result, workspace=workspace)[0]

    assert validation.summary.passed is True
    assert len(parsed_inputs) == 2
    assert all(isinstance(file, StringIO) for file in parsed_inputs)


def test_validation_accepts_complete_fixture_candidate(tmp_path: Path) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    candidate_path = workspace / "candidates" / "passing.pdb"
    candidate_path.write_bytes(candidate_bytes)
    runner_result = _runner_result(
        (_candidate("passing", "candidates/passing.pdb", candidate_bytes, generated_atoms, score=4.0),)
    )

    validations = validate_runner_result(request, runner_result, workspace=workspace)
    result = build_validated_result(request, runner_result, workspace=workspace)

    assert len(validations) == 1
    assert validations[0].summary.passed is True
    assert validations[0].summary.hard_gate_failures == ()
    assert result.status is DiffusionStatus.SUCCESS
    assert result.resource_metrics.wall_time_seconds == 1.5
    assert result.resource_metrics.peak_vram_bytes == 4096
    assert [candidate.candidate_id for candidate in result.candidates] == ["passing"]
    metrics = {metric.name: metric.value for metric in result.validation_summaries[0].metrics}
    assert metrics["fixed-heavy-atom-rmsd"] == 0.0
    assert metrics["generated-heavy-atoms-missing"] == 0.0
    assert metrics["detectable-d-ca"] == 0.0


def test_validation_rejects_raw_candidate_after_refinement_failure(
    tmp_path: Path,
) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    candidate_path = workspace / "candidates" / "raw.pdb"
    candidate_path.write_bytes(candidate_bytes)
    raw = _candidate(
        "raw",
        "candidates/raw.pdb",
        candidate_bytes,
        generated_atoms,
        score=4.0,
    )
    runner_result = _runner_result((replace(
        raw,
        postprocessing_failures=("localized-openmm-boundary-refinement-failed",),
    ),))

    result = build_validated_result(request, runner_result, workspace=workspace)

    assert result.status is DiffusionStatus.FAILED
    assert result.candidates[0].coordinate_artifact == raw.coordinate_artifact
    assert result.validation_summaries[0].hard_gate_failures == (
        "localized-openmm-boundary-refinement-failed",
    )


def test_validation_rejects_outside_identity_and_fixed_coordinate_drift(tmp_path: Path) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    outside_atom = AtomIdentity("C", "64", "", "CA")
    candidate_bytes = _rewrite_coordinate(candidate_bytes, outside_atom, dx=0.050)
    candidate_bytes = _remove_atom(candidate_bytes, AtomIdentity("C", "64", "", "CZ"))
    candidate_path = workspace / "candidates" / "drifted.pdb"
    candidate_path.write_bytes(candidate_bytes)
    runner_result = _runner_result(
        (_candidate("drifted", "candidates/drifted.pdb", candidate_bytes, generated_atoms, score=1.0),)
    )

    validation = validate_runner_result(request, runner_result, workspace=workspace)[0].summary
    result = build_validated_result(request, runner_result, workspace=workspace)

    assert validation.passed is False
    assert "outside-generated-identity-mismatch" in validation.hard_gate_failures
    assert "fixed-heavy-atoms-missing" in validation.hard_gate_failures
    assert "fixed-heavy-atom-max-displacement" in validation.hard_gate_failures
    assert result.status is DiffusionStatus.FAILED
    assert [candidate.candidate_id for candidate in result.candidates] == ["drifted"]
    assert len(result.validation_summaries) == 1
    assert result.validation_summaries[0].passed is False
    assert result.resource_metrics.wall_time_seconds == 1.5


def test_validation_rejects_missing_generated_heavy_atom_and_bad_junction(tmp_path: Path) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    candidate_bytes = _remove_atom(candidate_bytes, AtomIdentity("C", "68", "", "NZ"))
    candidate_bytes = _rewrite_coordinate(candidate_bytes, AtomIdentity("C", "65", "", "N"), dx=2.0)
    candidate_path = workspace / "candidates" / "bad-gap.pdb"
    candidate_path.write_bytes(candidate_bytes)
    runner_result = _runner_result(
        (_candidate("bad-gap", "candidates/bad-gap.pdb", candidate_bytes, generated_atoms, score=1.0),)
    )

    validation = validate_runner_result(request, runner_result, workspace=workspace)[0].summary

    assert validation.passed is False
    assert "generated-heavy-atom-completeness" in validation.hard_gate_failures
    assert "junction-peptide-connectivity" in validation.hard_gate_failures


@pytest.mark.parametrize("distance,passes", [(1.19, False), (1.21, True), (1.33, True), (1.44, True), (1.46, False), (1.80, False)])
def test_junction_gate_measures_carbonyl_c_to_next_n_in_angstroms(tmp_path: Path, distance: float, passes: bool) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    lines = candidate_bytes.decode().splitlines(keepends=True)
    carbon = next(line for line in lines if line.startswith("ATOM  ") and _atom_identity(line) == AtomIdentity("C", "64", "", "C"))
    position = (float(carbon[30:38]) + distance, float(carbon[38:46]), float(carbon[46:54]))
    # Other geometry may intentionally fail: this test isolates the junction
    # decision and its metric using a precisely controlled physical C-N length.
    candidate_bytes = "".join(
        line[:30] + "".join(f"{value:8.3f}" for value in position) + line[54:]
        if line.startswith("ATOM  ") and _atom_identity(line) == AtomIdentity("C", "65", "", "N") else line
        for line in lines
    ).encode()
    (workspace / "candidates" / "controlled-cn.pdb").write_bytes(candidate_bytes)
    result = _runner_result((_candidate("controlled", "candidates/controlled-cn.pdb", candidate_bytes, generated_atoms, score=1.0),))
    validation = validate_runner_result(request, result, workspace=workspace)[0].summary
    assert ("junction-peptide-connectivity" not in validation.hard_gate_failures) is passes
    metrics = {metric.name: metric.value for metric in validation.metrics}
    assert metrics["junction-cn-distance-min"] <= distance + 1e-12
    assert metrics["junction-cn-distance-max"] >= distance - 1e-12


def test_validation_preserves_requested_explicit_links_canonically(tmp_path: Path) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    atom1 = AtomIdentity("C", "64", "", "N")
    atom2 = AtomIdentity("C", "70", "", "O")
    linked_bytes = _append_conect(candidate_bytes, atom1, atom2)
    candidate_path = workspace / "candidates" / "linked.pdb"
    candidate_path.write_bytes(linked_bytes)
    request = replace(
        request,
        retained_explicit_links=(ExplicitLink(atom2, atom1, "conect"),),
    )
    runner_result = _runner_result(
        (_candidate("linked", "candidates/linked.pdb", linked_bytes, generated_atoms, score=1.0),)
    )

    validation = validate_runner_result(request, runner_result, workspace=workspace)[0].summary

    assert validation.passed is True
    metrics = {metric.name: metric.value for metric in validation.metrics}
    assert metrics["retained-explicit-links-missing"] == 0.0


def test_validation_accepts_link_record_source_equivalent_to_conect(tmp_path: Path) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    atom1 = AtomIdentity("C", "64", "", "N")
    atom2 = AtomIdentity("C", "70", "", "O")
    linked_bytes = _append_conect(candidate_bytes, atom1, atom2)
    candidate_path = workspace / "candidates" / "equivalent-link.pdb"
    candidate_path.write_bytes(linked_bytes)
    request = replace(
        request,
        retained_explicit_links=(ExplicitLink(atom1, atom2, "LINK"),),
    )
    runner_result = _runner_result(
        (
            _candidate(
                "equivalent-link",
                "candidates/equivalent-link.pdb",
                linked_bytes,
                generated_atoms,
                score=1.0,
            ),
        )
    )

    validation = validate_runner_result(request, runner_result, workspace=workspace)[0].summary

    assert validation.passed is True


def test_validation_rejects_unexpected_explicit_link_outside_generated_region(
    tmp_path: Path,
) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    linked_bytes = _append_conect(
        candidate_bytes,
        AtomIdentity("C", "64", "", "N"),
        AtomIdentity("C", "70", "", "O"),
    )
    candidate_path = workspace / "candidates" / "unexpected-link.pdb"
    candidate_path.write_bytes(linked_bytes)
    runner_result = _runner_result(
        (
            _candidate(
                "unexpected-link",
                "candidates/unexpected-link.pdb",
                linked_bytes,
                generated_atoms,
                score=1.0,
            ),
        )
    )

    validation = validate_runner_result(request, runner_result, workspace=workspace)[0].summary

    assert validation.passed is False
    assert "retained-explicit-link-unexpected" in validation.hard_gate_failures


def test_validation_rejects_missing_requested_explicit_link(tmp_path: Path) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    request = replace(
        request,
        retained_explicit_links=(
            ExplicitLink(
                AtomIdentity("C", "64", "", "N"),
                AtomIdentity("C", "70", "", "O"),
                "CONECT",
            ),
        ),
    )
    candidate_path = workspace / "candidates" / "unlinked.pdb"
    candidate_path.write_bytes(candidate_bytes)
    runner_result = _runner_result(
        (_candidate("unlinked", "candidates/unlinked.pdb", candidate_bytes, generated_atoms, score=1.0),)
    )

    validation = validate_runner_result(request, runner_result, workspace=workspace)[0].summary

    assert validation.passed is False
    assert "retained-explicit-link-missing" in validation.hard_gate_failures


def test_validation_rejects_generated_bond_length_error(tmp_path: Path) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    candidate_bytes = _rewrite_coordinate(
        candidate_bytes,
        AtomIdentity("C", "65", "", "OG"),
        dx=2.0,
    )
    candidate_path = workspace / "candidates" / "bad-bond.pdb"
    candidate_path.write_bytes(candidate_bytes)
    runner_result = _runner_result(
        (_candidate("bad-bond", "candidates/bad-bond.pdb", candidate_bytes, generated_atoms, score=1.0),)
    )

    validation = validate_runner_result(request, runner_result, workspace=workspace)[0].summary

    assert validation.passed is False
    assert "generated-or-junction-bond-length" in validation.hard_gate_failures
    metrics = {metric.name: metric.value for metric in validation.metrics}
    assert metrics["generated-or-junction-bond-length-errors"] >= 1.0


def test_validation_rejects_generated_backbone_angle_error(tmp_path: Path) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    candidate_bytes = _rewrite_coordinate(
        candidate_bytes,
        AtomIdentity("C", "66", "", "CA"),
        dx=1.0,
    )
    candidate_path = workspace / "candidates" / "bad-angle.pdb"
    candidate_path.write_bytes(candidate_bytes)
    runner_result = _runner_result(
        (
            _candidate(
                "bad-angle",
                "candidates/bad-angle.pdb",
                candidate_bytes,
                generated_atoms,
                score=1.0,
            ),
        )
    )

    validation = validate_runner_result(request, runner_result, workspace=workspace)[0].summary

    assert validation.passed is False
    assert "generated-or-junction-bond-angle" in validation.hard_gate_failures
    metrics = {metric.name: metric.value for metric in validation.metrics}
    assert metrics["generated-or-junction-bond-angle-errors"] >= 1.0


def test_validation_rejects_generated_ramachandran_outlier(tmp_path: Path) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    candidate_bytes = _rewrite_coordinate(
        candidate_bytes,
        AtomIdentity("C", "67", "", "N"),
        dx=-1.75,
    )
    candidate_path = workspace / "candidates" / "rama-outlier.pdb"
    candidate_path.write_bytes(candidate_bytes)
    runner_result = _runner_result(
        (
            _candidate(
                "rama-outlier",
                "candidates/rama-outlier.pdb",
                candidate_bytes,
                generated_atoms,
                score=1.0,
            ),
        )
    )

    validation = validate_runner_result(request, runner_result, workspace=workspace)[0].summary

    assert validation.passed is False
    assert "generated-or-junction-ramachandran" in validation.hard_gate_failures
    metrics = {metric.name: metric.value for metric in validation.metrics}
    assert metrics["generated-or-junction-ramachandran-outliers"] >= 1.0


def test_validation_rejects_generated_sidechain_chi12_outlier(
    tmp_path: Path,
) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    candidate_bytes = _rotate_lysine_chi12_to_zero(candidate_bytes, "68")
    candidate_path = workspace / "candidates" / "chi12-outlier.pdb"
    candidate_path.write_bytes(candidate_bytes)
    runner_result = _runner_result(
        (
            _candidate(
                "chi12-outlier",
                "candidates/chi12-outlier.pdb",
                candidate_bytes,
                generated_atoms,
                score=1.0,
            ),
        )
    )

    validation = validate_runner_result(request, runner_result, workspace=workspace)[0].summary

    assert validation.passed is False
    assert "generated-or-junction-sidechain-chi12" in validation.hard_gate_failures
    metrics = {metric.name: metric.value for metric in validation.metrics}
    assert metrics["generated-or-junction-sidechain-chi12-outliers"] >= 1.0


def test_validation_rejects_generated_amide_nonplanarity(tmp_path: Path) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    candidate_bytes = _rewrite_coordinate(
        candidate_bytes,
        AtomIdentity("C", "66", "", "C"),
        dx=1.0,
    )
    candidate_path = workspace / "candidates" / "non-planar.pdb"
    candidate_path.write_bytes(candidate_bytes)
    runner_result = _runner_result(
        (
            _candidate(
                "non-planar",
                "candidates/non-planar.pdb",
                candidate_bytes,
                generated_atoms,
                score=1.0,
            ),
        )
    )

    validation = validate_runner_result(request, runner_result, workspace=workspace)[0].summary

    assert validation.passed is False
    assert "generated-or-junction-amide-planarity" in validation.hard_gate_failures
    metrics = {metric.name: metric.value for metric in validation.metrics}
    assert metrics["generated-or-junction-non-planar-amides"] >= 1.0


def test_validation_rejects_d_chirality_after_final_coordinates(tmp_path: Path) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    candidate_bytes = _mirror_cb(candidate_bytes, "65")
    candidate_path = workspace / "candidates" / "d-residue.pdb"
    candidate_path.write_bytes(candidate_bytes)
    runner_result = _runner_result(
        (_candidate("d-residue", "candidates/d-residue.pdb", candidate_bytes, generated_atoms, score=1.0),)
    )

    validation = validate_runner_result(request, runner_result, workspace=workspace)[0].summary

    assert validation.passed is False
    assert "d-ca-chirality" in validation.hard_gate_failures
    metrics = {metric.name: metric.value for metric in validation.metrics}
    assert metrics["detectable-d-ca"] == 1.0


def test_ranking_keeps_only_passing_candidates_and_uses_candidate_id_tiebreak(
    tmp_path: Path,
) -> None:
    workspace, request, candidate_bytes, generated_atoms = _workspace(tmp_path)
    bad_bytes = _remove_atom(candidate_bytes, AtomIdentity("C", "68", "", "NZ"))
    paths_and_data = (
        ("higher", candidate_bytes, 9.0),
        ("lower", candidate_bytes, 2.0),
        ("failed", bad_bytes, 0.0),
    )
    candidates: list[RunnerCandidate] = []
    for candidate_id, data, score in paths_and_data:
        relative = f"candidates/{candidate_id}.pdb"
        (workspace / relative).write_bytes(data)
        candidates.append(_candidate(candidate_id, relative, data, generated_atoms, score=score))
    request = replace(request, candidate_count=3, seeds=(7, 11, 13))
    runner_result = _runner_result(tuple(candidates))

    result = build_validated_result(request, runner_result, workspace=workspace)

    assert result.status is DiffusionStatus.SUCCESS
    assert [candidate.candidate_id for candidate in result.candidates] == ["higher", "lower"]
    assert len(result.validation_summaries) == 2
    assert all(summary.passed for summary in result.validation_summaries)
