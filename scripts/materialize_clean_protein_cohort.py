#!/usr/bin/env python3
"""Freeze full, clean protein complexes and source-only gap masks before inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

import gemmi
from Bio.Align import PairwiseAligner, substitution_matrices
from materialize_intact_recheck import (
    make_intact_request,
    prepare_intact_pdb,
    verify_engine_templates,
)
from run_a100_relaxation import sha, verify_inventory

from dvbfixer.ffutils import sanitize_protein_hetatm
from dvbfixer.model.diffusion.contract import ProteinContextPolicy
from dvbfixer.model.diffusion.protein_context import sampling_entities, select_protein_context
from dvbfixer.model.diffusion.scope import _CANONICAL_ONE_TO_THREE, CANONICAL_HEAVY_ATOMS
from dvbfixer.model.diffusion.validate import (
    ValidationThresholds,
    _load_structure,
    _parse_pdb_text,
    _validate_candidate,
)
from dvbfixer.structure_input import normalize_structure

ROOT = Path(__file__).resolve().parents[1]
LENGTHS = (5, 13, 25, 26, 50)
REVERSE = {value: key for key, value in _CANONICAL_ONE_TO_THREE.items()}


def sequence_overlap(first, second):
    normalized = "".join(char if char in "ACDEFGHIKLMNPQRSTVWY" else "X" for char in second)
    aligner = PairwiseAligner(mode="local", substitution_matrix=substitution_matrices.load("BLOSUM62"), open_gap_score=-10, extend_gap_score=-0.5)
    alignments = aligner.align(first, normalized)
    if alignments.score <= 0:
        return 0.0
    indices = alignments[0].indices
    paired = [(i, j) for i, j in zip(*indices) if i >= 0 and j >= 0]
    if len(paired) < 80 or len(paired) / min(len(first), len(normalized)) < 0.80:
        return 0.0
    possible_matches = sum(first[i] == normalized[j] or normalized[j] == "X" for i, j in paired)
    return possible_matches / indices.shape[1]


def prior_sequences():
    sequences = set()
    for filename in ("cuda-calibration-sources.json", "relaxation-holdout-sources-blosum62.json"):
        sequences.update(row["sequence"] for row in json.loads((ROOT / "docs/research" / filename).read_text())["cases"] if row.get("sequence"))
    for path in (ROOT / "gap_visual_review").glob("*/deposited_source.cif"):
        structure = gemmi.read_structure(str(path))
        for entity in structure.entities:
            if entity.polymer_type in {gemmi.PolymerType.PeptideL, gemmi.PolymerType.PeptideD} and entity.full_sequence:
                sequences.add("".join(REVERSE.get(name, "X") for name in entity.full_sequence))
    return sorted(sequences)


def inspect_clean_structure(structure):
    """No components or chains are discarded to satisfy these source criteria."""
    if len(structure) != 1:
        return {"supported": False, "reasons": ["multiple-models"]}
    reasons, chain_rows, sequences = [], {}, {}
    entity_map = {subchain: entity for entity in structure.entities for subchain in entity.subchains}
    waters = 0
    for chain in structure[0]:
        rows = []
        for residue in chain:
            if residue.is_water():
                waters += 1
                continue
            if residue.name not in CANONICAL_HEAVY_ATOMS or residue.entity_type != gemmi.EntityType.Polymer:
                reasons.append(f"nonprotein-or-noncanonical:{chain.name}/{residue.name}{residue.seqid}")
                continue
            if any(atom.altloc not in {"\x00", " "} for atom in residue):
                reasons.append(f"alternate-conformers:{chain.name}/{residue.seqid}")
            atoms = [atom for atom in residue if not atom.element.is_hydrogen]
            names = [atom.name for atom in atoms]
            if len(names) != len(set(names)) or not set(CANONICAL_HEAVY_ATOMS[residue.name]) <= set(names):
                reasons.append(f"incomplete-or-duplicate-heavy-atoms:{chain.name}/{residue.seqid}")
            if set(names) - set(CANONICAL_HEAVY_ATOMS[residue.name]) - {"OXT"}:
                reasons.append(f"unexpected-heavy-atoms:{chain.name}/{residue.seqid}")
            rows.append(residue)
        if not rows:
            continue
        subchains = {residue.subchain for residue in rows}
        if len(subchains) != 1 or next(iter(subchains)) not in entity_map:
            reasons.append(f"ambiguous-polymer-entity:{chain.name}")
        else:
            entity = entity_map[next(iter(subchains))]
            if entity.polymer_type != gemmi.PolymerType.PeptideL or not entity.full_sequence or any(name not in REVERSE for name in entity.full_sequence):
                reasons.append(f"noncanonical-or-undeclared-polymer-sequence:{chain.name}")
            elif ([residue.label_seq for residue in rows] != list(range(1, len(entity.full_sequence) + 1))
                  or [residue.name for residue in rows] != list(entity.full_sequence)):
                reasons.append(f"coordinate-incomplete-polymer-sequence:{chain.name}")
        for left, right in zip(rows, rows[1:]):
            if not left.find_atom("C", "*") or not right.find_atom("N", "*"):
                continue
            distance = left["C"][0].pos.dist(right["N"][0].pos)
            if not 1.0 <= distance <= 1.8:
                reasons.append(f"native-backbone-break:{chain.name}/{left.seqid}->{right.seqid}")
        chain_rows[chain.name] = rows
        sequences[chain.name] = "".join(REVERSE[residue.name] for residue in rows)
    count = sum(len(rows) for rows in chain_rows.values())
    if not count or count > 512:
        reasons.append("whole-source-residue-budget-exceeded-or-empty")
    for connection in structure.connections:
        kind = str(connection.type)
        if kind not in {"ConnectionType.Covale", "ConnectionType.Disulf"}:
            continue
        first, second = connection.partner1, connection.partner2
        disulfide = first.atom_name == second.atom_name == "SG"
        chain = chain_rows.get(first.chain_name, [])
        order = {(str(residue.seqid.num), residue.seqid.icode.strip()): index for index, residue in enumerate(chain)}
        first_index = order.get((str(first.res_id.seqid.num), first.res_id.seqid.icode.strip()))
        second_index = order.get((str(second.res_id.seqid.num), second.res_id.seqid.icode.strip()))
        peptide = (first.chain_name == second.chain_name and {first.atom_name, second.atom_name} == {"C", "N"}
                   and first_index is not None and second_index is not None and abs(first_index - second_index) == 1)
        if not disulfide and not peptide:
            reasons.append("nonstandard-covalent-protein-link:" + connection.name)
    return {"supported": not reasons, "reasons": sorted(set(reasons)), "protein_residues": count,
        "chain_counts": {chain: len(rows) for chain, rows in chain_rows.items()}, "sequences": sequences, "water_residues": waters}


def secondary_annotation(structure, chain_name, residues):
    order = {(str(residue.seqid.num), residue.seqid.icode.strip()): index for index, residue in enumerate(residues)}
    labels = [set() for _ in residues]
    unresolved = 0
    entries = [(helix.start, helix.end, "helix") for helix in structure.helices]
    entries += [(strand.start, strand.end, "sheet") for sheet in structure.sheets for strand in sheet.strands]
    for first, last, kind in entries:
        if first.chain_name != chain_name or last.chain_name != chain_name:
            continue
        start = order.get((str(first.res_id.seqid.num), first.res_id.seqid.icode.strip()))
        stop = order.get((str(last.res_id.seqid.num), last.res_id.seqid.icode.strip()))
        if start is None or stop is None:
            unresolved += 1
            continue
        for index in range(start, stop + 1):
            labels[index].add(kind)
    return labels, unresolved


def starts_for_length(residues, length):
    return [start for start in range(1, len(residues) - length)
            if not any(residue.name == "CYS" for residue in residues[start:start + length])]


def freeze(args):
    if args.output.exists() or args.manifest.exists() or args.visual.exists():
        raise ValueError("clean-protein cohort destinations must be new")
    pool = json.loads(args.sources_manifest.read_text())
    verify_inventory(args.sources, pool["artifacts"])
    args.output.mkdir(parents=True)
    args.visual.mkdir()
    history = prior_sequences()
    selected_sequences = []
    screening, chosen = [], []
    for candidate in pool["cases"]:
        record = dict(candidate)
        if candidate["status"] != "downloaded":
            screening.append({**record, "status": "excluded", "reasons": [candidate.get("reason", candidate["status"])]})
            continue
        source = args.sources / (candidate["pdb_id"] + ".cif")
        structure = gemmi.read_structure(str(source))
        info = inspect_clean_structure(structure)
        record.update(info)
        if not info["supported"]:
            record["status"] = "excluded"
            screening.append(record)
            continue
        target = candidate["target_auth_chain"]
        if target not in info["chain_counts"]:
            record.update(status="excluded", reasons=["declared-target-chain-absent"])
            screening.append(record)
            continue
        target_residues = list(structure[0][target])
        target_residues = [residue for residue in target_residues if not residue.is_water()]
        missing_lengths = [length for length in LENGTHS if not starts_for_length(target_residues, length)]
        if missing_lengths:
            record.update(status="excluded", reasons=["no-CYS-free-internal-mask-for-length:" + ",".join(map(str, missing_lengths))])
            screening.append(record)
            continue
        sequences = sorted(set(info["sequences"].values()))
        overlap = max((sequence_overlap(sequence, old) for sequence in sequences for old in history if min(len(sequence), len(old)) >= 80), default=0)
        record["maximum_prior_sequence_overlap_with_unknown_sensitivity"] = overlap
        if overlap > 0.30 or any(sequence == old and len(sequence) >= 20 for sequence in sequences for old in history):
            record.update(status="excluded", reasons=["sequence-overlap-with-prior-reviewed-proteins"])
        elif any((min(len(sequence), len(other)) >= 80 and sequence_overlap(sequence, other) > 0.30)
                 or (sequence == other and len(sequence) >= 20) for sequence in sequences for other in selected_sequences):
            record.update(status="excluded", reasons=["sequence-overlap-with-an-earlier-selected-complex"])
        elif len(chosen) >= 20:
            record.update(status="eligible-not-selected", reasons=["predeclared-20-source-budget"])
        else:
            record.update(status="selected", reasons=[])
            chosen.append((candidate, structure))
            selected_sequences.extend(sequences)
        screening.append(record)
    if not chosen:
        (args.output / "screening.json").write_text(json.dumps(screening, indent=2, sort_keys=True) + "\n")
        raise ValueError("no intact clean sources passed the frozen criteria")
    cases, excluded = [], []
    source_records = []
    for candidate, structure in chosen:
        protein = candidate["pdb_id"]
        source = args.sources / (protein + ".cif")
        root = args.output / "sources" / protein
        root.mkdir(parents=True)
        visual = args.visual / protein
        visual.mkdir()
        shutil.copyfile(source, visual / "deposited_source.cif")
        normalized = normalize_structure(source, root / "full-normalized.pdb")
        sanitized = sanitize_protein_hetatm(str(normalized.pdb_path))
        before, preparation = prepare_intact_pdb(Path(sanitized).read_text())
        if preparation["native_breaks"] or preparation["alternative_conformer_atoms_removed"]:
            raise ValueError("clean screen and normalized intact preparation disagree")
        (root / "reference.pdb").write_bytes(before)
        _, residue_names, _ = _parse_pdb_text(before.decode())
        target = normalized.chain_map.get(candidate["target_auth_chain"], candidate["target_auth_chain"])
        target_rows = [residue for residue in residue_names if residue.chain == target]
        original_target = [residue for residue in structure[0][candidate["target_auth_chain"]] if not residue.is_water()]
        labels, unresolved = secondary_annotation(structure, candidate["target_auth_chain"], original_target)
        info = next(row for row in screening if row["pdb_id"] == protein)
        mapped_counts = {normalized.chain_map.get(chain, chain): count for chain, count in info["chain_counts"].items()}
        if dict(Counter(residue.chain for residue in residue_names)) != mapped_counts:
            raise ValueError("clean preparation dropped observed protein residues")
        source_records.append({"protein": protein, "source_sha256": sha(source), "protein_chains": mapped_counts,
            "protein_residues": info["protein_residues"], "status": "selected", "chain_map": normalized.chain_map, "preparation": preparation})
        for length in LENGTHS:
            starts = starts_for_length(original_target, length)
            start = min(starts, key=lambda index: hashlib.sha256(f"clean-protein-gap-v1:{protein}:{length}:{index}".encode()).hexdigest())
            stop = start + length
            generated = tuple(target_rows[start:stop])
            gap = {"chain": target, "left_anchor": asdict(target_rows[start - 1]), "right_anchor": asdict(target_rows[stop]),
                "generated_residues": [asdict(residue) for residue in generated]}
            case_id = f"{protein.lower()}-gap{length}-seed7"
            view = visual / f"gap_{length:03d}" / "seed_007"
            view.mkdir(parents=True)
            shutil.copyfile(source, view / "01_before_gap.cif")
            masked_cif = structure.clone()
            chain = masked_cif[0][candidate["target_auth_chain"]]
            selected_ids = {(residue.residue_number, residue.insertion_code) for residue in generated}
            for index in range(len(chain) - 1, -1, -1):
                if (str(chain[index].seqid.num), chain[index].seqid.icode.strip()) in selected_ids:
                    del chain[index]
            masked_cif.make_mmcif_document().write_file(str(view / "02_gapped_input.cif"))
            window_labels = labels[start:stop]
            secondary = {kind: sum(kind in flags for flags in window_labels) for kind in ("helix", "sheet")}
            secondary["unannotated"] = sum(not flags for flags in window_labels)
            record = {"case_id": case_id, "source_id": protein, "length": length, "seed": 7, "split": "expanded-clean-protein",
                "arms": ["full-clean-complex"], "original_gap": gap, "original_geometry_passed": True,
                "source_target_auth_chain": candidate["target_auth_chain"], "source_chain_map": normalized.chain_map,
                "visual_directory": view.relative_to(args.visual).as_posix(), "secondary_structure": secondary,
                "unresolved_deposited_secondary_ranges": unresolved, "full_source_residue_count": info["protein_residues"]}
            workspace = args.output / "cases" / case_id
            (workspace / "input").mkdir(parents=True)
            (workspace / "reference.pdb").write_bytes(before)
            reasons = []
            try:
                request, masked = make_intact_request(before, {"gap": gap})
                request = select_protein_context(replace(request, protein_context=None), masked,
                    ProteinContextPolicy(name="intact-native-segments-v1", target_flanks=None, partner_mode="full"))
                if request.protein_context.preserved_only:
                    raise ValueError("clean full-context protocol silently excludes fixed atoms from conditioning")
                represented = sum(span.stop - span.start for span in request.protein_context.spans)
                if represented != info["protein_residues"]:
                    raise ValueError("engine context does not cover the full protein complex")
                (workspace / "input/normalized.pdb").write_bytes(masked)
                (workspace / "request.json").write_text(request.to_json())
                (view / "01_before_gap.pdb").write_bytes(before)
                (view / "02_gapped_input.pdb").write_bytes(masked)
                verify_engine_templates(workspace, request)
                root_absolute = workspace.resolve()
                native = _load_structure(root_absolute, "reference.pdb", sha(workspace / "reference.pdb"))
                source_masked = _load_structure(root_absolute, "input/normalized.pdb", sha(workspace / "input/normalized.pdb"))
                native_validation = _validate_candidate(request, source_masked, native, ValidationThresholds())[0]
                record["native_source_validation"] = asdict(native_validation)
                record["original_geometry_passed"] = native_validation.passed
                if not native_validation.passed:
                    raise ValueError("source-native-window-already-fails-geometry:" + ",".join(native_validation.hard_gate_failures))
                record.update(status="eligible", engine_context_residue_count=represented, preserved_only_atom_count=0,
                    sampling_entities=[{"engine_chain": entity.engine_chain, "source_chain": entity.target.chain, "residue_count": len(entity.residues)} for entity in sampling_entities(request)],
                    artifacts={path.relative_to(workspace).as_posix(): sha(path) for path in workspace.rglob("*") if path.is_file()})
                cases.append(record)
            except (ValueError, RuntimeError) as exc:
                reasons.append(str(exc))
                record.update(status="unsupported", reasons=reasons)
                excluded.append(record)
            (view / "case.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
            (view / "README.md").write_text(f"# {case_id}\n\nStatus: {record['status']}\n\n"
                f"Chain {target}, residues {', '.join(residue.residue_number + residue.insertion_code for residue in generated)}.\n\n"
                f"Deposited annotation overlap: {secondary}. Unannotated is not assumed to be a loop.\n\n"
                "Full protein complex retained in input AND engine features; no partner or target truncation. Solvent-free preparation only; no ligand/cofactor stripping.\n\n"
                + ("Source-only exclusion: " + "; ".join(reasons) + "\n" if reasons else "Native source passes the unchanged local geometry checks before inference.\n"))
    paths = ("scripts/materialize_clean_protein_cohort.py", "scripts/materialize_intact_recheck.py", "src/dvbfixer/model/diffusion/protein_context.py", "src/dvbfixer/model/diffusion/scope.py")
    manifest = {"status": "frozen-before-a100-calibration-inference", "study": "clean-protein-full-complex-expanded-v1",
        "no_replacement": True, "pool_manifest_sha256": sha(args.sources_manifest), "screening": source_records,
        "source_pool_screening": screening, "cases": cases, "excluded_cases": excluded,
        "code_sha256": {relative: sha(ROOT / relative) for relative in paths},
        "scope": "complete clean canonical proteins; full target plus every partner on engine axis <=512; no native gaps, missing heavy atoms, ligands, ions, cofactors or other polymers",
        "selection": "fixed pool200, first20 source-eligible mutually nonredundant complexes, all five non-CYS masks required before source selection; no secondary-structure exclusion",
        "pre_inference_protocol_clarification": "v2 source-only homology screen: local BLOSUM62 open=-10 extend=-0.5; >=80 aligned residue pairs and >=80% shorter-chain coverage required; identity denominator includes all local alignment columns, including internal gaps; aligned unknowns conservatively treated as matches; exact shared chains>=20 excluded; first global-identity-over-shorter screen archived without inference",
        "original_geometry_role": "native source-window control, not an earlier generated candidate",
        "mask_source_quality_policy": "first fixed-hash chemical-eligible window only; if native geometry fails retain as excluded mask without trying another position",
        "limits": {"steps": 200, "timeout_seconds": 3600, "engine_context_budget": 512},
        "full_context": True, "reference_rmsd_used": False, "training_membership_independently_attested": False, "public_promotion": False}
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (args.visual / "README.md").write_text(f"# Expanded clean-protein full-context test\n\nSelected complete sources: {len(chosen)}. Planned masks: {len(chosen) * len(LENGTHS)}. Eligible: {len(cases)}. Source-only mask exclusions: {len(excluded)}.\n\n"
        "Every source is protein-only (waters excluded explicitly from solvent-free PDB preparation). Full target and all partner chains are supplied to the model, <=512 residues total. No source cropping or chemical-component stripping.\n\n"
        "01_before_gap / 02_gapped_input show exact masks; 03_restored_relaxed / 04_restored_raw are added after the run. Deposited helix/sheet overlap is recorded in case.json; unannotated does not mean loop.\n")
    (args.visual / "source_screening.json").write_text(json.dumps(screening, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"screened_pool": len(screening), "selected_sources": len(chosen), "planned_masks": len(chosen) * len(LENGTHS),
        "eligible_cases": len(cases), "source_only_mask_exclusions": len(excluded), "manifest_sha256": sha(args.manifest),
        "source_exclusion_counts": dict(Counter(reason.split(":", 1)[0] for row in screening for reason in row.get("reasons", [])))}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "sources-manifest", "output", "manifest", "visual"):
        parser.add_argument("--" + name, type=Path, required=True)
    freeze(parser.parse_args())


if __name__ == "__main__":
    main()
