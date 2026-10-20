#!/usr/bin/env python3
"""Confirm corrected local/source-position inputs through the ordinary adapter."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import run_cc89_known_sequence_holdout as execution

from dvbfixer.model.diffusion.contract import BackendOption, DiffusionRequest

ROOT = execution.ROOT


def freeze(args):
    if args.cohort.exists() or args.manifest.exists() or args.protocol.exists():
        raise ValueError("confirmation needs new inputs, manifest and execution protocol")
    controls = json.loads(args.control_protocol.read_text())
    if controls["status"] != "frozen-before-local-input-controls":
        raise ValueError("local diagnostic control protocol required")
    cases = []
    args.cohort.mkdir(parents=True)
    for control in controls["cases"]:
        name = control["case_id"]
        source = args.source_cohort / name
        execution.verify_inventory(source, {"request.json": control["local_request_sha256"],
            "input/normalized.pdb": control["input_sha256"], "reference.pdb": control["reference_sha256"]})
        request = DiffusionRequest.from_json((source / "request.json").read_text())
        request = replace(request, backend_options=(*request.backend_options, BackendOption("cc89_position_features", "source-physical-v1")))
        destination = args.cohort / name
        (destination / "requests").mkdir(parents=True)
        (destination / "input").mkdir()
        shutil.copyfile(source / "input/normalized.pdb", destination / "input/normalized.pdb")
        shutil.copyfile(source / "reference.pdb", destination / "reference.pdb")
        (destination / "requests/cc89-seed7.json").write_text(request.to_json())
        control_root = args.control_results / "samples" / name / "source-native"
        marker = json.loads((control_root / "complete.json").read_text())
        if marker["protocol_sha256"] != execution.sha(args.control_protocol):
            raise ValueError("confirmation reference belongs to another input control")
        execution.verify_inventory(control_root, marker["artifacts"])
        result = json.loads((control_root / "runner-result.json").read_text())
        cases.append({"case_id": name, "status": "eligible", "cc89_eligible": True,
            "source_id": "9WGM" if name.startswith("general-") else "1MIM" if "1mim" in name else "1BVL",
            "stratum": "general-protein" if name.startswith("general-") else "antibody-cdr", "length": 5,
            "expected_control_candidate_sha256": result["candidates"][0]["coordinate_artifact"]["sha256"],
            "artifacts": {p.relative_to(destination).as_posix(): execution.sha(p) for p in sorted(destination.rglob("*")) if p.is_file()}})
    manifest = {"status": "frozen-before-known-sequence-holdout-inference", "no_replacement": True,
        "cases": cases, "seeds": [7], "public_protenix_workflow_controls": [],
        "control_protocol_sha256": execution.sha(args.control_protocol),
        "interpretation": "ordinary-adapter confirmation of diagnostic input correction; not independent method acceptance"}
    with args.manifest.open("x") as stream:
        stream.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    execution.freeze(SimpleNamespace(cohort=args.cohort, manifest=args.manifest, protocol=args.protocol, supersedes=None))
    protocol = json.loads(args.protocol.read_text())
    protocol["jobs"]["modeller"] = []
    protocol["raw_parameters"]["position_feature_policy"] = "source-physical-v1"
    protocol["code_sha256"]["scripts/confirm_cc89_source_inputs.py"] = execution.sha(Path(__file__).resolve())
    protocol["comparison"] = manifest["interpretation"]
    args.protocol.write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"raw_jobs": 5, "refine_jobs": 5, "protocol_sha256": execution.sha(args.protocol)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    freezing = commands.add_parser("freeze")
    for name in ("source-cohort", "control-protocol", "control-results", "cohort", "manifest", "protocol"):
        freezing.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    freeze(args)


if __name__ == "__main__":
    main()
