#!/usr/bin/env python3
"""Screen every locked prospective source and freeze CUDA validation masks."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from materialize_protein_context_expansion import source_records
from scipy.spatial import cKDTree

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
from dvbfixer.model.diffusion.scope import (
    _CANONICAL_ONE_TO_THREE,
    assess_diffusion_scope,
    canonical_heavy_atom_identities,
)
from dvbfixer.structure_input import normalize_structure


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_request(rows, lines, points, chain, start, length, seed):
    stop = start + length
    generated = tuple(residue for residue, _name in rows[chain][start:stop])
    generated_set = set(generated)
    normalized = ("".join(line for line in lines if ResidueIdentity(line[21], line[22:26].strip(), line[26].strip()) not in generated_set) + "TER\nEND\n").encode()
    reference = ("".join(lines) + "TER\nEND\n").encode()
    reverse = {name: aa for aa, name in _CANONICAL_ONE_TO_THREE.items()}
    request = DiffusionRequest(schema_version=DIFFUSION_SCHEMA_VERSION,
        normalized_pdb=ArtifactReference("input/normalized.pdb", hashlib.sha256(normalized).hexdigest()),
        target_sequences=tuple(TargetSequence(identifier, "".join(reverse[name] for _residue, name in sequence)) for identifier, sequence in rows.items()),
        sequence_placements=tuple(SequencePlacement(identifier, len(sequence),
            tuple(index for index, (residue, _name) in enumerate(sequence) if residue not in generated_set),
            tuple(residue for residue, _name in sequence if residue not in generated_set)) for identifier, sequence in rows.items()),
        gaps=(GapRegion(chain, TargetInterval(start, stop), rows[chain][start - 1][0], rows[chain][stop][0], generated,
                         (rows[chain][start - 1][0], *generated, rows[chain][stop][0])),),
        fixed_atoms=tuple(atom for atom in points if ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code) not in generated_set),
        generated_atoms=tuple(atom for residue, name in rows[chain][start:stop] for atom in canonical_heavy_atom_identities(residue, name)),
        retained_explicit_links=(), seeds=(seed,), candidate_count=1, backend_options=(BackendOption("profile", "protenix-v1-cuda"),))
    return request, normalized, reference


def materialize(args):
    if args.output.exists() or args.manifest.exists():
        raise ValueError("prospective calibration cohort must be new")
    args.output.mkdir(parents=True)
    source_manifest = json.loads(args.sources_manifest.read_text())
    for relative, expected in source_manifest["artifacts"].items():
        if sha(args.sources / relative) != expected:
            raise ValueError("locked prospective source changed")
    screenings = []
    cases = []
    for rank, source in enumerate(source_manifest["cases"]):
        record = {**source, "rank": rank, "split": "calibration" if rank % 2 == 0 else "validation"}
        if source["status"] != "metadata-eligible":
            screenings.append(record)
            continue
        root = args.output / "screening" / source["pdb_id"]
        root.mkdir(parents=True)
        try:
            converted = normalize_structure(args.sources / (source["pdb_id"] + ".cif"), root / "source.pdb")
            target = converted.chain_map.get(source["target_auth_chain"], source["target_auth_chain"])
            data = converted.pdb_path.read_bytes()
            canonical = set(_CANONICAL_ONE_TO_THREE.values())
            all_chains = sorted({line[21] for line in data.decode().splitlines() if line.startswith("ATOM  ") and line[17:20].strip() in canonical})
            if target not in all_chains:
                raise ValueError("declared target chain is absent after boundary normalization")
            partners = [chain for chain in all_chains if chain != target]
            chains = (target, *partners[:1])
            rows, lines, points = source_records(data, chains)
            observed = "".join({value: key for key, value in _CANONICAL_ONE_TO_THREE.items()}[name] for _residue, name in rows[target])
            if observed != source["sequence"]:
                raise ValueError("target observed sequence is not the complete locked polymer sequence")
            for identifier, sequence in rows.items():
                for (first, _), (second, _) in zip(sequence, sequence[1:]):
                    c = points[AtomIdentity(identifier, first.residue_number, first.insertion_code, "C")]
                    n = points[AtomIdentity(identifier, second.residue_number, second.insertion_code, "N")]
                    if not 1.0 <= float(np.linalg.norm(c - n)) <= 1.8:
                        raise ValueError("source contains a non-contiguous or malformed peptide backbone")
            neighbors = np.asarray([xyz for atom, xyz in points.items() if atom.chain != target])
            tree = cKDTree(neighbors) if len(neighbors) else None
            distance_by_residue = {}
            if tree is not None:
                for atom, xyz in points.items():
                    if atom.chain == target:
                        key = ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code)
                        distance_by_residue[key] = min(distance_by_residue.get(key, float("inf")), float(tree.query(xyz)[0]))
            mask_metrics = []
            for length in (5, 13, 25, 26, 50):
                starts = []
                for start in range(1, len(rows[target]) - length):
                    if any(name == "CYS" for _residue, name in rows[target][start:start + length]):
                        continue
                    contacts = min(distance_by_residue[residue] for residue, _name in rows[target][start:start + length]) if tree is not None else None
                    # Select by frozen hash order within contact/non-contact
                    # strata, not by native reconstruction outcomes.
                    key = hashlib.sha256(f"cuda-calibration-mask-v1:{source['pdb_id']}:{length}:{start}".encode()).hexdigest()
                    starts.append((0 if contacts is not None and contacts <= 6 else 1, key, start, contacts))
                if not starts:
                    mask_metrics.append({"length": length, "status": "unsupported", "reason": "no-complete-non-CYS-window"})
                    continue
                _priority, _key, start, contacts = min(starts)
                for seed in source_manifest["seeds"]:
                    request, normalized, reference = make_request(rows, lines, points, target, start, length, seed)
                    policy = ProteinContextPolicy(target_flanks=8, same_chain_spatial=True) if length == 5 else ProteinContextPolicy(partner_mode="full")
                    selected = select_protein_context(request, normalized, policy)
                    if length == 5:
                        admission = assess_diffusion_scope(selected, normalized)
                        if not admission.supported:
                            raise ValueError("baseline source admission failed: " + ", ".join(admission.reasons))
                    case_id = f"{source['pdb_id'].lower()}-gap{length}-seed{seed}"
                    workspace = args.output / "cases" / case_id
                    (workspace / "input").mkdir(parents=True)
                    (workspace / "input/normalized.pdb").write_bytes(normalized)
                    (workspace / "reference.pdb").write_bytes(reference)
                    (workspace / "request.json").write_text(selected.to_json())
                    cases.append({"case_id": case_id, "kind": "adaptive-calibration" if length == 5 else "long-gap", "length": length,
                        "source_id": source["pdb_id"], "source_sha256": source["source_sha256"], "release_date": source["release_date"],
                        "split": record["split"], "target_chain": target, "partner_chains": list(chains[1:]), "start": start,
                        "reference_interface_minimum_distance_angstrom": contacts,
                        "arms": source_manifest["arms"]["short" if length == 5 else "long"],
                        "artifacts": {path.relative_to(workspace).as_posix(): sha(path) for path in workspace.rglob("*") if path.is_file()}})
                mask_metrics.append({"length": length, "status": "eligible", "start": start, "contact_distance_angstrom": contacts})
            record.update(status="eligible", declared_chains=list(chains), masks=mask_metrics)
        except (ValueError, OSError, RuntimeError) as exc:
            # No replacement from the next-ranked entry. Already emitted masks
            # for a rejected source must not become runnable.
            cases = [case for case in cases if case["source_id"] != source["pdb_id"]]
            record.update(status="unsupported", reason=str(exc))
        screenings.append(record)
    manifest = {"schema_version": 1, "status": "frozen-before-a100-calibration-inference", "no_replacement": True,
        "source_manifest_sha256": sha(args.sources_manifest), "screening": screenings, "cases": cases,
        "limits": source_manifest["limits"], "adaptive_contact_gate": source_manifest["adaptive_contact_gate"],
        "promotion": source_manifest["promotion"], "leakage": source_manifest["leakage"], "geometry_policy": "unchanged-current-independent-validator"}
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"screened_sources": len(screenings), "eligible_sources": sum(record["status"] == "eligible" for record in screenings),
                      "masked_cases": len(cases), "outcomes": sum(len(case["arms"]) for case in cases)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "sources-manifest", "output", "manifest"):
        parser.add_argument("--" + name, required=True, type=Path)
    materialize(parser.parse_args())


if __name__ == "__main__":
    main()
