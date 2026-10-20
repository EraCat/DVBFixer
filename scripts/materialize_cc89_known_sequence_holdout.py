#!/usr/bin/env python3
"""Freeze known-sequence gap/Homology inputs without withheld template atoms."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

from build_antibody_holdout_sources import CDRS
from materialize_clean_protein_cohort import REVERSE
from run_a100_relaxation import sha, verify_inventory

from dvbfixer.homology_plan import (
    build_mosaic_diffusion_request,
    materialize_template_plan,
)
from dvbfixer.model.diffusion.contract import (
    ArtifactReference,
    BackendOption,
    DiffusionRequest,
    ProteinContextPolicy,
)
from dvbfixer.model.diffusion.protein_context import (
    ProteinContextError,
    select_protein_context,
    validate_context_capability,
)
from dvbfixer.model.diffusion.validate import (
    ValidationThresholds,
    _load_structure,
    _validate_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
SEEDS = (7, 19)


def protein_rows(data):
    rows, lines = {}, []
    for line in data.decode().splitlines(keepends=True):
        if not line.startswith("ATOM  "):
            continue
        name = line[17:20].strip()
        if name not in REVERSE:
            raise ValueError("holdout inputs must be canonical proteins")
        key = (line[22:26].strip(), line[26].strip())
        chain = rows.setdefault(line[21], {})
        chain.setdefault(key, name)
        lines.append(line)
    return rows, lines


def atom_records(data):
    return {(line[21], line[22:26].strip(), line[26].strip(), line[12:16].strip()):
            (line[17:20].strip(), line[30:54]) for line in data.decode().splitlines() if line.startswith("ATOM  ")}


def assert_mask_only(reference, masked, removed_residues):
    before, after = atom_records(reference), atom_records(masked)
    expected = {atom: value for atom, value in before.items() if atom[:3] not in removed_residues}
    if after != expected:
        raise ValueError("masked input differs from exact source-minus-declared-gap atoms")


def choose_start(sequence, length, key, permitted=None):
    starts = [index for index in range(1, len(sequence) - length)
              if "C" not in sequence[index:index + length]
              and (permitted is None or set(range(index, index + length)) <= permitted)]
    if not starts:
        return None
    return min(starts, key=lambda index: hashlib.sha256(f"known-sequence-holdout-v1:{key}:{length}:{index}".encode()).hexdigest())


def write_case(directory, source, spec, *, atom37_terminals=False):
    rows, lines = protein_rows(source)
    sequences = {chain: "".join(REVERSE[name] for name in residues.values()) for chain, residues in rows.items()}
    chain, start, length = spec["chain"], spec["start"], spec["length"]
    original_keys = list(rows[chain])
    removed = {(chain, *key) for key in original_keys[start:start + length]}
    masked = b"".join(line.encode() for line in lines if (line[21], line[22:26].strip(), line[26].strip()) not in removed) + b"TER\nEND\n"
    assert_mask_only(source, masked, removed)
    template = directory / "masked-template.pdb"
    template.write_bytes(masked)
    templates, groups = [], []
    for source_chain, sequence in sequences.items():
        template_id = "observed-" + source_chain
        observed = sequence[:start] + "-" * length + sequence[start + length:] if source_chain == chain else sequence
        templates.append({"id": template_id, "path": template.resolve().as_posix(), "chain": source_chain, "targetChain": source_chain})
        groups.append({"chainId": source_chain, "rows": [{"id": source_chain, "kind": "target", "sequence": sequence},
            {"id": template_id, "kind": "template", "templateId": template_id, "sequence": observed}],
            "maskModes": {template_id: "all"}, "masks": {}})
    plan = directory / "template-plan.json"
    plan.write_text(json.dumps({"templates": templates, "alignmentGroups": groups}, indent=2, sort_keys=True) + "\n")
    (directory / "target.fasta").write_text("".join(f">{chain_id}\n{sequence}\n" for chain_id, sequence in sequences.items()))
    materialized = directory / "materialized"
    materialize_template_plan(plan, materialized)
    coverage = materialized / "selected_template_mosaic.coverage.json"
    input_path, request_path = build_mosaic_diffusion_request(coverage, list(sequences.items()), materialized,
        seeds=(7,), profile="protpardelle-1c-research")
    request = DiffusionRequest.from_json(request_path.read_text())
    # A separate evaluation-only reference maps every observed source residue to
    # its exact mosaic target ordinal; no alignment or missing-coordinate guess.
    remap = {(c, *key): str(index + 1) for c, residues in rows.items() for index, key in enumerate(residues)}
    reference = "".join(line[:22] + f"{int(remap[(line[21], line[22:26].strip(), line[26].strip())]):4d} " + line[27:]
                        for line in lines).encode() + b"TER\nEND\n"
    (directory / "reference.pdb").write_bytes(reference)
    dense_removed = {(r.chain, r.residue_number, r.insertion_code) for gap in request.gaps for r in gap.generated_residues}
    assert_mask_only(reference, input_path.read_bytes(), dense_removed)
    (directory / "input").mkdir()
    (directory / "input/normalized.pdb").write_bytes(input_path.read_bytes())
    request = replace(request, normalized_pdb=ArtifactReference("input/normalized.pdb", sha(input_path)),
        backend_options=(*request.backend_options, BackendOption("cc89_chain_phase", "neutral-v1")))
    policy = ProteinContextPolicy(name="atom37-terminal-preservation-v1", partner_mode="full") if atom37_terminals else ProteinContextPolicy(partner_mode="full")
    request = select_protein_context(request, input_path.read_bytes(), policy)
    (directory / "requests").mkdir()
    for seed in SEEDS:
        (directory / f"requests/cc89-seed{seed}.json").write_text(replace(request, seeds=(seed,)).to_json())
    summary, _ = _validate_candidate(request, _load_structure(directory, "input/normalized.pdb", sha(input_path)),
        _load_structure(directory, "reference.pdb", sha(directory / "reference.pdb")), ValidationThresholds())
    cc89_reasons = []
    try:
        validate_context_capability(request, "protpardelle")
    except ProteinContextError as exc:
        cc89_reasons.append(str(exc))
    record = {**spec, "status": "eligible" if summary.passed else "source-native-rejected",
        "source_native_validation": asdict(summary), "original_generated_residues": sorted(removed),
        "known_gap_sequence": sequences[chain][start:start + length], "source_observed_sequences": sequences,
        "protein_residue_count": sum(len(s) for s in sequences.values()),
        "protein_chain_count": len(sequences), "fixed_atom_count": len(request.fixed_atoms),
        "preserved_only_atoms": [asdict(atom) for atom in request.protein_context.preserved_only],
        "cc89_eligible": summary.passed and not cc89_reasons, "cc89_unsupported_reasons": cc89_reasons,
        "leakage_audit": {"template_is_source_minus_gap": True, "mosaic_input_is_reference_minus_gap": True,
                          "target_sequences_unchanged": True},
        "identity_mapping": [{"chain": c, "original_residue_number": key[0], "original_insertion_code": key[1],
            "mosaic_residue_number": remap[(c, *key)]} for c, residues in rows.items() for key in residues]}
    # Freeze the expected public Protenix request too, using the same plan path
    # as the public Homology CLI so coverage/request digests remain comparable.
    public_dir = directory / "protenix-materialized"
    public_dir.mkdir()
    public_input, public_request = build_mosaic_diffusion_request(coverage, list(sequences.items()), public_dir,
        seeds=(7,), profile="protenix-v1-cuda")
    public = DiffusionRequest.from_json(public_request.read_text())
    public = select_protein_context(public, public_input.read_bytes(), ProteinContextPolicy(partner_mode="full"))
    (directory / "requests/protenix-seed7.json").write_text(public.to_json())
    return record


def freeze(args):
    if args.output.exists() or args.manifest.exists():
        raise ValueError("holdout cohort and manifest must be new")
    clean = json.loads(args.clean_manifest.read_text())
    antibodies = json.loads(args.antibody_manifest.read_text())
    verify_inventory(args.antibody_sources, antibodies["artifacts"])
    args.output.mkdir(parents=True)
    specs = []
    for original in clean["cases"]:
        if original["length"] != 5:
            continue
        base = args.clean_cohort / "cases" / original["case_id"]
        verify_inventory(base, original["artifacts"])
        reference = (base / "reference.pdb").read_bytes()
        rows, _ = protein_rows(reference)
        chain = original["original_gap"]["chain"]
        sequence = "".join(REVERSE[name] for name in rows[chain].values())
        keys = list(rows[chain])
        first = original["original_gap"]["generated_residues"][0]
        old_start = keys.index((first["residue_number"], first["insertion_code"]))
        for length in (5, 10):
            start = old_start if length == 5 else choose_start(sequence, length, original["source_id"])
            specs.append((reference, {"case_id": f"general-{original['source_id'].lower()}-gap{length}",
                "source_id": original["source_id"], "stratum": "general-protein", "chain": chain, "length": length,
                "start": start, "previously_used_for_cc89_phase_selection": False,
                "prior_protenix_source_study": True, "source_reference_sha256": sha(base / "reference.pdb")}))
    for source in antibodies["cases"]:
        if source["status"] != "source-eligible":
            continue
        reference = (args.antibody_sources / source["pdb_id"] / "reference.pdb").read_bytes()
        for family, cdr, length in antibodies["protocol"]["mask_specs"]:
            types = {"H"} if family == "H" else {"K", "L"}
            eligible = [d for d in source["domains"] if d["chain_type"] in types]
            domain = min(eligible, key=lambda d: (d["chain"], d["start"]))
            sequence = source["observed_sequences"][domain["chain"]]
            low, high = CDRS[cdr]
            permitted = {p["target_index"] for p in domain["positions"] if low <= p["imgt_number"] <= high}
            start = choose_start(sequence, length, f"{source['pdb_id']}:{family}:{cdr}", permitted)
            specs.append((reference, {"case_id": f"antibody-{source['pdb_id'].lower()}-{family}-{cdr.lower()}-gap{length}",
                "source_id": source["pdb_id"], "stratum": "antibody-cdr", "chain": domain["chain"], "length": length,
                "start": start, "cdr": cdr, "imgt_range": [low, high], "antibody_chain_type": family,
                "previously_used_for_cc89_phase_selection": False, "prior_protenix_source_study": False,
                "source_reference_sha256": source["reference_sha256"], "unobserved_terminal_tails": source["unobserved_terminal_tails"]}))
    records = []
    for reference, spec in specs:
        directory = args.output / spec["case_id"]
        directory.mkdir()
        if spec["start"] is None:
            record = {**spec, "status": "mask-unavailable", "cc89_eligible": False,
                "reason": "no internal CYS-free known-coordinate window of the declared length inside the declared region"}
        else:
            record = write_case(directory, reference, spec, atom37_terminals=args.atom37_terminals)
        record["artifacts"] = {p.relative_to(directory).as_posix(): sha(p) for p in sorted(directory.rglob("*")) if p.is_file()}
        records.append(record)
        print(json.dumps({key: record[key] for key in ("case_id", "status", "cc89_eligible")}), flush=True)
    # Public workflow controls are source/stratum-selected, never chosen by a
    # generated candidate: first general monomer, first oligomer, H-CDR1 masks.
    public_controls = []
    for multichain in (False, True):
        candidates = [r for r in records if r["status"] == "eligible" and r["stratum"] == "general-protein" and r["length"] == 5
                      and (r["protein_chain_count"] > 1) == multichain]
        if candidates:
            public_controls.append(candidates[0]["case_id"])
    public_controls.extend(r["case_id"] for r in records if r["status"] == "eligible" and r["stratum"] == "antibody-cdr"
                           and r["antibody_chain_type"] == "H" and r["cdr"] == "CDR1")
    manifest = {"status": "frozen-before-known-sequence-holdout-inference", "no_replacement": True,
        "producer_sha256": sha(Path(__file__).resolve()), "clean_manifest_sha256": sha(args.clean_manifest),
        "antibody_manifest_sha256": sha(args.antibody_manifest), "cases": records,
        "seeds": SEEDS, "cc89_protocol": "neutral-v1, native conditioning, full supported protein context; 500 steps; scale1.2; churn200; fixed sequence; generated-only rigid v6 CUDA refinement",
        "cc89_context_policy": "atom37-terminal-preservation-v1" if args.atom37_terminals else "anchor-shell-v1",
        "supersedes_source_preflight_manifest_sha256": sha(args.supersedes) if args.supersedes else None,
        "terminal_atom_policy": ("OXT only at an observed C terminus is explicitly preserved-only; every canonical atom37 heavy atom remains conditioning; source/output and refinement retain all atoms"
                                 if args.atom37_terminals else "all selected fixed atoms must be represented by the model; incompatible terminal OXT remains unsupported"),
        "modeller_protocol": "public homology CLI; same already-masked template plan; one automodel; no loop refinement; md-level none",
        "public_protenix_workflow_controls": public_controls,
        "reference_policy": "evaluation-only; no reference file is copied into cc89 sampling workspaces",
        "chemistry_policy": "preserve all observed protein atoms including OXT; unsupported cc89 atom37 inputs remain unsupported without silent stripping",
        "training_membership_independently_attested": False,
        "interpretation": "prospective method-holdout for cc89 repair, not independent of the earlier Protenix source study; old antibody structures may overlap training",
        "public_promotion": False}
    with args.manifest.open("x") as stream:
        stream.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"planned_masks": len(records), "source_native_eligible_masks": sum(r["status"] == "eligible" for r in records),
        "cc89_eligible_masks": sum(r["cc89_eligible"] for r in records), "public_protenix_controls": public_controls}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("clean-manifest", "clean-cohort", "antibody-manifest", "antibody-sources", "output", "manifest"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--atom37-terminals", action="store_true", help="Explicit research policy: preserve observed terminal OXT outside atom37 conditioning, without removing it from source/output")
    parser.add_argument("--supersedes", type=Path, help="Prior source-only preflight manifest, before any inference")
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    freeze(args)


if __name__ == "__main__":
    main()
