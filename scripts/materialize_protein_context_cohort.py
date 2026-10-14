#!/usr/bin/env python3
"""Freeze a source-only protein-interface screening cohort before inference."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from dvbfixer.model.cli import AA3TO1
from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    ArtifactReference,
    AtomIdentity,
    BackendOption,
    DiffusionRequest,
    GapRegion,
    ProteinContextPolicy,
    ResidueIdentity,
    SequencePlacement,
    TargetInterval,
    TargetSequence,
)
from dvbfixer.model.diffusion.protein_context import select_protein_context
from dvbfixer.model.diffusion.scope import canonical_heavy_atom_identities

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    ("8xj0-fab", "tests/fixtures/assemblies/8XJ0.pdb", "B", "A", "fab-interface"),
    ("7k8s-fv", "tests/fixtures/insertion_codes/7K8S.pdb", "H", "L", "insertion-code-antibody"),
    ("1emv-complex", "tests/fixtures/regressions/1EMV.pdb", "A", "B", "buried-protein-complex"),
    ("1dqj-antigen", "tests/fixtures/regressions/1DQJ.pdb", "B", "C", "antibody-antigen"),
)


def materialize(output: Path, manifest_path: Path) -> dict:
    if output.exists() or manifest_path.exists():
        raise ValueError("context cohort and frozen manifest destinations must be new")
    output.mkdir(parents=True)
    cases = []
    for case_id, relative, target_chain, partner_chain, stratum in SOURCES:
        source_path = ROOT / relative
        data = source_path.read_bytes()
        rows = {target_chain: [], partner_chain: []}
        atoms = {}
        lines = []
        for line in data.decode().splitlines(keepends=True):
            if line.startswith("ENDMDL"):
                break
            if not line.startswith("ATOM  ") or line[21] not in rows or line[17:20].strip() not in AA3TO1:
                continue
            if line[76:78].strip() in {"H", "D"} or line[12:16].strip().lstrip("0123456789").startswith("H"):
                continue
            if line[16] not in {" ", "A"}:
                continue
            line = line[:16] + " " + line[17:]
            residue = ResidueIdentity(line[21], line[22:26].strip(), line[26].strip())
            atom = AtomIdentity(residue.chain, residue.residue_number, residue.insertion_code, line[12:16].strip())
            if atom in atoms:
                continue
            if residue not in [item[0] for item in rows[residue.chain]]:
                rows[residue.chain].append((residue, line[17:20].strip()))
            atoms[atom] = np.asarray([float(line[30:38]), float(line[38:46]), float(line[46:54])])
            lines.append(line)
        record = {"case_id": case_id, "source": relative, "source_sha256": hashlib.sha256(data).hexdigest(),
                  "target_chain": target_chain, "partner_chain": partner_chain, "stratum": stratum}
        try:
            for chain in rows:
                for residue, name in rows[chain]:
                    if not set(canonical_heavy_atom_identities(residue, name)) <= set(atoms):
                        raise ValueError(f"source heavy-atom-incomplete residue: {residue}")
            ordered = rows[target_chain]
            partner_points = np.asarray([point for atom, point in atoms.items() if atom.chain == partner_chain])
            starts = []
            for start in range(1, len(ordered) - 5):
                window = ordered[start:start + 5]
                if any(name == "CYS" for _residue_id, name in window):
                    continue
                window_ids = {residue for residue, _name in window}
                gap_points = np.asarray([point for atom, point in atoms.items() if ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code) in window_ids])
                distance = float(np.min(np.linalg.norm(gap_points[:, None] - partner_points[None], axis=2)))
                if distance <= 5.0:
                    starts.append((start, distance))
            if not starts:
                raise ValueError("no internal five-residue non-CYS interface window")
            start, distance = starts[0]  # Frozen file-order screening; no outcome selection.
            stop = start + 5
            generated = tuple(residue for residue, _name in ordered[start:stop])
            generated_set = set(generated)
            reference = "".join(lines) + "TER\nEND\n"
            normalized = "".join(line for line in lines if ResidueIdentity(line[21], line[22:26].strip(), line[26].strip()) not in generated_set) + "TER\nEND\n"
            fixed = tuple(atom for atom in atoms if ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code) not in generated_set)
            request = DiffusionRequest(
                schema_version=DIFFUSION_SCHEMA_VERSION,
                normalized_pdb=ArtifactReference("input/normalized.pdb", hashlib.sha256(normalized.encode()).hexdigest()),
                target_sequences=tuple(TargetSequence(chain, "".join(AA3TO1[name] for _residue_id, name in rows[chain])) for chain in rows),
                sequence_placements=tuple(SequencePlacement(chain, len(rows[chain]), tuple(i for i in range(len(rows[chain])) if chain != target_chain or not start <= i < stop), tuple(residue for i, (residue, _name) in enumerate(rows[chain]) if chain != target_chain or not start <= i < stop)) for chain in rows),
                gaps=(GapRegion(target_chain, TargetInterval(start, stop), ordered[start - 1][0], ordered[stop][0], generated, (ordered[start - 1][0], *generated, ordered[stop][0])),),
                fixed_atoms=fixed,
                generated_atoms=tuple(atom for residue, name in ordered[start:stop] for atom in canonical_heavy_atom_identities(residue, name)),
                retained_explicit_links=(), candidate_count=1, seeds=(7,), backend_options=(BackendOption("profile", "protenix-v1-cuda"),),
            )
            for policy in (ProteinContextPolicy(target_flanks=1, partner_mode="none"), ProteinContextPolicy(target_flanks=8, same_chain_spatial=True), ProteinContextPolicy(partner_mode="full")):
                select_protein_context(request, normalized.encode(), policy)
            case_root = output / case_id
            (case_root / "input").mkdir(parents=True)
            (case_root / "input/normalized.pdb").write_text(normalized)
            (case_root / "reference.pdb").write_text(reference)
            (case_root / "request.json").write_text(request.to_json())
            record.update(status="eligible", gap_start=start, gap_stop=stop, gap_length=5,
                          generated_residues=[{ "chain": r.chain, "residue_number": r.residue_number, "insertion_code": r.insertion_code} for r in generated],
                          reference_interface_minimum_distance_angstrom=distance,
                          artifacts={name: hashlib.sha256((case_root / name).read_bytes()).hexdigest() for name in ("input/normalized.pdb", "reference.pdb", "request.json")})
        except ValueError as exc:
            record.update(status="unsupported", reason=str(exc))
        cases.append(record)
    manifest = {
        "schema_version": 1, "status": "frozen-before-context-inference", "seed": 7,
        "screening_order_locked": True, "no_replacement": True,
        "selection": "first-complete-non-CYS-internal-gap5-reference-contact<=5A-in-file-order",
        "arms": ["anchors-gap", "sequence-8", "sequence-16", "same-chain-spatial", "local-partner", "full-protein", "template-only", "local-partner-refined"],
        "primary_causal_gate": {"probe_step_index": 100, "partner_translation_angstrom": [25.0, 0.0, 0.0],
                                "repeat_max_abs_delta_angstrom": 0.0, "minimum_generated_response_angstrom": 0.0001},
        "stop_rules": ["stop on mapping/projection/callback or source digest failure", "geometry rejects remain terminal outcomes without replacement", "no outcome-based policy or threshold changes"],
        "cases": cases,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--write-companion-fastas", action="store_true", help="Derive FASTAs from frozen requests without changing screening or masks")
    args = parser.parse_args()
    if args.write_companion_fastas:
        manifest = json.loads(args.manifest.read_text())
        for case in manifest["cases"]:
            if case["status"] != "eligible":
                continue
            source = args.output / case["case_id"]
            request_path = source / "request.json"
            if hashlib.sha256(request_path.read_bytes()).hexdigest() != case["artifacts"]["request.json"]:
                raise ValueError("frozen request digest changed")
            request = DiffusionRequest.from_json(request_path.read_text())
            text = "".join(f">{target.chain}\n{target.sequence}\n" for target in request.target_sequences)
            target_path = source / "target.fasta"
            if target_path.exists() and target_path.read_text() != text:
                raise ValueError("existing companion FASTA differs from frozen target sequences")
            target_path.write_text(text)
        print("Derived companion FASTAs; frozen masks and manifest unchanged")
    else:
        print(json.dumps(materialize(args.output, args.manifest), indent=2))


if __name__ == "__main__":
    main()
