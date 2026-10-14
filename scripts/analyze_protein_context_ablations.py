#!/usr/bin/env python3
"""Digest-verified context pilot summaries without promoting unsupported strata."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from dataclasses import asdict, replace
from pathlib import Path
from statistics import median

from dvbfixer.model.diffusion.benchmark import candidate_quality, load_pdb_coordinates
from dvbfixer.model.diffusion.context_metrics import measure_gap_environment
from dvbfixer.model.diffusion.contract import (
    ArtifactReference,
    DiffusionRequest,
    RunnerResult,
    SamplerTrace,
)
from dvbfixer.model.diffusion.protein_context import context_evidence, validate_context_source
from dvbfixer.model.diffusion.validate import build_validated_result, validate_runner_result


def analyze(manifest_path: Path, outcomes: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    rows = []
    for case in manifest["cases"]:
        if case["status"] != "eligible":
            continue
        for arm in case.get("arms", manifest["arms"]):
            if case.get("arm_support", {}).get(arm, {}).get("status") == "unsupported":
                continue
            root = outcomes / case["case_id"] / arm
            marker = json.loads((root / "complete.json").read_text())
            if marker["manifest_sha256"] != digest:
                raise ValueError("context outcome manifest identity changed")
            for relative, expected in marker["artifacts"].items():
                if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
                    raise ValueError("context outcome artifact digest changed")
            request = DiffusionRequest.from_json((root / "request.json").read_text())
            validate_context_source(request, (root / request.normalized_pdb.path).read_bytes())
            outcome = json.loads((root / "outcome.json").read_text())
            candidate = outcome["candidate"]
            trace = SamplerTrace.from_json((root / candidate["sampler_trace_artifact"]["path"]).read_text())
            if trace.protein_context_evidence != context_evidence(request, trace.atom_order) or trace.fixed_atoms != request.fixed_atoms:
                raise ValueError("context trace plan/mapping evidence changed")
            if trace.engine_revision != "85767b811c40ed46e73a9b39519cf6bfca8701ba" or not trace.device.startswith("cuda") or not trace.fallback_disabled:
                raise ValueError("context trace did not prove the frozen CUDA source")
            # Reconstruct the validation input from verified artifacts, rather
            # than accepting the worker's recorded pass/fail verdict.
            runner_result = RunnerResult.from_dict({
                "schema_version": request.schema_version, "status": "success",
                "candidates": [candidate],
                "runner_diagnostics": {"exit_code": 0, "timed_out": False},
                "backend_provenance": {
                    "backend": trace.profile, "runner_protocol_version": request.schema_version,
                    "engine_repository": trace.engine_repository,
                    "engine_revision": trace.engine_revision, "device": trace.device,
                },
            })
            validation = validate_runner_result(request, runner_result, workspace=root)[0].summary
            if json.loads(json.dumps(asdict(validation))) != outcome["validation"]:
                raise ValueError("context outcome differs from independent current-policy validation")
            if arm in {"local-partner", "full-protein"} or outcome["denoiser_context_probe"] is not None:
                probe = outcome["denoiser_context_probe"]
                gate = manifest["primary_causal_gate"]
                if (probe is None or probe["repeat_max_abs_delta_angstrom"] != gate["repeat_max_abs_delta_angstrom"]
                        or probe["step_index"] != gate["probe_step_index"]
                        or probe["partner_translation_angstrom"] != gate["partner_translation_angstrom"]
                        or probe["same_features_and_sigma"] is not True
                        or not math.isfinite(probe["generated_response_max_displacement_angstrom"])
                        or probe["generated_response_max_displacement_angstrom"] < gate["minimum_generated_response_angstrom"]):
                    raise ValueError("frozen causal denoiser gate failed")
            validation_metrics = {metric["name"]: metric["value"] for metric in outcome["validation"]["metrics"]}
            if arm != "template-only" and (trace.callback_update_count != 200 or trace.max_projection_error_angstrom != 0.0 or validation_metrics["fixed-heavy-atom-max-displacement"] != 0.0):
                raise ValueError("context projection/fixed-coordinate hard gate failed")
            reference = load_pdb_coordinates(root, ArtifactReference("reference.pdb", hashlib.sha256((root / "reference.pdb").read_bytes()).hexdigest()))
            raw = RunnerResult.from_dict({**runner_result.to_dict(), "candidates": [{
                **candidate, "candidate_id": candidate["candidate_id"].removesuffix("-refined"),
                "coordinate_artifact": {"path": "raw/candidate.pdb", "sha256": marker["artifacts"]["raw/candidate.pdb"]},
                "sampler_trace_artifact": {"path": "raw/sampler-trace.json", "sha256": marker["artifacts"]["raw/sampler-trace.json"]},
                "postprocessing_failures": [], "warnings": [],
            }]})
            raw_validation = validate_runner_result(request, raw, workspace=root)[0].summary
            raw_coordinates = load_pdb_coordinates(root, raw.candidates[0].coordinate_artifact)
            raw_quality = candidate_quality(raw.candidates[0].candidate_id, reference, raw_coordinates,
                generated_residues={residue for gap in request.gaps for residue in gap.generated_residues},
                fixed_atoms=set(request.fixed_atoms), anchor_residues={anchor for gap in request.gaps for anchor in (gap.left_anchor, gap.right_anchor) if anchor},
                closure_passed="junction-peptide-connectivity" not in raw_validation.hard_gate_failures,
                validation_passed=raw_validation.passed,
                interface_chain_pairs=tuple((request.gaps[0].chain, target.chain) for target in request.target_sequences if target.chain != request.gaps[0].chain),
                expected_generated_atoms=set(request.generated_atoms))
            rows.append({"case_id": case["case_id"], "stratum": case["stratum"], "arm": arm,
                         "seed": request.seeds[0],
                         "source_sha256": case.get("source_sha256"),
                         "raw_candidate_sha256": raw.candidates[0].coordinate_artifact.sha256,
                         "raw_quality": asdict(raw_quality),
                         "validation_passed": outcome["validation"]["passed"],
                         "failed_gates": outcome["validation"]["hard_gate_failures"],
                         "candidate_sha256": candidate["coordinate_artifact"]["sha256"],
                         "gap_backbone_rmsd_angstrom": outcome["quality"]["gap_backbone_rmsd_angstrom"],
                         "reference_metrics": outcome["quality"]["reference_metrics"],
                         "causal_probe": outcome["denoiser_context_probe"],
                         "selected_fixed_atom_count": len(trace.represented_fixed_atoms),
                          "preserved_only_atom_count": len(trace.protein_context_evidence.preserved_atoms),
                          "gap_environment": [asdict(metric) for metric in measure_gap_environment(request,
                              reference,
                              load_pdb_coordinates(root, runner_result.candidates[0].coordinate_artifact))]})
    summaries = {}
    for arm in manifest["arms"]:
        selected = [row for row in rows if row["arm"] == arm]
        screened = [case for case in manifest["cases"] if arm in case.get("arms", manifest["arms"])]
        summaries[arm] = {"eligible_case_count": len(selected), "screened_case_count": len(screened),
                          "accepted_count": sum(row["validation_passed"] for row in selected),
                          "scientific_rejected_count": sum(not row["validation_passed"] for row in selected),
                          "unsupported_case_count": sum(case["status"] != "eligible" or case.get("arm_support", {}).get(arm, {}).get("status") == "unsupported" for case in screened),
                          "median_gap_backbone_rmsd_angstrom": float(median(row["gap_backbone_rmsd_angstrom"] for row in selected)) if selected else None}
    paired = []
    for case in manifest["cases"]:
        by_arm = {row["arm"]: row for row in rows if row["case_id"] == case["case_id"]}
        if {"same-chain-spatial", "local-partner-refined"} <= by_arm.keys():
            first, second = by_arm["same-chain-spatial"], by_arm["local-partner-refined"]
            paired.append({"case_id": case["case_id"], "stratum": case["stratum"],
                "context_only_raw_backbone_rmsd_delta_angstrom": second["raw_quality"]["gap_backbone_rmsd_angstrom"] - first["raw_quality"]["gap_backbone_rmsd_angstrom"],
                "raw_bytes_identical": first["raw_candidate_sha256"] == second["raw_candidate_sha256"],
                "context_raw_validation_passed": second["raw_quality"]["validation_passed"],
                "same_chain_raw_validation_passed": first["raw_quality"]["validation_passed"]})
    ranking = []
    for case in manifest["cases"]:
        seed_case = next((item for item in manifest["cases"] if item["case_id"] == case["case_id"] + "-seed19"), None)
        arm = "local-partner-refined"
        if seed_case is None or case.get("arm_support", {}).get(arm, {}).get("status") == "unsupported":
            continue
        roots = [outcomes / item["case_id"] / arm for item in (case, seed_case)]
        request = DiffusionRequest.from_json((roots[0] / "request.json").read_text())
        outcomes_pair = [json.loads((root / "outcome.json").read_text()) for root in roots]
        seed_request = DiffusionRequest.from_json((roots[1] / "request.json").read_text())
        if replace(seed_request, seeds=request.seeds) != request:
            raise ValueError("two-seed ranking cases have different scientific masks or context plans")
        request = replace(request, normalized_pdb=ArtifactReference(roots[0].relative_to(outcomes).as_posix() + "/" + request.normalized_pdb.path,
                                                                   request.normalized_pdb.sha256), candidate_count=2, seeds=(7, 19))
        candidates = []
        for root, outcome in zip(roots, outcomes_pair):
            candidate = dict(outcome["candidate"])
            for key in ("coordinate_artifact", "sampler_trace_artifact"):
                candidate[key] = {**candidate[key], "path": root.relative_to(outcomes).as_posix() + "/" + candidate[key]["path"]}
            candidates.append(candidate)
        combined = RunnerResult.from_dict({**runner_result.to_dict(), "candidates": candidates})
        validated = build_validated_result(request, combined, workspace=outcomes)
        valid_quality = {outcome["candidate"]["candidate_id"]: outcome["quality"]["gap_backbone_rmsd_angstrom"]
                         for outcome in outcomes_pair if outcome["validation"]["passed"]}
        first = validated.candidates[0].candidate_id if valid_quality else None
        ranking.append({"case_id": case["case_id"], "candidate_count": 2, "passing_count": len(valid_quality),
                        "selected_candidate_id": first,
                        "selected_gap_backbone_rmsd_angstrom": valid_quality.get(first),
                        "oracle_valid_gap_backbone_rmsd_angstrom": min(valid_quality.values()) if valid_quality else None,
                        "ranking_regret_angstrom": valid_quality[first] - min(valid_quality.values()) if first else None})
    return {"schema_version": 2, "scope": manifest.get("scope", "bounded-mechanistic-interface-pilot-not-confirmatory-promotion"),
            "independent_current_policy_revalidation": True,
            "manifest_sha256": digest, "broad_interface_acceptance": False,
            "independent_source_digest_count": len({case.get("source_sha256") for case in manifest["cases"] if case.get("source_sha256")}),
            "arms": summaries, "cases": rows, "paired_context_only_raw_comparisons": paired, "two_seed_current_policy_ranking": ranking}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-bundle", type=Path, help="Verify and archive a completed public CLI context bundle")
    args = parser.parse_args()
    result = analyze(args.manifest, args.outcomes)
    if args.public_bundle:
        from dvbfixer.model.diffusion.publication import read_published_bundle

        selected = read_published_bundle(args.public_bundle).selected()
        destination = args.outcomes / "public-cli-bundle"
        if not destination.exists():
            shutil.copytree(args.public_bundle, destination)
        if read_published_bundle(destination).selected().pdb_bytes != selected.pdb_bytes:
            raise ValueError("public CLI archive differs from verified candidate")
        result["public_cli_candidate_sha256"] = hashlib.sha256(selected.pdb_bytes).hexdigest()
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["arms"], indent=2))


if __name__ == "__main__":
    main()
