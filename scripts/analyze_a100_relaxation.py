#!/usr/bin/env python3
"""Revalidate paired local relaxation, retaining failures and raw-pass regressions."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median

from analyze_a100_calibration import equivalent_validation
from analyze_a100_failures import findings
from run_a100_relaxation import quality, sha, verify_inventory

from dvbfixer.model.diffusion.contract import DiffusionRequest, RunnerResult, SamplerTrace
from dvbfixer.model.diffusion.validate import _load_structure, validate_runner_result


def equivalent(first, second):
    if isinstance(first, dict):
        return isinstance(second, dict) and first.keys() == second.keys() and all(equivalent(value, second[key]) for key, value in first.items())
    if isinstance(first, (list, tuple)):
        return isinstance(second, (list, tuple)) and len(first) == len(second) and all(equivalent(a, b) for a, b in zip(first, second))
    if isinstance(first, float):
        return isinstance(second, (float, int)) and math.isclose(first, second, rel_tol=0, abs_tol=1e-12)
    return first == second


def outside_records(text, generated):
    return [line for line in text.splitlines() if line.startswith(("ATOM  ", "HETATM"))
            and (line[21], line[22:26].strip(), line[26].strip()) not in generated]


def summarize(rows):
    evaluated = [row for row in rows if row["status"] == "evaluated"]
    transitions = Counter((row["raw_passed"], row["relaxed_passed"]) for row in evaluated)
    deltas = [row["relaxed_quality"]["gap_backbone_rmsd_angstrom"] - row["raw_quality"]["gap_backbone_rmsd_angstrom"] for row in evaluated]
    gates = sorted({gate for row in evaluated for gate in (*row["raw_failed_gates"], *row["relaxed_failed_gates"])})
    return {"outcome_count": len(rows), "evaluated_count": len(evaluated), "execution_error_count": len(rows) - len(evaluated),
        "source_count": len({row["source_id"] for row in rows}), "raw_accepted": sum(row["raw_passed"] for row in rows),
        "relaxed_accepted": sum(row["relaxed_passed"] for row in rows),
        "execution_errors_among_raw_accepted": sum(row["raw_passed"] for row in rows if row["status"] != "evaluated"),
        "transition_scope": "evaluated pairs only; execution errors remain in total denominator",
        "fail_to_pass": transitions[False, True], "pass_to_fail": transitions[True, False],
        "pass_to_pass": transitions[True, True], "fail_to_fail": transitions[False, False],
        "median_paired_backbone_rmsd_change_angstrom": median(deltas) if deltas else None,
        "median_raw_backbone_rmsd_angstrom_evaluated_pairs": median(row["raw_quality"]["gap_backbone_rmsd_angstrom"] for row in evaluated) if evaluated else None,
        "median_relaxed_backbone_rmsd_angstrom_evaluated_pairs": median(row["relaxed_quality"]["gap_backbone_rmsd_angstrom"] for row in evaluated) if evaluated else None,
        "backbone_rmsd_increased_more_than_0_1_angstrom": sum(value > 0.1 for value in deltas),
        "median_refinement_wall_seconds": median(row["refinement_wall_time_seconds"] for row in evaluated) if evaluated else None,
        "gate_transitions_evaluated_only": {gate: {"before": sum(gate in row["raw_failed_gates"] for row in evaluated),
            "after": sum(gate in row["relaxed_failed_gates"] for row in evaluated),
            "resolved": sum(gate in row["raw_failed_gates"] and gate not in row["relaxed_failed_gates"] for row in evaluated),
            "introduced": sum(gate not in row["raw_failed_gates"] and gate in row["relaxed_failed_gates"] for row in evaluated)} for gate in gates}}


def analyze(args):
    manifest = json.loads(args.manifest.read_text())
    digest = sha(args.manifest)
    rows, pending = [], []
    for case in manifest["cases"]:
        root = (args.outcomes / case["case_id"] / case["arm"]).resolve()
        if not (root / "complete.json").exists() and args.allow_incomplete:
            pending.append(case)
            continue
        marker = json.loads((root / "complete.json").read_text())
        if marker["manifest_sha256"] != digest or marker["raw_complete_sha256"] != case["raw_complete_sha256"]:
            raise ValueError("relaxation completion marker differs from frozen protocol")
        verify_inventory(root, marker["artifacts"])
        if sha(root / "raw-complete.json") != case["raw_complete_sha256"]:
            raise ValueError("raw completion custody changed")
        raw_marker = json.loads((root / "raw-complete.json").read_text())
        if raw_marker["manifest_sha256"] != manifest["raw_manifest_sha256"]:
            raise ValueError("raw source cohort differs from freeze")
        verify_inventory(root, raw_marker["artifacts"])
        request = DiffusionRequest.from_json((root / "request.json").read_text())
        raw = RunnerResult.from_json((root / "runner-result.json").read_text())
        before = validate_runner_result(request, raw, workspace=root)[0].summary
        if before.passed != case["raw_passed"]:
            raise ValueError("raw acceptance differs from frozen baseline")
        outcome = json.loads((root / "relaxation.json").read_text())
        row = {**case, "status": outcome["status"], "raw_passed": before.passed, "relaxed_passed": False,
            "raw_failed_gates": before.hard_gate_failures}
        if outcome["status"] == "execution-error":
            row["execution_error"] = outcome
        elif outcome["status"] == "evaluated":
            result = RunnerResult.from_json((root / "relaxed-runner-result.json").read_text())
            after = validate_runner_result(request, result, workspace=root)[0].summary
            if not equivalent_validation(before, outcome["raw_validation"]) or not equivalent_validation(after, outcome["relaxed_validation"]):
                raise ValueError("relaxation validation differs from independent revalidation")
            generated = {(residue.chain, residue.residue_number, residue.insertion_code) for gap in request.gaps for residue in gap.generated_residues}
            raw_text = (root / raw.candidates[0].coordinate_artifact.path).read_text()
            refined_text = (root / result.candidates[0].coordinate_artifact.path).read_text()
            if outside_records(raw_text, generated) != outside_records(refined_text, generated):
                raise ValueError("relaxation changed fixed atom records")
            if any(metric.value != 0 for metric in after.metrics if metric.name in {"fixed-heavy-atom-rmsd", "fixed-heavy-atom-max-displacement", "detectable-d-ca"}):
                raise ValueError("relaxation violated fixed-coordinate or chirality invariant")
            if not result.candidates[0].postprocessing_failures:
                trace = SamplerTrace.from_json((root / result.candidates[0].sampler_trace_artifact.path).read_text())
                parameters = {option.name: option.value for option in trace.refinement_parameters}
                if trace.refinement_mode != "localized-openmm-boundary-refinement" or parameters["platform"] != manifest["protocol"]["platform"]:
                    raise ValueError("relaxation trace differs from frozen platform/mode")
            raw_quality = quality(root, request, raw, before)
            relaxed_quality = quality(root, request, result, after)
            if not equivalent(raw_quality, outcome["raw_quality"]) or not equivalent(relaxed_quality, outcome["relaxed_quality"]):
                raise ValueError("relaxation reference quality differs from independent scoring")
            row.update(relaxed_passed=after.passed, relaxed_failed_gates=after.hard_gate_failures,
                raw_quality=raw_quality, relaxed_quality=relaxed_quality,
                refinement_wall_time_seconds=outcome["refinement_wall_time_seconds"], postprocessing_failures=result.candidates[0].postprocessing_failures)
            if not after.passed:
                artifact = result.candidates[0].coordinate_artifact
                row["relaxed_findings"] = findings(_load_structure(root, artifact.path, artifact.sha256), request)
                row["relaxed_metrics"] = {metric.name: metric.value for metric in after.metrics}
        else:
            raise ValueError("unrecognized relaxation outcome status")
        rows.append(row)
    report = {"manifest_sha256": digest, "complete": not pending, "pending": pending, "cases": rows,
        "all": summarize(rows), "by_length": {str(length): summarize([row for row in rows if row["length"] == length]) for length in sorted({row["length"] for row in rows})},
        "by_source": {source: summarize([row for row in rows if row["source_id"] == source]) for source in sorted({row["source_id"] for row in rows})},
        "by_split": {split: summarize([row for row in rows if row["split"] == split]) for split in sorted({row["split"] for row in rows})},
        "by_arm": {arm: summarize([row for row in rows if row["arm"] == arm]) for arm in sorted({row["arm"] for row in rows})},
        "independent_current_policy_revalidation": True, "external_scientific_review": False, "public_promotion": False}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"complete": report["complete"], "pending_count": len(pending), "all": report["all"]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "outcomes", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--allow-incomplete", action="store_true")
    analyze(parser.parse_args())


if __name__ == "__main__":
    main()
