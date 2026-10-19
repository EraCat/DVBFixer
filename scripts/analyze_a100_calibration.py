#!/usr/bin/env python3
"""Independently audit prospective A100 masks, routing decisions, and candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path
from statistics import median

from dvbfixer.model.diffusion.adaptive_context import (
    contact_gated_expansion,
    expand_from_sample,
    validate_adaptive_transition,
)
from dvbfixer.model.diffusion.benchmark import (
    candidate_quality,
    load_pdb_coordinates,
    wilson_score_interval,
)
from dvbfixer.model.diffusion.contract import (
    ArtifactReference,
    DiffusionRequest,
    RunnerResult,
    SamplerTrace,
)
from dvbfixer.model.diffusion.protein_context import validate_context_source
from dvbfixer.model.diffusion.validate import validate_runner_result


def equivalent_validation(current, recorded):
    current = json.loads(json.dumps(asdict(current)))
    if any(current[key] != recorded[key] for key in current if key != "metrics"):
        return False
    return len(current["metrics"]) == len(recorded["metrics"]) and all(
        first["name"] == second["name"] and first["unit"] == second["unit"]
        and (first["value"] == second["value"] if first["unit"] == "count" else math.isclose(first["value"], second["value"], rel_tol=0, abs_tol=1e-12))
        for first, second in zip(current["metrics"], recorded["metrics"]))


def analyze(args):
    manifest = json.loads(args.manifest.read_text())
    digest = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    rows = []
    pending = []
    for case in manifest["cases"]:
        source_root = args.cohort / "cases" / case["case_id"]
        for relative, expected in case["artifacts"].items():
            if hashlib.sha256((source_root / relative).read_bytes()).hexdigest() != expected:
                raise ValueError("prospective cohort input changed")
        for arm in case["arms"]:
            root = args.outcomes / case["case_id"] / arm
            if not (root / "complete.json").exists() and args.allow_incomplete:
                pending.append({"case_id": case["case_id"], "arm": arm})
                continue
            marker = json.loads((root / "complete.json").read_text())
            if marker["manifest_sha256"] != digest:
                raise ValueError("prospective outcome manifest changed")
            for relative, expected in marker["artifacts"].items():
                if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
                    raise ValueError("prospective artifact digest changed")
            for relative, expected in case["artifacts"].items():
                if relative != "request.json" and hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
                    raise ValueError("prospective archived input differs from frozen cohort")
            request = DiffusionRequest.from_json((root / "request.json").read_text())
            initial = DiffusionRequest.from_json((source_root / "request.json").read_text())
            if not arm.startswith("adaptive-") and request != initial:
                raise ValueError("prospective request differs from frozen input")
            source = (root / request.normalized_pdb.path).read_bytes()
            validate_context_source(request, source)
            result = RunnerResult.from_json((root / "runner-result.json").read_text())
            outcome = json.loads((root / "outcome.json").read_text())
            validation = validate_runner_result(request, result, workspace=root)[0].summary
            if not equivalent_validation(validation, outcome["validation"]):
                raise ValueError("prospective candidate differs from independent validation")
            trace = SamplerTrace.from_json((root / result.candidates[0].sampler_trace_artifact.path).read_text())
            if (trace.callback_update_count != 200 or trace.denoising_update_count != 200 or trace.max_projection_error_angstrom != 0
                    or not trace.device.startswith("cuda") or not trace.fallback_disabled):
                raise ValueError("prospective CUDA/projection evidence mismatch")
            if any(metric.value != 0 for metric in validation.metrics if metric.name in {"fixed-heavy-atom-rmsd", "fixed-heavy-atom-max-displacement"}):
                raise ValueError("prospective fixed source changed")
            if arm.startswith("adaptive-"):
                previous = DiffusionRequest.from_json((root / "stage-0/request.json").read_text())
                if previous != initial:
                    raise ValueError("adaptive initial request differs from frozen input")
                first_result = RunnerResult.from_json((root / "stage-0/runner-result.json").read_text())
                first_validation = validate_runner_result(previous, first_result, workspace=root)[0].summary
                candidate = first_result.candidates[0].coordinate_artifact
                sampled = (root / candidate.path).read_bytes()
                if arm == "adaptive-monotonic":
                    expected = expand_from_sample(previous, source, sampled, candidate_path=candidate.path)
                else:
                    gate = manifest["adaptive_contact_gate"]
                    expected, decision = contact_gated_expansion(previous, source, sampled, candidate_path=candidate.path,
                        initial_validation_passed=first_validation.passed, distance_angstrom=gate["distance_angstrom"],
                        minimum_new_contact_residues=gate["minimum_new_contact_residues"],
                        minimum_supporting_backbone_atoms=gate["minimum_supporting_backbone_atoms"])
                    if outcome["adaptive_decisions"] != [decision]:
                        raise ValueError("prospective adaptive routing decision changed")
                if expected != request:
                    raise ValueError("prospective adaptive request differs from sampled-only policy")
                if request != previous:
                    validate_adaptive_transition(previous, request, source, sampled)
            reference = ArtifactReference("reference.pdb", hashlib.sha256((root / "reference.pdb").read_bytes()).hexdigest())
            quality = candidate_quality(result.candidates[0].candidate_id, load_pdb_coordinates(root, reference),
                load_pdb_coordinates(root, result.candidates[0].coordinate_artifact),
                generated_residues={residue for gap in request.gaps for residue in gap.generated_residues}, fixed_atoms=set(request.fixed_atoms),
                anchor_residues={anchor for gap in request.gaps for anchor in (gap.left_anchor, gap.right_anchor) if anchor},
                closure_passed="junction-peptide-connectivity" not in validation.hard_gate_failures, validation_passed=validation.passed,
                expected_generated_atoms=set(request.generated_atoms),
                interface_chain_pairs=tuple((request.gaps[0].chain, target.chain) for target in request.target_sequences if target.chain != request.gaps[0].chain))
            rows.append({"case_id": case["case_id"], "source_id": case["source_id"], "split": case["split"], "length": case["length"],
                "seed": request.seeds[0], "arm": arm, "validation_passed": validation.passed, "failed_gates": validation.hard_gate_failures,
                "quality": asdict(quality), "candidate_sha256": result.candidates[0].coordinate_artifact.sha256,
                "adaptive_decisions": outcome["adaptive_decisions"], "resources": outcome["resources"]})
    summaries = {}
    for split in ("calibration", "validation", "all"):
        for length in (5, 13, 25, 26, 50):
            for arm in sorted({row["arm"] for row in rows if row["length"] == length}):
                group = [row for row in rows if row["length"] == length and row["arm"] == arm and (split == "all" or row["split"] == split)]
                if not group:
                    continue
                passed = sum(row["validation_passed"] for row in group)
                summaries[f"{split}/gap{length}/{arm}"] = {"candidate_count": len(group), "accepted_count": passed,
                    "independent_source_count": len({row["source_id"] for row in group}),
                    "descriptive_candidate_wilson_interval_not_cluster_CI": asdict(wilson_score_interval(passed, len(group))),
                    "median_backbone_rmsd_all_candidates_angstrom": median(row["quality"]["gap_backbone_rmsd_angstrom"] for row in group)}
    report = {"manifest_sha256": digest, "summaries": summaries, "cases": rows,
        "complete": not pending, "pending": pending,
        "screened_source_count": len(manifest["screening"]), "eligible_source_count": sum(record["status"] == "eligible" for record in manifest["screening"]),
        "scope": manifest["scope"], "public_promotion": False, "independent_current_policy_revalidation": True,
        "leakage": manifest["leakage"], "no_validation_driven_parameter_changes": True}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summaries, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "cohort", "outcomes", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--allow-incomplete", action="store_true", help="Audit completed outcomes and explicitly report pending membership")
    analyze(parser.parse_args())


if __name__ == "__main__":
    main()
