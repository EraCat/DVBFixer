#!/usr/bin/env python3
"""Freeze and run the explicit CUDA-only cc89 denoiser chain-phase repair.

The ordinary research runner and validator are used, with unchanged input
coordinates, gap masks, conditioning density, noise, seed, and geometry gates.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import replace
from pathlib import Path

import debug_cc89_conditioning as debug
import run_cc89_cuda_controls as controls
from run_a100_relaxation import verify_inventory

from dvbfixer.model.diffusion.contract import BackendOption, DiffusionRequest

ROOT = debug.ROOT


def freeze(args):
    if args.cohort.exists() or args.manifest.exists():
        raise ValueError("chain-phase repair needs a new cohort and manifest")
    previous = json.loads(args.source_manifest.read_text())
    previous_cases = {case["case_id"]: case for case in previous["cases"] if case["kind"] == "cc89-rich"}
    args.cohort.mkdir(parents=True)
    for name in debug.CASES:
        source = args.source_cohort / name
        verify_inventory(source, previous_cases[name]["artifacts"])
        destination = args.cohort / name
        shutil.copytree(source, destination)
        request_path = destination / "request.json"
        request = DiffusionRequest.from_json(request_path.read_text())
        request = replace(request, backend_options=(*request.backend_options, BackendOption("cc89_chain_phase", "neutral-v1")))
        request_path.write_text(request.to_json())
    controls.CONFIGURATIONS = {
        name: {"step_scale": 1.2, "s_churn": 200.0, "per_step_reinjection": projected,
            "crop_strategy": "backbone-sidechain", "replacement_guidance": False, "chain_phase_policy": "neutral-v1"}
        for name, projected in (("neutral-native", False), ("neutral-projected", True))
    }
    controls.freeze(args)
    protocol = json.loads(args.manifest.read_text())
    protocol.update(source_manifest_sha256=debug.sha(args.source_manifest),
        coordinator_sha256=debug.sha(Path(__file__).resolve()), controls_sha256=debug.sha(ROOT / "scripts/run_cc89_cuda_controls.py"),
        config_sha256=debug.sha(ROOT / debug.CONFIG), checkpoint_sha256=debug.sha(ROOT / debug.CHECKPOINT),
        rationale="Matched CUDA repair confirmation after chain-phase-only controls reduced gap RMSD from 13-20A to 0.35-0.88A; preserve original sampler chains and residue gaps",
        expected_intervention="denoiser rotary chain-phase only; no token/coordinate/motif/gap change",
        public_promotion=False, apple_mps="deferred")
    for case in protocol["cases"]:
        case.update(kind="cc89-rich", arms=list(controls.CONFIGURATIONS))
    args.manifest.write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"outcomes": 6, "manifest_sha256": debug.sha(args.manifest)}))


def run(args):
    protocol = json.loads(args.manifest.read_text())
    verify_inventory(ROOT, {
        "scripts/run_cc89_chain_phase_repair.py": protocol["coordinator_sha256"],
        "scripts/run_cc89_cuda_controls.py": protocol["controls_sha256"],
        debug.ENGINE + "/src/protpardelle/core/models.py": protocol["patched_engine_sha256"],
        debug.CONFIG: protocol["config_sha256"], debug.CHECKPOINT: protocol["checkpoint_sha256"],
    })
    controls.run(args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    freezing = commands.add_parser("freeze")
    for name in ("source-cohort", "source-manifest"):
        freezing.add_argument("--" + name, type=Path, required=True)
    execution = commands.add_parser("run")
    for name in ("output", "work-parent"):
        execution.add_argument("--" + name, type=Path, required=True)
    for command in (freezing, execution):
        command.add_argument("--cohort", type=Path, required=True)
        command.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    {"freeze": freeze, "run": run}[args.action](args)


if __name__ == "__main__":
    main()
