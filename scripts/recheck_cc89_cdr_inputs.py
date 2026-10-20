#!/usr/bin/env python3
"""Re-evaluate original mask/seed pairs with explicit corrected input routing."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import run_cc89_known_sequence_holdout as execution

from dvbfixer.model.diffusion.contract import BackendOption, DiffusionRequest, ProteinContextPolicy
from dvbfixer.model.diffusion.protein_context import select_protein_context

ROOT = execution.ROOT


def freeze(args):
    if args.cohort.exists() or args.manifest.exists() or args.protocol.exists():
        raise ValueError("CDR correction needs new inputs and protocol")
    original = json.loads(args.source_manifest.read_text())
    cases = []
    args.cohort.mkdir(parents=True)
    for old in original["cases"]:
        if (args.stratum != "all" and old["stratum"] != args.stratum) or old["status"] != "eligible":
            continue
        source = args.source_cohort / old["case_id"]
        execution.verify_inventory(source, old["artifacts"])
        request = DiffusionRequest.from_json((source / "requests/cc89-seed7.json").read_text())
        data = (source / request.normalized_pdb.path).read_bytes()
        local = select_protein_context(replace(request, protein_context=None), data,
            ProteinContextPolicy(name="atom37-terminal-preservation-v1", target_flanks=8,
                                 same_chain_spatial=True, partner_mode="local"))
        local = replace(local, backend_options=(*local.backend_options, BackendOption("cc89_position_features", "source-physical-v1")))
        directory = args.cohort / old["case_id"]
        (directory / "input").mkdir(parents=True)
        (directory / "requests").mkdir()
        shutil.copyfile(source / "input/normalized.pdb", directory / "input/normalized.pdb")
        shutil.copyfile(source / "reference.pdb", directory / "reference.pdb")
        for seed in original["seeds"]:
            (directory / f"requests/cc89-seed{seed}.json").write_text(replace(local, seeds=(seed,)).to_json())
        cases.append({"case_id": old["case_id"], "source_id": old["source_id"], "stratum": old["stratum"],
            "status": "eligible", "cc89_eligible": True, "length": old["length"],
            "known_gap_sequence": old["known_gap_sequence"], "original_generated_residues": old["original_generated_residues"],
            "full_axis_residues": old["protein_residue_count"],
            "local_axis_residues": sum(span.stop - span.start for span in local.protein_context.spans),
            "serialization_entities": len(local.protein_context.spans),
            "conditioned_atoms": len(local.protein_context.fixed_conditioning),
            "preserved_only_atoms": len(local.protein_context.preserved_only),
            "artifacts": {p.relative_to(directory).as_posix(): execution.sha(p) for p in sorted(directory.rglob("*")) if p.is_file()}})
    manifest = {"status": "frozen-before-known-sequence-holdout-inference", "cases": cases,
        "seeds": original["seeds"], "public_protenix_workflow_controls": [], "no_replacement": True,
        "selected_stratum": args.stratum,
        "source_holdout_manifest_sha256": execution.sha(args.source_manifest),
        "method": "source-only 8-residue flanks +6/10A shells; preserve full input/output; source-physical positions; neutral phase; unchanged native sampling and CUDA refinement",
        "interpretation": "diagnostic recheck of the same known-sequence masks after input correction; not independent confirmatory acceptance"}
    with args.manifest.open("x") as stream:
        stream.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    execution.freeze(SimpleNamespace(cohort=args.cohort, manifest=args.manifest, protocol=args.protocol, supersedes=None))
    protocol = json.loads(args.protocol.read_text())
    protocol["jobs"]["modeller"] = []
    protocol["raw_parameters"]["position_feature_policy"] = "source-physical-v1"
    protocol["code_sha256"]["scripts/recheck_cc89_cdr_inputs.py"] = execution.sha(Path(__file__).resolve())
    protocol["comparison"] = manifest["interpretation"]
    args.protocol.write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"masks": len(cases), "raw_jobs": len(protocol["jobs"]["raw"]),
        "refine_jobs": len(protocol["jobs"]["refine"]), "protocol_sha256": execution.sha(args.protocol)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-cohort", "source-manifest", "cohort", "manifest", "protocol"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--stratum", choices=("antibody-cdr", "general-protein", "all"), default="antibody-cdr")
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    freeze(args)


if __name__ == "__main__":
    main()
