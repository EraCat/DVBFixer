#!/usr/bin/env python3
"""Freeze and run paired, solvent-free local refinement of all raw A100 outputs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import openmm

from dvbfixer.model.diffusion import boundary_refinement as boundary
from dvbfixer.model.diffusion.benchmark import candidate_quality, load_pdb_coordinates
from dvbfixer.model.diffusion.contract import ArtifactReference, DiffusionRequest, RunnerResult
from dvbfixer.model.diffusion.runner_refinement import refine_runner_result
from dvbfixer.model.diffusion.validate import validate_runner_result

ROOT = Path(__file__).resolve().parents[1]
CODE = ("scripts/run_a100_relaxation.py", "src/dvbfixer/model/diffusion/boundary_refinement.py",
        "src/dvbfixer/model/diffusion/runner_refinement.py", "src/dvbfixer/model/diffusion/validate.py",
        "src/dvbfixer/ffutils/geometry.py")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inventory(root, inventory):
    for relative, digest in inventory.items():
        if sha(root / relative) != digest:
            raise ValueError(f"frozen artifact changed: {root / relative}")


def runtime_environment():
    packages = ("openmm-cuda-12", "nvidia-cuda-nvrtc-cu12", "nvidia-cuda-runtime-cu12", "nvidia-cuda-nvcc-cu12",
                "nvidia-cuda-cupti-cu12", "nvidia-cufft-cu12", "nvidia-nvjitlink-cu12")
    versions = {}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return {"openmm": openmm.__version__, "numpy": np.__version__, "python": sys.version.split()[0],
        "python_executable": sys.executable, "cuda_packages": versions}


def check_cuda_runtime():
    """Compile and execute an actual force kernel before starting a queue."""
    system = openmm.System()
    system.addParticle(12)
    force = openmm.CustomExternalForce("x*x+y*y+z*z")
    force.addParticle(0, [])
    system.addForce(force)
    integrator = openmm.VerletIntegrator(0.001)
    context = openmm.Context(system, integrator, openmm.Platform.getPlatformByName("CUDA"),
        {"Precision": "mixed", "DeterministicForces": "true"})
    context.setPositions([[1, 1, 1]])
    energy = context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(openmm.unit.kilojoule_per_mole)
    if not np.isclose(energy, 3):
        raise ValueError("CUDA preflight produced an unexpected force energy")


def freeze(args):
    if args.manifest.exists():
        raise ValueError("relaxation protocol must be new")
    raw = json.loads(args.raw_manifest.read_text())
    cases = []
    for case in raw["cases"]:
        for arm in case["arms"]:
            root = args.raw / case["case_id"] / arm
            marker = json.loads((root / "complete.json").read_text())
            if marker["manifest_sha256"] != sha(args.raw_manifest):
                raise ValueError("raw outcome belongs to another manifest")
            verify_inventory(root, marker["artifacts"])
            cases.append({"case_id": case["case_id"], "arm": arm, "source_id": case["source_id"],
                "length": case["length"], "split": case["split"], "raw_complete_sha256": sha(root / "complete.json"),
                "raw_passed": json.loads((root / "outcome.json").read_text())["validation"]["passed"]})
    manifest = {"status": "frozen-before-paired-relaxation", "raw_manifest_sha256": sha(args.raw_manifest),
        "raw_failure_analysis_sha256": sha(args.raw / "failure-analysis.json"),
        "cases": cases, "no_replacement": True, "include_raw_accepted": True,
        "code_sha256": {relative: sha(ROOT / relative) for relative in CODE},
        "environment": runtime_environment(),
        "supersedes_environment_failed_protocol_sha256": sha(args.supersedes_manifest) if getattr(args, "supersedes_manifest", None) else None,
        "protocol": {"revision": boundary.BOUNDARY_REFINEMENT_REVISION, "platform": "CUDA", "solvent": False,
            "mobile": "generated residues only; all outside atoms including anchors have mass zero",
            "reference_usage": "offline scoring only; never minimization or restart selection",
            "forcefield": boundary.BOUNDARY_REFINEMENT_FORCEFIELD,
            "max_iterations_short_le_5": 500, "max_iterations_other": boundary.BOUNDARY_REFINEMENT_MAX_ITERATIONS,
            "restart_count": boundary.BOUNDARY_REFINEMENT_RESTART_COUNT,
            "perturbation_angstrom_short_le_5": 0.25, "perturbation_angstrom_other": boundary.BOUNDARY_REFINEMENT_PERTURBATION_ANGSTROM,
            "tolerance_kj_mol_nm": boundary.BOUNDARY_REFINEMENT_TOLERANCE_KJ_MOL_NM,
            "extra_forces": "chirality wall; trans-amide omega; peptide angles",
            "constraints": "generated intra-residue heavy bonds at input lengths; inter-residue C-N unconstrained",
            "selection": "existing v6 local geometry error count, then energy; not reference RMSD",
            "on_refinement_failure": "retain raw candidate as explicitly failed; no resampling or replacement",
            "timeout_seconds": 1800}, "promotion": False, "validation_policy_changed": False}
    check_cuda_runtime()
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"outcomes": len(cases), "manifest_sha256": sha(args.manifest)}, indent=2))


def quality(root, request, result, validation):
    reference = ArtifactReference("reference.pdb", sha(root / "reference.pdb"))
    candidate = result.candidates[0]
    return asdict(candidate_quality(candidate.candidate_id, load_pdb_coordinates(root, reference),
        load_pdb_coordinates(root, candidate.coordinate_artifact),
        generated_residues={residue for gap in request.gaps for residue in gap.generated_residues}, fixed_atoms=set(request.fixed_atoms),
        anchor_residues={anchor for gap in request.gaps for anchor in (gap.left_anchor, gap.right_anchor) if anchor},
        closure_passed="junction-peptide-connectivity" not in validation.hard_gate_failures,
        validation_passed=validation.passed, expected_generated_atoms=set(request.generated_atoms),
        interface_chain_pairs=tuple((request.gaps[0].chain, target.chain) for target in request.target_sequences if target.chain != request.gaps[0].chain)))


def worker(args):
    root = args.workspace
    request = DiffusionRequest.from_json((root / "request.json").read_text())
    raw = RunnerResult.from_json((root / "runner-result.json").read_text())
    before = validate_runner_result(request, raw, workspace=root)[0].summary
    start = time.perf_counter()
    result = refine_runner_result(root / "request.json", raw, root / "relaxed", platform_name="CUDA")
    elapsed = time.perf_counter() - start
    after = validate_runner_result(request, result, workspace=root)[0].summary
    (root / "relaxed-runner-result.json").write_text(result.to_json())
    outcome = {"status": "evaluated", "raw_validation": asdict(before), "relaxed_validation": asdict(after),
        "raw_quality": quality(root, request, raw, before), "relaxed_quality": quality(root, request, result, after),
        "refinement_wall_time_seconds": elapsed, "postprocessing_failures": result.candidates[0].postprocessing_failures}
    (root / "relaxation.json").write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n")


def run(args):
    manifest = json.loads(args.manifest.read_text())
    if manifest["status"] != "frozen-before-paired-relaxation" or not manifest["no_replacement"]:
        raise ValueError("unfrozen relaxation protocol")
    verify_inventory(ROOT, manifest["code_sha256"])
    current = runtime_environment()
    if current != manifest["environment"]:
        raise ValueError("relaxation environment differs from freeze")
    check_cuda_runtime()
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for case in manifest["cases"]:
        source = args.raw / case["case_id"] / case["arm"]
        if sha(source / "complete.json") != case["raw_complete_sha256"]:
            raise ValueError("raw completion marker changed")
        marker = json.loads((source / "complete.json").read_text())
        verify_inventory(source, marker["artifacts"])
        destination = args.output / case["case_id"] / case["arm"]
        if destination.exists():
            completed = json.loads((destination / "complete.json").read_text())
            if completed["manifest_sha256"] != sha(args.manifest):
                raise ValueError("relaxation archive belongs to another protocol")
            verify_inventory(destination, completed["artifacts"])
            outcome = json.loads((destination / "relaxation.json").read_text())
        else:
            with tempfile.TemporaryDirectory(prefix="a100-relax-", dir=args.work_parent) as directory:
                workspace = Path(directory)
                shutil.copytree(source, workspace, dirs_exist_ok=True)
                (workspace / "complete.json").rename(workspace / "raw-complete.json")
                try:
                    environment = os.environ.copy()
                    environment.update(PYTHONPATH=str(ROOT / "src"), OPENMM_CPU_THREADS="1")
                    with (workspace / "relax-worker.log").open("x") as log:
                        subprocess.run([sys.executable, str(Path(__file__).resolve()), "worker", "--workspace", str(workspace)],
                            env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=manifest["protocol"]["timeout_seconds"])
                    outcome = json.loads((workspace / "relaxation.json").read_text())
                except (subprocess.SubprocessError, OSError) as exc:
                    outcome = {"status": "execution-error", "exception_type": type(exc).__name__, "message": str(exc)}
                    (workspace / "relaxation.json").write_text(json.dumps(outcome, indent=2) + "\n")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(workspace, destination)
                complete = {"manifest_sha256": sha(args.manifest), "raw_complete_sha256": case["raw_complete_sha256"],
                    "artifacts": {path.relative_to(destination).as_posix(): sha(path) for path in destination.rglob("*") if path.is_file()}}
                (destination / "complete.json").write_text(json.dumps(complete, indent=2, sort_keys=True) + "\n")
        row = {**case, "status": outcome["status"], "raw_passed": outcome.get("raw_validation", {}).get("passed", case["raw_passed"]),
            "relaxed_passed": outcome.get("relaxed_validation", {}).get("passed", False)}
        records.append(row)
        print(json.dumps(row), flush=True)
        (args.output / "progress.json").write_text(json.dumps({"manifest_sha256": sha(args.manifest), "records": records}, indent=2) + "\n")
    (args.output / "report.json").write_text(json.dumps({"manifest_sha256": sha(args.manifest), "records": records}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    prep = commands.add_parser("freeze")
    prep.add_argument("--raw-manifest", required=True, type=Path)
    prep.add_argument("--supersedes-manifest", type=Path)
    execution = commands.add_parser("run")
    for command in (prep, execution):
        command.add_argument("--raw", required=True, type=Path)
        command.add_argument("--manifest", required=True, type=Path)
    execution.add_argument("--output", required=True, type=Path)
    execution.add_argument("--work-parent", required=True, type=Path)
    invocation = commands.add_parser("worker")
    invocation.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    {"freeze": freeze, "run": run, "worker": worker}[args.action](args)


if __name__ == "__main__":
    main()
