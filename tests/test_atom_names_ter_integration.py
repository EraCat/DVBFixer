"""Exercise TER handling through the real CLI and its published PDB/JSON files."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _atom(serial: int, name: str, number: int, chain: str, icode: str = " ", residue: str = "ALA") -> str:
    return (
        f"ATOM  {serial:5d}  {name:<3} {residue:3} {chain}{number:4d}{icode}"
        f"      10.123  11.234  12.345  0.75 20.00          {name[0]:>2}  \n"
    )


def _run(source: Path, output: Path, *options: str, expected_code: int = 0) -> dict:
    report = output.with_suffix(".json")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(Path(__file__).parents[1] / "src"), environment.get("PYTHONPATH", "")) if part
    )
    completed = subprocess.run(
        [sys.executable, "-c", "from dvbfixer.cli import main; main()", "atom-names",
         str(source), "-o", str(output), "--report-json", str(report), *options],
        env=environment, capture_output=True, check=False, timeout=30,
    )
    assert completed.returncode == expected_code, (completed.stdout, completed.stderr)
    return json.loads(report.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("boundary", "chain", "target", "profile"),
    [
        ("", "A", "amber", "gromacs"),
        ("TER\n", "A", "amber", "gromacs"),
        ("TER\nTER\n", "A", "amber", "gromacs"),
        ("TER       5      ALA {chain}   1A\n", " ", "amber", "gromacs"),
        ("TER\n", " ", "amber19sb", "gromacs"),
        ("TER\n", "A", "charmm", "gromacs"),
        ("TER\n", "A", "amber", "standard"),
    ],
)
def test_cli_terminal_names_respect_ter_and_preserve_payload(
    tmp_path: Path, boundary: str, chain: str, target: str, profile: str,
) -> None:
    # Insertion codes distinguish consecutive residues; numbering gaps alone
    # must not introduce termini. Include ANISOU and CRLF byte preservation.
    first = _atom(1, "H", 1, chain)
    first += _atom(2, "H", 1, chain, "A")
    oxygen = _atom(3, "O", 1, chain, "A")
    anisou = "ANISOU" + oxygen[6:28] + "   1000   1100   1200    100    200    300       O  \n"
    first += oxygen + anisou + _atom(4, "OXT", 1, chain, "A")
    second = _atom(6, "H", 8, chain) + _atom(7, "H", 9, chain)
    second += _atom(8, "O", 9, chain) + _atom(9, "OXT", 9, chain)
    original = ("REMARK synthetic naming-only input\n" + first + boundary.format(chain=chain) + second + "END\n").replace("\n", "\r\n").encode("latin-1")
    source = tmp_path / "input.pdb"
    source.write_bytes(original)
    output = tmp_path / "named.pdb"
    options = ("--target-ff", target, "--profile", profile)
    report = _run(source, output, *options)
    converted = output.read_bytes()
    assert source.read_bytes() == original
    assert report["status"] == "success"
    before, after = original.splitlines(keepends=True), converted.splitlines(keepends=True)
    assert len(before) == len(after)
    for left, right in zip(before, after, strict=True):
        assert left[:12] == right[:12]
        assert left[16:] == right[16:]
        if not left.startswith((b"ATOM  ", b"ANISOU")):
            assert left == right

    names = [line[12:16].strip().decode() for line in after if line.startswith(b"ATOM  ")]
    if profile == "standard":
        expected = ["H", "H", "O", "OXT", "H", "H", "O", "OXT"]
    elif target == "charmm":
        expected = ["HN", "HN", "O", "OXT", "HN", "HN", "O", "OXT"]
    else:
        first_oxygen = ["OC2", "OC1"] if boundary and target == "amber" else ["O", "OXT"]
        last_oxygen = ["OC2", "OC1"] if target == "amber" else ["O", "OXT"]
        expected = ["H1", "H", *first_oxygen, "H1" if boundary else "H", "H", *last_oxygen]
    assert names == expected
    assert next(line[12:16].strip().decode() for line in after if line.startswith(b"ANISOU")) == expected[2]

    repeated = tmp_path / "repeated.pdb"
    assert _run(output, repeated, *options)["result"]["summary"]["changedAtoms"] == 0
    assert repeated.read_bytes() == converted
    dry_output = tmp_path / "dry.pdb"
    dry = _run(source, dry_output, *options, "--dry-run")
    assert not dry_output.exists()
    assert dry["result"] == report["result"]
    assert dry["output"]["sha256"] == report["output"]["sha256"]


@pytest.mark.parametrize("target", ["amber", "amber19sb", "charmm"])
@pytest.mark.parametrize("profile", ["gromacs", "standard"])
def test_cli_rejects_residue_identity_reused_across_ter(tmp_path: Path, target: str, profile: str) -> None:
    # Disjoint atom names would evade an atom-level duplicate check and merge
    # hydrogen evidence from different fragments into a fictitious HIP state.
    original = (_atom(1, "HD1", 1, "a", residue="HIS") + "TER\n"
                + _atom(2, "HE2", 1, "a", residue="HIS")).encode("latin-1")
    source = tmp_path / "input.pdb"
    source.write_bytes(original)
    for infer in ((), ("--infer-protonation",)):
        output = tmp_path / ("inferred.pdb" if infer else "named.pdb")
        report = _run(source, output, "--target-ff", target, "--profile", profile, *infer, expected_code=2)
        assert not output.exists()
        assert not report["output"]["written"]
        assert report["error"]["code"] == "NAMING_COLLISION"
        assert "TER" in report["error"]["message"]
        assert report["error"]["details"] == {
            "model": 1, "chain": "a", "residue_number": "1", "insertion_code": "", "lines": [1, 3],
        }
    assert source.read_bytes() == original


def test_cli_caps_and_chain_case_remain_distinct_across_ter(tmp_path: Path) -> None:
    # An ACE cap prevents the following ALA from being treated as a free N end;
    # uppercase/lowercase chains may safely reuse the same residue numbers.
    original = (_atom(1, "C", 1, "A", residue="ACE") + _atom(2, "H", 2, "A")
                + _atom(3, "O", 2, "A") + _atom(4, "OXT", 2, "A") + "TER\n"
                + _atom(5, "H", 1, "a") + _atom(6, "O", 1, "a")
                + _atom(7, "OXT", 1, "a")).encode("latin-1")
    source = tmp_path / "input.pdb"
    source.write_bytes(original)
    output = tmp_path / "named.pdb"
    _run(source, output, "--target-ff", "amber")
    names = [line[12:16].strip() for line in output.read_bytes().splitlines() if line.startswith(b"ATOM  ")]
    assert names == [b"C", b"H", b"OC2", b"OC1", b"H1", b"OC2", b"OC1"]
