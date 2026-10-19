#!/usr/bin/env python3
"""Freeze and execute source-motivated cc89 CUDA conditioning/noise controls."""

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

from dvbfixer.model.diffusion.contract import DiffusionRequest
from dvbfixer.model.diffusion.validate import validate_runner_result

ROOT = Path(__file__).resolve().parents[1]
CONFIGURATIONS = {
    "baseline-native": {"step_scale": 1.2, "s_churn": 200.0, "per_step_reinjection": False, "crop_strategy": "backbone-sidechain", "replacement_guidance": False},
    "deterministic-native": {"step_scale": 1.0, "s_churn": 0.0, "per_step_reinjection": False, "crop_strategy": "backbone-sidechain", "replacement_guidance": False},
    "deterministic-projected": {"step_scale": 1.0, "s_churn": 0.0, "per_step_reinjection": True, "crop_strategy": "backbone-sidechain", "replacement_guidance": False},
    "backbone-projected": {"step_scale": 1.0, "s_churn": 0.0, "per_step_reinjection": True, "crop_strategy": "backbone", "replacement_guidance": False},
    "replacement-projected": {"step_scale": 1.0, "s_churn": 0.0, "per_step_reinjection": True, "crop_strategy": "backbone-sidechain", "replacement_guidance": True},
}


def freeze(args):
    if args.manifest.exists():
        raise ValueError("cc89 control protocol must be new")
    cases = []
    for name in ("cc89-joint", "cc89-discontiguous", "cc89-case-insertion"):
        root = args.cohort / name
        cases.append({"case_id": name, "artifacts": {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                                   for path in root.rglob("*") if path.is_file()}})
    manifest = {"status": "frozen-before-cc89-cuda-control-inference", "no_replacement": True, "cases": cases,
        "configurations": CONFIGURATIONS, "steps": 500, "seed": 7,
        "rationale": "cc89 crop-conditional training limits motifs to24 residues; prior full-context native fit drifts14A; isolate churn, step scale, conditioning atoms and replacement before assuming a mapping defect",
        "code_sha256": hashlib.sha256((ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py").read_bytes()).hexdigest(),
        "patched_engine_sha256": hashlib.sha256((ROOT / "test/protpardelle-1c-audit/src/protpardelle/core/models.py").read_bytes()).hexdigest(),
        "promotion": False, "geometry_policy": "unchanged-current-independent-validator", "timeout_seconds": 600}
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(args.manifest)


def worker(args):
    manifest = json.loads(args.manifest.read_text())
    settings = manifest["configurations"][args.arm]
    params = ROOT / "test/protpardelle-1c-audit/model_params"
    adapter = _load("cc89_controls", ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py")
    args.workspace.joinpath("raw").mkdir()
    result, summary = adapter._run_staged(args.workspace / "request.json", args.workspace / "raw", params / "configs/cc89.yaml",
        params / "weights/cc89_epoch415.pth", steps=500, device_name="cuda", mps_profile=False, **settings)
    request = DiffusionRequest.from_json((args.workspace / "request.json").read_text())
    validation = validate_runner_result(request, result, workspace=args.workspace)[0].summary
    (args.workspace / "runner-result.json").write_text(result.to_json())
    (args.workspace / "outcome.json").write_text(json.dumps({"validation": asdict(validation), "resources": asdict(result.resource_metrics),
        "candidate": asdict(result.candidates[0]), "sampling": settings, "summary": summary.relative_to(args.workspace).as_posix()}, indent=2, sort_keys=True) + "\n")


def run(args):
    manifest = json.loads(args.manifest.read_text())
    digest = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    if manifest["status"] != "frozen-before-cc89-cuda-control-inference":
        raise ValueError("unfrozen cc89 controls")
    if hashlib.sha256((ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py").read_bytes()).hexdigest() != manifest["code_sha256"]:
        raise ValueError("cc89 control adapter changed since freeze")
    args.output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(PYTHONPATH=os.pathsep.join((str(ROOT / "src"), str(ROOT / "test/protpardelle-1c-audit/src"), str(ROOT / "scripts"))),
               PROTPARDELLE_MODEL_PARAMS=str(ROOT / "test/protpardelle-1c-audit/model_params"))
    records = []
    for case in manifest["cases"]:
        source = args.cohort / case["case_id"]
        for relative, expected in case["artifacts"].items():
            if hashlib.sha256((source / relative).read_bytes()).hexdigest() != expected:
                raise ValueError("cc89 control source changed")
        for arm in manifest["configurations"]:
            destination = args.output / case["case_id"] / arm
            if destination.exists():
                marker = json.loads((destination / "complete.json").read_text())
                if marker["manifest_sha256"] != digest:
                    raise ValueError("cc89 control archive belongs to another manifest")
                for relative, expected in marker["artifacts"].items():
                    if hashlib.sha256((destination / relative).read_bytes()).hexdigest() != expected:
                        raise ValueError("cc89 control archive changed")
                outcome = json.loads((destination / "outcome.json").read_text())
            else:
                with diagnostic_workspace(args, case["case_id"], arm) as workspace:
                    shutil.copytree(source, workspace, dirs_exist_ok=True)
                    with (workspace / "worker.log").open("xb") as log:
                        subprocess.run([str(ROOT / "test/protpardelle-env/bin/python"), str(Path(__file__).resolve()), "worker",
                            "--manifest", str(args.manifest), "--workspace", str(workspace), "--arm", arm],
                            env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=manifest["timeout_seconds"])
                    outcome = json.loads((workspace / "outcome.json").read_text())
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(workspace, destination)
                    marker = {"manifest_sha256": digest, "artifacts": {path.relative_to(destination).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in destination.rglob("*") if path.is_file()}}
                    (destination / "complete.json").write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n")
            row = {"case_id": case["case_id"], "arm": arm, "validation_passed": outcome["validation"]["passed"]}
            records.append(row)
            print(json.dumps(row), flush=True)
    (args.output / "report.json").write_text(json.dumps({"manifest_sha256": digest, "cases": records}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("freeze")
    prep.add_argument("--cohort", required=True, type=Path)
    execution = sub.add_parser("run")
    for name in ("cohort", "output", "work-parent"):
        execution.add_argument("--" + name, required=True, type=Path)
    invocation = sub.add_parser("worker")
    invocation.add_argument("--workspace", required=True, type=Path)
    invocation.add_argument("--arm", required=True)
    for command in (prep, execution, invocation):
        command.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    {"freeze": freeze, "run": run, "worker": worker}[args.action](args)


if __name__ == "__main__":
    main()
