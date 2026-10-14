#!/usr/bin/env python3
"""Digest-verified context pilot summaries without promoting unsupported strata."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from dataclasses import asdict
from pathlib import Path
from statistics import median

from dvbfixer.model.diffusion.contract import DiffusionRequest, RunnerResult, SamplerTrace
from dvbfixer.model.diffusion.protein_context import context_evidence, validate_context_source
from dvbfixer.model.diffusion.validate import validate_runner_result


def analyze(manifest_path: Path, outcomes: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    rows = []
    for case in manifest["cases"]:
        if case["status"] != "eligible":
            continue
        for arm in manifest["arms"]:
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
            if arm in {"local-partner", "full-protein"}:
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
            rows.append({"case_id": case["case_id"], "stratum": case["stratum"], "arm": arm,
                         "validation_passed": outcome["validation"]["passed"],
                         "failed_gates": outcome["validation"]["hard_gate_failures"],
                         "candidate_sha256": candidate["coordinate_artifact"]["sha256"],
                         "gap_backbone_rmsd_angstrom": outcome["quality"]["gap_backbone_rmsd_angstrom"],
                         "reference_metrics": outcome["quality"]["reference_metrics"],
                         "causal_probe": outcome["denoiser_context_probe"],
                         "selected_fixed_atom_count": len(trace.represented_fixed_atoms),
                         "preserved_only_atom_count": len(trace.protein_context_evidence.preserved_atoms)})
    summaries = {}
    for arm in manifest["arms"]:
        selected = [row for row in rows if row["arm"] == arm]
        summaries[arm] = {"eligible_case_count": len(selected), "screened_case_count": len(manifest["cases"]),
                          "accepted_count": sum(row["validation_passed"] for row in selected),
                          "scientific_rejected_count": sum(not row["validation_passed"] for row in selected),
                          "unsupported_case_count": sum(case["status"] != "eligible" for case in manifest["cases"]),
                          "median_gap_backbone_rmsd_angstrom": float(median(row["gap_backbone_rmsd_angstrom"] for row in selected))}
    return {"schema_version": 1, "scope": "bounded-mechanistic-interface-pilot-not-confirmatory-promotion",
            "independent_current_policy_revalidation": True,
            "manifest_sha256": digest, "broad_interface_acceptance": False,
            "arms": summaries, "cases": rows}


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
