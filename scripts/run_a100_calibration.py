#!/usr/bin/env python3
"""Run frozen prospective short/adaptive/long calibration on the pinned A100."""

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
    contact_gated_expansion,
    expand_from_sample,
    validate_adaptive_transition,
)
from dvbfixer.model.diffusion.benchmark import candidate_quality, load_pdb_coordinates
from dvbfixer.model.diffusion.contract import ArtifactReference, DiffusionRequest
from dvbfixer.model.diffusion.sampler import SamplingAblationMode
from dvbfixer.model.diffusion.validate import validate_runner_result

ROOT = Path(__file__).resolve().parents[1]


def worker(args):
    root = args.workspace
    request_path = root / "request.json"
    request = DiffusionRequest.from_json(request_path.read_text())
    source = (root / request.normalized_pdb.path).read_bytes()
    production = _load("calibration_production", ROOT / "deploy/protenix-v1/production_runner.py")
    production._verify_checkpoint(args.checkpoint)
    production._verify_profile_environment()
    _load("reinjection", ROOT / "deploy/protenix-v1/reinjection.py")
    builder = _load("calibration_builder", ROOT / "deploy/protenix-v1/build-template-input.py")
    adapter = _load("calibration_adapter", ROOT / "deploy/protenix-v1/checkpoint_gap_smoke.py")
    stages = []
    decisions = []
    rounds = 2 if args.arm.startswith("adaptive-") else 1
    for index in range(rounds):
        stage = root / f"stage-{index}"
        stage.mkdir()
        features = builder.build_input(request_path, stage / "features")
        result, _summary_path = adapter.run(request_path, features, stage / "raw", args.kalign, args.checkpoint,
            cycles=1, steps=200, ablation_mode=SamplingAblationMode.REINJECTION)
        validation = validate_runner_result(request, result, workspace=root)[0].summary
        (stage / "request.json").write_text(request.to_json())
        (stage / "runner-result.json").write_text(result.to_json())
        stages.append({"stage": index, "validation": asdict(validation), "selected_fixed_atom_count": len(request.protein_context.fixed_conditioning)})
        if index + 1 < rounds:
            candidate = result.candidates[0].coordinate_artifact
            sampled = (root / candidate.path).read_bytes()
            if args.arm == "adaptive-monotonic":
                updated = expand_from_sample(request, source, sampled, candidate_path=candidate.path)
                decision = {"reason": "unconditional-monotonic-expansion"}
            else:
                updated, decision = contact_gated_expansion(request, source, sampled, candidate_path=candidate.path,
                    initial_validation_passed=validation.passed, distance_angstrom=4.0,
                    minimum_new_contact_residues=2, minimum_supporting_backbone_atoms=2)
            if updated != request:
                validate_adaptive_transition(request, updated, source, sampled)
            decisions.append(decision)
            request = updated
            request_path.write_text(request.to_json())
    reference = ArtifactReference("reference.pdb", hashlib.sha256((root / "reference.pdb").read_bytes()).hexdigest())
    quality = candidate_quality(result.candidates[0].candidate_id, load_pdb_coordinates(root, reference),
        load_pdb_coordinates(root, result.candidates[0].coordinate_artifact),
        generated_residues={residue for gap in request.gaps for residue in gap.generated_residues}, fixed_atoms=set(request.fixed_atoms),
        anchor_residues={anchor for gap in request.gaps for anchor in (gap.left_anchor, gap.right_anchor) if anchor},
        closure_passed="junction-peptide-connectivity" not in validation.hard_gate_failures, validation_passed=validation.passed,
        expected_generated_atoms=set(request.generated_atoms),
        interface_chain_pairs=tuple((request.gaps[0].chain, target.chain) for target in request.target_sequences if target.chain != request.gaps[0].chain))
    (root / "runner-result.json").write_text(result.to_json())
    (root / "outcome.json").write_text(json.dumps({"arm": args.arm, "validation": asdict(validation), "quality": asdict(quality),
        "candidate": asdict(result.candidates[0]), "stages": stages, "adaptive_decisions": decisions,
        "resources": asdict(result.resource_metrics), "promotion": False}, indent=2, sort_keys=True) + "\n")


def run(args):
    manifest = json.loads(args.manifest.read_text())
    digest = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    if manifest["status"] != "frozen-before-a100-calibration-inference" or not manifest["no_replacement"]:
        raise ValueError("A100 calibration requires frozen no-replacement membership")
    args.output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", LAYERNORM_TYPE="torch",
        PYTHONPATH=os.pathsep.join((str(ROOT / ".artifacts/protenix-v1-acceptance-source"), str(ROOT / "src"), str(ROOT / "scripts"))),
        PROTENIX_ROOT_DIR=str(ROOT / ".artifacts/protenix-v1-acceptance-source"))
    environment["PATH"] = str(args.kalign.parent) + os.pathsep + environment.get("PATH", "")
    records = []
    for case in manifest["cases"]:
        source = args.cohort / "cases" / case["case_id"]
        for relative, expected in case["artifacts"].items():
            if hashlib.sha256((source / relative).read_bytes()).hexdigest() != expected:
                raise ValueError("frozen A100 calibration input changed")
        for arm in case["arms"]:
            destination = args.output / case["case_id"] / arm
            if destination.exists():
                marker = json.loads((destination / "complete.json").read_text())
                if marker["manifest_sha256"] != digest:
                    raise ValueError("completed calibration belongs to another manifest")
                for relative, expected in marker["artifacts"].items():
                    if hashlib.sha256((destination / relative).read_bytes()).hexdigest() != expected:
                        raise ValueError("completed calibration artifact changed")
                outcome = json.loads((destination / "outcome.json").read_text())
            else:
                with diagnostic_workspace(args, case["case_id"], arm) as workspace:
                    shutil.copytree(source, workspace, dirs_exist_ok=True)
                    with (workspace / "worker.log").open("xb") as log:
                        subprocess.run([str(ROOT / "test/protenix-env/bin/python"), str(Path(__file__).resolve()), "worker",
                            "--workspace", str(workspace), "--arm", arm, "--checkpoint", str(args.checkpoint), "--kalign", str(args.kalign)],
                            env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=manifest["limits"]["timeout_seconds"])
                    outcome = json.loads((workspace / "outcome.json").read_text())
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(workspace, destination)
                    marker = {"manifest_sha256": digest, "artifacts": {path.relative_to(destination).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in destination.rglob("*") if path.is_file()}}
                    (destination / "complete.json").write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n")
            row = {"case_id": case["case_id"], "source_id": case["source_id"], "split": case["split"], "length": case["length"],
                   "arm": arm, "validation_passed": outcome["validation"]["passed"]}
            records.append(row)
            print(json.dumps(row), flush=True)
            (args.output / "progress.json").write_text(json.dumps({"manifest_sha256": digest, "records": records}, indent=2) + "\n")
    (args.output / "report.json").write_text(json.dumps({"manifest_sha256": digest, "records": records}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    execution = sub.add_parser("run")
    for name in ("manifest", "cohort", "output", "work-parent"):
        execution.add_argument("--" + name, type=Path, required=True)
    invocation = sub.add_parser("worker")
    invocation.add_argument("--workspace", required=True, type=Path)
    invocation.add_argument("--arm", required=True)
    for group in (execution, invocation):
        group.add_argument("--checkpoint", type=Path, required=True)
        group.add_argument("--kalign", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    worker(args) if args.action == "worker" else run(args)


if __name__ == "__main__":
    main()
