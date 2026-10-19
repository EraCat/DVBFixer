#!/usr/bin/env python3
"""Private, frozen cc89 tensor-semantics controls; never a public runner.

Keep the original engine axis and scientific gap while varying only learned
motif density and fixed-state self-conditioning. Sparse learned conditioning is
explicitly distinguished from projection of the complete represented scaffold.
No RunnerResult or public conditioning claim is fabricated for these controls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np

from dvbfixer.model.diffusion.contract import (
    ArtifactReference,
    DiffusionRequest,
    ResidueIdentity,
)
from dvbfixer.model.diffusion.geometry import weighted_kabsch

ROOT = Path(__file__).resolve().parents[1]
CASES = ("cc89-joint", "cc89-discontiguous", "cc89-case-insertion")
ARMS = {
    "full-native": (None, False, False),
    "full-projected": (None, True, False),
    "sparse24-native": (24, False, False),
    "sparse24-projected": (24, True, False),
    "full-projected-selfcond": (None, True, True),
    "sparse24-projected-selfcond": (24, True, True),
}
ADAPTER = "deploy/protpardelle-1c/checkpoint_gap_smoke.py"
ENGINE = "test/protpardelle-1c-audit"
CONFIG = ENGINE + "/model_params/configs/cc89.yaml"
CHECKPOINT = ENGINE + "/model_params/weights/cc89_epoch415.pth"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def residue(atom):
    return ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code)


def conditioning_atoms(request, coordinates, limit):
    """Explicit ablation: complete anchor residues, then nearest source residues.

    No withheld or sampled coordinates enter this selection. Non-selected fixed
    atoms remain on the same engine axis and, in projected arms, are still fixed.
    """
    if limit is None:
        return request.fixed_atoms
    anchors = {anchor for gap in request.gaps for anchor in (gap.left_anchor, gap.right_anchor) if anchor}
    by_residue = {}
    for atom in request.fixed_atoms:
        by_residue.setdefault(residue(atom), []).append(coordinates[atom])
    if len(anchors) > limit or not anchors <= by_residue.keys():
        raise ValueError("conditioning budget cannot represent every anchor")
    queries = np.asarray([point for anchor in sorted(anchors) for point in by_residue[anchor]])
    candidates = sorted((float(np.linalg.norm(np.asarray(points)[:, None] - queries[None], axis=2).min()), identity)
                        for identity, points in by_residue.items() if identity not in anchors)
    selected = anchors | {identity for _, identity in candidates[:limit - len(anchors)]}
    return tuple(atom for atom in request.fixed_atoms if residue(atom) in selected)


def motif_placement(request, selected_atoms):
    """Place sparse conditioning on the unchanged full multichain token axis."""
    selected = {residue(atom) for atom in selected_atoms}
    observed = {r for placement in request.sequence_placements for r in placement.observed_residues}
    if not selected <= observed:
        raise ValueError("motif conditioning must be observed, never generated")
    positions, chains, offset = [], [], 0
    for number, target in enumerate(request.target_sequences):
        placement = next(p for p in request.sequence_placements if p.chain == target.chain)
        fixed = {index for index, r in zip(placement.observed_target_indices, placement.observed_residues) if r in selected}
        parts, start = [], 0
        while start < len(target.sequence):
            stop = start + 1
            while stop < len(target.sequence) and ((stop in fixed) == (start in fixed)):
                stop += 1
            if start in fixed:
                parts.append(f"{chr(65 + number)}{start + 1}-{stop}")
                positions.extend(range(offset + start, offset + stop))
            else:
                parts.append(str(stop - start))
            start = stop
        chains.append("/".join(parts))
        offset += len(target.sequence)
    return ";/;".join(chains), positions


def freeze(args):
    if args.protocol.exists():
        raise ValueError("debug protocol must be new")
    code = ("scripts/debug_cc89_conditioning.py", ADAPTER,
            "src/dvbfixer/model/diffusion/protein_context.py", "src/dvbfixer/model/diffusion/pdb_materialize.py",
            "src/dvbfixer/model/diffusion/validate.py", ENGINE + "/src/protpardelle/core/models.py",
            ENGINE + "/src/protpardelle/core/modules.py", ENGINE + "/src/protpardelle/data/pdb_io.py")
    protocol = {"status": "frozen-before-cc89-tensor-semantics-controls", "no_replacement": True,
        "cases": [{"case_id": name, "artifacts": {p.relative_to(args.cohort / name).as_posix(): sha(p)
                   for p in sorted((args.cohort / name).rglob("*")) if p.is_file()}} for name in CASES],
        "code_sha256": {name: sha(ROOT / name) for name in code},
        "config_sha256": sha(ROOT / CONFIG), "checkpoint_sha256": sha(ROOT / CHECKPOINT),
        "engine_revision": subprocess.check_output(["git", "-C", str(ROOT / ENGINE), "rev-parse", "HEAD"], text=True).strip(),
        "arms": {name: {"learned_motif_residue_limit": limit, "project_all_represented_fixed_atoms": project,
                        "project_fixed_self_conditioning": selfcond} for name, (limit, project, selfcond) in ARMS.items()},
        "seed": 7, "steps": 500, "step_scale": 1.2, "s_churn": 200.0, "timeout_seconds": 600,
        "device": "cuda", "torch": "2.6.0+cu124", "scope": "private-debug-no-public-runner-result",
        "hypotheses": ["motif density versus sparse <=24-residue training motifs on the same axis",
                       "fixed xt projection versus unprojected fixed x_self_cond"],
        "checks": ["actual denoiser crop tensor identities/coordinates and zero gap coordinates",
                   "independent geometry and fixed/environment-aligned withheld accuracy",
                   "baseline candidate byte comparison; no geometry-threshold changes"],
        "reference_usage": "offline scoring only", "refinement": "none", "public_promotion": False}
    with args.protocol.open("x") as stream:
        stream.write(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"outcomes": len(CASES) * len(ARMS), "protocol_sha256": sha(args.protocol)}))


def worker(args):
    sys.dont_write_bytecode = True
    import torch
    from protpardelle.common import residue_constants
    from protpardelle.core.models import load_model
    from protpardelle.utils import seed_everything
    from run_protein_context_ablations import _load

    from dvbfixer.model.diffusion.benchmark import candidate_quality, load_pdb_coordinates
    from dvbfixer.model.diffusion.pdb_materialize import materialize_candidate_pdb
    from dvbfixer.model.diffusion.protein_context import (
        engine_context_view,
        validate_context_source,
    )
    from dvbfixer.model.diffusion.validate import (
        ValidationThresholds,
        _load_structure,
        _validate_candidate,
    )

    protocol = json.loads(args.protocol.read_text())
    if not torch.cuda.is_available() or torch.__version__ != protocol["torch"]:
        raise ValueError("debug controls require the pinned CUDA environment without fallback")
    root = args.workspace
    request = DiffusionRequest.from_json((root / "request.json").read_text())
    source = root / request.normalized_pdb.path
    validate_context_source(request, source.read_bytes())
    view = engine_context_view(request)
    internal = view.request
    inverse = dict(view.atom_to_source)
    forward = {src: eng for eng, src in view.atom_to_source}
    adapter = _load("cc89_tensor_debug_adapter", ROOT / ADAPTER)
    source_coordinates = adapter._read_fixed_coordinates(source, request.fixed_atoms)
    fixed = {forward[atom]: xyz for atom, xyz in source_coordinates.items() if atom in forward}
    settings = protocol["arms"][args.arm]
    selected = conditioning_atoms(internal, fixed, settings["learned_motif_residue_limit"])
    placement, motif_positions = motif_placement(internal, selected)
    motif_path = root / "motif.pdb"
    adapter._write_motif_input(source, motif_path, replace(internal, fixed_atoms=selected), forward)
    model = load_model(ROOT / CONFIG, ROOT / CHECKPOINT, device="cuda")
    checkpoint_keys = set(torch.load(ROOT / CHECKPOINT, map_location="cpu", weights_only=False)["model_state_dict"])
    if checkpoint_keys != set(model.state_dict()):
        raise ValueError("checkpoint/model parameter keys differ")
    seed_everything(protocol["seed"])
    torch.manual_seed(protocol["seed"])
    torch.cuda.manual_seed_all(protocol["seed"])
    mask, residx, chainidx = model.make_seq_mask_for_sampling(
        prot_lens_per_chain=torch.tensor([[len(t.sequence) for t in internal.target_sequences]]))
    mapped = adapter._target_residue_map(internal)
    index = {r: i for i, r in mapped.items()}

    def address(atom):
        return index[residue(atom)], residue_constants.atom_order[atom.atom_name]

    selected_addresses = [address(atom) for atom in selected]
    fixed_order = sorted(fixed)
    fixed_addresses = [address(atom) for atom in fixed_order]
    generated_addresses = [address(atom) for atom in internal.generated_atoms]
    fixed_rows, fixed_columns = zip(*fixed_addresses)
    selected_rows, selected_columns = zip(*selected_addresses)
    generated_rows, generated_columns = zip(*generated_addresses)
    clean_fixed = None
    forward_calls, callback_count, projection_max_error = 0, 0, 0.0
    tensor_audit = {}
    original_forward = model.forward

    def audited_forward(**kwargs):
        nonlocal clean_fixed, forward_calls
        crop = kwargs["struct_crop_cond"]
        if forward_calls == 0:
            if crop is None or not torch.isfinite(crop).all():
                raise ValueError("missing/non-finite actual learned conditioning")
            selection_mask = torch.zeros(crop.shape[:-1], dtype=torch.bool, device=crop.device)
            selection_mask[:, selected_rows, selected_columns] = True
            if torch.count_nonzero(crop[~selection_mask]):
                raise ValueError("unexpected atom coordinates reached learned conditioning")
            mobile = np.asarray([fixed[atom] for atom in selected])
            target = crop[0, selected_rows, selected_columns].detach().cpu().numpy()
            transform = weighted_kabsch(mobile, target)
            maximum = float(np.linalg.norm(transform.apply(mobile) - target, axis=1).max())
            if maximum > 0.001:
                raise ValueError("actual denoiser motif tensor is misassigned to source atoms")
            clean_fixed = torch.as_tensor(transform.apply(np.asarray([fixed[atom] for atom in fixed_order])), device=crop.device, dtype=crop.dtype)
            # Preserve exact upstream motif coordinates for selected atoms. This
            # makes the full projected control identical to the old projector.
            fixed_index = {atom: i for i, atom in enumerate(fixed_order)}
            for atom, point in zip(selected, crop[0, selected_rows, selected_columns]):
                clean_fixed[fixed_index[atom]] = point
            tensor_audit.update(learned_context_atom_count=len(selected), learned_context_residue_count=len({residue(a) for a in selected}),
                learned_context_source_alignment_max_error_angstrom=maximum,
                generated_crop_max_abs_coordinate=float(crop[0, generated_rows, generated_columns].abs().max()),
                actual_chain_lengths=[int((kwargs["chain_index"][0] == i).sum()) for i in range(len(internal.target_sequences))],
                actual_residue_index=kwargs["residue_index"][0].detach().cpu().tolist(),
                learned_context_source_atoms=[asdict(inverse[a]) for a in selected])
        result = original_forward(**kwargs)
        if settings["project_fixed_self_conditioning"]:
            denoised, logits, x_self, s_self = result
            x_self = x_self.clone()
            x_self[:, fixed_rows, fixed_columns] = clean_fixed / model.sigma_data
            result = denoised, logits, x_self, s_self
        forward_calls += 1
        return result

    model.forward = audited_forward

    def project(state, step, step_count, motif_indices, motif_coordinates, motif_mask):
        nonlocal callback_count, projection_max_error
        if step != callback_count or step_count != protocol["steps"] or motif_indices != [motif_positions]:
            raise ValueError("projection callback/axis mismatch")
        updated = state.clone()
        updated[:, fixed_rows, fixed_columns] = clean_fixed
        projection_max_error = max(projection_max_error, float((updated[0, fixed_rows, fixed_columns] - clean_fixed).abs().max()))
        callback_count += 1
        return updated

    conditional = {"enabled": True, "discontiguous_motif_assignment": {"enabled": True, "strategy": "fixed", "fixed_motif_pos": motif_positions},
        "num_recurrence_steps": 1, "crop_conditional_guidance": {"enabled": True, "start": 0.0, "end": 2.0, "freq": 1,
            "freq_start": 0.0, "freq_end": 0.0, "strategy": "backbone-sidechain"},
        "reconstruction_guidance": {"enabled": False, "start": 0.0, "end": 2.0, "schedule": "custom", "max_scale": 10.0, "loss_weights": {"motif": 1.0}},
        "replacement_guidance": {"enabled": False, "start": 0.0, "end": 0.92}}
    sampled = model.sample(seq_mask=mask.to("cuda"), residue_index=residx.to("cuda"), chain_index=chainidx.to("cuda"),
        gt_aatype=torch.tensor([[residue_constants.restype_order[aa] for aa in adapter._target_sequence(internal)]], device="cuda"),
        num_steps=protocol["steps"], step_scale=protocol["step_scale"], s_churn=protocol["s_churn"], motif_file_path=str(motif_path),
        motif_placements_full=[placement], dummy_fill_mode=model.config.data.dummy_fill_mode,
        partial_diffusion={"enabled": False, "pdb_file_path": None, "num_steps": 100}, conditional_cfg=conditional,
        sidechain_mode=False, skip_mpnn_proportion=1.0, use_fullmpnn=False, use_fullmpnn_for_final=False,
        jump_steps=False, uniform_steps=True, **({"step_callback": project} if settings["project_all_represented_fixed_atoms"] else {}))
    if forward_calls != protocol["steps"] or callback_count != (protocol["steps"] if settings["project_all_represented_fixed_atoms"] else 0):
        raise ValueError("unexpected denoiser or callback count")
    identities, xyz, names = adapter._model_atoms(internal, adapter._coordinates_to_numpy(torch, sampled["x"][0]))
    native_fit = adapter._native_conditioning_fit(identities, xyz, fixed, joint_frame=True)
    loc = {a: i for i, a in enumerate(identities)}
    aligned = weighted_kabsch(np.asarray([xyz[loc[a]] for a in fixed_order]), np.asarray([fixed[a] for a in fixed_order])).apply(xyz)
    generated = set(request.generated_atoms)
    indices = [i for i, a in enumerate(identities) if inverse[a] in generated]
    candidate = root / "candidate.pdb"
    candidate.write_text(materialize_candidate_pdb(source.read_text(), tuple(inverse[identities[i]] for i in indices),
        aligned[indices], tuple(names[i] for i in indices), request))
    summary, _ = _validate_candidate(request, _load_structure(root, request.normalized_pdb.path, request.normalized_pdb.sha256),
        _load_structure(root, candidate.name, sha(candidate)), ValidationThresholds())
    quality = candidate_quality("cc89-debug", load_pdb_coordinates(root, ArtifactReference("reference.pdb", sha(root / "reference.pdb"))),
        load_pdb_coordinates(root, ArtifactReference(candidate.name, sha(candidate))),
        generated_residues={r for g in request.gaps for r in g.generated_residues}, fixed_atoms=set(request.fixed_atoms),
        anchor_residues={r for g in request.gaps for r in (g.left_anchor, g.right_anchor) if r},
        closure_passed="junction-peptide-connectivity" not in summary.hard_gate_failures, validation_passed=summary.passed,
        expected_generated_atoms=set(request.generated_atoms))
    outcome = {"status": "evaluated", "settings": settings, "tensor_audit": tensor_audit, "forward_calls": forward_calls,
        "callback_count": callback_count, "projection_max_error_angstrom": projection_max_error,
        "native_conditioning_fit": native_fit, "validation": asdict(summary), "quality": asdict(quality), "candidate_sha256": sha(candidate),
        "model_state_missing_or_unexpected_keys": [], "device": "cuda", "public_promotion": False}
    (root / "outcome.json").write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n")


def run(args):
    from run_a100_relaxation import verify_inventory

    protocol = json.loads(args.protocol.read_text())
    if protocol["status"] != "frozen-before-cc89-tensor-semantics-controls" or not protocol["no_replacement"]:
        raise ValueError("debug execution requires a frozen no-replacement protocol")
    verify_inventory(ROOT, protocol["code_sha256"])
    verify_inventory(ROOT, {CONFIG: protocol["config_sha256"], CHECKPOINT: protocol["checkpoint_sha256"]})
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for case in protocol["cases"]:
        source = args.cohort / case["case_id"]
        verify_inventory(source, case["artifacts"])
        for arm in protocol["arms"]:
            destination = args.output / case["case_id"] / arm
            if not destination.exists():
                with tempfile.TemporaryDirectory(prefix="cc89-tensor-debug-", dir=args.work_parent) as directory:
                    workspace = Path(directory)
                    shutil.copytree(source, workspace, dirs_exist_ok=True)
                    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                        "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / ENGINE / "src"), str(ROOT / "scripts"))),
                        "PROTPARDELLE_MODEL_PARAMS": str(ROOT / ENGINE / "model_params")}
                    try:
                        with (workspace / "worker.log").open("x") as log:
                            subprocess.run([str(ROOT / "test/protpardelle-env/bin/python"), str(Path(__file__).resolve()), "worker", "--protocol", str(args.protocol),
                                "--workspace", str(workspace), "--arm", arm], env=environment, stdout=log, stderr=subprocess.STDOUT,
                                check=True, timeout=protocol["timeout_seconds"])
                    except (subprocess.SubprocessError, OSError) as exc:
                        (workspace / "outcome.json").write_text(json.dumps({"status": "execution-error", "message": str(exc)}) + "\n")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(workspace, destination)
                    (destination / "complete.json").write_text(json.dumps({"protocol_sha256": sha(args.protocol),
                        "artifacts": {p.relative_to(destination).as_posix(): sha(p) for p in sorted(destination.rglob("*")) if p.is_file()}}, indent=2, sort_keys=True) + "\n")
            marker = json.loads((destination / "complete.json").read_text())
            if marker["protocol_sha256"] != sha(args.protocol):
                raise ValueError("debug archive protocol changed")
            verify_inventory(destination, marker["artifacts"])
            outcome = json.loads((destination / "outcome.json").read_text())
            row = {"case_id": case["case_id"], "arm": arm, **outcome}
            if arm in {"full-native", "full-projected"} and row["status"] == "evaluated":
                prior = args.baselines / case["case_id"] / ("native-500" if arm == "full-native" else "projection-500") / "raw/candidate.pdb"
                row["prior_baseline_candidate_sha256"] = sha(prior)
                row["byte_identical_baseline"] = sha(prior) == row["candidate_sha256"]
            records.append(row)
            print(json.dumps({"case_id": case["case_id"], "arm": arm, "status": row["status"],
                "passed": row.get("validation", {}).get("passed"), "backbone_rmsd": row.get("quality", {}).get("gap_backbone_rmsd_angstrom"),
                "byte_identical_baseline": row.get("byte_identical_baseline")}), flush=True)
    (args.output / "analysis.json").write_text(json.dumps({"protocol_sha256": sha(args.protocol), "cases": records,
        "public_promotion": False, "complete": True}, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    freezing = commands.add_parser("freeze")
    execution = commands.add_parser("run")
    working = commands.add_parser("worker")
    for command in (freezing, execution, working):
        command.add_argument("--protocol", type=Path, required=True)
    for command in (freezing, execution):
        command.add_argument("--cohort", type=Path, required=True)
    for name in ("output", "work-parent", "baselines"):
        execution.add_argument("--" + name, type=Path, required=True)
    working.add_argument("--workspace", type=Path, required=True)
    working.add_argument("--arm", choices=tuple(ARMS), required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    {"freeze": freeze, "run": run, "worker": worker}[args.action](args)


if __name__ == "__main__":
    main()
