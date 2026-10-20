"""Backend-neutral contracts for experimental diffusion gap reconstruction."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

from dvbfixer.model.diffusion.benchmark import (
    REPEATABILITY_RMSD_MAX_ANGSTROM,
    BenchmarkOutcome,
    CandidateQuality,
    DiffusionBenchmarkError,
    EnsembleSummary,
    ModellerComparison,
    RepeatabilityAssessment,
    StratumRun,
    StratumSummary,
    assess_same_seed_repeatability,
    candidate_quality,
    load_pdb_coordinates,
    pairwise_gap_backbone_rmsds,
    summarize_ensemble,
    summarize_strata,
)
from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    ArtifactReference,
    AtomIdentity,
    BackendOption,
    BackendProvenance,
    DiffusionCandidate,
    DiffusionContractError,
    DiffusionRequest,
    DiffusionResult,
    DiffusionStatus,
    ExplicitLink,
    GapRegion,
    Metric,
    ResidueIdentity,
    RunnerCandidate,
    RunnerDiagnostics,
    RunnerResourceMetrics,
    RunnerResult,
    SamplerStepTrace,
    SamplerTrace,
    SequencePlacement,
    TargetInterval,
    TargetSequence,
    ValidationSummary,
)
from dvbfixer.model.diffusion.geometry import (
    DiffusionGeometryError,
    RigidTransform,
    synchronize_and_reinject,
    weighted_kabsch,
)
from dvbfixer.model.diffusion.masks import (
    DiffusionMaskError,
    DiffusionMasks,
    ObservedResidue,
    build_diffusion_masks,
    build_sequence_placement,
)
from dvbfixer.model.diffusion.preflight import (
    DIFFUSION_PREFLIGHT_SCHEMA_VERSION,
    DIFFUSION_PROFILES,
    AdapterAvailability,
    AdapterPreflightCode,
    AdapterPreflightIssue,
    AdapterPreflightReport,
    AdapterPreflightSpec,
    DiffusionProfileMetadata,
    LocalCheckpoint,
    RunnerPreflightFacts,
    RunnerPreflightReport,
    assess_adapter_preflight,
    invoke_runner_preflight,
    runtime_preflight_facts,
)
from dvbfixer.model.diffusion.provenance import (
    DIFFUSION_PROVENANCE_SCHEMA_VERSION,
    DiagnosticSummary,
    DiffusionProvenanceManifest,
    PublicationArtifact,
    build_provenance_manifest,
)
from dvbfixer.model.diffusion.runner import (
    DIFFUSION_RUNNER_PROTOCOL_VERSION,
    DiffusionRunnerError,
    PreparedDiffusionRun,
    RunnerLimits,
    prepare_diffusion_workspace,
    run_diffusion_runner,
    run_prepared_diffusion_runner,
)
from dvbfixer.model.diffusion.sampler import (
    SamplerCapabilities,
    SamplerConformance,
    SamplingAblationMode,
    assess_sampler_conformance,
)

if TYPE_CHECKING:
    from dvbfixer.model.diffusion.pipeline import (
        BUNDLE_INDEX_SCHEMA_VERSION,
        DiffusionPipelineError,
        DiffusionPipelineOutcome,
        publish_diffusion_bundle,
        run_diffusion_pipeline,
    )
    from dvbfixer.model.diffusion.scope import (
        DiffusionScopeError,
        ScopeAdmission,
        assess_diffusion_scope,
    )
    from dvbfixer.model.diffusion.validate import (
        CandidateValidation,
        DiffusionValidationError,
        ValidationThresholds,
        build_validated_result,
        validate_runner_result,
    )

# Importing contracts or Doctor must not require an installed scientific stack.
# Preserve the public re-exports, but load OpenMM-backed execution on demand.
_LAZY_EXPORTS = {
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


def __getattr__(name: str) -> Any:
    for module_name, exports in _LAZY_EXPORTS.items():
        if name in exports:
            value = getattr(import_module(f"{__name__}.{module_name}"), name)
            globals()[name] = value
            return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DIFFUSION_PROVENANCE_SCHEMA_VERSION",
    "DIFFUSION_PREFLIGHT_SCHEMA_VERSION",
    "DIFFUSION_PROFILES",
    "DIFFUSION_RUNNER_PROTOCOL_VERSION",
    "DIFFUSION_SCHEMA_VERSION",
    "AdapterAvailability",
    "AdapterPreflightCode",
    "AdapterPreflightIssue",
    "AdapterPreflightReport",
    "AdapterPreflightSpec",
    "ArtifactReference",
    "BUNDLE_INDEX_SCHEMA_VERSION",
    "AtomIdentity",
    "BackendOption",
    "BackendProvenance",
    "BenchmarkOutcome",
    "CandidateQuality",
    "CandidateValidation",
    "DiffusionBenchmarkError",
    "DiffusionCandidate",
    "DiffusionContractError",
    "DiffusionGeometryError",
    "DiffusionProvenanceManifest",
    "DiffusionMaskError",
    "DiffusionMasks",
    "DiffusionPipelineError",
    "DiffusionPipelineOutcome",
    "DiffusionProfileMetadata",
    "DiffusionRequest",
    "DiffusionResult",
    "DiagnosticSummary",
    "DiffusionRunnerError",
    "DiffusionScopeError",
    "DiffusionStatus",
    "DiffusionValidationError",
    "EnsembleSummary",
    "ExplicitLink",
    "GapRegion",
    "LocalCheckpoint",
    "Metric",
    "ModellerComparison",
    "ObservedResidue",
    "PreparedDiffusionRun",
    "PublicationArtifact",
    "REPEATABILITY_RMSD_MAX_ANGSTROM",
    "RepeatabilityAssessment",
    "ResidueIdentity",
    "RigidTransform",
    "RunnerCandidate",
    "RunnerDiagnostics",
    "RunnerLimits",
    "RunnerPreflightFacts",
    "RunnerPreflightReport",
    "RunnerResourceMetrics",
    "RunnerResult",
    "SamplerCapabilities",
    "SamplerConformance",
    "SamplerStepTrace",
    "SamplerTrace",
    "SamplingAblationMode",
    "ScopeAdmission",
    "SequencePlacement",
    "StratumRun",
    "StratumSummary",
    "TargetInterval",
    "TargetSequence",
    "ValidationSummary",
    "ValidationThresholds",
    "assess_adapter_preflight",
    "assess_diffusion_scope",
    "assess_same_seed_repeatability",
    "assess_sampler_conformance",
    "build_diffusion_masks",
    "candidate_quality",
    "build_provenance_manifest",
    "build_sequence_placement",
    "build_validated_result",
    "load_pdb_coordinates",
    "invoke_runner_preflight",
    "pairwise_gap_backbone_rmsds",
    "prepare_diffusion_workspace",
    "publish_diffusion_bundle",
    "run_diffusion_pipeline",
    "run_diffusion_runner",
    "run_prepared_diffusion_runner",
    "runtime_preflight_facts",
    "summarize_ensemble",
    "summarize_strata",
    "synchronize_and_reinject",
    "validate_runner_result",
    "weighted_kabsch",
]
