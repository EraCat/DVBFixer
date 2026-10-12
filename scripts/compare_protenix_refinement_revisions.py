#!/usr/bin/env python3
"""Compare frozen v4 and current refinement on identical input and dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from types import ModuleType

import numpy as np
from openmm.app import PDBFile
from run_protenix_public_cohort import _atomic_json

from dvbfixer.model.diffusion.boundary_refinement import refine_generated_region
from dvbfixer.model.diffusion.contract import DiffusionRequest
from dvbfixer.model.diffusion.quality import check_sidechain_chi12
from dvbfixer.model.diffusion.runner_refinement import rewrite_generated_coordinates

FROZEN_REVISION = "47754cf"  # Last Reference v4 implementation before CUDA v5.
ROOT = Path(__file__).resolve().parents[1]


def restore_atom_order(text: str, reference_text: str) -> str:
    """Experimental control: change only ATOM record ordering, never coordinates."""
    if any(line.startswith(("CONECT", "ANISOU", "MODEL")) for line in text.splitlines()):
        raise ValueError("atom-order control requires a single plain protein PDB")

    def key(line: str) -> tuple[str, str, str, str]:
        return line[21], line[22:26], line[26], line[12:16]

    lines = text.splitlines(keepends=True)
    atoms = [line for line in lines if line.startswith("ATOM  ")]
    reference_keys = [key(line) for line in reference_text.splitlines() if line.startswith("ATOM  ")]
    by_key = {key(line): line for line in atoms}
    if len(by_key) != len(atoms) or len(set(reference_keys)) != len(reference_keys) or set(by_key) != set(reference_keys):
        raise ValueError("atom-order control requires identical unique atom identities")
    ordered = iter(by_key[identity] for identity in reference_keys)
    return "".join(next(ordered) if line.startswith("ATOM  ") else line for line in lines)


def compare(
    source_workspace: Path, *, raw_override: Path | None = None,
    restore_frozen_order: bool = False,
) -> dict:
    raw = raw_override or source_workspace / "confirmatory/protenix-raw/candidate.pdb"
    raw_text = raw.read_text()
    raw_digest = hashlib.sha256(raw.read_bytes()).hexdigest()
    if raw_override is None:
        raw_summary = json.loads((raw.parent / "summary.json").read_text())
        if raw_digest != raw_summary["candidate_sha256"]:
            raise ValueError("frozen raw candidate digest mismatch")
    if restore_frozen_order:
        raw_text = restore_atom_order(
            raw_text, (source_workspace / "confirmatory/protenix-raw/candidate.pdb").read_text(),
        )
    request_data = json.loads((source_workspace / "request.json").read_text())
    request_data["schema_version"] = 4
    request = DiffusionRequest.from_dict(request_data)
    if len(request.gaps) != 1:
        raise ValueError("controlled comparison requires one gap")
    source_code = subprocess.check_output([
        "git", "show", f"{FROZEN_REVISION}:src/dvbfixer/model/diffusion/boundary_refinement.py",
    ], cwd=ROOT, text=True)
    historical = ModuleType("protenix_frozen_boundary_refinement")
    sys.modules[historical.__name__] = historical
    exec(compile(source_code, "<frozen-v4-boundary-refinement>", "exec"), historical.__dict__)
    if historical.BOUNDARY_REFINEMENT_REVISION != "dvbfixer-openmm-boundary-refinement-v4":
        raise ValueError("unexpected frozen refinement revision")
    outcomes = []
    positions = []
    for label, refiner in (("v4-current-dependencies", historical.refine_generated_region),
                           ("v6-current-dependencies", refine_generated_region)):
        result = refiner(
            raw_text, generated_residues=request.gaps[0].generated_residues,
            generated_atoms=request.generated_atoms, platform_name="Reference",
            random_seed=request.seeds[0],
        )
        text = rewrite_generated_coordinates(raw_text, result.coordinates_angstrom)
        pdb = PDBFile(StringIO(text))
        findings = check_sidechain_chi12(pdb.topology, pdb.positions)
        positions.append(result.coordinates_angstrom)
        outcomes.append({
            "label": label, "pdb_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "pre_coordinate_sha256": result.pre_coordinate_sha256,
            "post_coordinate_sha256": result.post_coordinate_sha256,
            "initial_energy_kj_mol": result.initial_energy_kj_mol,
            "final_energy_kj_mol": result.final_energy_kj_mol,
            "sidechain_findings": [asdict(finding) for finding in findings],
        })
    max_delta = max(float(np.linalg.norm(positions[0][atom] - positions[1][atom])) for atom in positions[0])
    return {
        "schema_version": 1,
        "scope": "controlled-refinement-module-comparison-not-a-historical-environment-recreation",
        "raw_candidate_sha256": raw_digest,
        "restored_frozen_atom_order": restore_frozen_order,
        "historical_source_sha256": hashlib.sha256(source_code.encode()).hexdigest(),
        "historical_git_revision": FROZEN_REVISION,
        "same_input_same_current_dependencies": True,
        "maximum_coordinate_delta_angstrom": max_delta,
        "serialized_pdb_identical": outcomes[0]["pdb_sha256"] == outcomes[1]["pdb_sha256"],
        "outcomes": outcomes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--raw-candidate", type=Path, help="Optional captured current raw input")
    parser.add_argument("--restore-frozen-atom-order", action="store_true", help="Experimental ordering-only control")
    parser.add_argument("--archive-raw", type=Path, help="Preserve captured raw evidence in a new private file")
    args = parser.parse_args()
    result = compare(
        args.workspace, raw_override=args.raw_candidate,
        restore_frozen_order=args.restore_frozen_atom_order,
    )
    if args.archive_raw:
        if args.raw_candidate is None:
            parser.error("--archive-raw requires --raw-candidate")
        with args.raw_candidate.open("rb") as source, args.archive_raw.open("xb") as destination:
            shutil.copyfileobj(source, destination)
    _atomic_json(args.output, result)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
