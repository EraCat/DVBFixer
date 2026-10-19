"""Clean-source eligibility must reject incompatibilities, never trim them away."""

import importlib
from pathlib import Path

import gemmi
import numpy as np
import pytest


@pytest.fixture
def materializer(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("materialize_clean_protein_cohort")


def complete_protein():
    structure = gemmi.Structure()
    model = gemmi.Model("1")
    chain = gemmi.Chain("a")
    for index in range(6):
        residue = gemmi.Residue()
        residue.name = "GLY"
        residue.seqid = gemmi.SeqId(index + 1, " ")
        residue.label_seq = index + 1
        residue.subchain = "polymer_a"
        residue.entity_type = gemmi.EntityType.Polymer
        for name, offset in (("N", 0), ("CA", 1.4), ("C", 2.5), ("O", 2.8)):
            atom = gemmi.Atom()
            atom.name = name
            atom.element = gemmi.Element(name[0])
            atom.pos = gemmi.Position(index * 3.8 + offset, 0, 0)
            residue.add_atom(atom)
        chain.add_residue(residue)
    model.add_chain(chain)
    structure.add_model(model)
    entity = gemmi.Entity("protein")
    entity.polymer_type = gemmi.PolymerType.PeptideL
    entity.full_sequence = ["GLY"] * 6
    entity.subchains = ["polymer_a"]
    structure.entities.append(entity)
    return structure


def test_clean_complete_protein_is_accepted_without_chain_renaming(materializer):
    structure = complete_protein()
    result = materializer.inspect_clean_structure(structure)
    assert result["supported"]
    assert result["chain_counts"] == {"a": 6}
    labels, unresolved = materializer.secondary_annotation(structure, "a", list(structure[0]["a"]))
    assert labels == [set()] * 6
    assert unresolved == 0  # No annotation is not evidence of a loop.


def test_bound_ion_rejects_whole_source_instead_of_disappearing(materializer):
    structure = complete_protein()
    ion = gemmi.Residue()
    ion.name = "ZN"
    ion.seqid = gemmi.SeqId(100, " ")
    ion.entity_type = gemmi.EntityType.NonPolymer
    atom = gemmi.Atom()
    atom.name = "ZN"
    atom.element = gemmi.Element("Zn")
    ion.add_atom(atom)
    structure[0]["a"].add_residue(ion)
    result = materializer.inspect_clean_structure(structure)
    assert not result["supported"]
    assert any("ZN100" in reason for reason in result["reasons"])
    assert len(structure[0]["a"]) == 7


def test_incomplete_residue_rejects_source_without_selecting_a_shorter_run(materializer):
    structure = complete_protein()
    structure[0]["a"][2].remove_atom("O", "\x00")
    result = materializer.inspect_clean_structure(structure)
    assert not result["supported"]
    assert any("incomplete-or-duplicate-heavy-atoms" in reason for reason in result["reasons"])
    assert len(structure[0]["a"]) == 6


def test_missing_native_sequence_position_is_not_a_clean_intact_source(materializer):
    structure = complete_protein()
    del structure[0]["a"][2]
    result = materializer.inspect_clean_structure(structure)
    assert not result["supported"]
    assert any("coordinate-incomplete-polymer-sequence" in reason for reason in result["reasons"])
    assert any("native-backbone-break" in reason for reason in result["reasons"])
    assert len(structure[0]["a"]) == 5


def test_homology_screen_does_not_count_scattered_matches_across_a_long_protein(materializer):
    rng = np.random.default_rng(31)
    alphabet = list("ACDEFGHIKLMNPQRSTVWY")
    short = "".join(rng.choice(alphabet, 141))
    unrelated_long = "".join(rng.choice(alphabet, 1980))
    assert materializer.sequence_overlap(short, unrelated_long) == 0


def test_homology_screen_still_detects_an_intact_shared_domain(materializer):
    rng = np.random.default_rng(17)
    alphabet = list("ACDEFGHIKLMNPQRSTVWY")
    domain = "".join(rng.choice(alphabet, 120))
    unrelated_prefix = "".join(rng.choice(alphabet, 500))
    unrelated_suffix = "".join(rng.choice(alphabet, 500))
    assert materializer.sequence_overlap(domain, unrelated_prefix + domain + unrelated_suffix) > 0.9
