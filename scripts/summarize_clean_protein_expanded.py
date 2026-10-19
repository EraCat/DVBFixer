#!/usr/bin/env python3
"""Export verified clean-cohort results, source exclusions and annotation strata."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from run_a100_relaxation import sha
from summarize_intact_recheck import summarize as verify_and_export


def annotation_class(counts):
    if counts["helix"] and counts["sheet"]:
        return "helix-and-sheet-overlap"
    if counts["helix"]:
        return "helix-overlap"
    if counts["sheet"]:
        return "sheet-overlap"
    return "unannotated-not-assumed-loop"


def summarize(args):
    verify_and_export(args)
    manifest = json.loads(args.manifest.read_text())
    report = json.loads((args.results / "analysis.json").read_text())
    with (args.visual / "index.csv").open(encoding="utf-8-sig", newline="") as stream:
        index_rows = {row["case_id"]: row for row in csv.DictReader(stream)}
    raw_accepted_all_generated = sum(index_rows[row["case_id"]]["raw_passed"] == "True" for row in report["cases"])
    generation_completed = sum((args.results / row["case_id"] / "runner-result.json").exists() for row in report["cases"])
    cases = {case["case_id"]: case for case in manifest["cases"]}
    annotations = defaultdict(list)
    for row in report["cases"]:
        annotations[annotation_class(cases[row["case_id"]]["secondary_structure"])].append(row)
    strata = {}
    for name, rows in sorted(annotations.items()):
        strata[name] = {"attempted": len(rows), "source_count": len({row["source_id"] for row in rows}),
            "evaluated": sum(row["status"] == "evaluated" for row in rows),
            "relaxed_accepted": sum(row.get("relaxed_validation", {}).get("passed", False) for row in rows),
            "failures_remain_in_denominator": True}
    excluded_sources = [row for row in manifest["source_pool_screening"] if row["status"] != "selected"]
    source_counts = Counter(reason for row in excluded_sources for reason in {reason.split(":", 1)[0] for reason in row.get("reasons", [])})
    with (args.visual / "source_screening.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("pdb_id", "status", "reasons"))
        for row in manifest["source_pool_screening"]:
            writer.writerow((row["pdb_id"], row["status"], "; ".join(row.get("reasons", []))))
    result = {"complete": True, "run_analysis_sha256": sha(args.results / "analysis.json"), "cohort_sha256": sha(args.manifest),
        "producer_sha256": sha(Path(__file__).resolve()), "evaluated_pair_summary": report["all"],
        "generation_completed": generation_completed, "raw_accepted_all_generated": raw_accepted_all_generated,
        "selected_sources": len(manifest["screening"]), "screened_pool": len(manifest["source_pool_screening"]),
        "source_exclusion_counts_overlapping_sources_not_residue_findings": dict(source_counts),
        "source_native_window_exclusions": manifest["excluded_cases"], "by_deposited_annotation": strata,
        "interpretation": "annotation overlap is descriptive; absent helix/sheet annotation is not evidence of a loop; full deposited model/ASU, not assembly expansion",
        "reference_rmsd_used": False, "public_promotion": False}
    (args.results / "clean-cohort-audit.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (args.visual / "clean-cohort-audit.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    text = ["# Clean protein expanded cohort: completed results\n\n",
        "Every selected source is canonical-protein-only, coordinate-complete, without native gaps or missing heavy atoms. Waters are removed explicitly for solvent-free PDB preparation. No ligand/cofactor is stripped from an otherwise incompatible entry.\n\n",
        "Full target and every protein partner are represented in the actual model features, <=512 residues. Source coordinates outside the declared mask remain unchanged. This is the full deposited model/ASU, not a generated biological assembly.\n\n",
        f"Screened pool: {len(manifest['source_pool_screening'])}; selected sources: {len(manifest['screening'])}; planned masks: {len(manifest['cases']) + len(manifest['excluded_cases'])}; source-native quality exclusions before inference: {len(manifest['excluded_cases'])}.\n\n",
        f"Attempted: {report['all']['case_count']}; generated: {generation_completed}; raw geometry accepted: {raw_accepted_all_generated}; refined accepted: {report['all']['relaxed_accepted']}; execution/safety failures: {report['all']['execution_errors']}. Failed attempts remain in the denominator. Raw counts include generated candidates whose later refinement failed.\n\n",
        "| Deposited annotation overlap | Attempted | Sources | Relaxed PASS |\n|---|---:|---:|---:|\n"]
    for name, values in strata.items():
        text.append(f"| {name} | {values['attempted']} | {values['source_count']} | {values['relaxed_accepted']} |\n")
    text.append("\n| Gap length | Attempted | Refined PASS | Execution/safety failures |\n|---|---:|---:|---:|\n")
    for length, values in sorted(report["by_length"].items(), key=lambda item: int(item[0])):
        text.append(f"| {length} | {values['case_count']} | {values['relaxed_accepted']} | {values['execution_errors']} |\n")
    text.append("\nSee RESULTS.md, index.csv, source_screening.csv and per-case case.json / RESULT.md. No reference RMSD ranking or acceptance criterion is used.\n")
    (args.visual / "CLEAN_RESULTS.md").write_text("".join(text))
    if args.research_output:
        args.research_output.write_text("".join(text) + f"\nRun report SHA-256: `{sha(args.results / 'analysis.json')}`.\n")
    checksums = [f"{sha(path)}  {path.relative_to(args.visual).as_posix()}\n" for path in sorted(args.visual.rglob("*")) if path.is_file() and path.name != "CHECKSUMS.sha256"]
    (args.visual / "CHECKSUMS.sha256").write_text("".join(checksums))
    print(json.dumps({"selected_sources": len(manifest["screening"]), "source_native_window_exclusions": len(manifest["excluded_cases"]),
        "by_deposited_annotation": strata, "audit_sha256": sha(args.results / "clean-cohort-audit.json")}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "results", "visual"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--research-output", type=Path)
    summarize(parser.parse_args())


if __name__ == "__main__":
    main()
