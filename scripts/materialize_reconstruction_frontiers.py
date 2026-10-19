#!/usr/bin/env python3
"""Freeze richer cc89, adaptive context, deletion windows, and long-gap studies."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path

from materialize_protein_context_expansion import source_records

from dvbfixer.homology_plan import build_mosaic_diffusion_request, materialize_template_plan
from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    ArtifactReference,
    BackendOption,
    DiffusionRequest,
    GapRegion,
    ProteinContextPolicy,
    ResidueIdentity,
    SequencePlacement,
    TargetInterval,
    TargetSequence,
)
from dvbfixer.model.diffusion.gap_capabilities import gap_capability
from dvbfixer.model.diffusion.protein_context import select_protein_context
from dvbfixer.model.diffusion.scope import _CANONICAL_ONE_TO_THREE, canonical_heavy_atom_identities

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_case(root, request, normalized, reference):
    (root / "input").mkdir(parents=True)
    (root / "input/normalized.pdb").write_bytes(normalized)
    if reference is not None:
        (root / "reference.pdb").write_bytes(reference)
    (root / "request.json").write_text(request.to_json())


def freeze(output, manifest_path):
    if output.exists() or manifest_path.exists():
        raise ValueError("frontier cohort and manifest must be new")
    output.mkdir(parents=True)
    cases = []
    # Long lengths are declared before inference. The public 3-12 gate remains.
    for source_id, relative, chains in (("1ubq", "tests/fixtures/protein_context/1UBQ.pdb", ("A",)),
                                       ("1emv", "tests/fixtures/regressions/1EMV.pdb", ("A", "B"))):
        data = (ROOT / relative).read_bytes()
        rows, lines, points = source_records(data, chains)
        reverse = {value: key for key, value in _CANONICAL_ONE_TO_THREE.items()}
        for length in (13, 25, 26, 50):
            start = (len(rows[chains[0]]) - length) // 2
            stop = start + length
            generated = tuple(residue for residue, _name in rows[chains[0]][start:stop])
            mutable = set(generated)
            normalized = ("".join(line for line in lines if ResidueIdentity(line[21], line[22:26].strip(), line[26].strip()) not in mutable) + "TER\nEND\n").encode()
            reference = ("".join(lines) + "TER\nEND\n").encode()
            request = DiffusionRequest(schema_version=DIFFUSION_SCHEMA_VERSION,
                normalized_pdb=ArtifactReference("input/normalized.pdb", hashlib.sha256(normalized).hexdigest()),
                target_sequences=tuple(TargetSequence(chain, "".join(reverse[name] for _residue, name in rows[chain])) for chain in chains),
                sequence_placements=tuple(SequencePlacement(chain, len(rows[chain]),
                    tuple(index for index, (residue, _name) in enumerate(rows[chain]) if residue not in mutable),
                    tuple(residue for residue, _name in rows[chain] if residue not in mutable)) for chain in chains),
                gaps=(GapRegion(chains[0], TargetInterval(start, stop), rows[chains[0]][start - 1][0], rows[chains[0]][stop][0], generated,
                    (rows[chains[0]][start - 1][0], *generated, rows[chains[0]][stop][0])),),
                fixed_atoms=tuple(atom for atom in points if ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code) not in mutable),
                generated_atoms=tuple(atom for residue, name in rows[chains[0]][start:stop] for atom in canonical_heavy_atom_identities(residue, name)),
                retained_explicit_links=(), candidate_count=1, seeds=(7,), backend_options=(BackendOption("profile", "protenix-v1-cuda"),))
            for seed in (7, 19):
                name = f"long-{source_id}-{length}-seed{seed}"
                save_case(output / name, replace(request, seeds=(seed,)), normalized, reference)
                cases.append({"case_id": name, "kind": "long-gap", "length": length, "source": relative,
                              "source_sha256": hashlib.sha256(data).hexdigest(), "capability": asdict(gap_capability("protenix-v1-cuda", length)),
                              "arms": ["full-raw"], "refinement": "none"})
    # Reuse frozen sources/masks; re-declare configuration rather than changing
    # the earlier audit after its negative geometry outcomes.
    for name, origin, policy in (
        ("cc89-joint", "protein-context-expansion-cohort/1emv-joint", ProteinContextPolicy(partner_mode="full")),
        ("cc89-discontiguous", "protein-context-cohort/1emv-complex", ProteinContextPolicy(target_flanks=8, same_chain_spatial=True)),
        ("cc89-case-insertion", "protein-context-expansion-cohort/7k8s-insertion", ProteinContextPolicy(target_flanks=8, same_chain_spatial=True)),
    ):
        source = ROOT / ".artifacts" / origin
        request = DiffusionRequest.from_json((source / "request.json").read_text())
        normalized = (source / request.normalized_pdb.path).read_bytes()
        selected = select_protein_context(replace(request, backend_options=(BackendOption("profile", "protpardelle-1c-research"),)), normalized, policy)
        save_case(output / name, selected, normalized, (source / "reference.pdb").read_bytes())
        cases.append({"case_id": name, "kind": "cc89-rich", "arms": ["native-500", "projection-500"], "refinement": "none"})
    for name, origin in (("adaptive-1emv", "protein-context-cohort/1emv-complex"),
                         ("adaptive-7k8s", "protein-context-expansion-cohort/7k8s-insertion")):
        source = ROOT / ".artifacts" / origin
        request = DiffusionRequest.from_json((source / "request.json").read_text())
        normalized = (source / request.normalized_pdb.path).read_bytes()
        selected = select_protein_context(request, normalized, ProteinContextPolicy(target_flanks=8, same_chain_spatial=True))
        save_case(output / name, selected, normalized, (source / "reference.pdb").read_bytes())
        cases.append({"case_id": name, "kind": "adaptive", "arms": ["static-repeat", "adaptive-two-rounds"],
                      "rounds": 2, "refinement": "none", "axis_changes": "between-rounds-only", "selection": "monotonic-source-plus-sampled-backbone"})
    original = ROOT / ".artifacts/context-homology-cohort/deletion"
    plan = json.loads((original / "template-plan.json").read_text())
    targets = [(group["chainId"], group["rows"][0]["sequence"].replace("-", "")) for group in plan["alignmentGroups"]]
    for flanks in (1, 2, 3, 4, 5):
        name = f"deletion-flanks{flanks}"
        root = output / name
        root.mkdir()
        shutil.copyfile(original / "template-plan.json", root / "template-plan.json")
        shutil.copyfile(original / "target.fasta", root / "target.fasta")
        materialize_template_plan(root / "template-plan.json", root / "materialized")
        source, request_path = build_mosaic_diffusion_request(root / "materialized/selected_template_mosaic.coverage.json", targets,
            root / "materialized", seeds=(7,), regenerate_covered=True, profile="protenix-v1-cuda", edit_flanks=flanks)
        request = DiffusionRequest.from_json(request_path.read_text())
        normalized = source.read_bytes()
        request = replace(request, normalized_pdb=ArtifactReference("input/normalized.pdb", hashlib.sha256(normalized).hexdigest()))
        save_case(root, select_protein_context(request, normalized, ProteinContextPolicy(partner_mode="full")), normalized, None)
        cases.append({"case_id": name, "kind": "deletion", "edit_flanks": flanks,
                      "window_lengths": [len(gap.generated_residues) for gap in request.gaps],
                      "arms": ["full-refined"], "refinement": "Reference", "reference_quality": "undefined-no-solved-deletion-reference"})
    for case in cases:
        root = output / case["case_id"]
        case["artifacts"] = {path.relative_to(root).as_posix(): digest(path) for path in root.rglob("*") if path.is_file()}
    manifest = {"schema_version": 1, "status": "frozen-before-frontier-inference", "no_replacement": True, "cases": cases,
        "stop_rules": ["mapping/projection/source mismatch stops inference", "geometry rejection retained without replacement"],
        "limits": {"timeout_seconds": 3600, "protenix_steps": 200, "cc89_steps": 500, "residue_budget": 512,
                   "cc89_step_scale": 1.2, "cc89_s_churn": 200.0, "maximum_adaptive_rounds": 2},
        "public_acceptance": "existing-profile-3-12-only; richer-cc89-and-adaptive-remain-research",
        "promotion": "requires-larger-independent-cohort-and-separate-evidence-backed-decision",
        "sampling_environment": {"protenix_revision": "85767b811c40ed46e73a9b39519cf6bfca8701ba",
                                 "cc89_revision": "ee378400f25b801fa481028000f9060183d7fb4c"}}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"case_count": len(cases), "outcome_count": sum(len(case["arms"]) for case in cases)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    freeze(args.output, args.manifest)


if __name__ == "__main__":
    main()
