"""Versioned provenance manifests for published diffusion bundles."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dvbfixer import __version__
from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    ArtifactReference,
    AtomIdentity,
    BackendProvenance,
    DiffusionCandidate,
    DiffusionContractError,
    DiffusionRequest,
    HeterogenContext,
    ProteinContextPlan,
    RunnerDiagnostics,
    RunnerResourceMetrics,
    TargetSequence,
    TemplateOwnership,
    ValidationSummary,
)
from dvbfixer.model.diffusion.preflight import DIFFUSION_PROFILES

DIFFUSION_PROVENANCE_SCHEMA_VERSION = 4


@dataclass(frozen=True, slots=True)
class PublicationArtifact:
    role: str
    path: str
    sha256: str

    def __post_init__(self) -> None:
        if not self.role:
            raise DiffusionContractError("publication artifact role must not be empty")
        ArtifactReference(self.path, self.sha256)


@dataclass(frozen=True, slots=True)
class DiagnosticSummary:
    exit_code: int | None
    timed_out: bool
    stdout_bytes: int
    stderr_bytes: int

    def __post_init__(self) -> None:
        if self.stdout_bytes < 0 or self.stderr_bytes < 0:
            raise DiffusionContractError("diagnostic byte counts must be non-negative")


@dataclass(frozen=True, slots=True)
class DiffusionProvenanceManifest:
    schema_version: int
    diffusion_contract_schema_version: int
    dvbfixer_version: str
    dvbfixer_commit: str
    request_sha256: str
    normalized_pdb: ArtifactReference
    target_sequences: tuple[TargetSequence, ...]
    gaps: tuple[dict[str, Any], ...]
    fixed_atoms: tuple[AtomIdentity, ...]
    generated_atoms: tuple[AtomIdentity, ...]
    heterogen_contexts: tuple[HeterogenContext, ...]
    template_ownership: tuple[TemplateOwnership, ...]
    requested_profile: str
    profile_status: str
    profile_evidence_labels: tuple[str, ...]
    training_membership_status: str
    candidate: DiffusionCandidate
    validation_summary: ValidationSummary
    backend_provenance: BackendProvenance
    runner_diagnostics: DiagnosticSummary
    resource_metrics: RunnerResourceMetrics
    artifacts: tuple[PublicationArtifact, ...]
    protein_context: ProteinContextPlan | None = None
    regenerated_template_ownership: tuple[TemplateOwnership, ...] | None = None

    def __post_init__(self) -> None:
        if self.schema_version != DIFFUSION_PROVENANCE_SCHEMA_VERSION:
            raise DiffusionContractError(
                "unsupported diffusion provenance schema_version "
                f"{self.schema_version}; expected "
                f"{DIFFUSION_PROVENANCE_SCHEMA_VERSION}"
            )
        if self.diffusion_contract_schema_version != DIFFUSION_SCHEMA_VERSION:
            raise DiffusionContractError(
                "diffusion provenance contract schema version mismatch"
            )
        ArtifactReference("request.json", self.request_sha256)
        if not self.dvbfixer_version:
            raise DiffusionContractError("dvbfixer_version must not be empty")
        if not self.dvbfixer_commit:
            raise DiffusionContractError("dvbfixer_commit must not be empty")
        if len(set(self.profile_evidence_labels)) != len(self.profile_evidence_labels):
            raise DiffusionContractError("profile evidence labels must be unique")
        roles = [artifact.role for artifact in self.artifacts]
        if len(roles) != len(set(roles)):
            raise DiffusionContractError("publication artifact roles must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "diffusion_contract_schema_version": (
                self.diffusion_contract_schema_version
            ),
            "dvbfixer": {
                "version": self.dvbfixer_version,
                "commit": self.dvbfixer_commit,
            },
            "request_sha256": self.request_sha256,
            "normalized_pdb": _encode(self.normalized_pdb),
            "target_sequences": _encode(self.target_sequences),
            "gaps": list(self.gaps),
            "fixed_atoms": _encode(self.fixed_atoms),
            "generated_atoms": _encode(self.generated_atoms),
            "heterogen_contexts": _encode(self.heterogen_contexts),
            "template_ownership": _encode(self.template_ownership),
            **({"protein_context": _encode(self.protein_context)} if self.protein_context is not None else {}),
            **({"regenerated_template_ownership": _encode(self.regenerated_template_ownership)} if self.regenerated_template_ownership is not None else {}),
            "requested_profile": self.requested_profile,
            "profile_status": self.profile_status,
            "profile_evidence_labels": list(self.profile_evidence_labels),
            "training_membership_status": self.training_membership_status,
            "candidate": _encode(self.candidate),
            "validation_summary": _encode(self.validation_summary),
            "backend_provenance": _encode(self.backend_provenance),
            "runner_diagnostics": _encode(self.runner_diagnostics),
            "resource_metrics": _encode(self.resource_metrics),
            "artifacts": _encode(self.artifacts),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ) + "\n"


def build_provenance_manifest(
    request: DiffusionRequest,
    candidate: DiffusionCandidate,
    validation_summary: ValidationSummary,
    backend_provenance: BackendProvenance,
    runner_diagnostics: RunnerDiagnostics,
    artifacts: tuple[PublicationArtifact, ...],
    *,
    resource_metrics: RunnerResourceMetrics | None = None,
    repository_root: Path | None = None,
) -> DiffusionProvenanceManifest:
    """Build a credential-free manifest from independently validated data."""
    requested_profile = next(
        (
            option.value
            for option in request.backend_options
            if option.name == "profile"
        ),
        "",
    )
    profile = DIFFUSION_PROFILES.get(requested_profile)
    return DiffusionProvenanceManifest(
        schema_version=DIFFUSION_PROVENANCE_SCHEMA_VERSION,
        diffusion_contract_schema_version=DIFFUSION_SCHEMA_VERSION,
        dvbfixer_version=__version__,
        dvbfixer_commit=_git_commit(repository_root),
        request_sha256=hashlib.sha256(request.to_json().encode("utf-8")).hexdigest(),
        normalized_pdb=request.normalized_pdb,
        target_sequences=request.target_sequences,
        gaps=tuple(_gap_dict(gap) for gap in request.gaps),
        fixed_atoms=request.fixed_atoms,
        generated_atoms=request.generated_atoms,
        heterogen_contexts=request.heterogen_contexts,
        template_ownership=request.template_ownership,
        protein_context=request.protein_context,
        regenerated_template_ownership=request.regenerated_template_ownership,
        requested_profile=requested_profile,
        profile_status=profile.status if profile is not None else "unregistered",
        profile_evidence_labels=profile.evidence_labels if profile is not None else (),
        training_membership_status=(
            profile.training_membership_status if profile is not None else "unknown"
        ),
        candidate=candidate,
        validation_summary=validation_summary,
        backend_provenance=backend_provenance,
        runner_diagnostics=DiagnosticSummary(
            exit_code=runner_diagnostics.exit_code,
            timed_out=runner_diagnostics.timed_out,
            stdout_bytes=len(runner_diagnostics.stdout.encode("utf-8")),
            stderr_bytes=len(runner_diagnostics.stderr.encode("utf-8")),
        ),
        resource_metrics=resource_metrics or RunnerResourceMetrics(),
        artifacts=artifacts,
    )


def _git_commit(repository_root: Path | None) -> str:
    if repository_root is None:
        return "unknown"
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    commit = completed.stdout.strip().lower()
    if len(commit) != 40:
        return "unknown"
    try:
        int(commit, 16)
    except ValueError:
        return "unknown"
    return commit


def _gap_dict(gap: Any) -> dict[str, Any]:
    return {
        "chain": gap.chain,
        "gap_kind": gap.gap_kind.value,
        "target_interval": {
            "start": gap.target_interval.start,
            "stop": gap.target_interval.stop,
        },
        "left_anchor": _encode(gap.left_anchor),
        "right_anchor": _encode(gap.right_anchor),
        "generated_residues": _encode(gap.generated_residues),
        "movable_junction_residues": _encode(
            gap.movable_junction_residues
        ),
    }


def _encode(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: _encode(getattr(value, name))
            for name in value.__dataclass_fields__
        }
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported provenance value: {type(value).__name__}")
