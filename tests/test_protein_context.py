"""Context role partitions, source-only selection and explicit trace conformance."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    ArtifactReference,
    BackendProvenance,
    DiffusionContractError,
    DiffusionRequest,
    GapRegion,
    ProteinContextPolicy,
    ResidueIdentity,
    SequencePlacement,
    TargetInterval,
    TargetSequence,
)
from dvbfixer.model.diffusion.protein_context import (
    ProteinContextError,
    context_evidence,
    sampling_entities,
    select_protein_context,
    validate_context_capability,
)
from dvbfixer.model.diffusion.scope import canonical_heavy_atom_identities
from dvbfixer.model.diffusion.trace import build_sampler_trace, validate_sampler_trace_context


def context_request(chains=("D", "d"), partner_y=None):
    left, right = chains
    observed = (ResidueIdentity(left, "1"), ResidueIdentity(left, "5"))
    generated = tuple(ResidueIdentity(left, str(i)) for i in (2, 3, 4))
    partners = tuple(ResidueIdentity(right, str(i), "A" if i == 2 else "") for i in (1, 2, 3))
    fixed = tuple(atom for residue in (*observed, *partners) for atom in canonical_heavy_atom_identities(residue, "ALA"))
    coords = {}
    offsets = {"N": (-1, 0, 0), "CA": (0, 0, 0), "C": (1, 0, 0), "O": (1, 1, 0), "CB": (0, 0, 1)}
    text = ""
    for serial, atom in enumerate(fixed, 1):
        x = (int(atom.residue_number) - 1) * 3
        y = (partner_y or {}).get(int(atom.residue_number), 4) if atom.chain == right else 0
        point = np.asarray((x, y, 0)) + offsets[atom.atom_name]
        coords[atom] = point
        text += f"ATOM  {serial:5d} {atom.atom_name:>4s} ALA {atom.chain}{int(atom.residue_number):4d}{atom.insertion_code or ' '}   {point[0]:8.3f}{point[1]:8.3f}{point[2]:8.3f}  1.00  0.00          {atom.atom_name[0]:>2s}  \n"
    pdb = (text + "END\n").encode()
    request = DiffusionRequest(
        schema_version=DIFFUSION_SCHEMA_VERSION,
        normalized_pdb=ArtifactReference("input.pdb", hashlib.sha256(pdb).hexdigest()),
        target_sequences=(TargetSequence(left, "AAAAA"), TargetSequence(right, "AAA")),
        sequence_placements=(SequencePlacement(left, 5, (0, 4), observed), SequencePlacement(right, 3, (0, 1, 2), partners)),
        gaps=(GapRegion(left, TargetInterval(1, 4), observed[0], observed[1], generated, (*observed, *generated)),),
        fixed_atoms=fixed, generated_atoms=tuple(atom for residue in generated for atom in canonical_heavy_atom_identities(residue, "ALA")),
        retained_explicit_links=(), candidate_count=1, seeds=(7,),
    )
    return request, pdb


def test_disjoint_roles_and_case_sensitive_spans_are_source_deterministic():
    request, pdb = context_request()
    selected = select_protein_context(request, pdb, ProteinContextPolicy())
    assert selected == select_protein_context(request, pdb, ProteinContextPolicy())
    assert [entity.engine_chain for entity in sampling_entities(selected)] == ["D", "d"]
    roles = selected.protein_context
    assert set(roles.generated).isdisjoint(roles.movable_junction)
    assert set(roles.generated) | set(roles.movable_junction) == set(request.generated_atoms)
    assert len(roles.fixed_conditioning) == len(request.fixed_atoms)
    assert DiffusionRequest.from_json(selected.to_json()) == selected
    assert "protein_context" not in request.to_dict()  # Legacy canonical bytes stay stable.


def test_off_arm_preserves_partner_without_claiming_conditioning():
    request, pdb = context_request()
    off = select_protein_context(request, pdb, ProteinContextPolicy(target_flanks=1, partner_mode="none"))
    assert all(item.atom.chain == "D" for item in off.protein_context.fixed_conditioning)
    assert all(atom.chain == "d" for atom in off.protein_context.preserved_only)
    assert context_evidence(off, (*off.generated_atoms, *(item.atom for item in off.protein_context.fixed_conditioning))).capability == "gap-only"


def test_budget_failure_does_not_silently_drop_required_partner():
    request, pdb = context_request()
    with pytest.raises(ProteinContextError, match="no neighbors were silently dropped"):
        select_protein_context(request, pdb, ProteinContextPolicy(residue_budget=6))


def test_explicit_context_requires_matching_trace_evidence():
    request, pdb = context_request()
    selected = select_protein_context(request, pdb, ProteinContextPolicy(target_flanks=1, partner_mode="none"))
    atoms = tuple(item.atom for item in selected.protein_context.fixed_conditioning)
    axis = (*atoms, *selected.generated_atoms)
    proof = context_evidence(selected, axis)
    trace = build_sampler_trace(
        profile="test", engine_repository="test://engine", engine_revision="test", patch_identity="test",
        atom_order=axis, fixed_atoms=selected.fixed_atoms, represented_fixed_atoms=atoms,
        device="cpu", fallback_disabled=True, denoising_update_count=1,
        projection_errors_angstrom=(0.0,), final_fixed_coordinate_restoration=False,
        protein_context_evidence=proof,
    )
    provenance = BackendProvenance("test", 4, "test://engine", "test", device="cpu")
    validate_sampler_trace_context(trace, selected, provenance)
    with pytest.raises(DiffusionContractError, match="declared protein conditioning"):
        validate_sampler_trace_context(replace(trace, protein_context_evidence=None), selected, provenance)


def test_mutating_selected_coordinates_is_not_hidden_by_a_supplied_digest():
    request, pdb = context_request()
    selected = select_protein_context(request, pdb, ProteinContextPolicy())
    coordinate = selected.protein_context.fixed_conditioning[0]
    bad = replace(coordinate, coordinate_angstrom=(100.0, 100.0, 100.0))
    from dvbfixer.model.diffusion.protein_context import validate_context_source
    tampered = replace(selected, protein_context=replace(selected.protein_context, fixed_conditioning=(bad, *selected.protein_context.fixed_conditioning[1:])))
    with pytest.raises(ProteinContextError, match="coordinates do not match"):
        validate_context_source(tampered, pdb)


def load_research_module(relative):
    path = Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_discontiguous_partner_entities_round_trip_through_template_builder(tmp_path):
    import gemmi

    request, pdb = context_request(partner_y={2: 100})
    selected = select_protein_context(request, pdb, ProteinContextPolicy(sequence_padding=0))
    entities = sampling_entities(selected)
    assert [entity.engine_chain for entity in entities] == ["D", "d", "A"]
    assert [entity.residues for entity in entities[1:]] == [
        (ResidueIdentity("d", "1"),), (ResidueIdentity("d", "3"),),
    ]
    assert {atom.residue_number for atom in selected.protein_context.preserved_only} == {"2"}
    (tmp_path / "input.pdb").write_bytes(pdb)
    request_path = tmp_path / "request.json"
    request_path.write_text(selected.to_json())
    builder = load_research_module("deploy/protenix-v1/build-template-input.py")
    features = json.loads(builder.build_input(request_path, tmp_path / "features").read_text())[0]
    for entity, feature in zip(entities, features["sequences"], strict=True):
        protein = feature["proteinChain"]
        assert protein["id"] == [entity.engine_chain]
        assert protein["sequence"] == entity.target.sequence
        template = json.loads(Path(protein["templatesPath"]).read_text())[0]
        assert template["queryIndices"] == list(entity.placement.observed_target_indices)
        structure = gemmi.make_structure_from_block(gemmi.cif.read_string(template["mmcif"]).sole_block())
        residues = structure[0][entity.engine_chain]
        assert [(str(residue.seqid.num), residue.seqid.icode.strip()) for residue in residues] == [
            (residue.residue_number, residue.insertion_code) for residue in entity.placement.observed_residues
        ]


def test_failed_research_workspace_keeps_diagnostics_without_completion_marker(tmp_path):
    harness = load_research_module("scripts/run_protein_context_ablations.py")
    args = SimpleNamespace(work_parent=tmp_path, output=tmp_path / "outcomes")
    with pytest.raises(ValueError, match="injected failure"):
        with harness.diagnostic_workspace(args, "case", "local-partner") as workspace:
            (workspace / "worker.log").write_text("diagnostic evidence\n")
            raise ValueError("injected failure")
    assert not workspace.exists()
    archive, = (args.output / "failures" / "case").iterdir()
    assert (archive / "worker.log").read_text() == "diagnostic evidence\n"
    assert json.loads((archive / "failure.json").read_text())["exception_type"] == "ValueError"
    assert not (archive / "complete.json").exists()


def test_joint_gap_chains_are_one_exact_context_plan_and_fail_closed_for_protpardelle():
    first, first_pdb = context_request(("D", "d"))
    second, second_pdb = context_request(("d", "D"))
    pdb = ("".join(line + "\n" for line in first_pdb.decode().splitlines() if line.startswith("ATOM") and line[21] == "D")
           + "TER\n" + "".join(line + "\n" for line in second_pdb.decode().splitlines() if line.startswith("ATOM") and line[21] == "d") + "TER\nEND\n").encode()
    request = replace(first,
        normalized_pdb=ArtifactReference("input.pdb", hashlib.sha256(pdb).hexdigest()),
        target_sequences=(first.target_sequences[0], second.target_sequences[0]),
        sequence_placements=(first.sequence_placements[0], second.sequence_placements[0]),
        gaps=(*first.gaps, *second.gaps), generated_atoms=(*first.generated_atoms, *second.generated_atoms),
        fixed_atoms=tuple(atom for atom in first.fixed_atoms if atom.chain == "D") + tuple(atom for atom in second.fixed_atoms if atom.chain == "d"))
    selected = select_protein_context(request, pdb, ProteinContextPolicy(target_flanks=1, partner_mode="none"))
    entities = sampling_entities(selected)
    assert [entity.engine_chain for entity in entities] == ["D", "d"]
    axis = (*selected.fixed_atoms, *selected.generated_atoms)
    assert context_evidence(selected, axis).capability == "multichain-conditioned"
    validate_context_capability(selected, "protenix")
    with pytest.raises(ProteinContextError, match="joint gap-bearing"):
        validate_context_capability(selected, "protpardelle")
    with pytest.raises(ProteinContextError, match="require explicit"):
        validate_context_capability(request, "protenix")


@pytest.mark.parametrize("payload, reason", [(b"\xff", "valid UTF-8"), (b"ATOM  \n", "atom identity")])
def test_malformed_context_source_has_a_stable_prelaunch_error(payload, reason):
    request, _pdb = context_request()
    request = replace(request, normalized_pdb=ArtifactReference("input.pdb", hashlib.sha256(payload).hexdigest()))
    with pytest.raises(ProteinContextError, match=reason):
        select_protein_context(request, payload, ProteinContextPolicy())


def test_protpardelle_explicit_context_uses_shared_plan_and_cropped_gap_indices():
    request, pdb = context_request()
    selected = select_protein_context(request, pdb, ProteinContextPolicy(target_flanks=1))
    adapter = load_research_module("deploy/protpardelle-1c/checkpoint_gap_smoke.py")
    sampling, = adapter._chain_sampling_requests(selected)
    assert sampling.protein_context is None  # Internal cropped view, not new public semantics.
    assert sampling.fixed_atoms == tuple(item.atom for item in selected.protein_context.fixed_conditioning)
    assert sampling.generated_atoms == selected.generated_atoms
    assert adapter._target_residue_map(sampling)[1] == selected.gaps[0].generated_residues[0]
    request, pdb = context_request(partner_y={2: 100})
    discontiguous = select_protein_context(request, pdb, ProteinContextPolicy(sequence_padding=0))
    with pytest.raises(ProteinContextError, match="discontiguous"):
        validate_context_capability(discontiguous, "protpardelle")


def test_environment_metrics_fit_fixed_atoms_without_hiding_gap_movement():
    from dvbfixer.model.diffusion.context_metrics import measure_gap_environment
    from dvbfixer.model.diffusion.protein_context import source_coordinates

    request, pdb = context_request()
    reference = source_coordinates(request, pdb)
    reference.update({atom: np.asarray((float(atom.residue_number) * 3, 2, 1)) for atom in request.generated_atoms})
    rotation = np.asarray(((0, -1, 0), (1, 0, 0), (0, 0, 1)))
    candidate = {atom: rotation @ point + (50, -20, 10) for atom, point in reference.items()}
    measurement, = measure_gap_environment(request, reference, candidate)
    assert measurement.gap_backbone_rmsd_after_fixed_alignment_angstrom == pytest.approx(0, abs=1e-12)
    moved = {atom: point + rotation @ np.asarray((0, 4, 0)) if atom in request.generated_atoms else point
             for atom, point in candidate.items()}
    measurement, = measure_gap_environment(request, reference, moved)
    assert measurement.gap_backbone_rmsd_after_fixed_alignment_angstrom == pytest.approx(4)
    assert measurement.gap_centroid_displacement_angstrom == pytest.approx(4)
    assert measurement.gap_anchor_vector_angle_degrees > 0
    missing = {atom: point for atom, point in moved.items() if atom != request.generated_atoms[0]}
    measurement, = measure_gap_environment(request, reference, missing)
    assert measurement.gap_backbone_rmsd_after_fixed_alignment_angstrom is None
    assert "missing-generated-backbone" in measurement.undefined_reasons
