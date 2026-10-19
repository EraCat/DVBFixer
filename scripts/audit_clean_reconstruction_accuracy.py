#!/usr/bin/env python3
"""Audit withheld accuracy of the frozen full-input CUDA cohort, without sampling.

Geometry acceptance and reference agreement are separate endpoints. This audit
does not select candidates, tune a protocol, or promote public capabilities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from statistics import median

from run_a100_relaxation import verify_inventory

from dvbfixer.model.diffusion.benchmark import candidate_quality, load_pdb_coordinates
from dvbfixer.model.diffusion.contract import ArtifactReference, DiffusionRequest, RunnerResult
from dvbfixer.model.diffusion.gap_capabilities import gap_capability
from dvbfixer.model.diffusion.protein_context import validate_context_source
from dvbfixer.model.diffusion.validate import validate_runner_result


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def summarize(rows: list[dict], stage: str) -> dict:
    available = [row[stage] for row in rows if row.get(stage) is not None]
    accepted = [item for item in available if item["validation_passed"]]
    values = [item["quality"]["gap_backbone_rmsd_angstrom"] for item in available]
    accepted_values = [item["quality"]["gap_backbone_rmsd_angstrom"] for item in accepted]
    lddt = [item["quality"]["reference_metrics"]["generated_lddt"]["value"] for item in available]
    return {
        "planned_attempts": len(rows), "sources": len({row["source_id"] for row in rows}),
        "available": len(available), "missing": len(rows) - len(available),
        "geometry_accepted": len(accepted), "geometry_rejected": len(available) - len(accepted),
        "median_backbone_rmsd_all_candidates_angstrom": median(values) if values else None,
        "maximum_backbone_rmsd_all_candidates_angstrom": max(values, default=None),
        "median_backbone_rmsd_geometry_accepted_angstrom": median(accepted_values) if accepted_values else None,
        "maximum_backbone_rmsd_geometry_accepted_angstrom": max(accepted_values, default=None),
        "median_generated_lddt_defined_candidates": median(value for value in lddt if value is not None) if any(value is not None for value in lddt) else None,
        "undefined_generated_lddt_count": sum(value is None for value in lddt),
        "geometry_accepted_backbone_rmsd_bins_angstrom": {
            "<=1": sum(value <= 1 for value in accepted_values),
            "(1,2]": sum(1 < value <= 2 for value in accepted_values),
            "(2,4]": sum(2 < value <= 4 for value in accepted_values),
            ">4": sum(value > 4 for value in accepted_values),
        },
    }


def audit(manifest_path: Path, protocol_path: Path, outcomes: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    protocol = json.loads(protocol_path.read_text())
    if protocol["cohort_sha256"] != sha(manifest_path) or not protocol["no_outcome_replacement"]:
        raise ValueError("accuracy audit requires the exact frozen no-replacement cohort")
    cases = manifest["cases"]
    if len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError("accuracy audit cannot count duplicate case identities")
    rows = []
    for case in cases:
        root = (outcomes / case["case_id"]).resolve()
        marker = json.loads((root / "complete.json").read_text())
        if marker["protocol_sha256"] != sha(protocol_path):
            raise ValueError("accuracy outcome belongs to another frozen protocol")
        verify_inventory(root, marker["artifacts"])
        # A self-consistent completion marker is insufficient: bind the input
        # request/reference to this exact case in the frozen source manifest.
        verify_inventory(root, case["artifacts"])
        for name in ("request.json", "reference.pdb", "outcome.json"):
            if name not in marker["artifacts"]:
                raise ValueError("accuracy input is absent from the archived inventory")
        request = DiffusionRequest.from_json((root / "request.json").read_text())
        if len(request.gaps) != 1 or len(request.gaps[0].generated_residues) != case["length"]:
            raise ValueError("accuracy case length differs from its frozen request")
        source = (root / request.normalized_pdb.path).read_bytes()
        validate_context_source(request, source)
        if request.protein_context is None or request.protein_context.preserved_only:
            raise ValueError("clean full-context audit requires every fixed source atom to be represented")
        reference = load_pdb_coordinates(root, ArtifactReference("reference.pdb", marker["artifacts"]["reference.pdb"]))
        generated = {residue for gap in request.gaps for residue in gap.generated_residues}
        anchors = {anchor for gap in request.gaps for anchor in (gap.left_anchor, gap.right_anchor) if anchor}
        target_chains = {gap.chain for gap in request.gaps}
        partners = tuple((chain, target.chain) for chain in sorted(target_chains)
                         for target in request.target_sequences if target.chain not in target_chains)
        row = {"case_id": case["case_id"], "source_id": case["source_id"], "length": case["length"],
               "stratum": gap_capability("protenix-v1-cuda", case["length"]).stratum,
               "archive_complete_sha256": sha(root / "complete.json"),
               "terminal_status": json.loads((root / "outcome.json").read_text())["status"]}
        for stage, filename in (("raw", "runner-result.json"), ("relaxed", "relaxed-runner-result.json")):
            if filename not in marker["artifacts"]:
                if row["terminal_status"] == "evaluated":
                    raise ValueError("completed accuracy case is missing an archived candidate result")
                row[stage] = None
                continue
            result = RunnerResult.from_json((root / filename).read_text())
            validations = validate_runner_result(request, result, workspace=root)
            if len(validations) != 1:
                raise ValueError("frozen clean cohort requires exactly one candidate per attempt")
            validated, = validations
            candidate = validated.candidate
            summary = validated.summary
            quality = candidate_quality(candidate.candidate_id, reference,
                load_pdb_coordinates(root, candidate.coordinate_artifact),
                generated_residues=generated, fixed_atoms=set(request.fixed_atoms), anchor_residues=anchors,
                closure_passed="junction-peptide-connectivity" not in summary.hard_gate_failures,
                validation_passed=summary.passed, expected_generated_atoms=set(request.generated_atoms),
                interface_chain_pairs=partners)
            row[stage] = {"validation_passed": summary.passed, "failed_gates": summary.hard_gate_failures,
                "quality": asdict(quality), "candidate_sha256": candidate.coordinate_artifact.sha256}
        rows.append(row)
    groups = {"all": rows}
    groups.update({f"length-{length}": [row for row in rows if row["length"] == length]
                   for length in sorted({row["length"] for row in rows})})
    groups.update({stratum: [row for row in rows if row["stratum"] == stratum]
                   for stratum in sorted({row["stratum"] for row in rows})})
    return {
        "schema_version": 1, "complete": True, "cohort_sha256": sha(manifest_path),
        "protocol_sha256": sha(protocol_path), "producer_sha256": sha(Path(__file__).resolve()),
        "analysis_timing": "post-hoc-withheld-accuracy-audit; not preregistered acceptance",
        "summaries": {name: {stage: summarize(group, stage) for stage in ("raw", "relaxed")} for name, group in groups.items()},
        "cases": rows, "source_native_exclusions": manifest["excluded_cases"],
        "selection_uses_reference": False, "public_promotion": False,
        "interpretation": "RMSD bins are descriptive, not hard gates; repeated masks within a source are not independent structures",
        "remaining_acceptance": ["prospective paired MODELLER comparison", "independent scientific review"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "protocol", "outcomes", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be a new audit artifact")
    result = audit(args.manifest, args.protocol, args.outcomes)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps(result["summaries"], indent=2))


if __name__ == "__main__":
    main()
