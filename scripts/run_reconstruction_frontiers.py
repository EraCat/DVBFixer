#!/usr/bin/env python3
"""Bounded sequential frontier experiments with immutable input/outcome custody."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

from run_protein_context_ablations import _load, diagnostic_workspace

from dvbfixer.model.diffusion.adaptive_context import (
    expand_from_sample,
    validate_adaptive_transition,
)
from dvbfixer.model.diffusion.benchmark import candidate_quality, load_pdb_coordinates
from dvbfixer.model.diffusion.contract import (
    ArtifactReference,
    DiffusionRequest,
    ProteinContextPolicy,
)
from dvbfixer.model.diffusion.protein_context import select_protein_context, validate_context_source
from dvbfixer.model.diffusion.sampler import SamplingAblationMode
from dvbfixer.model.diffusion.validate import validate_runner_result

ROOT = Path(__file__).resolve().parents[1]


def worker(args):
    root = args.workspace
    request_path = root / "request.json"
    request = DiffusionRequest.from_json(request_path.read_text())
    source = (root / request.normalized_pdb.path).read_bytes()
    if request.protein_context is None:
        request = select_protein_context(request, source, ProteinContextPolicy(partner_mode="full"))
        request_path.write_text(request.to_json())
    results = []
    stages = []
    if args.kind == "cc89-rich":
        params = ROOT / "test/protpardelle-1c-audit/model_params"
        adapter = _load("cc89_frontier", ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py")
        directory = root / "raw"
        directory.mkdir()
        result, summary_path = adapter._run_staged(request_path, directory, params / "configs/cc89.yaml", params / "weights/cc89_epoch415.pth",
            steps=500, step_scale=1.2, s_churn=200.0, per_step_reinjection=args.arm == "projection-500", device_name="cuda", mps_profile=False)
        results.append(result)
        stages.append({"stage": 0, "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(), "summary": str(summary_path.relative_to(root))})
    else:
        production = _load("frontier_production", ROOT / "deploy/protenix-v1/production_runner.py")
        production._verify_checkpoint(args.checkpoint)
        production._verify_profile_environment()
        _load("reinjection", ROOT / "deploy/protenix-v1/reinjection.py")
        builder = _load("frontier_builder", ROOT / "deploy/protenix-v1/build-template-input.py")
        adapter = _load("frontier_adapter", ROOT / "deploy/protenix-v1/checkpoint_gap_smoke.py")
        stage_count = 2 if args.kind == "adaptive" else 1
        for stage in range(stage_count):
            stage_dir = root / f"stage-{stage}"
            stage_dir.mkdir()
            # Artifact paths remain relative to the common private root.
            features = builder.build_input(request_path, stage_dir / "features")
            result, summary_path = adapter.run(request_path, features, stage_dir / "raw", args.kalign, args.checkpoint,
                cycles=1, steps=200, ablation_mode=SamplingAblationMode.REINJECTION)
            (stage_dir / "request.json").write_text(request.to_json())
            (stage_dir / "runner-result.json").write_text(result.to_json())
            results.append(result)
            stages.append({"stage": stage, "request_sha256": hashlib.sha256(request.to_json().encode()).hexdigest(),
                           "summary": str(summary_path.relative_to(root)), "selected_fixed_atom_count": len(request.protein_context.fixed_conditioning)})
            if stage + 1 < stage_count and args.arm == "adaptive-two-rounds":
                candidate = result.candidates[0].coordinate_artifact
                sampled = (root / candidate.path).read_bytes()
                updated = expand_from_sample(request, source, sampled, candidate_path=candidate.path)
                validate_adaptive_transition(request, updated, source, sampled)
                request = updated
                request_path.write_text(request.to_json())
        result = results[-1]
        if args.kind == "deletion":
            from dvbfixer.model.diffusion.runner_refinement import refine_runner_result

            result = refine_runner_result(request_path, result, root / "refined", platform_name="Reference")
    validate_context_source(request, source)
    validation = validate_runner_result(request, result, workspace=root)[0].summary
    (root / "runner-result.json").write_text(result.to_json())
    quality = None
    if (root / "reference.pdb").exists():
        reference = ArtifactReference("reference.pdb", hashlib.sha256((root / "reference.pdb").read_bytes()).hexdigest())
        quality = asdict(candidate_quality(result.candidates[0].candidate_id, load_pdb_coordinates(root, reference),
            load_pdb_coordinates(root, result.candidates[0].coordinate_artifact),
            generated_residues={residue for gap in request.gaps for residue in gap.generated_residues}, fixed_atoms=set(request.fixed_atoms),
            anchor_residues={anchor for gap in request.gaps for anchor in (gap.left_anchor, gap.right_anchor) if anchor},
            closure_passed="junction-peptide-connectivity" not in validation.hard_gate_failures, validation_passed=validation.passed,
            interface_chain_pairs=tuple((request.gaps[0].chain, target.chain) for target in request.target_sequences if target.chain != request.gaps[0].chain),
            expected_generated_atoms=set(request.generated_atoms)))
    outcome = {"kind": args.kind, "arm": args.arm, "validation": asdict(validation), "quality": quality,
               "candidate": asdict(result.candidates[0]), "resources": asdict(result.resource_metrics), "stages": stages,
               "promotion": False}
    (root / "outcome.json").write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n")


def run(args):
    manifest = json.loads(args.manifest.read_text())
    digest = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    if manifest["status"] != "frozen-before-frontier-inference" or not manifest["no_replacement"]:
        raise ValueError("frontier study must be frozen and no-replacement")
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for case in manifest["cases"]:
        if args.kind and case["kind"] not in args.kind:
            continue
        source = args.cohort / case["case_id"]
        for relative, expected in case["artifacts"].items():
            if hashlib.sha256((source / relative).read_bytes()).hexdigest() != expected:
                raise ValueError("frontier frozen input changed")
        for arm in case["arms"]:
            destination = args.output / case["case_id"] / arm
            if destination.exists():
                marker = json.loads((destination / "complete.json").read_text())
                if marker["manifest_sha256"] != digest:
                    raise ValueError("frontier outcome manifest changed")
                for relative, expected in marker["artifacts"].items():
                    if hashlib.sha256((destination / relative).read_bytes()).hexdigest() != expected:
                        raise ValueError("frontier completed artifact changed")
                outcome = json.loads((destination / "outcome.json").read_text())
            else:
                with diagnostic_workspace(args, case["case_id"], arm) as workspace:
                    shutil.copytree(source, workspace, dirs_exist_ok=True)
                    environment = os.environ.copy()
                    if case["kind"] == "cc89-rich":
                        python = ROOT / "test/protpardelle-env/bin/python"
                        environment.update(PYTHONPATH=os.pathsep.join((str(ROOT / "src"), str(ROOT / "test/protpardelle-1c-audit/src"), str(ROOT / "scripts"))),
                                           PROTPARDELLE_MODEL_PARAMS=str(ROOT / "test/protpardelle-1c-audit/model_params"))
                    else:
                        python = ROOT / "test/protenix-env/bin/python"
                        environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", LAYERNORM_TYPE="torch",
                            PYTHONPATH=os.pathsep.join((str(ROOT / ".artifacts/protenix-v1-acceptance-source"), str(ROOT / "src"), str(ROOT / "scripts"))),
                            PROTENIX_ROOT_DIR=str(ROOT / ".artifacts/protenix-v1-acceptance-source"))
                    environment["PATH"] = str(args.kalign.parent) + os.pathsep + environment.get("PATH", "")
                    with (workspace / "worker.log").open("xb") as log:
                        subprocess.run([str(python), str(Path(__file__).resolve()), "worker", "--workspace", str(workspace),
                            "--kind", case["kind"], "--arm", arm, "--checkpoint", str(args.checkpoint), "--kalign", str(args.kalign)],
                            env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=manifest["limits"]["timeout_seconds"])
                    outcome = json.loads((workspace / "outcome.json").read_text())
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(workspace, destination)
                    marker = {"manifest_sha256": digest, "artifacts": {path.relative_to(destination).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in destination.rglob("*") if path.is_file()}}
                    (destination / "complete.json").write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n")
            record = {"case_id": case["case_id"], "kind": case["kind"], "arm": arm, "validation_passed": outcome["validation"]["passed"]}
            records.append(record)
            print(json.dumps(record), flush=True)
            (args.output / "progress.json").write_text(json.dumps({"manifest_sha256": digest, "records": records}, indent=2) + "\n")
    (args.output / ("report.json" if not args.kind else "report-" + "-".join(args.kind) + ".json")).write_text(json.dumps({"manifest_sha256": digest, "records": records}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    execution = sub.add_parser("run")
    for name in ("manifest", "cohort", "output", "work-parent"):
        execution.add_argument("--" + name, required=True, type=Path)
    execution.add_argument("--kind", action="append", default=[])
    worker_parser = sub.add_parser("worker")
    worker_parser.add_argument("--workspace", required=True, type=Path)
    worker_parser.add_argument("--kind", required=True)
    worker_parser.add_argument("--arm", required=True)
    for target in (execution, worker_parser):
        target.add_argument("--checkpoint", required=True, type=Path)
        target.add_argument("--kalign", required=True, type=Path)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    worker(args) if args.action == "worker" else run(args)


if __name__ == "__main__":
    main()
