#!/usr/bin/env python3
"""Select on development data, then run a frozen new-source holdout once."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from analyze_a100_relaxation import equivalent
from research_flank_refinement import refine
from run_a100_relaxation import runtime_environment, sha, verify_inventory
from run_flank_comparison import evaluate

from dvbfixer.model.diffusion.contract import DiffusionRequest, RunnerResult
from dvbfixer.model.diffusion.runner_refinement import refine_runner_result

ROOT = Path(__file__).resolve().parents[1]


def invoke(script, *arguments):
    subprocess.run([sys.executable, str(ROOT / "scripts" / script), *map(str, arguments)], check=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")})


def worker(args):
    root = args.workspace
    protocol = json.loads(args.protocol.read_text())
    request = DiffusionRequest.from_json((root / "request.json").read_text())
    raw_result = RunnerResult.from_json((root / "runner-result.json").read_text())
    before = evaluate(root, request, raw_result.candidates[0].coordinate_artifact.path)
    start = time.perf_counter()
    if protocol["selected_protocol"] == "rigid":
        result = refine_runner_result(root / "request.json", raw_result, root / "selected-refined", platform_name="CUDA")
        (root / "selected-runner-result.json").write_text(result.to_json())
        artifact = result.candidates[0].coordinate_artifact.path
        post_failures = result.candidates[0].postprocessing_failures
        after = evaluate(root, request, artifact)
        if post_failures:
            after["validation"]["passed"] = False
            after["validation"]["hard_gate_failures"] = [*after["validation"]["hard_gate_failures"], *post_failures]
            after["quality"]["validation_passed"] = False
    else:
        text = refine((root / raw_result.candidates[0].coordinate_artifact.path).read_text(), request)
        artifact = "selected-flank-candidate.pdb"
        (root / artifact).write_text(text, encoding="ascii")
        post_failures = ()
        after = evaluate(root, request, artifact, allow_flanks=True)
    elapsed = time.perf_counter() - start
    outcome = {"status": "evaluated", "candidate": {"path": artifact, "sha256": sha(root / artifact)},
        "raw": before, "selected": after,
        "original_strict": after if protocol["selected_protocol"] == "rigid" else evaluate(root, request, artifact),
        "refinement_wall_seconds": elapsed, "postprocessing_failures": post_failures}
    (root / "holdout-result.json").write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n")


def run(args):
    while args.comparison_pid:
        try:
            os.kill(args.comparison_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(15)
    invoke("run_flank_comparison.py", "analyze", "--manifest", args.comparison_manifest, "--output", args.comparison)
    development = json.loads((args.comparison / "analysis.json").read_text())
    holdout = json.loads(args.holdout_manifest.read_text())
    if not development["complete"] or any(case["split"] != "validation" for case in holdout["cases"]):
        raise ValueError("followup requires completed development and validation-only frozen holdout")
    paths = ("scripts/run_relaxation_followup.py", "scripts/run_flank_comparison.py", "scripts/research_flank_refinement.py",
        "src/dvbfixer/model/diffusion/boundary_refinement.py", "src/dvbfixer/model/diffusion/validate.py")
    protocol = {"status": "selected-and-frozen-before-new-source-inference", "selected_protocol": development["selected_protocol"],
        "development_comparison_sha256": sha(args.comparison / "analysis.json"), "selection_rule": development["selection_rule"],
        "holdout_manifest_sha256": sha(args.holdout_manifest), "environment": runtime_environment(),
        "code_sha256": {relative: sha(ROOT / relative) for relative in paths}, "no_replacement": True,
        "seeds": [7], "inference": "pinned Protenix CUDA; 200 updates; reinjection; no regeneration",
        "reference_use": "offline evaluation only; no tuning or restart selection", "solvent": False, "public_promotion": False}
    if args.protocol.exists():
        if json.loads(args.protocol.read_text()) != protocol:
            raise ValueError("selected holdout protocol differs from existing freeze")
    else:
        args.protocol.write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    args.output.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"selected_protocol": protocol["selected_protocol"], "holdout_outcomes": sum(len(case["arms"]) for case in holdout["cases"]),
        "protocol_sha256": sha(args.protocol)}), flush=True)
    raw_root = args.output / "raw"
    invoke("run_a100_calibration.py", "run", "--manifest", args.holdout_manifest, "--cohort", args.cohort,
        "--output", raw_root, "--work-parent", args.work_parent, "--checkpoint", args.checkpoint, "--kalign", args.kalign)
    invoke("analyze_a100_calibration.py", "--manifest", args.holdout_manifest, "--cohort", args.cohort,
        "--outcomes", raw_root, "--output", raw_root / "analysis.json")
    records = []
    for case in holdout["cases"]:
        for arm in case["arms"]:
            source = raw_root / case["case_id"] / arm
            raw_marker = json.loads((source / "complete.json").read_text())
            verify_inventory(source, raw_marker["artifacts"])
            destination = args.output / "selected" / case["case_id"] / arm
            if destination.exists():
                marker = json.loads((destination / "complete.json").read_text())
                if marker["protocol_sha256"] != sha(args.protocol) or marker["raw_complete_sha256"] != sha(source / "complete.json"):
                    raise ValueError("holdout completion custody changed")
                verify_inventory(destination, marker["artifacts"])
                outcome = json.loads((destination / "holdout-result.json").read_text())
            else:
                with tempfile.TemporaryDirectory(prefix="relaxation-holdout-", dir=args.work_parent) as directory:
                    workspace = Path(directory)
                    shutil.copytree(source, workspace, dirs_exist_ok=True)
                    (workspace / "complete.json").rename(workspace / "raw-complete.json")
                    try:
                        with (workspace / "holdout-worker.log").open("x") as log:
                            subprocess.run([sys.executable, str(Path(__file__).resolve()), "worker", "--workspace", str(workspace), "--protocol", str(args.protocol)],
                                env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "OPENMM_CPU_THREADS": "1"},
                                stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
                        outcome = json.loads((workspace / "holdout-result.json").read_text())
                    except (subprocess.SubprocessError, OSError) as exc:
                        outcome = {"status": "execution-error", "message": str(exc)}
                        (workspace / "holdout-result.json").write_text(json.dumps(outcome, indent=2) + "\n")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(workspace, destination)
                    marker = {"protocol_sha256": sha(args.protocol), "raw_complete_sha256": sha(source / "complete.json"),
                        "artifacts": {path.relative_to(destination).as_posix(): sha(path) for path in destination.rglob("*") if path.is_file()}}
                    (destination / "complete.json").write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n")
            records.append({"case_id": case["case_id"], "source_id": case["source_id"], "length": case["length"], "arm": arm, **outcome})
            print(json.dumps({"case_id": case["case_id"], "status": outcome["status"], "selected_passed": outcome.get("selected", {}).get("validation", {}).get("passed", False)}), flush=True)
            (args.output / "progress.json").write_text(json.dumps({"records": records}, indent=2) + "\n")
    # Recompute from archived PDBs; no runner-owned acceptance is trusted.
    for row in records:
        root = args.output / "selected" / row["case_id"] / row["arm"]
        verify_inventory(root, json.loads((root / "complete.json").read_text())["artifacts"])
        verify_inventory(root, json.loads((root / "raw-complete.json").read_text())["artifacts"])
        if row["status"] != "evaluated":
            continue
        request = DiffusionRequest.from_json((root / "request.json").read_text())
        raw = RunnerResult.from_json((root / "runner-result.json").read_text())
        if not equivalent(evaluate(root, request, raw.candidates[0].coordinate_artifact.path), row["raw"]):
            raise ValueError("holdout raw revalidation mismatch")
        candidate = row["candidate"]
        if sha(root / candidate["path"]) != candidate["sha256"]:
            raise ValueError("holdout candidate changed")
        current = evaluate(root, request, candidate["path"], allow_flanks=protocol["selected_protocol"] == "bounded-flank")
        if row["postprocessing_failures"]:
            current["validation"]["passed"] = False
            current["validation"]["hard_gate_failures"] = [*current["validation"]["hard_gate_failures"], *row["postprocessing_failures"]]
            current["quality"]["validation_passed"] = False
        if not equivalent(current, row["selected"]):
            raise ValueError("holdout selected revalidation mismatch")
    result = {"complete": True, "protocol_sha256": sha(args.protocol), "selected_protocol": protocol["selected_protocol"],
        "holdout_manifest_sha256": sha(args.holdout_manifest), "raw_analysis_sha256": sha(raw_root / "analysis.json"),
        "cases": records, "outcome_count": len(records), "source_count": len({row["source_id"] for row in records}),
        "selected_accepted": sum(row.get("selected", {}).get("validation", {}).get("passed", False) for row in records),
        "execution_errors": sum(row["status"] != "evaluated" for row in records), "public_promotion": False}
    (args.output / "analysis.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    execution = commands.add_parser("run")
    execution.add_argument("--comparison-pid", type=int, default=0)
    for name in ("comparison", "comparison-manifest", "holdout-manifest", "cohort", "output", "work-parent", "checkpoint", "kalign"):
        execution.add_argument("--" + name, type=Path, required=True)
    worker_parser = commands.add_parser("worker")
    worker_parser.add_argument("--workspace", type=Path, required=True)
    for command in (execution, worker_parser):
        command.add_argument("--protocol", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    run(args) if args.action == "run" else worker(args)


if __name__ == "__main__":
    main()
