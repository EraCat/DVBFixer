#!/usr/bin/env python3
"""Compare independently audited input-correction results with the original run."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import median

from run_cc89_known_sequence_holdout import sha


def summarize(rows):
    paired = [row for row in rows if row["original_backbone_rmsd_angstrom"] is not None]
    deltas = [row["backbone_rmsd_delta_angstrom"] for row in paired]
    return {
        "count": len(rows),
        "original_accepted": sum(row["original_passed"] for row in rows),
        "corrected_accepted": sum(row["corrected_passed"] for row in rows),
        "transitions": dict(sorted(Counter(row["transition"] for row in rows).items())),
        "corrected_detectable_d_ca_count": sum(row["corrected_d_ca_count"] for row in rows),
        "corrected_fixed_max_displacement_angstrom": max(
            row["corrected_fixed_max_displacement_angstrom"] for row in rows
        ),
        "paired_accuracy_count": len(paired),
        "original_accuracy_unavailable": len(rows) - len(paired),
        "median_original_backbone_rmsd_angstrom": median(
            row["original_backbone_rmsd_angstrom"] for row in paired
        ) if paired else None,
        "median_corrected_backbone_rmsd_angstrom": median(
            row["corrected_backbone_rmsd_angstrom"] for row in rows
        ),
        "median_paired_delta_angstrom": median(deltas) if deltas else None,
        "rmsd_increased_count": sum(delta > 0 for delta in deltas),
        "rmsd_increased_over_1_angstrom": sum(delta > 1 for delta in deltas),
        "corrected_rmsd_over_4_angstrom": sum(
            row["corrected_backbone_rmsd_angstrom"] > 4 for row in rows
        ),
    }


def compare(args):
    if args.output.exists() or args.markdown.exists():
        raise ValueError("paired comparison destinations must be new")
    original = json.loads(args.original.read_text())
    if not original["complete"]:
        raise ValueError("original audit is incomplete")
    indexes = {
        stage: {(row["case_id"], row["seed"]): row for row in original["stages"][stage]}
        for stage in ("raw", "refine")
    }
    rows, seen = [], set()
    for path in args.corrected:
        corrected = json.loads(path.read_text())
        if not corrected["complete"]:
            raise ValueError("corrected audit is incomplete")
        for row in corrected["rows"]:
            key = (row["stage"], row["case_id"], row["seed"])
            if key in seen or not row["independently_revalidated"]:
                raise ValueError("duplicate or unaudited corrected result")
            seen.add(key)
            old = indexes[row["stage"]][(row["case_id"], row["seed"])]
            before = bool((old.get("validation") or {}).get("passed", False))
            after = row["passed"]
            old_rmsd = (old.get("quality") or {}).get("gap_backbone_rmsd_angstrom")
            new_rmsd = row["backbone_rmsd_angstrom"]
            rows.append({
                "case_id": row["case_id"], "seed": row["seed"], "stage": row["stage"],
                "stratum": old["stratum"], "length": row["length"],
                "original_status": old["status"], "original_passed": before,
                "corrected_passed": after,
                "transition": f"{'PASS' if before else 'FAIL'}->{'PASS' if after else 'FAIL'}",
                "original_backbone_rmsd_angstrom": old_rmsd,
                "corrected_backbone_rmsd_angstrom": new_rmsd,
                "backbone_rmsd_delta_angstrom": None if old_rmsd is None else new_rmsd - old_rmsd,
                "corrected_failed_gates": row["failed_gates"],
                "corrected_d_ca_count": row["d_ca_count"],
                "corrected_fixed_max_displacement_angstrom": row["fixed_max_displacement_angstrom"],
            })
    summaries = {
        stage: {
            stratum: summarize([row for row in rows if row["stage"] == stage and row["stratum"] == stratum])
            for stratum in sorted({row["stratum"] for row in rows})
        }
        for stage in ("raw", "refine")
    }
    report = {
        "original_sha256": sha(args.original),
        "corrected_sha256": {path.name: sha(path) for path in args.corrected},
        "producer_sha256": sha(Path(__file__).resolve()),
        "interpretation": "Same-source diagnostic recheck; geometry PASS is not reference accuracy or independent acceptance.",
        "summaries": summaries, "rows": rows, "public_promotion": False,
    }
    text = ["# cc89 corrected-input paired comparison\n\n", report["interpretation"] + "\n\n",
        "## Primary outcome: geometry and source preservation\n\n",
        "Acceptance checks generated/junction geometry, chirality, severe overlaps, and preservation of the observed structure. Reference RMSD is descriptive and is not an acceptance gate. MODELLER is a comparator, not a structural ground truth.\n\n",
        "| Stage | Stratum | Original PASS | Corrected PASS | PASS→FAIL | FAIL→PASS | Corrected D-Cα | Fixed max displacement Å |\n",
        "|---|---|---:|---:|---:|---:|---:|---:|\n"]
    for stage, strata in summaries.items():
        for stratum, summary in strata.items():
            text.append(f"| {stage} | {stratum} | {summary['original_accepted']}/{summary['count']} | {summary['corrected_accepted']}/{summary['count']} | {summary['transitions'].get('PASS->FAIL', 0)} | {summary['transitions'].get('FAIL->PASS', 0)} | {summary['corrected_detectable_d_ca_count']:g} | {summary['corrected_fixed_max_displacement_angstrom']:g} |\n")
    text.extend(["\n## Secondary outcome: reference-conformation agreement\n\n",
        "Positive RMSD deltas mean worse agreement with the withheld reference. Missing original accuracy remains missing; guarded failures stay in the acceptance denominator. No seed is selected by reference accuracy.\n\n",
        "| Stage | Stratum | Original PASS | Corrected PASS | PASS→FAIL | FAIL→PASS | Paired accuracy n | Original median Å¹ | Corrected median Å² | Median paired Δ Å | Δ >1 Å |\n",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"])
    for stage, strata in summaries.items():
        for stratum, summary in strata.items():
            text.append(f"| {stage} | {stratum} | {summary['original_accepted']}/{summary['count']} | {summary['corrected_accepted']}/{summary['count']} | {summary['transitions'].get('PASS->FAIL', 0)} | {summary['transitions'].get('FAIL->PASS', 0)} | {summary['paired_accuracy_count']} | {summary['median_original_backbone_rmsd_angstrom']:.3f} | {summary['median_corrected_backbone_rmsd_angstrom']:.3f} | {summary['median_paired_delta_angstrom']:.3f} | {summary['rmsd_increased_over_1_angstrom']} |\n")
    text.append("\n¹ Original median uses available paired accuracy only. ² Corrected median uses all corrected results. Median paired delta is calculated per matching case/seed, not by subtracting the two medians.\n\n## Refined acceptance losses or reference RMSD increases above 1 Å\n\nAn RMSD increase alone is not a failed reconstruction; it can reflect a different geometrically valid conformation.\n\n")
    text.append("| Case | Seed | Transition | Original RMSD Å | Corrected RMSD Å | Δ Å |\n|---|---:|---|---:|---:|---:|\n")
    for row in rows:
        delta = row["backbone_rmsd_delta_angstrom"]
        if row["stage"] == "refine" and (row["transition"] == "PASS->FAIL" or (delta is not None and delta > 1)):
            before = "unavailable" if delta is None else f"{row['original_backbone_rmsd_angstrom']:.3f}"
            change = "unavailable" if delta is None else f"{delta:.3f}"
            text.append(f"| {row['case_id']} | {row['seed']} | {row['transition']} | {before} | {row['corrected_backbone_rmsd_angstrom']:.3f} | {change} |\n")
    text.append(f"\nMachine-readable evidence: `{args.output.name}`. Original and corrected audit SHA-256 digests are recorded in that report.\n")
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    args.markdown.write_text("".join(text))
    print(json.dumps(summaries, indent=2, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--corrected", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    compare(parser.parse_args())


if __name__ == "__main__":
    main()
