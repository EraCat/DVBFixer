#!/usr/bin/env python3
"""Audit final holdout sequence overlap, including development sequences with X."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_relaxation_holdout import sequence_identity
from run_a100_relaxation import sha


def audit(args):
    development = json.loads(args.development.read_text())
    sources = json.loads(args.sources.read_text())
    cohort = json.loads(args.cohort.read_text())
    selected = {case["source_id"] for case in cohort["cases"]}
    new = {case["pdb_id"]: case for case in sources["cases"] if case["pdb_id"] in selected}
    old_ids = {case["pdb_id"] for case in development["cases"]}
    if selected & old_ids:
        raise ValueError("holdout contains development entry IDs")
    records = []
    for identifier, case in new.items():
        comparisons = []
        for old in development["cases"]:
            sequence = old.get("sequence")
            if not sequence:
                continue
            unknown = sum(char not in "ACDEFGHIKLMNPQRSTVWY" for char in sequence)
            normalized = "".join(char if char in "ACDEFGHIKLMNPQRSTVWY" else "X" for char in sequence)
            identity = sequence_identity(case["sequence"], normalized)
            # Sensitivity to all unknown development residues matching on the
            # computed alignment; not an upper bound over every alignment.
            sensitivity = identity + unknown / min(len(sequence), len(case["sequence"]))
            comparisons.append({"development_id": old["pdb_id"], "identity": identity,
                "development_unknown_residue_count": unknown, "fixed_alignment_unknown_match_sensitivity": sensitivity})
        records.append({"holdout_id": identifier, "comparisons": comparisons,
            "maximum_identity": max(row["identity"] for row in comparisons),
            "maximum_unknown_sensitivity": max(row["fixed_alignment_unknown_match_sensitivity"] for row in comparisons)})
    within = [{"first": first, "second": second, "identity": sequence_identity(new[first]["sequence"], new[second]["sequence"])}
              for first in sorted(new) for second in sorted(new) if first < second]
    report = {"development_sha256": sha(args.development), "sources_sha256": sha(args.sources), "cohort_sha256": sha(args.cohort),
        "distinct_entry_ids": True, "holdout_source_count": len(selected), "records": records, "within_holdout": within,
        "all_development_overlap_checks_le_0_30": all(row["maximum_unknown_sensitivity"] <= 0.30 for row in records),
        "all_within_holdout_identity_le_0_30": all(row["identity"] <= 0.30 for row in within),
        "training_membership_independently_attested": False, "cohort_changed": False}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key not in {"records", "within_holdout"}}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("development", "sources", "cohort", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    audit(parser.parse_args())


if __name__ == "__main__":
    main()
