#!/usr/bin/env python3
"""Publish portable holdout evidence, without private worker argv or host paths."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_cc89_known_sequence_holdout import sha

ROW_FIELDS = {
    "case_id", "source_id", "seed", "length", "stratum", "status", "validation", "quality",
    "coordinate_alignment", "quality_fixed_atom_scope", "missing_fixed_atom_identities", "candidate",
    "comparator_geometry_passed", "comparator_geometry_failures", "publication_status", "coordinate_origin",
    "postprocessing_failures", "exception_type", "error_phase", "stage_wall_seconds", "resources",
    "independently_revalidated",
}


def number(value):
    return "undefined" if value is None else f"{value:.3f}"


def summarize(args):
    if args.report.exists() or args.markdown.exists():
        raise ValueError("portable report destinations must be new")
    full = json.loads(args.analysis.read_text())
    if not full["complete"] or full["pending"]:
        raise ValueError("portable results require a completed independently revalidated study")
    report = {key: value for key, value in full.items() if key != "stages"}
    report["stages"] = {stage: [{key: value for key, value in row.items() if key in ROW_FIELDS} for row in rows]
                        for stage, rows in full["stages"].items()}
    report.update(full_analysis_sha256=sha(args.analysis), portable_producer_sha256=sha(Path(__file__).resolve()),
        private_diagnostics="original bounded worker logs and error argv retained only in ignored local archives")
    with args.report.open("x") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    text = ["# Known-sequence cc89 / Homology holdout: completed results\n\n",
        "All targets are unchanged observed sequences from public X-ray structures. Known coordinates were removed before template construction and model conditioning. Withheld reference files were absent from cc89 sampling and refinement workspaces.\n\n",
        "30 masks on 13 deposited structures; cc89 seeds 7 and 19. Whole observed protein models and partners are retained. Terminal OXT is explicitly preserved-only outside atom37 conditioning.\n\n",
        "## Overall outcomes\n\n",
        "| Stage | Planned | Evaluated | Strict PASS | Operational/guarded statuses | Median backbone RMSD, all available (Å) |\n",
        "|---|---:|---:|---:|---|---:|\n"]
    for stage, summary in full["summaries"].items():
        failures = {key: value for key, value in summary["statuses"].items() if key != "evaluated"}
        text.append(f"| {stage} | {summary['planned_outcomes']} | {summary['evaluated']} | {summary['strict_accepted']} | {json.dumps(failures, sort_keys=True)} | {number(summary['median_backbone_rmsd_all_available_angstrom'])} |\n")
    model = full["summaries"]["modeller"]
    text.append(f"\nMODELLER's strict source-preservation status is separate from reconstruction geometry: **{model['comparator_geometry_accepted']}/{model['planned_outcomes']}** pass the existing unconstrained-comparator geometry policy. It is one automodel without loop refinement, versus two cc89 samples plus local refinement; this is a descriptive workflow comparison, not a confirmatory noninferiority or speed benchmark. MODELLER accuracy is rigidly aligned on common observed backbone atoms only.\n")
    text.extend(["\n## cc89 postprocessing by stratum\n\n",
        "| Stratum | Planned | Strict PASS | Evaluated | Median RMSD, all available (Å) | Median RMSD, accepted (Å) | Maximum RMSD, accepted (Å) |\n",
        "|---|---:|---:|---:|---:|---:|---:|\n"])
    for stratum, stages in full["by_stratum"].items():
        row = stages["refine"]
        text.append(f"| {stratum} | {row['planned_outcomes']} | {row['strict_accepted']} | {row['evaluated']} | {number(row['median_backbone_rmsd_all_available_angstrom'])} | {number(row['median_backbone_rmsd_strict_accepted_angstrom'])} | {number(row['maximum_backbone_rmsd_strict_accepted_angstrom'])} |\n")
    text.extend(["\n## cc89 postprocessing by gap length\n\n",
        "| Length | Planned | Strict PASS | Median RMSD, all available (Å) |\n",
        "|---|---:|---:|---:|\n"])
    for length, stages in full["by_length"].items():
        row = stages["refine"]
        text.append(f"| {length} | {row['planned_outcomes']} | {row['strict_accepted']} | {number(row['median_backbone_rmsd_all_available_angstrom'])} |\n")
    text.extend(["\n## cc89 postprocessing by source\n\n",
        "| PDB | Planned | Strict PASS | Statuses | Median RMSD, all available (Å) |\n",
        "|---|---:|---:|---|---:|\n"])
    for source, stages in full["by_source"].items():
        row = stages["refine"]
        text.append(f"| {source} | {row['planned_outcomes']} | {row['strict_accepted']} | {json.dumps(row['statuses'], sort_keys=True)} | {number(row['median_backbone_rmsd_all_available_angstrom'])} |\n")
    text.extend(["\n## Public Homology / Protenix controls\n\n",
        "| Case | Status | Strict PASS | Backbone RMSD (Å) |\n",
        "|---|---|---|---:|\n"])
    for row in full["stages"]["protenix"]:
        text.append(f"| {row['case_id']} | {row['status']} | {row.get('validation', {}).get('passed', False)} | {number((row.get('quality') or {}).get('gap_backbone_rmsd_angstrom'))} |\n")
    text.append("\nThe study is a method holdout for the cc89 repair. The general sources were previously used in Protenix research; the two historical antibody structures may overlap pretraining. Two seeds are not independent source structures. Raw-retained inspection candidates remain failed postprocessing outcomes, not successful refinements. Guarded failures without a scored candidate remain in the denominator. No public capability is promoted by this report.\n")
    text.append("\nAn external 600-second shell limit interrupted one unarchived refinement stage (general-9v77-gap10, seed19). It was resumed from the exact immutable raw archive under the unchanged 1,800-second per-job bound. Raw generation was not repeated and no terminal archived result was replaced.\n")
    text.append(f"\nPortable report: `{args.report.name}`, SHA-256 `{sha(args.report)}`. Full read-only revalidation report SHA-256: `{sha(args.analysis)}`.\n")
    with args.markdown.open("x") as stream:
        stream.write("".join(text))
    print(json.dumps({"portable_report_sha256": sha(args.report), "markdown_sha256": sha(args.markdown)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("analysis", "report", "markdown"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    summarize(args)


if __name__ == "__main__":
    main()
