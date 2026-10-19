"""Independent DVBFixer validation and ranking for diffusion candidates."""

from __future__ import annotations

import hashlib
import math
import os
import stat
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np
from openmm.app import PDBFile

from dvbfixer.diagnose.chemistry import (
    check_backbone_bond_angles,
    check_bond_lengths,
    check_peptide_omegas,
)
from dvbfixer.diagnose.report import Severity
from dvbfixer.diagnose.steric import clashes_python
from dvbfixer.ffutils.geometry import ChiralityError, assert_all_l
from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    MAX_TRACE_BYTES,
    ArtifactReference,
    AtomIdentity,
    DiffusionCandidate,
    DiffusionContractError,
    DiffusionRequest,
    DiffusionResult,
    DiffusionStatus,
    ExplicitLink,
    Metric,
    ResidueIdentity,
    RunnerCandidate,
    RunnerResult,
    SamplerTrace,
    ValidationSummary,
)
from dvbfixer.model.diffusion.quality import check_ramachandran, check_sidechain_chi12
from dvbfixer.model.diffusion.scope import CANONICAL_HEAVY_ATOMS
from dvbfixer.model.diffusion.trace import validate_sampler_trace_context

FIXED_HEAVY_ATOM_RMSD_MAX_ANGSTROM = 0.01
FIXED_HEAVY_ATOM_DISPLACEMENT_MAX_ANGSTROM = 0.03
# Junction acceptance is a bond-length quality gate around the ~1.33 Å amide
# bond, not merely detection of disconnected chains. It rejects compressed as
# well as stretched C(i)-N(i+1) bonds. The separate 1.80 Å internal-gap check
# below is only a coarse break detector; the two tests have different purposes.
JUNCTION_CN_MIN_ANGSTROM = 1.20
JUNCTION_CN_MAX_ANGSTROM = 1.45
GENERATED_BACKBONE_BREAK_MAX_ANGSTROM = 1.80
SEVERE_CLASH_OVERLAP_ANGSTROM = 0.90


class DiffusionValidationError(RuntimeError):
    """Raised when trusted validation inputs cannot be read safely."""


@dataclass(frozen=True, slots=True)
class ValidationThresholds:
    """Frozen numerical gates for the first canonical-protein validation slice."""

    fixed_heavy_atom_rmsd_angstrom_max: float = FIXED_HEAVY_ATOM_RMSD_MAX_ANGSTROM
    fixed_heavy_atom_displacement_angstrom_max: float = (
        FIXED_HEAVY_ATOM_DISPLACEMENT_MAX_ANGSTROM
    )
    junction_cn_angstrom_min: float = JUNCTION_CN_MIN_ANGSTROM
    junction_cn_angstrom_max: float = JUNCTION_CN_MAX_ANGSTROM
    generated_backbone_break_angstrom_max: float = (
        GENERATED_BACKBONE_BREAK_MAX_ANGSTROM
    )
    severe_clash_overlap_angstrom: float = SEVERE_CLASH_OVERLAP_ANGSTROM

    def __post_init__(self) -> None:
        values = (
            self.fixed_heavy_atom_rmsd_angstrom_max,
            self.fixed_heavy_atom_displacement_angstrom_max,
            self.junction_cn_angstrom_min,
            self.junction_cn_angstrom_max,
            self.generated_backbone_break_angstrom_max,
            self.severe_clash_overlap_angstrom,
        )
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("validation thresholds must be finite and positive")
        if self.junction_cn_angstrom_min > self.junction_cn_angstrom_max:
            raise ValueError("junction C-N minimum must not exceed maximum")


@dataclass(frozen=True, slots=True)
class CandidateValidation:
    """One raw runner candidate paired with DVBFixer-owned validation."""

    candidate: RunnerCandidate
    summary: ValidationSummary
    ranking_metrics: tuple[Metric, ...] = ()


@dataclass(frozen=True, slots=True)
class _AtomRecord:
    identity: AtomIdentity
    residue: ResidueIdentity
    residue_name: str
    coordinates_angstrom: np.ndarray
    element: str
    serial: int
    record_name: str
    altloc: str


@dataclass(frozen=True, slots=True)
class _Structure:
    path: Path
    pdb: PDBFile
    atoms: dict[AtomIdentity, _AtomRecord]
    residues: dict[ResidueIdentity, str]
    explicit_links: frozenset[ExplicitLink]


_ONE_TO_THREE = {
    "A": "ALA", "C": "CYS", "D": "ASP", "E": "GLU", "F": "PHE",
    "G": "GLY", "H": "HIS", "I": "ILE", "K": "LYS", "L": "LEU",
    "M": "MET", "N": "ASN", "P": "PRO", "Q": "GLN", "R": "ARG",
    "S": "SER", "T": "THR", "V": "VAL", "W": "TRP", "Y": "TYR",
}


def validate_runner_result(
    request: DiffusionRequest,
    runner_result: RunnerResult,
    *,
    workspace: Path,
    thresholds: ValidationThresholds | None = None,
) -> tuple[CandidateValidation, ...]:
    """Validate every raw candidate without trusting runner-provided science."""
    if runner_result.status is not DiffusionStatus.SUCCESS:
        return ()
    active_thresholds = thresholds or ValidationThresholds()
    root = _require_workspace(workspace)
    source = _load_structure(root, request.normalized_pdb.path, request.normalized_pdb.sha256)
    validations: list[CandidateValidation] = []
    for candidate in runner_result.candidates:
        trace = _load_sampler_trace(root, candidate.sampler_trace_artifact)
        try:
            validate_sampler_trace_context(
                trace,
                request,
                runner_result.backend_provenance,
            )
        except DiffusionContractError as exc:
            raise DiffusionValidationError(
                f"candidate {candidate.candidate_id!r} sampler trace mismatch: {exc}"
            ) from exc
        structure = _load_structure(
            root,
            candidate.coordinate_artifact.path,
            candidate.coordinate_artifact.sha256,
        )
        summary, ranking_metrics = _validate_candidate(
            request,
            source,
            structure,
            active_thresholds,
            postprocessing_failures=candidate.postprocessing_failures,
            candidate_warnings=candidate.warnings,
        )
        validations.append(
            CandidateValidation(
                candidate=candidate,
                summary=summary,
                ranking_metrics=ranking_metrics,
            )
        )
    return tuple(validations)


def build_validated_result(
    request: DiffusionRequest,
    runner_result: RunnerResult,
    *,
    workspace: Path,
    thresholds: ValidationThresholds | None = None,
) -> DiffusionResult:
    """Rank candidates and retain failed ones as explicitly rejected artifacts."""
    if runner_result.status is not DiffusionStatus.SUCCESS:
        return DiffusionResult(
            schema_version=DIFFUSION_SCHEMA_VERSION,
            status=runner_result.status,
            candidates=(),
            validation_summaries=(),
            runner_diagnostics=runner_result.runner_diagnostics,
            backend_provenance=runner_result.backend_provenance,
            resource_metrics=runner_result.resource_metrics,
            message=runner_result.message,
        )

    validations = validate_runner_result(
        request,
        runner_result,
        workspace=workspace,
        thresholds=thresholds,
    )
    passing = sorted(
        (item for item in validations if item.summary.passed),
        key=_ranking_key,
    )
    if not passing:
        failed = sorted(validations, key=_ranking_key)
        failed_ids = ", ".join(item.candidate.candidate_id for item in validations)
        message = "all diffusion candidates failed independent DVBFixer validation"
        if failed_ids:
            message += f": {failed_ids}"
        return DiffusionResult(
            schema_version=DIFFUSION_SCHEMA_VERSION,
            status=DiffusionStatus.FAILED,
            candidates=tuple(_validated_candidate(item.candidate) for item in failed),
            validation_summaries=tuple(item.summary for item in failed),
            runner_diagnostics=runner_result.runner_diagnostics,
            backend_provenance=runner_result.backend_provenance,
            resource_metrics=runner_result.resource_metrics,
            message=message,
        )

    candidates = tuple(_validated_candidate(item.candidate) for item in passing)
    summaries = tuple(item.summary for item in passing)
    return DiffusionResult(
        schema_version=DIFFUSION_SCHEMA_VERSION,
        status=DiffusionStatus.SUCCESS,
        candidates=candidates,
        validation_summaries=summaries,
        runner_diagnostics=runner_result.runner_diagnostics,
        backend_provenance=runner_result.backend_provenance,
        resource_metrics=runner_result.resource_metrics,
        message=runner_result.message,
    )


def _validate_candidate(
    request: DiffusionRequest,
    source: _Structure,
    candidate: _Structure,
    thresholds: ValidationThresholds,
    *,
    postprocessing_failures: tuple[str, ...] = (),
    candidate_warnings: tuple[str, ...] = (),
) -> tuple[ValidationSummary, tuple[Metric, ...]]:
    failures: list[str] = []
    warnings: list[str] = []
    metrics: list[Metric] = []
    failures.extend(postprocessing_failures)
    warnings.extend(candidate_warnings)
    generated_residues = {
        residue for gap in request.gaps for residue in gap.generated_residues
    }

    source_outside_atoms = {
        identity for identity in source.atoms if _residue(identity) not in generated_residues
    }
    candidate_outside_atoms = {
        identity for identity in candidate.atoms if _residue(identity) not in generated_residues
    }
    missing_outside = source_outside_atoms - candidate_outside_atoms
    added_outside = candidate_outside_atoms - source_outside_atoms
    changed_residue_names = {
        residue
        for residue, source_name in source.residues.items()
        if residue not in generated_residues
        and candidate.residues.get(residue) != source_name
    }
    metrics.extend(
        (
            Metric("outside-atom-identities-missing", float(len(missing_outside)), "count"),
            Metric("outside-atom-identities-added", float(len(added_outside)), "count"),
            Metric("outside-residue-names-changed", float(len(changed_residue_names)), "count"),
        )
    )
    if missing_outside or added_outside or changed_residue_names:
        failures.append("outside-generated-identity-mismatch")

    fixed_displacements: list[float] = []
    missing_fixed: list[AtomIdentity] = []
    non_heavy_fixed: list[AtomIdentity] = []
    for identity in request.fixed_atoms:
        source_atom = source.atoms.get(identity)
        candidate_atom = candidate.atoms.get(identity)
        if source_atom is None or candidate_atom is None:
            missing_fixed.append(identity)
            continue
        if not source_atom.element or source_atom.element.upper() == "H":
            non_heavy_fixed.append(identity)
            continue
        fixed_displacements.append(
            float(np.linalg.norm(candidate_atom.coordinates_angstrom - source_atom.coordinates_angstrom))
        )
    if missing_fixed:
        failures.append("fixed-heavy-atoms-missing")
    if non_heavy_fixed:
        warnings.append(
            "request fixed atom mask contains non-heavy atoms; "
            "they were excluded from drift metrics"
        )
    if fixed_displacements:
        displacement_array = np.asarray(fixed_displacements, dtype=np.float64)
        fixed_rmsd = float(np.sqrt(np.mean(displacement_array * displacement_array)))
        fixed_max = float(np.max(displacement_array))
    else:
        fixed_rmsd = 0.0
        fixed_max = 0.0
        failures.append("fixed-heavy-atom-mask-empty")
    metrics.extend(
        (
            Metric("fixed-heavy-atom-rmsd", fixed_rmsd, "angstrom"),
            Metric("fixed-heavy-atom-max-displacement", fixed_max, "angstrom"),
        )
    )
    if fixed_rmsd > thresholds.fixed_heavy_atom_rmsd_angstrom_max:
        failures.append("fixed-heavy-atom-rmsd")
    if fixed_max > thresholds.fixed_heavy_atom_displacement_angstrom_max:
        failures.append("fixed-heavy-atom-max-displacement")

    expected_generated = _expected_generated_residue_names(request)
    missing_generated_residues = 0
    wrong_generated_residue_names = 0
    missing_generated_heavy_atoms = 0
    unexpected_generated_heavy_atoms = 0
    for residue, expected_name in expected_generated.items():
        actual_name = candidate.residues.get(residue)
        if actual_name is None:
            missing_generated_residues += 1
            continue
        if actual_name != expected_name:
            wrong_generated_residue_names += 1
        present = {
            atom.identity.atom_name
            for atom in candidate.atoms.values()
            if atom.residue == residue and atom.element.upper() != "H"
        }
        expected_atoms = frozenset(CANONICAL_HEAVY_ATOMS[expected_name])
        missing_generated_heavy_atoms += len(expected_atoms - present)
        unexpected_generated_heavy_atoms += len(present - expected_atoms)
    metrics.extend(
        (
            Metric("generated-residues-missing", float(missing_generated_residues), "count"),
            Metric("generated-residue-names-wrong", float(wrong_generated_residue_names), "count"),
            Metric("generated-heavy-atoms-missing", float(missing_generated_heavy_atoms), "count"),
            Metric("generated-heavy-atoms-unexpected", float(unexpected_generated_heavy_atoms), "count"),
        )
    )
    if missing_generated_residues:
        failures.append("generated-residues-missing")
    if wrong_generated_residue_names:
        failures.append("generated-residue-name-mismatch")
    if missing_generated_heavy_atoms or unexpected_generated_heavy_atoms:
        failures.append("generated-heavy-atom-completeness")

    junction_distances: list[float] = []
    backbone_distances: list[float] = []
    for gap in request.gaps:
        ordered = (
            *((gap.left_anchor,) if gap.left_anchor is not None else ()),
            *gap.generated_residues,
            *((gap.right_anchor,) if gap.right_anchor is not None else ()),
        )
        anchors = {gap.left_anchor, gap.right_anchor} - {None}
        for index, (left, right) in enumerate(zip(ordered, ordered[1:])):
            distance = _cn_distance(candidate, left, right)
            if distance is None:
                failures.append("generated-backbone-atoms-missing")
                continue
            backbone_distances.append(distance)
            if left in anchors or right in anchors:
                junction_distances.append(distance)
                if not (
                    thresholds.junction_cn_angstrom_min
                    <= distance
                    <= thresholds.junction_cn_angstrom_max
                ):
                    failures.append("junction-peptide-connectivity")
            elif distance > thresholds.generated_backbone_break_angstrom_max:
                failures.append("generated-backbone-break")
    metrics.extend(
        (
            Metric(
                "junction-cn-distance-min",
                min(junction_distances, default=math.inf),
                "angstrom",
            ),
            Metric(
                "junction-cn-distance-max",
                max(junction_distances, default=math.inf),
                "angstrom",
            ),
            Metric(
                "generated-region-cn-distance-max",
                max(backbone_distances, default=math.inf),
                "angstrom",
            ),
        )
    )

    requested_links = {_link_key(link) for link in request.retained_explicit_links}
    candidate_links = {
        _link_key(link)
        for link in candidate.explicit_links
        if _link_touches_outside_generated(link, generated_residues)
    }
    missing_links = requested_links - candidate_links
    unexpected_links = candidate_links - requested_links
    metrics.extend(
        (
            Metric("retained-explicit-links-missing", float(len(missing_links)), "count"),
            Metric("retained-explicit-links-unexpected", float(len(unexpected_links)), "count"),
        )
    )
    if missing_links:
        failures.append("retained-explicit-link-missing")
    if unexpected_links:
        failures.append("retained-explicit-link-unexpected")

    generated_or_junction = generated_residues | {
        anchor
        for gap in request.gaps
        for anchor in (gap.left_anchor, gap.right_anchor)
        if anchor is not None
    }
    bond_length_findings = [
        finding
        for finding in check_bond_lengths(candidate.pdb.topology, candidate.pdb.positions)
        if finding.severity is Severity.ERROR
        and _finding_residue(finding.chain, finding.resid) in generated_or_junction
    ]
    bond_angle_findings = [
        finding
        for finding in check_backbone_bond_angles(
            candidate.pdb.topology,
            candidate.pdb.positions,
        )
        if finding.severity is Severity.ERROR
        and _finding_residue(finding.chain, finding.resid) in generated_or_junction
    ]
    non_planar_amides = [
        finding
        for finding in check_peptide_omegas(candidate.pdb.topology, candidate.pdb.positions)
        if finding.category == "non_planar_amide"
        and _finding_residue(finding.chain, finding.resid) in generated_or_junction
    ]
    ramachandran_outliers = [
        finding
        for finding in check_ramachandran(
            candidate.pdb.topology,
            candidate.pdb.positions,
        )
        if finding.severity is Severity.ERROR
        and _finding_residue(finding.chain, finding.resid) in generated_or_junction
    ]
    sidechain_chi12_outliers = [
        finding
        for finding in check_sidechain_chi12(
            candidate.pdb.topology,
            candidate.pdb.positions,
        )
        if finding.severity is Severity.ERROR
        and _finding_residue(finding.chain, finding.resid) in generated_or_junction
    ]
    metrics.extend(
        (
            Metric(
                "generated-or-junction-bond-length-errors",
                float(len(bond_length_findings)),
                "count",
            ),
            Metric(
                "generated-or-junction-bond-angle-errors",
                float(len(bond_angle_findings)),
                "count",
            ),
            Metric(
                "generated-or-junction-non-planar-amides",
                float(len(non_planar_amides)),
                "count",
            ),
            Metric(
                "generated-or-junction-ramachandran-outliers",
                float(len(ramachandran_outliers)),
                "count",
            ),
            Metric(
                "generated-or-junction-sidechain-chi12-outliers",
                float(len(sidechain_chi12_outliers)),
                "count",
            ),
        )
    )
    if bond_length_findings:
        failures.append("generated-or-junction-bond-length")
    if bond_angle_findings:
        failures.append("generated-or-junction-bond-angle")
    if non_planar_amides:
        failures.append("generated-or-junction-amide-planarity")
    if ramachandran_outliers:
        failures.append("generated-or-junction-ramachandran")
    if sidechain_chi12_outliers:
        failures.append("generated-or-junction-sidechain-chi12")

    severe_clashes = [
        finding
        for finding in clashes_python(
            candidate.pdb.topology,
            candidate.pdb.positions,
            clash_warn_a=thresholds.severe_clash_overlap_angstrom,
            clash_error_a=thresholds.severe_clash_overlap_angstrom,
        )
        if finding.severity is Severity.ERROR
        and (
            _finding_residue(finding.chain, finding.resid) in generated_or_junction
            or _finding_partner_residue(finding) in generated_or_junction
        )
    ]
    metrics.append(Metric("severe-steric-overlaps", float(len(severe_clashes)), "count"))
    if severe_clashes:
        failures.append("severe-steric-overlap")

    try:
        assert_all_l(candidate.pdb.topology, candidate.pdb.positions)
        d_residues = 0
    except ChiralityError as exc:
        d_residues = len(exc.residues)
        failures.append("d-ca-chirality")
    metrics.append(Metric("detectable-d-ca", float(d_residues), "count"))

    ranking_metrics = (
        Metric("ranking-junction-cn-deviation", _junction_deviation(junction_distances), "angstrom"),
        Metric(
            "ranking-generated-cn-deviation",
            _generated_cn_deviation(backbone_distances),
            "angstrom",
        ),
        Metric("ranking-severe-steric-overlaps", float(len(severe_clashes)), "count"),
    )
    return (
        ValidationSummary(
            passed=not failures,
            hard_gate_failures=tuple(dict.fromkeys(failures)),
            metrics=tuple(metrics),
            warnings=tuple(warnings),
        ),
        ranking_metrics,
    )


def _validated_candidate(candidate: RunnerCandidate) -> DiffusionCandidate:
    return DiffusionCandidate(
        candidate_id=candidate.candidate_id,
        seed=candidate.seed,
        coordinate_artifact=candidate.coordinate_artifact,
        sampler_trace_artifact=candidate.sampler_trace_artifact,
        generated_atoms=candidate.generated_atoms,
        generated_residues=candidate.generated_residues,
        raw_backend_score=candidate.raw_backend_score,
        score_provenance=candidate.score_provenance,
        warnings=candidate.warnings,
        postprocessing_failures=candidate.postprocessing_failures,
    )


def _ranking_key(item: CandidateValidation) -> tuple[float, float, float, float, str]:
    validation_metrics = {metric.name: metric.value for metric in item.summary.metrics}
    ranking_metrics = {metric.name: metric.value for metric in item.ranking_metrics}
    return (
        ranking_metrics["ranking-severe-steric-overlaps"],
        ranking_metrics["ranking-junction-cn-deviation"],
        ranking_metrics["ranking-generated-cn-deviation"],
        validation_metrics["fixed-heavy-atom-rmsd"],
        item.candidate.candidate_id,
    )


def _junction_deviation(distances: list[float]) -> float:
    return sum(abs(distance - 1.33) for distance in distances)


def _generated_cn_deviation(distances: list[float]) -> float:
    return sum(abs(distance - 1.33) for distance in distances)


def _expected_generated_residue_names(
    request: DiffusionRequest,
) -> dict[ResidueIdentity, str]:
    sequences = {target.chain: target.sequence for target in request.target_sequences}
    expected: dict[ResidueIdentity, str] = {}
    for gap in request.gaps:
        sequence = sequences[gap.chain][gap.target_interval.start : gap.target_interval.stop]
        if len(sequence) != len(gap.generated_residues):
            raise DiffusionValidationError("gap sequence and generated residue masks are inconsistent")
        for residue, one_letter in zip(gap.generated_residues, sequence):
            try:
                residue_name = _ONE_TO_THREE[one_letter]
            except KeyError as exc:
                raise DiffusionValidationError(
                    f"unsupported non-canonical target residue {one_letter!r}"
                ) from exc
            previous = expected.setdefault(residue, residue_name)
            if previous != residue_name:
                raise DiffusionValidationError("generated residue identity has conflicting sequences")
    return expected


def _cn_distance(
    structure: _Structure,
    left: ResidueIdentity,
    right: ResidueIdentity,
) -> float | None:
    c_atom = structure.atoms.get(AtomIdentity(left.chain, left.residue_number, left.insertion_code, "C"))
    n_atom = structure.atoms.get(AtomIdentity(right.chain, right.residue_number, right.insertion_code, "N"))
    if c_atom is None or n_atom is None:
        return None
    return float(np.linalg.norm(c_atom.coordinates_angstrom - n_atom.coordinates_angstrom))


def _residue(atom: AtomIdentity) -> ResidueIdentity:
    return ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code)


def _finding_residue(chain: str, resid: str) -> ResidueIdentity:
    number, insertion_code = _split_resid(resid)
    return ResidueIdentity(chain, number, insertion_code)


def _finding_partner_residue(finding: Any) -> ResidueIdentity | None:
    partner = finding.extra.get("clash_partner")
    if not isinstance(partner, dict):
        return None
    chain = partner.get("chain")
    resid = partner.get("resid")
    if not isinstance(chain, str) or not isinstance(resid, str):
        return None
    number, insertion_code = _split_resid(resid)
    return ResidueIdentity(chain, number, insertion_code)


def _split_resid(value: str) -> tuple[str, str]:
    if value and value[-1].isalpha():
        return value[:-1], value[-1]
    return value, ""


def _require_workspace(workspace: Path) -> Path:
    if workspace.is_symlink() or not workspace.is_dir():
        raise DiffusionValidationError("validation workspace must be a regular directory")
    return workspace.resolve(strict=True)


def _load_structure(
    workspace: Path,
    relative_path: str,
    expected_sha256: str,
) -> _Structure:
    path = workspace.joinpath(*Path(relative_path).parts)
    current = workspace
    for part in Path(relative_path).parts:
        current = current / part
        if current.is_symlink():
            raise DiffusionValidationError(f"structure path contains a symlink: {relative_path}")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise DiffusionValidationError(f"structure does not exist: {relative_path}") from exc
    if not resolved.is_relative_to(workspace):
        raise DiffusionValidationError(f"structure escapes validation workspace: {relative_path}")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise DiffusionValidationError(f"structure could not be opened safely: {relative_path}") from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
            raise DiffusionValidationError(f"structure is not a private regular file: {relative_path}")
        digest = hashlib.sha256()
        data = bytearray()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
            data.extend(chunk)
    finally:
        os.close(descriptor)
    if digest.hexdigest() != expected_sha256.lower():
        raise DiffusionValidationError(f"structure SHA-256 mismatch: {relative_path}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DiffusionValidationError(f"structure is not valid UTF-8: {relative_path}") from exc
    atoms, residues, links = _parse_pdb_text(text)
    try:
        pdb = PDBFile(StringIO(text))
    except Exception as exc:
        raise DiffusionValidationError(f"structure could not be parsed by OpenMM: {relative_path}") from exc
    return _Structure(
        path=path,
        pdb=pdb,
        atoms=atoms,
        residues=residues,
        explicit_links=frozenset(links),
    )


def _load_sampler_trace(workspace: Path, artifact: ArtifactReference) -> SamplerTrace:
    data = _read_private_artifact(workspace, artifact, max_bytes=MAX_TRACE_BYTES)
    try:
        return SamplerTrace.from_json(data.decode("utf-8"))
    except (DiffusionContractError, UnicodeDecodeError) as exc:
        raise DiffusionValidationError(
            f"sampler trace is malformed: {artifact.path}: {exc}"
        ) from exc


def _read_private_artifact(
    workspace: Path,
    artifact: ArtifactReference,
    *,
    max_bytes: int,
) -> bytes:
    relative_path = artifact.path
    path = workspace.joinpath(*Path(relative_path).parts)
    current = workspace
    for part in Path(relative_path).parts:
        current = current / part
        if current.is_symlink():
            raise DiffusionValidationError(
                f"artifact path contains a symlink: {relative_path}"
            )
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise DiffusionValidationError(f"artifact does not exist: {relative_path}") from exc
    if not resolved.is_relative_to(workspace):
        raise DiffusionValidationError(
            f"artifact escapes validation workspace: {relative_path}"
        )
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise DiffusionValidationError(
            f"artifact could not be opened safely: {relative_path}"
        ) from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
            raise DiffusionValidationError(
                f"artifact is not a private regular file: {relative_path}"
            )
        if file_stat.st_size > max_bytes:
            raise DiffusionValidationError(
                f"artifact exceeds the size limit: {relative_path}"
            )
        data = bytearray()
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            data.extend(chunk)
            digest.update(chunk)
    finally:
        os.close(descriptor)
    if digest.hexdigest() != artifact.sha256.lower():
        raise DiffusionValidationError(
            f"artifact SHA-256 mismatch: {relative_path}"
        )
    return bytes(data)


def _parse_pdb_text(
    text: str,
) -> tuple[
    dict[AtomIdentity, _AtomRecord],
    dict[ResidueIdentity, str],
    set[ExplicitLink],
]:
    lines = text.splitlines()
    if sum(line.startswith("MODEL ") for line in lines) > 1:
        raise DiffusionValidationError("multiple MODEL blocks are unsupported")
    atoms: dict[AtomIdentity, _AtomRecord] = {}
    residues: dict[ResidueIdentity, str] = {}
    serials: dict[int, AtomIdentity] = {}
    for line_number, line in enumerate(lines, 1):
        record_name = line[:6].strip()
        if record_name not in {"ATOM", "HETATM"}:
            continue
        if len(line) < 54:
            raise DiffusionValidationError(f"truncated PDB atom record on line {line_number}")
        try:
            serial = int(line[6:11])
            residue_number = line[22:26].strip()
            int(residue_number)
            coordinates = np.asarray(
                (float(line[30:38]), float(line[38:46]), float(line[46:54])),
                dtype=np.float64,
            )
        except ValueError as exc:
            raise DiffusionValidationError(f"malformed PDB atom record on line {line_number}") from exc
        if not np.all(np.isfinite(coordinates)):
            raise DiffusionValidationError(f"non-finite coordinate on line {line_number}")
        chain = line[21]
        insertion_code = line[26].strip()
        atom_name = line[12:16].strip()
        residue_name = line[17:20].strip()
        altloc = line[16].strip()
        if not atom_name or not residue_name:
            raise DiffusionValidationError(f"missing atom or residue name on line {line_number}")
        if altloc:
            raise DiffusionValidationError("alternate-location atoms are unsupported")
        identity = AtomIdentity(chain, residue_number, insertion_code, atom_name)
        residue = ResidueIdentity(chain, residue_number, insertion_code)
        if identity in atoms:
            raise DiffusionValidationError(f"duplicate atom identity on line {line_number}")
        if serial in serials:
            raise DiffusionValidationError(f"duplicate atom serial on line {line_number}")
        previous_name = residues.setdefault(residue, residue_name)
        if previous_name != residue_name:
            raise DiffusionValidationError(f"conflicting residue name on line {line_number}")
        element = line[76:78].strip() if len(line) >= 78 else ""
        if not element:
            element = next((character for character in atom_name if character.isalpha()), "")
        atoms[identity] = _AtomRecord(
            identity=identity,
            residue=residue,
            residue_name=residue_name,
            coordinates_angstrom=coordinates,
            element=element.upper(),
            serial=serial,
            record_name=record_name,
            altloc=altloc,
        )
        serials[serial] = identity

    if not atoms:
        raise DiffusionValidationError("PDB contains no coordinate records")

    links: set[ExplicitLink] = set()
    for line in lines:
        if line.startswith("CONECT"):
            serial_values: list[int] = []
            remainder = line[6:]
            while len(remainder) >= 5:
                chunk = remainder[:5].strip()
                remainder = remainder[5:]
                if chunk:
                    try:
                        serial_values.append(int(chunk))
                    except ValueError:
                        continue
            if len(serial_values) < 2 or serial_values[0] not in serials:
                continue
            source = serials[serial_values[0]]
            for target_serial in serial_values[1:]:
                target = serials.get(target_serial)
                if target is not None and source != target:
                    links.add(_link(source, target, "CONECT"))
        elif line.startswith("LINK") and len(line) >= 57:
            atom1 = _link_atom(line[21], line[22:26].strip(), line[26].strip(), line[12:16].strip())
            atom2 = _link_atom(line[51], line[52:56].strip(), line[56].strip(), line[42:46].strip())
            if atom1 in atoms and atom2 in atoms and atom1 != atom2:
                links.add(_link(atom1, atom2, "LINK"))
        elif line.startswith("SSBOND") and len(line) >= 36:
            atom1 = _link_atom(line[15], line[17:21].strip(), line[21].strip(), "SG")
            atom2 = _link_atom(line[29], line[31:35].strip(), line[35].strip(), "SG")
            if atom1 in atoms and atom2 in atoms and atom1 != atom2:
                links.add(_link(atom1, atom2, "SSBOND"))
    return atoms, residues, links


def _link_atom(chain: str, residue_number: str, insertion_code: str, atom_name: str) -> AtomIdentity:
    return AtomIdentity(chain, residue_number, insertion_code, atom_name)


def _link(atom1: AtomIdentity, atom2: AtomIdentity, source: str) -> ExplicitLink:
    first, second = sorted((atom1, atom2))
    return ExplicitLink(first, second, source.upper())


def _link_key(link: ExplicitLink) -> tuple[AtomIdentity, AtomIdentity]:
    first, second = sorted((link.atom1, link.atom2))
    return first, second


def _link_touches_outside_generated(
    link: ExplicitLink,
    generated_residues: set[ResidueIdentity],
) -> bool:
    return (
        _residue(link.atom1) not in generated_residues
        or _residue(link.atom2) not in generated_residues
    )
