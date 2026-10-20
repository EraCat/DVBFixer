#!/usr/bin/env python3
"""Bounded staged execution of the frozen known-sequence structural holdout.

Sampling/minimization workspaces contain no withheld reference PDB. References
are attached by the parent only after the worker exits, for independent scoring.
Terminal failures are archived and never resampled on resume.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from analyze_modeller_benchmark import _aligned_coordinates, _baseline_failures

from dvbfixer.model.diffusion.benchmark import (
    DiffusionBenchmarkError,
    candidate_quality,
    load_pdb_coordinates,
)
from dvbfixer.model.diffusion.contract import (
    ArtifactReference,
    DiffusionRequest,
    RunnerResult,
)
from dvbfixer.model.diffusion.validate import (
    ValidationThresholds,
    _load_structure,
    _validate_candidate,
    validate_runner_result,
)

ROOT = Path(__file__).resolve().parents[1]
RAW_PYTHON = ROOT / "test/protpardelle-env/bin/python"
REFINE_PYTHON = ROOT / "test/a100-relax-env/bin/python"
CORE_PYTHON = Path(sys.executable)
ENGINE = ROOT / "test/protpardelle-1c-audit"
STAGES = ("raw", "refine", "modeller", "protenix")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_inventory(root, inventory):
    for relative, digest in inventory.items():
        if sha(root / relative) != digest:
            raise ValueError(f"frozen artifact changed: {relative}")


def environment(stage):
    result = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "OPENMM_CPU_THREADS": "1"}
    paths = [str(ROOT / "src"), str(ROOT / "scripts")]
    if stage == "raw":
        paths.append(str(ENGINE / "src"))
        result["PROTPARDELLE_MODEL_PARAMS"] = str(ENGINE / "model_params")
    result["PYTHONPATH"] = os.pathsep.join(paths)
    result["PATH"] = str(CORE_PYTHON.parent) + os.pathsep + result.get("PATH", "")
    return result


def freeze(args):
    if args.protocol.exists():
        raise ValueError("execution protocol must be new")
    manifest = json.loads(args.manifest.read_text())
    if manifest["status"] != "frozen-before-known-sequence-holdout-inference" or not manifest["no_replacement"]:
        raise ValueError("holdout source manifest is not frozen")
    for case in manifest["cases"]:
        verify_inventory(args.cohort / case["case_id"], case["artifacts"])
    code = ("scripts/run_cc89_known_sequence_holdout.py", "scripts/materialize_cc89_known_sequence_holdout.py",
        "scripts/run_context_homology_acceptance.py", "scripts/analyze_modeller_benchmark.py", "scripts/run_a100_relaxation.py",
        "src/dvbfixer/homology.py", "src/dvbfixer/homology_plan.py", "src/dvbfixer/model/diffusion/protein_context.py",
        "src/dvbfixer/model/diffusion/contract.py", "src/dvbfixer/model/diffusion/validate.py",
        "src/dvbfixer/model/diffusion/runner_refinement.py", "src/dvbfixer/model/diffusion/boundary_refinement.py",
        "src/dvbfixer/model/diffusion/pdb_materialize.py", "src/dvbfixer/model/diffusion/geometry.py",
        "src/dvbfixer/model/diffusion/benchmark.py", "src/dvbfixer/model/diffusion/reference_metrics.py",
        "src/dvbfixer/model/diffusion_cli.py", "src/dvbfixer/model/diffusion/pipeline.py",
        "src/dvbfixer/model/diffusion/publication.py", "src/dvbfixer/model/diffusion/runner.py",
        "deploy/protenix-v1/production_runner.py", "deploy/protenix-v1/profile-lock.json",
        "deploy/protpardelle-1c/checkpoint_gap_smoke.py",
        "test/protpardelle-1c-audit/src/protpardelle/core/models.py", "test/protpardelle-1c-audit/src/protpardelle/core/modules.py")
    jobs = {stage: [] for stage in STAGES}
    for case in manifest["cases"]:
        if case["status"] != "eligible":
            continue
        jobs["modeller"].append({"case_id": case["case_id"], "seed": 7})
        if case["case_id"] in manifest["public_protenix_workflow_controls"]:
            jobs["protenix"].append({"case_id": case["case_id"], "seed": 7})
        if case["cc89_eligible"]:
            for seed in manifest["seeds"]:
                for stage in ("raw", "refine"):
                    jobs[stage].append({"case_id": case["case_id"], "seed": seed})
    probes = {}
    for kind, python in (("raw", RAW_PYTHON), ("refine", REFINE_PYTHON)):
        completed = subprocess.run([str(python), str(Path(__file__).resolve()), "preflight-worker", "--kind", kind],
            env=environment(kind), capture_output=True, text=True, check=True, timeout=120)
        probes[kind] = json.loads(completed.stdout)
    protocol = {"status": "frozen-before-known-sequence-holdout-execution", "manifest_sha256": sha(args.manifest),
        "code_sha256": {name: sha(ROOT / name) for name in code}, "jobs": jobs, "environments": probes,
        "config_sha256": sha(ENGINE / "model_params/configs/cc89.yaml"),
        "checkpoint_sha256": sha(ENGINE / "model_params/weights/cc89_epoch415.pth"),
        "raw_parameters": {"steps": 500, "step_scale": 1.2, "s_churn": 200.0, "per_step_reinjection": False,
                           "chain_phase_policy": "neutral-v1"},
        "timeouts_seconds": {"raw": 600, "refine": 1800, "modeller": 1800, "protenix": 1950},
        "public_protenix_timeout_seconds": 1800, "solvent": False, "no_replacement": True,
        "selection": "report every seed independently; no reference-based candidate selection or outcome-based restart",
        "modeller": "one public homology automodel; --md-level none --no-loop-refine; default Modeller seed; unconstrained comparator",
        "comparison": "descriptive paired masks; unequal candidate budgets disclosed; no confirmatory noninferiority claim",
        "modeller_accuracy": "rigidly align on common observed backbone only; disclose missing fixed atoms and score fixed RMSD on the common subset; strict validation still reports all missing atoms and original movement",
        "supersedes_setup_protocol_sha256": sha(args.supersedes) if args.supersedes else None,
        "reference_policy": "withheld reference absent during raw sampling and CUDA minimization; attach after worker exit",
        "public_promotion": False, "apple_mps": "deferred"}
    with args.protocol.open("x") as stream:
        stream.write(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"jobs": {stage: len(rows) for stage, rows in jobs.items()}, "protocol_sha256": sha(args.protocol)}), flush=True)


def preflight(args):
    if args.kind == "raw":
        import torch

        if not torch.cuda.is_available() or torch.__version__ != "2.6.0+cu124":
            raise ValueError("pinned cc89 CUDA environment required")
        print(json.dumps({"torch": torch.__version__, "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0)}))
    else:
        from run_a100_relaxation import check_cuda_runtime, runtime_environment

        check_cuda_runtime()
        data = runtime_environment()
        data.pop("python_executable", None)
        print(json.dumps(data))


def worker(args):
    workspace = args.workspace
    if (workspace / "reference.pdb").exists():
        raise ValueError("withheld reference must not be present during execution")
    protocol = json.loads(args.protocol.read_text())
    if args.kind == "raw":
        from run_protein_context_ablations import _load

        adapter = _load("cc89_known_sequence_holdout", ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py")
        (workspace / "raw").mkdir()
        result, _ = adapter._run_staged(workspace / "request.json", workspace / "raw",
            ENGINE / "model_params/configs/cc89.yaml", ENGINE / "model_params/weights/cc89_epoch415.pth",
            device_name="cuda", mps_profile=False, **protocol["raw_parameters"])
        (workspace / "runner-result.json").write_text(result.to_json())
    elif args.kind == "refine":
        from dvbfixer.ffutils.geometry import ChiralityError
        from dvbfixer.model.diffusion.runner_refinement import refine_runner_result

        result = RunnerResult.from_json((workspace / "runner-result.json").read_text())
        try:
            refined = refine_runner_result(workspace / "request.json", result, workspace / "refined", platform_name="CUDA")
        except ChiralityError as exc:
            (workspace / "guarded-chirality.json").write_text(json.dumps({"message": str(exc)}) + "\n")
            raise
        (workspace / "refined-runner-result.json").write_text(refined.to_json())
    else:
        source = args.source
        prefix = workspace / args.kind
        command = [str(CORE_PYTHON), "-m", "dvbfixer.cli", "homology", str(source / "target.fasta"),
            "--template-plan", str(source / "template-plan.json"), "--backend", "modeller" if args.kind == "modeller" else "diffusion", "-o", str(prefix)]
        if args.kind == "modeller":
            command += ["-n", "1", "--md-level", "none", "--no-loop-refine"]
        else:
            command += ["--diffusion-model", "protenix", "--diffusion-context", "full", "--diffusion-seed", "7",
                "--diffusion-timeout", str(protocol["public_protenix_timeout_seconds"]), "--diffusion-work-parent", str(args.work_parent)]
        subprocess.run(command, env=environment(args.kind), check=True, cwd=ROOT)
        if args.kind == "protenix":
            from dvbfixer.model.diffusion.publication import read_published_bundle

            request = DiffusionRequest.from_json((source / "requests/protenix-seed7.json").read_text())
            published = read_published_bundle(workspace / "protenix_homology_diffusion", request=request,
                source_root=source / "protenix-materialized", work_parent=args.work_parent)
            (workspace / "publication.json").write_text(json.dumps({"status": published.status,
                "candidate": published.candidates[0].pdb.relative_to(workspace).as_posix()}) + "\n")


def evaluate(workspace, request, candidate, *, summary=None, comparator=False):
    if summary is None:
        summary, _ = _validate_candidate(request, _load_structure(workspace, request.normalized_pdb.path, request.normalized_pdb.sha256),
            _load_structure(workspace, candidate, sha(workspace / candidate)), ValidationThresholds())
    gap_chains = {g.chain for g in request.gaps}
    coordinates = load_pdb_coordinates(workspace, ArtifactReference(candidate, sha(workspace / candidate)))
    missing_fixed = set(request.fixed_atoms) - coordinates.keys()
    scoring_fixed = set(request.fixed_atoms)
    if comparator:
        coordinates = _aligned_coordinates(request, load_pdb_coordinates(workspace, request.normalized_pdb), coordinates)
        scoring_fixed &= coordinates.keys()
    data = {"candidate": {"path": candidate, "sha256": sha(workspace / candidate)}, "validation": asdict(summary),
        "coordinate_alignment": "common-observed-backbone" if comparator else "unchanged-source-frame",
        "quality_fixed_atom_scope": "common-fixed-atoms" if comparator and missing_fixed else "all-requested-fixed-atoms",
        "missing_fixed_atom_identities": [asdict(atom) for atom in sorted(missing_fixed)]}
    try:
        quality = candidate_quality("modeller" if comparator else "holdout", load_pdb_coordinates(workspace, ArtifactReference("reference.pdb", sha(workspace / "reference.pdb"))),
            coordinates, generated_residues={r for gap in request.gaps for r in gap.generated_residues}, fixed_atoms=scoring_fixed,
            anchor_residues={r for gap in request.gaps for r in (gap.left_anchor, gap.right_anchor) if r},
            closure_passed="junction-peptide-connectivity" not in summary.hard_gate_failures, validation_passed=summary.passed,
            expected_generated_atoms=set(request.generated_atoms),
            interface_chain_pairs=tuple((chain, target.chain) for chain in sorted(gap_chains) for target in request.target_sequences if target.chain not in gap_chains))
        data["quality"] = asdict(quality)
    except DiffusionBenchmarkError as exc:
        if not comparator:
            raise
        data.update(quality=None, quality_undefined_reason=str(exc))
    if comparator:
        data["comparator_geometry_failures"] = _baseline_failures(summary)
        data["comparator_geometry_passed"] = not _baseline_failures(summary)
    return data


def score(stage, workspace, source):
    request = DiffusionRequest.from_json((workspace / "request.json").read_text())
    if stage in {"raw", "refine"}:
        filename = "runner-result.json" if stage == "raw" else "refined-runner-result.json"
        result = RunnerResult.from_json((workspace / filename).read_text())
        validated, = validate_runner_result(request, result, workspace=workspace)
        data = evaluate(workspace, request, validated.candidate.coordinate_artifact.path, summary=validated.summary)
        data["resources"] = asdict(result.resource_metrics)
    elif stage == "modeller":
        from run_context_homology_acceptance import normalize_comparator_ids

        candidate = workspace / "modeller_comparator.pdb"
        mapping = normalize_comparator_ids(workspace / "modeller_homology.pdb", candidate, request)
        data = evaluate(workspace, request, candidate.name, comparator=True)
        data["identity_mapping"] = mapping
    else:
        publication = json.loads((workspace / "publication.json").read_text())
        data = evaluate(workspace, request, publication["candidate"])
        data["publication_status"] = publication["status"]
    return {"status": "evaluated", **data}


def run(args):
    protocol = json.loads(args.protocol.read_text())
    manifest = json.loads(args.manifest.read_text())
    if protocol["status"] != "frozen-before-known-sequence-holdout-execution" or protocol["manifest_sha256"] != sha(args.manifest):
        raise ValueError("holdout execution protocol mismatch")
    verify_inventory(ROOT, protocol["code_sha256"])
    cases = {case["case_id"]: case for case in manifest["cases"]}
    stage = args.stage
    records, newly_executed = [], 0
    for job in protocol["jobs"][stage]:
        case = cases[job["case_id"]]
        source = args.cohort / job["case_id"]
        verify_inventory(source, case["artifacts"])
        destination = args.output / stage / job["case_id"] / f"seed{job['seed']}"
        dependency_sha = None
        raw_source = None
        if stage == "refine":
            raw_source = args.output / "raw" / job["case_id"] / f"seed{job['seed']}"
            marker = json.loads((raw_source / "complete.json").read_text())
            if marker["protocol_sha256"] != sha(args.protocol):
                raise ValueError("raw refinement dependency belongs to another protocol")
            verify_inventory(raw_source, marker["artifacts"])
            dependency_sha = sha(raw_source / "complete.json")
        if not destination.exists():
            if args.max_new and newly_executed >= args.max_new:
                break
            with tempfile.TemporaryDirectory(prefix=f"known-sequence-{stage}-", dir=args.work_parent) as directory:
                workspace = Path(directory)
                (workspace / "input").mkdir()
                shutil.copyfile(source / "input/normalized.pdb", workspace / "input/normalized.pdb")
                shutil.copyfile(source / f"requests/cc89-seed{job['seed']}.json", workspace / "request.json")
                blocked = False
                if raw_source is not None:
                    raw_outcome = json.loads((raw_source / "outcome.json").read_text())
                    if raw_outcome["status"] != "evaluated":
                        blocked = True
                    else:
                        shutil.copytree(raw_source / "raw", workspace / "raw")
                        shutil.copyfile(raw_source / "runner-result.json", workspace / "runner-result.json")
                start = time.perf_counter()
                if blocked:
                    outcome = {"status": "dependency-failed", "message": "raw generation failed; no replacement or refinement launch"}
                else:
                    python = RAW_PYTHON if stage == "raw" else REFINE_PYTHON if stage == "refine" else CORE_PYTHON
                    command = [str(python), str(Path(__file__).resolve()), "worker", "--kind", stage,
                        "--workspace", str(workspace), "--source", str(source), "--protocol", str(args.protocol), "--work-parent", str(args.work_parent)]
                    error_phase = "execution"
                    try:
                        with (workspace / f"{stage}-worker.log").open("x") as log:
                            subprocess.run(command, env=environment(stage), stdout=log, stderr=subprocess.STDOUT,
                                check=True, timeout=protocol["timeouts_seconds"][stage], cwd=ROOT)
                        error_phase = "evaluation"
                        shutil.copyfile(source / "reference.pdb", workspace / "reference.pdb")
                        outcome = score(stage, workspace, source)
                    except (subprocess.SubprocessError, OSError, ValueError, RuntimeError) as exc:
                        outcome = {"status": "guarded-chirality-rejection" if (workspace / "guarded-chirality.json").exists() else "execution-error",
                            "message": str(exc), "exception_type": type(exc).__name__, "error_phase": error_phase}
                outcome["stage_wall_seconds"] = time.perf_counter() - start
                (workspace / "outcome.json").write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n")
                destination.parent.mkdir(parents=True, exist_ok=True)
                staging = destination.parent / (".archive-" + uuid.uuid4().hex)
                shutil.copytree(workspace, staging)
                marker = {"protocol_sha256": sha(args.protocol), "manifest_sha256": sha(args.manifest),
                    "raw_complete_sha256": dependency_sha, "stage": stage, "job": job,
                    "artifacts": {p.relative_to(staging).as_posix(): sha(p) for p in sorted(staging.rglob("*")) if p.is_file()}}
                (staging / "complete.json").write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n")
                staging.rename(destination)
            newly_executed += 1
        marker = json.loads((destination / "complete.json").read_text())
        if marker["protocol_sha256"] != sha(args.protocol) or marker["raw_complete_sha256"] != dependency_sha or marker["job"] != job:
            raise ValueError("completed holdout archive identity changed")
        verify_inventory(destination, marker["artifacts"])
        outcome = json.loads((destination / "outcome.json").read_text())
        records.append({**job, "source_id": case["source_id"], "length": case["length"], "stratum": case["stratum"], **outcome})
        print(json.dumps({**job, "stage": stage, "status": outcome["status"],
            "passed": outcome.get("validation", {}).get("passed"), "backbone_rmsd": (outcome.get("quality") or {}).get("gap_backbone_rmsd_angstrom")}), flush=True)
    report = {"complete": len(records) == len(protocol["jobs"][stage]), "protocol_sha256": sha(args.protocol),
        "stage": stage, "planned": len(protocol["jobs"][stage]), "completed": len(records), "records": records, "public_promotion": False}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / (stage + "-report.json")).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "records"}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    freezing = commands.add_parser("freeze")
    freezing.add_argument("--supersedes", type=Path, help="Setup protocol superseded before any inference")
    execution = commands.add_parser("run")
    working = commands.add_parser("worker")
    for command in (freezing, execution):
        for name in ("cohort", "manifest", "protocol"):
            command.add_argument("--" + name, type=Path, required=True)
    for name in ("output", "work-parent"):
        execution.add_argument("--" + name, type=Path, required=True)
    execution.add_argument("--stage", choices=STAGES, required=True)
    execution.add_argument("--max-new", type=int, default=0)
    working.add_argument("--kind", choices=STAGES, required=True)
    for name in ("workspace", "source", "protocol", "work-parent"):
        working.add_argument("--" + name, type=Path, required=True)
    preflighting = commands.add_parser("preflight-worker")
    preflighting.add_argument("--kind", choices=("raw", "refine"), required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    {"freeze": freeze, "run": run, "worker": worker, "preflight-worker": preflight}[args.action](args)


if __name__ == "__main__":
    main()
