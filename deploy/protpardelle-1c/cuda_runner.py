#!/usr/bin/env python3
"""Public cc89 CUDA launcher with isolated CUDA refinement, without fallback."""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
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
from dvbfixer.model.diffusion.protein_context import validate_cuda_cc89_request
from dvbfixer.model.diffusion.runner import DIFFUSION_RUNNER_PROTOCOL_VERSION
from dvbfixer.model.diffusion.scope import assess_diffusion_scope
from dvbfixer.model.diffusion.validate import validate_runner_result

PROFILE = "protpardelle-1c-cuda"
METADATA = DIFFUSION_PROFILES[PROFILE]
ENVIRONMENT = "linux-amd64;cc89-cuda-v1;python=3.12;torch=2.6.0+cu124;refinement=openmm-8.6.1-cuda"
SOURCE_HASHES = {
    "src/protpardelle/core/models.py": "2ec52fee68368ba3addfa4b46eec70949c6730801f05cb309c8eb5ed22f1f810",
    "src/protpardelle/core/modules.py": "3fe69476e45932c04c56332e09f0e3b2b51cc77f3effe861d93c37d975a529a3",
}
CONFIG_SHA256 = "e9999ace79bf3044351cc982a624fc3459add3a4f91cbf97ff5b437b8942eb9d"


def _adapter():
    spec = importlib.util.spec_from_file_location("cc89_cuda_adapter", Path(__file__).with_name("checkpoint_gap_smoke.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("cc89 adapter is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path):
    import hashlib

    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def refinement_environment(python):
    # A host environment may contain a newer nvcc than the installed driver can
    # execute. Use the refinement runtime's compiler/toolchain, never that host
    # environment's PATH (which can otherwise produce unsupported PTX).
    libraries = sorted((python.parent.parent / "lib/python3.13/site-packages/nvidia").glob("*/lib"))
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "OPENMM_CPU_THREADS": "1",
            "PATH": str(python.parent) + os.pathsep + os.defpath,
            "LD_LIBRARY_PATH": os.pathsep.join(str(path) for path in libraries)}


def refinement_preflight():
    import numpy as np
    import openmm

    if sys.version_info[:2] != (3, 13) or openmm.__version__ != "8.6.1" or np.__version__ != "2.4.6":
        raise RuntimeError("refinement requires Python 3.13, OpenMM 8.6.1 and NumPy 2.4.6")
    system = openmm.System()
    system.addParticle(12)
    force = openmm.CustomExternalForce("x*x+y*y+z*z")
    force.addParticle(0, [])
    system.addForce(force)
    integrator = openmm.VerletIntegrator(0.001)
    context = openmm.Context(system, integrator, openmm.Platform.getPlatformByName("CUDA"),
                             {"Precision": "mixed", "DeterministicForces": "true"})
    context.setPositions([[1, 1, 1]])
    energy = context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(openmm.unit.kilojoule_per_mole)
    if not np.isclose(energy, 3):
        raise RuntimeError("CUDA refinement force-kernel probe failed")


def preflight_report(profile, checkpoint, refinement_python):
    issues = []
    revision, framework, device, digest = "", "", "", ""

    def issue(code, text):
        issues.append(AdapterPreflightIssue(code, text))

    if profile != PROFILE or sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        issue(AdapterPreflightCode.INCOMPATIBLE_PLATFORM, "cc89 CUDA requires Linux amd64 and the matching profile")
    if sys.version_info[:2] != (3, 12) or os.environ.get("PYTHONNOUSERSITE") != "1":
        issue(AdapterPreflightCode.INCOMPATIBLE_ENVIRONMENT, "sampling requires isolated Python 3.12")
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
    try:
        spec = importlib.util.find_spec("protpardelle")
        if spec is None or spec.origin is None:
            raise ValueError("engine unavailable")
        root = Path(spec.origin).resolve().parents[2]
        revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                                  capture_output=True, text=True, timeout=10).stdout.strip()
        changed = subprocess.run(["git", "-C", str(root), "diff", "--name-only", "HEAD", "--"], check=True,
                                 capture_output=True, text=True, timeout=10).stdout.splitlines()
        untracked = subprocess.run(["git", "-C", str(root), "ls-files", "--others", "--", "*.py", "*.pyc", "*.so", "*.pyd", "*.dylib"],
                                   check=True, capture_output=True, text=True, timeout=10).stdout.splitlines()
        if (revision != METADATA.source_revision or set(changed) != {"src/protpardelle/core/models.py"}
                or untracked or any(_sha(root / name) != value for name, value in SOURCE_HASHES.items())):
            raise ValueError("source state mismatch")
    except (OSError, ValueError, subprocess.SubprocessError):
        issue(AdapterPreflightCode.INCOMPATIBLE_SOURCE, "engine must match the frozen callback-patch source, without extra modules/bytecode")
    try:
        import torch

        framework = torch.__version__.split("+")[0]
        if torch.__version__ != "2.6.0+cu124":
            issue(AdapterPreflightCode.INCOMPATIBLE_FRAMEWORK, "sampling requires PyTorch 2.6.0+cu124")
        if not torch.cuda.is_available():
            issue(AdapterPreflightCode.MISSING_CUDA, "CUDA sampling device unavailable")
        else:
            device = f"cuda:{torch.cuda.current_device()}"
    except (ImportError, RuntimeError):
        issue(AdapterPreflightCode.INCOMPATIBLE_FRAMEWORK, "CUDA sampling runtime unavailable")
    try:
        subprocess.run([str(refinement_python), str(Path(__file__).resolve()), "--refinement-preflight"],
                       env=refinement_environment(refinement_python), check=True, capture_output=True, timeout=90)
    except (OSError, subprocess.SubprocessError) as exc:
        detail = (getattr(exc, "stderr", b"") or b"").decode(errors="replace").strip().splitlines()
        issue(AdapterPreflightCode.INCOMPATIBLE_REFINEMENT_PLATFORM,
              "isolated CUDA refinement runtime/kernel probe failed" + (": " + detail[-1][-160:] if detail else ""))
    return RunnerPreflightReport(profile, DIFFUSION_RUNNER_PROTOCOL_VERSION, DIFFUSION_SCHEMA_VERSION,
        runtime_preflight_facts(engine_revision=revision, patch_identity=METADATA.patch_identity,
            environment_identity=ENVIRONMENT, checkpoint_sha256=digest, framework_version=framework,
            accelerator_available=bool(device), effective_device=device, fallback_disabled=True,
            sampling_platform=METADATA.sampling_platform, refinement_platform=METADATA.refinement_platform), tuple(issues))


def run(args):
    if os.environ.get("DVBFIXER_DIFFUSION_PROTOCOL_VERSION") != str(DIFFUSION_RUNNER_PROTOCOL_VERSION):
        raise RuntimeError("incompatible execution protocol")
    report = preflight_report(args.profile, args.checkpoint, args.refinement_python)
    if not report.passed:
        raise RuntimeError("; ".join(issue.message for issue in report.issues))
    request_path = Path(os.environ.get("DVBFIXER_DIFFUSION_REQUEST", "request.json")).resolve()
    result_path = Path(os.environ.get("DVBFIXER_DIFFUSION_RESULT", "result.json"))
    request = DiffusionRequest.from_json(request_path.read_text())
    validate_cuda_cc89_request(request)
    admission = assess_diffusion_scope(request, (request_path.parent / request.normalized_pdb.path).read_bytes())
    if not admission.supported:
        raise ValueError("unsupported CUDA cc89 input: " + ", ".join(admission.reasons))
    os.environ["PROTPARDELLE_MODEL_PARAMS"] = str(args.checkpoint.parent.parent)
    adapter = _adapter()
    root = Path("candidates") / PROFILE
    results = []
    for seed in request.seeds:
        directory = root / f"seed-{seed}"
        (directory / "raw").mkdir(parents=True)
        # Sampling accepts one candidate; retain the original source directory so
        # every artifact and context identity stays bound to the public request.
        single_path = request_path.parent / f"sampling-seed-{seed}.json"
        single_path.write_text(replace(request, seeds=(seed,), candidate_count=1).to_json())
        raw, _ = adapter._run_staged(single_path, directory / "raw",
            args.checkpoint.parent.parent / "configs/cc89.yaml", args.checkpoint,
            device_name="cuda", mps_profile=False, steps=500, step_scale=1.2, s_churn=200.0,
            per_step_reinjection=False, chain_phase_policy="neutral-v1", position_feature_policy="source-physical-v1")
        raw_path = directory / "raw-result.json"
        raw_path.write_text(raw.to_json())
        refined_path = directory / "refined-result.json"
        subprocess.run([str(args.refinement_python), str(Path(__file__).resolve()), "--refine-worker",
            "--request", str(single_path), "--raw-result", str(raw_path), "--output", str(directory / "refined"),
            "--result", str(refined_path)], env=refinement_environment(args.refinement_python), check=True)
        refined = RunnerResult.from_json(refined_path.read_text())
        validate_runner_result(replace(request, seeds=(seed,), candidate_count=1), refined, workspace=request_path.parent)
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
        result = refine_runner_result(args.request, raw, args.output, platform_name="CUDA")
        args.result.write_text(result.to_json())
        return
    if args.checkpoint is None or args.refinement_python is None:
        parser.error("--checkpoint and --refinement-python are required")
    args.checkpoint = args.checkpoint.expanduser().resolve()
    # Resolving a venv's Python symlink selects its base interpreter and silently
    # loses the isolated OpenMM/CUDA packages.
    args.refinement_python = args.refinement_python.expanduser().absolute()
    if args.preflight:
        print(preflight_report(args.profile, args.checkpoint, args.refinement_python).to_json(), end="")
    else:
        run(args)


if __name__ == "__main__":
    main()
