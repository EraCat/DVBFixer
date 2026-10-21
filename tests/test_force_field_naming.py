from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from dvbfixer.domain.force_field_naming import (
    ForceFieldTarget,
    NamingConversionError,
    NamingErrorCode,
    NamingProfile,
    NamingRuleId,
    ResidueIdentity,
    VariantOverride,
)
from dvbfixer.force_field_naming import (
    NamingConversionRequest,
    convert_force_field_naming,
)


def _atom(
    serial: int,
    atom: str,
    residue: str,
    chain: str = "A",
    number: int = 1,
    *,
    icode: str = "",
    altloc: str = "",
    record: str = "ATOM",
    suffix: str = "      10.123  11.234  12.345  0.75 19.25           C  ",
) -> str:
    atom_field = atom[:4] if len(atom) == 4 else f" {atom:<3}"
    residue_field = residue if len(residue) == 4 else f"{residue:<3} "
    return (
        f"{record:<6}{serial:5d} {atom_field}{altloc or ' '}{residue_field}"
        f"{chain}{number:4d}{icode or ' '}{suffix}\n"
    )


def _convert(
    text: str,
    *,
    target: ForceFieldTarget = ForceFieldTarget.CHARMM,
    profile: NamingProfile = NamingProfile.STANDARD,
    overrides: dict[ResidueIdentity, str] | None = None,
):
    return convert_force_field_naming(
        NamingConversionRequest(
            pdb_text=text,
            target=target,
            profile=profile,
            variant_overrides=tuple(
                VariantOverride(identity, variant)
                for identity, variant in (overrides or {}).items()
            ),
        )
    )


def test_noop_has_empty_structured_report_and_model_one() -> None:
    text = "HEADER unchanged\n" + _atom(1, "CA", "HIS") + "END\n"
    result = _convert(text)
    assert result.pdb_text == text
    assert result.model == 1
    assert result.changes == ()
    assert result.diagnostics == ()
    assert result.summary.changed_atoms == 0
    assert result.summary.changed_residues == 0
    assert result.summary.variant_changes == 0
    assert result.summary.atom_name_changes == 0


def test_structured_result_is_json_serializable_for_future_adapters() -> None:
    result = _convert(
        _atom(1, "N", "HIS"),
        overrides={ResidueIdentity("A", "1", ""): "HIE"},
    )
    payload = json.loads(json.dumps(asdict(result)))
    assert payload["changes"][0]["rule_ids"] == ["explicit-variant"]
    assert payload["summary"]["variant_changes"] == 1


def test_explicit_variant_precedes_source_and_his_is_not_inferred() -> None:
    text = _atom(1, "N", "HIE", number=1) + _atom(2, "N", "HIS", number=2)
    result = _convert(
        text,
        overrides={ResidueIdentity("A", "1", ""): "HID"},
    )
    assert " HSD A   1" in result.pdb_text
    assert " HIS A   2" in result.pdb_text
    assert result.changes[0].rule_ids == (NamingRuleId.EXPLICIT_VARIANT,)


def test_insertion_code_siblings_and_chain_case_are_isolated() -> None:
    text = (
        _atom(1, "N", "HIS", "A", 7)
        + _atom(2, "N", "HIS", "A", 7, icode="B")
        + _atom(3, "N", "HIS", "a", 7)
    )
    result = _convert(
        text,
        overrides={ResidueIdentity("A", "7", ""): "HIE"},
    )
    lines = result.pdb_text.splitlines()
    assert _resname(lines[0]) == "HSE"
    assert _resname(lines[1]) == "HIS"
    assert _resname(lines[2]) == "HIS"


def _resname(line: str) -> str:
    return line[17:21].strip() if line[20:21].strip() else line[17:20].strip()


def test_preflight_rejects_target_atom_collision() -> None:
    text = _atom(1, "HB1", "LYS") + _atom(2, "HB3", "LYS")
    with pytest.raises(NamingConversionError) as caught:
        _convert(text, target=ForceFieldTarget.AMBER, profile=NamingProfile.GROMACS)
    assert caught.value.code is NamingErrorCode.NAMING_COLLISION
    assert caught.value.details["source_atom_names"] == ["HB1", "HB3"]


def test_preflight_rejects_duplicate_source_atom_identity() -> None:
    text = _atom(1, "HB3", "SER") + _atom(2, "HB3", "SER")
    with pytest.raises(NamingConversionError) as caught:
        _convert(text, target=ForceFieldTarget.AMBER, profile=NamingProfile.GROMACS)
    assert caught.value.code is NamingErrorCode.NAMING_COLLISION
    assert caught.value.details["atom_name"] == "HB3"


def test_duplicate_coordinate_serial_is_malformed() -> None:
    text = _atom(1, "N", "ALA") + _atom(1, "CA", "ALA")
    with pytest.raises(NamingConversionError) as caught:
        _convert(text)
    assert caught.value.code is NamingErrorCode.MALFORMED_PDB


def test_multiple_models_are_rejected_before_conversion() -> None:
    text = "MODEL        1\nENDMDL\nMODEL        2\nENDMDL\n"
    with pytest.raises(NamingConversionError) as caught:
        _convert(text)
    assert caught.value.code is NamingErrorCode.MULTI_MODEL_UNSUPPORTED


def test_single_model_number_is_reported() -> None:
    result = _convert("MODEL        7\n" + _atom(1, "N", "ALA") + "ENDMDL\n")
    assert result.model == 7


@pytest.mark.parametrize(("source", "target"), [("ASH", "ASPP"), ("GLH", "GLUP")])
def test_four_character_charmm_names_parse_and_render_idempotently(
    source: str, target: str
) -> None:
    overrides = {ResidueIdentity("A", "1", ""): source}
    first = _convert(_atom(1, "N", source), overrides=overrides)
    assert _resname(first.pdb_text) == target
    second = _convert(first.pdb_text, overrides=overrides)
    assert second.pdb_text == first.pdb_text
    assert second.changes == ()


def test_lyn_to_lsn_pair_is_unique_and_repeated_conversion_is_noop() -> None:
    text = _atom(1, "HZ2", "LYN") + _atom(2, "HZ3", "LYN")
    overrides = {ResidueIdentity("A", "1", ""): "LYN"}
    first = _convert(text, overrides=overrides)
    names = [line[12:16].strip() for line in first.pdb_text.splitlines()]
    assert names == ["HZ1", "HZ2"]
    second = _convert(first.pdb_text, overrides=overrides)
    assert second.pdb_text == first.pdb_text
    assert second.changes == ()


def test_already_target_lyn_pair_is_not_shifted_again() -> None:
    text = _atom(1, "HZ1", "LYN") + _atom(2, "HZ2", "LYN")
    result = _convert(text)
    assert [line[12:16].strip() for line in result.pdb_text.splitlines()] == ["HZ1", "HZ2"]


@pytest.mark.parametrize("middle", ["", "HZ2"])
def test_mixed_lyn_pair_fails_instead_of_duplicating_names(middle: str) -> None:
    text = _atom(1, "HZ1", "LYN")
    if middle:
        text += _atom(2, middle, "LYN")
    text += _atom(3, "HZ3", "LYN")
    with pytest.raises(NamingConversionError) as caught:
        _convert(text)
    assert caught.value.code is NamingErrorCode.NAMING_COLLISION


def test_anisou_and_full_ter_follow_residue_and_bare_ter_is_preserved() -> None:
    atom = _atom(9, "HZ2", "LYN")
    anisou = _atom(
        9,
        "HZ2",
        "LYN",
        record="ANISOU",
        suffix="    1000   1000   1000      0      0      0       H  ",
    )
    full_ter = f"TER   {10:5d}      {'LYN':<3} A{1:4d} \n"
    text = atom + anisou + full_ter + "TER\n"
    result = _convert(text, overrides={ResidueIdentity("A", "1", ""): "LYN"})
    lines = result.pdb_text.splitlines(keepends=True)
    assert lines[0][12:16].strip() == "HZ1"
    assert lines[1][12:16].strip() == "HZ1"
    assert _resname(lines[1]) == "LSN"
    assert _resname(lines[2]) == "LSN"
    assert lines[3] == "TER\n"
    assert result.summary.changed_atoms == 1


def test_anisou_labels_must_match_coordinate_record() -> None:
    text = _atom(9, "HZ2", "LYN") + _atom(
        9,
        "HZ3",
        "LYN",
        record="ANISOU",
        suffix="    1000   1000   1000      0      0      0       H  ",
    )
    with pytest.raises(NamingConversionError) as caught:
        _convert(text)
    assert caught.value.code is NamingErrorCode.MALFORMED_PDB


def test_bytes_outside_supported_name_fields_are_preserved() -> None:
    source = _atom(123, "HB3", "SER", "z", 42, icode="Q", altloc="B")
    result = _convert(
        source,
        target=ForceFieldTarget.AMBER,
        profile=NamingProfile.GROMACS,
    )
    changed = result.pdb_text
    assert changed[:12] == source[:12]
    assert changed[16:17] == source[16:17]
    assert changed[17:] == source[17:]


@pytest.mark.parametrize(
    ("residue", "source_names", "target_names"),
    [
        ("DA", ("H2'", "H2''", "H5'", "H5''"), ("H2'1", "H2'2", "H5'1", "H5'2")),
        ("A", ("H2'", "H2''", "H5'", "H5''", "HO'2"), ("H2'1", "H2'2", "H5'1", "H5'2", "HO2'")),
    ],
)
def test_end_to_end_dna_and_rna_atom_naming(
    residue: str, source_names: tuple[str, ...], target_names: tuple[str, ...]
) -> None:
    text = "".join(_atom(serial, name, residue) for serial, name in enumerate(source_names, 1))

    result = _convert(text, target=ForceFieldTarget.AMBER, profile=NamingProfile.GROMACS)

    assert tuple(line[12:16].strip() for line in result.pdb_text.splitlines()) == target_names
    assert result.summary.changed_atoms == len(source_names)
    assert result.summary.changed_residues == 1
    assert all(change.rule_ids == (NamingRuleId.NUCLEIC_ACID_ATOM_NAME,) for change in result.changes)


@pytest.mark.parametrize("record", ["ATOM", "HETATM", "ANISOU"])
def test_malformed_supported_records_fail_with_stable_code(record: str) -> None:
    with pytest.raises(NamingConversionError) as caught:
        _convert(f"{record}\n")
    assert caught.value.code is NamingErrorCode.MALFORMED_PDB


def test_pure_api_rejects_ambiguous_tuple_identity() -> None:
    with pytest.raises(TypeError, match="VariantOverride"):
        NamingConversionRequest(
            pdb_text="END\n",
            target=ForceFieldTarget.AMBER,
            variant_overrides=(("A", "1"),),  # type: ignore[arg-type]
        )


def test_invalid_variant_has_stable_error_code() -> None:
    with pytest.raises(NamingConversionError) as caught:
        VariantOverride(ResidueIdentity("A", "1"), "HIS")
    assert caught.value.code is NamingErrorCode.INVALID_VARIANT


def test_duplicate_override_has_stable_error_code() -> None:
    override = VariantOverride(ResidueIdentity("A", "1"), "HIE")
    with pytest.raises(NamingConversionError) as caught:
        NamingConversionRequest(
            pdb_text="END\n",
            target=ForceFieldTarget.AMBER,
            variant_overrides=(override, override),
        )
    assert caught.value.code is NamingErrorCode.AMBIGUOUS_VARIANT


def test_unsupported_target_has_stable_error_code() -> None:
    with pytest.raises(NamingConversionError) as caught:
        NamingConversionRequest(pdb_text="END\n", target="opls")  # type: ignore[arg-type]
    assert caught.value.code is NamingErrorCode.UNSUPPORTED_NAMING_DIRECTION


# Independent expected spellings: changing a production table must not silently
# change the expected output of these application-boundary tests.
_AMBER_CASES = [
    (residue, source.split(), destination.split())
    for residues, source, destination in [
        ("ALA VAL THR", "CA", "CA"),
        ("SER CYS CYX CYM ASN ASP ASH PHE TYR TRP HIS HID HIE HIP LEU", "HB2 HB3", "HB2 HB1"),
        ("GLU GLH GLN MET", "HB2 HB3 HG2 HG3", "HB2 HB1 HG2 HG1"),
        ("PRO ARG", "HB2 HB3 HG2 HG3 HD2 HD3", "HB2 HB1 HG2 HG1 HD2 HD1"),
        ("HYP", "CD HB2 HB3 HG HD1 HD2 HD3", "CD2 HB2 HB1 HG HD1 HD21 HD22"),
        ("LYS", "HB2 HB3 HG2 HG3 HD2 HD3 HE2 HE3", "HB2 HB1 HG2 HG1 HD2 HD1 HE2 HE1"),
        ("LYN", "HB2 HB3 HG2 HG3 HD2 HD3 HE2 HE3 HZ2 HZ3", "HB2 HB1 HG2 HG1 HD2 HD1 HE2 HE1 HZ2 HZ1"),
        ("GLY", "HA2 HA3", "HA2 HA1"),
        ("ILE", "HG12 HG13", "HG12 HG11"),
        ("ACE", "C CH3 H1 H2 H3", "C CH3 HH31 HH32 HH33"),
        ("NME", "N H C H1 H2 H3", "N H CH3 HH31 HH32 HH33"),
    ]
    for residue in residues.split()
]


@pytest.mark.parametrize(("residue", "source_names", "expected_names"), _AMBER_CASES)
@pytest.mark.parametrize("record", ["ATOM", "HETATM"])
def test_all_amber_mappings_and_repeat_conversion(
    residue: str, source_names: list[str], expected_names: list[str], record: str,
) -> None:
    text = "".join(
        _atom(serial, name, residue, record=record)
        for serial, name in enumerate(source_names, 1)
    )
    first = _convert(text, target=ForceFieldTarget.AMBER, profile=NamingProfile.GROMACS)
    assert [line[12:16].strip() for line in first.pdb_text.splitlines()] == expected_names
    changed = sum(source != target for source, target in zip(source_names, expected_names))
    assert asdict(first.summary) == {
        "changed_atoms": changed, "changed_residues": int(changed > 0),
        "variant_changes": 0, "atom_name_changes": changed,
    }
    second = _convert(first.pdb_text, target=ForceFieldTarget.AMBER, profile=NamingProfile.GROMACS)
    assert second.pdb_text.encode() == first.pdb_text.encode()
    assert second.changes == ()
    assert not any(asdict(second.summary).values())


def test_amber_matrix_covers_every_declared_mapping() -> None:
    from dvbfixer.domain.force_field_naming import GROMACS_AMBER_ATOM_RENAMES

    expected = {
        residue: {source: target for source, target in zip(sources, targets) if source != target}
        for residue, sources, targets in _AMBER_CASES
    }
    assert expected == GROMACS_AMBER_ATOM_RENAMES


def _rtp_atom_names(bundle: str, residue: str) -> set[str]:
    path = Path(__file__).parents[1] / "FF" / bundle / "aminoacids.rtp"
    in_residue = False
    in_atoms = False
    result: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split(";", 1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            if not raw_line.startswith((" ", "\t")):
                if in_residue:
                    break
                in_residue = section == residue
                in_atoms = False
            elif in_residue:
                in_atoms = section == "atoms"
            continue
        if in_residue and in_atoms and line:
            result.add(line.split()[0])
    assert result, f"missing RTP atom set for {bundle}/{residue}"
    return result


@pytest.mark.parametrize(
    ("target", "bundle", "source_residue", "rtp_residue", "source_names"),
    [
        (
            ForceFieldTarget.AMBER,
            "amber99sb-ildn-lipid21.ff",
            "HYP",
            "HYP",
            "N CD HD2 HD3 CG HG OD1 HD1 CB HB2 HB3 CA HA C O",
        ),
        (
            ForceFieldTarget.AMBER19SB,
            "amber19sb.ff",
            "HYP",
            "HYP",
            "N CD HD2 HD3 CG HG OD1 HD1 CB HB2 HB3 CA HA C O",
        ),
        (
            ForceFieldTarget.AMBER19SB,
            "amber19sb.ff",
            "ACE",
            "ACE",
            "H1 CH3 H2 H3 C O",
        ),
        (
            ForceFieldTarget.AMBER19SB,
            "amber19sb.ff",
            "NME",
            "NME",
            "N H C H1 H2 H3",
        ),
    ],
)
def test_amber_dialect_output_matches_bundled_rtp(
    target: ForceFieldTarget,
    bundle: str,
    source_residue: str,
    rtp_residue: str,
    source_names: str,
) -> None:
    text = "".join(
        _atom(serial, name, source_residue)
        for serial, name in enumerate(source_names.split(), 1)
    )
    result = _convert(text, target=target, profile=NamingProfile.GROMACS)
    actual = {line[12:16].strip() for line in result.pdb_text.splitlines()}
    assert actual == _rtp_atom_names(bundle, rtp_residue)


@pytest.mark.parametrize("target", list(ForceFieldTarget))
@pytest.mark.parametrize("residue", ["ALA", "PRO", "HYP"])
def test_termini_are_chain_local_and_idempotent(target: ForceFieldTarget, residue: str) -> None:
    names = ["H2", "H3", "O", "OXT"] if residue in {"PRO", "HYP"} else ["H", "H2", "H3", "O", "OXT"]
    expected = (
        ["H2", "H1", "OC2", "OC1"] if residue in {"PRO", "HYP"}
        else ["H1", "H2", "H3", "OC2", "OC1"]
    ) if target is ForceFieldTarget.AMBER else (
        ["H2", "H1", "O", "OXT"] if residue in {"PRO", "HYP"}
        else ["H1", "H2", "H3", "O", "OXT"]
    ) if target is ForceFieldTarget.AMBER19SB else ["HN" if name == "H" else name for name in names]
    # Both case-distinct chains have a single residue, so each is both termini.
    text = "".join(
        _atom(chain_index * len(names) + index, name, residue, chain, 82, icode="A")
        for chain_index, chain in enumerate(("H", "h"))
        for index, name in enumerate(names, 1)
    )
    first = _convert(text, target=target, profile=NamingProfile.GROMACS)
    assert [line[12:16].strip() for line in first.pdb_text.splitlines()] == expected * 2
    assert _convert(first.pdb_text, target=target, profile=NamingProfile.GROMACS).pdb_text == first.pdb_text


@pytest.mark.parametrize("target", list(ForceFieldTarget))
def test_caps_do_not_make_the_internal_protein_residue_terminal(target: ForceFieldTarget) -> None:
    residues = [("ACE", ["C", "H1", "H2", "H3"]), ("ALA", ["H", "O"]), ("NME", ["N", "H", "C", "H1", "H2", "H3"])]
    text = ""
    serial = 0
    for number, (residue, names) in enumerate(residues, 1):
        for name in names:
            serial += 1
            text += _atom(serial, name, residue, number=number)
    first = _convert(text, target=target, profile=NamingProfile.GROMACS)
    hydrogen = "HN" if target is ForceFieldTarget.CHARMM else "H"
    cap_names = (
        ["C", "H1", "H2", "H3", hydrogen, "O", "N", hydrogen, "C", "H1", "H2", "H3"]
        if target is ForceFieldTarget.AMBER19SB
        else ["C", "HH31", "HH32", "HH33", hydrogen, "O", "N", hydrogen, "CH3", "HH31", "HH32", "HH33"]
    )
    assert [line[12:16].strip() for line in first.pdb_text.splitlines()] == cap_names
    assert _convert(first.pdb_text, target=target, profile=NamingProfile.GROMACS).pdb_text == first.pdb_text


@pytest.mark.parametrize("residue", ["DA", "DC", "DG", "DT", "A", "C", "G", "U"])
def test_all_nucleic_acid_mappings_repeat_without_changes(residue: str) -> None:
    names = ["H2'", "H2''", "H5'", "H5''"]
    expected = ["H2'1", "H2'2", "H5'1", "H5'2"]
    if not residue.startswith("D"):
        names.append("HO'2")
        expected.append("HO2'")
    text = "".join(_atom(index, name, residue) for index, name in enumerate(names, 1))
    first = _convert(text, target=ForceFieldTarget.AMBER, profile=NamingProfile.GROMACS)
    assert [line[12:16].strip() for line in first.pdb_text.splitlines()] == expected
    second = _convert(first.pdb_text, target=ForceFieldTarget.AMBER, profile=NamingProfile.GROMACS)
    assert second.pdb_text == first.pdb_text
    assert second.changes == ()


@pytest.mark.parametrize("text", ["", "END\n", "HEADER no coordinates\r\nREMARK unchanged"])
@pytest.mark.parametrize("target", list(ForceFieldTarget))
def test_empty_coordinate_input_is_a_byte_preserving_noop(text: str, target: ForceFieldTarget) -> None:
    result = _convert(text, target=target, profile=NamingProfile.GROMACS)
    assert result.pdb_text == text
    assert result.changes == result.diagnostics == ()
    assert not any(asdict(result.summary).values())


@pytest.mark.parametrize("record", ["ATOM", "HETATM", "ANISOU"])
@pytest.mark.parametrize(("start", "end", "replacement"), [
    (6, 11, "abcde"), (22, 26, "oops"), (12, 16, "    "), (17, 21, "    "),
])
def test_malformed_identity_fields_report_the_line(
    record: str, start: int, end: int, replacement: str,
) -> None:
    line = _atom(1, "N", "ALA", record=record)
    text = "HEADER preserved\n" + line[:start] + replacement + line[end:]
    with pytest.raises(NamingConversionError) as caught:
        _convert(text)
    assert caught.value.code is NamingErrorCode.MALFORMED_PDB
    assert caught.value.details["line"] == 2
    assert caught.value.details["record"] == record


@pytest.mark.parametrize("model", ["MODEL\n", "MODEL     nope\n"])
def test_malformed_model_number_is_rejected(model: str) -> None:
    with pytest.raises(NamingConversionError) as caught:
        _convert(model + _atom(1, "CA", "ALA") + "ENDMDL\n")
    assert caught.value.code is NamingErrorCode.MALFORMED_PDB


def test_duplicate_anisou_serial_is_rejected() -> None:
    anisou = _atom(1, "CA", "ALA", record="ANISOU")
    with pytest.raises(NamingConversionError) as caught:
        _convert(_atom(1, "CA", "ALA") + anisou + anisou)
    assert caught.value.code is NamingErrorCode.MALFORMED_PDB


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_record_matrix_preserves_non_name_bytes_and_counts_coordinate_changes(newline: str) -> None:
    lines = [
        "HEADER untouched\n", "SEQRES   1 H    1  LYN\n", "MODEL        3\n",
        _atom(1, "HZ2", "LYN", "H", 82, icode="A"),
        _atom(1, "HZ2", "LYN", "H", 82, icode="A", record="ANISOU"),
        _atom(2, "HZ3", "LYN", "H", 82, icode="A", record="HETATM"),
        f"TER   {3:5d}      {'LYN':<3} H{82:4d}A\n",
        "TER\n", "CONECT    1    2\n", "ENDMDL\n", "END",
    ]
    text = "".join(lines).replace("\n", newline)
    result = _convert(text)
    before = text.splitlines(keepends=True)
    after = result.pdb_text.splitlines(keepends=True)
    assert len(before) == len(after)
    for index, (source, destination) in enumerate(zip(before, after)):
        if index in {3, 4, 5, 6}:
            assert destination[:12] == source[:12]
            assert destination[16:17] == source[16:17]
            assert destination[21:] == source[21:]
            assert _resname(destination) == "LSN"
        else:
            assert destination == source
    assert [after[index][12:16].strip() for index in (3, 4, 5)] == ["HZ1", "HZ1", "HZ2"]
    assert asdict(result.summary) == {
        "changed_atoms": 2, "changed_residues": 1, "variant_changes": 1, "atom_name_changes": 2,
    }
    assert _convert(result.pdb_text).pdb_text == result.pdb_text


@pytest.mark.parametrize(("amber", "charmm"), [
    ("HID", "HSD"), ("HIE", "HSE"), ("HIP", "HSP"), ("ASH", "ASPP"),
    ("GLH", "GLUP"), ("LYN", "LSN"), ("CYM", "CYM"),
])
@pytest.mark.parametrize("target", list(ForceFieldTarget))
@pytest.mark.parametrize("profile", list(NamingProfile))
def test_variant_mappings_repeat_without_changes(
    amber: str, charmm: str, target: ForceFieldTarget, profile: NamingProfile,
) -> None:
    source, expected = (amber, charmm) if target is ForceFieldTarget.CHARMM else (charmm, amber)
    names = ["N", "CA", "H"]
    if amber == "LYN":
        names += ["HZ2", "HZ3"] if source == "LYN" else ["HZ1", "HZ2"]
    text = "".join(_atom(index, name, source) for index, name in enumerate(names, 1))
    first = _convert(text, target=target, profile=profile)
    assert {_resname(line) for line in first.pdb_text.splitlines()} == {expected}
    if amber == "LYN":
        expected_pair = ["HZ2", "HZ3"] if target is not ForceFieldTarget.CHARMM and profile is NamingProfile.STANDARD else ["HZ1", "HZ2"]
        assert [line[12:16].strip() for line in first.pdb_text.splitlines()][-2:] == expected_pair
    second = _convert(first.pdb_text, target=target, profile=profile)
    assert second.pdb_text == first.pdb_text
    assert not any(asdict(second.summary).values())


@pytest.fixture(scope="module")
def native_templates():
    app = pytest.importorskip("openmm.app")
    return (
        app.ForceField("amber14/protein.ff14SB.xml")._templates,
        app.ForceField("charmm36.xml")._templates,
    )


@pytest.mark.parametrize("residue", [
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HYP", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
])
@pytest.mark.parametrize("target", list(ForceFieldTarget))
def test_standard_protein_names_match_independent_native_templates(native_templates, residue, target):
    amber, charmm = native_templates
    source, expected = (amber, charmm) if target is ForceFieldTarget.CHARMM else (charmm, amber)
    text = "".join(_atom(index, atom.name, residue) for index, atom in enumerate(source[residue].atoms, 1))
    result = _convert(text, target=target)
    lines = result.pdb_text.splitlines()
    assert {line[12:16].strip() for line in lines} == set(expected[residue].atomIndices)
    assert [line[21:] for line in lines] == [line[21:] for line in text.splitlines()]
    assert _convert(result.pdb_text, target=target).pdb_text == result.pdb_text

    # Consumer-specific output must also be usable as a native conversion input.
    # Surround the internal template with anchors: a lone residue would be
    # classified as N-terminal by the existing GROMACS profile (H -> H1).
    amber_text = _atom(100, "N", "ALA", number=0)
    amber_text += "".join(_atom(index, atom.name, residue) for index, atom in enumerate(amber[residue].atoms, 1))
    amber_text += _atom(101, "N", "ALA", number=2)
    consumer = _convert(amber_text, target=target, profile=NamingProfile.GROMACS)
    restored = _convert(consumer.pdb_text, target=target)
    assert {line[12:16].strip() for line in restored.pdb_text.splitlines() if line[22:26].strip() == "1"} == set(expected[residue].atomIndices)


@pytest.mark.parametrize("target", [ForceFieldTarget.AMBER, ForceFieldTarget.AMBER19SB])
@pytest.mark.parametrize(("residue", "names", "expected"), [
    ("SER", ["HB1", "HB2"], ["HB3", "HB2"]),
    ("ACE", ["HH31", "HH32", "HH33"], ["H1", "H2", "H3"]),
    ("NME", ["CH3", "HH31", "HH32", "HH33"], ["C", "H1", "H2", "H3"]),
    ("ALA", ["OC2", "OC1"], ["O", "OXT"]),
    ("ALA", ["HT1", "HT2", "HT3", "OT1", "OT2"], ["H1", "H2", "H3", "O", "OXT"]),
    ("DA", ["H2'1", "H2'2", "H5'1", "H5'2"], ["H2'", "H2''", "H5'", "H5''"]),
])
def test_standard_amber_restores_recognized_consumer_aliases(target, residue, names, expected):
    text = "".join(_atom(index, name, residue) for index, name in enumerate(names, 1))
    first = _convert(text, target=target)
    assert [line[12:16].strip() for line in first.pdb_text.splitlines()] == expected
    assert _convert(first.pdb_text, target=target).pdb_text == first.pdb_text


def test_standard_charmm_uses_native_terminal_names():
    names = ["H1", "H2", "H3", "O", "OXT"]
    text = "".join(_atom(index, name, "ALA") for index, name in enumerate(names, 1))
    first = _convert(text)
    assert [line[12:16].strip() for line in first.pdb_text.splitlines()] == ["HT1", "HT2", "HT3", "OT1", "OT2"]
    assert _convert(first.pdb_text).pdb_text == first.pdb_text


@pytest.mark.parametrize("target", list(ForceFieldTarget))
def test_standard_proline_terminal_names(target):
    names = ["H1", "H2"]  # GROMACS PRO: native AMBER H3 -> H1.
    text = "".join(_atom(index, name, "PRO") for index, name in enumerate(names, 1))
    expected = ["HN2", "HN1"] if target is ForceFieldTarget.CHARMM else ["H3", "H2"]
    first = _convert(text, target=target)
    assert [line[12:16].strip() for line in first.pdb_text.splitlines()] == expected
    assert _convert(first.pdb_text, target=target).pdb_text == first.pdb_text
