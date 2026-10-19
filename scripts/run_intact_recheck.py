#!/usr/bin/env python3
"""Run and audit intact-source reconstruction without reference-RMSD selection."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from analyze_a100_calibration import equivalent_validation
from analyze_a100_failures import findings
from analyze_a100_relaxation import outside_records
from audit_intact_inputs import audit as audit_inputs
from run_a100_relaxation import check_cuda_runtime, runtime_environment, sha, verify_inventory
from run_protein_context_ablations import _load

from dvbfixer.model.diffusion.contract import DiffusionRequest, RunnerResult, SamplerTrace
from dvbfixer.model.diffusion.runner_refinement import refine_runner_result
from dvbfixer.model.diffusion.sampler import SamplingAblationMode
from dvbfixer.model.diffusion.validate import _load_structure, validate_runner_result

ROOT = Path(__file__).resolve().parents[1]


def inference_worker(args):
    root = args.workspace
    production = _load("intact_production", ROOT / "deploy/protenix-v1/production_runner.py")
    production._verify_checkpoint(args.checkpoint)
    production._verify_profile_environment()
    _load("reinjection", ROOT / "deploy/protenix-v1/reinjection.py")
    builder = _load("intact_builder", ROOT / "deploy/protenix-v1/build-template-input.py")
    adapter = _load("intact_adapter", ROOT / "deploy/protenix-v1/checkpoint_gap_smoke.py")
    features = builder.build_input(root / "request.json", root / "engine-features")
    result, _ = adapter.run(root / "request.json", features, root / "raw", args.kalign, args.checkpoint,
        cycles=1, steps=200, ablation_mode=SamplingAblationMode.REINJECTION)
    (root / "runner-result.json").write_text(result.to_json())


def relaxation_worker(args):
    root = args.workspace
    request = DiffusionRequest.from_json((root / "request.json").read_text())
    raw = RunnerResult.from_json((root / "runner-result.json").read_text())
    before = validate_runner_result(request, raw, workspace=root)[0].summary
    start = time.perf_counter()
    selected = refine_runner_result(root / "request.json", raw, root / "relaxed", platform_name="CUDA")
    elapsed = time.perf_counter() - start
    after = validate_runner_result(request, selected, workspace=root)[0].summary
    (root / "relaxed-runner-result.json").write_text(selected.to_json())
    (root / "outcome.json").write_text(json.dumps({"status": "evaluated", "raw_validation": asdict(before),
        "relaxed_validation": asdict(after), "refinement_wall_seconds": elapsed,
        "postprocessing_failures": selected.candidates[0].postprocessing_failures}, indent=2, sort_keys=True) + "\n")


def protocol(args, manifest):
    paths = ("scripts/run_intact_recheck.py", "scripts/audit_intact_inputs.py", "src/dvbfixer/model/diffusion/protein_context.py",
        "src/dvbfixer/model/diffusion/scope.py", "src/dvbfixer/model/diffusion/boundary_refinement.py",
        "src/dvbfixer/model/diffusion/runner_refinement.py", "deploy/protenix-v1/build-template-input.py",
        "deploy/protenix-v1/checkpoint_gap_smoke.py", "deploy/protenix-v1/reinjection.py")
    frozen = {"status": "frozen-before-intact-recheck-inference", "cohort_sha256": sha(args.manifest),
        "code_sha256": {relative: sha(ROOT / relative) for relative in paths}, "environment": runtime_environment(),
        "input_audit_sha256": sha(args.cohort / "input-audit.json"), "solvent": False, "no_replacement": True,
        "source_count": len(manifest["screening"]), "eligible_case_count": len(manifest["cases"]),
        "unsupported_case_count": len(manifest["excluded_cases"]), "context": "6/10A heavy-atom anchor shells, all source chains, sequence padding2, no source truncation",
        "inference": "pinned Protenix CUDA, seed7, 200 per-step reinjections", "refinement": "existing rigid v6 CUDA generated-only, unchanged iteration/restart policy",
        "evaluation": "geometry and full-source preservation; no reference RMSD ranking or selection", "public_promotion": False}
    if args.protocol.exists():
        if json.loads(args.protocol.read_text()) != frozen:
            raise ValueError("intact protocol changed since freeze")
    else:
        args.protocol.write_text(json.dumps(frozen, indent=2, sort_keys=True) + "\n")


def summarize(rows):
    evaluated = [row for row in rows if row["status"] == "evaluated"]
    return {"case_count": len(rows), "evaluated": len(evaluated), "execution_errors": len(rows) - len(evaluated),
        "source_count": len({row["source_id"] for row in rows}),
        "raw_accepted": sum(row["raw_validation"]["passed"] for row in evaluated),
        "relaxed_accepted": sum(row["relaxed_validation"]["passed"] for row in evaluated),
        "fail_to_pass": sum(not row["raw_validation"]["passed"] and row["relaxed_validation"]["passed"] for row in evaluated),
        "pass_to_fail": sum(row["raw_validation"]["passed"] and not row["relaxed_validation"]["passed"] for row in evaluated),
        "raw_gate_counts": dict(Counter(gate for row in evaluated for gate in row["raw_validation"]["hard_gate_failures"])),
        "relaxed_gate_counts": dict(Counter(gate for row in evaluated for gate in row["relaxed_validation"]["hard_gate_failures"]))}


def run(args):
    manifest = json.loads(args.manifest.read_text())
    verify_inventory(ROOT, manifest["code_sha256"])
    inputs = audit_inputs(args.manifest, args.cohort, args.visual)
    if not inputs["all_intact_input_checks_passed"]:
        raise ValueError("intact source coverage failed")
    check_cuda_runtime()
    protocol(args, manifest)
    args.output.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "LAYERNORM_TYPE": "torch",
        "PYTHONPATH": os.pathsep.join((str(ROOT / ".artifacts/protenix-v1-acceptance-source"), str(ROOT / "src"), str(ROOT / "scripts"))),
        "PROTENIX_ROOT_DIR": str(ROOT / ".artifacts/protenix-v1-acceptance-source"), "PATH": str(args.kalign.parent) + os.pathsep + os.environ.get("PATH", "")}
    rows = []
    for case in manifest["cases"]:
        source = args.cohort / "cases" / case["case_id"]
        verify_inventory(source, case["artifacts"])
        destination = args.output / case["case_id"]
        if destination.exists():
            marker = json.loads((destination / "complete.json").read_text())
            if marker["protocol_sha256"] != sha(args.protocol):
                raise ValueError("intact result belongs to another protocol")
            verify_inventory(destination, marker["artifacts"])
            outcome = json.loads((destination / "outcome.json").read_text())
        else:
            with tempfile.TemporaryDirectory(prefix="intact-recheck-", dir=args.work_parent) as directory:
                workspace = Path(directory)
                shutil.copytree(source, workspace, dirs_exist_ok=True)
                phase = "inference"
                try:
                    with (workspace / "inference-worker.log").open("x") as log:
                        subprocess.run([str(ROOT / "test/protenix-env/bin/python"), str(Path(__file__).resolve()), "inference-worker",
                            "--workspace", str(workspace), "--checkpoint", str(args.checkpoint), "--kalign", str(args.kalign)],
                            env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=3600)
                    phase = "relaxation"
                    with (workspace / "relaxation-worker.log").open("x") as log:
                        subprocess.run([sys.executable, str(Path(__file__).resolve()), "relaxation-worker", "--workspace", str(workspace)],
                            env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "OPENMM_CPU_THREADS": "1"},
                            stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
                    outcome = json.loads((workspace / "outcome.json").read_text())
                except (subprocess.SubprocessError, OSError) as exc:
                    outcome = {"status": "execution-error", "failure_phase": phase, "message": str(exc)}
                    (workspace / "outcome.json").write_text(json.dumps(outcome, indent=2) + "\n")
                shutil.copytree(workspace, destination)
                marker = {"protocol_sha256": sha(args.protocol), "artifacts": {path.relative_to(destination).as_posix(): sha(path)
                    for path in destination.rglob("*") if path.is_file()}}
                (destination / "complete.json").write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n")
        view = args.visual / case["visual_directory"]
        for result_name, output_name in (("runner-result.json", "04_restored_raw.pdb"), ("relaxed-runner-result.json", "03_restored_relaxed.pdb")):
            if (destination / result_name).exists():
                result = RunnerResult.from_json((destination / result_name).read_text())
                artifact = result.candidates[0].coordinate_artifact
                if sha(destination / artifact.path) != artifact.sha256:
                    raise ValueError("intact result digest changed before visual export")
                shutil.copyfile(destination / artifact.path, view / output_name)
        row = {**{key: case[key] for key in ("case_id", "source_id", "length", "full_source_residue_count", "engine_context_residue_count", "original_geometry_passed")}, **outcome}
        rows.append(row)
        (view / "result.json").write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"case_id": case["case_id"], "status": outcome["status"], "relaxed_passed": outcome.get("relaxed_validation", {}).get("passed", False)}), flush=True)
        (args.output / "progress.json").write_text(json.dumps({"protocol_sha256": sha(args.protocol), "records": rows}, indent=2) + "\n")
    for row in rows:
        root = args.output / row["case_id"]
        verify_inventory(root, json.loads((root / "complete.json").read_text())["artifacts"])
        if row["status"] != "evaluated":
            continue
        request = DiffusionRequest.from_json((root / "request.json").read_text())
        generated = {(residue.chain, residue.residue_number, residue.insertion_code) for gap in request.gaps for residue in gap.generated_residues}
        original_outside = outside_records((root / "reference.pdb").read_text(), generated)
        for result_name, expected_name in (("runner-result.json", "raw_validation"), ("relaxed-runner-result.json", "relaxed_validation")):
            result = RunnerResult.from_json((root / result_name).read_text())
            validation = validate_runner_result(request, result, workspace=root)[0].summary
            if not equivalent_validation(validation, row[expected_name]):
                raise ValueError("intact outcome differs from independent validation")
            candidate = result.candidates[0]
            if outside_records((root / candidate.coordinate_artifact.path).read_text(), generated) != original_outside:
                raise ValueError("intact reconstruction changed an original background atom record")
            if result_name == "runner-result.json":
                trace = SamplerTrace.from_json((root / candidate.sampler_trace_artifact.path).read_text())
                if trace.callback_update_count != 200 or trace.denoising_update_count != 200 or trace.max_projection_error_angstrom != 0:
                    raise ValueError("intact sampler reinjection trace is incomplete")
            elif not validation.passed:
                row["relaxed_findings"] = findings(_load_structure(root, candidate.coordinate_artifact.path, candidate.coordinate_artifact.sha256), request)
        row["full_original_background_atom_records_preserved"] = True
    report = {"complete": True, "protocol_sha256": sha(args.protocol), "manifest_sha256": sha(args.manifest),
        "input_audit": {key: value for key, value in inputs.items() if key != "cases"},
        "all": summarize(rows), "by_source": {source: summarize([row for row in rows if row["source_id"] == source]) for source in sorted({row["source_id"] for row in rows})},
        "by_length": {str(length): summarize([row for row in rows if row["length"] == length]) for length in sorted({row["length"] for row in rows})},
        "cases": rows, "excluded_cases": manifest["excluded_cases"], "reference_rmsd_used": False, "public_promotion": False}
    (args.output / "analysis.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (args.visual / "results.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    checksums = [f"{sha(path)}  {path.relative_to(args.visual).as_posix()}\n" for path in sorted(args.visual.rglob("*")) if path.is_file() and path.name != "CHECKSUMS.sha256"]
    (args.visual / "CHECKSUMS.sha256").write_text("".join(checksums))
    print(json.dumps(report["all"], indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    execution = commands.add_parser("run")
    for name in ("manifest", "cohort", "visual", "output", "protocol", "work-parent", "checkpoint", "kalign"):
        execution.add_argument("--" + name, type=Path, required=True)
    inference = commands.add_parser("inference-worker")
    for name in ("workspace", "checkpoint", "kalign"):
        inference.add_argument("--" + name, type=Path, required=True)
    relaxation = commands.add_parser("relaxation-worker")
    relaxation.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    {"run": run, "inference-worker": inference_worker, "relaxation-worker": relaxation_worker}[args.action](args)


if __name__ == "__main__":
    main()
