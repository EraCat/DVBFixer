"""Opt-in observed-H identification; no pKa engine or scientific dependencies."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dvbfixer.atom_names import main
from dvbfixer.domain.force_field_naming import (
    ForceFieldTarget,
    NamingProfile,
    ResidueIdentity,
    VariantOverride,
)
from dvbfixer.force_field_naming import NamingConversionRequest, convert_force_field_naming


def _atom(serial, name, residue="HIS", *, chain="H", icode="", altloc="", record="ATOM", element=None):
    element = element or ("H" if name.lstrip("123").startswith("H") else name[0])
    return (f"{record:<6}{serial:5d} {name:>4s}{altloc or ' '}{residue:<4s}{chain}{82:4d}{icode or ' '}"
            f"   {serial:8.3f}{1.:8.3f}{2.:8.3f}  1.00 20.00          {element:>2s}\n")


def _convert(text, *, infer=True, target="amber", overrides=()):
    return convert_force_field_naming(NamingConversionRequest(
        text, ForceFieldTarget(target), NamingProfile.STANDARD, overrides, infer,
    ))


def _names(result):
    return {line[17:21].strip() for line in result.pdb_text.splitlines() if line.startswith(("ATOM", "HETATM"))}


@pytest.mark.parametrize(("residue", "atoms", "expected"), [
    ("HIS", ["ND1", "NE2", "HD1"], "HID"),
    ("HIS", ["ND1", "NE2", "HE2"], "HIE"),
    ("HIS", ["ND1", "NE2", "HD1", "HE2"], "HIP"),
    ("ASP", ["OD1", "OD2", "HD2"], "ASH"),
    ("GLU", ["OE1", "OE2", "HE2"], "GLH"),
    ("LYS", ["NZ", "HZ2", "HZ3"], "LYN"),
    ("LYS", ["NZ", "HZ1", "HZ2", "HZ3"], "LYS"),
    ("CYS", ["SG", "HG"], "CYS"),
    ("CYM", ["SG", "HG"], "CYS"),
    ("HIE", ["ND1", "NE2", "HD1"], "HID"),
    ("HSD", ["ND1", "NE2", "HE2"], "HIE"),
    ("ASPP", ["OD1", "OD2", "HD2"], "ASH"),
])
def test_identifies_name_then_site_hydrogens(residue, atoms, expected):
    text = "".join(_atom(index, name, residue) for index, name in enumerate(atoms, 1))
    result = _convert(text)
    assert _names(result) == {expected}
    assert len(result.pdb_text.splitlines()) == len(text.splitlines())
    assert [line[21:] for line in result.pdb_text.splitlines()] == [line[21:] for line in text.splitlines()]
    assert _convert(result.pdb_text).pdb_text == result.pdb_text


@pytest.mark.parametrize("profile", list(NamingProfile))
@pytest.mark.parametrize("target", list(ForceFieldTarget))
def test_default_does_not_identify_his_even_with_both_ring_hydrogens(profile, target):
    text = "".join(_atom(i, name) for i, name in enumerate(["ND1", "NE2", "HD1", "HE2"], 1))
    result = convert_force_field_naming(NamingConversionRequest(text, target, profile))
    assert _names(result) == {"HIS"}
    assert not result.diagnostics


def test_inferred_variant_is_translated_to_target_and_reported():
    text = "".join(_atom(i, name) for i, name in enumerate(["ND1", "NE2", "HD1"], 1))
    result = _convert(text, target="charmm")
    assert _names(result) == {"HSD"}
    assert any("observed-protonation" in change.rule_ids for change in result.changes)


@pytest.mark.parametrize(("residue", "atoms"), [
    ("HIS", ["ND1", "NE2"]), ("HID", ["ND1", "NE2"]),
    ("HIS", ["ND1", "HD1"]), ("ASH", ["OD1", "OD2", "HB2"]),
    ("GLH", ["OE1", "OE2"]), ("LYS", ["NZ", "HZ1"]),
    ("CYS", ["SG"]), ("CYM", ["SG"]), ("CYX", ["SG", "HG"]),
    ("ASP", ["OD1", "OD2", "HD1", "HD2"]),
])
def test_incomplete_or_ambiguous_site_retains_name_state_and_reports(residue, atoms):
    text = "".join(_atom(index, name, residue) for index, name in enumerate(atoms, 1))
    result = _convert(text)
    assert _names(result) == {residue}
    assert any(d.code == "PROTONATION_UNRESOLVED" for d in result.diagnostics)


def test_explicit_overrides_take_precedence_over_hydrogen_inference():
    text = "".join(_atom(i, name) for i, name in enumerate(["ND1", "NE2", "HD1"], 1))
    result = _convert(text, overrides=(VariantOverride(ResidueIdentity("H", "82"), "HIE"),))
    assert _names(result) == {"HIE"}
    assert not result.diagnostics


def test_conflicting_altlocs_do_not_merge_into_false_hip():
    text = _atom(1, "ND1") + _atom(2, "NE2") + _atom(3, "HD1", altloc="A") + _atom(4, "HE2", altloc="B")
    result = _convert(text)
    assert _names(result) == {"HIS"}
    assert any("Alternate conformers" in d.message for d in result.diagnostics)


def test_chain_case_and_insertion_codes_keep_hydrogens_separate():
    text = ""
    serial = 0
    for chain, icode, hydrogen in [("H", "", "HD1"), ("H", "A", "HE2"), ("h", "", "HE2")]:
        for name in ["ND1", "NE2", hydrogen]:
            serial += 1
            text += _atom(serial, name, chain=chain, icode=icode)
    result = _convert(text)
    names = {(line[21], line[26]): line[17:20].strip() for line in result.pdb_text.splitlines()}
    assert names == {("H", " "): "HID", ("H", "A"): "HIE", ("h", " "): "HIE"}


def test_anisou_ter_headers_and_conect_are_preserved_or_relabelled():
    text = "HEADER original\n" + _atom(1, "ND1") + _atom(1, "ND1", record="ANISOU")
    text += _atom(2, "NE2") + _atom(3, "HD1") + "TER       4      HIS H  82 \nTER\nCONECT    1    3\nEND\n"
    before = text.splitlines(keepends=True)
    after = _convert(text).pdb_text.splitlines(keepends=True)
    assert len(before) == len(after)
    for source, output in zip(before, after):
        assert source[:17] == output[:17]
        assert source[21:] == output[21:]
    assert after[2][17:20] == "HID"
    assert after[5][17:20] == "HID"


def test_cli_opt_in_dry_run_records_flag_and_preserves_input(tmp_path: Path):
    source = tmp_path / "input.pdb"
    output = tmp_path / "output.pdb"
    report = tmp_path / "report.json"
    text = "".join(_atom(i, name) for i, name in enumerate(["ND1", "NE2", "HD1"], 1))
    source.write_text(text)
    main([str(source), "-o", str(output), "--target-ff", "amber", "--infer-protonation", "--dry-run", "--report-json", str(report)])
    payload = json.loads(report.read_text())
    assert payload["request"]["inferProtonation"] is True
    assert payload["result"]["changes"][0]["targetResidueName"] == "HID"
    assert not output.exists()
    assert source.read_text() == text


def test_legacy_rename_remains_canonicalization_only(tmp_path: Path):
    from dvbfixer.rename import canonicalize_pdb

    source = tmp_path / "input.pdb"
    output = tmp_path / "canonical.pdb"
    source.write_text(_atom(1, "ND1", "HID") + _atom(2, "NE2", "HID") + _atom(3, "HD1", "HID"))
    canonicalize_pdb(source, output)
    assert {line[17:20] for line in output.read_text().splitlines()} == {"HIS"}


def test_named_heavy_mercury_is_not_a_cysteine_hydrogen():
    text = _atom(1, "SG", "CYM") + _atom(2, "HG", "CYM", element="HG")
    result = _convert(text)
    assert _names(result) == {"CYM"}
    assert any(d.code == "PROTONATION_UNRESOLVED" for d in result.diagnostics)


def test_digit_prefix_and_deuterium_site_aliases_are_recognized_without_editing_them():
    text = _atom(1, "ND1") + _atom(2, "NE2") + _atom(3, "DD1", element="D")
    result = _convert(text)
    assert _names(result) == {"HID"}
    assert "DD1" in result.pdb_text
    lys = _atom(1, "NZ", "LYS") + _atom(2, "2HZ", "LYS") + _atom(3, "3HZ", "LYS")
    assert _names(_convert(lys)) == {"LYN"}


def test_shared_and_altloc_lys_hydrogens_use_one_conformer_for_atom_naming():
    text = _atom(1, "NZ", "LYS") + _atom(2, "HZ1", "LYS") + _atom(3, "HZ2", "LYS", altloc="A")
    result = _convert(text, target="charmm")
    assert _names(result) == {"LSN"}
    assert [line[12:16].strip() for line in result.pdb_text.splitlines()] == ["NZ", "HZ1", "HZ2"]
