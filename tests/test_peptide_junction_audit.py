"""Independent junction measurement preserves exact PDB residue identities."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from dvbfixer.model.diffusion.contract import ResidueIdentity
from dvbfixer.model.diffusion.validate import _cn_distance, _parse_pdb_text

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/audit_peptide_junctions.py"
SPEC = importlib.util.spec_from_file_location("junction_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def atom(serial, name, chain, number, insertion, x):
    return f"ATOM  {serial:5d} {name:^4s} ALA {chain}{number:4d}{insertion:1s}   {x:8.3f}{0:8.3f}{0:8.3f}  1.00 20.00           {name:>2s}\n"


def test_independent_and_production_measurement_use_direction_case_and_insertion_code():
    # File order and numeric adjacency cannot choose the bond: 82->82A is
    # valid, and the lowercase chain contains a deliberately distant decoy.
    text = (atom(1, "N", "H", 82, "A", 1.33) + atom(2, "C", "h", 82, "", 20)
            + atom(3, "C", "H", 82, "", 0) + atom(4, "N", "H", 82, "", -5)
            + atom(5, "C", "H", 82, "A", 5))
    coordinates, _ = audit.read_coordinates(text)
    left, right = ("H", "82", ""), ("H", "82", "A")
    assert audit.cn_distance(coordinates, left, right) == pytest.approx(1.33)
    structure = SimpleNamespace(atoms=_parse_pdb_text(text)[0])
    assert _cn_distance(structure, ResidueIdentity(*left), ResidueIdentity(*right)) == pytest.approx(1.33)
    assert _cn_distance(structure, ResidueIdentity(*right), ResidueIdentity(*left)) == pytest.approx(10)
    assert _cn_distance(structure, ResidueIdentity("H", "81"), ResidueIdentity(*right)) is None


def test_independent_parser_rejects_ambiguous_duplicate_coordinates():
    text = atom(1, "C", "A", 1, "", 0) + atom(2, "C", "A", 1, "", 1)
    with pytest.raises(ValueError, match="ambiguous"):
        audit.read_coordinates(text)
