#!/usr/bin/env python3
"""Freeze complete-fragment calibration from every previously locked 2026 entry."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import gemmi
from materialize_cuda_calibration import make_request, sha
from materialize_protein_context_expansion import source_records

from dvbfixer.model.diffusion.contract import ProteinContextPolicy
from dvbfixer.model.diffusion.protein_context import select_protein_context
from dvbfixer.model.diffusion.scope import CANONICAL_HEAVY_ATOMS, assess_diffusion_scope
from dvbfixer.structure_input import normalize_structure


def complete_runs(chain):
    runs = []
    for residue in chain:
        names = CANONICAL_HEAVY_ATOMS.get(residue.name)
        atoms = {atom.name: atom for atom in residue if atom.altloc in {"\x00", " ", "A"} and not atom.element.is_hydrogen}
        if names is None or not set(names) <= atoms.keys():
            if runs and runs[-1]:
                runs.append([])
            continue
        selected = residue.clone()
        for atom in list(selected):
            if atom.altloc not in {"\x00", " ", "A"} or atom.element.is_hydrogen:
                selected.remove_atom(atom.name, atom.altloc)
        if not runs or not runs[-1]:
            if not runs:
                runs.append([])
        elif not 1.0 <= runs[-1][-1]["C"][0].pos.dist(atoms["N"].pos) <= 1.8:
            runs.append([])
        runs[-1].append(selected)
    return [run for run in runs if run]


def materialize(args):
    if args.output.exists() or args.manifest.exists():
        raise ValueError("fragment cohort and manifest must be new")
    args.output.mkdir(parents=True)
    locked = json.loads(args.sources_manifest.read_text())
    for relative, expected in locked["artifacts"].items():
        if sha(args.sources / relative) != expected:
            raise ValueError("locked 2026 source changed")
    screenings = []
    cases = []
    for rank, entry in enumerate(locked["cases"]):
        record = {**entry, "rank": rank, "split": "validation" if getattr(args, "validation_only", False) else ("calibration" if rank % 2 == 0 else "validation")}
        if entry["status"] != "metadata-eligible":
            screenings.append(record)
            continue
        root = args.output / "screening" / entry["pdb_id"]
        root.mkdir(parents=True)
        try:
            # Research dataset selection precedes the normal CLI conversion
            # boundary. The deposited CIF is retained byte-for-byte; the derived
            # CIF explicitly declares its selected canonical protein fragments.
            original = gemmi.read_structure(str(args.sources / (entry["pdb_id"] + ".cif")))
            target_chain = original[0][entry["target_auth_chain"]]
            target_runs = complete_runs(target_chain)
            target = max(target_runs, key=lambda run: (len(run), -run[0].seqid.num))
            if len(target) < 70:
                raise ValueError("no complete contiguous target fragment of at least 70 residues")
            target = target[:250]
            partner_candidates = []
            for chain in original[0]:
                if chain.name == target_chain.name:
                    continue
                for run in complete_runs(chain):
                    if len(run) < 12:
                        continue
                    # Deterministic nearest complete fragment; at most 120
                    # residues, keeping declared subcomplex below 512 tokens.
                    positions = [(residue["CA"][0].pos.dist(target_residue["CA"][0].pos), index)
                                 for index, residue in enumerate(run) for target_residue in target]
                    distance, center = min(positions)
                    start = max(0, min(center - 60, len(run) - 120))
                    partner_candidates.append((distance, chain.name, start, run[start:start + 120]))
            selected = [(target_chain.name, target)]
            if partner_candidates:
                _distance, identifier, _start, partner = min(partner_candidates, key=lambda item: item[:3])
                selected.append((identifier, partner))
            structure = gemmi.Structure()
            model = gemmi.Model("1")
            for identifier, run in selected:
                chain = gemmi.Chain(identifier)
                for residue in run:
                    chain.add_residue(residue)
                model.add_chain(chain)
            structure.add_model(model)
            structure.setup_entities()
            derived = root / "selected-protein-fragments.cif"
            structure.make_mmcif_document().write_file(str(derived))
            normalized = normalize_structure(derived, root / "selected-protein-fragments.pdb")
            chain_ids = tuple(normalized.chain_map.get(identifier, identifier) for identifier, _run in selected)
            rows, lines, points = source_records(normalized.pdb_path.read_bytes(), chain_ids)
            source_cases = []
            for length in (5, 13, 25, 26, 50):
                eligible = [start for start in range(1, len(rows[chain_ids[0]]) - length)
                            if not any(name == "CYS" for _residue, name in rows[chain_ids[0]][start:start + length])]
                if not eligible:
                    continue
                start = min(eligible, key=lambda index: hashlib.sha256(f"a100-fragment-mask-v1:{entry['pdb_id']}:{length}:{index}".encode()).hexdigest())
                for seed in locked["seeds"]:
                    request, pdb, reference = make_request(rows, lines, points, chain_ids[0], start, length, seed)
                    policy = ProteinContextPolicy(target_flanks=8, same_chain_spatial=True) if length == 5 else ProteinContextPolicy(partner_mode="full")
                    request = select_protein_context(request, pdb, policy)
                    if length == 5:
                        admission = assess_diffusion_scope(request, pdb)
                        if not admission.supported:
                            raise ValueError("baseline admission failed: " + ", ".join(admission.reasons))
                    case_id = f"{entry['pdb_id'].lower()}-gap{length}-seed{seed}"
                    workspace = args.output / "cases" / case_id
                    (workspace / "input").mkdir(parents=True)
                    (workspace / "input/normalized.pdb").write_bytes(pdb)
                    (workspace / "reference.pdb").write_bytes(reference)
                    (workspace / "request.json").write_text(request.to_json())
                    source_cases.append({"case_id": case_id, "kind": "adaptive-calibration" if length == 5 else "long-gap", "length": length,
                        "source_id": entry["pdb_id"], "source_sha256": entry["source_sha256"], "release_date": entry["release_date"],
                        "split": record["split"], "target_chain": chain_ids[0], "partner_chains": list(chain_ids[1:]), "start": start,
                        "arms": locked["arms"]["short" if length == 5 else "long"],
                        "artifacts": {path.relative_to(workspace).as_posix(): sha(path) for path in workspace.rglob("*") if path.is_file()}})
            cases.extend(source_cases)
            record.update(status="eligible", fragment_residue_counts=[len(run) for _identifier, run in selected],
                          declared_chains=list(chain_ids), derived_source_sha256=sha(derived), mask_count=len(source_cases))
        except (ValueError, OSError, RuntimeError, KeyError) as exc:
            record.update(status="unsupported", reason=str(exc))
        screenings.append(record)
    manifest = {"schema_version": 1, "status": "frozen-before-a100-calibration-inference", "no_replacement": True,
        "source_manifest_sha256": sha(args.sources_manifest), "screening": screenings, "cases": cases,
        "limits": locked["limits"], "adaptive_contact_gate": locked["adaptive_contact_gate"],
        "promotion": locked["promotion"], "leakage": locked["leakage"], "geometry_policy": "unchanged-current-independent-validator",
        "scope": "complete-contiguous-protein-fragments-not-full-ASU-or-complete-biological-assemblies",
        "version_note": "separate fragment-screening protocol after low complete-chain eligibility; before any calibration inference",
        "selection": "longest complete target run >=70, capped250; nearest complete partner run >=12, capped120; original-24-source-membership-no-replacement"}
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"screened_sources": len(screenings), "eligible_sources": sum(record["status"] == "eligible" for record in screenings),
                      "masked_cases": len(cases), "outcomes": sum(len(case["arms"]) for case in cases)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "sources-manifest", "output", "manifest"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--validation-only", action="store_true", help="Declare every source as a new holdout; do not create calibration members")
    materialize(parser.parse_args())


if __name__ == "__main__":
    main()
