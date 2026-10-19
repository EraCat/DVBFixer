"""Trace fragment truncation independently of missing-residue reconstruction."""

import importlib
from pathlib import Path

import gemmi


def gly_chain(name, start, count, *, axis="x", offset=0):
    chain = gemmi.Chain(name)
    for index in range(count):
        residue = gemmi.Residue()
        residue.name = "GLY"
        residue.seqid = gemmi.SeqId(start + index, " ")
        for atom_name, along, transverse in (("N", 0, 0), ("CA", 1.4, 0), ("C", 2.5, 0), ("O", 2.8, 0.5)):
            atom = gemmi.Atom()
            atom.name = atom_name
            atom.element = gemmi.Element(atom_name[0])
            position = index * 3.8 + along
            atom.pos = gemmi.Position(position, offset + transverse, 0) if axis == "x" else gemmi.Position(offset + transverse, position + 5, 0)
            residue.add_atom(atom)
        chain.add_residue(residue)
    return chain


def test_incomplete_sidechain_splits_otherwise_observed_chain(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    audit = importlib.import_module("audit_gap_chain_coverage")
    chain = gly_chain("A", 1, 3)
    chain[1].name = "LYS"  # Backbone present, but lysine's side chain is absent.
    assert len(chain) == 3
    assert [len(run) for run in audit.complete_runs(chain)] == [1, 1]
    event = audit.breakup_events(chain)[0]
    assert event["reason"] == "incomplete-heavy-atoms"
    assert event["residue"] == "2"
    assert "NZ" in event["missing"]


def test_partner_is_cropped_after_noncanonical_residue_not_lost_by_parser(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    audit = importlib.import_module("audit_gap_chain_coverage")
    structure = gemmi.Structure()
    model = gemmi.Model("1")
    model.add_chain(gly_chain("D", 2058, 111, axis="y", offset=300))
    partner = gly_chain("V", 59, 155)
    partner[18].name = "CAS"  # Residue 77 breaks the canonical-only selection.
    model.add_chain(partner)
    structure.add_model(model)
    assert len(structure[0]["V"]) == 155
    selected = dict(audit.replay_selection(structure, "D"))
    assert len(selected["V"]) == 120
    assert audit.span(selected["V"]) == "78…197"
    assert any(event.get("residue") == "77" and event["reason"] == "noncanonical-amino-acid"
               for event in audit.breakup_events(structure[0]["V"]))
