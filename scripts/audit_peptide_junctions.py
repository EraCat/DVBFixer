#!/usr/bin/env python3
"""Audit frozen A100 peptide junctions directly from PDB columns in angstroms.

Threshold sensitivity is descriptive only; this script never changes validation
policy or candidate acceptance. Reference geometry is an offline control.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from types import SimpleNamespace

from dvbfixer.model.diffusion.contract import ResidueIdentity
from dvbfixer.model.diffusion.validate import _cn_distance, _parse_pdb_text


def read_coordinates(text):
    """Independent fixed-column parser: no OpenMM units or topology inference."""
    atoms = {}
    order = {}
    for line in text.splitlines():
        if line[:6].strip() not in {"ATOM", "HETATM"}:
            continue
        residue = (line[21], line[22:26].strip(), line[26].strip())
        identity = (*residue, line[12:16].strip())
        xyz = tuple(float(line[start:start + 8]) for start in (30, 38, 46))
        if line[16].strip() or identity in atoms or not all(math.isfinite(value) for value in xyz):
            raise ValueError("ambiguous or non-finite PDB coordinate")
        atoms[identity] = xyz
        if residue not in order.setdefault(residue[0], []):
            order[residue[0]].append(residue)
    return atoms, order


def residue_key(record):
    return record["chain"], record["residue_number"], record["insertion_code"]


def cn_distance(atoms, left, right):
    return math.dist(atoms[(*left, "C")], atoms[(*right, "N")])


def verified_text(root, relative, digest):
    data = (root / relative).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"artifact digest mismatch: {root / relative}")
    return data.decode()


def audit(args):
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    rows = []
    for case in manifest["cases"]:
        for arm in case["arms"]:
            root = args.outcomes / case["case_id"] / arm
            marker = json.loads((root / "complete.json").read_text())
            if marker["manifest_sha256"] != digest:
                raise ValueError("outcome belongs to another manifest")
            request = json.loads(verified_text(root, "request.json", marker["artifacts"]["request.json"]))
            result = json.loads(verified_text(root, "runner-result.json", marker["artifacts"]["runner-result.json"]))
            outcome = json.loads(verified_text(root, "outcome.json", marker["artifacts"]["outcome.json"]))
            artifact = result["candidates"][0]["coordinate_artifact"]
            text = verified_text(root, artifact["path"], artifact["sha256"])
            candidate, _order = read_coordinates(text)
            reference, reference_order = read_coordinates(verified_text(root, "reference.pdb", case["artifacts"]["reference.pdb"]))
            production = SimpleNamespace(atoms=_parse_pdb_text(text)[0])
            distances = []
            internal = []
            for gap_index, gap in enumerate(request["gaps"]):
                generated = [residue_key(record) for record in gap["generated_residues"]]
                for left, right in zip(generated, generated[1:]):
                    order = reference_order[left[0]]
                    if left[0] != right[0] or order.index(right) != order.index(left) + 1:
                        raise ValueError("internal gap pair is not neighboring same-chain reference residues")
                    internal.append({"left": left, "right": right, "candidate_cn_angstrom": cn_distance(candidate, left, right),
                        "reference_cn_angstrom": cn_distance(reference, left, right)})
                pairs = []
                if gap["left_anchor"] is not None:
                    pairs.append(("left", residue_key(gap["left_anchor"]), generated[0]))
                if gap["right_anchor"] is not None:
                    pairs.append(("right", generated[-1], residue_key(gap["right_anchor"])))
                for side, left, right in pairs:
                    order = reference_order[left[0]]
                    if left[0] != right[0] or order.index(right) != order.index(left) + 1:
                        raise ValueError("junction is not neighboring same-chain reference residues")
                    distance = cn_distance(candidate, left, right)
                    actual = _cn_distance(production, ResidueIdentity(*left), ResidueIdentity(*right))
                    if actual is None or not math.isclose(actual, distance, rel_tol=0, abs_tol=1e-12):
                        raise ValueError("production C-N measurement differs from independent PDB calculation")
                    distances.append({"gap": gap_index, "side": side, "left": left, "right": right,
                        "candidate_cn_angstrom": distance, "reference_cn_angstrom": cn_distance(reference, left, right)})
            metrics = {metric["name"]: metric["value"] for metric in outcome["validation"]["metrics"]}
            values = [row["candidate_cn_angstrom"] for row in distances]
            if not all(math.isclose(metrics[name], value, rel_tol=0, abs_tol=1e-12) for name, value in (
                ("junction-cn-distance-min", min(values)), ("junction-cn-distance-max", max(values)))):
                raise ValueError("recorded junction metrics differ from independent measurement")
            failed = any(not 1.20 <= value <= 1.45 for value in values)
            gates = outcome["validation"]["hard_gate_failures"]
            if failed != ("junction-peptide-connectivity" in gates):
                raise ValueError("recorded junction gate differs from independent decision")
            internal_break = any(row["candidate_cn_angstrom"] > 1.80 for row in internal)
            if internal_break != ("generated-backbone-break" in gates):
                raise ValueError("recorded internal break gate differs from independent decision")
            if not math.isclose(metrics["generated-region-cn-distance-max"], max(values + [row["candidate_cn_angstrom"] for row in internal]), rel_tol=0, abs_tol=1e-12):
                raise ValueError("recorded generated backbone maximum differs from independent measurement")
            rows.append({"case_id": case["case_id"], "source_id": case["source_id"], "length": case["length"],
                "arm": arm, "junctions": distances, "internal_bonds": internal, "junction_failed": failed, "failed_gates": gates})
    junctions = [junction for row in rows for junction in row["junctions"]]
    internal_bonds = [bond for row in rows for bond in row["internal_bonds"]]
    reference_values = [row["reference_cn_angstrom"] for row in junctions]
    failed_rows = [row for row in rows if row["junction_failed"]]
    def maximum_violation(row):
        return max(max(1.20 - junction["candidate_cn_angstrom"], junction["candidate_cn_angstrom"] - 1.45, 0)
                   for junction in row["junctions"])

    sensitivity = {}
    for maximum in (1.45, 1.50, 1.60, 1.80, 2.00):
        passing = [row for row in rows if all(1.20 <= junction["candidate_cn_angstrom"] <= maximum for junction in row["junctions"])]
        sensitivity[str(maximum)] = {"junction_passing_outcomes": len(passing),
            "would_pass_all_other_existing_gates": sum(not (set(row["failed_gates"]) - {"junction-peptide-connectivity"}) for row in passing)}
    report = {"manifest_sha256": digest, "outcome_count": len(rows), "junction_count": len(junctions),
        "junction_failing_outcomes": len(failed_rows), "production_measurement_and_decision_mismatches": 0,
        "failed_outcomes_by_length": dict(Counter(row["length"] for row in failed_rows)),
        "junction_only_failing_outcomes": sum(set(row["failed_gates"]) == {"junction-peptide-connectivity"} for row in rows),
        "reference_cn_min_angstrom": min(reference_values), "reference_cn_max_angstrom": max(reference_values),
        "reference_cn_median_angstrom": median(reference_values),
        "reference_out_of_current_range_junctions": sum(not 1.20 <= value <= 1.45 for value in reference_values),
        "candidate_cn_below_1_20": sum(row["candidate_cn_angstrom"] < 1.20 for row in junctions),
        "candidate_cn_above_1_45": sum(row["candidate_cn_angstrom"] > 1.45 for row in junctions),
        "candidate_cn_above_1_80": sum(row["candidate_cn_angstrom"] > 1.80 for row in junctions),
        "failing_outcomes_with_any_cn_above_1_80": sum(any(junction["candidate_cn_angstrom"] > 1.80 for junction in row["junctions"]) for row in failed_rows),
        "failing_outcomes_with_any_cn_below_1_20": sum(any(junction["candidate_cn_angstrom"] < 1.20 for junction in row["junctions"]) for row in failed_rows),
        "failing_outcomes_with_max_threshold_exceedance_at_most_0_005_angstrom": sum(maximum_violation(row) <= 0.005 for row in failed_rows),
        "failing_outcomes_with_max_threshold_exceedance_at_most_0_01_angstrom": sum(maximum_violation(row) <= 0.01 for row in failed_rows),
        "internal_cn_count": len(internal_bonds),
        "internal_candidate_cn_below_1_20": sum(bond["candidate_cn_angstrom"] < 1.20 for bond in internal_bonds),
        "internal_candidate_cn_above_1_45": sum(bond["candidate_cn_angstrom"] > 1.45 for bond in internal_bonds),
        "internal_candidate_cn_above_1_80": sum(bond["candidate_cn_angstrom"] > 1.80 for bond in internal_bonds),
        "internal_reference_out_of_junction_range": sum(not 1.20 <= bond["reference_cn_angstrom"] <= 1.45 for bond in internal_bonds),
        "sensitivity_only_no_policy_change": sensitivity, "outcomes": rows}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "outcomes"}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "outcomes", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    audit(parser.parse_args())


if __name__ == "__main__":
    main()
