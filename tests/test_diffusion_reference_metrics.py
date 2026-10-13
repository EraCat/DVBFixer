"""Independent distance-score examples, honest denominators and interface identity."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from dvbfixer.model.diffusion.benchmark import candidate_quality
from dvbfixer.model.diffusion.contract import AtomIdentity, ResidueIdentity
from dvbfixer.model.diffusion.reference_metrics import (
    ReferenceMetricPolicy,
    ReferenceScoreCase,
    interface_contacts,
    local_lddt,
    paired_reference_score_difference,
    reference_metrics,
    summarize_reference_metrics,
)


def _pair(distance=1.0):
    return {
        AtomIdentity("A", "1", "", "CA"): np.asarray((0.0, 0.0, 0.0)),
        AtomIdentity("A", "2", "", "CA"): np.asarray((distance, 0.0, 0.0)),
    }


def test_standard_thresholds_are_strict_and_neighbor_radius_is_strict():
    reference = _pair()
    result = local_lddt(reference, _pair(2.0), centers=set(reference))
    assert result.value == 0.5  # delta=1: passes only 2 and 4 Å thresholds.
    assert result.scored_atom_count == 2
    assert result.comparison_count == 2
    exact_boundary = _pair(15.0)
    assert local_lddt(exact_boundary, exact_boundary, centers=set(exact_boundary)).undefined_reason == "no-reference-neighbor-pairs"


def test_mean_per_atom_is_not_pair_count_weighted():
    atoms = [AtomIdentity("A", str(index), "", "CA") for index in (1, 2, 3)]
    reference = dict(zip(atoms, (np.asarray((x, 0.0, 0.0)) for x in (0.0, 1.0, 15.5))))
    candidate = dict(zip(atoms, (np.asarray((x, 0.0, 0.0)) for x in (0.0, 2.0, 16.5))))
    score = local_lddt(reference, candidate, centers=set(atoms[:2]))
    assert score.value == 0.625  # mean of atom scores 0.5 and 0.75, not 2/3.


def test_missing_atoms_are_zero_contributions_not_removed_from_denominator():
    reference = _pair()
    candidate = {next(iter(reference)): np.zeros(3)}
    result = local_lddt(reference, candidate, centers=set(reference))
    assert result.value == 0.0
    assert result.comparison_count == 2
    assert result.missing_candidate_atom_count == 1


def test_same_residue_pairs_do_not_inflate_local_score():
    reference = _pair(3.0)
    cb = AtomIdentity("A", "1", "", "CB")
    reference[cb] = np.asarray((1.0, 0.0, 0.0))
    candidate = {atom: point.copy() for atom, point in reference.items()}
    candidate[cb] += 100.0
    result = local_lddt(reference, candidate, centers={AtomIdentity("A", "1", "", "CA")})
    assert result.value == 1.0
    assert result.comparison_count == 1


def test_distance_score_is_rigid_transform_invariant_but_does_not_override_validation():
    reference = _pair(3.0)
    rotation = np.asarray(((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
    candidate = {atom: rotation @ point + (10, 20, 30) for atom, point in reference.items()}
    quality = candidate_quality(
        "rejected", reference, candidate, generated_residues={ResidueIdentity("A", "2")},
        fixed_atoms={AtomIdentity("A", "1", "", "CA")}, anchor_residues={ResidueIdentity("A", "1")},
        closure_passed=False, validation_passed=False,
    )
    assert quality.reference_metrics.generated_lddt.value == 1.0
    assert quality.fixed_heavy_rmsd_angstrom > 0.0
    assert quality.validation_passed is False


def test_interface_contacts_preserve_case_distinct_chains_and_insertion_codes():
    reference = {
        AtomIdentity("D", "82", "A", "CA"): np.asarray((0.0, 0.0, 0.0)),
        AtomIdentity("D", "82", "a", "CA"): np.asarray((20.0, 0.0, 0.0)),
        AtomIdentity("D", "90", "", "CA"): np.asarray((80.0, 0.0, 0.0)),
        AtomIdentity("d", "1", "", "CA"): np.asarray((4.0, 0.0, 0.0)),
        AtomIdentity("d", "2", "", "CA"): np.asarray((40.0, 0.0, 0.0)),
        AtomIdentity("d", "3", "", "CA"): np.asarray((84.0, 0.0, 0.0)),
    }
    candidate = {atom: point.copy() for atom, point in reference.items()}
    candidate[AtomIdentity("d", "1", "", "CA")] = np.asarray((40.0, 0.0, 0.0))
    candidate[AtomIdentity("d", "2", "", "CA")] = np.asarray((24.0, 0.0, 0.0))
    result = interface_contacts(reference, candidate, chain_pairs=(("D", "d"),))
    assert result.reference_contact_count == 2
    assert result.candidate_contact_count == 2
    assert result.true_positive_contact_count == 1
    assert result.precision.value == 0.5 and result.recall.value == 0.5


def test_interface_lddt_excludes_preserved_noninterface_atoms():
    reference = {AtomIdentity("A", "1", "", "CA"): np.zeros(3),
                 AtomIdentity("A", "2", "", "CA"): np.asarray((100.0, 0.0, 0.0)),
                 AtomIdentity("B", "1", "", "CA"): np.asarray((5.0, 0.0, 0.0))}
    candidate = {atom: point.copy() for atom, point in reference.items()}
    candidate[AtomIdentity("A", "2", "", "CA")][0] = 200.0
    score = local_lddt(reference, candidate, centers=set(reference), interface_chain_pairs=(("A", "B"),))
    assert score.value == 1.0 and score.scored_atom_count == 2
    contacts = interface_contacts(reference, reference, chain_pairs=(("A", "B"),))
    assert contacts.precision.value == 1.0  # Inclusive 5 Å contact boundary.


def test_empty_interface_denominators_are_undefined_not_perfect():
    reference = _pair()
    assert interface_contacts(reference, reference, chain_pairs=()).precision.undefined_reason == "interface-not-declared"
    moved_chain = {AtomIdentity("B", "1", "", "CA"): np.asarray((100.0, 0.0, 0.0))}
    reference.update(moved_chain)
    result = interface_contacts(reference, reference, chain_pairs=(("A", "B"),))
    assert result.precision.value is None and result.recall.value is None
    assert result.recall.undefined_reason == "no-reference-interface-contacts"


def test_reference_incompleteness_is_counted_without_inventing_coordinates():
    reference = _pair()
    center = AtomIdentity("A", "2", "", "CA")
    absent_reference = AtomIdentity("A", "2", "", "CB")
    result = local_lddt(reference, reference, centers={center}, expected_reference_atoms={center, absent_reference})
    assert result.value == 1.0
    assert result.missing_reference_atom_count == 1


def test_invalid_coordinates_and_duplicate_interface_declarations_are_explicit():
    reference = _pair()
    invalid = {atom: point.copy() for atom, point in reference.items()}
    invalid[next(iter(invalid))][0] = np.nan
    assert local_lddt(reference, invalid, centers=set(reference)).undefined_reason == "invalid-candidate-coordinates"
    with pytest.raises(ValueError, match="repeat"):
        interface_contacts(reference, reference, chain_pairs=(("D", "d"), ("d", "D")))


def test_junction_centers_use_reference_order_not_numeric_residue_ranges():
    reference = {
        AtomIdentity("D", "82", "", "CA"): np.asarray((0.0, 0.0, 0.0)),
        AtomIdentity("D", "82", "A", "CA"): np.asarray((3.0, 0.0, 0.0)),
        AtomIdentity("D", "82", "B", "CA"): np.asarray((6.0, 0.0, 0.0)),
        AtomIdentity("D", "83", "", "CA"): np.asarray((9.0, 0.0, 0.0)),
    }
    result = reference_metrics(
        reference, reference,
        generated_residues={ResidueIdentity("D", "82", "A"), ResidueIdentity("D", "82", "B")},
        anchor_residues={ResidueIdentity("D", "82"), ResidueIdentity("D", "83")},
    )
    assert result.junction_lddt.scored_atom_count == 4
    assert result.generated_lddt.value == 1.0


def test_aggregation_retains_undefined_and_rejected_denominators():
    reference = _pair(3.0)
    metrics = reference_metrics(reference, reference, generated_residues={ResidueIdentity("A", "2")}, anchor_residues={ResidueIdentity("A", "1")})
    summary = summarize_reference_metrics(((metrics, True), (metrics, False)))
    assert summary["case_count"] == 2
    assert summary["metrics"]["generated_lddt"]["defined_case_count"] == 2
    assert summary["metrics"]["generated_lddt"]["defined_valid_case_count"] == 1
    assert summary["metrics"]["interface_lddt"]["undefined_reasons"] == {"interface-not-declared": 2}
    changed_definition = replace(metrics, policy=ReferenceMetricPolicy(neighbor_radius_angstrom=10.0))
    with pytest.raises(ValueError, match="identical measurement definitions"):
        summarize_reference_metrics(((metrics, True), (changed_definition, True)))


def test_paired_difference_does_not_treat_missing_or_rejected_scores_as_zero():
    candidate = (
        ReferenceScoreCase("a", "group-a", 0.9, True),
        ReferenceScoreCase("b", "group-b", 0.7, False),
        ReferenceScoreCase("c", "group-c", None, True),
    )
    baseline = (
        ReferenceScoreCase("a", "group-a", 0.5, True),
        ReferenceScoreCase("b", "group-b", 0.2, True),
        ReferenceScoreCase("c", "group-c", 0.3, True),
    )
    result = paired_reference_score_difference(candidate, baseline, bootstrap_samples=100)
    assert result["case_count"] == 3
    assert result["both_valid_defined_case_count"] == 1
    assert result["rejected_defined_pair_count"] == 1
    assert result["undefined_pair_count"] == 1
    assert result["median_candidate_minus_baseline"] == pytest.approx(0.4)
    assert result["minimum_30_groups_available"] is False
    with pytest.raises(ValueError, match="identical case IDs"):
        paired_reference_score_difference(candidate, baseline[:1])


def test_matches_independent_biotite_atom_aggregation_when_available():
    structure = pytest.importorskip("biotite.structure")
    atoms = [AtomIdentity("A", str(index), "", "CA") for index in range(1, 7)]
    points = np.asarray(((0, 0, 0), (2, 1, 0), (5, 0, 1), (9, 2, 0), (12, 1, 2), (19, 0, 0)), dtype=float)
    predicted = points + np.asarray(((0, 0, 0), (0.3, 0.2, 0), (1.1, 0, 0.3), (0, 0.8, 0), (2.3, 0, 0), (0, 0, 0)))
    array = structure.AtomArray(len(atoms))
    array.coord = points
    array.chain_id[:] = "A"
    array.res_id = np.arange(1, 7)
    mask = np.asarray((True, True, True, False, False, False))
    independent = structure.lddt(array, predicted, aggregation="atom", atom_mask=mask)
    measured = local_lddt(dict(zip(atoms, points)), dict(zip(atoms, predicted)), centers=set(atoms[:3]))
    assert measured.value == pytest.approx(float(np.nanmean(independent)), abs=1e-6)
