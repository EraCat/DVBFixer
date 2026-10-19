"""Intact-source masks must preserve background chains and native segments."""

import importlib
from dataclasses import asdict
from pathlib import Path

from dvbfixer.model.diffusion.contract import ResidueIdentity
from dvbfixer.model.diffusion.validate import _parse_pdb_text


def test_far_background_chain_is_preserved_even_when_not_conditioned(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    module = importlib.import_module("materialize_intact_recheck")
    fixture = Path(__file__).parent / "fixtures/protein_context/1UBQ.pdb"
    original = [line for line in fixture.read_text().splitlines(keepends=True) if line.startswith("ATOM  ")]
    partner = []
    for line in original:
        line = line[:6] + f"{int(line[6:11]) + 10000:5d}" + line[11:21] + "b" + line[22:]
        line = line[:30] + f"{float(line[30:38]) + 100:8.3f}" + line[38:]
        partner.append(line)
    before, _ = module.prepare_intact_pdb("".join(original) + "TER\n" + "".join(partner) + "TER\nEND\n")
    generated = [ResidueIdentity("A", str(number)) for number in range(10, 15)]
    gap = {"chain": "A", "generated_residues": [asdict(residue) for residue in generated],
        "left_anchor": asdict(ResidueIdentity("A", "9")), "right_anchor": asdict(ResidueIdentity("A", "15"))}
    request, masked = module.make_intact_request(before, {"gap": gap})
    source_atoms, source_residues, _ = _parse_pdb_text(before.decode())
    remaining, remaining_residues, _ = _parse_pdb_text(masked.decode())
    assert len(source_residues) == 152
    assert len(remaining_residues) == 147
    assert all(atom in remaining for atom in source_atoms if atom.chain == "b")
    assert all(atom in request.protein_context.preserved_only for atom in remaining if atom.chain == "b")
    assert not any(item.atom.chain == "b" for item in request.protein_context.fixed_conditioning)
    assert set(source_atoms) - set(remaining) == set(request.generated_atoms)


def test_native_break_is_marked_without_deleting_either_side(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    module = importlib.import_module("materialize_intact_recheck")
    fixture = Path(__file__).parent / "fixtures/protein_context/1UBQ.pdb"
    lines = []
    for line in fixture.read_text().splitlines(keepends=True):
        if not line.startswith("ATOM  "):
            continue
        if int(line[22:26]) > 40:
            line = line[:30] + f"{float(line[30:38]) + 100:8.3f}" + line[38:]
        lines.append(line)
    before, metadata = module.prepare_intact_pdb("".join(lines) + "END\n")
    assert len(_parse_pdb_text(before.decode())[1]) == 76
    assert b"TER\n" in before
    assert any(row["left"]["residue_number"] == "40" and row["right"]["residue_number"] == "41" for row in metadata["native_breaks"])
