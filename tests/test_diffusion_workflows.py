"""Publication custody, batch preflight, and validated ZBS PDB/.dat handoffs."""

from __future__ import annotations

import hashlib
import json
from argparse import Namespace
from pathlib import Path

import pytest

from dvbfixer.batch import run_directory
from dvbfixer.ffutils.dat import DatRecord
from dvbfixer.model.diffusion.contract import AtomIdentity
from dvbfixer.model.diffusion.publication import (
    PublicationError,
    copy_selected_candidate,
    read_published_bundle,
)
from dvbfixer.model.diffusion.trace import build_sampler_trace
from dvbfixer.zbs import main as zbs_main


def _bundle(root: Path, *, passed=True, payload=b"END\n") -> None:
    root.mkdir(parents=True)
    pdb = root / "ranked-first.pdb"
    pdb.write_bytes(payload)
    dat = root / "ranked-first.dat"
    DatRecord(added_atoms=[{
        "chain": "d", "resid": "82", "icode": "A", "resname": "ALA", "atom": "CA", "element": "C",
    }]).save(dat, verbose=False)
    atom = AtomIdentity("d", "82", "A", "CA")
    trace = build_sampler_trace(
        profile="test", engine_repository="test://engine", engine_revision="test",
        patch_identity="test", atom_order=(atom,), fixed_atoms=(atom,), device="cpu",
        fallback_disabled=True, denoising_update_count=0, final_fixed_coordinate_restoration=True,
    )
    trace_path = root / "trace.json"
    trace_path.write_text(trace.to_json())
    references = {name: {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                  for name, path in (("pdb", pdb), ("dat", dat), ("sampler_trace", trace_path))}
    failures = [] if passed else ["geometry"]
    provenance = {"validation_summary": {"passed": passed, "hard_gate_failures": failures},
                  "candidate": {"candidate_id": "ranked-first", "seed": 11,
                                "generated_atoms": [{"chain": "d", "residue_number": "82", "insertion_code": "A", "atom_name": "CA"}],
                                "coordinate_artifact": references["pdb"], "sampler_trace_artifact": references["sampler_trace"]}}
    prov = root / "provenance.json"
    prov.write_text(json.dumps(provenance))
    references["provenance"] = {"path": prov.name, "sha256": hashlib.sha256(prov.read_bytes()).hexdigest()}
    (root / "bundle.json").write_text(json.dumps({
        "schema_version": 2, "status": "success" if passed else "validation_failed",
        "candidates": [{"candidate_id": "ranked-first", "seed": 11,
                        "validation_passed": passed, "hard_gate_failures": failures, **references}],
    }))


def test_handoff_keeps_bundle_immutable_and_full_residue_identity(tmp_path):
    bundle = tmp_path / "bundle"
    _bundle(bundle)
    before = {p.name: p.read_bytes() for p in bundle.iterdir()}
    destination = tmp_path / "model.pdb"
    copy_selected_candidate(bundle, destination)
    assert DatRecord.load(destination.with_suffix(".dat")).added_keys() == {("d", "82", "A", "CA")}
    assert {p.name: p.read_bytes() for p in bundle.iterdir()} == before
    copy_selected_candidate(bundle, destination, resume=True)
    destination.write_bytes(b"changed")
    with pytest.raises(PublicationError, match="already exists"):
        copy_selected_candidate(bundle, destination, resume=True)


def test_rejected_or_corrupt_publication_cannot_enter_pipeline(tmp_path):
    bundle = tmp_path / "bundle"
    _bundle(bundle, passed=False)
    with pytest.raises(PublicationError, match="validated candidate"):
        copy_selected_candidate(bundle, tmp_path / "model.pdb")
    (bundle / "ranked-first.pdb").write_bytes(b"changed")
    with pytest.raises(PublicationError, match="SHA-256"):
        read_published_bundle(bundle)
    assert not (tmp_path / "model.pdb").exists()


def test_batch_preflights_all_collisions_before_first_launch(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    (source / "same.pdb").write_text("END\n")
    (source / "same.cif").write_text("data_test\n")
    output = tmp_path / "output"
    calls = []
    with pytest.raises(SystemExit, match="colliding"):
        run_directory("model", calls.append, Namespace(input_dir=str(source), output_dir=str(output), recursive=False, fail_fast=False), ["--backend", "diffusion"])
    assert calls == []
    assert not output.exists()


def test_batch_scientific_rejection_and_fail_fast_report(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    for name in ("a", "b"):
        (source / f"{name}.pdb").write_text("END\n")
    output = tmp_path / "output"

    def model(args):
        _bundle(Path(args[args.index("-o") + 1]), passed=False)

    with pytest.raises(SystemExit):
        run_directory("model", model, Namespace(input_dir=str(source), output_dir=str(output), recursive=False, fail_fast=True), ["--backend", "diffusion", "--diffusion-seed", "11"])
    report = json.loads((output / "diffusion-batch.json").read_text())
    assert [r["status"] for r in report["results"]] == ["validation_failed", "skipped"]
    assert report["seeds"] == [11]


def test_zbs_selects_validated_candidate_and_dat_before_prepare(tmp_path, monkeypatch):
    source = tmp_path / "source.pdb"
    source.write_bytes(b"END\n")
    final = tmp_path / "result.pdb"
    calls = []

    def model(args):
        assert "--backend" in args and args[args.index("--backend") + 1] == "diffusion"
        assert "--md-level" not in args
        _bundle(Path(args[args.index("-o") + 1]))

    def prepare(args):
        input_path = Path(args[0])
        assert DatRecord.load(input_path.with_suffix(".dat")).added_keys() == {("d", "82", "A", "CA")}
        calls.append(input_path)
        Path(args[args.index("-o") + 1]).write_bytes(input_path.read_bytes())

    monkeypatch.setattr("dvbfixer.model.main", model)
    monkeypatch.setattr("dvbfixer.prepare.main", prepare)
    zbs_main([str(source), "-o", str(final), "--model-backend", "diffusion",
              "--skip-renumber", "--skip-minimize", "--no-postflight", "--no-align-to-input", "--no-solvent"])
    assert len(calls) == 1 and final.exists()
    assert (tmp_path / "source_model_diffusion/bundle.json").exists()


def test_standalone_prepare_keeps_original_dat_after_input_preprocessing(tmp_path, monkeypatch):
    from openmm.app import PDBFile

    from dvbfixer.prepare import pipeline

    original = tmp_path / "model.pdb"
    original.write_text("ATOM      1  CA  ALA d  82A      1.000   2.000   3.000  1.00  0.00           C  \nTER\nEND\n")
    DatRecord(added_atoms=[{
        "chain": "d", "resid": "82", "icode": "A", "resname": "ALA", "atom": "CA", "element": "C",
    }]).save(original.with_suffix(".dat"), verbose=False)
    rewritten = tmp_path / "model_inferred.pdb"
    rewritten.write_bytes(original.read_bytes())
    monkeypatch.setattr("dvbfixer.pdbutils._materialise_inferred_pdb", lambda *_args, **_kwargs: rewritten)

    def fix(input_path, *_args, **_kwargs):
        assert input_path == rewritten
        return PDBFile(str(input_path)), set(), {}

    monkeypatch.setattr(pipeline, "run_pdbfixer", fix)
    destination = tmp_path / "prepared.pdb"
    pipeline.main([str(original), "-o", str(destination), "--ff", "amber", "--atom-naming", "standard",
                   "--no-propka", "--no-protassign", "--no-heterogen-h"])
    assert DatRecord.load(destination.with_suffix(".dat")).added_keys() == {("d", "82", "A", "CA")}
