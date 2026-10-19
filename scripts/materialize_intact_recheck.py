#!/usr/bin/env python3
"""Inspect and freeze intact deposited inputs for the repeated gap experiment."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import gemmi
import numpy as np

from dvbfixer.ffutils import sanitize_protein_hetatm
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
from dvbfixer.model.diffusion.protein_context import (
    sampling_entities,
    select_protein_context,
    validate_context_capability,
)
from dvbfixer.model.diffusion.scope import (
    _CANONICAL_ONE_TO_THREE,
    CANONICAL_HEAVY_ATOMS,
    assess_diffusion_scope,
    canonical_heavy_atom_identities,
)
from dvbfixer.model.diffusion.validate import _parse_pdb_text
from dvbfixer.renumber import update_conect
from dvbfixer.structure_input import normalize_structure

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def residue_key(line):
    return ResidueIdentity(line[21], line[22:26].strip(), line[26].strip())


def prepare_intact_pdb(text):
    """Choose a declared conformer and mark native breaks, retaining every residue."""
    retained = []
    rows, points = {}, {}
    dropped_water_atoms = dropped_hydrogens = dropped_altloc_atoms = 0
    for line in text.splitlines(keepends=True):
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if line[17:20].strip() in {"HOH", "WAT", "DOD"}:
            dropped_water_atoms += 1
            continue
        if line[76:78].strip() in {"H", "D"}:
            dropped_hydrogens += 1
            continue
        if line[16] not in {" ", "A"}:
            dropped_altloc_atoms += 1
            continue
        if line[17:20].strip() not in CANONICAL_HEAVY_ATOMS:
            raise ValueError("intact input contains unsupported retained chemistry")
        residue = residue_key(line)
        atom = AtomIdentity(residue.chain, residue.residue_number, residue.insertion_code, line[12:16].strip())
        if atom in points:
            raise ValueError("blank/A conformer selection has duplicate atom identity")
        points[atom] = np.asarray([float(line[30:38]), float(line[38:46]), float(line[46:54])])
        if not rows.setdefault(residue.chain, []) or rows[residue.chain][-1] != residue:
            rows[residue.chain].append(residue)
        retained.append(line[:16] + " " + line[17:])
    breaks = set()
    descriptions = []
    for chain, residues in rows.items():
        for left, right in zip(residues, residues[1:]):
            carbon = points.get(AtomIdentity(chain, left.residue_number, left.insertion_code, "C"))
            nitrogen = points.get(AtomIdentity(chain, right.residue_number, right.insertion_code, "N"))
            distance = float(np.linalg.norm(carbon - nitrogen)) if carbon is not None and nitrogen is not None else None
            if distance is None or not 1.0 <= distance <= 1.8:
                breaks.add(right)
                descriptions.append({"chain": chain, "left": asdict(left), "right": asdict(right), "cn_angstrom": distance})
    atom_lines = {int(line[6:11]): line for line in retained}
    serial_map = {serial: serial for serial in atom_lines}
    output, previous, terminated = [], None, False
    for line in text.splitlines(keepends=True):
        if line.startswith(("ATOM  ", "HETATM")):
            serial = int(line[6:11])
            if serial not in atom_lines:
                continue
            residue = residue_key(line)
            if residue != previous:
                if residue in breaks and previous is not None and previous.chain == residue.chain and not terminated:
                    output.append("TER\n")
                previous = residue
                terminated = False
            output.append(atom_lines[serial])
        elif line.startswith("ANISOU"):
            if int(line[6:11]) in atom_lines:
                output.append(line)
        elif line.startswith("CONECT"):
            rewritten = update_conect(line, serial_map)
            if rewritten:
                output.append(rewritten)
        else:
            output.append(line)
            if line.startswith("TER"):
                terminated = True
    return "".join(output).encode(), {"native_breaks": descriptions, "water_atoms_removed": dropped_water_atoms,
        "hydrogens_removed": dropped_hydrogens, "alternative_conformer_atoms_removed": dropped_altloc_atoms,
        "conformer_policy": "blank and A only; reject if any observed residue disappears or selected context is incomplete"}


def masked_pdb(before, generated):
    source_lines = before.decode().splitlines(keepends=True)
    kept_serials = {int(line[6:11]) for line in source_lines if line.startswith(("ATOM  ", "HETATM")) and residue_key(line) not in generated}
    output = []
    for line in source_lines:
        if line.startswith(("ATOM  ", "HETATM")) and residue_key(line) in generated:
            continue
        if line.startswith("ANISOU") and int(line[6:11]) not in kept_serials:
            continue
        if line.startswith("CONECT"):
            line = update_conect(line, {serial: serial for serial in kept_serials})
            if line is None:
                continue
        output.append(line)
    return "".join(output).encode()


def make_intact_request(before, old_case):
    atoms, names, links = _parse_pdb_text(before.decode())
    by_chain = {}
    for identity, name in names.items():
        if name not in CANONICAL_HEAVY_ATOMS:
            raise ValueError("noncanonical residue in intact request")
        by_chain.setdefault(identity.chain, []).append(identity)
    gap = old_case["gap"]
    generated = tuple(ResidueIdentity(**record) for record in gap["generated_residues"])
    left, right = ResidueIdentity(**gap["left_anchor"]), ResidueIdentity(**gap["right_anchor"])
    target_rows = by_chain[gap["chain"]]
    start = target_rows.index(generated[0])
    stop = start + len(generated)
    if tuple(target_rows[start:stop]) != generated or target_rows[start - 1] != left or target_rows[stop] != right:
        raise ValueError("original gap is not the same anchored interval in the full source")
    generated_set = set(generated)
    if any(ResidueIdentity(link.atom1.chain, link.atom1.residue_number, link.atom1.insertion_code) in generated_set
           or ResidueIdentity(link.atom2.chain, link.atom2.residue_number, link.atom2.insertion_code) in generated_set for link in links):
        raise ValueError("explicit source bond touches the proposed test gap")
    masked = masked_pdb(before, generated_set)
    masked_atoms, _, retained_links = _parse_pdb_text(masked.decode())
    expected = tuple(atom for residue in generated for atom in canonical_heavy_atom_identities(residue, names[residue]))
    if set(atoms) - set(masked_atoms) != set(expected) or any(atoms[atom].coordinates_angstrom.tolist() != masked_atoms[atom].coordinates_angstrom.tolist() for atom in masked_atoms):
        raise ValueError("mask changes more than the exact declared generated atoms")
    reverse = {value: key for key, value in _CANONICAL_ONE_TO_THREE.items()}
    request = DiffusionRequest(schema_version=DIFFUSION_SCHEMA_VERSION,
        normalized_pdb=ArtifactReference("input/normalized.pdb", hashlib.sha256(masked).hexdigest()),
        target_sequences=tuple(TargetSequence(chain, "".join(reverse[names[residue]] for residue in residues)) for chain, residues in by_chain.items()),
        sequence_placements=tuple(SequencePlacement(chain, len(residues),
            tuple(index for index, residue in enumerate(residues) if residue not in generated_set),
            tuple(residue for residue in residues if residue not in generated_set)) for chain, residues in by_chain.items()),
        gaps=(GapRegion(gap["chain"], TargetInterval(start, stop), left, right, generated, (left, *generated, right)),),
        fixed_atoms=tuple(masked_atoms), generated_atoms=expected, retained_explicit_links=tuple(sorted(retained_links, key=lambda link: (link.atom1, link.atom2, link.source))),
        candidate_count=1, seeds=(7,), backend_options=(BackendOption("profile", "protenix-v1-cuda"),))
    request = select_protein_context(request, masked, ProteinContextPolicy(name="intact-native-segments-v1",
        target_flanks=8, same_chain_spatial=True, partner_mode="local"))
    validate_context_capability(request, "protenix")
    admission = assess_diffusion_scope(request, masked)
    unexpected = set(admission.reasons) - {"intact-native-segments-research-only", "unsupported-gap-length"}
    if unexpected:
        raise ValueError("unsupported intact scope: " + ", ".join(sorted(unexpected)))
    return request, masked


def verify_engine_templates(workspace, request):
    path = ROOT / "deploy/protenix-v1/build-template-input.py"
    spec = importlib.util.spec_from_file_location("intact_input_preflight", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = workspace / "preflight-features"
    module.build_input(workspace / "request.json", output)
    for index, entity in enumerate(sampling_entities(request)):
        template = json.loads((output / f"template-{index}.json").read_text())[0]
        structure = gemmi.make_structure_from_block(gemmi.cif.read_string(template["mmcif"]).sole_block())
        actual = {(str(residue.seqid.num), residue.seqid.icode.strip()) for chain in structure[0] for residue in chain}
        expected = {(residue.residue_number, residue.insertion_code) for residue in entity.placement.observed_residues}
        if actual != expected:
            raise ValueError("engine template dropped native observed segments")


def freeze(args):
    if args.output.exists() or args.manifest.exists() or args.visual_output.exists():
        raise ValueError("intact recheck destinations must be new")
    args.output.mkdir(parents=True)
    args.visual_output.mkdir()
    review = json.loads((args.review / "manifest.json").read_text())
    original_cases = [case for case in review["cases"] if case["seed"] == 7]
    inventory = {row["protein"]: row for row in inspect_sources(args.review)}
    screening, included, excluded = [], [], []
    for protein, info in inventory.items():
        cases = [case for case in original_cases if case["protein"] == protein]
        source = args.review / protein / "deposited_source.cif"
        root = args.output / "sources" / protein
        root.mkdir(parents=True)
        visual = args.visual_output / protein
        visual.mkdir()
        shutil.copyfile(source, root / "deposited_source.cif")
        shutil.copyfile(source, visual / "deposited_source.cif")
        reasons = []
        if info["models"] != 1:
            reasons.append("multiple-models")
        if info["noncanonical_residues"]:
            reasons.append("noncanonical-residues-retained:" + ",".join(info["noncanonical_residues"]))
        if info["nonwater_heterogens"]:
            reasons.append("unsupported-nonwater-chemistry-retained:" + ",".join(info["nonwater_heterogens"]))
        prepared, preparation = None, {}
        if not reasons:
            try:
                normalized = normalize_structure(source, root / "full-normalized.pdb")
                if any(old != new for old, new in normalized.chain_map.items()):
                    raise ValueError("full-source chain renaming requires explicit old-gap remapping")
                sanitized = sanitize_protein_hetatm(str(normalized.pdb_path))
                prepared, preparation = prepare_intact_pdb(Path(sanitized).read_text())
                _, names, _ = _parse_pdb_text(prepared.decode())
                actual_counts = dict(Counter(residue.chain for residue in names))
                if actual_counts != info["protein_chains"]:
                    raise ValueError("intact normalization/conformer selection lost observed residues")
                (root / "before-gap.pdb").write_bytes(prepared)
            except (ValueError, RuntimeError) as exc:
                reasons.append(str(exc))
                prepared = None
        screening.append({**info, "status": "eligible-source" if prepared is not None else "unsupported-source",
            "reasons": reasons, "preparation": preparation, "source_sha256": sha(source)})
        for old_case in cases:
            case_id = old_case["case_id"]
            view = visual / f"gap_{old_case['length']:03d}" / "seed_007"
            view.mkdir(parents=True)
            shutil.copyfile(source, view / "01_before_gap.cif")
            structure = gemmi.read_structure(str(source))
            gap = old_case["gap"]
            generated_keys = {(record["residue_number"], record["insertion_code"]) for record in gap["generated_residues"]}
            removed = 0
            chain = structure[0][gap["chain"]]
            for index in range(len(chain) - 1, -1, -1):
                if (str(chain[index].seqid.num), chain[index].seqid.icode.strip()) in generated_keys:
                    del chain[index]
                    removed += 1
            if removed != old_case["length"]:
                raise ValueError(f"{protein}: full CIF mask does not match the original test gap")
            structure.make_mmcif_document().write_file(str(view / "02_gapped_input.cif"))
            record = {"case_id": case_id, "source_id": protein, "length": old_case["length"], "seed": 7,
                "split": "recheck", "arms": ["intact-local"], "original_gap": gap,
                "original_geometry_passed": old_case["geometry_passed"], "visual_directory": view.relative_to(args.visual_output).as_posix()}
            case_reasons = list(reasons)
            if prepared is not None:
                (view / "01_before_gap.pdb").write_bytes(prepared)
                generated_residues = {ResidueIdentity(**item) for item in gap["generated_residues"]}
                (view / "02_gapped_input.pdb").write_bytes(masked_pdb(prepared, generated_residues))
                try:
                    request, masked = make_intact_request(prepared, old_case)
                    workspace = args.output / "cases" / case_id
                    (workspace / "input").mkdir(parents=True)
                    (workspace / "input/normalized.pdb").write_bytes(masked)
                    (workspace / "reference.pdb").write_bytes(prepared)
                    (workspace / "request.json").write_text(request.to_json())
                    verify_engine_templates(workspace, request)
                    record.update(status="eligible", full_source_residue_count=info["protein_residues"],
                        engine_context_residue_count=sum(span.stop - span.start for span in request.protein_context.spans),
                        conditioned_chains=sorted({item.atom.chain for item in request.protein_context.fixed_conditioning}),
                        sampling_entities=[{"engine_chain": entity.engine_chain, "source_chain": entity.target.chain, "residue_count": len(entity.residues)} for entity in sampling_entities(request)],
                        preserved_only_atom_count=len(request.protein_context.preserved_only),
                        artifacts={path.relative_to(workspace).as_posix(): sha(path) for path in workspace.rglob("*") if path.is_file()})
                    included.append(record)
                except (ValueError, RuntimeError) as exc:
                    case_reasons.append(str(exc))
            if case_reasons:
                record.update(status="unsupported", reasons=case_reasons)
                excluded.append(record)
            (view / "case.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
            (view / "README.md").write_text(f"# {protein}, gap {old_case['length']}, seed 7\n\n"
                f"Status: {record['status']}\n\nAll deposited chains and observed coordinate residues remain in the CIF pair. Only the original test gap is deleted.\n\n"
                f"Target chain: {gap['chain']}; removed: {', '.join(item['residue_number'] + item['insertion_code'] for item in gap['generated_residues'])}.\n\n"
                + ("Unsupported reasons: " + "; ".join(case_reasons) + "\n" if case_reasons else
                   "PDB pair: explicit solvent-free, heavy-atom blank/A conformer preparation; every observed protein residue and chain retained. Native breaks marked with TER, never cropped or joined into fake peptides.\n"))
    paths = ("scripts/materialize_intact_recheck.py", "src/dvbfixer/model/diffusion/protein_context.py", "src/dvbfixer/model/diffusion/scope.py")
    manifest = {"status": "frozen-before-a100-calibration-inference", "study": "intact-source-local-context-recheck-v1", "no_replacement": True,
        "scope": "all deposited observed protein chains/segments preserved; solvent-free canonical-only engine admission; unsupported chemistry remains visible and excluded explicitly",
        "input_review_manifest_sha256": sha(args.review / "manifest.json"), "screening": screening, "cases": included, "excluded_cases": excluded,
        "code_sha256": {relative: sha(ROOT / relative) for relative in paths}, "seed_policy": "seed7 for each of47 original structural masks; no new gap positions",
        "limits": {"steps": 200, "timeout_seconds": 3600, "engine_context_budget": 512}, "adaptive_contact_gate": {},
        "leakage": {"reference_use": "offline scoring only", "cohort_role": "repeated development examples, not new holdout"},
        "promotion": False, "invariants": ["no protein residue cropping", "only declared gap atoms deleted", "all background observed coordinates fixed", "native breaks distinct from test gap"]}
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (args.visual_output / "README.md").write_text("# Intact-source gap recheck\n\n"
        "All ten original deposited sources are preserved. 01_before_gap.cif and 02_gapped_input.cif retain the full complex, including unsupported chemistry.\n\n"
        "Eligible PDB inputs contain every observed protein chain/residue; only waters, hydrogens and alternate conformers are removed explicitly. Local engine context is selected around gap anchors without deleting the other coordinates.\n\n"
        f"Original structural masks: {len(original_cases)}; eligible cases: {len(included)}; explicitly unsupported: {len(excluded)}. Seed7 only, original gap positions. Results are added after generation and rigid local relaxation. Unsupported cases are not replaced.\n")
    print(json.dumps({"sources": len(screening), "original_masks": len(original_cases), "eligible_cases": len(included), "unsupported_cases": len(excluded),
        "manifest_sha256": sha(args.manifest)}, indent=2))


def inspect_sources(review):
    rows = []
    for directory in sorted(path for path in review.iterdir() if path.is_dir()):
        source = directory / "deposited_source.cif"
        if not source.exists():
            continue
        structure = gemmi.read_structure(str(source))
        chains, incomplete, noncanonical, heterogens = {}, [], [], Counter()
        for chain in structure[0]:
            count = 0
            for residue in chain:
                if residue.is_water():
                    continue
                expected = CANONICAL_HEAVY_ATOMS.get(residue.name)
                if expected is None:
                    if gemmi.find_tabulated_residue(residue.name).is_amino_acid():
                        noncanonical.append(f"{chain.name}/{residue.name}{residue.seqid}")
                        count += 1
                    else:
                        heterogens[residue.name] += 1
                    continue
                count += 1
                names = {atom.name for atom in residue if atom.altloc in {"\x00", " ", "A"}}
                if not set(expected) <= names:
                    incomplete.append({"chain": chain.name, "residue": str(residue.seqid), "name": residue.name, "missing": sorted(set(expected) - names)})
            if count:
                chains[chain.name] = count
        rows.append({"protein": directory.name, "models": len(structure), "protein_chains": chains,
            "protein_residues": sum(chains.values()), "incomplete_residues": incomplete,
            "noncanonical_residues": noncanonical, "nonwater_heterogens": dict(heterogens)})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("inspect", "freeze"), default="inspect")
    parser.add_argument("--review", type=Path, default=ROOT / "gap_visual_review")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--visual-output", type=Path)
    args = parser.parse_args()
    if args.action == "freeze":
        if not all((args.output, args.manifest, args.visual_output)):
            parser.error("freeze requires --output, --manifest and --visual-output")
        freeze(args)
    else:
        print(json.dumps(inspect_sources(args.review), indent=2))


if __name__ == "__main__":
    main()
