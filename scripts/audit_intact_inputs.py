#!/usr/bin/env python3
"""Verify intact CIF/PDB coverage, exact masks, and native engine-entity splits."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import gemmi
from run_a100_relaxation import sha, verify_inventory

from dvbfixer.model.diffusion.contract import AtomIdentity, DiffusionRequest
from dvbfixer.model.diffusion.protein_context import sampling_entities, validate_context_source
from dvbfixer.model.diffusion.validate import _parse_pdb_text


def cif_atoms(path):
    structure = gemmi.read_structure(str(path))
    atoms = {}
    for model_index, model in enumerate(structure):
        for chain in model:
            for residue in chain:
                for atom in residue:
                    key = (model_index, chain.name, str(residue.seqid.num), residue.seqid.icode.strip(), residue.name, atom.name, atom.altloc)
                    if key in atoms:
                        raise ValueError("ambiguous source CIF atom identity")
                    atoms[key] = (atom.pos.x, atom.pos.y, atom.pos.z)
    return atoms


def audit(manifest_path, cohort, visual):
    manifest = json.loads(manifest_path.read_text())
    rows = []
    source_info = {row["protein"]: row for row in manifest["screening"]}
    for case in (*manifest["cases"], *manifest["excluded_cases"]):
        view = visual / case["visual_directory"]
        original = visual / case["source_id"] / "deposited_source.cif"
        if sha(original) != source_info[case["source_id"]]["source_sha256"] or sha(view / "01_before_gap.cif") != sha(original):
            raise ValueError("full deposited CIF differs from the frozen original")
        before_cif, after_cif = cif_atoms(view / "01_before_gap.cif"), cif_atoms(view / "02_gapped_input.cif")
        inverse_chain_map = {mapped: original for original, mapped in case.get("source_chain_map", {}).items()}
        deleted_residues = {(inverse_chain_map.get(record["chain"], record["chain"]), record["residue_number"], record["insertion_code"])
                            for record in case["original_gap"]["generated_residues"]}
        expected_deleted = {atom for atom in before_cif if atom[1:4] in deleted_residues}
        if set(before_cif) - set(after_cif) != expected_deleted or set(after_cif) - set(before_cif):
            raise ValueError("full CIF pair changes more than the declared test gap")
        if any(before_cif[atom] != xyz for atom, xyz in after_cif.items()):
            raise ValueError("full CIF pair changes a background coordinate")
        row = {"case_id": case["case_id"], "source_id": case["source_id"], "status": case["status"],
            "all_deposited_atom_identities_outside_gap_preserved": True, "all_deposited_coordinates_outside_gap_preserved": True}
        if case["status"] == "eligible":
            root = cohort / "cases" / case["case_id"]
            verify_inventory(root, case["artifacts"])
            request = DiffusionRequest.from_json((root / "request.json").read_text())
            before = (root / "reference.pdb").read_bytes()
            masked = (root / request.normalized_pdb.path).read_bytes()
            atoms, residues, _ = _parse_pdb_text(before.decode())
            fixed, _, _ = _parse_pdb_text(masked.decode())
            actual_counts = dict(Counter(residue.chain for residue in residues))
            if actual_counts != source_info[case["source_id"]]["protein_chains"]:
                raise ValueError("intact PDB drops an observed protein residue or chain")
            if set(atoms) - set(fixed) != set(request.generated_atoms) or set(fixed) != set(request.fixed_atoms):
                raise ValueError("PDB atom masks do not cover the full intact source")
            if any(atoms[atom].coordinates_angstrom.tolist() != record.coordinates_angstrom.tolist() for atom, record in fixed.items()):
                raise ValueError("PDB gap creation moved a fixed source atom")
            validate_context_source(request, masked)
            if manifest.get("full_context") and (request.protein_context.preserved_only
                    or sum(span.stop - span.start for span in request.protein_context.spans) != sum(actual_counts.values())):
                raise ValueError("full-context cohort omits observed source atoms from conditioning")
            represented = {residue for entity in sampling_entities(request) for residue in entity.placement.observed_residues}
            conditioned = {(item.atom.chain, item.atom.residue_number, item.atom.insertion_code) for item in request.protein_context.fixed_conditioning}
            if {(residue.chain, residue.residue_number, residue.insertion_code) for residue in represented} != conditioned:
                raise ValueError("engine entities omit declared conditioning residues")
            for entity in sampling_entities(request):
                for left, right in zip(entity.residues, entity.residues[1:]):
                    carbon = fixed.get(AtomIdentity(left.chain, left.residue_number, left.insertion_code, "C"))
                    nitrogen = fixed.get(AtomIdentity(right.chain, right.residue_number, right.insertion_code, "N"))
                    if carbon is not None and nitrogen is not None:
                        distance = float(((carbon.coordinates_angstrom - nitrogen.coordinates_angstrom) ** 2).sum() ** 0.5)
                        if not 1.0 <= distance <= 1.8:
                            raise ValueError("engine entity joins a native chain break")
            row.update(observed_protein_chains=actual_counts, full_residue_count=sum(actual_counts.values()),
                engine_context_residue_count=case["engine_context_residue_count"], native_segments_never_falsely_joined=True)
        rows.append(row)
    return {"manifest_sha256": sha(manifest_path), "case_count": len(rows), "eligible": len(manifest["cases"]),
        "unsupported": len(manifest["excluded_cases"]), "cases": rows, "all_intact_input_checks_passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "cohort", "visual", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.manifest, args.cohort, args.visual)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, indent=2))


if __name__ == "__main__":
    main()
