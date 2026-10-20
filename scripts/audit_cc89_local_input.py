#!/usr/bin/env python3
"""Matched local-axis versus full-axis controls, retaining the full source PDB."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import audit_cc89_input_frames as frames
import numpy as np
from run_cc89_known_sequence_holdout import ROOT, evaluate, sha, verify_inventory

from dvbfixer.model.diffusion.contract import (
    AtomIdentity,
    DiffusionRequest,
    ProteinContextPolicy,
)
from dvbfixer.model.diffusion.pdb_materialize import materialize_candidate_pdb
from dvbfixer.model.diffusion.protein_context import select_protein_context

ARMS = {"native": frames.ARMS["native"], "ode-projected": frames.ARMS["ode-projected"],
        "source-native": frames.ARMS["native"], "source-ode-projected": frames.ARMS["ode-projected"]}
ENGINE = frames.ENGINE


def physical_positions(request):
    """Preserve within-source sequence offsets across proxy serialization spans.

    Normalize each selected physical chain's origin and retain a 200-position
    break between physical chains. Omitted spans are never turned into peptide
    adjacency; proxy labels remain solely a motif serialization mechanism.
    """
    order = list(dict.fromkeys(span.chain for span in request.protein_context.spans))
    numbers = {chain: index for index, chain in enumerate(order)}
    origins, previous_end = {}, None
    for chain in order:
        spans = [span for span in request.protein_context.spans if span.chain == chain]
        first, last = min(s.start for s in spans), max(s.stop for s in spans)
        start = 1 if previous_end is None else previous_end + 200
        origins[chain] = start - first
        previous_end = origins[chain] + last - 1
    indices, chains = [], []
    for span in request.protein_context.spans:
        indices.extend(origins[span.chain] + i for i in range(span.start, span.stop))
        chains.extend([numbers[span.chain]] * (span.stop - span.start))
    return indices, chains


def freeze(args):
    if args.protocol.exists() or args.cohort.exists():
        raise ValueError("local input controls require new inputs and protocol")
    args.cohort.mkdir(parents=True)
    cases = []
    for name in frames.CASES:
        source = args.source_cohort / name
        request = DiffusionRequest.from_json((source / "requests/cc89-seed7.json").read_text())
        data = (source / request.normalized_pdb.path).read_bytes()
        local = select_protein_context(replace(request, protein_context=None), data,
            ProteinContextPolicy(name="atom37-terminal-preservation-v1", target_flanks=8, same_chain_spatial=True, partner_mode="local"))
        if replace(local, protein_context=request.protein_context) != request:
            raise ValueError("local control changed a field beyond explicit model context")
        directory = args.cohort / name
        (directory / "input").mkdir(parents=True)
        shutil.copyfile(source / request.normalized_pdb.path, directory / request.normalized_pdb.path)
        shutil.copyfile(source / "reference.pdb", directory / "reference.pdb")
        (directory / "request.json").write_text(local.to_json())
        cases.append({"case_id": name, "source_request_sha256": sha(source / "requests/cc89-seed7.json"),
            "local_request_sha256": sha(directory / "request.json"), "input_sha256": sha(directory / request.normalized_pdb.path),
            "reference_sha256": sha(directory / "reference.pdb"),
            "full_axis_residues": sum(span.stop - span.start for span in request.protein_context.spans),
            "local_axis_residues": sum(span.stop - span.start for span in local.protein_context.spans),
            "local_spans": len(local.protein_context.spans), "preserved_only_atoms": len(local.protein_context.preserved_only),
            "conditioned_atoms": len(local.protein_context.fixed_conditioning)})
    code = ("scripts/audit_cc89_local_input.py", "scripts/audit_cc89_input_frames.py",
        "scripts/run_cc89_known_sequence_holdout.py", "deploy/protpardelle-1c/checkpoint_gap_smoke.py",
        "src/dvbfixer/model/diffusion/protein_context.py", "src/dvbfixer/model/diffusion/geometry.py",
        "src/dvbfixer/model/diffusion/pdb_materialize.py", "src/dvbfixer/model/diffusion/validate.py",
        "test/protpardelle-1c-audit/src/protpardelle/core/models.py", "test/protpardelle-1c-audit/src/protpardelle/core/modules.py")
    protocol = {"status": "frozen-before-local-input-controls", "cases": cases, "arms": ARMS, "seed": 7,
        "axis_modes": {name: "source-physical" if name.startswith("source-") else "proxy-native" for name in ARMS},
        "steps": 500, "torch": "2.6.0+cu124", "device": "cuda", "timeout_seconds": 600,
        "code_sha256": {name: sha(ROOT / name) for name in code}, "no_replacement": True,
        "interpretation": "diagnostic source-context routing after the full-context holdout; not independent acceptance",
        "reference_policy": "offline only; absent from sampling workspaces", "public_promotion": False}
    with args.protocol.open("x") as stream:
        stream.write(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"samplings": len(cases) * len(ARMS), "cases": cases}, indent=2))


def run(args):
    protocol = json.loads(args.protocol.read_text())
    if protocol["status"] != "frozen-before-local-input-controls":
        raise ValueError("local controls require frozen protocol")
    verify_inventory(ROOT, protocol["code_sha256"])
    for case in protocol["cases"]:
        source = args.cohort / case["case_id"]
        verify_inventory(source, {"request.json": case["local_request_sha256"], "input/normalized.pdb": case["input_sha256"]})
        for arm in protocol["arms"]:
            root = args.output / "samples" / case["case_id"] / arm
            if not root.exists():
                (root / "input").mkdir(parents=True)
                shutil.copyfile(source / "request.json", root / "request.json")
                shutil.copyfile(source / "input/normalized.pdb", root / "input/normalized.pdb")
                environment = {**os.environ, "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "scripts"), str(ENGINE / "src"))),
                    "PROTPARDELLE_MODEL_PARAMS": str(ENGINE / "model_params")}
                with (root / "worker.log").open("x") as log:
                    subprocess.run([str(ROOT / "test/protpardelle-env/bin/python"), str(Path(__file__).resolve()), "worker",
                        "--workspace", str(root), "--protocol", str(args.protocol), "--arm", arm], env=environment,
                        stdout=log, stderr=subprocess.STDOUT, check=True, timeout=protocol["timeout_seconds"])
                (root / "complete.json").write_text(json.dumps({"protocol_sha256": sha(args.protocol),
                    "artifacts": {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}}, indent=2, sort_keys=True) + "\n")
            marker = json.loads((root / "complete.json").read_text())
            if marker["protocol_sha256"] != sha(args.protocol):
                raise ValueError("local control archive protocol mismatch")
            verify_inventory(root, marker["artifacts"])
            print(json.dumps({"case_id": case["case_id"], "arm": arm, "captured": True}), flush=True)


def worker(args):
    sys.dont_write_bytecode = True
    import protpardelle.core.models as models
    import torch

    protocol = json.loads(args.protocol.read_text())
    request = DiffusionRequest.from_json((args.workspace / "request.json").read_text())
    original_loader = models.load_model

    def loader(*values, **kwargs):
        model = original_loader(*values, **kwargs)
        if protocol["axis_modes"][args.arm] == "source-physical":
            original_make = model.make_seq_mask_for_sampling

            def make(**options):
                mask, ri, ci = original_make(**options)
                positions, chains = physical_positions(request)
                if ri.shape != (1, len(positions)):
                    raise ValueError("physical source features do not match unchanged local token axis")
                return mask, torch.as_tensor([positions], device=ri.device, dtype=ri.dtype), torch.as_tensor([chains], device=ci.device, dtype=ci.dtype)

            model.make_seq_mask_for_sampling = make
        rope = model.struct_model.net.transformer.layers[0][0].rope
        original_rope_forward = rope.forward
        captured = False

        def rope_forward(t, chain_index=None, seq_len=None, offset=0):
            nonlocal captured
            if not captured:
                (args.workspace / "rope-positions.json").write_text(json.dumps({
                    "positions": t[0].detach().cpu().tolist(),
                    "chain_phase": chain_index[0].detach().cpu().tolist(),
                    "use_residx": rope.use_residx, "interpolation": rope.interpolate_factor,
                    "convolution_layers": model.struct_model.net.num_conv_layers,
                }) + "\n")
                captured = True
            return original_rope_forward(t, chain_index=chain_index, seq_len=seq_len, offset=offset)

        rope.forward = rope_forward
        return model

    models.load_model = loader
    try:
        frames.worker(args)
    finally:
        models.load_model = original_loader


def selected_oracle(source, output, request, internal, source_to_engine, inverse, world_to_motif, adapter, constants):
    from protpardelle.core.models import parse_fixed_pos_str
    from protpardelle.data.pdb_io import load_feats_from_pdb

    labels = adapter._motif_chain_labels(internal)
    spans = {target.chain: span for target, span in zip(internal.target_sequences, request.protein_context.spans, strict=True)}
    lines = []
    for line in (source / "reference.pdb").read_text().splitlines():
        if not line.startswith("ATOM  "):
            continue
        original = AtomIdentity(line[21], line[22:26].strip(), line[26].strip(), line[12:16].strip())
        if original not in source_to_engine:
            continue
        engine = source_to_engine[original]
        ordinal = int(original.residue_number) - spans[engine.chain].start
        lines.append(line[:21] + labels[engine.chain] + f"{ordinal:4d} " + line[27:] + "\n")
    path = output / "oracle-upstream-native.pdb"
    path.write_text("".join(lines) + "TER\nEND\n")
    features, _ = load_feats_from_pdb(path, include_pos_feats=True)
    points, masks = [], []
    for target in internal.target_sequences:
        indices = parse_fixed_pos_str(f"{labels[target.chain]}1-{len(target.sequence)}", features["chain_id_mapping"],
            features["residue_index_orig"], features["chain_index"])
        if features["aatype"][indices].tolist() != [constants.restype_order[aa] for aa in target.sequence]:
            raise ValueError("selected native oracle sequence mismatch")
        points.append(features["atom_positions"][indices].numpy())
        masks.append(features["atom_mask"][indices].numpy())
    native = np.concatenate(points)
    encoded = world_to_motif.apply(native.reshape(-1, 3)).reshape(native.shape) * np.concatenate(masks)[..., None]
    identities, xyz, names = adapter._model_atoms(internal, encoded)
    observed = adapter._read_fixed_coordinates(output / request.normalized_pdb.path, request.fixed_atoms)
    observed_names = adapter._read_fixed_residue_names(output / request.normalized_pdb.path, request.fixed_atoms)
    fixed = {source_to_engine[a]: p for a, p in observed.items() if a in source_to_engine}
    fixed_names = {source_to_engine[a]: p for a, p in observed_names.items() if a in source_to_engine}
    identities, xyz, names = adapter._synchronize_and_restore_fixed_atoms(identities, xyz, names, fixed, fixed_names, internal, joint_frame=True)
    selected = [i for i, atom in enumerate(identities) if inverse[atom] in set(request.generated_atoms)]
    candidate = output / "oracle-roundtrip.pdb"
    candidate.write_text(materialize_candidate_pdb((output / request.normalized_pdb.path).read_text(),
        tuple(inverse[identities[i]] for i in selected), xyz[selected], tuple(names[i] for i in selected), request))
    return {"neural_forward_calls": 0, "reference_deliberately_used_for_adapter_test": True,
        "sequence_verified_by_independent_upstream_parser": True, **evaluate(output, request, candidate.name)}


def analyze(args):
    sys.dont_write_bytecode = True
    from protpardelle.common import residue_constants
    from run_protein_context_ablations import _load

    protocol = json.loads(args.protocol.read_text())
    adapter = _load("cc89_local_frame_decoder", ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py")
    records = []
    original_oracle = frames.oracle_roundtrip
    frames.oracle_roundtrip = selected_oracle
    try:
        for case in protocol["cases"]:
            for arm in protocol["arms"]:
                root = args.output / "samples" / case["case_id"] / arm
                marker = json.loads((root / "complete.json").read_text())
                if marker["protocol_sha256"] != sha(args.protocol):
                    raise ValueError("local frame analysis protocol mismatch")
                verify_inventory(root, marker["artifacts"])
                verify_inventory(args.cohort / case["case_id"], {"reference.pdb": case["reference_sha256"]})
                data = frames.analyze_sample(args.cohort / case["case_id"], root,
                    args.output / "analysis" / case["case_id"] / arm, adapter, residue_constants)
                rope = json.loads((root / "rope-positions.json").read_text())
                arrays = np.load(root / "sampler-input-output.npz", allow_pickle=False)
                if not np.array_equal(np.asarray(rope["positions"]), arrays["physical_input_residue_index"][0] / rope["interpolation"]):
                    raise ValueError("local RoPE replaced supplied source/proxy position features")
                data["actual_rope_features"] = rope
                records.append({"case_id": case["case_id"], "arm": arm, **data})
                print(json.dumps({"case_id": case["case_id"], "arm": arm,
                    "rmsd": data["frames"]["legacy"]["quality"]["gap_backbone_rmsd_angstrom"],
                    "passed": data["frames"]["legacy"]["validation"]["passed"]}), flush=True)
    finally:
        frames.oracle_roundtrip = original_oracle
    (args.output / "analysis.json").write_text(json.dumps({"complete": True, "cases": records,
        "protocol_sha256": sha(args.protocol), "public_promotion": False}, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    freezing = commands.add_parser("freeze")
    freezing.add_argument("--source-cohort", type=Path, required=True)
    execution = commands.add_parser("run")
    offline = commands.add_parser("analyze")
    capture = commands.add_parser("worker")
    capture.add_argument("--workspace", type=Path, required=True)
    capture.add_argument("--arm", choices=tuple(ARMS), required=True)
    capture.add_argument("--protocol", type=Path, required=True)
    for command in (freezing, execution, offline):
        command.add_argument("--cohort", type=Path, required=True)
        command.add_argument("--protocol", type=Path, required=True)
    for command in (execution, offline):
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    {"freeze": freeze, "run": run, "worker": worker, "analyze": analyze}[args.action](args)


if __name__ == "__main__":
    main()
