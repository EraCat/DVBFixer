#!/usr/bin/env python3
"""Localize raw A100 validation failures without tuning the frozen policy."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from analyze_a100_calibration import equivalent_validation

from dvbfixer.diagnose.chemistry import (
    check_backbone_bond_angles,
    check_bond_lengths,
    check_peptide_omegas,
)
from dvbfixer.diagnose.report import Severity
from dvbfixer.diagnose.steric import clashes_python
from dvbfixer.model.diffusion.contract import DiffusionRequest, RunnerResult
from dvbfixer.model.diffusion.quality import check_ramachandran, check_sidechain_chi12
from dvbfixer.model.diffusion.validate import (
    _finding_partner_residue,
    _finding_residue,
    _load_structure,
    validate_runner_result,
)


def findings(structure, request):
    local = {residue for gap in request.gaps for residue in (*gap.generated_residues, gap.left_anchor, gap.right_anchor) if residue}
    pdb = structure.pdb
    records = []
    for check in (check_bond_lengths, check_backbone_bond_angles, check_peptide_omegas, check_ramachandran, check_sidechain_chi12):
        for finding in check(pdb.topology, pdb.positions):
            if (finding.severity is Severity.ERROR or finding.category == "non_planar_amide") and _finding_residue(finding.chain, finding.resid) in local:
                records.append(asdict(finding))
    for finding in clashes_python(pdb.topology, pdb.positions, clash_warn_a=0.9, clash_error_a=0.9):
        if finding.severity is Severity.ERROR and (_finding_residue(finding.chain, finding.resid) in local or _finding_partner_residue(finding) in local):
            records.append(asdict(finding))
    generated = {(residue.chain, residue.residue_number, residue.insertion_code)
                 for gap in request.gaps for residue in gap.generated_residues}
    for record in records:
        atoms = record["extra"].get("atoms", [])
        roles = {"generated" if (atom["chain"], atom["resid"], atom.get("icode", "")) in generated else "fixed" for atom in atoms}
        record["atom_scope"] = "+".join(sorted(roles)) or "residue-level"
    return records


def summarize(rows):
    return {"outcomes": len(rows), "accepted": sum(row["passed"] for row in rows),
        "sources": sorted({row["source_id"] for row in rows}),
        "gate_counts": dict(Counter(gate for row in rows for gate in row["failed_gates"])),
        "gate_combinations": dict(Counter(" + ".join(sorted(row["failed_gates"])) or "accepted" for row in rows))}


def analyze(args):
    analysis = json.loads(args.analysis.read_text())
    if not analysis["complete"] or analysis["pending"]:
        raise ValueError("failure audit requires the completed independent analysis")
    rows = []
    for case in analysis["cases"]:
        root = (args.outcomes / case["case_id"] / case["arm"]).resolve()
        marker = json.loads((root / "complete.json").read_text())
        if marker["manifest_sha256"] != analysis["manifest_sha256"]:
            raise ValueError("raw manifest changed")
        for relative, expected in marker["artifacts"].items():
            if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
                raise ValueError("raw artifact changed")
        request = DiffusionRequest.from_json((root / "request.json").read_text())
        result = RunnerResult.from_json((root / "runner-result.json").read_text())
        validation = validate_runner_result(request, result, workspace=root)[0].summary
        outcome = json.loads((root / "outcome.json").read_text())
        if not equivalent_validation(validation, outcome["validation"]) or validation.passed != case["validation_passed"]:
            raise ValueError("raw current validation changed")
        candidate = result.candidates[0].coordinate_artifact
        structure = _load_structure(root, candidate.path, candidate.sha256)
        reference = _load_structure(root, "reference.pdb", marker["artifacts"]["reference.pdb"])
        detailed = findings(structure, request)
        reference_findings = findings(reference, request)
        identical = [finding for finding in detailed if finding in reference_findings]
        rows.append({"case_id": case["case_id"], "arm": case["arm"], "source_id": case["source_id"], "length": case["length"],
            "split": case["split"], "passed": validation.passed, "failed_gates": validation.hard_gate_failures,
            "metrics": {metric.name: metric.value for metric in validation.metrics}, "quality": case["quality"],
            "findings": detailed, "reference_findings": reference_findings, "findings_identical_to_reference": identical})
    report = {"raw_analysis_sha256": hashlib.sha256(args.analysis.read_bytes()).hexdigest(), "all": summarize(rows),
        "by_source": {source: summarize([row for row in rows if row["source_id"] == source]) for source in sorted({row["source_id"] for row in rows})},
        "by_length": {str(length): summarize([row for row in rows if row["length"] == length]) for length in sorted({row["length"] for row in rows})},
        "outcomes_with_findings_identical_to_reference": sum(bool(row["findings_identical_to_reference"]) for row in rows),
        "findings_identical_to_reference_count": sum(len(row["findings_identical_to_reference"]) for row in rows),
        "finding_localization": dict(Counter(finding["category"] + "/" + finding["atom_scope"] for row in rows for finding in row["findings"])),
        "outcomes": rows, "policy_changed": False}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "outcomes"}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("analysis", "outcomes", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    analyze(parser.parse_args())


if __name__ == "__main__":
    main()
