from __future__ import annotations

import argparse
import hashlib
import itertools
import shutil
import subprocess
from pathlib import Path

import pytest

from dvbfixer.top.capabilities import (
    DEFAULT_TOPOLOGY_FORCE_FIELD,
    TOPOLOGY_FORCE_FIELDS,
    resolve_bundle,
    resolve_force_field,
    validate_options,
)
from dvbfixer.top.cli import FF_DIR, parse_args
from dvbfixer.top.pipeline import _preflight_amber19sb, read_pdb_chains
from dvbfixer.top.topology_builder import TopologyBuilder
from dvbfixer.top.types import PDBChain, PDBResidue

AMBER19SB = resolve_force_field("amber19sb")
WATER_ION_PAIRS = tuple(AMBER19SB.water_ion_pairs.items())


def _builder() -> TopologyBuilder:
    root = resolve_bundle(AMBER19SB, FF_DIR)
    return TopologyBuilder(root, "amber19sb", descriptor=AMBER19SB)


def _append_chain(
    lines: list[str], builder: TopologyBuilder, chain: str,
    residues: list[tuple[str, int, str]], serial: int = 1,
) -> int:
    for index, (resname, resseq, icode) in enumerate(residues):
        if len(residues) == 1:
            position = "twter"
        elif index == 0:
            position = "nter"
        elif index == len(residues) - 1:
            position = "cter"
        else:
            position = "mid"
        rtp_name = builder._resolve_resname(resname, position, set())
        assert rtp_name is not None
        for atom_index, (atom_name, _atom_type, _charge, _cgnr) in enumerate(
            builder.residues[rtp_name].atoms
        ):
            x = index * 1.30 + atom_index * 0.005
            y = atom_index * 0.003
            element = next((char for char in atom_name if char.isalpha()), "C")
            lines.append(
                f"ATOM  {serial:5d} {atom_name:^4s} {resname:>3s} {chain}"
                f"{resseq:4d}{icode[:1]:1s}   {x:8.3f}{y:8.3f}{0.0:8.3f}"
                f"  1.00  0.00          {element:>2s}\n"
            )
            serial += 1
        lines.append("TER\n")
    return serial


def _write_peptide(
    path: Path, residues: list[tuple[str, int, str]] | None = None,
    extra_chains: list[tuple[str, list[tuple[str, int, str]]]] | None = None,
) -> Path:
    builder = _builder()
    lines: list[str] = []
    serial = _append_chain(
        lines, builder, "A", residues or [("ALA", 1, ""), ("GLY", 2, ""), ("VAL", 3, "")]
    )
    for chain, chain_residues in extra_chains or []:
        serial = _append_chain(lines, builder, chain, chain_residues, serial)
    lines.append("END\n")
    path.write_text("".join(lines))
    return path


def _run_top(path: Path, out_dir: Path, *extra: str) -> Path:
    from dvbfixer.top import main as top_main

    out_dir.mkdir()
    top = out_dir / "topol.top"
    top_main([
        str(path), "--ff", "amber19sb", "--no-infer-conect",
        "-o", str(top), "--pdb", str(out_dir / "conf.pdb"), *extra,
    ])
    return top


def _section_atom_types(path: Path, section: str) -> set[str]:
    result: set[str] = set()
    current = ""
    for raw in path.read_text().splitlines():
        line = raw.split(";", 1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            continue
        if current != section or not line:
            continue
        parts = line.split()
        if section == "atomtypes":
            result.add(parts[0])
        elif parts[0].isdigit() and len(parts) > 1:
            result.add(parts[1])
    return result


def test_descriptor_and_cli_defaults() -> None:
    args = parse_args(["input.pdb"])
    assert args.ff == DEFAULT_TOPOLOGY_FORCE_FIELD == "amber"
    assert tuple(TOPOLOGY_FORCE_FIELDS) == ("amber", "amber19sb", "charmm")
    assert AMBER19SB.fail_closed
    assert AMBER19SB.supports_cmap
    assert not AMBER19SB.has_arn
    assert not AMBER19SB.supports_custom_ff_dir
    assert not AMBER19SB.supports_acpype
    assert AMBER19SB.accepted_molecule_classes == {
        "protein", "protein-cap", "water", "simple-ion",
    }


def test_bundle_inventory_and_manifest() -> None:
    bundle = resolve_bundle(AMBER19SB, FF_DIR)
    assert {path.name for path in bundle.iterdir()} == set(AMBER19SB.expected_sha256)
    for name, expected in AMBER19SB.expected_sha256.items():
        assert hashlib.sha256((bundle / name).read_bytes()).hexdigest() == expected


def test_absent_optional_arn_is_explicit_and_buildable() -> None:
    builder = _builder()
    assert builder.arn == {}
    assert builder.arn_reverse == {}


@pytest.mark.parametrize(("water", "pair"), WATER_ION_PAIRS)
def test_every_upstream_water_ion_pair_is_self_contained(
    tmp_path: Path, water: str, pair: object,
) -> None:
    input_pdb = _write_peptide(tmp_path / "input.pdb")
    out = tmp_path / water
    _run_top(input_pdb, out, "--water", water)

    atomtypes = _section_atom_types(out / "ffparams.itp", "atomtypes")
    used = _section_atom_types(out / "water.itp", "atoms")
    used |= _section_atom_types(out / "ions.itp", "atoms")
    assert used
    assert used <= atomtypes
    assert "#include" not in (out / "water.itp").read_text()
    assert "#include" not in (out / "ions.itp").read_text()
    assert pair.water_file == f"{water}.itp"
    assert pair.ion_file == f"ions_{water}.itp"


@pytest.mark.parametrize(
    ("water", "ion_set"),
    [
        (water, other.ion_set)
        for (water, _pair), (_other_water, other) in itertools.permutations(WATER_ION_PAIRS, 2)
    ],
)
def test_all_amber19sb_cross_pairs_are_rejected(water: str, ion_set: str) -> None:
    args = argparse.Namespace(
        water=water, ion_set=ion_set, ff_dir=None, merge=False, acpype=False, pdb=None,
    )
    with pytest.raises(ValueError, match="Unsupported Amber19SB water/ion pair"):
        validate_options(AMBER19SB, args)


def test_standard_residues_cmap_and_terminal_blocks(tmp_path: Path) -> None:
    residues = [
        (name, index, "")
        for index, name in enumerate(sorted(AMBER19SB.accepted_residues - {
            "ACE", "NME", "ASH", "GLH", "HID", "HIE", "HIP", "CYX", "CYM", "LYN", "HYP",
        }), 1)
    ]
    top = _run_top(_write_peptide(tmp_path / "standard.pdb", residues), tmp_path / "out")
    chain_itp = top.parent / "Protein_chain_A.itp"
    assert "[ cmap ]" in chain_itp.read_text()
    assert "[ cmaptypes ]" in (top.parent / "ffparams.itp").read_text()


def test_caps_protonation_variants_hyp_and_chyp(tmp_path: Path) -> None:
    variants = [
        ("ACE", 1, ""), ("ALA", 2, ""), ("ASH", 3, ""), ("GLH", 4, ""),
        ("HID", 5, ""), ("HIE", 6, ""), ("HIP", 7, ""), ("CYM", 8, ""),
        ("LYN", 9, ""), ("HYP", 10, ""), ("NME", 11, ""),
    ]
    out = tmp_path / "out"
    _run_top(_write_peptide(tmp_path / "variants.pdb", variants), out)
    text = (out / "Protein_chain_A.itp").read_text()
    for name in ("ACE", "ASH", "GLH", "HID", "HIE", "HIP", "CYM", "LYN", "HYP", "NME"):
        assert name in text

    builder = _builder()
    chain = read_pdb_chains(_write_peptide(
        tmp_path / "chyp.pdb", [("ALA", 1, ""), ("HYP", 2, "")]
    ))[0]
    built = builder.build_chain(chain)
    assert built is not None
    assert built.atoms[-1].resname == "CHYP"


def test_disulfide_case_sensitive_chains_and_insertion_codes(tmp_path: Path) -> None:
    input_pdb = _write_peptide(
        tmp_path / "identity.pdb",
        [("ALA", 1, ""), ("CYS", 2, ""), ("CYS", 3, ""), ("VAL", 4, "")],
        extra_chains=[
            ("D", [("ALA", 82, ""), ("GLY", 82, "A"), ("VAL", 83, "")]),
            ("d", [("ALA", 1, ""), ("GLY", 2, ""), ("VAL", 3, "")]),
        ],
    )
    out = tmp_path / "out"
    _run_top(input_pdb, out, "--ss", "A:2:A:3")
    assert (out / "Protein_chain_D.itp").is_file()
    assert (out / "Protein_chain_d.itp").is_file()
    pdb_lines = (out / "conf.pdb").read_text().splitlines()
    assert any(line[21] == "D" and line[22:27] == "  82A" for line in pdb_lines if line.startswith("ATOM"))
    assert "CYX" in (out / "Protein_chain_A.itp").read_text()


@pytest.mark.parametrize("resname", ["DA", "A", "NAG", "POPC", "LIG", "MSE", "ZN"])
def test_unsupported_component_classes_name_identity_and_alternative(resname: str) -> None:
    chain = PDBChain("a", [PDBResidue("a", resname, 82, "A", [("C1", 0.0, 0.0, 0.0)])])
    with pytest.raises(ValueError) as exc:
        _preflight_amber19sb([chain], AMBER19SB, set())
    message = str(exc.value)
    assert resname in message
    assert "a:82A" in message
    assert "use --ff" in message


def test_unsupported_input_leaves_no_partial_artifacts(tmp_path: Path) -> None:
    from dvbfixer.top import main as top_main

    input_pdb = _write_peptide(tmp_path / "mixed.pdb")
    with input_pdb.open("a") as handle:
        handle.write(
            "HETATM 9999  C1  NAG A 900       0.000   0.000   0.000  1.00  0.00           C\n"
        )
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(SystemExit):
        top_main([
            str(input_pdb), "--ff", "amber19sb", "--no-infer-conect",
            "-o", str(out / "topol.top"),
        ])
    assert list(out.iterdir()) == []


@pytest.mark.parametrize(("water", "pair"), WATER_ION_PAIRS)
def test_grompp_external_acceptance(tmp_path: Path, water: str, pair: object) -> None:
    gmx = shutil.which("gmx")
    if gmx is None:
        pytest.skip("GROMACS `gmx` executable unavailable; Amber19SB grompp acceptance not executed")
    input_pdb = _write_peptide(tmp_path / "input.pdb")
    out = tmp_path / "out"
    top = _run_top(input_pdb, out, "--water", water)
    # Verlet requires periodic boundaries. A finite, sufficiently large box is
    # part of the preprocessing fixture, not a change to force-field parameters.
    coordinates = out / "boxed.gro"
    boxed = subprocess.run(
        [gmx, "editconf", "-f", str(out / "conf.pdb"), "-o", str(coordinates), "-box", "4", "4", "4"],
        cwd=out, text=True, capture_output=True, check=False,
    )
    assert boxed.returncode == 0, boxed.stdout + boxed.stderr
    mdp = out / "acceptance.mdp"
    mdp.write_text(
        "integrator = md\nnsteps = 0\ncontinuation = yes\npbc = xyz\ncutoff-scheme = Verlet\n"
        "comm-mode = none\nverlet-buffer-tolerance = -1\n"
        "nstlist = 10\nrlist = 1.0\ncoulombtype = Cut-off\nrcoulomb = 1.0\n"
        "vdwtype = Cut-off\nrvdw = 1.0\n"
    )
    result = subprocess.run(
        [gmx, "grompp", "-f", str(mdp), "-p", str(top), "-c", str(coordinates),
         "-o", str(out / "acceptance.tpr"), "-maxwarn", "0"],
        cwd=out, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
