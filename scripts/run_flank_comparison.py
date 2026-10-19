#!/usr/bin/env python3
"""Freeze, execute and audit a bounded-flank research comparison on old masks."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, replace
from pathlib import Path
from statistics import median

import numpy as np
from analyze_a100_relaxation import equivalent
from research_flank_refinement import FLANK_MAX_DISPLACEMENT_ANGSTROM, flank_atoms, refine
from run_a100_relaxation import (
    check_cuda_runtime,
    quality,
    runtime_environment,
    sha,
    verify_inventory,
)

from dvbfixer.model.diffusion.contract import ArtifactReference, DiffusionRequest, RunnerResult
from dvbfixer.model.diffusion.validate import (
    ValidationThresholds,
    _load_structure,
    _validate_candidate,
)

ROOT = Path(__file__).resolve().parents[1]


def choose_protocol(*, evaluated_count, total_count, rigid_passed, bounded_passed, regressions, median_rmsd_change):
    return "bounded-flank" if (evaluated_count == total_count and bounded_passed > rigid_passed
        and regressions == 0 and median_rmsd_change is not None and median_rmsd_change <= 0.10) else "rigid"


def evaluate(root, request, filename, *, allow_flanks=False):
    source = _load_structure(root, request.normalized_pdb.path, request.normalized_pdb.sha256)
    candidate = _load_structure(root, filename, sha(root / filename))
    selected = set(flank_atoms(request))
    active = replace(request, fixed_atoms=tuple(atom for atom in request.fixed_atoms if atom not in selected), protein_context=None) if allow_flanks else request
    summary = _validate_candidate(active, source, candidate, ValidationThresholds())[0]
    displacements = [float(np.linalg.norm(candidate.atoms[atom].coordinates_angstrom - source.atoms[atom].coordinates_angstrom)) for atom in selected]
    maximum = max(displacements, default=0)
    if allow_flanks and maximum > FLANK_MAX_DISPLACEMENT_ANGSTROM:
        summary = replace(summary, passed=False, hard_gate_failures=(*summary.hard_gate_failures, "research-flank-displacement-cap"))
    raw = RunnerResult.from_json((root / "runner-result.json").read_text())
    scored = replace(raw, candidates=(replace(raw.candidates[0], coordinate_artifact=ArtifactReference(filename, sha(root / filename))),))
    return {"validation": asdict(summary), "quality": quality(root, request, scored, summary),
        "flank_max_displacement_angstrom": maximum, "flank_rmsd_angstrom": float(np.sqrt(np.mean(np.square(displacements))))}


def freeze(args):
    if args.manifest.exists():
        raise ValueError("comparison protocol must be new")
    analysis = json.loads(args.rigid_analysis.read_text())
    if not analysis["complete"]:
        raise ValueError("rigid control must be fully audited")
    cases = []
    for row in analysis["cases"]:
        if row["arm"] not in {"static-local", "full-raw"}:
            continue
        raw = args.raw / row["case_id"] / row["arm"]
        rigid = args.rigid / row["case_id"] / row["arm"]
        for root in (raw, rigid):
            verify_inventory(root, json.loads((root / "complete.json").read_text())["artifacts"])
        result = RunnerResult.from_json((rigid / "relaxed-runner-result.json").read_text())
        cases.append({"case_id": row["case_id"], "source_id": row["source_id"], "length": row["length"], "arm": row["arm"],
            "raw_complete_sha256": sha(raw / "complete.json"), "rigid_complete_sha256": sha(rigid / "complete.json"),
            "rigid_candidate": asdict(result.candidates[0].coordinate_artifact), "rigid_passed": row["relaxed_passed"]})
    paths = ("scripts/run_flank_comparison.py", "scripts/research_flank_refinement.py", "scripts/run_a100_relaxation.py",
             "src/dvbfixer/model/diffusion/boundary_refinement.py", "src/dvbfixer/model/diffusion/validate.py")
    manifest = {"status": "frozen-before-flank-comparison", "cases": cases, "no_replacement": True,
        "rigid_analysis_sha256": sha(args.rigid_analysis), "environment": runtime_environment(),
        "supersedes_failed_adapter_manifest_sha256": sha(args.supersedes_manifest) if getattr(args, "supersedes_manifest", None) else None,
        "code_sha256": {relative: sha(ROOT / relative) for relative in paths},
        "protocol": {"platform": "CUDA", "solvent": False, "flanks": "one complete immediate anchor residue each side",
            "positional_k_kj_mol_nm2": 10000, "wall_k_kj_mol_nm2": 1000000, "wall_radius_angstrom": 0.25,
            "max_flank_displacement_angstrom": FLANK_MAX_DISPLACEMENT_ANGSTROM,
            "refinement": "v6 unchanged iteration/restart/perturbation settings; expanded mobile mask; private ForceField subclass adds flank restraints",
            "validation": "same geometry gates; protected atoms stay exact; explicit <=0.30A flank allowance; original strict validation reported separately",
            "timeout_seconds": 1800},
        "selection_rule": "choose bounded-flank only if more accepted cases, zero loss among rigid-accepted controls, no execution errors, and median paired original-gap backbone RMSD change <=0.10A; otherwise retain rigid",
        "development_scope": "all64 old mask/seed cases now development; original split no longer claimed untouched holdout",
        "promotion": False}
    check_cuda_runtime()
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"case_count": len(cases), "manifest_sha256": sha(args.manifest)}, indent=2))


def worker(args):
    root = args.workspace
    request = DiffusionRequest.from_json((root / "request.json").read_text())
    raw = RunnerResult.from_json((root / "runner-result.json").read_text())
    raw_text = (root / raw.candidates[0].coordinate_artifact.path).read_text()
    before = evaluate(root, request, "control-candidate.pdb")
    start = time.perf_counter()
    text = refine(raw_text, request)
    elapsed = time.perf_counter() - start
    (root / "flank-candidate.pdb").write_text(text, encoding="ascii")
    outcome = {"status": "evaluated", "rigid": before,
        "bounded_flank": evaluate(root, request, "flank-candidate.pdb", allow_flanks=True),
        "original_strict_flank": evaluate(root, request, "flank-candidate.pdb"), "refinement_wall_seconds": elapsed}
    (root / "comparison.json").write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n")


def run(args):
    manifest = json.loads(args.manifest.read_text())
    verify_inventory(ROOT, manifest["code_sha256"])
    if runtime_environment() != manifest["environment"] or manifest["status"] != "frozen-before-flank-comparison":
        raise ValueError("comparison environment/protocol changed")
    check_cuda_runtime()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in manifest["cases"]:
        source = args.raw / case["case_id"] / case["arm"]
        control = args.rigid / case["case_id"] / case["arm"]
        if sha(source / "complete.json") != case["raw_complete_sha256"] or sha(control / "complete.json") != case["rigid_complete_sha256"]:
            raise ValueError("paired control custody changed")
        verify_inventory(source, json.loads((source / "complete.json").read_text())["artifacts"])
        verify_inventory(control, json.loads((control / "complete.json").read_text())["artifacts"])
        destination = args.output / case["case_id"]
        if destination.exists():
            marker = json.loads((destination / "complete.json").read_text())
            if marker["manifest_sha256"] != sha(args.manifest):
                raise ValueError("comparison outcome belongs to another manifest")
            verify_inventory(destination, marker["artifacts"])
            outcome = json.loads((destination / "comparison.json").read_text())
        else:
            with tempfile.TemporaryDirectory(prefix="flank-research-", dir=args.work_parent) as directory:
                workspace = Path(directory)
                shutil.copytree(source, workspace, dirs_exist_ok=True)
                (workspace / "complete.json").rename(workspace / "raw-complete.json")
                artifact = case["rigid_candidate"]
                if sha(control / artifact["path"]) != artifact["sha256"]:
                    raise ValueError("rigid candidate digest changed")
                shutil.copyfile(control / artifact["path"], workspace / "control-candidate.pdb")
                try:
                    with (workspace / "flank-worker.log").open("x") as log:
                        subprocess.run([sys.executable, str(Path(__file__).resolve()), "worker", "--workspace", str(workspace)],
                            env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "OPENMM_CPU_THREADS": "1"},
                            stdout=log, stderr=subprocess.STDOUT, check=True, timeout=manifest["protocol"]["timeout_seconds"])
                    outcome = json.loads((workspace / "comparison.json").read_text())
                except (subprocess.SubprocessError, OSError) as exc:
                    outcome = {"status": "execution-error", "message": str(exc)}
                    (workspace / "comparison.json").write_text(json.dumps(outcome, indent=2) + "\n")
                shutil.copytree(workspace, destination)
                marker = {"manifest_sha256": sha(args.manifest), "artifacts": {path.relative_to(destination).as_posix(): sha(path) for path in destination.rglob("*") if path.is_file()}}
                (destination / "complete.json").write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n")
        rows.append({"case_id": case["case_id"], "status": outcome["status"], "bounded_flank_passed": outcome.get("bounded_flank", {}).get("validation", {}).get("passed", False)})
        print(json.dumps(rows[-1]), flush=True)
        (args.output / "progress.json").write_text(json.dumps({"records": rows}, indent=2) + "\n")
    (args.output / "report.json").write_text(json.dumps({"records": rows}, indent=2) + "\n")


def analyze(args):
    manifest = json.loads(args.manifest.read_text())
    rows = []
    for case in manifest["cases"]:
        root = (args.output / case["case_id"]).resolve()
        marker = json.loads((root / "complete.json").read_text())
        if marker["manifest_sha256"] != sha(args.manifest):
            raise ValueError("comparison manifest mismatch")
        verify_inventory(root, marker["artifacts"])
        if sha(root / "raw-complete.json") != case["raw_complete_sha256"]:
            raise ValueError("comparison raw custody changed")
        verify_inventory(root, json.loads((root / "raw-complete.json").read_text())["artifacts"])
        outcome = json.loads((root / "comparison.json").read_text())
        if outcome["status"] == "evaluated":
            request = DiffusionRequest.from_json((root / "request.json").read_text())
            for key, filename, allowed in (("rigid", "control-candidate.pdb", False), ("bounded_flank", "flank-candidate.pdb", True), ("original_strict_flank", "flank-candidate.pdb", False)):
                if not equivalent(evaluate(root, request, filename, allow_flanks=allowed), outcome[key]):
                    raise ValueError("comparison differs from independent coordinate audit")
            if sha(root / "control-candidate.pdb") != case["rigid_candidate"]["sha256"] or outcome["rigid"]["validation"]["passed"] != case["rigid_passed"]:
                raise ValueError("rigid control changed")
        rows.append({**case, **outcome})
    evaluated = [row for row in rows if row["status"] == "evaluated"]
    rigid_passed = sum(row["rigid_passed"] for row in rows)
    bounded_passed = sum(row["bounded_flank"]["validation"]["passed"] for row in evaluated)
    regressions = sum(row["rigid_passed"] and not row["bounded_flank"]["validation"]["passed"] for row in evaluated)
    deltas = [row["bounded_flank"]["quality"]["gap_backbone_rmsd_angstrom"] - row["rigid"]["quality"]["gap_backbone_rmsd_angstrom"] for row in evaluated]
    chosen = choose_protocol(evaluated_count=len(evaluated), total_count=len(rows), rigid_passed=rigid_passed,
        bounded_passed=bounded_passed, regressions=regressions, median_rmsd_change=median(deltas) if deltas else None)
    report = {"complete": True, "manifest_sha256": sha(args.manifest), "cases": rows, "summary": {"case_count": len(rows),
        "execution_errors": len(rows) - len(evaluated), "rigid_accepted": rigid_passed, "bounded_flank_accepted": bounded_passed,
        "rigid_pass_to_bounded_fail": regressions, "median_paired_backbone_rmsd_change_angstrom": median(deltas) if deltas else None,
        "maximum_flank_displacement_angstrom": max((row["bounded_flank"]["flank_max_displacement_angstrom"] for row in evaluated), default=None)},
        "selected_protocol": chosen, "selection_rule": manifest["selection_rule"], "public_promotion": False}
    (args.output / "analysis.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"summary": report["summary"], "selected_protocol": chosen}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    prep = commands.add_parser("freeze")
    prep.add_argument("--rigid-analysis", type=Path, required=True)
    prep.add_argument("--supersedes-manifest", type=Path)
    execution = commands.add_parser("run")
    audit = commands.add_parser("analyze")
    for command in (prep, execution):
        command.add_argument("--raw", type=Path, required=True)
        command.add_argument("--rigid", type=Path, required=True)
    for command in (prep, execution, audit):
        command.add_argument("--manifest", type=Path, required=True)
    for command in (execution, audit):
        command.add_argument("--output", type=Path, required=True)
    execution.add_argument("--work-parent", type=Path, required=True)
    invocation = commands.add_parser("worker")
    invocation.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    {"freeze": freeze, "run": run, "worker": worker, "analyze": analyze}[args.action](args)


if __name__ == "__main__":
    main()
