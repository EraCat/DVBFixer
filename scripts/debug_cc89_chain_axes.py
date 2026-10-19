#!/usr/bin/env python3
"""Source-chain positional controls and explicit monomer controls for cc89.

Separate motif serialization labels from physical source-chain identity. The
zero-chain-phase arm retains residue-index gaps and is a private intervention,
never a claim that distinct chains are one continuous protein.
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
from dataclasses import replace
from pathlib import Path

import debug_cc89_conditioning as base

from dvbfixer.model.diffusion.contract import (
    ArtifactReference,
    DiffusionRequest,
    ProteinContextPolicy,
)
from dvbfixer.model.diffusion.protein_context import sampling_entities, select_protein_context

ROOT = base.ROOT


def source_position_features(request, chain_gap=200):
    """Use original target positions, not compacted fragment ordinals/proxy IDs."""
    chain_numbers = {target.chain: i for i, target in enumerate(request.target_sequences)}
    offsets, total = {}, 0
    for target in request.target_sequences:
        offsets[target.chain] = total
        total += len(target.sequence)
    residue_indices, chain_indices = [], []
    for entity, span in zip(sampling_entities(request), request.protein_context.spans, strict=True):
        number = chain_numbers[span.chain]
        residue_indices.extend(offsets[span.chain] + position + 1 + chain_gap * number for position in range(span.start, span.stop))
        chain_indices.extend([number] * len(entity.target.sequence))
    return residue_indices, chain_indices


def chain_only_pdb(data, chain):
    """Explicit protein-chain ablation; never change the parent full-input cohort."""
    return b"".join(line for line in data.splitlines(keepends=True)
        if line.startswith(b"ATOM  ") and chr(line[21]) == chain) + b"TER\nEND\n"


def materialize_monomer(source, destination, chain):
    request = DiffusionRequest.from_json((source / "request.json").read_text())
    gaps = tuple(gap for gap in request.gaps if gap.chain == chain)
    if not gaps:
        raise ValueError("monomer control requires a gap in the declared chain")
    normalized = chain_only_pdb((source / request.normalized_pdb.path).read_bytes(), chain)
    (destination / "input").mkdir(parents=True)
    (destination / "input/normalized.pdb").write_bytes(normalized)
    (destination / "reference.pdb").write_bytes(chain_only_pdb((source / "reference.pdb").read_bytes(), chain))
    request = replace(request, normalized_pdb=ArtifactReference("input/normalized.pdb", hashlib.sha256(normalized).hexdigest()),
        target_sequences=tuple(t for t in request.target_sequences if t.chain == chain),
        sequence_placements=tuple(p for p in request.sequence_placements if p.chain == chain), gaps=gaps,
        fixed_atoms=tuple(a for a in request.fixed_atoms if a.chain == chain),
        generated_atoms=tuple(a for a in request.generated_atoms if a.chain == chain), protein_context=None,
        retained_explicit_links=(), template_ownership=(), regenerated_template_ownership=None)
    request = select_protein_context(request, normalized, ProteinContextPolicy(partner_mode="none"))
    (destination / "request.json").write_text(request.to_json())


def freeze(args):
    if args.protocol.exists() or args.cohort.exists():
        raise ValueError("axis controls need new frozen protocol and cohort")
    args.cohort.mkdir(parents=True)
    cases = []
    for name in base.CASES:
        destination = args.cohort / name
        shutil.copytree(args.source_cohort / name, destination)
        cases.append({"case_id": name, "role": "rich-source-axes",
            "arms": ["source-native", "source-projected", "zero-phase-native", "zero-phase-projected"]})
    for name, origin, chain in (("monomer-1emv-A", "cc89-joint", "A"), ("monomer-1emv-B", "cc89-joint", "B"),
                                ("monomer-7k8s-H", "cc89-case-insertion", "H")):
        destination = args.cohort / name
        materialize_monomer(args.source_cohort / origin, destination, chain)
        cases.append({"case_id": name, "role": "explicit-monomer-control", "arms": ["monomer-native", "monomer-projected"],
            "parent_case": origin, "chain": chain})
    for case in cases:
        directory = args.cohort / case["case_id"]
        case["artifacts"] = {p.relative_to(directory).as_posix(): base.sha(p) for p in sorted(directory.rglob("*")) if p.is_file()}
    previous = json.loads(args.tensor_protocol.read_text())
    protocol = {**previous, "status": "frozen-before-cc89-source-axis-controls", "cases": cases,
        "prior_tensor_protocol_sha256": base.sha(args.tensor_protocol),
        "source_cohort_manifest_sha256": base.sha(ROOT / "docs/research/reconstruction-frontiers-cohort.json"),
        "hypotheses": ["proxy fragments incorrectly change physical source chain and relative positional features",
                       "single-chain versus multichain generation with the same gap sequence and dense conditioning"],
        "arms": {name: {"learned_motif_residue_limit": None, "project_all_represented_fixed_atoms": projected,
            "project_fixed_self_conditioning": False, "axis_mode": mode}
            for name, mode, projected in (("source-native", "source", False), ("source-projected", "source", True),
                ("zero-phase-native", "zero-phase", False), ("zero-phase-projected", "zero-phase", True),
                ("monomer-native", "legacy", False), ("monomer-projected", "legacy", True))},
        "public_promotion": False}
    protocol["code_sha256"]["scripts/debug_cc89_chain_axes.py"] = base.sha(Path(__file__).resolve())
    from run_a100_relaxation import verify_inventory

    verify_inventory(ROOT, protocol["code_sha256"])
    with args.protocol.open("x") as stream:
        stream.write(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"outcomes": sum(len(case["arms"]) for case in cases), "protocol_sha256": base.sha(args.protocol)}))


def worker(args):
    sys.dont_write_bytecode = True
    import protpardelle.core.models as models
    import torch

    original_loader = models.load_model
    protocol = json.loads(args.protocol.read_text())
    mode = protocol["arms"][args.arm]["axis_mode"]
    request = DiffusionRequest.from_json((args.workspace / "request.json").read_text())

    def load_model(*loader_args, **loader_kwargs):
        model = original_loader(*loader_args, **loader_kwargs)
        original_maker = model.make_seq_mask_for_sampling

        def make_axes(**kwargs):
            mask, residx, chainidx = original_maker(**kwargs)
            if mode == "source":
                ri, ci = source_position_features(request)
                if residx.shape != (1, len(ri)):
                    raise ValueError("source positions do not match the unchanged engine axis")
                residx = torch.as_tensor([ri], dtype=residx.dtype, device=residx.device)
                chainidx = torch.as_tensor([ci], dtype=chainidx.dtype, device=chainidx.device)
            elif mode == "zero-phase":
                chainidx = torch.zeros_like(chainidx)  # Keep all residue-index chain gaps.
            return mask, residx, chainidx

        model.make_seq_mask_for_sampling = make_axes
        return model

    models.load_model = load_model
    try:
        base.worker(args)
    finally:
        models.load_model = original_loader


def run(args):
    from run_a100_relaxation import verify_inventory

    protocol = json.loads(args.protocol.read_text())
    if protocol["status"] != "frozen-before-cc89-source-axis-controls" or not protocol["no_replacement"]:
        raise ValueError("axis controls require frozen no-replacement protocol")
    verify_inventory(ROOT, protocol["code_sha256"])
    verify_inventory(ROOT, {base.CONFIG: protocol["config_sha256"], base.CHECKPOINT: protocol["checkpoint_sha256"]})
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for case in protocol["cases"]:
        source = args.cohort / case["case_id"]
        verify_inventory(source, case["artifacts"])
        for arm in case["arms"]:
            destination = args.output / case["case_id"] / arm
            if not destination.exists():
                with tempfile.TemporaryDirectory(prefix="cc89-axis-debug-", dir=args.work_parent) as directory:
                    workspace = Path(directory)
                    shutil.copytree(source, workspace, dirs_exist_ok=True)
                    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
                        "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT / base.ENGINE / "src"), str(ROOT / "scripts"))),
                        "PROTPARDELLE_MODEL_PARAMS": str(ROOT / base.ENGINE / "model_params")}
                    try:
                        with (workspace / "worker.log").open("x") as log:
                            subprocess.run([str(ROOT / "test/protpardelle-env/bin/python"), str(Path(__file__).resolve()), "worker", "--protocol", str(args.protocol),
                                "--workspace", str(workspace), "--arm", arm], env=environment, stdout=log, stderr=subprocess.STDOUT,
                                check=True, timeout=protocol["timeout_seconds"])
                    except (subprocess.SubprocessError, OSError) as exc:
                        (workspace / "outcome.json").write_text(json.dumps({"status": "execution-error", "message": str(exc)}) + "\n")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(workspace, destination)
                    (destination / "complete.json").write_text(json.dumps({"protocol_sha256": base.sha(args.protocol),
                        "artifacts": {p.relative_to(destination).as_posix(): base.sha(p) for p in sorted(destination.rglob("*")) if p.is_file()}}, indent=2, sort_keys=True) + "\n")
            marker = json.loads((destination / "complete.json").read_text())
            if marker["protocol_sha256"] != base.sha(args.protocol):
                raise ValueError("axis-control archive protocol changed")
            verify_inventory(destination, marker["artifacts"])
            outcome = json.loads((destination / "outcome.json").read_text())
            row = {"case_id": case["case_id"], "role": case["role"], "arm": arm, **outcome}
            records.append(row)
            print(json.dumps({"case_id": case["case_id"], "arm": arm, "status": row["status"], "passed": row.get("validation", {}).get("passed"),
                "backbone_rmsd": row.get("quality", {}).get("gap_backbone_rmsd_angstrom")}), flush=True)
    (args.output / "analysis.json").write_text(json.dumps({"protocol_sha256": base.sha(args.protocol), "cases": records,
        "public_promotion": False, "complete": True}, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    freezing = commands.add_parser("freeze")
    for name in ("source-cohort", "tensor-protocol"):
        freezing.add_argument("--" + name, type=Path, required=True)
    execution = commands.add_parser("run")
    for name in ("output", "work-parent"):
        execution.add_argument("--" + name, type=Path, required=True)
    working = commands.add_parser("worker")
    working.add_argument("--workspace", type=Path, required=True)
    working.add_argument("--arm", required=True)
    for command in (freezing, execution):
        command.add_argument("--cohort", type=Path, required=True)
    for command in (freezing, execution, working):
        command.add_argument("--protocol", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    {"freeze": freeze, "run": run, "worker": worker}[args.action](args)


if __name__ == "__main__":
    main()
