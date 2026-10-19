#!/usr/bin/env python3
"""Revalidate every frozen cc89 control from its archived coordinates and trace."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import median

from analyze_a100_calibration import equivalent_validation

from dvbfixer.model.diffusion.contract import DiffusionRequest, RunnerResult, SamplerTrace
from dvbfixer.model.diffusion.protein_context import validate_context_source
from dvbfixer.model.diffusion.validate import validate_runner_result


def analyze(args):
    manifest = json.loads(args.manifest.read_text())
    digest = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    rows = []
    for case in manifest["cases"]:
        for arm, settings in manifest["configurations"].items():
            root = args.outcomes / case["case_id"] / arm
            marker = json.loads((root / "complete.json").read_text())
            if marker["manifest_sha256"] != digest:
                raise ValueError("cc89 outcome belongs to another manifest")
            for inventory in (marker["artifacts"], case["artifacts"]):
                for relative, expected in inventory.items():
                    if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
                        raise ValueError("cc89 archived artifact differs from frozen digest")
            request = DiffusionRequest.from_json((root / "request.json").read_text())
            validate_context_source(request, (root / request.normalized_pdb.path).read_bytes())
            result = RunnerResult.from_json((root / "runner-result.json").read_text())
            outcome = json.loads((root / "outcome.json").read_text())
            summary = json.loads((root / outcome["summary"]).read_text())
            validation = validate_runner_result(request, result, workspace=root)[0].summary
            if not equivalent_validation(validation, outcome["validation"]):
                raise ValueError("cc89 current validation differs from recorded outcome")
            if outcome["sampling"] != settings or any(summary[key] != value for key, value in settings.items()):
                raise ValueError("cc89 sampler settings differ from frozen control")
            trace = SamplerTrace.from_json((root / result.candidates[0].sampler_trace_artifact.path).read_text())
            callbacks = manifest["steps"] if settings["per_step_reinjection"] else 0
            if (trace.denoising_update_count != manifest["steps"] or trace.callback_update_count != callbacks
                    or not trace.device.startswith("cuda") or not trace.fallback_disabled
                    or trace.max_projection_error_angstrom != (0 if callbacks else None)
                    or request.seeds != (manifest["seed"],)):
                raise ValueError("cc89 CUDA trace differs from frozen protocol")
            if any(metric.value != 0 for metric in validation.metrics
                   if metric.name in {"fixed-heavy-atom-rmsd", "fixed-heavy-atom-max-displacement"}):
                raise ValueError("cc89 fixed source coordinates changed")
            rows.append({"case_id": case["case_id"], "arm": arm, "validation_passed": validation.passed,
                "failed_gates": validation.hard_gate_failures, "native_conditioning_fit": summary["native_conditioning_fit"],
                "candidate_sha256": result.candidates[0].coordinate_artifact.sha256})
    summaries = {}
    for arm in manifest["configurations"]:
        group = [row for row in rows if row["arm"] == arm]
        summaries[arm] = {"candidate_count": len(group), "accepted_count": sum(row["validation_passed"] for row in group),
            "failed_gate_counts": dict(Counter(gate for row in group for gate in row["failed_gates"])),
            "median_native_fixed_rmsd_angstrom": median(row["native_conditioning_fit"]["rmsd_angstrom"] for row in group)}
    report = {"manifest_sha256": digest, "cases": rows, "summaries": summaries,
        "independent_current_policy_revalidation": True, "external_scientific_review": False, "public_promotion": False}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summaries, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "outcomes", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    analyze(parser.parse_args())


if __name__ == "__main__":
    main()
