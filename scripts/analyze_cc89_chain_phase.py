#!/usr/bin/env python3
"""Revalidate cc89 debugging/repair archives without launching a sampler."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from analyze_a100_relaxation import equivalent, outside_records
from debug_cc89_conditioning import sha
from run_a100_relaxation import quality as runner_quality
from run_a100_relaxation import verify_inventory

from dvbfixer.model.diffusion.benchmark import candidate_quality, load_pdb_coordinates
from dvbfixer.model.diffusion.contract import (
    ArtifactReference,
    DiffusionRequest,
    RunnerResult,
    SamplerTrace,
)
from dvbfixer.model.diffusion.protein_context import validate_context_source
from dvbfixer.model.diffusion.validate import (
    ValidationThresholds,
    _load_structure,
    _validate_candidate,
    validate_runner_result,
)


def compact(validation, quality):
    metrics = {m["name"]: m["value"] for m in validation["metrics"]}
    return {"passed": validation["passed"], "failed_gates": validation["hard_gate_failures"],
        "backbone_rmsd_angstrom": quality["gap_backbone_rmsd_angstrom"],
        "junction_cn_min_angstrom": metrics["junction-cn-distance-min"],
        "junction_cn_max_angstrom": metrics["junction-cn-distance-max"],
        "d_ca_count": metrics["detectable-d-ca"],
        "fixed_max_displacement_angstrom": metrics["fixed-heavy-atom-max-displacement"]}


def archive(root, protocol_path, input_inventory):
    marker = json.loads((root / "complete.json").read_text())
    expected = marker.get("protocol_sha256", marker.get("manifest_sha256"))
    if expected != sha(protocol_path):
        raise ValueError("archive belongs to another frozen protocol")
    verify_inventory(root, marker["artifacts"])
    verify_inventory(root, input_inventory)
    request = DiffusionRequest.from_json((root / "request.json").read_text())
    source = (root / request.normalized_pdb.path).read_bytes()
    validate_context_source(request, source)
    return request


def assert_background(root, request, candidate):
    generated = {(r.chain, r.residue_number, r.insertion_code) for gap in request.gaps for r in gap.generated_residues}
    if outside_records((root / candidate).read_text(), generated) != outside_records((root / request.normalized_pdb.path).read_text(), generated):
        raise ValueError("debug/repair candidate changed original outside-gap atom records")


def debug_study(protocol_path, outcomes, baselines=None):
    protocol = json.loads(protocol_path.read_text())
    rows = []
    for case in protocol["cases"]:
        for arm in case.get("arms", protocol["arms"]):
            root = outcomes / case["case_id"] / arm
            request = archive(root, protocol_path, case["artifacts"])
            recorded = json.loads((root / "outcome.json").read_text())
            if recorded["status"] != "evaluated":
                rows.append({"case_id": case["case_id"], "arm": arm, "status": recorded["status"]})
                continue
            if recorded["settings"] != protocol["arms"][arm] or recorded["forward_calls"] != protocol["steps"]:
                raise ValueError("debug execution differs from the frozen intervention")
            if recorded["tensor_audit"]["generated_crop_max_abs_coordinate"] != 0 or recorded["tensor_audit"]["learned_context_source_alignment_max_error_angstrom"] > 0.001:
                raise ValueError("debug runtime tensor audit failed")
            if recorded["projection_max_error_angstrom"] != 0:
                raise ValueError("debug projected context drift")
            expected_callbacks = protocol["steps"] if protocol["arms"][arm]["project_all_represented_fixed_atoms"] else 0
            if recorded["callback_count"] != expected_callbacks:
                raise ValueError("debug callback evidence incomplete")
            summary, _ = _validate_candidate(request, _load_structure(root, request.normalized_pdb.path, request.normalized_pdb.sha256),
                _load_structure(root, "candidate.pdb", recorded["candidate_sha256"]), ValidationThresholds())
            if not equivalent(asdict(summary), recorded["validation"]):
                raise ValueError("debug independent structural validation differs")
            quality = candidate_quality("cc89-debug", load_pdb_coordinates(root, ArtifactReference("reference.pdb", sha(root / "reference.pdb"))),
                load_pdb_coordinates(root, ArtifactReference("candidate.pdb", recorded["candidate_sha256"])),
                generated_residues={r for g in request.gaps for r in g.generated_residues}, fixed_atoms=set(request.fixed_atoms),
                anchor_residues={r for g in request.gaps for r in (g.left_anchor, g.right_anchor) if r},
                closure_passed="junction-peptide-connectivity" not in summary.hard_gate_failures,
                validation_passed=summary.passed, expected_generated_atoms=set(request.generated_atoms))
            if not equivalent(asdict(quality), recorded["quality"]):
                raise ValueError("debug independent reference measurements differ")
            assert_background(root, request, "candidate.pdb")
            row = {"case_id": case["case_id"], "arm": arm, "status": "evaluated", **compact(recorded["validation"], recorded["quality"]),
                "candidate_sha256": recorded["candidate_sha256"], "conditioned_residues": recorded["tensor_audit"]["learned_context_residue_count"]}
            if baselines is not None and arm in {"full-native", "full-projected"}:
                prior = baselines / case["case_id"] / ("native-500" if arm == "full-native" else "projection-500") / "raw/candidate.pdb"
                row["byte_identical_prior_baseline"] = sha(prior) == recorded["candidate_sha256"]
                if not row["byte_identical_prior_baseline"]:
                    raise ValueError("debug baseline did not reproduce the previous sampler output")
            rows.append(row)
    return rows


def repair_study(args):
    manifest = json.loads(args.repair_manifest.read_text())
    refinement_protocol = json.loads(args.refinement_protocol.read_text())
    refinement_cases = {(c["case_id"], c["arm"]): c for c in refinement_protocol["cases"]}
    rows = []
    for case in manifest["cases"]:
        for arm in case["arms"]:
            raw_root = args.repair / case["case_id"] / arm
            request = archive(raw_root, args.repair_manifest, case["artifacts"])
            original = DiffusionRequest.from_json((args.original_cohort / case["case_id"] / "request.json").read_text())
            added = [option for option in request.backend_options if option not in original.backend_options]
            if len(added) != 1 or (added[0].name, added[0].value) != ("cc89_chain_phase", "neutral-v1") or replace(request, backend_options=original.backend_options) != original:
                raise ValueError("repair changed original request beyond the declared chain phase")
            raw = RunnerResult.from_json((raw_root / "runner-result.json").read_text())
            summary = validate_runner_result(request, raw, workspace=raw_root)[0].summary
            trace = SamplerTrace.from_json((raw_root / raw.candidates[0].sampler_trace_artifact.path).read_text())
            if "cc89-chain-phase=neutral-v1" not in trace.patch_identity or not trace.fallback_disabled or trace.device != "cuda":
                raise ValueError("repair trace omits the explicit CUDA chain-phase intervention")
            control_arm = "zero-phase-native" if arm == "neutral-native" else "zero-phase-projected"
            control = args.axis_outcomes / case["case_id"] / control_arm / "candidate.pdb"
            if sha(control) != raw.candidates[0].coordinate_artifact.sha256:
                raise ValueError("denoiser-only repair does not reproduce the causal zero-phase control")
            final_root = args.refined / case["case_id"] / arm
            archive(final_root, args.refinement_protocol, case["artifacts"])
            if sha(raw_root / "complete.json") != refinement_cases[(case["case_id"], arm)]["raw_complete_sha256"]:
                raise ValueError("refinement is not bound to the exact frozen repair output")
            final = RunnerResult.from_json((final_root / "cuda-runner-result.json").read_text())
            post = validate_runner_result(request, final, workspace=final_root)[0].summary
            recorded = json.loads((final_root / "cuda-outcome.json").read_text())
            if not equivalent(asdict(summary), recorded["raw"]["validation"]) or not equivalent(asdict(post), recorded["refined"]["validation"]):
                raise ValueError("repair/refinement independent structural validation differs")
            if not equivalent(runner_quality(raw_root, request, raw, summary), recorded["raw"]["quality"]) or not equivalent(
                runner_quality(final_root, request, final, post), recorded["refined"]["quality"]
            ):
                raise ValueError("repair/refinement independent reference measurements differ")
            assert_background(raw_root, request, raw.candidates[0].coordinate_artifact.path)
            assert_background(final_root, request, final.candidates[0].coordinate_artifact.path)
            rows.append({"case_id": case["case_id"], "arm": arm,
                "raw": compact(recorded["raw"]["validation"], recorded["raw"]["quality"]),
                "refined": compact(recorded["refined"]["validation"], recorded["refined"]["quality"]),
                "candidate_sha256": final.candidates[0].coordinate_artifact.sha256,
                "matches_causal_control_bytes": True, "only_declared_request_change": True})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("tensor-protocol", "tensor-outcomes", "axis-protocol", "axis-outcomes", "original-cohort", "baselines",
                 "repair-manifest", "repair", "refinement-protocol", "refined", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    if args.output.exists():
        parser.error("analysis output must be new")
    tensor = debug_study(args.tensor_protocol, args.tensor_outcomes, args.baselines)
    axes = debug_study(args.axis_protocol, args.axis_outcomes)
    repaired = repair_study(args)
    report = {"complete": True, "producer_sha256": sha(Path(__file__).resolve()),
        "protocol_digests": {name: sha(getattr(args, name)) for name in ("tensor_protocol", "axis_protocol", "repair_manifest", "refinement_protocol")},
        "tensor_controls": tensor, "axis_controls": axes, "repair": repaired,
        "counts": {"tensor_controls": len(tensor), "axis_controls": len(axes), "repair": len(repaired),
                   "raw_repair_accepted": sum(row["raw"]["passed"] for row in repaired),
                   "refined_repair_accepted": sum(row["refined"]["passed"] for row in repaired)},
        "public_promotion": False, "scope": "causal-debug-and-same-seed-repair-confirmation; two deposited sources, not broad acceptance"}
    with args.output.open("x") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["counts"], indent=2))


if __name__ == "__main__":
    main()
