from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dvbfixer import __version__, atom_names


def _atom(
    serial: int,
    atom: str,
    residue: str,
    chain: str = "A",
    number: int = 1,
    *,
    icode: str = "",
) -> str:
    atom_field = atom[:4] if len(atom) == 4 else f" {atom:<3}"
    residue_field = residue if len(residue) == 4 else f"{residue:<3} "
    return (
        f"ATOM  {serial:5d} {atom_field} {residue_field}{chain}{number:4d}{icode or ' '}"
        "      10.123  11.234  12.345  1.00 20.00           C  \n"
    )


def _invoke(*arguments: object) -> None:
    atom_names.main([str(argument) for argument in arguments])


def _invoke_error(*arguments: object) -> int:
    with pytest.raises(SystemExit) as caught:
        _invoke(*arguments)
    return int(caught.value.code)


def _base_paths(tmp_path: Path, text: str | None = None) -> tuple[Path, Path]:
    source = tmp_path / "input.pdb"
    source.write_bytes((text or _atom(1, "HB3", "SER")).encode("latin-1"))
    return source, tmp_path / "output.pdb"


def _error_report(tmp_path: Path, text: str, *extra: object) -> dict[str, object]:
    source, output = _base_paths(tmp_path, text)
    report = tmp_path / "report.json"
    assert _invoke_error(source, "-o", output, "--target-ff", "amber", "--report-json", report, *extra) == 2
    assert not output.exists()
    return json.loads(report.read_text(encoding="utf-8"))


def _assert_report_schema(payload: dict[str, object], status: str) -> None:
    assert set(payload) == {
        "schemaVersion", "operation", "status", "tool", "request", "output", "result", "error"
    }
    assert payload["schemaVersion"] == 1
    assert payload["operation"] == "pdb-force-field-naming"
    assert payload["status"] == status
    tool = payload["tool"]
    request_payload = payload["request"]
    output = payload["output"]
    assert isinstance(tool, dict)
    assert isinstance(request_payload, dict)
    assert isinstance(output, dict)
    assert set(tool) == {"name", "version"}
    assert set(request_payload) == {
        "targetForceField", "profile", "dryRun", "variantOverrides"
    }
    assert set(output) == {"path", "written", "bytes", "sha256"}
    if status == "success":
        result = payload["result"]
        assert isinstance(result, dict)
        assert set(result) == {"model", "summary", "changes", "diagnostics"}
        summary = result["summary"]
        assert isinstance(summary, dict)
        assert set(summary) == {
            "changedAtoms", "changedResidues", "variantChanges", "atomNameChanges"
        }
        assert payload["error"] is None
    else:
        assert payload["result"] is None
        error = payload["error"]
        assert isinstance(error, dict)
        assert set(error) == {"code", "category", "message", "details"}


def test_parser_requires_output_and_target_and_exposes_both_profiles() -> None:
    with pytest.raises(SystemExit) as missing:
        atom_names.parse_args(["input.pdb"])
    assert missing.value.code == 2

    args = atom_names.parse_args(
        ["input.pdb", "-o", "output.pdb", "--target-ff", "amber"]
    )
    assert args.profile == "gromacs"
    assert atom_names.parse_args(
        ["input.pdb", "-o", "output.pdb", "--target-ff", "amber19sb"]
    ).target_ff == "amber19sb"
    assert atom_names.parse_args(
        ["input.pdb", "-o", "output.pdb", "--target-ff", "amber", "--profile", "standard"]
    ).profile == "standard"
    with pytest.raises(SystemExit) as unsupported:
        atom_names.parse_args(
            [
                "input.pdb",
                "-o",
                "output.pdb",
                "--target-ff",
                "amber",
                "--profile",
                "unsupported",
            ]
        )
    assert unsupported.value.code == 2


@pytest.mark.parametrize("target", ["amber", "amber19sb", "charmm"])
def test_standard_profile_converts_and_reports_native_names(tmp_path: Path, target: str) -> None:
    text = _atom(1, "HN", "SER") + _atom(2, "HB1", "SER") + _atom(3, "HB2", "SER")
    source, output = _base_paths(tmp_path, text)
    report = tmp_path / "report.json"
    _invoke(source, "-o", output, "--target-ff", target, "--profile", "standard", "--report-json", report)
    expected = ["HN", "HB1", "HB2"] if target == "charmm" else ["H", "HB3", "HB2"]
    assert [line[12:16].strip() for line in output.read_text().splitlines()] == expected
    assert source.read_text() == text
    payload = json.loads(report.read_text())
    _assert_report_schema(payload, "success")
    assert payload["request"]["profile"] == "standard"


def test_parser_marks_batch_as_unsupported(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        atom_names.parse_args(["--help"])
    assert caught.value.code == 0
    assert "does not support directory batch input" in capsys.readouterr().out


def test_successful_conversion_preserves_source_and_writes_explicit_report(tmp_path: Path) -> None:
    source, output = _base_paths(tmp_path)
    source_bytes = source.read_bytes()
    report = tmp_path / "report.json"

    _invoke(source, "-o", output, "--target-ff", "amber", "--report-json", report)

    assert source.read_bytes() == source_bytes
    assert output.read_text(encoding="latin-1").splitlines()[0][12:16].strip() == "HB1"
    payload = json.loads(report.read_text(encoding="utf-8"))
    _assert_report_schema(payload, "success")
    assert payload["schemaVersion"] == 1
    assert payload["operation"] == "pdb-force-field-naming"
    assert payload["status"] == "success"
    assert payload["tool"] == {"name": "dvbfixer", "version": __version__}
    assert payload["request"] == {
        "targetForceField": "amber",
        "profile": "gromacs",
        "dryRun": False,
        "variantOverrides": [],
    }
    assert payload["output"] == {
        "path": str(output),
        "written": True,
        "bytes": len(output.read_bytes()),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    assert payload["error"] is None
    assert "pdb_text" not in json.dumps(payload)
    change = payload["result"]["changes"][0]
    assert set(change) == {
        "model",
        "chainId",
        "residueNumber",
        "insertionCode",
        "alternateLocation",
        "atomSerial",
        "sourceResidueName",
        "targetResidueName",
        "sourceAtomName",
        "targetAtomName",
        "ruleIds",
    }
    assert change["ruleIds"] == ["amber-atom-name"]
    assert report.read_bytes().endswith(b"\n")


def test_amber19sb_report_preserves_target_and_cap_names(tmp_path: Path) -> None:
    text = "".join(
        _atom(serial, name, "NME")
        for serial, name in enumerate(("N", "H", "C", "H1", "H2", "H3"), 1)
    )
    source, output = _base_paths(tmp_path, text)
    report = tmp_path / "report.json"

    _invoke(source, "-o", output, "--target-ff", "amber19sb", "--report-json", report)

    assert [line[12:16].strip() for line in output.read_text().splitlines()] == [
        "N", "H", "C", "H1", "H2", "H3",
    ]
    payload = json.loads(report.read_text())
    assert payload["request"]["targetForceField"] == "amber19sb"


def test_latin1_noop_still_writes_distinct_identical_output(tmp_path: Path) -> None:
    source, output = _base_paths(tmp_path, "HEADER caf\xe9\n" + _atom(1, "CA", "ALA"))
    original = source.read_bytes()

    _invoke(source, "-o", output, "--target-ff", "charmm")

    assert source.read_bytes() == original
    assert output.read_bytes() == original
    assert output.resolve() != source.resolve()


@pytest.mark.parametrize(
    ("residue", "source_names", "target_names"),
    [
        ("DA", ("H2'", "H2''", "H5'", "H5''"), ("H2'1", "H2'2", "H5'1", "H5'2")),
        ("A", ("H2'", "H2''", "H5'", "H5''", "HO'2"), ("H2'1", "H2'2", "H5'1", "H5'2", "HO2'")),
    ],
)
def test_cli_converts_dna_and_rna_atom_names(
    tmp_path: Path,
    residue: str,
    source_names: tuple[str, ...],
    target_names: tuple[str, ...],
) -> None:
    text = "".join(_atom(serial, name, residue) for serial, name in enumerate(source_names, 1))
    source, output = _base_paths(tmp_path, text)
    report = tmp_path / "report.json"

    _invoke(source, "-o", output, "--target-ff", "amber", "--report-json", report)

    assert tuple(line[12:16].strip() for line in output.read_text().splitlines()) == target_names
    payload = json.loads(report.read_text())
    _assert_report_schema(payload, "success")
    assert payload["result"]["summary"]["changedAtoms"] == len(source_names)
    assert {tuple(change["ruleIds"]) for change in payload["result"]["changes"]} == {
        ("nucleic-acid-atom-name",)
    }


def test_dry_run_writes_only_report_with_candidate_digest(tmp_path: Path) -> None:
    source, output = _base_paths(tmp_path)
    report = tmp_path / "report.json"

    _invoke(
        source,
        "-o",
        output,
        "--target-ff",
        "amber",
        "--dry-run",
        "--report-json",
        report,
    )

    assert not output.exists()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["output"]["written"] is False
    assert payload["output"]["bytes"] > 0
    assert len(payload["output"]["sha256"]) == 64


def test_strict_overrides_preserve_chain_case_and_insertion_code(tmp_path: Path) -> None:
    text = (
        _atom(1, "N", "HIS", "A", 7)
        + _atom(2, "N", "HIS", "A", 7, icode="B")
        + _atom(3, "N", "HIS", "a", 7)
    )
    source, output = _base_paths(tmp_path, text)
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        json.dumps(
            [
                {
                    "chainId": "A",
                    "residueNumber": "7",
                    "insertionCode": "B",
                    "variant": "HIE",
                }
            ]
        ),
        encoding="utf-8",
    )
    report = tmp_path / "report.json"

    _invoke(
        source,
        "-o",
        output,
        "--target-ff",
        "charmm",
        "--variant-overrides",
        overrides,
        "--report-json",
        report,
    )

    names = [line[17:21].strip() for line in output.read_text().splitlines()]
    assert names == ["HIS", "HSE", "HIS"]
    payload = json.loads(report.read_text())
    assert payload["request"]["variantOverrides"][0]["insertionCode"] == "B"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [{}],
        [{"chainId": "A", "residueNumber": 1, "variant": "HIE"}],
        [{"chainId": "AA", "residueNumber": "1", "variant": "HIE"}],
        [{"chainId": "A", "residueNumber": "1.0", "variant": "HIE"}],
        [{"chainId": "A", "residueNumber": "1", "variant": "hie"}],
        [{"chainId": "A", "residueNumber": "1", "variant": "HIE", "extra": "x"}],
        [
            {"chainId": "A", "residueNumber": "1", "variant": "HIE"},
            {"chainId": "A", "residueNumber": "1", "insertionCode": "", "variant": "HID"},
        ],
    ],
)
def test_invalid_and_duplicate_overrides_write_stable_error_report(
    tmp_path: Path, payload: object
) -> None:
    source, output = _base_paths(tmp_path)
    overrides = tmp_path / "overrides.json"
    overrides.write_text(json.dumps(payload), encoding="utf-8")
    report = tmp_path / "report.json"

    assert _invoke_error(
        source,
        "-o",
        output,
        "--target-ff",
        "amber",
        "--variant-overrides",
        overrides,
        "--report-json",
        report,
    ) == 2

    assert not output.exists()
    error = json.loads(report.read_text())["error"]
    assert error["code"] == "INVALID_VARIANT_OVERRIDES"
    assert error["category"] == "validation"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (_atom(1, "HB1", "SER") + _atom(2, "HB3", "SER"), "NAMING_COLLISION"),
        ("ATOM\n", "MALFORMED_PDB"),
        ("MODEL        1\nENDMDL\nMODEL        2\nENDMDL\n", "MULTI_MODEL_UNSUPPORTED"),
    ],
)
def test_conversion_failures_keep_stable_codes(tmp_path: Path, text: str, code: str) -> None:
    payload = _error_report(tmp_path, text)
    _assert_report_schema(payload, "error")
    assert payload["status"] == "error"
    assert payload["result"] is None
    assert payload["error"]["code"] == code
    assert payload["error"]["category"] == "conversion"
    assert set(payload["error"]) == {"code", "category", "message", "details"}


def test_rejects_source_output_aliases_including_symlink(tmp_path: Path) -> None:
    source, _output = _base_paths(tmp_path)
    original = source.read_bytes()
    assert _invoke_error(source, "-o", source, "--target-ff", "amber") == 2

    alias = tmp_path / "alias.pdb"
    alias.symlink_to(source)
    assert _invoke_error(source, "-o", alias, "--target-ff", "amber") == 2
    assert source.read_bytes() == original


def test_rejects_path_conflicts_and_existing_destinations(tmp_path: Path) -> None:
    source, output = _base_paths(tmp_path)
    overrides = tmp_path / "overrides.json"
    overrides.write_text("[]")
    assert _invoke_error(
        source,
        "-o",
        output,
        "--target-ff",
        "amber",
        "--variant-overrides",
        overrides,
        "--report-json",
        overrides,
    ) == 2

    missing_shared_path = tmp_path / "missing-shared.json"
    assert _invoke_error(
        source,
        "-o",
        output,
        "--target-ff",
        "amber",
        "--variant-overrides",
        missing_shared_path,
        "--report-json",
        missing_shared_path,
    ) == 2
    assert not missing_shared_path.exists()

    output.write_text("existing")
    assert _invoke_error(source, "-o", output, "--target-ff", "amber") == 2
    assert output.read_text() == "existing"

    output.unlink()
    report = tmp_path / "report.json"
    report.write_text("existing")
    assert _invoke_error(
        source, "-o", output, "--target-ff", "amber", "--report-json", report
    ) == 2
    assert report.read_text() == "existing"
    assert not output.exists()


def test_report_and_overrides_cannot_alias_source(tmp_path: Path) -> None:
    source, output = _base_paths(tmp_path)
    original = source.read_bytes()

    assert _invoke_error(
        source,
        "-o",
        output,
        "--target-ff",
        "amber",
        "--report-json",
        source,
    ) == 2
    assert source.read_bytes() == original
    assert not output.exists()

    assert _invoke_error(
        source,
        "-o",
        output,
        "--target-ff",
        "amber",
        "--variant-overrides",
        source,
    ) == 2
    assert source.read_bytes() == original
    assert not output.exists()


def test_rejects_missing_wrong_extensions_and_cif_without_normalization(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pdb"
    output = tmp_path / "output.pdb"
    assert _invoke_error(missing, "-o", output, "--target-ff", "amber") == 2

    source = tmp_path / "input.cif"
    source.write_text("data_valid\n_atom_site.id 1\n")
    report = tmp_path / "report.json"
    assert _invoke_error(
        source, "-o", output, "--target-ff", "amber", "--report-json", report
    ) == 2
    assert json.loads(report.read_text())["error"]["code"] == "UNSUPPORTED_INPUT_FORMAT"
    assert not output.exists()

    pdb = tmp_path / "input.pdb"
    pdb.write_text(_atom(1, "CA", "ALA"))
    assert _invoke_error(pdb, "-o", tmp_path / "output.ent", "--target-ff", "amber") == 2


def test_output_publication_failure_removes_report_and_temporary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, output = _base_paths(tmp_path)
    report = tmp_path / "report.json"
    real_publish = atom_names._publish

    def fail_output(staged: Path, destination: Path) -> None:
        if destination == output:
            raise OSError("simulated output publication failure")
        real_publish(staged, destination)

    monkeypatch.setattr(atom_names, "_publish", fail_output)
    assert _invoke_error(
        source, "-o", output, "--target-ff", "amber", "--report-json", report
    ) == 1
    assert not output.exists()
    assert not report.exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_unified_cli_subprocess_dispatch_uses_report_not_stdout(tmp_path: Path) -> None:
    source, output = _base_paths(tmp_path)
    report = tmp_path / "report.json"
    environment = os.environ.copy()
    source_root = str(Path(__file__).parents[1] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_root, environment.get("PYTHONPATH", "")) if part
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from dvbfixer.cli import main; main()",
            "atom-names",
            str(source),
            "-o",
            str(output),
            "--target-ff",
            "amber",
            "--report-json",
            str(report),
        ],
        env=environment,
        check=False,
        capture_output=True,
    )

    assert completed.returncode == 0
    assert output.is_file()
    assert json.loads(report.read_text())["status"] == "success"
