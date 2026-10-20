#!/usr/bin/env python3
"""Capture actual first-layer RoPE positions; stop before completing inference."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from run_cc89_known_sequence_holdout import ROOT, sha

from dvbfixer.model.diffusion.contract import DiffusionRequest
from dvbfixer.model.diffusion.protein_context import engine_context_view

CASES = ("antibody-1mim-H-cdr1-gap5", "antibody-1mim-L-cdr1-gap5",
         "antibody-1bvl-H-cdr1-gap5", "antibody-1bvl-L-cdr1-gap5")
ENGINE = ROOT / "test/protpardelle-1c-audit"


class CapturedPositions(Exception):
    pass


def worker(args):
    sys.dont_write_bytecode = True
    import protpardelle.core.models as models
    from run_protein_context_ablations import _load

    original_loader = models.load_model
    request = DiffusionRequest.from_json((args.workspace / "request.json").read_text())
    internal = engine_context_view(request).request
    expected_chain = np.concatenate([np.full(len(target.sequence), i) for i, target in enumerate(internal.target_sequences)])
    observed = {}

    def loader(*values, **options):
        model = original_loader(*values, **options)
        network = model.struct_model.net
        # Transformer layers deep-copy the template attention/rope module.
        # Instrument the actual first layer, not the unused template attribute.
        rope = network.transformer.layers[0][0].rope
        original_struct = model.struct_model.forward

        def struct(*args, **kwargs):
            observed["outer_positions"] = kwargs["residue_index"].detach().cpu().numpy().copy()
            observed["outer_chain_phase"] = kwargs["chain_index"].detach().cpu().numpy().copy()
            return original_struct(*args, **kwargs)

        def rope_forward(t, chain_index=None, seq_len=None, offset=0):
            used = t.detach().cpu().numpy()
            boundaries = np.nonzero(expected_chain[1:] != expected_chain[:-1])[0]
            deltas = used[0, boundaries + 1] - used[0, boundaries]
            if not np.array_equal(used, observed["outer_positions"] / rope.interpolate_factor):
                raise ValueError("RoPE silently replaced supplied residue positions")
            data = {"status": "captured-before-first-attention-completes", "neural_forward_completed": False,
                "code_sha256": {"adapter": sha(ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py"),
                    "models": sha(ENGINE / "src/protpardelle/core/models.py"), "modules": sha(ENGINE / "src/protpardelle/core/modules.py"),
                    "producer": sha(Path(__file__).resolve())},
                "request_sha256": sha(args.workspace / "request.json"),
                "engine_chain_lengths": [len(target.sequence) for target in internal.target_sequences],
                "actual_used_positions": used[0].tolist(), "chain_boundary_jumps": deltas.tolist(),
                "rope_uses_residue_index": rope.use_residx, "position_interpolation_factor": rope.interpolate_factor,
                "denoiser_chain_phase_values": np.unique(chain_index.detach().cpu().numpy()).tolist(),
                "outer_chain_phase_values": np.unique(observed["outer_chain_phase"]).tolist(),
                "convolution_layers": network.num_conv_layers,
                "position_embedding_type": network.position_embedding_type,
                "all_chain_boundaries_have_position_gap": bool(np.all(np.abs(deltas) > 1)),
                "checkpoint": "cc89_epoch415", "reference_present": (args.workspace / "reference.pdb").exists()}
            (args.workspace / "positions.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
            raise CapturedPositions()

        model.struct_model.forward = struct
        rope.forward = rope_forward
        return model

    models.load_model = loader
    try:
        adapter = _load("cc89_first_attention_probe", ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py")
        (args.workspace / "raw").mkdir()
        try:
            adapter._run_staged(args.workspace / "request.json", args.workspace / "raw", ENGINE / "model_params/configs/cc89.yaml",
                ENGINE / "model_params/weights/cc89_epoch415.pth", steps=500, step_scale=1.2, s_churn=200.0,
                per_step_reinjection=False, device_name="cuda", mps_profile=False, chain_phase_policy="neutral-v1")
        except CapturedPositions:
            return
        raise ValueError("first-layer position probe did not fire")
    finally:
        models.load_model = original_loader


def run(args):
    if args.output.exists():
        raise ValueError("position probe destination must be new")
    args.output.mkdir(parents=True)
    records = []
    for name in CASES:
        source = args.cohort / name
        root = args.output / name
        (root / "input").mkdir(parents=True)
        shutil.copyfile(source / "input/normalized.pdb", root / "input/normalized.pdb")
        shutil.copyfile(source / "requests/cc89-seed7.json", root / "request.json")
        environment = {**os.environ, "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "scripts"), str(ENGINE / "src"))),
            "PROTPARDELLE_MODEL_PARAMS": str(ENGINE / "model_params")}
        with (root / "probe.log").open("x") as log:
            subprocess.run([str(ROOT / "test/protpardelle-env/bin/python"), str(Path(__file__).resolve()), "worker",
                "--workspace", str(root)], env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
        data = json.loads((root / "positions.json").read_text())
        records.append({"case_id": name, **data})
        print(json.dumps({"case_id": name, "chain_lengths": data["engine_chain_lengths"],
            "boundary_jumps": data["chain_boundary_jumps"], "phase": data["denoiser_chain_phase_values"],
            "convolutions": data["convolution_layers"]}), flush=True)
    (args.output / "report.json").write_text(json.dumps({"cases": records, "complete": True}, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    execution = commands.add_parser("run")
    for name in ("cohort", "output"):
        execution.add_argument("--" + name, type=Path, required=True)
    capture = commands.add_parser("worker")
    capture.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    {"run": run, "worker": worker}[args.action](args)


if __name__ == "__main__":
    main()
