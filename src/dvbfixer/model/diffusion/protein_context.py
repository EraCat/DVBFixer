"""Deterministic, source-only protein context selection and engine span mapping."""

from __future__ import annotations

import hashlib
import json
import string
from dataclasses import dataclass, replace

import numpy as np

from dvbfixer.domain.structure_identity import allocate_chain_ids
from dvbfixer.model.diffusion.contract import (
    ArtifactReference,
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
    TemplateOwnership,
    atom_identity_digest,
    protein_context_digest,
)
from dvbfixer.model.diffusion.scope import (
    _CANONICAL_ONE_TO_THREE,
    CANONICAL_HEAVY_ATOMS,
    canonical_heavy_atom_identities,
)


class ProteinContextError(ValueError):
    """Required context is incomplete, incompatible, or exceeds the engine budget."""


def source_coordinates(request: DiffusionRequest, pdb: bytes) -> dict[AtomIdentity, np.ndarray]:
    if hashlib.sha256(pdb).hexdigest() != request.normalized_pdb.sha256:
        raise ProteinContextError("context source digest mismatch")
    try:
        text = pdb.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProteinContextError("context source is not valid UTF-8") from exc
    fixed = set(request.fixed_atoms)
    points = {}
    for line in text.splitlines():
        if not line.startswith("ATOM  "):
            continue
        try:
            atom = AtomIdentity(line[21], line[22:26].strip(), line[26].strip(), line[12:16].strip())
        except (ValueError, IndexError) as exc:
            raise ProteinContextError("malformed context source atom identity") from exc
        if atom not in fixed:
            continue
        if atom in points:
            raise ProteinContextError("duplicate context source atom identity")
        try:
            coordinate = np.asarray([float(line[30:38]), float(line[38:46]), float(line[46:54])])
        except ValueError as exc:
            raise ProteinContextError("malformed context source coordinate") from exc
        if not np.isfinite(coordinate).all():
            raise ProteinContextError("non-finite context source coordinate")
        points[atom] = coordinate
    if set(points) != set(request.fixed_atoms):
        raise ProteinContextError("protein context requires every fixed atom in the normalized protein source")
    return points


def _residue(atom: AtomIdentity) -> ResidueIdentity:
    return ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code)


def select_protein_context(
    request: DiffusionRequest, pdb: bytes, policy: ProteinContextPolicy, *,
    trajectory_queries: tuple[ContextCoordinate, ...] | None = None,
    retained_conditioning: tuple[AtomIdentity, ...] | None = None,
    previous_plan_sha256: str | None = None,
    adaptation_source: ArtifactReference | None = None,
) -> DiffusionRequest:
    """Select complete spans from observed anchor atoms; never inspect withheld positions."""
    targets = {target.chain: target for target in request.target_sequences}
    placements = {placement.chain: placement for placement in request.sequence_placements}
    gap_chains = {gap.chain for gap in request.gaps}
    if not gap_chains or request.heterogen_contexts:
        raise ProteinContextError("protein context requires gap-bearing chains and canonical protein context")
    points = source_coordinates(request, pdb)
    atoms_by_residue: dict[ResidueIdentity, list[AtomIdentity]] = {}
    for atom in request.fixed_atoms:
        atoms_by_residue.setdefault(_residue(atom), []).append(atom)
    anchors = {anchor for gap in request.gaps for anchor in (gap.left_anchor, gap.right_anchor) if anchor is not None}
    anchor_points = np.asarray([points[atom] for residue in sorted(anchors) for atom in atoms_by_residue.get(residue, [])])
    if len(anchor_points) < 3:
        raise ProteinContextError("context requires complete observed anchor geometry")
    if trajectory_queries is not None:
        expected = {atom for atom in request.generated_atoms if atom.atom_name in {"N", "CA", "C", "O"}}
        if {query.atom for query in trajectory_queries} != expected:
            raise ProteinContextError("adaptive selection requires the complete generated backbone, not reference positions")
        anchor_points = np.concatenate((anchor_points, np.asarray([query.coordinate_angstrom for query in trajectory_queries])))
    selected: set[tuple[str, int]] = set()
    for gap in request.gaps:
        start = 0 if policy.target_flanks is None else max(0, gap.target_interval.start - policy.target_flanks)
        stop = len(targets[gap.chain].sequence) if policy.target_flanks is None else min(len(targets[gap.chain].sequence), gap.target_interval.stop + policy.target_flanks)
        selected.update((gap.chain, index) for index in range(start, stop))
    if retained_conditioning is not None:
        if not set(retained_conditioning) <= set(request.fixed_atoms):
            raise ProteinContextError("adaptive retained identities must belong to the immutable fixed source")
        retained_residues = {_residue(atom) for atom in retained_conditioning}
        selected.update((placement.chain, index) for placement in request.sequence_placements
                        for index, residue in zip(placement.observed_target_indices, placement.observed_residues) if residue in retained_residues)
    priorities = []
    for chain, placement in placements.items():
        if chain not in gap_chains and policy.partner_mode == "none":
            continue
        for index, residue in zip(placement.observed_target_indices, placement.observed_residues):
            if (chain, index) in selected:
                continue
            if chain in gap_chains and not policy.same_chain_spatial:
                continue
            residue_atoms = atoms_by_residue.get(residue, [])
            if not residue_atoms:
                continue
            distance = float(np.min(np.linalg.norm(np.asarray([points[atom] for atom in residue_atoms])[:, None, :] - anchor_points[None, :, :], axis=2)))
            full_partner = chain not in gap_chains and policy.partner_mode == "full"
            if not full_partner and distance > policy.secondary_radius_angstrom:
                continue
            rank = 0 if distance <= policy.direct_radius_angstrom else 1
            priorities.append((rank, distance, chain, index))
    # Include every required shell contact and complete neighboring sequence
    # windows. Priority is deterministic; budget failure never trims contacts.
    for _rank, _distance, chain, index in sorted(priorities):
        if policy.partner_mode == "full" and chain not in gap_chains:
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
    # Retain declared target order for gap-bearing entities and deterministic
    # partner order. Single-chain legacy plans retain their exact span ordering.
    for chain in (*(target.chain for target in request.target_sequences if target.chain in gap_chains), *sorted(set(targets) - gap_chains)):
        indices = sorted(index for c, index in selected if c == chain)
        for index in indices:
            if spans and spans[-1].chain == chain and spans[-1].stop == index:
                spans[-1] = ProteinContextSpan(chain, spans[-1].start, index + 1)
            else:
                spans.append(ProteinContextSpan(chain, index, index + 1))
    if policy.name == "intact-native-segments-v1":
        spans = _split_native_segments(request, pdb, points, spans)
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
        trajectory_queries, retained_conditioning, previous_plan_sha256, adaptation_source,
    )
    return replace(request, protein_context=plan)


def _split_native_segments(
    request: DiffusionRequest,
    pdb: bytes,
    points: dict[AtomIdentity, np.ndarray],
    spans: list[ProteinContextSpan],
) -> list[ProteinContextSpan]:
    """Keep observed native breaks as separate engine entities, not deletions.

    The intact-input research policy uses an observed-residue sequence axis.
    Consecutive axis indices do not imply a peptide bond across a native break.
    Artificial gaps are distinguished by their intervening generated indices.
    """
    indices = {residue: (placement.chain, index) for placement in request.sequence_placements
               for index, residue in zip(placement.observed_target_indices, placement.observed_residues)}
    boundaries: set[tuple[str, int]] = set()
    for placement in request.sequence_placements:
        observed = tuple(zip(placement.observed_target_indices, placement.observed_residues))
        for (left_index, left), (right_index, right) in zip(observed, observed[1:]):
            if right_index != left_index + 1:
                continue
            carbon = points.get(AtomIdentity(left.chain, left.residue_number, left.insertion_code, "C"))
            nitrogen = points.get(AtomIdentity(right.chain, right.residue_number, right.insertion_code, "N"))
            if carbon is None or nitrogen is None or not 1.0 <= float(np.linalg.norm(carbon - nitrogen)) <= 1.8:
                boundaries.add((placement.chain, right_index))
    previous = None
    terminated = False
    for line in pdb.decode().splitlines():
        if line.startswith("TER"):
            terminated = True
        elif line.startswith("ATOM  "):
            residue = ResidueIdentity(line[21], line[22:26].strip(), line[26].strip())
            if residue != previous:
                if terminated and previous in indices and residue in indices:
                    left_chain, left_index = indices[previous]
                    right_chain, right_index = indices[residue]
                    if left_chain == right_chain and right_index == left_index + 1:
                        boundaries.add((right_chain, right_index))
                previous = residue
                terminated = False
    separated = []
    for span in spans:
        cuts = [span.start, *(index for chain, index in sorted(boundaries) if chain == span.chain and span.start < index < span.stop), span.stop]
        separated.extend(ProteinContextSpan(span.chain, left, right) for left, right in zip(cuts, cuts[1:]))
    return separated


@dataclass(frozen=True)
class SamplingEntity:
    engine_chain: str
    target: TargetSequence
    placement: SequencePlacement
    residues: tuple[ResidueIdentity, ...]


@dataclass(frozen=True)
class EngineContextView:
    """Private engine identities plus an exact inverse to the scientific request."""

    request: DiffusionRequest
    atom_to_source: tuple[tuple[AtomIdentity, AtomIdentity], ...]

    def __post_init__(self) -> None:
        engine = [pair[0] for pair in self.atom_to_source]
        source = [pair[1] for pair in self.atom_to_source]
        if len(set(engine)) != len(engine) or len(set(source)) != len(source):
            raise ProteinContextError("engine context mapping must be bijective")
        if set(engine) != set(self.request.fixed_atoms) | set(self.request.generated_atoms):
            raise ProteinContextError("engine context mapping must cover every represented atom")


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


def engine_context_view(request: DiffusionRequest) -> EngineContextView:
    """Represent discontiguous spans as separate real chains, never concatenations.

    Only this internal view uses proxy chain IDs. Scientific source identities,
    including insertion codes and case-distinct chains, round trip through the map.
    """
    if request.protein_context is None:
        raise ProteinContextError("engine context view requires an explicit plan")
    entities = sampling_entities(request)
    selected = {item.atom for item in request.protein_context.fixed_conditioning}
    residue_map = {}
    position_map = {}
    for entity, span in zip(entities, request.protein_context.spans, strict=True):
        for index, residue in enumerate(entity.residues):
            residue_map[residue] = ResidueIdentity(entity.engine_chain, residue.residue_number, residue.insertion_code)
            position_map[(span.chain, span.start + index)] = (entity.engine_chain, index)

    def atom_map(atom: AtomIdentity) -> AtomIdentity:
        residue = residue_map[_residue(atom)]
        return AtomIdentity(residue.chain, residue.residue_number, residue.insertion_code, atom.atom_name)

    gaps = []
    for gap in request.gaps:
        chain, start = position_map[(gap.chain, gap.target_interval.start)]
        if any(position_map[(gap.chain, index)] != (chain, start + index - gap.target_interval.start)
               for index in range(gap.target_interval.start, gap.target_interval.stop)):
            raise ProteinContextError("one generated gap must fit completely within one engine entity")
        gaps.append(replace(gap, chain=chain, target_interval=type(gap.target_interval)(start, start + len(gap.generated_residues)),
                            left_anchor=residue_map[gap.left_anchor] if gap.left_anchor else None,
                            right_anchor=residue_map[gap.right_anchor] if gap.right_anchor else None,
                            generated_residues=tuple(residue_map[residue] for residue in gap.generated_residues),
                            movable_junction_residues=tuple(residue_map[residue] for residue in gap.movable_junction_residues)))

    def owner_map(owner: TemplateOwnership) -> TemplateOwnership:
        chain, index = position_map[(owner.chain, owner.target_index)]
        return replace(owner, chain=chain, target_index=index, residue=residue_map[owner.residue])

    represented = tuple(atom for atom in request.fixed_atoms if atom in selected) + request.generated_atoms
    internal = replace(request, protein_context=None,
        target_sequences=tuple(TargetSequence(entity.engine_chain, entity.target.sequence) for entity in entities),
        sequence_placements=tuple(SequencePlacement(entity.engine_chain, entity.placement.target_length,
            entity.placement.observed_target_indices, tuple(residue_map[residue] for residue in entity.placement.observed_residues)) for entity in entities),
        gaps=tuple(gaps), fixed_atoms=tuple(atom_map(atom) for atom in request.fixed_atoms if atom in selected),
        generated_atoms=tuple(atom_map(atom) for atom in request.generated_atoms), retained_explicit_links=(),
        template_ownership=tuple(owner_map(owner) for owner in request.template_ownership if owner.residue in {_residue(atom) for atom in selected}),
        regenerated_template_ownership=tuple(owner_map(owner) for owner in request.regenerated_template_ownership)
            if request.regenerated_template_ownership is not None else None)
    return EngineContextView(internal, tuple((atom_map(atom), atom) for atom in represented))


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
    capability = "multichain-conditioned" if len(target_chains) > 1 or any(atom.chain not in target_chains for atom in selected) else "same-chain-conditioned"
    if len(target_chains) == 1 and plan.policy.target_flanks == 1 and plan.policy.partner_mode == "none" and not plan.policy.same_chain_spatial:
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
    plan = request.protein_context
    expected = select_protein_context(replace(request, protein_context=None), pdb, plan.policy,
        trajectory_queries=plan.trajectory_queries, retained_conditioning=plan.retained_conditioning,
        previous_plan_sha256=plan.previous_plan_sha256, adaptation_source=plan.adaptation_source)
    if expected.protein_context != request.protein_context:
        raise ProteinContextError("protein context plan differs from deterministic source selection")


def validate_context_capability(request: DiffusionRequest, model: str) -> None:
    """Reject engine-incompatible plans before preflight or checkpoint loading."""
    if request.protein_context is None:
        if model == "protenix" and (len(request.target_sequences) != 1 or len(request.gaps) != 1):
            raise ProteinContextError("Protenix multiple chains or gaps require explicit --diffusion-context local|full")
        return
    if sum(span.stop - span.start for span in request.protein_context.spans) > 512:
        raise ProteinContextError("explicit protein context exceeds the audited 512-residue engine-axis budget")
    if model == "protenix":
        try:
            sampling_entities(request)
        except ValueError as exc:
            raise ProteinContextError(f"unsupported Protenix context mapping: {exc}") from exc
        return
    if model != "protpardelle":
        raise ProteinContextError("selected engine does not support explicit protein context")
    if len({gap.chain for gap in request.gaps}) != 1:
        raise ProteinContextError("Protpardelle explicit context does not support joint gap-bearing chains")
    spans = request.protein_context.spans
    if len({span.chain for span in spans}) != len(spans):
        raise ProteinContextError("Protpardelle explicit context does not support discontiguous source-chain entities")
    if len(spans) > 26:
        raise ProteinContextError("Protpardelle explicit context supports at most 26 engine chains")
    canonical_names = {name for names in CANONICAL_HEAVY_ATOMS.values() for name in names}
    if any(item.atom.atom_name not in canonical_names for item in request.protein_context.fixed_conditioning):
        raise ProteinContextError("Protpardelle explicit context contains atoms outside its audited canonical-heavy mask")


def select_legacy_partner_spans(
    request: DiffusionRequest,
    target_chain: str,
    coordinates: dict[AtomIdentity, np.ndarray],
    *,
    residue_budget: int,
) -> tuple[ProteinContextSpan, ...]:
    """Compatibility policy for the previously accepted cc89 local crops.

    This preserves the legacy 12 Å, one-run-per-chain, budget-trim behavior.
    Explicit context plans use the complete fail-closed selector above instead.
    Keeping the old policy here removes scientific selection from the adapter.
    """
    if residue_budget <= 0:
        return ()
    anchors = {anchor for gap in request.gaps if gap.chain == target_chain
               for anchor in (gap.left_anchor, gap.right_anchor) if anchor is not None}
    anchor_points = np.asarray([xyz for atom, xyz in coordinates.items() if _residue(atom) in anchors])
    if not len(anchor_points):
        return ()
    by_residue: dict[ResidueIdentity, list[np.ndarray]] = {}
    for atom, xyz in coordinates.items():
        by_residue.setdefault(_residue(atom), []).append(xyz)
    candidates = []
    for placement in request.sequence_placements:
        if placement.chain == target_chain:
            continue
        observed = tuple(zip(placement.observed_target_indices, placement.observed_residues))
        distances = {}
        for index, residue in observed:
            points = by_residue.get(residue, [])
            if points:
                distance = float(np.linalg.norm(np.asarray(points)[:, None] - anchor_points[None], axis=2).min())
                if distance <= 12.0:
                    distances[index] = distance
        if not distances:
            continue
        runs: list[list[tuple[int, ResidueIdentity]]] = []
        for item in observed:
            if not runs or item[0] != runs[-1][-1][0] + 1:
                runs.append([item])
            else:
                runs[-1].append(item)
        eligible = [run for run in runs if any(index in distances for index, _residue_id in run)]
        run = min(eligible, key=lambda items: (-sum(index in distances for index, _residue_id in items),
                                              min(distances.get(index, float("inf")) for index, _residue_id in items), items[0][0]))
        contacts = [index for index, _residue_id in run if index in distances]
        start = max(run[0][0], min(contacts) - 2)
        stop = min(run[-1][0] + 1, max(contacts) + 3)
        candidates.append((min(distances[index] for index in contacts), placement.chain, start, stop,
                           min(contacts, key=distances.__getitem__), run[0][0]))
    remaining = residue_budget
    spans = []
    for _distance, chain, start, stop, closest, run_start in sorted(candidates):
        if remaining <= 0:
            break
        if stop - start > remaining:
            start = max(start, closest - (remaining - 1) // 2)
            stop = min(stop, start + remaining)
            start = max(run_start, stop - remaining)
        spans.append(ProteinContextSpan(chain, start, stop))
        remaining -= stop - start
    return tuple(spans)
