"""Reference-dependent local distance and declared-interface measurements.

These scores describe agreement with observed reference coordinates. They do
not replace geometry validation, infer conditioning, or participate in ranking.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from statistics import median

import numpy as np

from dvbfixer.model.diffusion.benchmark import _is_hydrogen, _residue
from dvbfixer.model.diffusion.contract import AtomIdentity, ResidueIdentity

LDDT_THRESHOLDS_ANGSTROM = (0.5, 1.0, 2.0, 4.0)


@dataclass(frozen=True, slots=True)
class ReferenceMetric:
    value: float | None
    undefined_reason: str | None
    reference_atom_count: int = 0
    matched_atom_count: int = 0
    reference_context_atom_count: int = 0
    matched_context_atom_count: int = 0
    scored_atom_count: int = 0
    comparison_count: int = 0
    missing_candidate_atom_count: int = 0
    missing_reference_atom_count: int | None = None

    def __post_init__(self) -> None:
        if self.value is None:
            if not self.undefined_reason:
                raise ValueError("undefined reference metrics require a reason")
        elif self.undefined_reason or not math.isfinite(self.value) or not 0 <= self.value <= 1:
            raise ValueError("defined reference metrics must be finite scores in [0, 1]")


@dataclass(frozen=True, slots=True)
class ReferenceMetricPolicy:
    schema_version: int = 1
    neighbor_radius_angstrom: float = 15.0
    contact_cutoff_angstrom: float = 5.0
    lddt_thresholds_angstrom: tuple[float, ...] = LDDT_THRESHOLDS_ANGSTROM
    atom_scope: str = field(default="observed-reference-heavy-atom-axis", init=False)
    hydrogen_filter: str = field(default="existing-protein-benchmark-H-prefix-convention", init=False)
    aggregation: str = field(default="mean-of-per-atom-lddt", init=False)
    same_residue_pairs: str = field(default="excluded", init=False)
    missing_candidate_policy: str = field(default="zero-contribution-not-denominator-exclusion", init=False)
    contact_scope: str = field(default="undirected-cross-chain-residue-pairs-on-reference-atom-axis", init=False)
    correspondence: str = field(default="exact-atom-identity-no-symmetry-remapping", init=False)

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.lddt_thresholds_angstrom != LDDT_THRESHOLDS_ANGSTROM:
            raise ValueError("unsupported reference metric definition")
        if any(not math.isfinite(value) or value <= 0 for value in (
            self.neighbor_radius_angstrom, self.contact_cutoff_angstrom,
        )):
            raise ValueError("reference metric distance cutoffs must be positive and finite")


@dataclass(frozen=True, slots=True)
class InterfaceContacts:
    precision: ReferenceMetric
    recall: ReferenceMetric
    reference_contact_count: int
    candidate_contact_count: int
    true_positive_contact_count: int


@dataclass(frozen=True, slots=True)
class ReferenceMetrics:
    policy: ReferenceMetricPolicy
    generated_lddt: ReferenceMetric
    junction_lddt: ReferenceMetric
    interface_lddt: ReferenceMetric
    interface_contacts: InterfaceContacts
    interface_chain_pairs: tuple[tuple[str, str], ...]


def _pairs(pairs: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    normalized = []
    for pair in pairs:
        if len(pair) != 2 or any(not isinstance(chain, str) or len(chain) != 1 for chain in pair) or pair[0] == pair[1]:
            raise ValueError("interface declarations require distinct one-character PDB chain IDs")
        normalized.append(tuple(sorted(pair)))
    if len(set(normalized)) != len(normalized):
        raise ValueError("interface declarations repeat a chain pair")
    return tuple(sorted(normalized))


def _invalid_coordinates(coordinates: dict[AtomIdentity, np.ndarray]) -> bool:
    try:
        return any(np.asarray(point, dtype=float).shape != (3,) or not np.all(np.isfinite(point)) for point in coordinates.values())
    except (TypeError, ValueError):
        return True


def local_lddt(
    reference: dict[AtomIdentity, np.ndarray],
    candidate: dict[AtomIdentity, np.ndarray],
    *,
    centers: set[AtomIdentity],
    policy: ReferenceMetricPolicy = ReferenceMetricPolicy(),
    interface_chain_pairs: tuple[tuple[str, str], ...] | None = None,
    expected_reference_atoms: set[AtomIdentity] | None = None,
) -> ReferenceMetric:
    """Average reference-neighbor distance preservation over selected center atoms.

    Reference distances are strictly below the neighborhood radius; each
    threshold comparison is strict. Center atoms without reference neighbors
    are unscored and counted separately. Missing candidate center/neighbor atoms
    receive zero contribution. Extra candidate atoms are outside the reference
    axis and do not provide fabricated reference observations.
    """
    reference = {atom: point for atom, point in reference.items() if not _is_hydrogen(atom)}
    centers = {atom for atom in centers if not _is_hydrogen(atom)}
    matched = set(reference) & set(candidate)
    missing_reference = len({atom for atom in expected_reference_atoms if not _is_hydrogen(atom)} - set(reference)) if expected_reference_atoms is not None else None
    counts = dict(reference_atom_count=len(centers), matched_atom_count=len(centers & matched),
                  reference_context_atom_count=len(reference), matched_context_atom_count=len(matched),
                  missing_candidate_atom_count=len(set(reference) - matched), missing_reference_atom_count=missing_reference)
    if _invalid_coordinates(reference):
        return ReferenceMetric(None, "invalid-reference-coordinates", **counts)
    if _invalid_coordinates({atom: candidate[atom] for atom in matched}):
        return ReferenceMetric(None, "invalid-candidate-coordinates", **counts)
    declared = _pairs(interface_chain_pairs) if interface_chain_pairs is not None else None
    if declared is not None:
        if not declared:
            return ReferenceMetric(None, "interface-not-declared", **counts)
        if {chain for pair in declared for chain in pair} - {atom.chain for atom in reference}:
            return ReferenceMetric(None, "declared-interface-chain-missing-from-reference", **counts)
    if not centers:
        return ReferenceMetric(None, "empty-reference-scope", **counts)
    if not centers <= set(reference):
        return ReferenceMetric(None, "scope-atoms-missing-from-reference", **counts)
    ordered = sorted(reference)
    points = np.asarray([reference[atom] for atom in ordered], dtype=float)
    residue_indices = {residue: index for index, residue in enumerate(sorted({_residue(atom) for atom in ordered}))}
    residues = np.asarray([residue_indices[_residue(atom)] for atom in ordered])
    chains = np.asarray([atom.chain for atom in ordered])
    present = np.asarray([atom in matched for atom in ordered])
    candidate_points = np.asarray([candidate[atom] if atom in matched else (0.0, 0.0, 0.0) for atom in ordered], dtype=float)
    thresholds = np.asarray(policy.lddt_thresholds_angstrom)
    scores = []
    comparisons = 0
    for center in sorted(centers):
        distances = np.linalg.norm(points - np.asarray(reference[center]), axis=1)
        eligible = (residues != residue_indices[_residue(center)]) & (distances < policy.neighbor_radius_angstrom)
        if declared is not None:
            partners = {right if left == center.chain else left for left, right in declared if center.chain in (left, right)}
            eligible &= np.isin(chains, tuple(partners))
        indices = np.flatnonzero(eligible)
        if len(indices) == 0:
            continue
        comparisons += len(indices)
        total = 0.0
        if center in matched:
            known = eligible & present
            deltas = np.abs(np.linalg.norm(candidate_points[known] - np.asarray(candidate[center]), axis=1) - distances[known])
            total = float(np.sum(np.mean(deltas[:, None] < thresholds, axis=1)))
        scores.append(total / len(indices))
    if not scores:
        return ReferenceMetric(None, "no-reference-neighbor-pairs", **counts)
    return ReferenceMetric(float(np.mean(scores)), None, scored_atom_count=len(scores), comparison_count=comparisons, **counts)


def interface_contacts(
    reference: dict[AtomIdentity, np.ndarray], candidate: dict[AtomIdentity, np.ndarray],
    *, chain_pairs: tuple[tuple[str, str], ...], policy: ReferenceMetricPolicy = ReferenceMetricPolicy(),
) -> InterfaceContacts:
    """Precision/recall of declared residue contacts; never turn an empty set into 1."""
    declared = _pairs(chain_pairs)
    if not declared:
        undefined = ReferenceMetric(None, "interface-not-declared")
        return InterfaceContacts(undefined, undefined, 0, 0, 0)
    chains = {chain for pair in declared for chain in pair}
    reference = {atom: point for atom, point in reference.items() if atom.chain in chains and not _is_hydrogen(atom)}
    matched = {atom: candidate[atom] for atom in reference if atom in candidate}
    counts = dict(reference_atom_count=len(reference), matched_atom_count=len(matched),
                  reference_context_atom_count=len(reference), matched_context_atom_count=len(matched),
                  missing_candidate_atom_count=len(reference) - len(matched))
    reason = None
    if chains - {atom.chain for atom in reference}:
        reason = "declared-interface-chain-missing-from-reference"
    elif _invalid_coordinates(reference):
        reason = "invalid-reference-coordinates"
    elif _invalid_coordinates(matched):
        reason = "invalid-candidate-coordinates"
    if reason:
        undefined = ReferenceMetric(None, reason, **counts)
        return InterfaceContacts(undefined, undefined, 0, 0, 0)

    def contacts(coordinates):
        found = set()
        for left, right in declared:
            right_atoms = sorted(atom for atom in coordinates if atom.chain == right)
            if not right_atoms:
                continue
            points = np.asarray([coordinates[atom] for atom in right_atoms])
            for atom in sorted(atom for atom in coordinates if atom.chain == left):
                indices = np.flatnonzero(np.linalg.norm(points - coordinates[atom], axis=1) <= policy.contact_cutoff_angstrom)
                found.update((_residue(atom), _residue(right_atoms[index])) for index in indices)
        return found

    expected = contacts(reference)
    predicted = contacts(matched)
    true_positive = len(expected & predicted)
    precision = ReferenceMetric(true_positive / len(predicted), None, comparison_count=len(predicted), **counts) if predicted else ReferenceMetric(None, "no-predicted-interface-contacts", **counts)
    recall = ReferenceMetric(true_positive / len(expected), None, comparison_count=len(expected), **counts) if expected else ReferenceMetric(None, "no-reference-interface-contacts", **counts)
    return InterfaceContacts(precision, recall, len(expected), len(predicted), true_positive)


def reference_metrics(
    reference: dict[AtomIdentity, np.ndarray], candidate: dict[AtomIdentity, np.ndarray],
    *, generated_residues: set[ResidueIdentity], anchor_residues: set[ResidueIdentity],
    chain_pairs: tuple[tuple[str, str], ...] = (),
    expected_generated_atoms: set[AtomIdentity] | None = None,
    policy: ReferenceMetricPolicy = ReferenceMetricPolicy(),
) -> ReferenceMetrics:
    """Generated centers and anchor/end-generated junction centers on a shared axis."""
    generated = {atom for atom in reference if _residue(atom) in generated_residues}
    junction = set(anchor_residues)
    by_chain: dict[str, list[ResidueIdentity]] = {}
    for atom in reference:
        residue = _residue(atom)
        rows = by_chain.setdefault(atom.chain, [])
        if residue not in rows:
            rows.append(residue)
    for anchor in anchor_residues:
        rows = by_chain.get(anchor.chain, [])
        if anchor not in rows:
            continue
        index = rows.index(anchor)
        for neighbor in rows[max(0, index - 1):index + 2]:
            if neighbor in generated_residues:
                junction.add(neighbor)
    junction_atoms = {atom for atom in reference if _residue(atom) in junction}
    declared = _pairs(chain_pairs)
    interface_atoms = {atom for atom in reference if atom.chain in {chain for pair in declared for chain in pair}}
    interface = local_lddt(reference, candidate, centers=interface_atoms, policy=policy, interface_chain_pairs=declared) if declared else ReferenceMetric(None, "interface-not-declared")
    generated_score = local_lddt(reference, candidate, centers=generated, policy=policy, expected_reference_atoms=expected_generated_atoms)
    junction_score = local_lddt(reference, candidate, centers=junction_atoms, policy=policy)
    present_residues = {_residue(atom) for atom in reference}
    if generated_residues - present_residues:
        generated_score = ReferenceMetric(None, "generated-residues-missing-from-reference")
    if anchor_residues - present_residues:
        junction_score = ReferenceMetric(None, "anchors-missing-from-reference")
    return ReferenceMetrics(
        policy,
        generated_score, junction_score,
        interface, interface_contacts(reference, candidate, chain_pairs=declared, policy=policy), declared,
    )


def summarize_reference_metrics(rows: tuple[tuple[ReferenceMetrics, bool], ...]) -> dict:
    """Keep defined/undefined and accepted/all-candidate denominators explicit."""
    if not rows:
        raise ValueError("reference metric summary requires cases")
    if any(metrics.policy != rows[0][0].policy for metrics, _passed in rows):
        raise ValueError("reference metric summaries require identical measurement definitions")
    summaries = {}
    for name in ("generated_lddt", "junction_lddt", "interface_lddt", "interface_contact_precision", "interface_contact_recall"):
        values = []
        valid_values = []
        reasons = Counter()
        missing_candidates = 0
        missing_references = 0
        reference_completeness_unknown = 0
        for metrics, passed in rows:
            metric = (metrics.interface_contacts.precision if name == "interface_contact_precision" else
                      metrics.interface_contacts.recall if name == "interface_contact_recall" else getattr(metrics, name))
            if metric.value is None:
                reasons[metric.undefined_reason] += 1
            else:
                values.append(metric.value)
                if passed:
                    valid_values.append(metric.value)
            missing_candidates += metric.missing_candidate_atom_count > 0
            missing_references += (metric.missing_reference_atom_count or 0) > 0
            reference_completeness_unknown += metric.missing_reference_atom_count is None
        summaries[name] = {
            "defined_case_count": len(values), "undefined_case_count": sum(reasons.values()),
            "undefined_reasons": dict(reasons), "defined_valid_case_count": len(valid_values),
            "median_all_candidates": float(median(values)) if values else None,
            "median_valid_candidates": float(median(valid_values)) if valid_values else None,
            "cases_with_missing_candidate_atoms": missing_candidates,
            "cases_with_missing_reference_atoms": missing_references,
            "reference_completeness_unknown_case_count": reference_completeness_unknown,
        }
    return {"schema_version": 1, "case_count": len(rows), "metrics": summaries}


@dataclass(frozen=True, slots=True)
class ReferenceScoreCase:
    case_id: str
    independence_group: str
    value: float | None
    validation_passed: bool


def paired_reference_score_difference(
    candidate: tuple[ReferenceScoreCase, ...], baseline: tuple[ReferenceScoreCase, ...],
    *, bootstrap_samples: int = 10_000, random_seed: int = 0,
) -> dict:
    """Descriptive median score delta on both-valid cases, cluster-bootstrap CI."""
    left = {case.case_id: case for case in candidate}
    right = {case.case_id: case for case in baseline}
    if not left or len(left) != len(candidate) or len(right) != len(baseline) or set(left) != set(right):
        raise ValueError("paired reference scores require unique identical case IDs")
    if bootstrap_samples <= 0:
        raise ValueError("bootstrap sample count must be positive")
    grouped: dict[str, list[float]] = {}
    undefined = 0
    rejected = 0
    for case_id in sorted(left):
        a, b = left[case_id], right[case_id]
        if a.independence_group != b.independence_group:
            raise ValueError("paired reference scores have inconsistent independence groups")
        for value in (a.value, b.value):
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("reference scores must be finite values in [0, 1]")
        if a.value is None or b.value is None:
            undefined += 1
        elif not (a.validation_passed and b.validation_passed):
            rejected += 1
        else:
            grouped.setdefault(a.independence_group, []).append(a.value - b.value)
    values = [value for rows in grouped.values() for value in rows]
    interval = None
    if grouped:
        groups = sorted(grouped)
        rng = np.random.default_rng(random_seed)
        bootstrapped = [
            float(median(value for index in rng.integers(0, len(groups), size=len(groups)) for value in grouped[groups[int(index)]]))
            for _ in range(bootstrap_samples)
        ]
        lower, upper = np.quantile(bootstrapped, (0.025, 0.975))
        interval = {"lower": float(lower), "upper": float(upper), "confidence_level": 0.95}
    return {
        "descriptive_only": True, "case_count": len(left), "both_valid_defined_case_count": len(values),
        "undefined_pair_count": undefined, "rejected_defined_pair_count": rejected,
        "independence_group_count": len(grouped), "minimum_30_groups_available": len(grouped) >= 30,
        "median_candidate_minus_baseline": float(median(values)) if values else None,
        "cluster_bootstrap_interval": interval, "higher_score_is_better": True,
    }
