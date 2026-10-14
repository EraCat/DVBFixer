"""Deterministic, source-only protein context selection and engine span mapping."""

from __future__ import annotations

import hashlib
import json
import string
from dataclasses import dataclass, replace

import numpy as np

from dvbfixer.domain.structure_identity import allocate_chain_ids
from dvbfixer.model.diffusion.contract import (
    AtomIdentity,
    ContextCoordinate,
    DiffusionRequest,
    ProteinContextEvidence,
    ProteinContextPlan,
    ProteinContextPolicy,
    ProteinContextSpan,
    ResidueIdentity,
    SequencePlacement,
    TargetSequence,
    atom_identity_digest,
    protein_context_digest,
)
from dvbfixer.model.diffusion.scope import _CANONICAL_ONE_TO_THREE, canonical_heavy_atom_identities


class ProteinContextError(ValueError):
    """Required context is incomplete, incompatible, or exceeds the engine budget."""


def source_coordinates(request: DiffusionRequest, pdb: bytes) -> dict[AtomIdentity, np.ndarray]:
    if hashlib.sha256(pdb).hexdigest() != request.normalized_pdb.sha256:
        raise ProteinContextError("context source digest mismatch")
    points = {}
    for line in pdb.decode("utf-8").splitlines():
        if not line.startswith("ATOM  "):
            continue
        atom = AtomIdentity(line[21], line[22:26].strip(), line[26].strip(), line[12:16].strip())
        if atom not in request.fixed_atoms:
            continue
        if atom in points:
            raise ProteinContextError("duplicate context source atom identity")
        coordinate = np.asarray([float(line[30:38]), float(line[38:46]), float(line[46:54])])
        if not np.isfinite(coordinate).all():
            raise ProteinContextError("non-finite context source coordinate")
        points[atom] = coordinate
    if set(points) != set(request.fixed_atoms):
        raise ProteinContextError("protein context requires every fixed atom in the normalized protein source")
    return points


def _residue(atom: AtomIdentity) -> ResidueIdentity:
    return ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code)


def select_protein_context(request: DiffusionRequest, pdb: bytes, policy: ProteinContextPolicy) -> DiffusionRequest:
    """Select complete spans from observed anchor atoms; never inspect withheld positions."""
    targets = {target.chain: target for target in request.target_sequences}
    placements = {placement.chain: placement for placement in request.sequence_placements}
    gap_chains = {gap.chain for gap in request.gaps}
    if len(gap_chains) != 1 or request.heterogen_contexts:
        raise ProteinContextError("context-v1 requires one gap-bearing chain and canonical protein context")
    target_chain = next(iter(gap_chains))
    points = source_coordinates(request, pdb)
    atoms_by_residue: dict[ResidueIdentity, list[AtomIdentity]] = {}
    for atom in request.fixed_atoms:
        atoms_by_residue.setdefault(_residue(atom), []).append(atom)
    anchors = {anchor for gap in request.gaps for anchor in (gap.left_anchor, gap.right_anchor) if anchor is not None}
    anchor_points = np.asarray([points[atom] for residue in sorted(anchors) for atom in atoms_by_residue.get(residue, [])])
    if len(anchor_points) < 3:
        raise ProteinContextError("context requires complete observed anchor geometry")
    first = min(gap.target_interval.start for gap in request.gaps)
    last = max(gap.target_interval.stop for gap in request.gaps)
    target_start = 0 if policy.target_flanks is None else max(0, first - policy.target_flanks)
    target_stop = len(targets[target_chain].sequence) if policy.target_flanks is None else min(len(targets[target_chain].sequence), last + policy.target_flanks)
    selected = {(target_chain, index) for index in range(target_start, target_stop)}
    priorities = []
    for chain, placement in placements.items():
        if chain != target_chain and policy.partner_mode == "none":
            continue
        for index, residue in zip(placement.observed_target_indices, placement.observed_residues):
            if (chain, index) in selected:
                continue
            if chain == target_chain and not policy.same_chain_spatial:
                continue
            residue_atoms = atoms_by_residue.get(residue, [])
            if not residue_atoms:
                continue
            distance = float(np.min(np.linalg.norm(np.asarray([points[atom] for atom in residue_atoms])[:, None, :] - anchor_points[None, :, :], axis=2)))
            full_partner = chain != target_chain and policy.partner_mode == "full"
            if not full_partner and distance > policy.secondary_radius_angstrom:
                continue
            rank = 0 if distance <= policy.direct_radius_angstrom else 1
            priorities.append((rank, distance, chain, index))
    # Include every required shell contact and complete neighboring sequence
    # windows. Priority is deterministic; budget failure never trims contacts.
    for _rank, _distance, chain, index in sorted(priorities):
        if policy.partner_mode == "full" and chain != target_chain:
            selected.update((chain, i) for i in range(len(targets[chain].sequence)))
        else:
            observed = set(placements[chain].observed_target_indices)
            left = index
            right = index + 1
            for _ in range(policy.sequence_padding):
                if left - 1 in observed:
                    left -= 1
                if right in observed:
                    right += 1
            selected.update((chain, i) for i in range(left, right))
    spans: list[ProteinContextSpan] = []
    for chain in (target_chain, *sorted(set(targets) - {target_chain})):
        indices = sorted(index for c, index in selected if c == chain)
        for index in indices:
            if spans and spans[-1].chain == chain and spans[-1].stop == index:
                spans[-1] = ProteinContextSpan(chain, spans[-1].start, index + 1)
            else:
                spans.append(ProteinContextSpan(chain, index, index + 1))
    if sum(span.stop - span.start for span in spans) > policy.residue_budget:
        raise ProteinContextError("required protein context exceeds residue budget; no neighbors were silently dropped")
    selected_residues = set()
    for chain, placement in placements.items():
        for index, residue in zip(placement.observed_target_indices, placement.observed_residues):
            if (chain, index) not in selected:
                continue
            expected = set(canonical_heavy_atom_identities(residue, _CANONICAL_ONE_TO_THREE[targets[chain].sequence[index]]))
            if not expected <= set(atoms_by_residue.get(residue, [])):
                raise ProteinContextError(f"selected context residue is heavy-atom-incomplete: {residue}")
            selected_residues.add(residue)
    selected_fixed = tuple(atom for atom in request.fixed_atoms if _residue(atom) in selected_residues)
    junction = {residue for gap in request.gaps for residue in (gap.generated_residues[0], gap.generated_residues[-1])}
    plan = ProteinContextPlan(
        policy, request.normalized_pdb.sha256, tuple(spans),
        tuple(atom for atom in request.generated_atoms if _residue(atom) not in junction),
        tuple(atom for atom in request.generated_atoms if _residue(atom) in junction),
        tuple(ContextCoordinate(atom, (float(points[atom][0]), float(points[atom][1]), float(points[atom][2]))) for atom in selected_fixed),
        tuple(atom for atom in request.fixed_atoms if atom not in selected_fixed),
    )
    return replace(request, protein_context=plan)


@dataclass(frozen=True)
class SamplingEntity:
    engine_chain: str
    target: TargetSequence
    placement: SequencePlacement
    residues: tuple[ResidueIdentity, ...]


def sampling_entities(request: DiffusionRequest) -> tuple[SamplingEntity, ...]:
    targets = {target.chain: target for target in request.target_sequences}
    placements = {placement.chain: placement for placement in request.sequence_placements}
    spans = request.protein_context.spans if request.protein_context else tuple(ProteinContextSpan(target.chain, 0, len(target.sequence)) for target in request.target_sequences)
    reserved = {span.chain for span in spans}
    extra_count = len(spans) - len(reserved - {" "})
    extra_labels = iter(allocate_chain_ids(extra_count, alphabet=tuple(string.ascii_uppercase + string.ascii_lowercase + string.digits), reserved=reserved))
    used = set()
    entities = []
    for span in spans:
        engine_chain = span.chain if span.chain not in used and span.chain != " " else next(extra_labels)
        used.add(engine_chain)
        placement = placements[span.chain]
        mapped = dict(zip(placement.observed_target_indices, placement.observed_residues))
        for gap in request.gaps:
            if gap.chain == span.chain:
                mapped.update(zip(range(gap.target_interval.start, gap.target_interval.stop), gap.generated_residues))
        if any(index not in mapped for index in range(span.start, span.stop)):
            raise ProteinContextError("sampling span contains an unmapped sequence position")
        observed = [(index - span.start, residue) for index, residue in zip(placement.observed_target_indices, placement.observed_residues) if span.start <= index < span.stop]
        entities.append(SamplingEntity(
            engine_chain, TargetSequence(span.chain, targets[span.chain].sequence[span.start:span.stop]),
            SequencePlacement(span.chain, span.stop - span.start, tuple(index for index, _residue_id in observed), tuple(residue for _index, residue in observed)),
            tuple(mapped[index] for index in range(span.start, span.stop)),
        ))
    return tuple(entities)


def selected_coordinate_digest(plan: ProteinContextPlan) -> str:
    payload = [[item.atom.chain, item.atom.residue_number, item.atom.insertion_code, item.atom.atom_name, *item.coordinate_angstrom] for item in plan.fixed_conditioning]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def context_evidence(request: DiffusionRequest, atom_axis: tuple[AtomIdentity, ...]) -> ProteinContextEvidence:
    plan = request.protein_context
    if plan is None:
        raise ProteinContextError("context evidence requires an explicit selection plan")
    selected = tuple(item.atom for item in plan.fixed_conditioning)
    target_chains = {gap.chain for gap in request.gaps}
    primary_residues = {
        residue for entity in sampling_entities(request)
        if set(entity.residues) & {_residue(atom) for atom in request.generated_atoms}
        for residue in entity.residues
    }
    alignment = tuple(atom for atom in selected if _residue(atom) in primary_residues)
    capability = "multichain-conditioned" if any(atom.chain not in target_chains for atom in selected) else "same-chain-conditioned"
    if plan.policy.target_flanks == 1 and plan.policy.partner_mode == "none" and not plan.policy.same_chain_spatial:
        capability = "gap-only"
    return ProteinContextEvidence(protein_context_digest(plan), atom_identity_digest(atom_axis), selected_coordinate_digest(plan), selected, plan.preserved_only, alignment, capability)


def validate_context_source(request: DiffusionRequest, pdb: bytes) -> None:
    if request.protein_context is None:
        return
    points = source_coordinates(request, pdb)
    for item in request.protein_context.fixed_conditioning:
        if not np.array_equal(points[item.atom], item.coordinate_angstrom):
            raise ProteinContextError("declared conditioning coordinates do not match normalized source")
    # Recompute the complete deterministic selection, not merely its supplied hash.
    expected = select_protein_context(replace(request, protein_context=None), pdb, request.protein_context.policy)
    if expected.protein_context != request.protein_context:
        raise ProteinContextError("protein context plan differs from deterministic source selection")
