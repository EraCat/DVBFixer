#!/usr/bin/env python3
"""Verify full-source review copies and summarize all recheck/excluded cases."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from analyze_a100_failures import findings
from analyze_a100_relaxation import outside_records
from run_a100_relaxation import sha, verify_inventory

from dvbfixer.model.diffusion.contract import DiffusionRequest, RunnerResult
from dvbfixer.model.diffusion.validate import _load_structure, validate_runner_result


def summarize(args):
    manifest = json.loads(args.manifest.read_text())
    report = json.loads((args.results / "analysis.json").read_text())
    if not report["complete"] or report["manifest_sha256"] != sha(args.manifest):
        raise ValueError("intact report is incomplete or belongs to another input cohort")
    rows = {row["case_id"]: row for row in report["cases"]}
    if set(rows) != {case["case_id"] for case in manifest["cases"]}:
        raise ValueError("intact report drops or adds an admitted case")
    index = []
    safety_rejections = []
    for case in (*manifest["cases"], *manifest["excluded_cases"]):
        view = args.visual / case["visual_directory"]
        if case["status"] != "eligible":
            status = "unsupported"
            gates = "; ".join(case["reasons"])
            raw_pass = relaxed_pass = ""
        else:
            root = args.results / case["case_id"]
            marker = json.loads((root / "complete.json").read_text())
            if marker["protocol_sha256"] != report["protocol_sha256"]:
                raise ValueError("intact outcome protocol mismatch")
            verify_inventory(root, marker["artifacts"])
            verify_inventory(root, case["artifacts"])
            for name, source in (("01_before_gap.pdb", root / "reference.pdb"), ("02_gapped_input.pdb", root / "input/normalized.pdb")):
                if sha(view / name) != sha(source):
                    raise ValueError("intact visual input differs from the archived input")
            row = rows[case["case_id"]]
            status = row["status"]
            if status == "evaluated":
                for filename, visual_name in (("runner-result.json", "04_restored_raw.pdb"), ("relaxed-runner-result.json", "03_restored_relaxed.pdb")):
                    result = RunnerResult.from_json((root / filename).read_text())
                    artifact = result.candidates[0].coordinate_artifact
                    if sha(view / visual_name) != artifact.sha256 or sha(root / artifact.path) != artifact.sha256:
                        raise ValueError("intact visual result differs from the independently validated candidate")
                if not row["full_original_background_atom_records_preserved"]:
                    raise ValueError("intact background preservation proof is absent")
                raw_pass, relaxed_pass = row["raw_validation"]["passed"], row["relaxed_validation"]["passed"]
                gates = "; ".join(row["relaxed_validation"]["hard_gate_failures"])
                if not relaxed_pass:
                    request = DiffusionRequest.from_json((root / "request.json").read_text())
                    reference = _load_structure(root.resolve(), "reference.pdb", sha(root / "reference.pdb"))
                    original_findings = findings(reference, request)
                    detailed = row.get("relaxed_findings", [])
                    (view / "physical_findings.json").write_text(json.dumps({"after_restoration": detailed,
                        "before_test_gap": original_findings, "identical_preexisting_findings": [finding for finding in detailed if finding in original_findings],
                        "geometry_gates_changed": False}, indent=2, sort_keys=True) + "\n")
            else:
                raw_pass = relaxed_pass = False
                gates = row["failure_phase"] + ": " + row["message"]
                if (root / "runner-result.json").exists():
                    request = DiffusionRequest.from_json((root / "request.json").read_text())
                    raw = RunnerResult.from_json((root / "runner-result.json").read_text())
                    validation = validate_runner_result(request, raw, workspace=root.resolve())[0].summary
                    raw_pass = validation.passed
                    artifact = raw.candidates[0].coordinate_artifact
                    if sha(view / "04_restored_raw.pdb") != artifact.sha256:
                        raise ValueError("failed-refinement raw review copy changed")
                    generated = {(residue.chain, residue.residue_number, residue.insertion_code) for gap in request.gaps for residue in gap.generated_residues}
                    if outside_records((root / "reference.pdb").read_text(), generated) != outside_records((root / artifact.path).read_text(), generated):
                        raise ValueError("failed-refinement raw candidate changed the original background")
                log = root / (row["failure_phase"] + "-worker.log")
                if log.exists():
                    text = log.read_text(errors="replace")
                    (view / "failure.log").write_text(text)
                    if "ChiralityError" in text:
                        status = "rejected-chirality"
                        gates = "Final L-chirality invariant failed during local refinement; no relaxed structure published."
                        safety_rejections.append({"case_id": case["case_id"], "reason": "chirality-invariant", "original_status": row["status"]})
        index.append({"protein": case["source_id"], "case_id": case["case_id"], "length": case["length"], "seed": 7,
            "status": status, "raw_passed": raw_pass, "relaxed_passed": relaxed_pass, "reasons": gates,
            "directory": case["visual_directory"]})
        (view / "RESULT.md").write_text(f"# {case['case_id']}\n\nStatus: **{status}**\n\nRaw geometry: {raw_pass}\n\nRelaxed geometry: {relaxed_pass}\n\nReasons: {gates or 'none'}\n\n"
            "The CIF pair preserves every deposited background atom. Eligible PDB inputs preserve all observed protein residues/segments after explicit solvent/conformer preparation.\n")
    with (args.visual / "index.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(index[0]))
        writer.writeheader()
        writer.writerows(sorted(index, key=lambda row: (row["protein"], row["length"])))
    lines = ["# Intact-source recheck: completed results\n\n",
        "| Source | Attempted | Raw PASS | Relaxed PASS | Execution errors / safety rejections |\n|---|---:|---:|---:|---:|\n"]
    for source, summary in sorted(report["by_source"].items()):
        lines.append(f"| {source} | {summary['case_count']} | {summary['raw_accepted']} | {summary['relaxed_accepted']} | {summary['execution_errors']} |\n")
    lines.append(f"\nExplicitly unsupported original masks: {len(manifest['excluded_cases'])}. Full inputs are retained for viewing. See index.csv and each case's RESULT.md. No reference RMSD is used.\n")
    if safety_rejections:
        lines.append("\nChirality safety rejections: " + ", ".join(item["case_id"] for item in safety_rejections) + ". No relaxed structure is published for these cases; the raw structure and failure log remain available.\n")
    (args.visual / "RESULTS.md").write_text("".join(lines))
    (args.visual / "safety_rejections.json").write_text(json.dumps(safety_rejections, indent=2) + "\n")
    checksums = [f"{sha(path)}  {path.relative_to(args.visual).as_posix()}\n" for path in sorted(args.visual.rglob("*")) if path.is_file() and path.name != "CHECKSUMS.sha256"]
    (args.visual / "CHECKSUMS.sha256").write_text("".join(checksums))
    print(json.dumps({"admitted_cases_verified": len(rows), "all_input_cases_indexed": len(index),
        "report_sha256": sha(args.results / "analysis.json"), "summary": report["all"]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "results", "visual"):
        parser.add_argument("--" + name, type=Path, required=True)
    summarize(parser.parse_args())


if __name__ == "__main__":
    main()
