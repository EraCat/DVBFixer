#!/usr/bin/env python3
"""Freeze and execute the source-only corrected cc89 Apple research pilot.

Workers receive only the frozen request and gapped source, never evaluation PDBs.
Every started outcome is terminal: resume verifies archives, never resamples.
This runner does not register or promote a public profile.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

import numpy as np

from dvbfixer.model.diffusion.contract import DiffusionRequest, RunnerResult, SamplerTrace
from dvbfixer.model.diffusion.protein_context import (
    source_context_position_features,
    validate_context_source,
)
from dvbfixer.model.diffusion.validate import validate_runner_result

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "protpardelle-1c-mps-source-physical-research-v1"
MPS_TUNING = (
    "PYTORCH_MPS_FAST_MATH", "PYTORCH_MPS_PREFER_METAL",
    "PYTORCH_MPS_HIGH_WATERMARK_RATIO", "PYTORCH_MPS_LOW_WATERMARK_RATIO",
)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dump_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def load_adapter():
    path = ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py"
    spec = importlib.util.spec_from_file_location("apple_cc89_research_adapter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def environment(protocol):
    env = {key: value for key, value in os.environ.items() if key not in MPS_TUNING}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTORCH_ENABLE_MPS_FALLBACK="0",
        OPENMM_CPU_THREADS="1", PROTPARDELLE_MODEL_PARAMS=str(Path(protocol["checkpoint"]).parent.parent),
        PYTHONPATH=os.pathsep.join((str(Path(protocol["engine_root"]) / "src"), str(ROOT / "src"))))
    return env


def verify(protocol):
    for path, digest in protocol["sha256"].items():
        if sha(path) != digest:
            raise ValueError(f"frozen pilot artifact changed: {path}")


def freeze(args):
    from prepare_apple_cc89_handoff import CASES

    adapter = load_adapter()
    manifest_path = args.controls / "inputs.json"
    manifest = json.loads(manifest_path.read_text())
    expected = [(case_id, seed) for _, case_id in CASES for seed in (7, 19)]
    if [(row["case_id"], row["seed"]) for row in manifest["requests"]] != expected or manifest["inference_executed"]:
        raise ValueError("pilot requires the four original masks and seeds 7/19")
    bindings = {}

    def bind(path):
        path = path.absolute()
        bindings[str(path)] = sha(path)
        return str(path)

    jobs = []
    for row in manifest["requests"]:
        request_path = args.controls / row["case_id"] / f"request-seed{row['seed']}.json"
        if sha(request_path) != row["request_sha256"]:
            raise ValueError("materialized request digest changed")
        request = DiffusionRequest.from_json(request_path.read_text())
        adapter._require_corrected_mps_request(request, "mps")
        source = request_path.parent / request.normalized_pdb.path
        validate_context_source(request, source.read_bytes())
        positions, chains = source_context_position_features(request)
        if hashlib.sha256(np.asarray((positions, chains), dtype="<i8").tobytes()).hexdigest() != row["source_position_sha256"]:
            raise ValueError("materialized physical positions changed")
        jobs.append({**row, "request": bind(request_path), "source": bind(source)})
    if sha(args.checkpoint) != adapter._CHECKPOINT_SHA256 or sha(args.config) != adapter._CONFIG_SHA256:
        raise ValueError("checkpoint/config does not match cc89")
    for path in (*sorted((ROOT / "src/dvbfixer").rglob("*.py")),
            *sorted((ROOT / "deploy/protpardelle-1c").glob("*.py")),
            ROOT / "deploy/protpardelle-1c/apple-portability.patch", Path(__file__),
            ROOT / "scripts/prepare_apple_cc89_handoff.py", manifest_path, args.inventory,
            args.operator_comparison, args.config, args.checkpoint):
        bind(path)
    for name in ("models.py", "modules.py"):
        bind(args.engine_root / "src/protpardelle/core" / name)
    inventory = json.loads(args.inventory.read_text())
    bind(Path(inventory["environment_lock"]["path"]))
    # Bind both smoke summaries and coordinate payloads, not just comparison text.
    comparison = json.loads(args.operator_comparison.read_text())
    for device in ("cpu", "mps"):
        summary = args.operator_comparison.parent / f"{device}-operator-smoke.json"
        data = json.loads(summary.read_text())
        if (sha(summary) != comparison[f"{device}_summary_sha256"] or data["status"] != "passed"
                or data["device"] != device):
            raise ValueError("paired operator smokes do not match comparison")
        coordinate = summary.parent / data["coordinate_artifact"]
        if sha(coordinate) != data["coordinate_artifact_sha256"]:
            raise ValueError("operator-smoke coordinates changed")
        bind(summary)
        bind(coordinate)
    protocol = {"status": "frozen-before-corrected-mps-pilot", "profile": PROFILE,
        "jobs": jobs, "sha256": bindings, "public_promotion": False,
        "sampling_python": str(args.sampling_python), "refinement_python": str(args.refinement_python),
        "engine_root": str(args.engine_root), "checkpoint": str(args.checkpoint), "config": str(args.config),
        "parameters": {"steps": 500, "step_scale": 1.2, "s_churn": 200.0,
            "chain_phase_policy": "neutral-v1", "position_feature_policy": "source-physical-v1",
            "corrected_mps_research": True, "per_step_reinjection": False, "device_name": "mps", "mps_profile": False},
        "timeouts_seconds": {"probe": 300, "raw": 1800, "refine": 3600},
        "refinement_platform": "CPU", "solvent": False, "no_replacement": True,
        "reference_policy": "no native/reference PDB copied to workers; geometry and preservation primary; no RMSD seed selection",
        "inventory_scope": "clean baseline checkout; executed development source is separately digest-bound",
        "environment_exports": {}}
    for label in ("sampling", "refinement"):
        # Do NOT resolve interpreter symlinks: that can select the base env.
        python = protocol[f"{label}_python"]
        completed = subprocess.run([python, "-B", "-m", "pip", "freeze"], env=environment(protocol),
            capture_output=True, text=True, check=True, timeout=120)
        protocol["environment_exports"][label] = completed.stdout.splitlines()
    dump_new(args.protocol, protocol)
    print(json.dumps({"jobs": len(jobs), "protocol_sha256": sha(args.protocol)}))


def worker(args):
    protocol = json.loads(args.protocol.read_text())
    verify(protocol)
    workspace = args.workspace
    if (workspace / "reference.pdb").exists():
        raise ValueError("withheld reference cannot enter the worker")
    request_path = workspace / "request.json"
    if args.stage in {"raw", "probe"}:
        parameters = dict(protocol["parameters"])
        if args.stage == "probe":
            parameters["steps"] = 1
        output = workspace / "raw"
        output.mkdir()
        result, _ = load_adapter()._run_staged(request_path, output,
            Path(protocol["config"]), Path(protocol["checkpoint"]), **parameters)
        (workspace / "raw-result.json").write_text(result.to_json())
    else:
        from dvbfixer.model.diffusion.pipeline import _candidate_dat_record
        from dvbfixer.model.diffusion.runner_refinement import refine_runner_result

        raw = RunnerResult.from_json((workspace / "raw-result.json").read_text())
        result = refine_runner_result(request_path, raw, workspace / "refined", platform_name="CPU")
        (workspace / "refined-result.json").write_text(result.to_json())
        request = DiffusionRequest.from_json(request_path.read_text())
        for candidate in result.candidates:
            path = workspace / candidate.coordinate_artifact.path
            record = _candidate_dat_record(path.read_bytes(), {r for gap in request.gaps for r in gap.generated_residues})
            record.save(path.with_suffix(".dat"), verbose=False)


def prepare_workspace(workspace, job):
    if workspace.exists():
        raise FileExistsError("started pilot outcomes must not be replaced")
    workspace.mkdir(parents=True)
    request = DiffusionRequest.from_json(Path(job["request"]).read_text())
    destination = workspace / request.normalized_pdb.path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(job["source"], destination)
    shutil.copyfile(job["request"], workspace / "request.json")


def archive_inventory(workspace):
    return {path.relative_to(workspace).as_posix(): sha(path)
        for path in sorted(workspace.rglob("*")) if path.is_file() and path.name != "complete.json"}


def run_stage(protocol, protocol_path, workspace, stage):
    python = protocol["refinement_python" if stage == "refine" else "sampling_python"]
    try:
        with (workspace / f"{stage}.log").open("x") as log:
            result = subprocess.run([python, "-B", str(Path(__file__).absolute()), "worker", "--protocol", str(protocol_path),
                "--workspace", str(workspace), "--stage", stage], env=environment(protocol), cwd=workspace,
                stdout=log, stderr=subprocess.STDOUT, timeout=protocol["timeouts_seconds"][stage], check=False)
        return {"status": "completed" if result.returncode == 0 else "failed", "exit_code": result.returncode}
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}


def execute(args):
    protocol = json.loads(args.protocol.read_text())
    verify(protocol)
    if args.stage == "pilot":
        if args.probes is None:
            raise ValueError("pilot requires successful frozen one-step probes via --probes")
        for job in protocol["jobs"]:
            if job["seed"] != 7:
                continue
            probe_root = args.probes / job["case_id"] / "seed7"
            marker = json.loads((probe_root / "complete.json").read_text())
            if (marker["protocol_sha256"] != sha(args.protocol) or marker["job"] != job
                    or marker["artifacts"] != archive_inventory(probe_root)
                    or marker["stages"].get("probe", {}).get("status") != "completed"):
                raise ValueError("corrected one-step probe did not pass under this frozen protocol")
    jobs = protocol["jobs"] if args.stage == "pilot" else [job for job in protocol["jobs"] if job["seed"] == 7]
    for job in jobs:
        workspace = args.output / job["case_id"] / f"seed{job['seed']}"
        marker = workspace / "complete.json"
        if marker.exists():
            archived = json.loads(marker.read_text())
            if (archived["protocol_sha256"] != sha(args.protocol) or archived["job"] != job
                    or archived["artifacts"] != archive_inventory(workspace)):
                raise ValueError("resume archive identity/digests changed")
            continue
        if workspace.exists():
            raise ValueError(f"interrupted outcome remains terminal; inspect rather than retry: {workspace}")
        prepare_workspace(workspace, job)
        stages = ("probe",) if args.stage == "probe" else ("raw", "refine")
        outcomes = {}
        for stage in stages:
            outcomes[stage] = run_stage(protocol, args.protocol, workspace, stage)
            if outcomes[stage]["status"] != "completed":
                break
        dump_new(marker, {"protocol_sha256": sha(args.protocol), "job": job, "stages": outcomes,
            "artifacts": archive_inventory(workspace)})
        print(json.dumps({"case_id": job["case_id"], "seed": job["seed"], "stages": outcomes}), flush=True)


def audit(args):
    from dvbfixer.ffutils.dat import DatRecord

    protocol = json.loads(args.protocol.read_text())
    verify(protocol)
    rows = []
    for job in protocol["jobs"]:
        workspace = args.output / job["case_id"] / f"seed{job['seed']}"
        marker = json.loads((workspace / "complete.json").read_text())
        if (marker["protocol_sha256"] != sha(args.protocol) or marker["job"] != job
                or marker["artifacts"] != archive_inventory(workspace)):
            raise ValueError("pilot archive identity/digests changed")
        request = DiffusionRequest.from_json((workspace / "request.json").read_text())
        if sha(workspace / "request.json") != job["request_sha256"]:
            raise ValueError("executed request differs from frozen request")
        row = {"case_id": job["case_id"], "seed": job["seed"], "stages": marker["stages"]}
        if all(marker["stages"].get(stage, {}).get("status") == "completed" for stage in ("raw", "refine")):
            result = RunnerResult.from_json((workspace / "refined-result.json").read_text())
            validated, = validate_runner_result(request, result, workspace=workspace)
            candidate = validated.candidate
            trace = SamplerTrace.from_json((workspace / candidate.sampler_trace_artifact.path).read_text())
            if (trace.profile != PROFILE or trace.device != "mps" or not trace.fallback_disabled
                    or trace.denoising_update_count != 500 or trace.callback_update_count != 0
                    or (not candidate.postprocessing_failures and not any(
                        option.name == "platform" and option.value == "CPU" for option in trace.refinement_parameters))):
                raise ValueError("pilot trace lacks actual corrected MPS/CPU refinement evidence")
            flags = result.backend_provenance.deterministic_flags
            if f"cc89-position-features-sha256={job['source_position_sha256']}" not in flags:
                raise ValueError("pilot source-position provenance changed")
            summary = json.loads((workspace / "raw/summary.json").read_text())
            if not summary.get("source_position_probes") or any(probe["calls"] != 1000 for probe in summary["source_position_probes"]):
                raise ValueError("missing actual first-layer RoPE evidence")
            data = (workspace / candidate.coordinate_artifact.path).read_bytes()
            source = (workspace / request.normalized_pdb.path).read_bytes()
            generated = {r for gap in request.gaps for r in gap.generated_residues}

            def outside(payload, generated=generated):
                return [line for line in payload.splitlines(keepends=True) if line.startswith((b"ATOM  ", b"HETATM"))
                    and (line[21:22].decode(), line[22:26].strip().decode(), line[26:27].strip().decode())
                    not in {(r.chain, r.residue_number, r.insertion_code) for r in generated}]

            if outside(data) != outside(source):
                raise ValueError("pilot changed outside-gap atom records")
            restored = DatRecord.load((workspace / candidate.coordinate_artifact.path).with_suffix(".dat"))
            identities = {(a["chain"], a["resid"], a["icode"], a["atom"]) for a in restored.added_atoms}
            if identities != {(a.chain, a.residue_number, a.insertion_code, a.atom_name) for a in request.generated_atoms}:
                raise ValueError("generated-atom .dat handoff differs from request")
            row.update(validation=asdict(validated.summary), outside_gap_atom_records_identical=True,
                dat_generated_atom_count=len(identities), coordinate_sha256=sha(workspace / candidate.coordinate_artifact.path),
                sampling_resources=summary["resource_metrics"], profile=trace.profile,
                postprocessing_failures=candidate.postprocessing_failures)
        rows.append(row)
    dump_new(args.report, {"protocol_sha256": sha(args.protocol), "planned_outcomes": 8,
        "accepted": sum(row.get("validation", {}).get("passed", False) for row in rows),
        "public_promotion": False, "reference_rmsd_used": False, "rows": rows})
    print(args.report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    freezing = commands.add_parser("freeze")
    for name in ("controls", "inventory", "operator-comparison", "sampling-python", "refinement-python", "engine-root", "checkpoint", "config"):
        freezing.add_argument("--" + name, type=Path, required=True)
    for action in ("freeze", "run", "worker", "audit"):
        command = freezing if action == "freeze" else commands.add_parser(action)
        command.add_argument("--protocol", type=Path, required=True)
        if action in {"run", "audit"}:
            command.add_argument("--output", type=Path, required=True)
        if action == "run":
            command.add_argument("--stage", choices=("probe", "pilot"), required=True)
            command.add_argument("--probes", type=Path)
        if action == "worker":
            command.add_argument("--workspace", type=Path, required=True)
            command.add_argument("--stage", choices=("raw", "refine", "probe"), required=True)
        if action == "audit":
            command.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.expanduser().absolute())
    {"freeze": freeze, "run": execute, "worker": worker, "audit": audit}[args.action](args)


if __name__ == "__main__":
    main()
