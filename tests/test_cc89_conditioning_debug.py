"""Sparse learned conditioning must not change the scientific gap or token axis."""

import importlib
from pathlib import Path

import pytest

from dvbfixer.model.diffusion.protein_context import (
    engine_context_view,
    sampling_entities,
    select_protein_context,
    source_coordinates,
)


@pytest.fixture
def debug(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("debug_cc89_conditioning")


@pytest.fixture
def source_request(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parent))
    return importlib.import_module("test_protein_context").context_request()


def test_sparse_motif_retains_full_axis_and_never_conditions_on_gap(debug, source_request):
    from dvbfixer.model.diffusion.contract import ProteinContextPolicy

    request, pdb = source_request
    request = select_protein_context(request, pdb, ProteinContextPolicy())
    view = engine_context_view(request)
    points = source_coordinates(request, pdb)
    coordinates = {engine: points[src] for engine, src in view.atom_to_source if src in points}
    all_atoms = debug.conditioning_atoms(view.request, coordinates, None)
    assert debug.motif_placement(view.request, all_atoms) == ("A1-1/3/A5-5;/;B1-3", [0, 4, 5, 6, 7])
    sparse = debug.conditioning_atoms(view.request, coordinates, 2)
    assert len(sparse) == 10  # Two complete ALA anchors, not two arbitrary atoms.
    assert not set(sparse) & set(view.request.generated_atoms)
    assert debug.motif_placement(view.request, sparse) == ("A1-1/3/A5-5;/;3", [0, 4])
    assert tuple(len(t.sequence) for t in view.request.target_sequences) == (5, 3)
    assert debug.conditioning_atoms(view.request, coordinates, 2) == sparse


def test_sparse_budget_cannot_drop_an_anchor_or_accept_generated_coordinates(debug, source_request):
    request, _ = source_request
    coordinates = {atom: (0, 0, 0) for atom in request.fixed_atoms}
    with pytest.raises(ValueError, match="every anchor"):
        debug.conditioning_atoms(request, coordinates, 1)
    with pytest.raises(ValueError, match="never generated"):
        debug.motif_placement(request, request.generated_atoms)


def test_source_position_features_keep_discontinuous_parent_chain_identity(monkeypatch):
    from dvbfixer.model.diffusion.contract import ProteinContextPolicy

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parent))
    module = importlib.import_module("debug_cc89_chain_axes")
    request, pdb = importlib.import_module("test_protein_context").context_request(partner_y={2: 100})
    selected = select_protein_context(request, pdb, ProteinContextPolicy(sequence_padding=0))
    assert len(sampling_entities(selected)) == 3
    indices, chains = module.source_position_features(selected)
    assert indices == [1, 2, 3, 4, 5, 206, 208]
    assert chains == [0, 0, 0, 0, 0, 1, 1]


def test_local_physical_features_do_not_turn_proxy_fragments_into_new_chains(monkeypatch):
    from dvbfixer.model.diffusion.contract import ProteinContextPolicy

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parent))
    module = importlib.import_module("audit_cc89_local_input")
    request, pdb = importlib.import_module("test_protein_context").context_request(partner_y={2: 100})
    selected = select_protein_context(request, pdb, ProteinContextPolicy(sequence_padding=0))
    positions, chains = module.physical_positions(selected)
    assert len(sampling_entities(selected)) == 3  # Three serialization entities.
    assert chains == [0, 0, 0, 0, 0, 1, 1]  # Only two physical source chains.
    assert positions == [1, 2, 3, 4, 5, 205, 207]
    assert positions[-1] - positions[-2] == 2  # Omitted native residue is not a peptide neighbor.
    assert positions[5] - positions[4] == 200
