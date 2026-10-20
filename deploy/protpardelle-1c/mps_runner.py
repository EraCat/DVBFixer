#!/usr/bin/env python3
"""Versioned corrected Apple cc89 launcher with isolated CPU refinement."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    DiffusionRequest,
    RunnerResourceMetrics,
    RunnerResult,
)
from dvbfixer.model.diffusion.preflight import (
    DIFFUSION_PROFILES,
    AdapterPreflightCode,
    AdapterPreflightIssue,
    RunnerPreflightReport,
    runtime_preflight_facts,
)
from dvbfixer.model.diffusion.protein_context import MPS_CC89_PROFILE, validate_mps_cc89_request
from dvbfixer.model.diffusion.runner import DIFFUSION_RUNNER_PROTOCOL_VERSION
from dvbfixer.model.diffusion.scope import assess_diffusion_scope
from dvbfixer.model.diffusion.validate import validate_runner_result

PROFILE = MPS_CC89_PROFILE
METADATA = DIFFUSION_PROFILES[PROFILE]
ENVIRONMENT = "macos-arm64;cc89-local-v1;python=3.12;torch=2.6.0;refinement=openmm-8.5.2-cpu"
CONFIG_SHA256 = "e9999ace79bf3044351cc982a624fc3459add3a4f91cbf97ff5b437b8942eb9d"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"cc89_apple_{name}", Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("Apple cc89 adapter is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def refinement_environment(python):
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
        "OPENMM_CPU_THREADS": "1", "PATH": str(python.parent) + os.pathsep + os.defpath}


def refinement_preflight():
    import platform

    import numpy as np
    import openmm

    if (sys.platform != "darwin" or platform.machine() != "arm64" or sys.version_info[:2] != (3, 12)
            or openmm.__version__ != "8.5.2" or np.__version__ != "2.4.6"):
        raise RuntimeError("Apple refinement requires native arm64 Python 3.12, OpenMM 8.5.2 and NumPy 2.4.6")
    system = openmm.System()
    system.addParticle(12)
    force = openmm.CustomExternalForce("x*x+y*y+z*z")
    force.addParticle(0, [])
    system.addForce(force)
    integrator = openmm.VerletIntegrator(0.001)
    context = openmm.Context(system, integrator, openmm.Platform.getPlatformByName("CPU"), {"Threads": "1"})
    context.setPositions([[1, 1, 1]])
    energy = context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(openmm.unit.kilojoule_per_mole)
    if not np.isclose(energy, 3):
        raise RuntimeError("CPU refinement force-kernel probe failed")


def preflight_report(profile, checkpoint, refinement_python):
    issues = []
    framework, device, digest = "", "", ""

    def issue(code, message):
        issues.append(AdapterPreflightIssue(code, message))

    if profile != PROFILE:
        issue(AdapterPreflightCode.INCOMPATIBLE_ENVIRONMENT, "runner does not support the requested profile")
    try:
        _load("production_runner")._verify_profile_environment()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        issue(AdapterPreflightCode.INCOMPATIBLE_SOURCE, str(exc))
    try:
        if checkpoint.is_symlink() or not checkpoint.is_file():
            raise ValueError("checkpoint is not a regular file")
        digest = _sha(checkpoint)
        if digest != METADATA.expected_checkpoint_sha256:
            issue(AdapterPreflightCode.CHECKPOINT_DIGEST_MISMATCH, "cc89 checkpoint digest mismatch")
        if _sha(checkpoint.parent.parent / "configs/cc89.yaml") != CONFIG_SHA256:
            issue(AdapterPreflightCode.INCOMPATIBLE_ENVIRONMENT, "cc89 config digest mismatch")
    except (OSError, ValueError):
        issue(AdapterPreflightCode.MISSING_CHECKPOINT, "cc89 checkpoint/config unavailable")
    fallback_disabled = os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "0"
    if not fallback_disabled:
        issue(AdapterPreflightCode.FALLBACK_ENABLED, "PYTORCH_ENABLE_MPS_FALLBACK=0 is required")
    try:
        import torch

        framework = torch.__version__.split("+")[0]
        if framework != "2.6.0":
            issue(AdapterPreflightCode.INCOMPATIBLE_FRAMEWORK, "sampling requires PyTorch 2.6.0")
        if not torch.backends.mps.is_built() or not torch.backends.mps.is_available():
            issue(AdapterPreflightCode.MISSING_MPS, "MPS sampling device unavailable")
        else:
            device = "mps"
    except (ImportError, RuntimeError):
        issue(AdapterPreflightCode.INCOMPATIBLE_FRAMEWORK, "MPS sampling runtime unavailable")
    try:
        subprocess.run([str(refinement_python), str(Path(__file__).resolve()), "--refinement-preflight"],
            env=refinement_environment(refinement_python), check=True, capture_output=True, timeout=90)
    except (OSError, subprocess.SubprocessError):
        issue(AdapterPreflightCode.INCOMPATIBLE_REFINEMENT_PLATFORM, "isolated CPU refinement runtime/kernel probe failed")
    return RunnerPreflightReport(PROFILE, DIFFUSION_RUNNER_PROTOCOL_VERSION, DIFFUSION_SCHEMA_VERSION,
        runtime_preflight_facts(engine_revision=METADATA.source_revision, patch_identity=METADATA.patch_identity,
            environment_identity=ENVIRONMENT, checkpoint_sha256=digest, framework_version=framework,
            accelerator_available=bool(device), effective_device=device, fallback_disabled=fallback_disabled,
            sampling_platform=METADATA.sampling_platform, refinement_platform=METADATA.refinement_platform), tuple(issues))


def _sampling_provenance(provenance):
    # The shared refiner owns its own operation annotation. Adding CPU here
    # makes refinement's immutable provenance fail the duplicate-entry guard.
    return replace(provenance, source_license="MIT", environment_identity=ENVIRONMENT,
        known_nondeterministic_operations=("PyTorch MPS sampling",))


def run(args):
    if os.environ.get("DVBFIXER_DIFFUSION_PROTOCOL_VERSION") != str(DIFFUSION_RUNNER_PROTOCOL_VERSION):
        raise RuntimeError("incompatible execution protocol")
    report = preflight_report(args.profile, args.checkpoint, args.refinement_python)
    if not report.passed:
        raise RuntimeError("; ".join(issue.message for issue in report.issues))
    request_path = Path(os.environ.get("DVBFIXER_DIFFUSION_REQUEST", "request.json")).resolve()
    result_path = Path(os.environ.get("DVBFIXER_DIFFUSION_RESULT", "result.json"))
    request = DiffusionRequest.from_json(request_path.read_text())
    validate_mps_cc89_request(request)
    admission = assess_diffusion_scope(request, (request_path.parent / request.normalized_pdb.path).read_bytes())
    if not admission.supported:
        raise ValueError("unsupported MPS cc89 input: " + ", ".join(admission.reasons))
    os.environ["PROTPARDELLE_MODEL_PARAMS"] = str(args.checkpoint.parent.parent)
    adapter = _load("checkpoint_gap_smoke")
    results = []
    for seed in request.seeds:
        single = replace(request, seeds=(seed,), candidate_count=1)
        single_path = request_path.parent / f"sampling-seed-{seed}.json"
        single_path.write_text(single.to_json())
        directory = request_path.parent / "candidates" / PROFILE / f"seed-{seed}"
        (directory / "raw").mkdir(parents=True, exist_ok=False)
        raw, _ = adapter._run_staged(single_path, directory / "raw",
            args.checkpoint.parent.parent / "configs/cc89.yaml", args.checkpoint,
            device_name="mps", mps_profile=False, steps=500, step_scale=1.2, s_churn=200.0,
            per_step_reinjection=False, chain_phase_policy="neutral-v1", position_feature_policy="source-physical-v1")
        raw = replace(raw, backend_provenance=_sampling_provenance(raw.backend_provenance))
        raw_path = directory / "raw-result.json"
        raw_path.write_text(raw.to_json())
        refined_path = directory / "refined-result.json"
        subprocess.run([str(args.refinement_python), str(Path(__file__).resolve()), "--refine-worker",
            "--request", str(single_path), "--raw-result", str(raw_path), "--output", str(directory / "refined"),
            "--result", str(refined_path)], env=refinement_environment(args.refinement_python), check=True)
        refined = RunnerResult.from_json(refined_path.read_text())
        validate_runner_result(single, refined, workspace=request_path.parent)
        results.append(refined)
    result = replace(results[0], candidates=tuple(candidate for item in results for candidate in item.candidates),
        resource_metrics=RunnerResourceMetrics(
            wall_time_seconds=sum(item.resource_metrics.wall_time_seconds or 0 for item in results),
            model_load_seconds=sum(item.resource_metrics.model_load_seconds or 0 for item in results),
            peak_ram_bytes=max((item.resource_metrics.peak_ram_bytes or 0 for item in results), default=0),
            peak_vram_bytes=max((item.resource_metrics.peak_vram_bytes or 0 for item in results), default=0)))
    result_path.write_text(result.to_json())


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=PROFILE)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--refinement-python", type=Path)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--refinement-preflight", action="store_true")
    parser.add_argument("--refine-worker", action="store_true")
    for name in ("request", "raw-result", "output", "result"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.refinement_preflight:
        refinement_preflight()
        return
    if args.refine_worker:
        from dvbfixer.model.diffusion.runner_refinement import refine_runner_result

        refinement_preflight()
        raw = RunnerResult.from_json(args.raw_result.read_text())
        result = refine_runner_result(args.request, raw, args.output, platform_name="CPU")
        args.result.write_text(result.to_json())
        return
    if args.checkpoint is None or args.refinement_python is None:
        parser.error("--checkpoint and --refinement-python are required")
    args.checkpoint = args.checkpoint.expanduser().absolute()
    args.refinement_python = args.refinement_python.expanduser().absolute()
    if args.preflight:
        print(preflight_report(args.profile, args.checkpoint, args.refinement_python).to_json(), end="")
    else:
        run(args)


if __name__ == "__main__":
    main()
