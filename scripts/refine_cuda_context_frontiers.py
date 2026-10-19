#!/usr/bin/env python3
"""Freeze and audit CUDA refinement of every rich-context cc89 frontier output.

Raw inference archives are immutable inputs. No new model sampling, reference-
guided optimization, replacement of failures, or Apple acceptance is performed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from analyze_a100_relaxation import equivalent
from run_a100_relaxation import (
    check_cuda_runtime,
    quality,
    runtime_environment,
    sha,
    verify_inventory,
)

from dvbfixer.model.diffusion.contract import DiffusionRequest, RunnerResult
from dvbfixer.model.diffusion.runner_refinement import refine_runner_result
from dvbfixer.model.diffusion.validate import validate_runner_result

ROOT = Path(__file__).resolve().parents[1]
CODE = ("scripts/refine_cuda_context_frontiers.py", "src/dvbfixer/model/diffusion/boundary_refinement.py",
        "src/dvbfixer/model/diffusion/runner_refinement.py", "src/dvbfixer/model/diffusion/validate.py",
        "src/dvbfixer/ffutils/geometry.py")


def freeze(args):
    if args.protocol.exists():
        raise ValueError("refinement protocol must be new")
    manifest = json.loads(args.manifest.read_text())
    cases = []
    for case in manifest["cases"]:
        if case["kind"] != "cc89-rich":
            continue
        for arm in case["arms"]:
            root = args.raw / case["case_id"] / arm
            marker = json.loads((root / "complete.json").read_text())
            if marker["manifest_sha256"] != sha(args.manifest):
                raise ValueError("rich-context input belongs to another frozen study")
            verify_inventory(root, marker["artifacts"])
            cases.append({"case_id": case["case_id"], "arm": arm, "raw_complete_sha256": sha(root / "complete.json")})
    if not cases:
        raise ValueError("no rich-context inputs in the frozen manifest")
    check_cuda_runtime()
    protocol = {"status": "frozen-before-rich-context-cuda-refinement", "manifest_sha256": sha(args.manifest),
        "code_sha256": {path: sha(ROOT / path) for path in CODE}, "cases": cases, "environment": runtime_environment(),
        "sampling": "none; reuse every immutable raw native/projection-500 candidate",
        "refinement": "unchanged rigid v6 CUDA; generated residues only; complete fixed source force-field context",
        "reference_usage": "offline evaluation only", "solvent": False, "no_replacement": True,
        "timeout_seconds": 1800, "public_promotion": False, "apple_mps": "deferred-until-cuda-implementation-completes"}
    with args.protocol.open("x") as stream:
        stream.write(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"outcomes": len(cases), "protocol_sha256": sha(args.protocol)}), flush=True)


def evaluate(root, request, result):
    validation, = validate_runner_result(request, result, workspace=root)
    return {"validation": asdict(validation.summary), "quality": quality(root, request, result, validation.summary)}


def worker(args):
    root = args.workspace
    request = DiffusionRequest.from_json((root / "request.json").read_text())
    raw = RunnerResult.from_json((root / "runner-result.json").read_text())
    before = evaluate(root, request, raw)
    selected = refine_runner_result(root / "request.json", raw, root / "cuda-refined", platform_name="CUDA")
    after = evaluate(root, request, selected)
    (root / "cuda-runner-result.json").write_text(selected.to_json())
    (root / "cuda-outcome.json").write_text(json.dumps({"status": "evaluated", "raw": before, "refined": after}, indent=2, sort_keys=True) + "\n")


def run(args):
    protocol = json.loads(args.protocol.read_text())
    if protocol["status"] != "frozen-before-rich-context-cuda-refinement" or not protocol["no_replacement"]:
        raise ValueError("CUDA refinement requires a frozen no-replacement protocol")
    verify_inventory(ROOT, protocol["code_sha256"])
    if runtime_environment() != protocol["environment"]:
        raise ValueError("CUDA refinement environment changed after freeze")
    check_cuda_runtime()
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for case in protocol["cases"]:
        source = args.raw / case["case_id"] / case["arm"]
        if sha(source / "complete.json") != case["raw_complete_sha256"]:
            raise ValueError("raw CUDA context archive changed after freeze")
        verify_inventory(source, json.loads((source / "complete.json").read_text())["artifacts"])
        destination = args.output / case["case_id"] / case["arm"]
        if not destination.exists():
            with tempfile.TemporaryDirectory(prefix="cc89-context-refinement-", dir=args.work_parent) as directory:
                workspace = Path(directory)
                shutil.copytree(source, workspace, dirs_exist_ok=True)
                (workspace / "complete.json").rename(workspace / "raw-complete.json")
                try:
                    with (workspace / "cuda-refinement.log").open("x") as log:
                        subprocess.run([sys.executable, str(Path(__file__).resolve()), "worker", "--workspace", str(workspace)],
                            env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "OPENMM_CPU_THREADS": "1"},
                            stdout=log, stderr=subprocess.STDOUT, check=True, timeout=protocol["timeout_seconds"])
                except (subprocess.SubprocessError, OSError) as exc:
                    (workspace / "cuda-outcome.json").write_text(json.dumps({"status": "execution-error", "message": str(exc)}, indent=2) + "\n")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(workspace, destination)
                marker = {"protocol_sha256": sha(args.protocol), "raw_complete_sha256": case["raw_complete_sha256"],
                    "artifacts": {path.relative_to(destination).as_posix(): sha(path) for path in destination.rglob("*") if path.is_file()}}
                (destination / "complete.json").write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n")
        marker = json.loads((destination / "complete.json").read_text())
        if marker["protocol_sha256"] != sha(args.protocol) or marker["raw_complete_sha256"] != case["raw_complete_sha256"]:
            raise ValueError("CUDA refinement completion belongs to another protocol/input")
        verify_inventory(destination, marker["artifacts"])
        outcome = json.loads((destination / "cuda-outcome.json").read_text())
        if outcome["status"] == "evaluated":
            request = DiffusionRequest.from_json((destination / "request.json").read_text())
            for stage, filename in (("raw", "runner-result.json"), ("refined", "cuda-runner-result.json")):
                current = evaluate(destination, request, RunnerResult.from_json((destination / filename).read_text()))
                if not equivalent(current, outcome[stage]):
                    raise ValueError("rich-context independent validation/accuracy mismatch")
        row = {**case, **outcome}
        records.append(row)
        print(json.dumps({"case_id": case["case_id"], "arm": case["arm"], "status": row["status"],
            "refined_passed": row.get("refined", {}).get("validation", {}).get("passed", False)}), flush=True)
    report = {"complete": True, "protocol_sha256": sha(args.protocol), "cases": records,
        "outcomes": len(records), "execution_errors": sum(row["status"] != "evaluated" for row in records),
        "raw_accepted": sum(row.get("raw", {}).get("validation", {}).get("passed", False) for row in records),
        "refined_accepted": sum(row.get("refined", {}).get("validation", {}).get("passed", False) for row in records),
        "public_promotion": False, "apple_mps": protocol["apple_mps"]}
    (args.output / "analysis.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    freezing = commands.add_parser("freeze")
    freezing.add_argument("--manifest", type=Path, required=True)
    execution = commands.add_parser("run")
    for command in (freezing, execution):
        command.add_argument("--protocol", type=Path, required=True)
        command.add_argument("--raw", type=Path, required=True)
    execution.add_argument("--output", type=Path, required=True)
    execution.add_argument("--work-parent", type=Path, required=True)
    working = commands.add_parser("worker")
    working.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    {"freeze": freeze, "run": run, "worker": worker}[args.action](args)


if __name__ == "__main__":
    main()
