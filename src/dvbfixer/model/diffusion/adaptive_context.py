"""Bounded research context expansion from sampled, never withheld, coordinates."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import numpy as np

from dvbfixer.model.diffusion.contract import (
    ArtifactReference,
    AtomIdentity,
    ContextCoordinate,
    DiffusionRequest,
    ResidueIdentity,
    protein_context_digest,
)
from dvbfixer.model.diffusion.protein_context import (
    ProteinContextError,
    select_protein_context,
    source_coordinates,
    validate_context_source,
)
from dvbfixer.model.diffusion.scope import _CANONICAL_ONE_TO_THREE


def sampled_backbone_queries(request: DiffusionRequest, candidate: bytes) -> tuple[ContextCoordinate, ...]:
    expected = {atom for atom in request.generated_atoms if atom.atom_name in {"N", "CA", "C", "O"}}
    if not expected:
        raise ProteinContextError("sampled adaptive backbone is empty")
    targets = {target.chain: target.sequence for target in request.target_sequences}
    names = {residue: _CANONICAL_ONE_TO_THREE[targets[gap.chain][index]]
             for gap in request.gaps for index, residue in zip(
                 range(gap.target_interval.start, gap.target_interval.stop), gap.generated_residues)}
    try:
        lines = candidate.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise ProteinContextError("sampled adaptive candidate is not an ASCII PDB") from exc
    if sum(line.startswith("MODEL ") for line in lines) > 1:
        raise ProteinContextError("sampled adaptive candidate contains multiple models")
    points = {}
    for line in lines:
        if not line.startswith("ATOM  "):
            continue
        try:
            atom = AtomIdentity(line[21], line[22:26].strip(), line[26].strip(), line[12:16].strip())
        except (ValueError, IndexError) as exc:
            raise ProteinContextError("malformed sampled adaptive atom identity") from exc
        if atom not in expected:
            continue
        if line[16] != " ":
            raise ProteinContextError("sampled adaptive backbone contains alternate locations")
        residue = ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code)
        if line[17:20].strip() != names[residue]:
            raise ProteinContextError("sampled adaptive backbone residue differs from the target sequence")
        if atom in points:
            raise ProteinContextError("sampled adaptive backbone contains duplicate identities")
        try:
            points[atom] = ContextCoordinate(atom, (float(line[30:38]), float(line[38:46]), float(line[46:54])))
        except ValueError as exc:
            raise ProteinContextError("sampled adaptive backbone contains invalid coordinates") from exc
    if set(points) != expected:
        raise ProteinContextError("sampled adaptive backbone is incomplete")
    return tuple(points[atom] for atom in request.generated_atoms if atom in expected)


def expand_from_sample(
    previous: DiffusionRequest, normalized_pdb: bytes, candidate: bytes, *, candidate_path: str,
) -> DiffusionRequest:
    """Expand between sampling rounds; retain every previously conditioned atom.

    A new atom axis is constructed for the next complete inference. This is not
    an unsupported in-place resize of a model's denoising tensors.
    """
    plan = previous.protein_context
    if plan is None:
        raise ProteinContextError("adaptive expansion requires an initial explicit context plan")
    validate_context_source(previous, normalized_pdb)
    queries = sampled_backbone_queries(previous, candidate)
    return select_protein_context(replace(previous, protein_context=None), normalized_pdb, plan.policy,
        trajectory_queries=queries, retained_conditioning=tuple(item.atom for item in plan.fixed_conditioning),
        previous_plan_sha256=protein_context_digest(plan),
        adaptation_source=ArtifactReference(candidate_path, hashlib.sha256(candidate).hexdigest()))


def validate_adaptive_transition(
    previous: DiffusionRequest, current: DiffusionRequest, normalized_pdb: bytes, candidate: bytes,
) -> None:
    plan = current.protein_context
    if plan is None or plan.adaptation_source is None:
        raise ProteinContextError("adaptive transition lacks sampled source evidence")
    expected = expand_from_sample(previous, normalized_pdb, candidate, candidate_path=plan.adaptation_source.path)
    if expected != current:
        raise ProteinContextError("adaptive transition differs from the verified sampled trajectory")


def contact_gated_expansion(
    previous: DiffusionRequest, normalized_pdb: bytes, candidate: bytes, *, candidate_path: str,
    initial_validation_passed: bool, distance_angstrom: float = 4.0,
    minimum_new_contact_residues: int = 2, minimum_supporting_backbone_atoms: int = 2,
) -> tuple[DiffusionRequest, dict[str, str | int | bool | float]]:
    """Research routing policy: preserve an accepted candidate's static context.

    Otherwise require multiple independently close sampled backbone atoms for
    each new contact residue. Uses no reference coordinates or reference scores.
    """
    if previous.protein_context is None:
        raise ProteinContextError("contact-gated expansion requires an initial context plan")
    if not np.isfinite(distance_angstrom) or distance_angstrom <= 0 or minimum_new_contact_residues < 1 or minimum_supporting_backbone_atoms < 1:
        raise ProteinContextError("invalid contact-gated adaptive policy")
    decision: dict[str, str | int | bool | float] = {"initial_validation_passed": initial_validation_passed,
        "distance_angstrom": distance_angstrom, "new_supported_contact_residue_count": 0, "expanded": False}
    if initial_validation_passed:
        decision["reason"] = "accepted-static-candidate-preserved"
        return previous, decision
    queries = np.asarray([query.coordinate_angstrom for query in sampled_backbone_queries(previous, candidate)])
    source = source_coordinates(previous, normalized_pdb)
    selected = {coordinate.atom for coordinate in previous.protein_context.fixed_conditioning}
    by_residue: dict[tuple[str, str, str], list[np.ndarray]] = {}
    for atom in previous.protein_context.preserved_only:
        if atom not in selected:
            by_residue.setdefault((atom.chain, atom.residue_number, atom.insertion_code), []).append(source[atom])
    supported = 0
    for points in by_residue.values():
        distances = np.linalg.norm(queries[:, None, :] - np.asarray(points)[None, :, :], axis=2)
        if int(np.count_nonzero(distances.min(axis=1) <= distance_angstrom)) >= minimum_supporting_backbone_atoms:
            supported += 1
    decision["new_supported_contact_residue_count"] = supported
    if supported < minimum_new_contact_residues:
        decision["reason"] = "insufficient-new-supported-contacts"
        return previous, decision
    expanded = expand_from_sample(previous, normalized_pdb, candidate, candidate_path=candidate_path)
    before = {coordinate.atom for coordinate in previous.protein_context.fixed_conditioning}
    after = {coordinate.atom for coordinate in expanded.protein_context.fixed_conditioning} if expanded.protein_context else set()
    if before == after:
        decision["reason"] = "no-additional-context-permitted-by-policy"
        return previous, decision
    decision["expanded"] = True
    decision["reason"] = "failed-static-candidate-with-supported-new-contacts"
    return expanded, decision
