#!/usr/bin/env python3
"""Sequential frozen protein-context ablations with native work and durable evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path

from dvbfixer.model.diffusion.contract import BackendOption, DiffusionRequest, ProteinContextPolicy
from dvbfixer.model.diffusion.protein_context import select_protein_context

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]

POLICIES = {
    "anchors-gap": ProteinContextPolicy(target_flanks=1, partner_mode="none"),
    "sequence-8": ProteinContextPolicy(target_flanks=8, partner_mode="none"),
    "sequence-16": ProteinContextPolicy(target_flanks=16, partner_mode="none"),
    "same-chain-spatial": ProteinContextPolicy(target_flanks=8, same_chain_spatial=True, partner_mode="none"),
    "local-partner": ProteinContextPolicy(target_flanks=8, same_chain_spatial=True),
    "full-protein": ProteinContextPolicy(partner_mode="full"),
    "template-only": ProteinContextPolicy(target_flanks=8, same_chain_spatial=True),
    "local-partner-refined": ProteinContextPolicy(target_flanks=8, same_chain_spatial=True),
    "direct-shell": ProteinContextPolicy(target_flanks=8, same_chain_spatial=True, secondary_radius_angstrom=6.0),
    "budget-64": ProteinContextPolicy(target_flanks=8, same_chain_spatial=True, residue_budget=64),
}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def diagnostic_workspace(args, case_id, arm):
    """Retain failed-run diagnostics before the private native workspace is removed."""
    with tempfile.TemporaryDirectory(prefix="context-arm-", dir=args.work_parent) as directory:
        workspace = Path(directory)
        try:
            yield workspace
        except Exception as exc:
            destination = args.output / "failures" / case_id / f"{arm}-{uuid.uuid4().hex}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(workspace, destination)
            (destination / "failure.json").write_text(json.dumps({
                "case_id": case_id, "arm": arm,
                "exception_type": type(exc).__name__, "message": str(exc),
            }, indent=2) + "\n")
            raise


def worker(args):
    from dvbfixer.model.diffusion.benchmark import candidate_quality, load_pdb_coordinates
    from dvbfixer.model.diffusion.contract import ArtifactReference
    from dvbfixer.model.diffusion.runner_refinement import refine_runner_result
    from dvbfixer.model.diffusion.sampler import SamplingAblationMode
    from dvbfixer.model.diffusion.validate import build_validated_result

    production = _load("context_production", ROOT / "deploy/protenix-v1/production_runner.py")
    production._verify_checkpoint(args.checkpoint)
    production._verify_profile_environment()
    _load("reinjection", ROOT / "deploy/protenix-v1/reinjection.py")
    builder = _load("context_builder", ROOT / "deploy/protenix-v1/build-template-input.py")
    adapter = _load("context_checkpoint", ROOT / "deploy/protenix-v1/checkpoint_gap_smoke.py")
    request_path = args.workspace / "request.json"
    request = DiffusionRequest.from_json(request_path.read_text())
    input_path = builder.build_input(request_path, args.workspace / "input-features")
    mode = SamplingAblationMode.TEMPLATE_ONLY if args.arm == "template-only" else SamplingAblationMode.REINJECTION
    probe_supported = any(item.atom.chain not in {gap.chain for gap in request.gaps} for item in request.protein_context.fixed_conditioning)
    result, raw_summary_path = adapter.run(request_path, input_path, args.workspace / "raw", args.kalign,
                                         args.checkpoint, cycles=1, steps=200, ablation_mode=mode,
                                         context_probe=probe_supported and args.arm in {"local-partner", "full-protein", "local-partner-refined"})
    if args.arm == "local-partner-refined":
        result = refine_runner_result(request_path, result, args.workspace / "refined", platform_name="Reference")
    validated = build_validated_result(request, result, workspace=args.workspace)
    summary = validated.validation_summaries[0]
    candidate = result.candidates[0]
    reference_path = args.workspace / "reference.pdb"
    quality = candidate_quality(
        candidate.candidate_id,
        load_pdb_coordinates(args.workspace, ArtifactReference("reference.pdb", hashlib.sha256(reference_path.read_bytes()).hexdigest())),
        load_pdb_coordinates(args.workspace, candidate.coordinate_artifact),
        generated_residues=set(candidate.generated_residues), fixed_atoms=set(request.fixed_atoms),
        anchor_residues={anchor for gap in request.gaps for anchor in (gap.left_anchor, gap.right_anchor) if anchor is not None},
        closure_passed="junction-peptide-connectivity" not in summary.hard_gate_failures,
        validation_passed=summary.passed,
        interface_chain_pairs=tuple((request.gaps[0].chain, target.chain) for target in request.target_sequences if target.chain != request.gaps[0].chain),
        expected_generated_atoms=set(request.generated_atoms),
    )
    raw = json.loads(raw_summary_path.read_text())
    output = {"schema_version": 1, "arm": args.arm, "validation": asdict(summary),
              "quality": asdict(quality), "resources": asdict(result.resource_metrics),
              "candidate": asdict(candidate), "denoiser_context_probe": raw.get("denoiser_context_probe")}
    (args.workspace / "outcome.json").write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")


def run(args):
    manifest = json.loads(args.manifest.read_text())
    manifest_digest = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    if manifest["status"] != "frozen-before-context-inference" or not manifest["no_replacement"]:
        raise ValueError("context acceptance requires a frozen no-replacement manifest")
    args.output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTHONPATH=os.pathsep.join((str(args.engine_root), str(ROOT / "src"))),
                       PATH=str(args.kalign.parent) + os.pathsep + environment.get("PATH", ""),
                       PROTENIX_ROOT_DIR=str(args.engine_root), LAYERNORM_TYPE="torch")
    records = []
    for case in manifest["cases"]:
        if args.case and case["case_id"] not in args.case:
            continue
        if case["status"] != "eligible":
            records.append({"case_id": case["case_id"], "status": "unsupported", "reason": case["reason"]})
            continue
        source = args.cohort / case["case_id"]
        for relative, digest in case["artifacts"].items():
            if hashlib.sha256((source / relative).read_bytes()).hexdigest() != digest:
                raise ValueError("context materialization digest changed")
        original = DiffusionRequest.from_json((source / "request.json").read_text())
        for arm in args.arm or case.get("arms", manifest["arms"]):
            support = case.get("arm_support", {}).get(arm, {})
            if support.get("status") == "unsupported":
                records.append({"case_id": case["case_id"], "arm": arm, **support})
                continue
            destination = args.output / case["case_id"] / arm
            if destination.exists():
                completion = json.loads((destination / "complete.json").read_text())
                if completion["manifest_sha256"] != manifest_digest:
                    raise ValueError("existing context outcome belongs to another manifest")
                for relative, digest in completion["artifacts"].items():
                    if hashlib.sha256((destination / relative).read_bytes()).hexdigest() != digest:
                        raise ValueError("existing context outcome digest changed")
                records.append({"case_id": case["case_id"], "arm": arm, "resumed": True})
                continue
            with diagnostic_workspace(args, case["case_id"], arm) as workspace:
                (workspace / "input").mkdir()
                shutil.copyfile(source / "input/normalized.pdb", workspace / "input/normalized.pdb")
                shutil.copyfile(source / "reference.pdb", workspace / "reference.pdb")
                request = select_protein_context(original, (workspace / "input/normalized.pdb").read_bytes(), POLICIES[arm])
                if arm == "template-only":
                    request = replace(request, backend_options=(BackendOption("profile", "protenix-v1-template-only-research"),))
                (workspace / "request.json").write_text(request.to_json())
                with (workspace / "worker.log").open("xb") as log:
                    subprocess.run([str(args.backend_python), str(Path(__file__).resolve()), "worker", "--workspace", str(workspace),
                                    "--arm", arm, "--checkpoint", str(args.checkpoint), "--kalign", str(args.kalign)],
                                   env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=3600)
                outcome = json.loads((workspace / "outcome.json").read_text())
                if arm in {"local-partner", "full-protein"}:
                    probe = outcome["denoiser_context_probe"]
                    if probe is None or probe["repeat_max_abs_delta_angstrom"] != 0.0 or probe["generated_response_max_displacement_angstrom"] < manifest["primary_causal_gate"]["minimum_generated_response_angstrom"]:
                        raise ValueError("frozen causal denoiser gate failed; remaining inference stopped")
                destination.parent.mkdir(parents=True, exist_ok=True)
                staging = destination.with_name(f".{arm}.staging")
                if staging.exists():
                    raise ValueError("interrupted archive staging requires inspection")
                shutil.copytree(workspace, staging)
                completion = {"manifest_sha256": manifest_digest, "artifacts": {
                    path.relative_to(staging).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in staging.rglob("*") if path.is_file()
                }}
                (staging / "complete.json").write_text(json.dumps(completion, indent=2, sort_keys=True) + "\n")
                staging.rename(destination)
                records.append({"case_id": case["case_id"], "arm": arm, "validation_passed": outcome["validation"]["passed"]})
                print(json.dumps(records[-1]), flush=True)
    (args.output / "report.json").write_text(json.dumps({"manifest_sha256": manifest_digest, "records": records}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    worker_parser = subparsers.add_parser("worker")
    worker_parser.add_argument("--workspace", type=Path, required=True)
    worker_parser.add_argument("--arm", required=True)
    run_parser = subparsers.add_parser("run")
    for name in ("manifest", "cohort", "output", "work-parent", "backend-python", "engine-root"):
        run_parser.add_argument("--" + name, type=Path, required=True)
    run_parser.add_argument("--case", action="append", default=[])
    run_parser.add_argument("--arm", action="append", choices=tuple(POLICIES), default=[])
    for command_parser in (worker_parser, run_parser):
        command_parser.add_argument("--checkpoint", type=Path, required=True)
        command_parser.add_argument("--kalign", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.absolute())
    worker(args) if args.action == "worker" else run(args)


if __name__ == "__main__":
    main()
