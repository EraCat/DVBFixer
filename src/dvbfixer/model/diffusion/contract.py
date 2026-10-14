"""Versioned request/result contract for experimental diffusion runners."""

from __future__ import annotations

import json
import math
from dataclasses import MISSING, dataclass, fields, is_dataclass
from dataclasses import field as dataclass_field
from enum import StrEnum
from pathlib import Path
from types import UnionType
from typing import Any, ClassVar, TypeVar, Union, get_args, get_origin, get_type_hints

from dvbfixer.model.diffusion.sampler import SamplerCapabilities, SamplingAblationMode

DIFFUSION_SCHEMA_VERSION = 4
MAX_TRACE_ATOMS = 1_000_000
MAX_TRACE_BYTES = 8_000_000
MAX_TRACE_STEPS = 10_000
MAX_TRACE_PARAMETERS = 64
MAX_TRACE_TEXT_LENGTH = 512
MAX_RESOURCE_SECONDS = 31_536_000.0
MAX_RESOURCE_BYTES = 1 << 50


class DiffusionContractError(ValueError):
    """Raised when a request or result violates the diffusion protocol schema."""


class DiffusionStatus(StrEnum):
    SUCCESS = "success"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class GapKind(StrEnum):
    INTERNAL = "internal"
    N_TERMINAL = "n_terminal"
    C_TERMINAL = "c_terminal"


def _required_text(value: str, field_name: str) -> None:
    if not value:
        raise DiffusionContractError(f"{field_name} must not be empty")


def _single_character(value: str, field_name: str, *, allow_blank: bool = False) -> None:
    if len(value) != 1 or (not allow_blank and value == " "):
        raise DiffusionContractError(f"{field_name} must be exactly one non-blank character")


@dataclass(frozen=True, slots=True, order=True)
class ResidueIdentity:
    chain: str
    residue_number: str
    insertion_code: str = ""

    def __post_init__(self) -> None:
        _single_character(self.chain, "chain")
        _required_text(self.residue_number, "residue_number")
        if len(self.insertion_code) > 1:
            raise DiffusionContractError("insertion_code must contain at most one character")


@dataclass(frozen=True, slots=True, order=True)
class AtomIdentity:
    chain: str
    residue_number: str
    insertion_code: str
    atom_name: str

    def __post_init__(self) -> None:
        ResidueIdentity(self.chain, self.residue_number, self.insertion_code)
        _required_text(self.atom_name, "atom_name")
        if len(self.atom_name) > 4:
            raise DiffusionContractError("atom_name must contain at most four characters")


@dataclass(frozen=True, slots=True)
class TargetInterval:
    start: int
    stop: int

    def __post_init__(self) -> None:
        if self.start < 0:
            raise DiffusionContractError("target interval start must be non-negative")
        if self.stop <= self.start:
            raise DiffusionContractError("target interval stop must be greater than start")


@dataclass(frozen=True, slots=True)
class TargetSequence:
    chain: str
    sequence: str

    def __post_init__(self) -> None:
        _single_character(self.chain, "target sequence chain")
        _required_text(self.sequence, "target sequence")
        if not self.sequence.isalpha() or self.sequence != self.sequence.upper():
            raise DiffusionContractError("target sequence must contain uppercase alphabetic symbols")


@dataclass(frozen=True, slots=True)
class SequencePlacement:
    chain: str
    target_length: int
    observed_target_indices: tuple[int, ...]
    observed_residues: tuple[ResidueIdentity, ...]

    def __post_init__(self) -> None:
        _single_character(self.chain, "sequence placement chain")
        if self.target_length <= 0:
            raise DiffusionContractError("target_length must be positive")
        if len(self.observed_target_indices) != len(self.observed_residues):
            raise DiffusionContractError(
                "observed_target_indices and observed_residues must have equal length"
            )
        if tuple(sorted(self.observed_target_indices)) != self.observed_target_indices:
            raise DiffusionContractError("observed_target_indices must be strictly ordered")
        if len(set(self.observed_target_indices)) != len(self.observed_target_indices):
            raise DiffusionContractError("observed_target_indices must not contain duplicates")
        if any(index < 0 or index >= self.target_length for index in self.observed_target_indices):
            raise DiffusionContractError("observed target index is outside target_length")
        if any(residue.chain != self.chain for residue in self.observed_residues):
            raise DiffusionContractError("observed residue chain does not match placement chain")
        if len(set(self.observed_residues)) != len(self.observed_residues):
            raise DiffusionContractError("observed_residues must not contain duplicates")


@dataclass(frozen=True, slots=True)
class GapRegion:
    chain: str
    target_interval: TargetInterval
    left_anchor: ResidueIdentity | None
    right_anchor: ResidueIdentity | None
    generated_residues: tuple[ResidueIdentity, ...]
    movable_junction_residues: tuple[ResidueIdentity, ...]
    gap_kind: GapKind = GapKind.INTERNAL

    def __post_init__(self) -> None:
        _single_character(self.chain, "gap chain")
        if not isinstance(self.gap_kind, GapKind):
            try:
                object.__setattr__(self, "gap_kind", GapKind(self.gap_kind))
            except ValueError as exc:
                raise DiffusionContractError(f"unknown gap kind: {self.gap_kind}") from exc
        anchors = tuple(
            anchor
            for anchor in (self.left_anchor, self.right_anchor)
            if anchor is not None
        )
        if any(anchor.chain != self.chain for anchor in anchors):
            raise DiffusionContractError("gap anchors must belong to the target chain")
        if len(set(anchors)) != len(anchors):
            raise DiffusionContractError("left and right anchors must be distinct")
        if self.gap_kind is GapKind.INTERNAL and len(anchors) != 2:
            raise DiffusionContractError("internal gap requires left and right anchors")
        if self.gap_kind is GapKind.N_TERMINAL and (
            self.left_anchor is not None or self.right_anchor is None
        ):
            raise DiffusionContractError("N-terminal gap requires only a right anchor")
        if self.gap_kind is GapKind.C_TERMINAL and (
            self.left_anchor is None or self.right_anchor is not None
        ):
            raise DiffusionContractError("C-terminal gap requires only a left anchor")
        expected_count = self.target_interval.stop - self.target_interval.start
        if len(self.generated_residues) != expected_count:
            raise DiffusionContractError(
                "generated_residues length must match target_interval length"
            )
        if not self.generated_residues:
            raise DiffusionContractError("gap must contain at least one generated residue")
        if any(residue.chain != self.chain for residue in self.generated_residues):
            raise DiffusionContractError("generated residue chain does not match gap chain")
        if len(set(self.generated_residues)) != len(self.generated_residues):
            raise DiffusionContractError("generated_residues must not contain duplicates")
        if any(residue.chain != self.chain for residue in self.movable_junction_residues):
            raise DiffusionContractError(
                "movable junction residue chain does not match gap chain"
            )
        if len(set(self.movable_junction_residues)) != len(self.movable_junction_residues):
            raise DiffusionContractError(
                "movable_junction_residues must not contain duplicates"
            )
        required_movable = {*anchors, *self.generated_residues}
        if not required_movable <= set(self.movable_junction_residues):
            raise DiffusionContractError(
                "movable_junction_residues must contain every anchor and generated residue"
            )


@dataclass(frozen=True, slots=True)
class ExplicitLink:
    atom1: AtomIdentity
    atom2: AtomIdentity
    source: str

    def __post_init__(self) -> None:
        if self.atom1 == self.atom2:
            raise DiffusionContractError("explicit link endpoints must be distinct")
        _required_text(self.source, "explicit link source")


@dataclass(frozen=True, slots=True)
class HeterogenContext:
    residue: ResidueIdentity
    residue_name: str
    atoms: tuple[AtomIdentity, ...]
    canonical_smiles: str
    authoritative_graph_sha256: str
    conditioning_mode: str = "fixed-geometric-repulsion"

    def __post_init__(self) -> None:
        _required_text(self.residue_name, "heterogen residue name")
        _required_text(self.canonical_smiles, "heterogen canonical SMILES")
        _required_text(self.conditioning_mode, "heterogen conditioning mode")
        ArtifactReference("authoritative_graph", self.authoritative_graph_sha256)
        if not self.atoms or len(set(self.atoms)) != len(self.atoms):
            raise DiffusionContractError(
                "heterogen context atoms must be non-empty and unique"
            )
        if any(
            ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code)
            != self.residue
            for atom in self.atoms
        ):
            raise DiffusionContractError(
                "heterogen context atoms must belong to its declared residue"
            )


@dataclass(frozen=True, slots=True)
class TemplateOwnership:
    chain: str
    target_index: int
    residue: ResidueIdentity
    template_id: str

    def __post_init__(self) -> None:
        _single_character(self.chain, "template ownership chain")
        if self.target_index < 0:
            raise DiffusionContractError(
                "template ownership target index must be non-negative"
            )
        if self.residue.chain != self.chain:
            raise DiffusionContractError(
                "template ownership residue must belong to its declared chain"
            )
        _required_text(self.template_id, "template ownership template ID")


@dataclass(frozen=True, slots=True)
class BackendOption:
    name: str
    value: str

    def __post_init__(self) -> None:
        _required_text(self.name, "backend option name")


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    path: str
    sha256: str

    def __post_init__(self) -> None:
        _required_text(self.path, "artifact path")
        artifact_path = Path(self.path)
        if (
            artifact_path.is_absolute()
            or not artifact_path.parts
            or ".." in artifact_path.parts
            or artifact_path.name in {"", ".", ".."}
        ):
            raise DiffusionContractError("artifact path must be relative and contained")
        if len(self.sha256) != 64:
            raise DiffusionContractError("artifact sha256 must contain 64 hexadecimal characters")
        try:
            int(self.sha256, 16)
        except ValueError as exc:
            raise DiffusionContractError("artifact sha256 must be hexadecimal") from exc


@dataclass(frozen=True, slots=True)
class Metric:
    name: str
    value: float
    unit: str = ""

    def __post_init__(self) -> None:
        _required_text(self.name, "metric name")


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    passed: bool
    hard_gate_failures: tuple[str, ...] = ()
    metrics: tuple[Metric, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.passed and self.hard_gate_failures:
            raise DiffusionContractError("passing validation cannot contain hard gate failures")
        if not self.passed and not self.hard_gate_failures:
            raise DiffusionContractError("failed validation must name a hard gate failure")
        names = [metric.name for metric in self.metrics]
        if len(names) != len(set(names)):
            raise DiffusionContractError("validation metric names must be unique")


@dataclass(frozen=True, slots=True)
class RunnerDiagnostics:
    exit_code: int | None
    timed_out: bool
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True, slots=True)
class BackendProvenance:
    backend: str
    runner_protocol_version: int
    engine_repository: str
    engine_revision: str
    source_license: str = ""
    checkpoint_sha256: str = ""
    checkpoint_license: str = ""
    container_digest: str = ""
    environment_hash: str = ""
    environment_identity: str = ""
    device: str = ""
    precision: str = ""
    framework: str = ""
    framework_version: str = ""
    cuda_version: str = ""
    driver_version: str = ""
    deterministic_algorithms: bool | None = None
    deterministic_flags: tuple[str, ...] = ()
    known_nondeterministic_operations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required_text(self.backend, "backend")
        if self.runner_protocol_version <= 0:
            raise DiffusionContractError("runner_protocol_version must be positive")
        _required_text(self.engine_repository, "engine_repository")
        _required_text(self.engine_revision, "engine_revision")
        if self.checkpoint_sha256:
            ArtifactReference("checkpoint", self.checkpoint_sha256)
        if len(set(self.deterministic_flags)) != len(self.deterministic_flags):
            raise DiffusionContractError("deterministic_flags must not contain duplicates")
        if len(set(self.known_nondeterministic_operations)) != len(
            self.known_nondeterministic_operations
        ):
            raise DiffusionContractError(
                "known_nondeterministic_operations must not contain duplicates"
            )


@dataclass(frozen=True, slots=True)
class RunnerResourceMetrics:
    wall_time_seconds: float | None = None
    model_load_seconds: float | None = None
    peak_ram_bytes: int | None = None
    peak_vram_bytes: int | None = None

    def __post_init__(self) -> None:
        for value in (self.wall_time_seconds, self.model_load_seconds):
            if value is not None and (
                not math.isfinite(value)
                or value < 0
                or value > MAX_RESOURCE_SECONDS
            ):
                raise DiffusionContractError(
                    "runner resource timings must be finite and non-negative within bounds"
                )
        for value in (self.peak_ram_bytes, self.peak_vram_bytes):
            if value is not None and (value < 0 or value > MAX_RESOURCE_BYTES):
                raise DiffusionContractError(
                    "runner resource byte counts must be non-negative and within bounds"
                )


def atom_identity_digest(atoms: tuple[AtomIdentity, ...]) -> str:
    """Return the canonical digest for an ordered atom identity axis."""
    import hashlib

    payload = json.dumps(
        _encode(atoms),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def fixed_mask_digest(
    atom_order: tuple[AtomIdentity, ...],
    fixed_atoms: tuple[AtomIdentity, ...],
) -> str:
    """Return the canonical digest for the fixed mask on an atom axis."""
    import hashlib

    fixed = set(fixed_atoms)
    payload = bytes(identity in fixed for identity in atom_order)
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class ProteinContextPolicy:
    name: str = "anchor-shell-v1"
    target_flanks: int | None = None
    same_chain_spatial: bool = False
    partner_mode: str = "local"
    direct_radius_angstrom: float = 6.0
    secondary_radius_angstrom: float = 10.0
    sequence_padding: int = 2
    residue_budget: int = 512

    def __post_init__(self) -> None:
        if self.partner_mode not in {"none", "local", "full"}:
            raise DiffusionContractError("unknown protein partner selection mode")
        if self.target_flanks is not None and self.target_flanks < 1:
            raise DiffusionContractError("target flanks must retain both anchors")
        if self.sequence_padding < 0 or self.residue_budget < 1:
            raise DiffusionContractError("context padding/budget must be non-negative/positive")
        if not 0 < self.direct_radius_angstrom <= self.secondary_radius_angstrom or not math.isfinite(self.secondary_radius_angstrom):
            raise DiffusionContractError("context shell radii must be positive ordered finite distances")


@dataclass(frozen=True, slots=True)
class ProteinContextSpan:
    chain: str
    start: int
    stop: int

    def __post_init__(self) -> None:
        _single_character(self.chain, "context chain")
        if self.start < 0 or self.stop <= self.start:
            raise DiffusionContractError("context spans must be zero-based half-open")


@dataclass(frozen=True, slots=True)
class ContextCoordinate:
    atom: AtomIdentity
    coordinate_angstrom: tuple[float, float, float]

    def __post_init__(self) -> None:
        if len(self.coordinate_angstrom) != 3 or any(not math.isfinite(x) for x in self.coordinate_angstrom):
            raise DiffusionContractError("context coordinates must be finite three-vectors")


@dataclass(frozen=True, slots=True)
class ProteinContextPlan:
    policy: ProteinContextPolicy
    source_sha256: str
    spans: tuple[ProteinContextSpan, ...]
    generated: tuple[AtomIdentity, ...]
    movable_junction: tuple[AtomIdentity, ...]
    fixed_conditioning: tuple[ContextCoordinate, ...]
    preserved_only: tuple[AtomIdentity, ...]

    def __post_init__(self) -> None:
        ArtifactReference("context-source", self.source_sha256)
        roles = (self.generated, self.movable_junction, tuple(item.atom for item in self.fixed_conditioning), self.preserved_only)
        combined = tuple(atom for role in roles for atom in role)
        if len(set(combined)) != len(combined):
            raise DiffusionContractError("protein context atom roles must be disjoint and unique")
        if not self.spans or sum(span.stop - span.start for span in self.spans) > self.policy.residue_budget:
            raise DiffusionContractError("protein context axis is empty or exceeds budget")
        for i, span in enumerate(self.spans):
            if any(span.chain == other.chain and max(span.start, other.start) < min(span.stop, other.stop) for other in self.spans[:i]):
                raise DiffusionContractError("protein context spans must not overlap")


def protein_context_digest(plan: ProteinContextPlan) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(_encode(plan), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ProteinContextEvidence:
    plan_sha256: str
    mapping_sha256: str
    selected_coordinate_sha256: str
    selected_atoms: tuple[AtomIdentity, ...]
    preserved_atoms: tuple[AtomIdentity, ...]
    alignment_atoms: tuple[AtomIdentity, ...]
    capability: str

    def __post_init__(self) -> None:
        for digest in (self.plan_sha256, self.mapping_sha256, self.selected_coordinate_sha256):
            ArtifactReference("context-evidence", digest)
        if self.capability not in {"gap-only", "same-chain-conditioned", "multichain-conditioned"}:
            raise DiffusionContractError("unknown protein context capability")
        if not self.alignment_atoms or not set(self.alignment_atoms) <= set(self.selected_atoms):
            raise DiffusionContractError("context frame alignment must use selected fixed atoms")


@dataclass(frozen=True, slots=True)
class SamplerStepTrace:
    step_index: int
    atom_identity_sha256: str
    post_projection_max_error_angstrom: float

    def __post_init__(self) -> None:
        if self.step_index < 0:
            raise DiffusionContractError("sampler step index must be non-negative")
        ArtifactReference("atom_identity_sha256", self.atom_identity_sha256)
        for value in (self.post_projection_max_error_angstrom,):
            if not math.isfinite(value) or value < 0:
                raise DiffusionContractError(
                    "sampler projection errors must be finite and non-negative"
                )


@dataclass(frozen=True, slots=True)
class SamplerConditioningContext:
    target_chain: str
    partner_chains: tuple[str, ...]
    partner_atoms: tuple[AtomIdentity, ...]

    def __post_init__(self) -> None:
        _single_character(self.target_chain, "conditioning target chain")
        if not self.partner_chains:
            raise DiffusionContractError(
                "conditioning context must contain at least one partner chain"
            )
        if len(set(self.partner_chains)) != len(self.partner_chains):
            raise DiffusionContractError("conditioning partner chains must be unique")
        for chain in self.partner_chains:
            _single_character(chain, "conditioning partner chain")
        if self.target_chain in self.partner_chains:
            raise DiffusionContractError(
                "conditioning target chain cannot also be a partner chain"
            )
        if not self.partner_atoms or len(set(self.partner_atoms)) != len(self.partner_atoms):
            raise DiffusionContractError(
                "conditioning partner atoms must be non-empty and unique"
            )
        if any(atom.chain not in self.partner_chains for atom in self.partner_atoms):
            raise DiffusionContractError(
                "conditioning partner atom chain is not declared by the context"
            )


@dataclass(frozen=True, slots=True)
class SamplerTrace:
    schema_version: int
    profile: str
    capabilities: SamplerCapabilities
    engine_repository: str
    engine_revision: str
    patch_identity: str
    atom_order: tuple[AtomIdentity, ...]
    atom_order_sha256: str
    fixed_mask_sha256: str
    ablation_mode: SamplingAblationMode
    fixed_atoms: tuple[AtomIdentity, ...]
    represented_fixed_atoms: tuple[AtomIdentity, ...]
    fixed_tolerance_angstrom: float
    steps: tuple[SamplerStepTrace, ...]
    callback_update_count: int | None
    denoising_update_count: int | None
    max_projection_error_angstrom: float | None
    sampler_evidence_complete: bool
    final_fixed_coordinate_restoration: bool
    refinement_mode: str
    refinement_parameters: tuple[BackendOption, ...]
    device: str
    fallback_disabled: bool
    resource_metrics: RunnerResourceMetrics
    localized_refinement_residues: tuple[ResidueIdentity, ...] = ()
    final_heavy_coordinate_operations: tuple[str, ...] = ()
    conditioning_contexts: tuple[SamplerConditioningContext, ...] = ()
    conditioned_heterogen_atoms: tuple[AtomIdentity, ...] = ()
    protein_context_evidence: ProteinContextEvidence | None = dataclass_field(default=None, metadata={"omit_if_none": True})

    def __post_init__(self) -> None:
        if self.schema_version != DIFFUSION_SCHEMA_VERSION:
            raise DiffusionContractError(
                f"unsupported schema_version {self.schema_version}; "
                f"expected {DIFFUSION_SCHEMA_VERSION}"
            )
        for field_name, value in (
            ("profile", self.profile),
            ("engine_repository", self.engine_repository),
            ("engine_revision", self.engine_revision),
            ("patch_identity", self.patch_identity),
            ("refinement_mode", self.refinement_mode),
            ("device", self.device),
        ):
            _required_text(value, field_name)
            if len(value) > MAX_TRACE_TEXT_LENGTH:
                raise DiffusionContractError(
                    f"sampler trace {field_name} exceeds {MAX_TRACE_TEXT_LENGTH} characters"
                )
        if len(self.atom_order) > MAX_TRACE_ATOMS:
            raise DiffusionContractError("sampler trace atom order exceeds its count limit")
        if not self.atom_order or len(set(self.atom_order)) != len(self.atom_order):
            raise DiffusionContractError(
                "sampler trace atom_order must be non-empty and contain no duplicates"
            )
        if self.atom_order_sha256 != atom_identity_digest(self.atom_order):
            raise DiffusionContractError("sampler trace atom-order digest mismatch")
        if self.fixed_mask_sha256 != fixed_mask_digest(
            self.atom_order,
            self.represented_fixed_atoms,
        ):
            raise DiffusionContractError("sampler trace fixed-mask digest mismatch")
        if not isinstance(self.ablation_mode, SamplingAblationMode):
            try:
                object.__setattr__(
                    self,
                    "ablation_mode",
                    SamplingAblationMode(self.ablation_mode),
                )
            except ValueError as exc:
                raise DiffusionContractError(
                    f"unknown sampling ablation mode: {self.ablation_mode}"
                ) from exc
        if not self.fixed_atoms:
            raise DiffusionContractError("sampler trace fixed_atoms must not be empty")
        if len(set(self.fixed_atoms)) != len(self.fixed_atoms):
            raise DiffusionContractError("sampler trace fixed_atoms must not contain duplicates")
        if len(set(self.represented_fixed_atoms)) != len(self.represented_fixed_atoms):
            raise DiffusionContractError(
                "sampler trace represented_fixed_atoms must not contain duplicates"
            )
        if self.protein_context_evidence is not None:
            evidence = self.protein_context_evidence
            if self.represented_fixed_atoms != evidence.selected_atoms:
                raise DiffusionContractError("context evidence changed represented fixed atoms")
            if set(evidence.selected_atoms) & set(evidence.preserved_atoms) or set(evidence.selected_atoms) | set(evidence.preserved_atoms) != set(self.fixed_atoms):
                raise DiffusionContractError("context evidence must partition the fixed atom mask")
        if not math.isfinite(self.fixed_tolerance_angstrom) or self.fixed_tolerance_angstrom < 0:
            raise DiffusionContractError(
                "sampler trace fixed tolerance must be finite and non-negative"
            )
        if not set(self.represented_fixed_atoms) <= set(self.fixed_atoms):
            raise DiffusionContractError(
                "represented fixed atoms must be a subset of request fixed atoms"
            )
        if not set(self.represented_fixed_atoms) <= set(self.atom_order):
            raise DiffusionContractError(
                "represented fixed atoms must be present on atom_order"
            )
        context_targets = [context.target_chain for context in self.conditioning_contexts]
        if len(context_targets) != len(set(context_targets)):
            raise DiffusionContractError(
                "sampler conditioning contexts must have unique target chains"
            )
        if any(
            not set(context.partner_atoms) <= set(self.represented_fixed_atoms)
            for context in self.conditioning_contexts
        ):
            raise DiffusionContractError(
                "conditioning partner atoms must be represented fixed atoms"
            )
        if len(set(self.conditioned_heterogen_atoms)) != len(
            self.conditioned_heterogen_atoms
        ):
            raise DiffusionContractError(
                "conditioned heterogen atoms must not contain duplicates"
            )
        if not set(self.conditioned_heterogen_atoms) <= set(
            self.represented_fixed_atoms
        ):
            raise DiffusionContractError(
                "conditioned heterogen atoms must be represented fixed atoms"
            )
        if len(self.steps) > MAX_TRACE_STEPS:
            raise DiffusionContractError("sampler trace exceeds its step count limit")
        if self.sampler_evidence_complete:
            if self.callback_update_count is None or self.denoising_update_count is None:
                raise DiffusionContractError(
                    "complete sampler evidence requires callback and denoising counts"
                )
            if self.callback_update_count < 0 or self.denoising_update_count < 0:
                raise DiffusionContractError(
                    "sampler callback and denoising update counts must be non-negative"
                )
            if self.callback_update_count != len(self.steps):
                raise DiffusionContractError(
                    "sampler callback count must equal recorded step count"
                )
        elif (
            self.callback_update_count is not None
            or self.denoising_update_count is not None
            or self.steps
            or self.max_projection_error_angstrom is not None
        ):
            raise DiffusionContractError(
                "incomplete sampler evidence cannot claim counts or projection steps"
            )
        if self.steps:
            if (
                self.max_projection_error_angstrom is None
                or not math.isfinite(self.max_projection_error_angstrom)
                or self.max_projection_error_angstrom < 0
            ):
                raise DiffusionContractError(
                    "maximum projection error must be finite and non-negative"
                )
            observed_max = max(
                step.post_projection_max_error_angstrom for step in self.steps
            )
            if self.max_projection_error_angstrom != observed_max:
                raise DiffusionContractError(
                    "maximum projection error does not match step evidence"
                )
        elif self.max_projection_error_angstrom is not None:
            raise DiffusionContractError(
                "maximum projection error requires per-step projection evidence"
            )
        if len(self.refinement_parameters) > MAX_TRACE_PARAMETERS:
            raise DiffusionContractError("sampler trace has too many refinement parameters")
        parameter_names = [parameter.name for parameter in self.refinement_parameters]
        if len(parameter_names) != len(set(parameter_names)):
            raise DiffusionContractError("refinement parameter names must be unique")
        if any(
            len(parameter.name) > MAX_TRACE_TEXT_LENGTH
            or len(parameter.value) > MAX_TRACE_TEXT_LENGTH
            for parameter in self.refinement_parameters
        ):
            raise DiffusionContractError("refinement parameter text exceeds its length limit")
        if self.ablation_mode is SamplingAblationMode.TEMPLATE_ONLY:
            if self.steps:
                raise DiffusionContractError(
                    "template-only sampler trace cannot claim per-step projection evidence"
                )
        elif not self.steps:
            raise DiffusionContractError(
                "reinjection sampler trace must contain per-step projection evidence"
            )
        indices = tuple(step.step_index for step in self.steps)
        if indices != tuple(range(len(self.steps))):
            raise DiffusionContractError(
                "sampler trace step indices must be contiguous and start at zero"
            )
        if any(
            step.atom_identity_sha256 != self.atom_order_sha256
            for step in self.steps
        ):
            raise DiffusionContractError(
                "sampler step atom identity digest must match atom_order_sha256"
            )
        if any(
            step.post_projection_max_error_angstrom > self.fixed_tolerance_angstrom
            for step in self.steps
        ):
            raise DiffusionContractError(
                "sampler trace post-projection error exceeds fixed tolerance"
            )
        if len(set(self.localized_refinement_residues)) != len(
            self.localized_refinement_residues
        ):
            raise DiffusionContractError(
                "localized refinement residues must not contain duplicates"
            )
        if self.refinement_mode != "none" and not self.localized_refinement_residues:
            raise DiffusionContractError(
                "boundary-refinement trace must name localized refinement residues"
            )
        if self.refinement_mode == "none" and self.localized_refinement_residues:
            raise DiffusionContractError(
                "localized refinement residues require a refinement mode"
            )
        if any(not operation for operation in self.final_heavy_coordinate_operations):
            raise DiffusionContractError(
                "final heavy-coordinate operation names must not be empty"
            )
        if len(self.final_heavy_coordinate_operations) > MAX_TRACE_PARAMETERS or any(
            len(operation) > MAX_TRACE_TEXT_LENGTH
            for operation in self.final_heavy_coordinate_operations
        ):
            raise DiffusionContractError(
                "final heavy-coordinate operations exceed trace bounds"
            )
        if self.profile == "protenix-v1-cuda":
            if not self.sampler_evidence_complete:
                raise DiffusionContractError(
                    "Protenix production profile requires complete sampler evidence"
                )
            if self.protein_context_evidence is None and self.represented_fixed_atoms != self.fixed_atoms:
                raise DiffusionContractError(
                    "Protenix profile requires every fixed atom on the sampler axis"
                )
            if not self.capabilities.supports_per_step_reinjection():
                raise DiffusionContractError("Protenix profile must claim reinjection capabilities")
            if (
                self.callback_update_count != 200
                or self.denoising_update_count != 200
                or len(self.steps) != 200
            ):
                raise DiffusionContractError(
                    "Protenix profile requires evidence for every denoising update"
                )
            if not self.device.startswith("cuda") or not self.fallback_disabled:
                raise DiffusionContractError(
                    "Protenix profile requires CUDA with fallback disabled"
                )
        if self.profile == "protpardelle-1c-mps":
            if not self.sampler_evidence_complete:
                raise DiffusionContractError(
                    "Apple production profile requires complete sampler evidence"
                )
            if self.capabilities.supports_per_step_reinjection():
                raise DiffusionContractError(
                    "Apple profile cannot claim per-step reinjection capability"
                )
            if self.callback_update_count or self.steps:
                raise DiffusionContractError("Apple profile must record zero callbacks")
            if self.denoising_update_count != 500:
                raise DiffusionContractError(
                    "Apple profile must record exactly 500 denoising updates"
                )
            if not self.final_fixed_coordinate_restoration:
                raise DiffusionContractError(
                    "Apple profile must record final fixed-coordinate restoration"
                )
            if self.device != "mps" or not self.fallback_disabled:
                raise DiffusionContractError(
                    "Apple profile requires MPS with fallback disabled"
                )

    def to_dict(self) -> dict[str, Any]:
        return _encode(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SamplerTrace:
        if not isinstance(raw, dict):
            raise DiffusionContractError("SamplerTrace must be a JSON object")
        return _decode_dataclass(cls, raw)

    @classmethod
    def from_json(cls, text: str) -> SamplerTrace:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DiffusionContractError(f"invalid JSON: {exc.msg}") from exc
        if not isinstance(raw, dict):
            raise DiffusionContractError("SamplerTrace must be a JSON object")
        return cls.from_dict(raw)


@dataclass(frozen=True, slots=True)
class DiffusionCandidate:
    candidate_id: str
    seed: int
    coordinate_artifact: ArtifactReference
    sampler_trace_artifact: ArtifactReference
    generated_atoms: tuple[AtomIdentity, ...]
    generated_residues: tuple[ResidueIdentity, ...]
    raw_backend_score: float | None
    score_provenance: str
    warnings: tuple[str, ...] = ()
    postprocessing_failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required_text(self.candidate_id, "candidate_id")
        if self.seed < 0:
            raise DiffusionContractError("candidate seed must be non-negative")
        _required_text(self.score_provenance, "score_provenance")
        if len(set(self.generated_atoms)) != len(self.generated_atoms):
            raise DiffusionContractError("generated_atoms must not contain duplicates")
        if len(set(self.generated_residues)) != len(self.generated_residues):
            raise DiffusionContractError("generated_residues must not contain duplicates")
        if len(set(self.postprocessing_failures)) != len(self.postprocessing_failures):
            raise DiffusionContractError("postprocessing_failures must not contain duplicates")
        for failure in self.postprocessing_failures:
            _required_text(failure, "postprocessing failure")


@dataclass(frozen=True, slots=True)
class RunnerCandidate:
    candidate_id: str
    seed: int
    coordinate_artifact: ArtifactReference
    sampler_trace_artifact: ArtifactReference
    generated_atoms: tuple[AtomIdentity, ...]
    generated_residues: tuple[ResidueIdentity, ...]
    raw_backend_score: float | None
    score_provenance: str
    warnings: tuple[str, ...] = ()
    postprocessing_failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required_text(self.candidate_id, "candidate_id")
        if self.seed < 0:
            raise DiffusionContractError("candidate seed must be non-negative")
        _required_text(self.score_provenance, "score_provenance")
        if len(set(self.generated_atoms)) != len(self.generated_atoms):
            raise DiffusionContractError("generated_atoms must not contain duplicates")
        if len(set(self.generated_residues)) != len(self.generated_residues):
            raise DiffusionContractError("generated_residues must not contain duplicates")
        if len(set(self.postprocessing_failures)) != len(self.postprocessing_failures):
            raise DiffusionContractError("postprocessing_failures must not contain duplicates")
        for failure in self.postprocessing_failures:
            _required_text(failure, "postprocessing failure")


T = TypeVar("T", bound="_JsonContract")


@dataclass(frozen=True, slots=True)
class _JsonContract:
    schema_version: int

    _schema_version: ClassVar[int] = DIFFUSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != self._schema_version:
            raise DiffusionContractError(
                f"unsupported schema_version {self.schema_version}; "
                f"expected {self._schema_version}"
            )

    def to_dict(self) -> dict[str, Any]:
        return _encode(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls: type[T], raw: dict[str, Any]) -> T:
        if not isinstance(raw, dict):
            raise DiffusionContractError(f"{cls.__name__} must be a JSON object")
        return _decode_dataclass(cls, raw)

    @classmethod
    def from_json(cls: type[T], text: str) -> T:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DiffusionContractError(f"invalid JSON: {exc.msg}") from exc
        if not isinstance(raw, dict):
            raise DiffusionContractError(f"{cls.__name__} must be a JSON object")
        return cls.from_dict(raw)


@dataclass(frozen=True, slots=True)
class DiffusionRequest(_JsonContract):
    normalized_pdb: ArtifactReference
    target_sequences: tuple[TargetSequence, ...]
    sequence_placements: tuple[SequencePlacement, ...]
    gaps: tuple[GapRegion, ...]
    fixed_atoms: tuple[AtomIdentity, ...]
    generated_atoms: tuple[AtomIdentity, ...]
    retained_explicit_links: tuple[ExplicitLink, ...]
    candidate_count: int
    seeds: tuple[int, ...]
    backend_options: tuple[BackendOption, ...] = ()
    heterogen_contexts: tuple[HeterogenContext, ...] = ()
    template_ownership: tuple[TemplateOwnership, ...] = ()
    protein_context: ProteinContextPlan | None = dataclass_field(default=None, metadata={"omit_if_none": True})
    regenerated_template_ownership: tuple[TemplateOwnership, ...] | None = dataclass_field(default=None, metadata={"omit_if_none": True})

    def __post_init__(self) -> None:
        super(DiffusionRequest, self).__post_init__()
        if not self.target_sequences:
            raise DiffusionContractError("target_sequences must not be empty")
        if not self.sequence_placements:
            raise DiffusionContractError("sequence_placements must not be empty")
        if not self.gaps:
            raise DiffusionContractError("gaps must not be empty")
        sequence_chains = [sequence.chain for sequence in self.target_sequences]
        placement_chains = [placement.chain for placement in self.sequence_placements]
        if len(sequence_chains) != len(set(sequence_chains)):
            raise DiffusionContractError("target sequence chains must be unique")
        if len(placement_chains) != len(set(placement_chains)):
            raise DiffusionContractError("sequence placement chains must be unique")
        if set(sequence_chains) != set(placement_chains):
            raise DiffusionContractError(
                "target_sequences and sequence_placements must cover the same chains"
            )
        lengths = {sequence.chain: len(sequence.sequence) for sequence in self.target_sequences}
        if any(lengths[placement.chain] != placement.target_length for placement in self.sequence_placements):
            raise DiffusionContractError("sequence placement target_length does not match sequence")
        if any(gap.chain not in lengths for gap in self.gaps):
            raise DiffusionContractError("gap references a chain without a target sequence")
        if self.candidate_count <= 0:
            raise DiffusionContractError("candidate_count must be positive")
        if len(self.seeds) != self.candidate_count:
            raise DiffusionContractError("seeds length must match candidate_count")
        if len(set(self.seeds)) != len(self.seeds):
            raise DiffusionContractError("seeds must be unique")
        if any(seed < 0 for seed in self.seeds):
            raise DiffusionContractError("seeds must be non-negative")
        if len(set(self.fixed_atoms)) != len(self.fixed_atoms):
            raise DiffusionContractError("fixed_atoms must not contain duplicates")
        if len(set(self.generated_atoms)) != len(self.generated_atoms):
            raise DiffusionContractError("generated_atoms must not contain duplicates")
        overlap = set(self.fixed_atoms) & set(self.generated_atoms)
        if overlap:
            raise DiffusionContractError("fixed_atoms and generated_atoms must be disjoint")
        if self.protein_context is not None:
            context = self.protein_context
            if context.source_sha256 != self.normalized_pdb.sha256:
                raise DiffusionContractError("protein context source digest does not match request")
            if set(context.generated) | set(context.movable_junction) != set(self.generated_atoms):
                raise DiffusionContractError("mutable context roles must cover requested generated atoms")
            if {item.atom for item in context.fixed_conditioning} | set(context.preserved_only) != set(self.fixed_atoms):
                raise DiffusionContractError("fixed context roles must cover requested fixed atoms")
            for span in context.spans:
                if span.chain not in lengths or span.stop > lengths[span.chain]:
                    raise DiffusionContractError("context span exceeds target chain sequence")
        context_residues = [context.residue for context in self.heterogen_contexts]
        if len(context_residues) != len(set(context_residues)):
            raise DiffusionContractError("heterogen context residues must be unique")
        context_atoms = {
            atom for context in self.heterogen_contexts for atom in context.atoms
        }
        if not context_atoms <= set(self.fixed_atoms):
            raise DiffusionContractError(
                "heterogen context atoms must be part of the fixed atom mask"
            )
        ownership_keys = [
            (ownership.chain, ownership.target_index)
            for ownership in self.template_ownership
        ]
        if len(ownership_keys) != len(set(ownership_keys)):
            raise DiffusionContractError("template ownership positions must be unique")
        fixed_residues = {
            ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code)
            for atom in self.fixed_atoms
        }
        if any(
            ownership.residue not in fixed_residues
            for ownership in self.template_ownership
        ):
            raise DiffusionContractError(
                "template-owned residues must be represented by fixed atoms"
            )
        target_lengths = {
            target.chain: len(target.sequence) for target in self.target_sequences
        }
        placement_maps = {
            placement.chain: dict(zip(
                placement.observed_target_indices,
                placement.observed_residues,
            ))
            for placement in self.sequence_placements
        }
        if any(
            ownership.chain not in target_lengths
            or ownership.target_index >= target_lengths[ownership.chain]
            or placement_maps.get(ownership.chain, {}).get(ownership.target_index)
            != ownership.residue
            for ownership in self.template_ownership
        ):
            raise DiffusionContractError(
                "template ownership must match an observed target placement"
            )
        if self.regenerated_template_ownership is not None:
            generated_placements = {
                (gap.chain, index): residue for gap in self.gaps
                for index, residue in zip(range(gap.target_interval.start, gap.target_interval.stop), gap.generated_residues)
            }
            keys = [(owner.chain, owner.target_index) for owner in self.regenerated_template_ownership]
            if len(set(keys)) != len(keys) or any(
                generated_placements.get((owner.chain, owner.target_index)) != owner.residue
                for owner in self.regenerated_template_ownership
            ):
                raise DiffusionContractError("regenerated template ownership must match generated target placements")
        option_names = [option.name for option in self.backend_options]
        if len(option_names) != len(set(option_names)):
            raise DiffusionContractError("backend option names must be unique")


@dataclass(frozen=True, slots=True)
class RunnerResult(_JsonContract):
    status: DiffusionStatus
    candidates: tuple[RunnerCandidate, ...]
    runner_diagnostics: RunnerDiagnostics
    backend_provenance: BackendProvenance
    resource_metrics: RunnerResourceMetrics = RunnerResourceMetrics()
    message: str = ""

    def __post_init__(self) -> None:
        super(RunnerResult, self).__post_init__()
        if not isinstance(self.status, DiffusionStatus):
            try:
                object.__setattr__(self, "status", DiffusionStatus(self.status))
            except ValueError as exc:
                raise DiffusionContractError(f"unknown diffusion status: {self.status}") from exc
        if self.status is DiffusionStatus.SUCCESS and not self.candidates:
            raise DiffusionContractError("successful runner result must contain candidates")
        if self.status is not DiffusionStatus.SUCCESS and self.candidates:
            raise DiffusionContractError(
                "unsupported or failed runner result cannot contain candidates"
            )
        if self.status is DiffusionStatus.UNSUPPORTED and not self.message:
            raise DiffusionContractError("unsupported runner result must include a message")


@dataclass(frozen=True, slots=True)
class DiffusionResult(_JsonContract):
    status: DiffusionStatus
    candidates: tuple[DiffusionCandidate, ...]
    validation_summaries: tuple[ValidationSummary, ...]
    runner_diagnostics: RunnerDiagnostics
    backend_provenance: BackendProvenance
    resource_metrics: RunnerResourceMetrics = RunnerResourceMetrics()
    message: str = ""

    def __post_init__(self) -> None:
        super(DiffusionResult, self).__post_init__()
        if not isinstance(self.status, DiffusionStatus):
            try:
                object.__setattr__(self, "status", DiffusionStatus(self.status))
            except ValueError as exc:
                raise DiffusionContractError(f"unknown diffusion status: {self.status}") from exc
        if self.status is DiffusionStatus.SUCCESS:
            if not self.candidates:
                raise DiffusionContractError("successful result must contain candidates")
            if len(self.candidates) != len(self.validation_summaries):
                raise DiffusionContractError(
                    "successful result must contain one validation summary per candidate"
                )
            if not all(summary.passed for summary in self.validation_summaries):
                raise DiffusionContractError("successful result cannot contain failed validation")
        elif self.status is DiffusionStatus.FAILED and self.candidates:
            if len(self.candidates) != len(self.validation_summaries):
                raise DiffusionContractError(
                    "failed result candidates require matching validation summaries"
                )
            if any(summary.passed for summary in self.validation_summaries):
                raise DiffusionContractError(
                    "failed result cannot contain a passing published candidate"
                )
        elif self.candidates:
            raise DiffusionContractError("unsupported result cannot publish candidates")
        if self.status is DiffusionStatus.UNSUPPORTED and not self.message:
            raise DiffusionContractError("unsupported result must include a message")


def _encode(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {item.name: _encode(getattr(value, item.name)) for item in fields(value)
                if not (item.metadata.get("omit_if_none") and getattr(value, item.name) is None)}
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported contract value: {type(value).__name__}")


def _decode_dataclass(cls: type[Any], raw: dict[str, Any]) -> Any:
    expected = {field.name for field in fields(cls)}
    unknown = set(raw) - expected
    missing = {
        field.name
        for field in fields(cls)
        if field.name not in raw
        and field.default is MISSING
        and field.default_factory is MISSING
    }
    if unknown:
        raise DiffusionContractError(
            f"{cls.__name__} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    if missing:
        raise DiffusionContractError(
            f"{cls.__name__} is missing fields: {', '.join(sorted(missing))}"
        )
    hints = get_type_hints(cls)
    values: dict[str, Any] = {}
    for field in fields(cls):
        if field.name in raw:
            values[field.name] = _decode_value(hints[field.name], raw[field.name], field.name)
    try:
        return cls(**values)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, DiffusionContractError):
            raise
        raise DiffusionContractError(f"invalid {cls.__name__}: {exc}") from exc


def _decode_value(annotation: Any, value: Any, field_name: str) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is tuple:
        if not isinstance(value, list):
            raise DiffusionContractError(f"{field_name} must be a JSON array")
        item_type = args[0]
        return tuple(_decode_value(item_type, item, field_name) for item in value)
    if origin in {Union, UnionType}:
        if value is None and type(None) in args:
            return None
        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) == 1:
            return _decode_value(non_none[0], value, field_name)
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        if not isinstance(value, str):
            raise DiffusionContractError(f"{field_name} must be a string")
        try:
            return annotation(value)
        except ValueError as exc:
            raise DiffusionContractError(f"{field_name} has unknown value {value!r}") from exc
    if isinstance(annotation, type) and is_dataclass(annotation):
        if not isinstance(value, dict):
            raise DiffusionContractError(f"{field_name} must be a JSON object")
        return _decode_dataclass(annotation, value)
    if annotation is bool:
        if type(value) is not bool:
            raise DiffusionContractError(f"{field_name} must be a boolean")
        return value
    if annotation is int:
        if type(value) is not int:
            raise DiffusionContractError(f"{field_name} must be an integer")
        return value
    if annotation is float:
        if type(value) not in {int, float}:
            raise DiffusionContractError(f"{field_name} must be a number")
        return float(value)
    if annotation is str:
        if not isinstance(value, str):
            raise DiffusionContractError(f"{field_name} must be a string")
        return value
    raise DiffusionContractError(f"unsupported schema annotation for {field_name}")
