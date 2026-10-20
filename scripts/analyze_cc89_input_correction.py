#!/usr/bin/env python3
"""Independently compare original and corrected known-sequence CDR inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from statistics import median

import numpy as np
from analyze_a100_relaxation import equivalent, outside_records
from run_cc89_known_sequence_holdout import evaluate, sha, verify_inventory

from dvbfixer.model.diffusion.contract import DiffusionRequest, RunnerResult, SamplerTrace
from dvbfixer.model.diffusion.protein_context import (
    source_context_position_features,
    validate_context_source,
)
from dvbfixer.model.diffusion.validate import validate_runner_result


def analyze(args):
    manifest = json.loads(args.manifest.read_text())
    protocol = json.loads(args.protocol.read_text())
    if protocol["manifest_sha256"] != sha(args.manifest):
        raise ValueError("corrected-input manifest/protocol mismatch")
    cases = {case["case_id"]: case for case in manifest["cases"]}
    rows = []
    for stage in ("raw", "refine"):
        for job in protocol["jobs"][stage]:
            case = cases[job["case_id"]]
            source = args.cohort / job["case_id"]
            verify_inventory(source, case["artifacts"])
            root = args.results / stage / job["case_id"] / f"seed{job['seed']}"
            marker = json.loads((root / "complete.json").read_text())
            if marker["protocol_sha256"] != sha(args.protocol) or marker["manifest_sha256"] != sha(args.manifest) or marker["job"] != job:
                raise ValueError("corrected-input archive binding changed")
            verify_inventory(root, marker["artifacts"])
            if sha(root / "request.json") != case["artifacts"][f"requests/cc89-seed{job['seed']}.json"]:
                raise ValueError("corrected executed request differs from the frozen source")
            request = DiffusionRequest.from_json((root / "request.json").read_text())
            original = DiffusionRequest.from_json((args.original_cohort / job["case_id"] / f"requests/cc89-seed{job['seed']}.json").read_text())
            if replace(request, protein_context=original.protein_context, backend_options=original.backend_options) != original:
                raise ValueError("input correction changed a field beyond context and positional policy")
            added = [x for x in request.backend_options if x not in original.backend_options]
            if len(added) != 1 or (added[0].name, added[0].value) != ("cc89_position_features", "source-physical-v1"):
                raise ValueError("undeclared input-correction backend option")
            validate_context_source(request, (root / request.normalized_pdb.path).read_bytes())
            if sha(root / "reference.pdb") != sha(args.original_cohort / job["case_id"] / "reference.pdb"):
                raise ValueError("input correction changed the evaluation reference")
            if stage == "refine" and marker["raw_complete_sha256"] != sha(args.results / "raw" / job["case_id"] / f"seed{job['seed']}" / "complete.json"):
                raise ValueError("corrected refinement is not bound to its raw generation")
            result = RunnerResult.from_json((root / ("runner-result.json" if stage == "raw" else "refined-runner-result.json")).read_text())
            validation, = validate_runner_result(request, result, workspace=root)
            candidate = validation.candidate
            current = evaluate(root, request, candidate.coordinate_artifact.path, summary=validation.summary)
            recorded = json.loads((root / "outcome.json").read_text())
            for key, value in current.items():
                if not equivalent(value, recorded.get(key)):
                    raise ValueError(f"corrected independent evaluation differs: {job}/{stage}/{key}")
            trace = SamplerTrace.from_json((root / candidate.sampler_trace_artifact.path).read_text())
            if "cc89-position-features=source-physical-v1" not in trace.patch_identity or trace.denoising_update_count != 500 or trace.device != "cuda" or not trace.fallback_disabled:
                raise ValueError("corrected trace omits position/CUDA provenance")
            positions, chains = source_context_position_features(request)
            digest = hashlib.sha256(np.asarray((positions, chains), dtype="<i8").tobytes()).hexdigest()
            if f"cc89-position-features-sha256={digest}" not in result.backend_provenance.deterministic_flags:
                raise ValueError("corrected provenance position digest differs from physical source features")
            generated = {(r.chain, r.residue_number, r.insertion_code) for gap in request.gaps for r in gap.generated_residues}
            if outside_records((root / candidate.coordinate_artifact.path).read_text(), generated) != outside_records((root / request.normalized_pdb.path).read_text(), generated):
                raise ValueError("corrected result changed outside-gap original atom records")
            metrics = {metric.name: metric.value for metric in validation.summary.metrics}
            rows.append({"case_id": job["case_id"], "seed": job["seed"], "stage": stage, "length": case["length"],
                "passed": validation.summary.passed, "failed_gates": validation.summary.hard_gate_failures,
                "backbone_rmsd_angstrom": current["quality"]["gap_backbone_rmsd_angstrom"],
                "candidate": current["candidate"], "d_ca_count": metrics["detectable-d-ca"],
                "fixed_max_displacement_angstrom": metrics["fixed-heavy-atom-max-displacement"],
                "local_axis_residues": case["local_axis_residues"], "full_axis_residues": case["full_axis_residues"],
                "source_position_feature_sha256": digest, "independently_revalidated": True})
    final = [r for r in rows if r["stage"] == "refine"]
    raw = [r for r in rows if r["stage"] == "raw"]
    report = {"complete": True, "protocol_sha256": sha(args.protocol), "manifest_sha256": sha(args.manifest),
        "producer_sha256": sha(Path(__file__).resolve()), "rows": rows, "raw_accepted": sum(r["passed"] for r in raw),
        "refined_accepted": sum(r["passed"] for r in final), "refined_count": len(final),
        "median_refined_backbone_rmsd_angstrom": median(r["backbone_rmsd_angstrom"] for r in final),
        "maximum_refined_backbone_rmsd_angstrom": max(r["backbone_rmsd_angstrom"] for r in final),
        "minimum_refined_backbone_rmsd_angstrom": min(r["backbone_rmsd_angstrom"] for r in final),
        "public_promotion": False, "interpretation": manifest["interpretation"]}
    if args.output.exists() or args.visual.exists():
        raise ValueError("corrected result destinations must be new")
    args.visual.mkdir(parents=True)
    for row in final:
        case_id, seed = row["case_id"], row["seed"]
        target = args.visual / case_id / f"seed{seed}"
        target.mkdir(parents=True)
        source = args.cohort / case_id
        shutil.copyfile(source / "reference.pdb", target / "01_known_reference.pdb")
        shutil.copyfile(source / "input/normalized.pdb", target / "02_gapped_full_input.pdb")
        for stage, name in (("raw", "03_corrected_raw.pdb"), ("refine", "04_corrected_refined.pdb")):
            current = next(r for r in rows if r["case_id"] == case_id and r["seed"] == seed and r["stage"] == stage)
            shutil.copyfile(args.results / stage / case_id / f"seed{seed}" / current["candidate"]["path"], target / name)
        (target / "RESULT.json").write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    with args.output.open("x") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in {"rows"}}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "protocol", "cohort", "results", "original-cohort", "output", "visual"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    analyze(args)


if __name__ == "__main__":
    main()
