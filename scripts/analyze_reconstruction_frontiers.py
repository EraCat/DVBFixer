#!/usr/bin/env python3
"""Independent artifact, trajectory, mapping, and geometry audit of frontier studies."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from dataclasses import asdict
from pathlib import Path
from statistics import median

from dvbfixer.model.diffusion.adaptive_context import validate_adaptive_transition
from dvbfixer.model.diffusion.contract import DiffusionRequest, RunnerResult, SamplerTrace
from dvbfixer.model.diffusion.protein_context import validate_context_source
from dvbfixer.model.diffusion.validate import validate_runner_result


def analyze(manifest_path, outcomes):
    manifest = json.loads(manifest_path.read_text())
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    rows = []
    for case in manifest["cases"]:
        for arm in case["arms"]:
            root = outcomes / case["case_id"] / arm
            marker = json.loads((root / "complete.json").read_text())
            if marker["manifest_sha256"] != digest:
                raise ValueError("frontier outcome manifest mismatch")
            for relative, expected in marker["artifacts"].items():
                if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
                    raise ValueError("frontier artifact digest mismatch")
            request = DiffusionRequest.from_json((root / "request.json").read_text())
            source = (root / request.normalized_pdb.path).read_bytes()
            validate_context_source(request, source)
            result = RunnerResult.from_json((root / "runner-result.json").read_text())
            outcome = json.loads((root / "outcome.json").read_text())
            summary = validate_runner_result(request, result, workspace=root)[0].summary
            current = json.loads(json.dumps(asdict(summary)))
            recorded = outcome["validation"]
            structural_match = all(current[key] == recorded[key] for key in current if key != "metrics")
            metrics_match = len(current["metrics"]) == len(recorded["metrics"]) and all(
                first["name"] == second["name"] and first["unit"] == second["unit"]
                and (first["value"] == second["value"] if first["unit"] == "count"
                     else math.isclose(first["value"], second["value"], rel_tol=0, abs_tol=1e-12))
                for first, second in zip(current["metrics"], recorded["metrics"]))
            if not structural_match or not metrics_match:
                changed = {key: {"current": value, "recorded": outcome["validation"].get(key)} for key, value in current.items()
                           if value != outcome["validation"].get(key)}
                raise ValueError(f"frontier independent validation differs for {case['case_id']}/{arm}: {changed}")
            trace = SamplerTrace.from_json((root / result.candidates[0].sampler_trace_artifact.path).read_text())
            expected_steps = 500 if case["kind"] == "cc89-rich" else 200
            if trace.denoising_update_count != expected_steps or not trace.device.startswith("cuda") or not trace.fallback_disabled:
                raise ValueError("frontier sampling profile/device evidence mismatch")
            projection = arm == "projection-500" or case["kind"] != "cc89-rich"
            if projection and (trace.callback_update_count != expected_steps or trace.max_projection_error_angstrom != 0):
                raise ValueError("frontier projection evidence mismatch")
            if case["kind"] == "adaptive":
                previous = DiffusionRequest.from_json((root / "stage-0/request.json").read_text())
                current = DiffusionRequest.from_json((root / "stage-1/request.json").read_text())
                initial_result = RunnerResult.from_json((root / "stage-0/runner-result.json").read_text())
                validate_runner_result(previous, initial_result, workspace=root)
                candidate = initial_result.candidates[0].coordinate_artifact
                if arm == "adaptive-two-rounds":
                    if current.protein_context.adaptation_source != candidate:
                        raise ValueError("adaptive queries are not bound to the previous sampled artifact")
                    validate_adaptive_transition(previous, current, source, (root / candidate.path).read_bytes())
                elif previous != current:
                    raise ValueError("static repeat changed its scientific request")
            metric_values = {metric.name: metric.value for metric in summary.metrics}
            if metric_values["fixed-heavy-atom-max-displacement"] != 0:
                raise ValueError("frontier fixed-source coordinate drift")
            rows.append({"case_id": case["case_id"], "kind": case["kind"], "arm": arm,
                         "length": case.get("length"), "seed": request.seeds[0], "window_lengths": [len(gap.generated_residues) for gap in request.gaps],
                         "validation_passed": summary.passed, "failed_gates": summary.hard_gate_failures,
                         "gap_backbone_rmsd_angstrom": outcome["quality"]["gap_backbone_rmsd_angstrom"] if outcome["quality"] else None,
                         "candidate_sha256": result.candidates[0].coordinate_artifact.sha256,
                         "resources": outcome["resources"], "stages": outcome["stages"]})
    summaries = {}
    for kind in sorted({row["kind"] for row in rows}):
        group = [row for row in rows if row["kind"] == kind]
        summaries[kind] = {"completed_count": len(group), "accepted_count": sum(row["validation_passed"] for row in group),
                           "scientific_rejected_count": sum(not row["validation_passed"] for row in group)}
    for length in (13, 25, 26, 50):
        group = [row for row in rows if row["length"] == length]
        summaries[f"length-{length}"] = {"completed_count": len(group), "accepted_count": sum(row["validation_passed"] for row in group),
            "median_backbone_rmsd_all_candidates_angstrom": median(row["gap_backbone_rmsd_angstrom"] for row in group)}
    return {"manifest_sha256": digest, "summaries": summaries, "cases": rows, "public_promotion": False,
            "floating_metric_revalidation_absolute_tolerance": 1e-12,
            "scope": "bounded-frontier-study-not-confirmatory-acceptance", "independent_current_policy_revalidation": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "outcomes", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--public-bundle", type=Path, help="Verify and durably archive the public wide-deletion CLI bundle")
    args = parser.parse_args()
    report = analyze(args.manifest, args.outcomes)
    if args.public_bundle:
        from dvbfixer.model.diffusion.publication import read_published_bundle

        selected = read_published_bundle(args.public_bundle).selected()
        destination = args.outcomes / "public-deletion-flanks3-bundle"
        if not destination.exists():
            shutil.copytree(args.public_bundle, destination)
        archived = read_published_bundle(destination).selected()
        if archived.pdb_bytes != selected.pdb_bytes:
            raise ValueError("public wide-deletion archive differs from the verified candidate")
        report["public_wide_deletion_candidate_sha256"] = hashlib.sha256(selected.pdb_bytes).hexdigest()
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["summaries"], indent=2))


if __name__ == "__main__":
    main()
