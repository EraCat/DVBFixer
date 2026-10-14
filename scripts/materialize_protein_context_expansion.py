#!/usr/bin/env python3
"""Freeze expanded protein-only context cases and controls before inference."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
from run_protein_context_ablations import POLICIES

from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    ArtifactReference,
    AtomIdentity,
    BackendOption,
    DiffusionRequest,
    GapRegion,
    ResidueIdentity,
    SequencePlacement,
    TargetInterval,
    TargetSequence,
)
from dvbfixer.model.diffusion.protein_context import select_protein_context
from dvbfixer.model.diffusion.scope import _CANONICAL_ONE_TO_THREE, canonical_heavy_atom_identities

ROOT = Path(__file__).resolve().parents[1]
SPECS = (
    ("1ubq-low-contact", "tests/fixtures/protein_context/1UBQ.pdb", ("A",), "low-contact"),
    ("1ubq-core", "tests/fixtures/protein_context/1UBQ.pdb", ("A",), "high-contact"),
    ("1tim-interface", "tests/fixtures/protein_context/1TIM.pdb", ("A", "B"), "interface"),
    ("1a3n-interface", "tests/fixtures/protein_context/1A3N.pdb", ("A", "B"), "interface"),
    ("7k8s-insertion", "tests/fixtures/insertion_codes/7K8S.pdb", ("H", "L"), "insertion"),
    ("1emv-joint", "tests/fixtures/regressions/1EMV.pdb", ("A", "B"), "joint"),
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_records(data, chains):
    reverse = {value: key for key, value in _CANONICAL_ONE_TO_THREE.items()}
    residues = {chain: [] for chain in chains}
    lines = []
    points = {}
    for line in data.decode().splitlines(keepends=True):
        if line.startswith("ENDMDL"):
            break
        if not line.startswith("ATOM  ") or line[21] not in chains or line[17:20].strip() not in reverse:
            continue
        if line[16] not in {" ", "A"} or line[76:78].strip() in {"H", "D"}:
            continue
        atom = AtomIdentity(line[21], line[22:26].strip(), line[26].strip(), line[12:16].strip())
        if atom in points:
            continue
        residue = ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code)
        if not residues[atom.chain] or residues[atom.chain][-1][0] != residue:
            residues[atom.chain].append((residue, line[17:20].strip()))
        points[atom] = np.asarray([float(line[30:38]), float(line[38:46]), float(line[46:54])])
        lines.append(line[:16] + " " + line[17:])
    if any(not rows for rows in residues.values()):
        raise ValueError("required source chain absent")
    for rows in residues.values():
        for residue, name in rows:
            if not set(canonical_heavy_atom_identities(residue, name)) <= points.keys():
                raise ValueError(f"source heavy-atom-incomplete residue: {residue}")
    return residues, lines, points


def choose_window(rows, points, chain, criterion):
    candidates = []
    other_points = np.asarray([xyz for atom, xyz in points.items() if atom.chain != chain])
    for start in range(1, len(rows) - 5):
        window = rows[start:start + 5]
        if any(name == "CYS" for _residue, name in window):
            continue
        ids = {residue for residue, _name in window}
        coordinates = np.asarray([xyz for atom, xyz in points.items()
                                  if ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code) in ids])
        interface_distance = float(np.linalg.norm(coordinates[:, None] - other_points[None], axis=2).min()) if len(other_points) else None
        neighborhood = rows[max(0, start - 2):start + 7]
        excluded = {residue for residue, _name in neighborhood}
        contacts = set()
        for atom, xyz in points.items():
            residue = ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code)
            if atom.chain == chain and residue not in excluded and np.linalg.norm(coordinates - xyz, axis=1).min() <= 6.0:
                contacts.add(residue)
        if criterion in {"interface", "joint"} and (interface_distance is None or interface_distance > 5.0):
            continue
        if criterion == "insertion" and not any(residue.insertion_code for residue, _name in window):
            continue
        candidates.append((len(contacts), start, interface_distance))
    if not candidates:
        raise ValueError("no eligible preregistered five-residue window")
    selected = min(candidates, key=lambda item: (item[0], item[1])) if criterion == "low-contact" else max(candidates, key=lambda item: (item[0], -item[1])) if criterion == "high-contact" else min(candidates, key=lambda item: item[1])
    return selected[1], {"nonlocal_same_chain_contact_residue_count": selected[0], "reference_interface_minimum_distance_angstrom": selected[2]}


def materialize(output, manifest_path):
    if output.exists() or manifest_path.exists():
        raise ValueError("expanded cohort and manifest must be new")
    output.mkdir(parents=True)
    cases = []
    for case_id, relative, chains, criterion in SPECS:
        data = (ROOT / relative).read_bytes()
        record = {"case_id": case_id, "source": relative, "source_sha256": sha(data), "stratum": criterion}
        try:
            rows, lines, points = source_records(data, chains)
            selections = {chain: choose_window(rows[chain], points, chain, criterion) for chain in (chains if criterion == "joint" else chains[:1])}
            generated = {residue for chain, (start, _metrics) in selections.items() for residue, _name in rows[chain][start:start + 5]}
            gaps = tuple(GapRegion(chain, TargetInterval(start, start + 5), rows[chain][start - 1][0], rows[chain][start + 5][0],
                                   tuple(residue for residue, _name in rows[chain][start:start + 5]),
                                   tuple(residue for residue, _name in rows[chain][start - 1:start + 6])) for chain, (start, _metrics) in selections.items())
            normalized = "".join(line for line in lines if ResidueIdentity(line[21], line[22:26].strip(), line[26].strip()) not in generated) + "TER\nEND\n"
            reference = "".join(lines) + "TER\nEND\n"
            reverse = {value: key for key, value in _CANONICAL_ONE_TO_THREE.items()}
            request = DiffusionRequest(
                schema_version=DIFFUSION_SCHEMA_VERSION, normalized_pdb=ArtifactReference("input/normalized.pdb", sha(normalized.encode())),
                target_sequences=tuple(TargetSequence(chain, "".join(reverse[name] for _residue, name in rows[chain])) for chain in chains),
                sequence_placements=tuple(SequencePlacement(chain, len(rows[chain]),
                    tuple(index for index, (residue, _name) in enumerate(rows[chain]) if residue not in generated),
                    tuple(residue for residue, _name in rows[chain] if residue not in generated)) for chain in chains),
                gaps=gaps, fixed_atoms=tuple(atom for atom in points if ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code) not in generated),
                generated_atoms=tuple(atom for chain in chains for residue, name in rows[chain] if residue in generated for atom in canonical_heavy_atom_identities(residue, name)),
                retained_explicit_links=(), candidate_count=1, seeds=(7,), backend_options=(BackendOption("profile", "protenix-v1-cuda"),),
            )
            variants = [(case_id, request, normalized, reference, criterion, ["same-chain-spatial", "local-partner-refined"])]
            # A second seed is frozen for every eligible source, not selected
            # after viewing first-seed geometry.
            variants.append((case_id + "-seed19", replace(request, seeds=(19,)), normalized, reference, criterion, ["local-partner-refined"]))
            if len(chains) > 1 and criterion != "joint":
                def translated(text, target_chain=chains[0]):
                    result = []
                    for line in text.splitlines(keepends=True):
                        if line.startswith("ATOM  ") and line[21] != target_chain:
                            line = line[:30] + f"{float(line[30:38]) + 80:8.3f}" + line[38:]
                        result.append(line)
                    return "".join(result)
                distant = translated(normalized)
                variants.append((case_id + "-distant", replace(request, normalized_pdb=ArtifactReference("input/normalized.pdb", sha(distant.encode()))), distant, translated(reference), "distant-negative-control", ["same-chain-spatial", "local-partner-refined"]))
            for name, variant, source_text, reference_text, stratum, arms in variants:
                root = output / name
                (root / "input").mkdir(parents=True)
                (root / "input/normalized.pdb").write_text(source_text)
                (root / "reference.pdb").write_text(reference_text)
                (root / "request.json").write_text(variant.to_json())
                arm_support = {}
                for arm in (*arms, "direct-shell", "budget-64"):
                    try:
                        selected = select_protein_context(variant, source_text.encode(), POLICIES[arm])
                        arm_support[arm] = {"status": "eligible", "selected_residue_count": sum(span.stop - span.start for span in selected.protein_context.spans)}
                    except ValueError as exc:
                        arm_support[arm] = {"status": "unsupported", "reason": str(exc)}
                cases.append({**record, "case_id": name, "status": "eligible", "stratum": stratum,
                              "arms": arms, "seed": variant.seeds[0], "arm_support": arm_support,
                              "mask_metrics": {chain: metrics for chain, (_start, metrics) in selections.items()},
                              "artifacts": {path: sha((root / path).read_bytes()) for path in ("input/normalized.pdb", "reference.pdb", "request.json")}})
        except ValueError as exc:
            cases.append({**record, "status": "unsupported", "reason": str(exc)})
    manifest = {"schema_version": 1, "status": "frozen-before-context-inference", "no_replacement": True,
                "scope": "expanded-descriptive-protein-context-not-production-promotion",
                "arms": ["same-chain-spatial", "local-partner-refined"], "cases": cases,
                "policies": {name: asdict(policy) for name, policy in POLICIES.items()},
                "primary_causal_gate": {"minimum_generated_response_angstrom": 0.0001, "partner_translation_angstrom": [25.0, 0.0, 0.0], "probe_step_index": 100, "repeat_max_abs_delta_angstrom": 0.0},
                "selection": "observed-complete-canonical-protein; gap5; no-CYS; file-order interfaces/insertion; min/max nonlocal-contact proxy",
                "stop_rules": ["mapping/source/projection failure stops execution", "geometry rejection is a terminal outcome without replacement"],
                "limitations": ["training membership unknown", "contact count is not solvent accessibility", "heterogens stripped for protein-only mechanism study", "no joint Protpardelle promotion"]}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    manifest = materialize(args.output, args.manifest)
    print(json.dumps([{key: case[key] for key in ("case_id", "status", "reason") if key in case} for case in manifest["cases"]], indent=2))


if __name__ == "__main__":
    main()
