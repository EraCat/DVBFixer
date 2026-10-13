"""CPU-testable repeatability and withheld-coordinate diffusion metrics."""

from __future__ import annotations

import hashlib
import math
import os
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from statistics import NormalDist, median
from typing import TYPE_CHECKING

import numpy as np

from dvbfixer.model.diffusion.contract import (
    ArtifactReference,
    AtomIdentity,
    ResidueIdentity,
)

if TYPE_CHECKING:
    from dvbfixer.model.diffusion.reference_metrics import ReferenceMetrics

REPEATABILITY_RMSD_MAX_ANGSTROM = 0.01
_BACKBONE_ATOMS = frozenset({"N", "CA", "C", "O"})


class DiffusionBenchmarkError(RuntimeError):
    """Raised when benchmark structures cannot be compared safely."""


@dataclass(frozen=True, slots=True)
class RepeatabilityAssessment:
    classification: str
    coordinate_rmsd_angstrom: float
    maximum_displacement_angstrom: float
    atom_count: int
    threshold_angstrom: float = REPEATABILITY_RMSD_MAX_ANGSTROM


@dataclass(frozen=True, slots=True)
class CandidateQuality:
    candidate_id: str
    gap_backbone_rmsd_angstrom: float
    gap_all_heavy_rmsd_angstrom: float
    fixed_heavy_rmsd_angstrom: float
    anchor_heavy_rmsd_angstrom: float
    closure_passed: bool
    validation_passed: bool
    reference_metrics: ReferenceMetrics | None = None


@dataclass(frozen=True, slots=True)
class EnsembleSummary:
    candidate_count: int
    passing_count: int
    closure_pass_rate: float
    validation_pass_rate: float
    top1_gap_backbone_rmsd_angstrom: float
    oracle_gap_backbone_rmsd_angstrom: float
    mean_pairwise_gap_backbone_rmsd_angstrom: float
    ranking_enrichment_angstrom: float


class BenchmarkOutcome(StrEnum):
    SUCCESS = "success"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class BackendEligibilityPolicy(StrEnum):
    CONSTRAINED = "constrained"
    COMPARATOR = "comparator"


@dataclass(frozen=True, slots=True)
class StratumRun:
    stratum: str
    outcome: BenchmarkOutcome
    wall_time_seconds: float | None = None
    model_load_seconds: float | None = None
    peak_ram_bytes: int | None = None
    peak_vram_bytes: int | None = None
    external_process_timed_out: bool = False
    external_process_crashed: bool = False

    def __post_init__(self) -> None:
        if not self.stratum:
            raise ValueError("benchmark stratum must not be empty")
        for value in (self.wall_time_seconds, self.model_load_seconds):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("benchmark timings must be finite and non-negative")
        for value in (self.peak_ram_bytes, self.peak_vram_bytes):
            if value is not None and value < 0:
                raise ValueError("benchmark memory values must be non-negative")
        if self.external_process_timed_out and self.external_process_crashed:
            raise ValueError("one benchmark run cannot be both timed out and crashed")
        if self.outcome is not BenchmarkOutcome.FAILED and (
            self.external_process_timed_out or self.external_process_crashed
        ):
            raise ValueError("timeout or crash evidence requires a failed outcome")


@dataclass(frozen=True, slots=True)
class StratumSummary:
    stratum: str
    run_count: int
    success_count: int
    unsupported_count: int
    failure_count: int
    success_rate: float
    unsupported_rate: float
    failure_rate: float
    timeout_rate: float
    crash_rate: float
    median_wall_time_seconds: float | None
    median_model_load_seconds: float | None
    peak_ram_bytes: int | None
    peak_vram_bytes: int | None


@dataclass(frozen=True, slots=True)
class ModellerComparison:
    experimental_median_gap_backbone_rmsd_angstrom: float
    modeller_median_gap_backbone_rmsd_angstrom: float
    experimental_junction_pass_rate: float
    modeller_junction_pass_rate: float
    experimental_fixed_heavy_rmsd_angstrom: float
    modeller_fixed_heavy_rmsd_angstrom: float
    rmsd_delta_limit_angstrom: float = 0.25

    def __post_init__(self) -> None:
        values = (
            self.experimental_median_gap_backbone_rmsd_angstrom,
            self.modeller_median_gap_backbone_rmsd_angstrom,
            self.experimental_fixed_heavy_rmsd_angstrom,
            self.modeller_fixed_heavy_rmsd_angstrom,
            self.rmsd_delta_limit_angstrom,
        )
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("MODELLER comparison values must be finite and non-negative")
        for rate in (
            self.experimental_junction_pass_rate,
            self.modeller_junction_pass_rate,
        ):
            if not math.isfinite(rate) or not 0 <= rate <= 1:
                raise ValueError("MODELLER comparison rates must be within [0, 1]")

    @property
    def gap_backbone_rmsd_delta_angstrom(self) -> float:
        return (
            self.experimental_median_gap_backbone_rmsd_angstrom
            - self.modeller_median_gap_backbone_rmsd_angstrom
        )

    @property
    def passes_rmsd_gate(self) -> bool:
        return self.gap_backbone_rmsd_delta_angstrom <= self.rmsd_delta_limit_angstrom

    @property
    def passes_junction_gate(self) -> bool:
        return self.experimental_junction_pass_rate >= self.modeller_junction_pass_rate

    @property
    def passes_fixed_adherence_gate(self) -> bool:
        return self.experimental_fixed_heavy_rmsd_angstrom < self.modeller_fixed_heavy_rmsd_angstrom

    @property
    def passed(self) -> bool:
        return (
            self.passes_rmsd_gate and self.passes_junction_gate and self.passes_fixed_adherence_gate
        )


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    lower: float
    upper: float
    confidence_level: float


@dataclass(frozen=True, slots=True)
class BackendCaseResult:
    """One backend result for one withheld gap.

    ``independence_group`` identifies masks that must remain together during
    resampling, such as two gaps withheld from the same PDB structure.
    ``eligibility_policy`` keeps the MODELLER comparator usable without
    pretending that its whole-model optimization preserves fixed coordinates.
    """

    backend_id: str
    case_id: str
    independence_group: str
    validation_passed: bool
    fixed_coordinates_exact: bool
    mapping_valid: bool
    leakage_resolved: bool
    gap_backbone_rmsd_angstrom: float | None = None
    wall_time_seconds: float | None = None
    peak_vram_bytes: int | None = None
    peak_ram_bytes: int | None = None
    gpu_memory_applicable: bool = True
    eligibility_policy: BackendEligibilityPolicy = BackendEligibilityPolicy.CONSTRAINED

    def __post_init__(self) -> None:
        if not self.backend_id or not self.case_id or not self.independence_group:
            raise ValueError("backend, case, and independence-group IDs are required")
        if self.validation_passed and self.gap_backbone_rmsd_angstrom is None:
            raise ValueError("a valid candidate requires a gap-backbone RMSD")
        for value in (self.gap_backbone_rmsd_angstrom, self.wall_time_seconds):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("benchmark measurements must be finite and non-negative")
        for label, value in (
            ("peak RAM", self.peak_ram_bytes),
            ("peak VRAM", self.peak_vram_bytes),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{label} must be non-negative")
        if not self.gpu_memory_applicable and self.peak_vram_bytes is not None:
            raise ValueError("peak VRAM must be absent when GPU memory is not applicable")


@dataclass(frozen=True, slots=True)
class BackendSummary:
    backend_id: str
    case_count: int
    passing_count: int
    validation_pass_rate: float
    validation_pass_rate_interval: ConfidenceInterval
    median_valid_gap_backbone_rmsd_angstrom: float | None
    median_wall_time_seconds: float | None
    peak_ram_bytes: int | None
    peak_vram_bytes: int | None
    wall_time_observed_count: int
    peak_ram_observed_count: int
    peak_vram_observed_count: int
    gpu_memory_applicable: bool
    resource_reporting_complete: bool
    eligible: bool
    ineligibility_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PairedBackendComparison:
    candidate: BackendSummary
    baseline: BackendSummary
    paired_case_count: int
    both_passed_count: int
    candidate_only_passed_count: int
    baseline_only_passed_count: int
    neither_passed_count: int
    pass_rate_difference: float
    pass_rate_difference_interval: ConfidenceInterval
    median_paired_rmsd_difference_angstrom: float | None
    median_paired_rmsd_difference_interval: ConfidenceInterval | None
    noninferiority_margin: float
    independence_group_count: int
    minimum_independence_groups: int
    maximum_independence_groups: int
    sample_size_sufficient: bool
    both_valid_independence_group_count: int
    minimum_both_valid_independence_groups: int
    rmsd_sample_size_sufficient: bool
    noninferiority_demonstrated: bool
    decision: str


def wilson_score_interval(
    successes: int,
    total: int,
    *,
    confidence_level: float = 0.95,
) -> ConfidenceInterval:
    """Return a Wilson score interval for a binomial proportion."""
    if total <= 0 or successes < 0 or successes > total:
        raise ValueError("successes and total do not define a binomial sample")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence level must be within (0, 1)")
    z = NormalDist().inv_cdf(0.5 + confidence_level / 2)
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    radius = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return ConfidenceInterval(
        lower=max(0.0, centre - radius),
        upper=min(1.0, centre + radius),
        confidence_level=confidence_level,
    )


def paired_noninferiority_power(
    independence_groups: int,
    *,
    discordance_rate: float,
    true_pass_rate_difference: float = 0.0,
    noninferiority_margin: float = 0.05,
    confidence_level: float = 0.95,
) -> float:
    """Approximate power for the paired pass-rate noninferiority endpoint.

    Discordance is the probability that exactly one backend passes. The normal
    approximation matches the two-sided confidence-interval decision used by
    :func:`compare_paired_backends` and is intended for blinded sample-size
    planning, not for replacing the final cluster bootstrap.
    """
    if independence_groups <= 0:
        raise ValueError("independence-group count must be positive")
    if not 0 <= discordance_rate <= 1:
        raise ValueError("discordance rate must be within [0, 1]")
    if not -discordance_rate <= true_pass_rate_difference <= discordance_rate:
        raise ValueError("pass-rate difference is incompatible with discordance rate")
    if not 0 <= noninferiority_margin < 1:
        raise ValueError("noninferiority margin must be within [0, 1)")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence level must be within (0, 1)")
    variance = discordance_rate - true_pass_rate_difference**2
    if variance == 0:
        return float(true_pass_rate_difference >= -noninferiority_margin)
    z = NormalDist().inv_cdf(0.5 + confidence_level / 2)
    standardized = (
        math.sqrt(independence_groups)
        * (true_pass_rate_difference + noninferiority_margin)
        / math.sqrt(variance)
    )
    return NormalDist().cdf(standardized - z)


def summarize_backend_cases(
    runs: tuple[BackendCaseResult, ...],
    *,
    confidence_level: float = 0.95,
) -> BackendSummary:
    """Summarize one backend without treating failed gaps as missing data."""
    if not runs:
        raise DiffusionBenchmarkError("backend result set is empty")
    backend_ids = {run.backend_id for run in runs}
    if len(backend_ids) != 1:
        raise DiffusionBenchmarkError("backend result set mixes backend IDs")
    case_ids = {run.case_id for run in runs}
    if len(case_ids) != len(runs):
        raise DiffusionBenchmarkError("backend result set repeats a case ID")
    passing = [run for run in runs if run.validation_passed]
    reasons: list[str] = []
    policies = {run.eligibility_policy for run in runs}
    if len(policies) != 1:
        raise DiffusionBenchmarkError("backend result set mixes eligibility policies")
    eligibility_policy = next(iter(policies))
    if any(not run.mapping_valid for run in runs):
        reasons.append("invalid-request-result-mapping")
    if eligibility_policy is BackendEligibilityPolicy.CONSTRAINED:
        if any(not run.fixed_coordinates_exact for run in runs):
            reasons.append("fixed-coordinates-not-exact")
        if any(not run.leakage_resolved for run in runs):
            reasons.append("unresolved-training-leakage")
    wall_times = [run.wall_time_seconds for run in runs if run.wall_time_seconds is not None]
    peak_ram = [run.peak_ram_bytes for run in runs if run.peak_ram_bytes is not None]
    peak_vram = [run.peak_vram_bytes for run in runs if run.peak_vram_bytes is not None]
    gpu_applicability = {run.gpu_memory_applicable for run in runs}
    if len(gpu_applicability) != 1:
        raise DiffusionBenchmarkError("backend result set mixes GPU-memory applicability")
    gpu_memory_applicable = next(iter(gpu_applicability))
    rmsds = [
        run.gap_backbone_rmsd_angstrom
        for run in passing
        if run.gap_backbone_rmsd_angstrom is not None
    ]
    return BackendSummary(
        backend_id=next(iter(backend_ids)),
        case_count=len(runs),
        passing_count=len(passing),
        validation_pass_rate=len(passing) / len(runs),
        validation_pass_rate_interval=wilson_score_interval(
            len(passing),
            len(runs),
            confidence_level=confidence_level,
        ),
        median_valid_gap_backbone_rmsd_angstrom=(float(median(rmsds)) if rmsds else None),
        median_wall_time_seconds=(float(median(wall_times)) if wall_times else None),
        peak_ram_bytes=max(peak_ram) if peak_ram else None,
        peak_vram_bytes=max(peak_vram) if peak_vram else None,
        wall_time_observed_count=len(wall_times),
        peak_ram_observed_count=len(peak_ram),
        peak_vram_observed_count=len(peak_vram),
        gpu_memory_applicable=gpu_memory_applicable,
        resource_reporting_complete=(
            len(wall_times) == len(runs)
            and len(peak_ram) == len(runs)
            and (not gpu_memory_applicable or len(peak_vram) == len(runs))
        ),
        eligible=not reasons,
        ineligibility_reasons=tuple(reasons),
    )


def compare_paired_backends(
    candidate_runs: tuple[BackendCaseResult, ...],
    baseline_runs: tuple[BackendCaseResult, ...],
    *,
    noninferiority_margin: float = 0.05,
    minimum_independence_groups: int = 180,
    maximum_independence_groups: int = 300,
    minimum_both_valid_independence_groups: int = 30,
    require_complete_resources: bool = True,
    confidence_level: float = 0.95,
    bootstrap_samples: int = 10_000,
    random_seed: int = 0,
) -> PairedBackendComparison:
    """Compare backends on identical gaps with dependence-aware resampling."""
    if not 0 <= noninferiority_margin < 1:
        raise ValueError("noninferiority margin must be within [0, 1)")
    if minimum_independence_groups <= 0:
        raise ValueError("minimum independence-group count must be positive")
    if maximum_independence_groups < minimum_independence_groups:
        raise ValueError("maximum independence-group count must not be below minimum")
    if minimum_both_valid_independence_groups <= 0:
        raise ValueError("minimum both-valid group count must be positive")
    if not 0 < confidence_level < 1:
        raise ValueError("confidence level must be within (0, 1)")
    if bootstrap_samples <= 0:
        raise ValueError("bootstrap sample count must be positive")
    candidate = summarize_backend_cases(
        candidate_runs,
        confidence_level=confidence_level,
    )
    baseline = summarize_backend_cases(
        baseline_runs,
        confidence_level=confidence_level,
    )
    candidate_by_case = {run.case_id: run for run in candidate_runs}
    baseline_by_case = {run.case_id: run for run in baseline_runs}
    if set(candidate_by_case) != set(baseline_by_case):
        raise DiffusionBenchmarkError("paired backends must contain identical case IDs")

    pairs: list[tuple[BackendCaseResult, BackendCaseResult]] = []
    grouped: dict[str, list[tuple[BackendCaseResult, BackendCaseResult]]] = {}
    for case_id in sorted(candidate_by_case):
        pair = candidate_by_case[case_id], baseline_by_case[case_id]
        if pair[0].independence_group != pair[1].independence_group:
            raise DiffusionBenchmarkError(
                f"paired case {case_id!r} has inconsistent independence groups"
            )
        pairs.append(pair)
        grouped.setdefault(pair[0].independence_group, []).append(pair)

    pass_differences = [
        int(candidate_run.validation_passed) - int(baseline_run.validation_passed)
        for candidate_run, baseline_run in pairs
    ]
    paired_rmsd_differences = _paired_rmsd_differences(pairs)
    rmsd_grouped = {
        group_id: group_pairs
        for group_id, group_pairs in grouped.items()
        if _paired_rmsd_differences(group_pairs)
    }
    rng = np.random.default_rng(random_seed)
    group_ids = sorted(grouped)
    bootstrap_pass_differences: list[float] = []
    for _ in range(bootstrap_samples):
        sampled_pairs: list[tuple[BackendCaseResult, BackendCaseResult]] = []
        for sampled_index in rng.integers(0, len(group_ids), size=len(group_ids)):
            sampled_pairs.extend(grouped[group_ids[int(sampled_index)]])
        bootstrap_pass_differences.append(
            float(
                np.mean(
                    [
                        int(candidate_run.validation_passed) - int(baseline_run.validation_passed)
                        for candidate_run, baseline_run in sampled_pairs
                    ]
                )
            )
        )

    bootstrap_rmsd_differences: list[float] = []
    rmsd_group_ids = sorted(rmsd_grouped)
    if rmsd_group_ids:
        for _ in range(bootstrap_samples):
            sampled_pairs = []
            for sampled_index in rng.integers(
                0,
                len(rmsd_group_ids),
                size=len(rmsd_group_ids),
            ):
                sampled_pairs.extend(rmsd_grouped[rmsd_group_ids[int(sampled_index)]])
            bootstrap_rmsd_differences.append(
                float(median(_paired_rmsd_differences(sampled_pairs)))
            )

    pass_interval = _percentile_interval(
        bootstrap_pass_differences,
        confidence_level,
    )
    rmsd_interval = (
        _percentile_interval(bootstrap_rmsd_differences, confidence_level)
        if rmsd_group_ids
        else None
    )
    sample_size_sufficient = (
        minimum_independence_groups <= len(group_ids) <= maximum_independence_groups
    )
    rmsd_sample_size_sufficient = len(rmsd_group_ids) >= minimum_both_valid_independence_groups
    noninferiority_demonstrated = (
        candidate.eligible
        and baseline.eligible
        and sample_size_sufficient
        and pass_interval.lower >= -noninferiority_margin
    )
    if not candidate.eligible:
        decision = "candidate-ineligible"
    elif not baseline.eligible:
        decision = "baseline-ineligible"
    elif len(group_ids) < minimum_independence_groups:
        decision = "insufficient-sample"
    elif len(group_ids) > maximum_independence_groups:
        decision = "sample-exceeds-preregistered-maximum"
    elif not noninferiority_demonstrated:
        decision = "noninferiority-not-demonstrated"
    elif not rmsd_sample_size_sufficient:
        decision = "noninferior-rmsd-insufficient-sample"
    elif require_complete_resources and not (
        candidate.resource_reporting_complete and baseline.resource_reporting_complete
    ):
        decision = "resource-reporting-incomplete"
    elif rmsd_interval is not None and rmsd_interval.upper < 0:
        decision = "candidate-preferred"
    elif rmsd_interval is not None and rmsd_interval.lower > 0:
        decision = "baseline-preferred"
    else:
        decision = "noninferior-rmsd-inconclusive"

    both_passed = sum(a.validation_passed and b.validation_passed for a, b in pairs)
    candidate_only = sum(a.validation_passed and not b.validation_passed for a, b in pairs)
    baseline_only = sum(not a.validation_passed and b.validation_passed for a, b in pairs)
    neither = len(pairs) - both_passed - candidate_only - baseline_only
    return PairedBackendComparison(
        candidate=candidate,
        baseline=baseline,
        paired_case_count=len(pairs),
        both_passed_count=both_passed,
        candidate_only_passed_count=candidate_only,
        baseline_only_passed_count=baseline_only,
        neither_passed_count=neither,
        pass_rate_difference=float(np.mean(pass_differences)),
        pass_rate_difference_interval=pass_interval,
        median_paired_rmsd_difference_angstrom=(
            float(median(paired_rmsd_differences)) if paired_rmsd_differences else None
        ),
        median_paired_rmsd_difference_interval=rmsd_interval,
        noninferiority_margin=noninferiority_margin,
        independence_group_count=len(group_ids),
        minimum_independence_groups=minimum_independence_groups,
        maximum_independence_groups=maximum_independence_groups,
        sample_size_sufficient=sample_size_sufficient,
        both_valid_independence_group_count=len(rmsd_group_ids),
        minimum_both_valid_independence_groups=(minimum_both_valid_independence_groups),
        rmsd_sample_size_sufficient=rmsd_sample_size_sufficient,
        noninferiority_demonstrated=noninferiority_demonstrated,
        decision=decision,
    )


def _paired_rmsd_differences(
    pairs: list[tuple[BackendCaseResult, BackendCaseResult]],
) -> list[float]:
    return [
        candidate.gap_backbone_rmsd_angstrom - baseline.gap_backbone_rmsd_angstrom
        for candidate, baseline in pairs
        if candidate.validation_passed
        and baseline.validation_passed
        and candidate.gap_backbone_rmsd_angstrom is not None
        and baseline.gap_backbone_rmsd_angstrom is not None
    ]


def _percentile_interval(
    values: list[float],
    confidence_level: float,
) -> ConfidenceInterval:
    tail = (1 - confidence_level) / 2
    lower, upper = np.quantile(values, (tail, 1 - tail))
    return ConfidenceInterval(
        lower=float(lower),
        upper=float(upper),
        confidence_level=confidence_level,
    )


def assess_same_seed_repeatability(
    first: dict[AtomIdentity, np.ndarray],
    second: dict[AtomIdentity, np.ndarray],
    *,
    atom_identities: set[AtomIdentity] | None = None,
    threshold_angstrom: float = REPEATABILITY_RMSD_MAX_ANGSTROM,
) -> RepeatabilityAssessment:
    """Classify two same-seed coordinate sets using stable atom identities."""
    if not math.isfinite(threshold_angstrom) or threshold_angstrom <= 0:
        raise ValueError("repeatability threshold must be finite and positive")
    if atom_identities is None:
        identities = set(first)
        if set(second) != identities:
            raise DiffusionBenchmarkError(
                "repeatability structures do not contain identical requested atoms"
            )
    else:
        identities = set(atom_identities)
        if set(first) & identities != identities or set(second) & identities != identities:
            raise DiffusionBenchmarkError(
                "repeatability structures do not contain identical requested atoms"
            )
    if not identities:
        raise DiffusionBenchmarkError("repeatability atom identity set is empty")
    displacements = _displacements(first, second, identities)
    rmsd = float(np.sqrt(np.mean(displacements * displacements)))
    maximum = float(np.max(displacements))
    return RepeatabilityAssessment(
        classification="deterministic" if rmsd <= threshold_angstrom else "nondeterministic",
        coordinate_rmsd_angstrom=rmsd,
        maximum_displacement_angstrom=maximum,
        atom_count=len(identities),
        threshold_angstrom=threshold_angstrom,
    )


def candidate_quality(
    candidate_id: str,
    reference: dict[AtomIdentity, np.ndarray],
    candidate: dict[AtomIdentity, np.ndarray],
    *,
    generated_residues: set[ResidueIdentity],
    fixed_atoms: set[AtomIdentity],
    anchor_residues: set[ResidueIdentity],
    closure_passed: bool,
    validation_passed: bool,
    interface_chain_pairs: tuple[tuple[str, str], ...] = (),
    expected_generated_atoms: set[AtomIdentity] | None = None,
) -> CandidateQuality:
    """Compute honest coordinate metrics against withheld reference atoms."""
    generated_heavy = {
        identity
        for identity in reference
        if _residue(identity) in generated_residues and not _is_hydrogen(identity)
    }
    generated_backbone = {
        identity for identity in generated_heavy if identity.atom_name in _BACKBONE_ATOMS
    }
    fixed_heavy = {
        identity for identity in fixed_atoms if identity in reference and not _is_hydrogen(identity)
    }
    anchor_heavy = {
        identity
        for identity in reference
        if _residue(identity) in anchor_residues and not _is_hydrogen(identity)
    }
    from dvbfixer.model.diffusion.reference_metrics import reference_metrics

    return CandidateQuality(
        candidate_id=candidate_id,
        gap_backbone_rmsd_angstrom=_rmsd(
            reference,
            candidate,
            generated_backbone,
            "gap backbone",
        ),
        gap_all_heavy_rmsd_angstrom=_rmsd(
            reference,
            candidate,
            generated_heavy,
            "gap all-heavy",
        ),
        fixed_heavy_rmsd_angstrom=_rmsd(
            reference,
            candidate,
            fixed_heavy,
            "fixed heavy",
        ),
        anchor_heavy_rmsd_angstrom=_rmsd(
            reference,
            candidate,
            anchor_heavy,
            "anchor heavy",
        ),
        closure_passed=closure_passed,
        validation_passed=validation_passed,
        reference_metrics=reference_metrics(
            reference, candidate, generated_residues=generated_residues,
            anchor_residues=anchor_residues, chain_pairs=interface_chain_pairs,
            expected_generated_atoms=expected_generated_atoms,
        ),
    )


def summarize_ensemble(
    qualities: tuple[CandidateQuality, ...],
    ranked_candidate_ids: tuple[str, ...],
    pairwise_gap_backbone_rmsds: tuple[float, ...],
) -> EnsembleSummary:
    """Summarize top-1/oracle quality, rates, diversity, and ranking enrichment."""
    if not qualities:
        raise DiffusionBenchmarkError("ensemble contains no candidates")
    by_id = {quality.candidate_id: quality for quality in qualities}
    if len(by_id) != len(qualities):
        raise DiffusionBenchmarkError("ensemble candidate IDs are not unique")
    if set(ranked_candidate_ids) != set(by_id):
        raise DiffusionBenchmarkError("ranked candidate IDs do not match ensemble candidates")
    if any(not math.isfinite(value) or value < 0 for value in pairwise_gap_backbone_rmsds):
        raise DiffusionBenchmarkError("pairwise RMSDs must be finite and non-negative")
    top1 = by_id[ranked_candidate_ids[0]].gap_backbone_rmsd_angstrom
    oracle = min(quality.gap_backbone_rmsd_angstrom for quality in qualities)
    return EnsembleSummary(
        candidate_count=len(qualities),
        passing_count=sum(quality.validation_passed for quality in qualities),
        closure_pass_rate=(sum(quality.closure_passed for quality in qualities) / len(qualities)),
        validation_pass_rate=(
            sum(quality.validation_passed for quality in qualities) / len(qualities)
        ),
        top1_gap_backbone_rmsd_angstrom=top1,
        oracle_gap_backbone_rmsd_angstrom=oracle,
        mean_pairwise_gap_backbone_rmsd_angstrom=(
            float(np.mean(pairwise_gap_backbone_rmsds)) if pairwise_gap_backbone_rmsds else 0.0
        ),
        ranking_enrichment_angstrom=top1 - oracle,
    )


def pairwise_gap_backbone_rmsds(
    candidates: tuple[dict[AtomIdentity, np.ndarray], ...],
    generated_residues: set[ResidueIdentity],
) -> tuple[float, ...]:
    """Return pairwise generated-backbone RMSDs for ensemble diversity."""
    if not candidates:
        return ()
    identities = {
        identity
        for identity in candidates[0]
        if _residue(identity) in generated_residues
        and identity.atom_name in _BACKBONE_ATOMS
        and not _is_hydrogen(identity)
    }
    values: list[float] = []
    for index, first in enumerate(candidates):
        for second in candidates[index + 1 :]:
            values.append(_rmsd(first, second, identities, "pairwise gap backbone"))
    return tuple(values)


def summarize_strata(
    runs: tuple[StratumRun, ...],
) -> tuple[StratumSummary, ...]:
    """Summarize outcomes and observed resources without fabricating missing data."""
    if not runs:
        raise DiffusionBenchmarkError("benchmark run set is empty")
    grouped: dict[str, list[StratumRun]] = {}
    for run in runs:
        grouped.setdefault(run.stratum, []).append(run)
    summaries: list[StratumSummary] = []
    for stratum in sorted(grouped):
        stratum_runs = grouped[stratum]
        run_count = len(stratum_runs)
        success_count = sum(run.outcome is BenchmarkOutcome.SUCCESS for run in stratum_runs)
        unsupported_count = sum(run.outcome is BenchmarkOutcome.UNSUPPORTED for run in stratum_runs)
        failure_count = sum(run.outcome is BenchmarkOutcome.FAILED for run in stratum_runs)
        wall_times = [
            run.wall_time_seconds for run in stratum_runs if run.wall_time_seconds is not None
        ]
        model_load_times = [
            run.model_load_seconds for run in stratum_runs if run.model_load_seconds is not None
        ]
        peak_ram = [run.peak_ram_bytes for run in stratum_runs if run.peak_ram_bytes is not None]
        peak_vram = [run.peak_vram_bytes for run in stratum_runs if run.peak_vram_bytes is not None]
        summaries.append(
            StratumSummary(
                stratum=stratum,
                run_count=run_count,
                success_count=success_count,
                unsupported_count=unsupported_count,
                failure_count=failure_count,
                success_rate=success_count / run_count,
                unsupported_rate=unsupported_count / run_count,
                failure_rate=failure_count / run_count,
                timeout_rate=(
                    sum(run.external_process_timed_out for run in stratum_runs) / run_count
                ),
                crash_rate=(sum(run.external_process_crashed for run in stratum_runs) / run_count),
                median_wall_time_seconds=(float(np.median(wall_times)) if wall_times else None),
                median_model_load_seconds=(
                    float(np.median(model_load_times)) if model_load_times else None
                ),
                peak_ram_bytes=max(peak_ram) if peak_ram else None,
                peak_vram_bytes=max(peak_vram) if peak_vram else None,
            )
        )
    return tuple(summaries)


def load_pdb_coordinates(
    root: Path,
    artifact: ArtifactReference,
) -> dict[AtomIdentity, np.ndarray]:
    """Read stable-identity coordinates from a verified contained PDB artifact."""
    data = _read_contained(root, artifact)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DiffusionBenchmarkError("benchmark PDB is not valid UTF-8") from exc
    coordinates: dict[AtomIdentity, np.ndarray] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if line[:6].strip() not in {"ATOM", "HETATM"}:
            continue
        if len(line) < 54:
            raise DiffusionBenchmarkError(
                f"truncated benchmark PDB coordinate on line {line_number}"
            )
        identity = AtomIdentity(
            line[21],
            line[22:26].strip(),
            line[26].strip(),
            line[12:16].strip(),
        )
        if identity in coordinates:
            raise DiffusionBenchmarkError("duplicate benchmark atom identity")
        try:
            point = np.asarray(
                (
                    float(line[30:38]),
                    float(line[38:46]),
                    float(line[46:54]),
                ),
                dtype=np.float64,
            )
        except ValueError as exc:
            raise DiffusionBenchmarkError(
                f"malformed benchmark PDB coordinate on line {line_number}"
            ) from exc
        if not np.all(np.isfinite(point)):
            raise DiffusionBenchmarkError("non-finite benchmark PDB coordinate")
        coordinates[identity] = point
    if not coordinates:
        raise DiffusionBenchmarkError("benchmark PDB contains no coordinates")
    return coordinates


def _rmsd(
    reference: dict[AtomIdentity, np.ndarray],
    candidate: dict[AtomIdentity, np.ndarray],
    identities: set[AtomIdentity],
    label: str,
) -> float:
    if not identities:
        raise DiffusionBenchmarkError(f"{label} atom identity set is empty")
    if set(reference) & identities != identities or set(candidate) & identities != identities:
        raise DiffusionBenchmarkError(f"{label} atom identity mismatch")
    displacements = _displacements(reference, candidate, identities)
    return float(np.sqrt(np.mean(displacements * displacements)))


def _displacements(
    first: dict[AtomIdentity, np.ndarray],
    second: dict[AtomIdentity, np.ndarray],
    identities: set[AtomIdentity],
) -> np.ndarray:
    ordered = sorted(identities)
    return np.asarray(
        [np.linalg.norm(second[identity] - first[identity]) for identity in ordered],
        dtype=np.float64,
    )


def _residue(identity: AtomIdentity) -> ResidueIdentity:
    return ResidueIdentity(
        identity.chain,
        identity.residue_number,
        identity.insertion_code,
    )


def _is_hydrogen(identity: AtomIdentity) -> bool:
    return identity.atom_name.lstrip("0123456789").upper().startswith("H")


def _read_contained(root: Path, artifact: ArtifactReference) -> bytes:
    if root.is_symlink() or not root.is_dir():
        raise DiffusionBenchmarkError("benchmark root must be a regular directory")
    resolved_root = root.resolve(strict=True)
    path = resolved_root.joinpath(*Path(artifact.path).parts)
    current = resolved_root
    for part in Path(artifact.path).parts:
        current = current / part
        if current.is_symlink():
            raise DiffusionBenchmarkError("benchmark artifact path contains a symlink")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise DiffusionBenchmarkError("benchmark artifact does not exist") from exc
    if not resolved.is_relative_to(resolved_root):
        raise DiffusionBenchmarkError("benchmark artifact escapes its root")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
            raise DiffusionBenchmarkError("benchmark artifact is not a private regular file")
        digest = hashlib.sha256()
        data = bytearray()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
            data.extend(chunk)
    finally:
        os.close(descriptor)
    if digest.hexdigest() != artifact.sha256.lower():
        raise DiffusionBenchmarkError("benchmark artifact SHA-256 mismatch")
    return bytes(data)
