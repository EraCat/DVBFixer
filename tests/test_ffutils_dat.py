"""Unit tests for the shared ``.dat`` schema in ``dvbfixer.ffutils.dat``."""

from __future__ import annotations

import json
from pathlib import Path

from dvbfixer.ffutils.dat import DatRecord, load, load_added_keys


def _make_atom(chain: str = "A", resid: str = "10", atom: str = "HA", *, element: str = "H") -> dict:
    return {
        "chain": chain,
        "resid": resid,
        "icode": "",
        "resname": "ALA",
        "atom": atom,
        "element": element,
    }


def test_blank_insertion_codes_merge_without_collapsing_real_codes() -> None:
    blank = _make_atom(atom="CA", element="C")
    spaced = {**blank, "icode": " "}
    upper = {**blank, "icode": "A"}
    lower = {**blank, "icode": "a"}
    record = DatRecord(added_atoms=[spaced, upper])
    assert record.merge(DatRecord(added_atoms=[blank, lower])) == 1
    assert record.added_keys() == {("A", "10", "", "CA"), ("A", "10", "A", "CA"), ("A", "10", "a", "CA")}


def test_roundtrip(tmp_workdir: Path) -> None:
    rec = DatRecord(
        description="test",
        added_atoms=[_make_atom(atom="HA"), _make_atom(atom="HB1")],
        residue_summary={"A/ALA10": {"heavy": 0, "hydrogen": 2}},
    )
    out = tmp_workdir / "test.dat"
    rec.save(out, verbose=False)
    loaded = DatRecord.load(out)
    assert loaded.description == "test"
    assert len(loaded.added_atoms) == 2
    assert loaded.residue_summary == {"A/ALA10": {"heavy": 0, "hydrogen": 2}}


def test_total_added_is_derived(tmp_workdir: Path) -> None:
    """total_added is auto-populated on save — writers can't drift."""
    rec = DatRecord(added_atoms=[_make_atom(), _make_atom(atom="HB1"), _make_atom(atom="HB2")])
    out = tmp_workdir / "test.dat"
    rec.save(out, verbose=False)
    raw = json.loads(out.read_text())
    assert raw["total_added"] == 3


def test_optional_fields_omitted_when_unset(tmp_workdir: Path) -> None:
    rec = DatRecord(added_atoms=[_make_atom()])
    out = tmp_workdir / "test.dat"
    rec.save(out, verbose=False)
    raw = json.loads(out.read_text())
    assert "variant_overrides" not in raw
    assert "removed_residues" not in raw
    assert "templates" not in raw


def test_optional_fields_preserved(tmp_workdir: Path) -> None:
    rec = DatRecord(
        added_atoms=[_make_atom()],
        variant_overrides={"A:39": "CYX"},
        removed_residues=[{"chain": "A", "resid": 100, "resname": "GLY"}],
        templates=["template1.pdb", "template2.pdb"],
        target_chains={"H": 220, "L": 214},
    )
    out = tmp_workdir / "test.dat"
    rec.save(out, verbose=False)
    loaded = DatRecord.load(out)
    assert loaded.variant_overrides == {"A:39": "CYX"}
    assert loaded.removed_residues == [{"chain": "A", "resid": 100, "resname": "GLY"}]
    assert loaded.templates == ["template1.pdb", "template2.pdb"]
    assert loaded.target_chains == {"H": 220, "L": 214}


def test_merge_adds_missing_atoms() -> None:
    downstream = DatRecord(added_atoms=[_make_atom(atom="HA")])
    upstream = DatRecord(
        added_atoms=[_make_atom(atom="HB1"), _make_atom(atom="HB2")],
    )
    carried = downstream.merge(upstream)
    assert carried == 2
    assert len(downstream.added_atoms) == 3
    atoms = {a["atom"] for a in downstream.added_atoms}
    assert atoms == {"HA", "HB1", "HB2"}


def test_merge_skips_duplicates() -> None:
    downstream = DatRecord(added_atoms=[_make_atom(atom="HA")])
    upstream = DatRecord(added_atoms=[_make_atom(atom="HA")])
    carried = downstream.merge(upstream)
    assert carried == 0
    assert len(downstream.added_atoms) == 1


def test_merge_updates_residue_summary() -> None:
    downstream = DatRecord()
    upstream = DatRecord(
        added_atoms=[_make_atom(atom="HA", element="H"), _make_atom(atom="OXT", element="O")],
    )
    downstream.merge(upstream)
    assert downstream.residue_summary["A/ALA10"] == {"heavy": 1, "hydrogen": 1}


def test_merge_downstream_variant_overrides_win() -> None:
    """Merged variant_overrides prefer downstream on collision — downstream
    was written by a later stage so its opinion is more current.
    """
    downstream = DatRecord(variant_overrides={"A:39": "CYX"})
    upstream = DatRecord(variant_overrides={"A:39": "CYS", "B:20": "HIE"})
    downstream.merge(upstream)
    assert downstream.variant_overrides == {"A:39": "CYX", "B:20": "HIE"}


def test_added_keys_shape() -> None:
    rec = DatRecord(added_atoms=[_make_atom(atom="HA"), _make_atom(atom="HB1", resid="11")])
    assert rec.added_keys() == {
        ("A", "10", "", "HA"),
        ("A", "11", "", "HB1"),
    }


def test_module_level_load(tmp_workdir: Path) -> None:
    rec = DatRecord(added_atoms=[_make_atom()])
    out = tmp_workdir / "m.dat"
    rec.save(out, verbose=False)
    loaded = load(out)
    assert isinstance(loaded, DatRecord)
    assert len(loaded.added_atoms) == 1


def test_load_added_keys_prints_summary(tmp_workdir: Path, capsys) -> None:
    rec = DatRecord(added_atoms=[_make_atom(), _make_atom(atom="HB1")])
    out = tmp_workdir / "m.dat"
    rec.save(out, verbose=False)
    keys = load_added_keys(out)
    assert len(keys) == 2
    captured = capsys.readouterr()
    assert "Loaded restraint data" in captured.out
