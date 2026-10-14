"""Reference-dependent gap orientation and fixed-environment measurements.

These are descriptive measurements, not additional scientific acceptance gates.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dvbfixer.model.diffusion.contract import AtomIdentity, DiffusionRequest
from dvbfixer.model.diffusion.geometry import weighted_kabsch


@dataclass(frozen=True)
class GapEnvironmentMeasurement:
    chain: str
    start: int
    stop: int
    fixed_alignment_atom_count: int
    gap_backbone_rmsd_after_fixed_alignment_angstrom: float | None
    gap_centroid_displacement_angstrom: float | None
    gap_anchor_vector_angle_degrees: float | None
    minimum_generated_interchain_distance_angstrom: float | None
    generated_interchain_pairs_below_1_2_angstrom: int | None
    undefined_reasons: tuple[str, ...]


def measure_gap_environment(
    request: DiffusionRequest,
    reference: dict[AtomIdentity, np.ndarray],
    candidate: dict[AtomIdentity, np.ndarray],
) -> tuple[GapEnvironmentMeasurement, ...]:
    """Fit only fixed atoms; never fit the generated region to its reference."""
    fixed = tuple(sorted(set(request.fixed_atoms) & reference.keys() & candidate.keys()))
    aligned = None
    if len(fixed) >= 3:
        try:
            transform = weighted_kabsch(np.asarray([candidate[atom] for atom in fixed]),
                                        np.asarray([reference[atom] for atom in fixed]))
            aligned = {atom: transform.apply(np.asarray([xyz]))[0] for atom, xyz in candidate.items()}
        except ValueError:
            pass
    measurements = []
    for gap in request.gaps:
        reasons = []
        gap_residues = {(residue.chain, residue.residue_number, residue.insertion_code) for residue in gap.generated_residues}
        backbone = tuple(atom for atom in request.generated_atoms
                         if atom.chain == gap.chain and atom.atom_name in {"N", "CA", "C", "O"}
                         and any((atom.residue_number, atom.insertion_code) == (residue.residue_number, residue.insertion_code)
                                 for residue in gap.generated_residues))
        rmsd = displacement = angle = None
        if aligned is None:
            reasons.append("insufficient-or-degenerate-fixed-alignment")
        elif not backbone or not set(backbone) <= reference.keys() & candidate.keys():
            reasons.append("missing-generated-backbone")
        else:
            expected = np.asarray([reference[atom] for atom in backbone])
            observed = np.asarray([aligned[atom] for atom in backbone])
            rmsd = float(np.sqrt(np.mean(np.sum((observed - expected) ** 2, axis=1))))
            displacement = float(np.linalg.norm(observed.mean(axis=0) - expected.mean(axis=0)))
            anchors = tuple(AtomIdentity(residue.chain, residue.residue_number, residue.insertion_code, "CA")
                            for residue in (gap.left_anchor, gap.right_anchor) if residue is not None)
            if not anchors or not set(anchors) <= reference.keys():
                reasons.append("missing-anchor-ca")
            else:
                origin = np.asarray([reference[atom] for atom in anchors]).mean(axis=0)
                first = expected.mean(axis=0) - origin
                second = observed.mean(axis=0) - origin
                denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
                if denominator <= 1e-12:
                    reasons.append("degenerate-gap-anchor-vector")
                else:
                    angle = float(np.degrees(np.arccos(np.clip(np.dot(first, second) / denominator, -1, 1))))
        generated = [candidate[atom] for atom in request.generated_atoms if atom in candidate
                     and (atom.chain, atom.residue_number, atom.insertion_code) in gap_residues]
        neighbors = [xyz for atom, xyz in candidate.items() if atom.chain != gap.chain and not atom.atom_name.startswith(("H", "D"))]
        minimum = None
        overlaps = None
        if generated and neighbors:
            distances = np.linalg.norm(np.asarray(generated)[:, None, :] - np.asarray(neighbors)[None, :, :], axis=2)
            minimum = float(distances.min())
            overlaps = int(np.count_nonzero(distances < 1.2))
        else:
            reasons.append("no-generated-interchain-pairs")
        measurements.append(GapEnvironmentMeasurement(gap.chain, gap.target_interval.start, gap.target_interval.stop,
                            len(fixed), rmsd, displacement, angle, minimum, overlaps, tuple(reasons)))
    return tuple(measurements)
