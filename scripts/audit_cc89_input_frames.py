#!/usr/bin/env python3
"""Instrument actual cc89 inputs and pre-restoration outputs on suspect cases.

Historical holdout outcomes are immutable. These are diagnostic controls, not a
new independent benchmark. Oracle round trips are explicitly non-neural adapter
tests; their native coordinates never enter real sampling workspaces.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from run_cc89_known_sequence_holdout import ROOT, evaluate, sha, verify_inventory

from dvbfixer.model.diffusion.contract import AtomIdentity, DiffusionRequest, RunnerResult
from dvbfixer.model.diffusion.geometry import weighted_kabsch
from dvbfixer.model.diffusion.pdb_materialize import materialize_candidate_pdb
from dvbfixer.model.diffusion.protein_context import engine_context_view, validate_context_source

CASES = ("general-9wgm-gap5", "antibody-1mim-H-cdr1-gap5", "antibody-1mim-L-cdr1-gap5",
         "antibody-1bvl-H-cdr1-gap5", "antibody-1bvl-L-cdr1-gap5")
ARMS = {
    "native": {"step_scale": 1.2, "s_churn": 200.0, "per_step_reinjection": False},
    "projected": {"step_scale": 1.2, "s_churn": 200.0, "per_step_reinjection": True},
    "ode-native": {"step_scale": 1.0, "s_churn": 0.0, "per_step_reinjection": False},
    "ode-projected": {"step_scale": 1.0, "s_churn": 0.0, "per_step_reinjection": True},
}
ENGINE = ROOT / "test/protpardelle-1c-audit"


def residue(atom):
    from dvbfixer.model.diffusion.contract import ResidueIdentity

    return ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code)


def freeze(args):
    if args.protocol.exists():
        raise ValueError("frame diagnostic protocol must be new")
    cases = []
    for name in CASES:
        source = args.cohort / name
        raw = args.baselines / "raw" / name / "seed7"
        marker = json.loads((raw / "complete.json").read_text())
        verify_inventory(raw, marker["artifacts"])
        result = RunnerResult.from_json((raw / "runner-result.json").read_text())
        cases.append({"case_id": name, "request_sha256": sha(source / "requests/cc89-seed7.json"),
            "input_sha256": sha(source / "input/normalized.pdb"), "reference_sha256": sha(source / "reference.pdb"),
            "original_raw_complete_sha256": sha(raw / "complete.json"),
            "original_native_candidate_sha256": result.candidates[0].coordinate_artifact.sha256})
    code = ("scripts/audit_cc89_input_frames.py", "scripts/run_cc89_known_sequence_holdout.py",
        "deploy/protpardelle-1c/checkpoint_gap_smoke.py", "src/dvbfixer/model/diffusion/protein_context.py",
        "src/dvbfixer/model/diffusion/geometry.py", "src/dvbfixer/model/diffusion/pdb_materialize.py",
        "src/dvbfixer/model/diffusion/validate.py", "test/protpardelle-1c-audit/src/protpardelle/core/models.py",
        "test/protpardelle-1c-audit/src/protpardelle/core/modules.py", "test/protpardelle-1c-audit/src/protpardelle/data/pdb_io.py")
    protocol = {"status": "frozen-before-cc89-input-frame-diagnostics", "cases": cases, "arms": ARMS,
        "code_sha256": {name: sha(ROOT / name) for name in code}, "seed": 7, "steps": 500,
        "config_sha256": sha(ENGINE / "model_params/configs/cc89.yaml"),
        "checkpoint_sha256": sha(ENGINE / "model_params/weights/cc89_epoch415.pth"),
        "frame_controls": ["legacy-output-scaffold-fit", "authoritative-input-motif-fit", "observed-anchor-fit"],
        "oracle_control": "native-reference through independent upstream PDB featurization and output round trip; zero neural forward calls; not restoration accuracy evidence",
        "sampling_reference_policy": "no reference copied to real sampling workspace; references read only by offline frame/oracle analysis",
        "torch": "2.6.0+cu124", "device": "cuda",
        "no_replacement": True, "timeout_seconds": 600, "refinement": "none", "public_promotion": False}
    with args.protocol.open("x") as stream:
        stream.write(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"samplings": len(CASES) * len(ARMS), "protocol_sha256": sha(args.protocol)}), flush=True)


def worker(args):
    sys.dont_write_bytecode = True
    import protpardelle.core.models as models
    import torch
    from run_protein_context_ablations import _load

    root = args.workspace
    if (root / "reference.pdb").exists():
        raise ValueError("withheld reference present in real sampler workspace")
    protocol = json.loads(args.protocol.read_text())
    if not torch.cuda.is_available() or torch.__version__ != protocol["torch"]:
        raise ValueError("input/frame controls require the pinned CUDA environment")
    captures, count = {}, 0
    original_loader = models.load_model

    def array(tensor):
        return tensor.detach().cpu().numpy().copy()

    def loader(*loader_args, **loader_kwargs):
        model = original_loader(*loader_args, **loader_kwargs)
        original_forward = model.struct_model.forward
        original_sample = model.sample

        def forward(*values, **kwargs):
            nonlocal count
            if count in (0, 1, protocol["steps"] - 1):
                for label, tensor in (("noisy", values[0]), ("sigma", values[1]), ("crop", kwargs["struct_crop_cond"]),
                                      ("residue_index", kwargs["residue_index"]), ("denoiser_chain_phase", kwargs["chain_index"])):
                    captures[f"{label}_{count}"] = array(tensor)
            count += 1
            return original_forward(*values, **kwargs)

        def sample(**kwargs):
            captures["actual_gt_aatype"] = array(kwargs["gt_aatype"])
            captures["physical_input_chain_index"] = array(kwargs["chain_index"])
            captures["physical_input_residue_index"] = array(kwargs["residue_index"])
            result = original_sample(**kwargs)
            for name in ("x", "s", "seq_mask", "motif_all_atom", "motif_atom_mask", "residue_index", "chain_index"):
                captures[name] = array(result[name])
            captures["motif_positions"] = np.asarray(result["motif_idx"][0], dtype=np.int64)
            captures["motif_aatype"] = array(result["motif_aatype"][0])
            np.savez_compressed(root / "sampler-input-output.npz", **captures)
            return result

        model.struct_model.forward = forward
        model.sample = sample
        return model

    models.load_model = loader
    try:
        adapter = _load("cc89_input_frame_capture", ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py")
        (root / "raw").mkdir()
        result, _ = adapter._run_staged(root / "request.json", root / "raw", ENGINE / "model_params/configs/cc89.yaml",
            ENGINE / "model_params/weights/cc89_epoch415.pth", steps=protocol["steps"], device_name="cuda", mps_profile=False,
            chain_phase_policy="neutral-v1", **protocol["arms"][args.arm])
        if count != protocol["steps"]:
            raise ValueError("captured denoiser-call count differs from sampling updates")
        (root / "runner-result.json").write_text(result.to_json())
        (root / "capture.json").write_text(json.dumps({"forward_calls": count, "reference_present_during_sampling": False}) + "\n")
    finally:
        models.load_model = original_loader


def run(args):
    protocol = json.loads(args.protocol.read_text())
    if protocol["status"] != "frozen-before-cc89-input-frame-diagnostics":
        raise ValueError("frame controls require frozen protocol")
    verify_inventory(ROOT, protocol["code_sha256"])
    records, executed = [], 0
    for case in protocol["cases"]:
        source = args.cohort / case["case_id"]
        verify_inventory(source, {"requests/cc89-seed7.json": case["request_sha256"], "input/normalized.pdb": case["input_sha256"]})
        for arm in protocol["arms"]:
            destination = args.output / "samples" / case["case_id"] / arm
            if not destination.exists():
                if args.max_new and executed >= args.max_new:
                    print(json.dumps({"completed": len(records), "partial": True}), flush=True)
                    return
                destination.mkdir(parents=True)
                (destination / "input").mkdir()
                shutil.copyfile(source / "input/normalized.pdb", destination / "input/normalized.pdb")
                shutil.copyfile(source / "requests/cc89-seed7.json", destination / "request.json")
                environment = {**os.environ, "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / "scripts"), str(ENGINE / "src"))),
                    "PROTPARDELLE_MODEL_PARAMS": str(ENGINE / "model_params")}
                with (destination / "worker.log").open("x") as log:
                    subprocess.run([str(ROOT / "test/protpardelle-env/bin/python"), str(Path(__file__).resolve()), "worker",
                        "--workspace", str(destination), "--protocol", str(args.protocol), "--arm", arm], env=environment,
                        stdout=log, stderr=subprocess.STDOUT, check=True, timeout=protocol["timeout_seconds"])
                result = RunnerResult.from_json((destination / "runner-result.json").read_text())
                same = result.candidates[0].coordinate_artifact.sha256 == case["original_native_candidate_sha256"]
                if arm == "native" and not same:
                    raise ValueError("passive native capture failed byte-identical baseline reproduction")
                (destination / "complete.json").write_text(json.dumps({"protocol_sha256": sha(args.protocol),
                    "native_reproduces_original": same if arm == "native" else None,
                    "artifacts": {p.relative_to(destination).as_posix(): sha(p) for p in sorted(destination.rglob("*")) if p.is_file()}}, indent=2, sort_keys=True) + "\n")
                executed += 1
            marker = json.loads((destination / "complete.json").read_text())
            if marker["protocol_sha256"] != sha(args.protocol):
                raise ValueError("capture archive belongs to another frame protocol")
            verify_inventory(destination, marker["artifacts"])
            records.append({"case_id": case["case_id"], "arm": arm, "native_reproduces_original": marker["native_reproduces_original"]})
            print(json.dumps(records[-1]), flush=True)
    (args.output / "capture-report.json").write_text(json.dumps({"complete": True, "records": records}, indent=2) + "\n")


def analyze_sample(source, capture_root, analysis_root, adapter, constants):
    request = DiffusionRequest.from_json((capture_root / "request.json").read_text())
    validate_context_source(request, (capture_root / request.normalized_pdb.path).read_bytes())
    view = engine_context_view(request)
    internal, inverse = view.request, dict(view.atom_to_source)
    source_to_engine = {src: eng for eng, src in view.atom_to_source}
    fixed_source = adapter._read_fixed_coordinates(capture_root / request.normalized_pdb.path, request.fixed_atoms)
    fixed = {source_to_engine[a]: xyz for a, xyz in fixed_source.items() if a in source_to_engine}
    mapped = adapter._target_residue_map(internal)
    positions = {r: index for index, r in mapped.items()}

    def address(atom):
        return positions[residue(atom)], constants.atom_order[atom.atom_name]

    arrays = np.load(capture_root / "sampler-input-output.npz", allow_pickle=False)
    expected_sequence = np.asarray([constants.restype_order[aa] for aa in adapter._target_sequence(internal)])
    if not np.array_equal(arrays["actual_gt_aatype"][0], expected_sequence) or not np.array_equal(arrays["s"][0], expected_sequence):
        raise ValueError("actual input or sampled sequence differs from the known target")
    motif_indices = arrays["motif_positions"]
    if not np.array_equal(arrays["motif_aatype"], expected_sequence[motif_indices]):
        raise ValueError("upstream motif sequence is misassigned to actual target positions")
    ordered = sorted(fixed)
    addresses = [address(a) for a in ordered]
    rows, columns = zip(*addresses)
    motif_row = {int(index): row for row, index in enumerate(motif_indices)}
    motif_points = np.asarray([arrays["motif_all_atom"][0, motif_row[row], col] for row, col in addresses])
    crop_points = arrays["crop_0"][0, rows, columns]
    if not np.array_equal(crop_points, motif_points):
        raise ValueError("actual crop tensor is not the authoritative upstream motif")
    allowed = np.zeros(arrays["crop_0"].shape[:-1], dtype=bool)
    allowed[0, rows, columns] = True
    if np.count_nonzero(arrays["crop_0"][~allowed]):
        raise ValueError("unexpected or generated coordinates entered crop conditioning")
    world_points = np.asarray([fixed[a] for a in ordered])
    input_to_world = weighted_kabsch(motif_points, world_points)
    input_error = float(np.linalg.norm(input_to_world.apply(motif_points) - world_points, axis=1).max())
    if input_error > 0.001:
        raise ValueError("actual motif tensor has wrong source coordinates or units")
    identities, xyz, names = adapter._model_atoms(internal, arrays["x"][0])
    index = {a: i for i, a in enumerate(identities)}
    legacy = weighted_kabsch(np.asarray([xyz[index[a]] for a in ordered]), world_points)
    anchors = {r for gap in internal.gaps for r in (gap.left_anchor, gap.right_anchor) if r}
    anchor_atoms = [a for a in ordered if residue(a) in anchors]
    anchor_fit = weighted_kabsch(np.asarray([xyz[index[a]] for a in anchor_atoms]), np.asarray([fixed[a] for a in anchor_atoms]))
    generated_indices = [i for i, atom in enumerate(identities) if inverse[atom] in set(request.generated_atoms)]
    analysis_root.mkdir(parents=True)
    (analysis_root / "input").mkdir()
    shutil.copyfile(capture_root / request.normalized_pdb.path, analysis_root / "input/normalized.pdb")
    shutil.copyfile(source / "reference.pdb", analysis_root / "reference.pdb")
    frames = {}
    for label, transform in (("legacy", legacy), ("input-motif", input_to_world), ("anchors", anchor_fit)):
        filename = label + ".pdb"
        coordinates = transform.apply(xyz)[generated_indices]
        (analysis_root / filename).write_text(materialize_candidate_pdb((capture_root / request.normalized_pdb.path).read_text(),
            tuple(inverse[identities[i]] for i in generated_indices), coordinates, tuple(names[i] for i in generated_indices), request))
        frames[label] = evaluate(analysis_root, request, filename)
    original_candidate = RunnerResult.from_json((capture_root / "runner-result.json").read_text()).candidates[0]
    if sha(analysis_root / "legacy.pdb") != original_candidate.coordinate_artifact.sha256:
        raise ValueError("offline prefit decoding does not reproduce the actual adapter output")
    state_errors = {str(step): float(np.sqrt(np.mean(np.sum((arrays[f"noisy_{step}"][0, rows, columns] - motif_points) ** 2, axis=1))))
                    for step in (0, 1, 499)}
    oracle = oracle_roundtrip(source, analysis_root, request, internal, source_to_engine, inverse,
        weighted_kabsch(world_points, motif_points), adapter, constants)
    distances = []
    for gap in internal.gaps:
        for left, right in zip(gap.generated_residues, gap.generated_residues[1:]):
            carbon = AtomIdentity(left.chain, left.residue_number, left.insertion_code, "C")
            nitrogen = AtomIdentity(right.chain, right.residue_number, right.insertion_code, "N")
            distances.append(float(np.linalg.norm(xyz[index[carbon]] - xyz[index[nitrogen]])))
    return {"input_audit": {"known_sequence_matches": True, "motif_sequence_matches": True,
        "actual_crop_matches_motif": True, "no_generated_crop_coordinates": True,
        "motif_to_source_max_error_angstrom": input_error, "observed_noisy_state_rmsd_angstrom": state_errors},
        "prefit_internal_peptide_cn_angstrom": {"minimum": min(distances), "maximum": max(distances)},
        "frames": frames, "oracle_adapter_roundtrip": oracle}


def oracle_roundtrip(source, output, request, internal, source_to_engine, inverse, world_to_motif, adapter, constants):
    """Independent upstream featurization of native reference, with no NN calls.

    This deliberately uses native coordinates solely as a unit/oracle control.
    The complete-native PDB is created under offline analysis, never sampling.
    """
    from protpardelle.core.models import parse_fixed_pos_str
    from protpardelle.data.pdb_io import load_feats_from_pdb

    labels = adapter._motif_chain_labels(internal)
    engine_lines = []
    for line in (source / "reference.pdb").read_text().splitlines():
        if not line.startswith("ATOM  "):
            continue
        original = AtomIdentity(line[21], line[22:26].strip(), line[26].strip(), line[12:16].strip())
        if original not in source_to_engine:
            continue
        engine = source_to_engine[original]
        # This diagnostic cohort has full chains with dense mosaic ordinals.
        # Use reference numbering directly, independently of the decoder's
        # observed/generated target-position dictionary.
        engine_lines.append(line[:21] + labels[engine.chain] + f"{int(original.residue_number):4d} " + line[27:] + "\n")
    native_input = output / "oracle-upstream-native.pdb"
    native_input.write_text("".join(engine_lines) + "TER\nEND\n")
    features, _ = load_feats_from_pdb(native_input, include_pos_feats=True)
    coordinates, masks = [], []
    for target in internal.target_sequences:
        indices = parse_fixed_pos_str(f"{labels[target.chain]}1-{len(target.sequence)}", features["chain_id_mapping"],
            features["residue_index_orig"], features["chain_index"])
        expected = [constants.restype_order[aa] for aa in target.sequence]
        if features["aatype"][indices].tolist() != expected:
            raise ValueError("native upstream oracle features do not reproduce the target sequence order")
        coordinates.append(features["atom_positions"][indices].numpy())
        masks.append(features["atom_mask"][indices].numpy())
    native = np.concatenate(coordinates)
    mask = np.concatenate(masks)
    internal_frame = world_to_motif.apply(native.reshape(-1, 3)).reshape(native.shape) * mask[..., None]
    identities, points, names = adapter._model_atoms(internal, internal_frame)
    fixed_source = adapter._read_fixed_coordinates(output / request.normalized_pdb.path, request.fixed_atoms)
    fixed = {source_to_engine[a]: xyz for a, xyz in fixed_source.items() if a in source_to_engine}
    source_names = adapter._read_fixed_residue_names(output / request.normalized_pdb.path, request.fixed_atoms)
    fixed_names = {source_to_engine[a]: name for a, name in source_names.items() if a in source_to_engine}
    identities, points, names = adapter._synchronize_and_restore_fixed_atoms(identities, points, names, fixed, fixed_names, internal, joint_frame=True)
    generated = set(request.generated_atoms)
    indices = [i for i, atom in enumerate(identities) if inverse[atom] in generated]
    candidate = output / "oracle-roundtrip.pdb"
    candidate.write_text(materialize_candidate_pdb((output / request.normalized_pdb.path).read_text(),
        tuple(inverse[identities[i]] for i in indices), points[indices], tuple(names[i] for i in indices), request))
    result = evaluate(output, request, candidate.name)
    return {"neural_forward_calls": 0, "reference_deliberately_used_for_adapter_test": True,
            "sequence_verified_by_independent_upstream_parser": True, **result}


def analyze(args):
    sys.dont_write_bytecode = True
    from protpardelle.common import residue_constants
    from run_protein_context_ablations import _load

    protocol = json.loads(args.protocol.read_text())
    adapter = _load("cc89_offline_frame_decoder", ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py")
    report = []
    for case in protocol["cases"]:
        for arm in protocol["arms"]:
            root = args.output / "samples" / case["case_id"] / arm
            if not (root / "complete.json").exists():
                if not args.allow_partial:
                    raise ValueError("frame diagnostic captures are incomplete")
                report.append({"case_id": case["case_id"], "arm": arm, "status": "pending"})
                continue
            marker = json.loads((root / "complete.json").read_text())
            if marker["protocol_sha256"] != sha(args.protocol):
                raise ValueError("offline frame audit protocol mismatch")
            verify_inventory(root, marker["artifacts"])
            verify_inventory(args.cohort / case["case_id"], {"reference.pdb": case["reference_sha256"]})
            data = analyze_sample(args.cohort / case["case_id"], root, args.output / args.analysis_name / case["case_id"] / arm, adapter, residue_constants)
            report.append({"case_id": case["case_id"], "arm": arm, "status": "evaluated", **data})
            print(json.dumps({"case_id": case["case_id"], "arm": arm,
                "rmsd": {k: v["quality"]["gap_backbone_rmsd_angstrom"] for k, v in data["frames"].items()}}), flush=True)
    (args.output / (args.analysis_name + ".json")).write_text(json.dumps({"protocol_sha256": sha(args.protocol), "cases": report,
        "public_promotion": False, "complete": all(row["status"] == "evaluated" for row in report)}, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    freezing = commands.add_parser("freeze")
    freezing.add_argument("--baselines", type=Path, required=True)
    execution = commands.add_parser("run")
    execution.add_argument("--max-new", type=int, default=0)
    offline = commands.add_parser("analyze")
    offline.add_argument("--allow-partial", action="store_true")
    offline.add_argument("--analysis-name", default="analysis")
    for command in (freezing, execution, offline):
        command.add_argument("--cohort", type=Path, required=True)
    for command in (execution, offline):
        command.add_argument("--output", type=Path, required=True)
    working = commands.add_parser("worker")
    working.add_argument("--workspace", type=Path, required=True)
    working.add_argument("--arm", choices=tuple(ARMS), required=True)
    for command in (freezing, execution, offline, working):
        command.add_argument("--protocol", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    {"freeze": freeze, "run": run, "worker": worker, "analyze": analyze}[args.action](args)


if __name__ == "__main__":
    main()
