#!/usr/bin/env python3
"""Run frozen public Homology diffusion and identical-plan MODELLER comparisons."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

from run_protein_context_ablations import diagnostic_workspace

from dvbfixer.homology import AA3TO1
from dvbfixer.model.diffusion.benchmark import (
    DiffusionBenchmarkError,
    candidate_quality,
    load_pdb_coordinates,
)
from dvbfixer.model.diffusion.context_metrics import measure_gap_environment
from dvbfixer.model.diffusion.contract import ArtifactReference, DiffusionRequest
from dvbfixer.model.diffusion.publication import read_published_bundle
from dvbfixer.model.diffusion.validate import (
    ValidationThresholds,
    _load_structure,
    _validate_candidate,
)

ROOT = Path(__file__).resolve().parents[1]


def normalize_comparator_ids(source: Path, destination: Path, request: DiffusionRequest) -> list[dict]:
    """Normalize only the comparator copy after exact full-sequence verification.

    MODELLER numbers its second segment after the first. The mosaic numbers each
    chain independently. Keep the original result and disclose the bijection.
    """
    lines = source.read_text().splitlines(keepends=True)
    by_chain = {}
    for line in lines:
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        key = (line[21], line[22:26].strip(), line[26].strip())
        residues = by_chain.setdefault(line[21], {})
        residues.setdefault(key, line[17:20].strip())
    mapping = {}
    for target in request.target_sequences:
        residues = by_chain.get(target.chain, {})
        if "".join(AA3TO1.get(name, "?") for name in residues.values()) != target.sequence:
            raise ValueError("MODELLER comparator does not reproduce the complete declared target sequence")
        for index, key in enumerate(residues, 1):
            mapping[key] = str(index)
    rewritten = []
    for line in lines:
        if line.startswith(("ATOM  ", "HETATM", "ANISOU", "TER   ")) and len(line) >= 27:
            key = (line[21], line[22:26].strip(), line[26].strip())
            if key in mapping:
                line = line[:22] + f"{int(mapping[key]):4d} " + line[27:]
        if not line.endswith("\n"):
            line += "\n"
        rewritten.append(line)
    destination.write_text("".join(rewritten))
    return [{"chain": key[0], "original_residue_number": key[1], "original_insertion_code": key[2],
             "comparator_residue_number": value} for key, value in mapping.items()]


def reanalyze(args):
    """Recompute derived comparator data without resampling or changing originals."""
    manifest = json.loads(args.manifest.read_text())
    digest = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    records = []
    for case in manifest["cases"]:
        root = args.output / case["case_id"]
        marker = json.loads((root / "complete.json").read_text())
        if marker["manifest_sha256"] != digest:
            raise ValueError("completed Homology manifest changed")
        for relative, expected in marker["artifacts"].items():
            if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
                raise ValueError("completed Homology artifact changed")
        source = args.cohort / case["case_id"]
        request = DiffusionRequest.from_json((source / "context-request.json").read_text())
        row = json.loads((root / "outcome.json").read_text())
        if row.get("analysis_version") != 2:
            (root / "outcome-before-comparator-newline-fix.json").write_bytes((root / "outcome.json").read_bytes())
        baseline = root / "modeller_comparator.pdb"
        row["modeller_identity_mapping"] = normalize_comparator_ids(root / "modeller_homology.pdb", baseline, request)
        summary, _ = _validate_candidate(request,
            _load_structure(source / "materialized", request.normalized_pdb.path, request.normalized_pdb.sha256),
            _load_structure(root, baseline.name, hashlib.sha256(baseline.read_bytes()).hexdigest()), ValidationThresholds())
        row["modeller_validation"] = asdict(summary)
        read_published_bundle(root / "diffusion_homology_diffusion", request=request, source_root=source / "materialized", work_parent=args.work_parent)
        reference_path = source / "reference-materialized/selected_template_mosaic.pdb"
        if reference_path.exists():
            reference = load_pdb_coordinates(reference_path.parent, ArtifactReference(reference_path.name, hashlib.sha256(reference_path.read_bytes()).hexdigest()))
            coordinates = load_pdb_coordinates(root, ArtifactReference(baseline.name, hashlib.sha256(baseline.read_bytes()).hexdigest()))
            row["modeller_quality"] = asdict(candidate_quality("modeller", reference, coordinates,
                generated_residues={residue for gap in request.gaps for residue in gap.generated_residues}, fixed_atoms=set(request.fixed_atoms),
                anchor_residues={anchor for gap in request.gaps for anchor in (gap.left_anchor, gap.right_anchor) if anchor},
                closure_passed="junction-peptide-connectivity" not in summary.hard_gate_failures, validation_passed=summary.passed,
                expected_generated_atoms=set(request.generated_atoms)))
            row["modeller_gap_environment"] = [asdict(metric) for metric in measure_gap_environment(request, reference, coordinates)]
            row.pop("modeller_quality_undefined_reason", None)
            row.pop("modeller_fixed_atom_identities_missing", None)
        row["analysis_version"] = 2
        (root / "outcome.json").write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
        marker["artifacts"] = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in root.rglob("*") if path.is_file() and path != root / "complete.json"}
        (root / "complete.json").write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n")
        records.append(row)
    (args.output / "report.json").write_text(json.dumps({"manifest_sha256": digest, "cases": records}, indent=2, sort_keys=True) + "\n")
    print(json.dumps([{key: row[key] for key in ("case_id", "diffusion_status")} for row in records], indent=2))


def run(args):
    manifest = json.loads(args.manifest.read_text())
    if manifest["status"] != "frozen-before-homology-inference" or not manifest["no_replacement"]:
        raise ValueError("Homology acceptance requires a frozen no-replacement manifest")
    digest = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", "")
    for case in manifest["cases"]:
        destination = args.output / case["case_id"]
        if destination.exists():
            marker = json.loads((destination / "complete.json").read_text())
            if marker["manifest_sha256"] != digest:
                raise ValueError("Homology archive manifest changed")
            for name, expected in marker["artifacts"].items():
                if hashlib.sha256((destination / name).read_bytes()).hexdigest() != expected:
                    raise ValueError("Homology archive artifact changed")
            records.append(json.loads((destination / "outcome.json").read_text()))
            continue
        source = args.cohort / case["case_id"]
        for name, expected in case["artifacts"].items():
            if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
                raise ValueError("Homology frozen input changed")
        request = DiffusionRequest.from_json((source / "context-request.json").read_text())
        with diagnostic_workspace(args, case["case_id"], "homology") as workspace:
            recovered = sorted((args.output / "failures" / case["case_id"]).glob("homology-*/diffusion_homology_diffusion/bundle.json"))
            recovered_execution = False
            if recovered:
                # A scoring failure must not trigger a new scientific sample.
                # Verify the exact existing request and current policy first.
                archive = recovered[0].parent.parent
                read_published_bundle(archive / "diffusion_homology_diffusion", request=request,
                                      source_root=source / "materialized", work_parent=args.work_parent)
                for item in archive.iterdir():
                    if item.is_dir():
                        shutil.copytree(item, workspace / item.name)
                    elif item.name != "failure.json":
                        shutil.copyfile(item, workspace / item.name)
                recovered_execution = True
            common = [str(source / "target.fasta"), "--template-plan", str(source / "template-plan.json")]
            for backend in (() if recovered_execution else ("modeller", "diffusion")):
                prefix = workspace / backend
                command = [sys.executable, "-m", "dvbfixer.cli", "homology", *common, "-o", str(prefix), "--backend", backend]
                if backend == "diffusion":
                    command += ["--diffusion-model", "protenix", "--diffusion-context", "full", "--diffusion-work-parent", str(args.work_parent)]
                    if case["regenerate_covered"]:
                        command.append("--diffusion-regenerate-covered")
                else:
                    command += ["-n", "1", "--md-level", "none", "--no-loop-refine"]
                with (workspace / f"{backend}.log").open("xb") as log:
                    completed = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=3600)
                if completed.returncode and not (workspace / "diffusion_homology_diffusion/bundle.json").exists():
                    failure = args.output / f"{case['case_id']}-{backend}-failure-{uuid.uuid4().hex}"
                    shutil.copytree(workspace, failure)
                    raise RuntimeError(f"{backend} execution failed; diagnostics archived at {failure}")
            bundle = workspace / "diffusion_homology_diffusion"
            published = read_published_bundle(bundle, request=request, source_root=source / "materialized", work_parent=args.work_parent)
            selected = published.candidates[0]
            bundle_index = json.loads((bundle / "bundle.json").read_text())
            provenance_path = bundle / bundle_index["candidates"][0]["provenance"]["path"]
            diffusion_summary = json.loads(provenance_path.read_text())["validation_summary"]
            # MODELLER has no diffusion sampler trace and is explicitly an
            # unconstrained comparator. Report fixed drift, never disguise it.
            baseline = workspace / "modeller_comparator.pdb"
            comparator_mapping = normalize_comparator_ids(workspace / "modeller_homology.pdb", baseline, request)
            baseline_summary, _ranking = _validate_candidate(request,
                _load_structure(source / "materialized", request.normalized_pdb.path, request.normalized_pdb.sha256),
                _load_structure(workspace, baseline.name, hashlib.sha256(baseline.read_bytes()).hexdigest()), ValidationThresholds())
            row = {"case_id": case["case_id"], "diffusion_status": published.status,
                   "analysis_version": 2,
                   "recovered_verified_execution_after_scoring_failure": recovered_execution,
                   "diffusion_validation": diffusion_summary,
                   "modeller_comparator_policy": "unconstrained-scaffold-report-full-validation-no-sampler-claim",
                   "modeller_identity_mapping": comparator_mapping,
                   "modeller_validation": asdict(baseline_summary),
                   "regenerated_template_residue_count": len(request.regenerated_template_ownership or ()),
                   "gap_count": len(request.gaps), "gap_chains": sorted({gap.chain for gap in request.gaps})}
            reference_path = source / "reference-materialized/selected_template_mosaic.pdb"
            if reference_path.exists():
                reference = load_pdb_coordinates(reference_path.parent, ArtifactReference(reference_path.name, hashlib.sha256(reference_path.read_bytes()).hexdigest()))
                for backend, candidate_path in (("modeller", baseline), ("diffusion", selected.pdb)):
                    coordinates = load_pdb_coordinates(candidate_path.parent, ArtifactReference(candidate_path.name, hashlib.sha256(candidate_path.read_bytes()).hexdigest()))
                    try:
                        row[backend + "_quality"] = asdict(candidate_quality(backend, reference, coordinates,
                            generated_residues={residue for gap in request.gaps for residue in gap.generated_residues},
                            fixed_atoms=set(request.fixed_atoms), anchor_residues={anchor for gap in request.gaps for anchor in (gap.left_anchor, gap.right_anchor) if anchor},
                            closure_passed="junction-peptide-connectivity" not in (baseline_summary.hard_gate_failures if backend == "modeller" else diffusion_summary["hard_gate_failures"]),
                            validation_passed=baseline_summary.passed if backend == "modeller" else published.status == "success",
                            expected_generated_atoms=set(request.generated_atoms)))
                    except DiffusionBenchmarkError as exc:
                        if backend != "modeller":
                            raise
                        row[backend + "_quality"] = None
                        row[backend + "_quality_undefined_reason"] = str(exc)
                        row[backend + "_fixed_atom_identities_missing"] = [asdict(atom) for atom in sorted(set(request.fixed_atoms) - coordinates.keys())]
                    row[backend + "_gap_environment"] = [asdict(metric) for metric in measure_gap_environment(request, reference, coordinates)]
            else:
                row["reference_quality_undefined_reason"] = "no-experimental-mutant-or-deletion-reference"
            (workspace / "outcome.json").write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
            shutil.copytree(workspace, destination)
            marker = {"manifest_sha256": digest, "artifacts": {
                path.relative_to(destination).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in destination.rglob("*") if path.is_file()}}
            (destination / "complete.json").write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n")
            records.append(row)
            print(json.dumps({key: row[key] for key in ("case_id", "diffusion_status")}), flush=True)
    (args.output / "report.json").write_text(json.dumps({"manifest_sha256": digest, "cases": records}, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "cohort", "output", "work-parent"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--reanalyze", action="store_true", help="Recompute verified completed comparator data without new models")
    args = parser.parse_args()
    for key, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, key, value.resolve())
    reanalyze(args) if args.reanalyze else run(args)


if __name__ == "__main__":
    main()
