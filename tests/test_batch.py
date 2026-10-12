from argparse import Namespace
from pathlib import Path

import pytest

from dvbfixer.batch import extract_batch_options, run_directory
from dvbfixer.ffutils.dat import DatRecord
from dvbfixer.zbs import main as zbs_main

PDB_WITH_CASE_DISTINCT_CHAINS = """\
ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C
ATOM      2  CA  GLY b   1       4.000   0.000   0.000  1.00  0.00           C
TER
END
"""


def _pdb_chains(path: Path) -> set[str]:
    return {
        line[21]
        for line in path.read_text().splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    }


def _tree_snapshot(root: Path) -> tuple[list[str], dict[str, bytes]]:
    entries = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
    contents = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    return entries, contents


def _install_fake_zbs_stages(monkeypatch, calls):
    def stage(name, *, sidecar=False):
        def fake(argv):
            source = Path(argv[0])
            output = Path(argv[argv.index("-o") + 1])
            assert _pdb_chains(source) == {"A", "b"}
            calls.append((name, source, output))

            outputs = [output]
            if name == "model" and int(argv[argv.index("--num-output") + 1]) > 1:
                outputs = [
                    output.with_stem(f"{output.stem}_1"),
                    output.with_stem(f"{output.stem}_2"),
                ]
            for destination in outputs:
                destination.write_text(source.read_text())
                if sidecar:
                    DatRecord(
                        description=f"fake {name} output",
                        added_atoms=[{
                            "chain": "b", "resid": "1", "icode": "",
                            "resname": "GLY", "atom": "CA", "element": "C",
                        }],
                        residue_summary={"b/GLY1": {"heavy": 1, "hydrogen": 0}},
                    ).save(destination.with_suffix(".dat"), verbose=False)

        return fake

    monkeypatch.setattr("dvbfixer.renumber.main", stage("renumber"))
    monkeypatch.setattr("dvbfixer.model.main", stage("model", sidecar=True))
    monkeypatch.setattr("dvbfixer.prepare.main", stage("prepare", sidecar=True))
    monkeypatch.setattr("dvbfixer.minimize.main", stage("minimize"))


def test_extract_batch_options_preserves_command_arguments():
    options, remaining = extract_batch_options(
        ["--input-dir", "structures", "--no-solvent", "--recursive"]
    )
    assert options.input_dir == "structures"
    assert options.recursive is True
    assert options.fail_fast is False
    assert remaining == ["--no-solvent"]


@pytest.mark.parametrize(
    "argv",
    [
        ["input.pdb", "--output", "output.pdb"],
        ["input.pdb", "--log", "command-specific-value"],
        ["--input", "command-specific-value"],
        ["input.pdb", "--fail", "command-specific-value"],
    ],
)
def test_extract_batch_options_does_not_abbreviate_global_flags(argv):
    options, remaining = extract_batch_options(argv)
    assert options.input_dir is None
    assert options.output_dir is None
    assert options.log_file is None
    assert options.fail_fast is False
    assert remaining == argv


def test_directory_runs_each_pdb_and_preserves_subdirectories(tmp_path: Path):
    source = tmp_path / "structures"
    nested = source / "nested"
    nested.mkdir(parents=True)
    (source / "a.pdb").write_text("END\n")
    (nested / "b.ent").write_text("END\n")
    (source / "c.cif").write_text("data_c\n")
    (nested / "d.mmcif").write_text("data_d\n")
    (source / "ignore.txt").write_text("not a structure\n")
    output = tmp_path / "results"
    calls = []

    run_directory(
        "zbs",
        calls.append,
        Namespace(
            input_dir=str(source),
            output_dir=str(output),
            recursive=True,
            fail_fast=False,
        ),
        ["--no-solvent"],
    )

    assert calls == [
        [str(source / "a.pdb"), "--no-solvent", "-o", str(output / "a_zbs.pdb")],
        [str(source / "c.cif"), "--no-solvent", "-o", str(output / "c_zbs.pdb")],
        [
            str(nested / "b.ent"),
            "--no-solvent",
            "-o",
            str(output / "nested" / "b_zbs.pdb"),
        ],
        [
            str(nested / "d.mmcif"),
            "--no-solvent",
            "-o",
            str(output / "nested" / "d_zbs.pdb"),
        ],
    ]


def test_batch_zbs_contains_retained_intermediates_in_nested_output(
    monkeypatch, tmp_path: Path,
):
    source_root = tmp_path / "source"
    source_dir = source_root / "nested" / "complexes"
    source_dir.mkdir(parents=True)
    source = source_dir / "sample.pdb"
    source.write_text(PDB_WITH_CASE_DISTINCT_CHAINS)
    source_before = _tree_snapshot(source_root)
    output_root = tmp_path / "results"
    calls = []
    _install_fake_zbs_stages(monkeypatch, calls)

    run_directory(
        "zbs",
        zbs_main,
        Namespace(
            input_dir=str(source_root),
            output_dir=str(output_root),
            recursive=True,
            fail_fast=False,
        ),
        ["--keep-interim", "--no-postflight", "--no-align-to-input", "--no-solvent"],
    )

    destination = output_root / "nested" / "complexes"
    expected_pdbs = [
        destination / f"sample_{suffix}.pdb"
        for suffix in ("renum", "model", "prepared", "minimized", "zbs")
    ]
    expected_sidecars = [
        destination / "sample_model.dat",
        destination / "sample_prepared.dat",
    ]
    assert all(path.is_file() for path in [*expected_pdbs, *expected_sidecars])
    assert all(path.is_relative_to(output_root) for path in [*expected_pdbs, *expected_sidecars])
    assert all(_pdb_chains(path) == {"A", "b"} for path in expected_pdbs)
    assert [DatRecord.load(path).description for path in expected_sidecars] == [
        "fake model output",
        "fake prepare output",
    ]
    assert [(name, input_path, output_path) for name, input_path, output_path in calls] == [
        ("renumber", source, destination / "sample_renum.pdb"),
        ("model", destination / "sample_renum.pdb", destination / "sample_model.pdb"),
        ("prepare", destination / "sample_model.pdb", destination / "sample_prepared.pdb"),
        ("minimize", destination / "sample_prepared.pdb", destination / "sample_minimized.pdb"),
    ]
    assert _tree_snapshot(source_root) == source_before


def test_batch_zbs_multi_output_cleanup_retains_unselected_candidates(
    monkeypatch, tmp_path: Path,
):
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "sample.pdb"
    source.write_text(PDB_WITH_CASE_DISTINCT_CHAINS)
    source_before = _tree_snapshot(source_root)
    output_root = tmp_path / "results"
    calls = []
    _install_fake_zbs_stages(monkeypatch, calls)

    run_directory(
        "zbs",
        zbs_main,
        Namespace(
            input_dir=str(source_root),
            output_dir=str(output_root),
            recursive=False,
            fail_fast=False,
        ),
        ["--num-output", "2", "--no-postflight", "--no-align-to-input", "--no-solvent"],
    )

    final_output = output_root / "sample_zbs.pdb"
    retained_candidate = output_root / "sample_model_2.pdb"
    retained_sidecar = output_root / "sample_model_2.dat"
    assert final_output.is_file()
    assert retained_candidate.is_file()
    assert retained_sidecar.is_file()
    assert _pdb_chains(final_output) == {"A", "b"}
    assert DatRecord.load(retained_sidecar).description == "fake model output"
    assert calls[2][1] == output_root / "sample_model_1.pdb"

    removed_intermediates = [
        output_root / f"sample_{suffix}{extension}"
        for suffix in ("renum", "model", "model_1", "prepared", "minimized")
        for extension in (".pdb", ".dat")
    ]
    assert not any(path.exists() for path in removed_intermediates)
    assert _tree_snapshot(source_root) == source_before


def test_directory_rejects_ambiguous_output_option(tmp_path: Path):
    (tmp_path / "a.pdb").write_text("END\n")
    with pytest.raises(SystemExit, match="Use --output-dir"):
        run_directory(
            "prepare",
            lambda argv: None,
            Namespace(
                input_dir=str(tmp_path),
                output_dir=None,
                recursive=False,
                fail_fast=False,
            ),
            ["-o", "one.pdb"],
        )


@pytest.mark.parametrize(
    "backend_args",
    (["--backend", "diffusion"], ["--backend=diffusion"]),
)
def test_directory_diffusion_reports_missing_publication(
    tmp_path: Path,
    backend_args: list[str],
):
    source = tmp_path / "structures"
    source.mkdir()
    (source / "a.pdb").write_text("END\n")
    output = tmp_path / "results"
    calls: list[list[str]] = []

    with pytest.raises(SystemExit):
        run_directory(
            "model",
            calls.append,
            Namespace(
                input_dir=str(source),
                output_dir=str(output),
                recursive=False,
                fail_fast=False,
            ),
            backend_args,
        )

    assert len(calls) == 1
    assert calls[0][-1].endswith("a_model_diffusion")
    assert (output / "diffusion-batch.json").exists()


def test_directory_continues_by_default_and_prints_clear_summary(tmp_path: Path, capsys):
    (tmp_path / "a.pdb").write_text("END\n")
    (tmp_path / "b.pdb").write_text("END\n")
    calls = []

    def fail(argv):
        calls.append(Path(argv[0]).name)
        raise SystemExit(1)

    with pytest.raises(SystemExit) as caught:
        run_directory(
            "zbs", fail,
            Namespace(input_dir=str(tmp_path), output_dir=str(tmp_path / "results"),
                      recursive=False, fail_fast=False),
            ["--no-solvent"],
        )
    assert caught.value.code == 1
    assert calls == ["a.pdb", "b.pdb"]
    output = capsys.readouterr().out
    assert "Batch mode completed: 0 succeeded, 2 failed, 0 not processed" in output
    assert "Batch failed for" not in output
    assert "command exited with status 1" in output
    assert "How to fix:" in output


def test_directory_summary_retains_command_error_and_explains_fasta_chain_mismatch(
    tmp_path: Path, capsys,
):
    (tmp_path / "8cxi_t_b.pdb").write_text("END\n")

    def fail(_argv):
        print(
            "Error: FASTA missing sequences for chain(s): A. "
            "FASTA has: B, D, E. PDB has: A.",
            file=__import__("sys").stderr,
        )
        raise SystemExit(1)

    with pytest.raises(SystemExit, match="1"):
        run_directory(
            "zbs", fail,
            Namespace(input_dir=str(tmp_path), output_dir=str(tmp_path / "results"),
                      recursive=False, fail_fast=False),
            ["--fasta", "chains.fasta"],
        )

    output = capsys.readouterr()
    combined = output.out + output.err
    assert "Cause: FASTA missing sequences for chain(s): A" in combined
    assert "Rename/add the FASTA header for every listed PDB chain" in combined
    assert "Chain IDs are case-sensitive" in combined


def test_fail_fast_stops_after_first_failure(tmp_path: Path):
    (tmp_path / "a.pdb").write_text("END\n")
    (tmp_path / "b.pdb").write_text("END\n")
    calls = []

    def fail(argv):
        calls.append(Path(argv[0]).name)
        raise SystemExit(2)

    with pytest.raises(SystemExit):
        run_directory(
            "prepare", fail,
            Namespace(input_dir=str(tmp_path), output_dir=str(tmp_path / "results"),
                      recursive=False, fail_fast=True),
            [],
        )
    assert calls == ["a.pdb"]


def test_diagnose_exit_one_is_findings_not_execution_failure(tmp_path: Path, capsys):
    (tmp_path / "a.pdb").write_text("END\n")
    with pytest.raises(SystemExit) as caught:
        run_directory(
            "diagnose", lambda argv: (_ for _ in ()).throw(SystemExit(1)),
            Namespace(input_dir=str(tmp_path), output_dir=str(tmp_path / "results"),
                      recursive=False, fail_fast=False),
            [],
        )
    assert caught.value.code == 1  # retains diagnose's CI-friendly semantics
    output = capsys.readouterr().out
    assert "1 with ERROR findings, 0 execution failures" in output
    assert "FAILED:" not in output
