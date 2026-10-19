#!/usr/bin/env python3
"""Separate geometric acceptance from withheld-coordinate accuracy."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import median

import numpy as np

from dvbfixer.model.diffusion.benchmark import load_pdb_coordinates
from dvbfixer.model.diffusion.contract import ArtifactReference, DiffusionRequest, RunnerResult
from dvbfixer.model.diffusion.geometry import weighted_kabsch


def fitted_backbone_rmsd(root):
    root = root.resolve()
    marker = json.loads((root / "complete.json").read_text())
    for relative in ("request.json", "relaxed-runner-result.json", "reference.pdb"):
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != marker["artifacts"][relative]:
            raise ValueError("paired accuracy audit input differs from archived inventory")
    request = DiffusionRequest.from_json((root / "request.json").read_text())
    result = RunnerResult.from_json((root / "relaxed-runner-result.json").read_text())
    reference_path = root / "reference.pdb"
    reference = load_pdb_coordinates(root, ArtifactReference("reference.pdb", hashlib.sha256(reference_path.read_bytes()).hexdigest()))
    candidate = load_pdb_coordinates(root, result.candidates[0].coordinate_artifact)
    atoms = [atom for atom in request.generated_atoms if atom.atom_name in {"N", "CA", "C", "O"}]
    mobile = np.asarray([candidate[atom] for atom in atoms])
    target = np.asarray([reference[atom] for atom in atoms])
    aligned = weighted_kabsch(mobile, target).apply(mobile)
    return float(np.sqrt(np.mean(np.sum((aligned - target) ** 2, axis=1))))


def summarize(rows):
    accepted = [row for row in rows if row["relaxed_passed"]]
    values = [row["relaxed_quality"]["gap_backbone_rmsd_angstrom"] for row in accepted]
    return {"outcomes": len(rows), "sources": len({row["source_id"] for row in rows}), "geometry_accepted": len(accepted),
        "accepted_backbone_rmsd_bins_angstrom": {
            "<=1": sum(value <= 1 for value in values), "(1,2]": sum(1 < value <= 2 for value in values),
            "(2,4]": sum(2 < value <= 4 for value in values), ">4": sum(value > 4 for value in values)},
        "median_accepted_backbone_rmsd_angstrom": median(values) if values else None,
        "maximum_accepted_backbone_rmsd_angstrom": max(values, default=None),
        "median_accepted_generated_lddt": median(row["relaxed_quality"]["reference_metrics"]["generated_lddt"]["value"] for row in accepted) if accepted else None}


def analyze(args):
    report = json.loads(args.analysis.read_text())
    if not report["complete"] or report["pending"]:
        raise ValueError("accuracy audit requires complete paired evidence")
    rows = report["cases"]
    unique = [row for row in rows if row["arm"] in {"static-local", "full-raw"}]
    if len({row["case_id"] for row in unique}) != len(unique):
        raise ValueError("development masks are not unique after arm selection")
    worst = sorted((row for row in unique if row["relaxed_passed"]), key=lambda row: row["relaxed_quality"]["gap_backbone_rmsd_angstrom"], reverse=True)[:10]
    fitted = {row["case_id"]: fitted_backbone_rmsd(args.outcomes / row["case_id"] / row["arm"]) for row in unique}
    result = {"paired_analysis_sha256": hashlib.sha256(args.analysis.read_bytes()).hexdigest(),
        "all_arms": summarize(rows), "unique_mask_seed_cases": summarize(unique),
        "unique_by_length": {str(length): summarize([row for row in unique if row["length"] == length]) for length in sorted({row["length"] for row in unique})},
        "worst_geometry_accepted_unique": [{"case_id": row["case_id"], "source_id": row["source_id"], "length": row["length"],
            "backbone_rmsd_angstrom": row["relaxed_quality"]["gap_backbone_rmsd_angstrom"],
            "gap_only_fitted_backbone_rmsd_angstrom": fitted[row["case_id"]],
            "generated_lddt": row["relaxed_quality"]["reference_metrics"]["generated_lddt"]["value"],
            "junction_lddt": row["relaxed_quality"]["reference_metrics"]["junction_lddt"]["value"]} for row in worst],
        "remaining_failures": [{"case_id": row["case_id"], "backbone_rmsd_angstrom": row["relaxed_quality"]["gap_backbone_rmsd_angstrom"],
            "gap_only_fitted_backbone_rmsd_angstrom": fitted[row["case_id"]],
            "gates": row["relaxed_failed_gates"], "findings": row.get("relaxed_findings", [])} for row in unique if not row["relaxed_passed"]],
        "interpretation": "RMSD bins are descriptive, not acceptance gates; whole-interface scores can be dominated by preserved atoms",
        "public_promotion": False}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key not in {"remaining_failures", "worst_geometry_accepted_unique"}}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--outcomes", type=Path, required=True)
    analyze(parser.parse_args())


if __name__ == "__main__":
    main()
