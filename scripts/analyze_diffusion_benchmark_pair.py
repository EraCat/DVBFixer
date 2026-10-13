#!/usr/bin/env python3
"""Validate and compare two same-seed diffusion benchmark workspaces."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from dvbfixer.model.diffusion.benchmark import (
    assess_same_seed_repeatability,
    candidate_quality,
    load_pdb_coordinates,
)
from dvbfixer.model.diffusion.contract import (
    ArtifactReference,
    DiffusionRequest,
    RunnerResult,
)
from dvbfixer.model.diffusion.validate import build_validated_result


def analyze(first: Path, second: Path) -> dict[str, object]:
    """Return independent validation, withheld quality, and repeatability metrics."""
    first = first.expanduser().resolve()
    second = second.expanduser().resolve()
    request = DiffusionRequest.from_json((first / "request.json").read_text())
    repeated_request = DiffusionRequest.from_json((second / "request.json").read_text())
    if repeated_request != request:
        raise ValueError("benchmark workspaces do not contain identical requests")

    first_runner = RunnerResult.from_json((first / "result.json").read_text())
    second_runner = RunnerResult.from_json((second / "result.json").read_text())
    if len(first_runner.candidates) != 1 or len(second_runner.candidates) != 1:
        raise ValueError("benchmark pair must contain exactly one candidate per workspace")
    validated = build_validated_result(request, first_runner, workspace=first)
    summary = validated.validation_summaries[0]
    candidate = first_runner.candidates[0]

    reference_bytes = (first / "reference.pdb").read_bytes()
    reference_artifact = ArtifactReference(
        "reference.pdb",
        hashlib.sha256(reference_bytes).hexdigest(),
    )
    reference = load_pdb_coordinates(first, reference_artifact)
    first_coordinates = load_pdb_coordinates(first, candidate.coordinate_artifact)
    second_coordinates = load_pdb_coordinates(
        second,
        second_runner.candidates[0].coordinate_artifact,
    )
    quality = candidate_quality(
        candidate.candidate_id,
        reference,
        first_coordinates,
        generated_residues=set(request.gaps[0].generated_residues),
        fixed_atoms=set(request.fixed_atoms),
        anchor_residues={request.gaps[0].left_anchor, request.gaps[0].right_anchor},
        closure_passed="junction-peptide-connectivity" not in summary.hard_gate_failures,
        validation_passed=summary.passed,
        expected_generated_atoms=set(request.generated_atoms),
    )
    repeatability = assess_same_seed_repeatability(
        first_coordinates,
        second_coordinates,
        atom_identities=set(request.generated_atoms),
    )
    return {
        "candidate_sha256": candidate.coordinate_artifact.sha256,
        "validation_passed": summary.passed,
        "hard_gate_failures": summary.hard_gate_failures,
        "validation_metrics": {metric.name: metric.value for metric in summary.metrics},
        "quality": {
            "gap_backbone_rmsd_angstrom": quality.gap_backbone_rmsd_angstrom,
            "gap_all_heavy_rmsd_angstrom": quality.gap_all_heavy_rmsd_angstrom,
            "fixed_heavy_rmsd_angstrom": quality.fixed_heavy_rmsd_angstrom,
            "reference_metrics": asdict(quality.reference_metrics),
        },
        "repeatability": {
            "classification": repeatability.classification,
            "coordinate_rmsd_angstrom": repeatability.coordinate_rmsd_angstrom,
            "maximum_displacement_angstrom": repeatability.maximum_displacement_angstrom,
            "atom_count": repeatability.atom_count,
        },
        "resource_metrics": {
            "wall_time_seconds": first_runner.resource_metrics.wall_time_seconds,
            "peak_ram_bytes": first_runner.resource_metrics.peak_ram_bytes,
            "peak_vram_bytes": first_runner.resource_metrics.peak_vram_bytes,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(json.dumps(analyze(args.first, args.second), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
