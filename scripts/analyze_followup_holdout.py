#!/usr/bin/env python3
"""Audit selected rigid holdout with full runner traces and local defect details."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import median

from analyze_a100_calibration import equivalent_validation
from analyze_a100_failures import findings
from analyze_a100_relaxation import equivalent
from run_a100_relaxation import quality, sha, verify_inventory

from dvbfixer.model.diffusion.contract import DiffusionRequest, RunnerResult
from dvbfixer.model.diffusion.validate import _load_structure, validate_runner_result


def summarize(rows):
    accepted = [row for row in rows if row["selected_passed"]]
    values = [row["selected_quality"]["gap_backbone_rmsd_angstrom"] for row in accepted]
    return {"case_count": len(rows), "source_count": len({row["source_id"] for row in rows}),
        "raw_accepted": sum(row["raw_passed"] for row in rows), "selected_accepted": len(accepted),
        "fail_to_pass": sum(not row["raw_passed"] and row["selected_passed"] for row in rows),
        "pass_to_fail": sum(row["raw_passed"] and not row["selected_passed"] for row in rows),
        "raw_gate_counts": dict(Counter(gate for row in rows for gate in row["raw_gates"])),
        "selected_gate_counts": dict(Counter(gate for row in rows for gate in row["selected_gates"])),
        "median_raw_backbone_rmsd_angstrom_all": median(row["raw_quality"]["gap_backbone_rmsd_angstrom"] for row in rows),
        "median_selected_backbone_rmsd_angstrom_all": median(row["selected_quality"]["gap_backbone_rmsd_angstrom"] for row in rows),
        "accepted_backbone_rmsd_bins_angstrom": {"<=1": sum(value <= 1 for value in values),
            "(1,2]": sum(1 < value <= 2 for value in values), "(2,4]": sum(2 < value <= 4 for value in values), ">4": sum(value > 4 for value in values)}}


def audit(args):
    original = json.loads((args.outcomes / "analysis.json").read_text())
    if not original["complete"] or original["selected_protocol"] != "rigid" or original["execution_errors"]:
        raise ValueError("full-trace rigid audit requires completed evaluated rigid holdout")
    rows = []
    for case in original["cases"]:
        root = (args.outcomes / "selected" / case["case_id"] / case["arm"]).resolve()
        marker = json.loads((root / "complete.json").read_text())
        if marker["protocol_sha256"] != original["protocol_sha256"] or marker["raw_complete_sha256"] != sha(root / "raw-complete.json"):
            raise ValueError("holdout custody differs from protocol")
        verify_inventory(root, marker["artifacts"])
        verify_inventory(root, json.loads((root / "raw-complete.json").read_text())["artifacts"])
        request = DiffusionRequest.from_json((root / "request.json").read_text())
        raw = RunnerResult.from_json((root / "runner-result.json").read_text())
        selected = RunnerResult.from_json((root / "selected-runner-result.json").read_text())
        before = validate_runner_result(request, raw, workspace=root)[0].summary
        after = validate_runner_result(request, selected, workspace=root)[0].summary
        if not equivalent_validation(before, case["raw"]["validation"]) or not equivalent_validation(after, case["selected"]["validation"]):
            raise ValueError("full runner-trace validation differs from direct holdout validation")
        if any(metric.value != 0 for metric in after.metrics if metric.name in {"fixed-heavy-atom-rmsd", "fixed-heavy-atom-max-displacement", "detectable-d-ca"}):
            raise ValueError("selected holdout violates exact fixed/chirality invariants")
        raw_quality, selected_quality = quality(root, request, raw, before), quality(root, request, selected, after)
        for current, recorded in ((raw_quality, case["raw"]["quality"]), (selected_quality, case["selected"]["quality"])):
            if not equivalent({key: value for key, value in current.items() if key != "candidate_id"},
                              {key: value for key, value in recorded.items() if key != "candidate_id"}):
                raise ValueError("independent holdout reference quality differs")
        artifact = selected.candidates[0].coordinate_artifact
        details = findings(_load_structure(root, artifact.path, artifact.sha256), request) if not after.passed else []
        rows.append({"case_id": case["case_id"], "source_id": case["source_id"], "length": case["length"],
            "raw_passed": before.passed, "selected_passed": after.passed, "raw_gates": before.hard_gate_failures,
            "selected_gates": after.hard_gate_failures, "raw_quality": raw_quality, "selected_quality": selected_quality,
            "selected_metrics": {metric.name: metric.value for metric in after.metrics}, "findings": details})
    result = {"complete": True, "holdout_analysis_sha256": sha(args.outcomes / "analysis.json"),
        "all": summarize(rows), "by_length": {str(length): summarize([row for row in rows if row["length"] == length]) for length in sorted({row["length"] for row in rows})},
        "by_source": {source: summarize([row for row in rows if row["source_id"] == source]) for source in sorted({row["source_id"] for row in rows})},
        "cases": rows, "full_runner_trace_revalidation": True, "public_promotion": False}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["all"], indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    audit(parser.parse_args())


if __name__ == "__main__":
    main()
