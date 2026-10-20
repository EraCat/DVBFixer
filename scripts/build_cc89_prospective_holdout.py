#!/usr/bin/env python3
"""Freeze new source-disjoint cc89 inputs before any corrected-mode inference."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen

import gemmi
import run_cc89_known_sequence_holdout as execution
from build_antibody_holdout_sources import CDRS, antibody_domains, inspect_observed_protein
from build_diffusion_confirmatory_cohort import (
    ENTITY_QUERY,
    GRAPHQL_URL,
    SEARCH_URL,
    post_json,
    search_request,
)
from materialize_cc89_known_sequence_holdout import choose_start, write_case
from materialize_clean_protein_cohort import sequence_overlap
from materialize_intact_recheck import prepare_intact_pdb

from dvbfixer.ffutils import sanitize_protein_hetatm
from dvbfixer.model.diffusion.contract import BackendOption, DiffusionRequest, ProteinContextPolicy
from dvbfixer.model.diffusion.protein_context import (
    engine_context_view,
    select_protein_context,
    source_context_position_features,
    validate_context_source,
)
from dvbfixer.structure_input import normalize_structure

ROOT = execution.ROOT
HISTORY = (
    "cc89-known-sequence-holdout-v2.json", "clean-protein-expanded-sources.json",
    "cuda-calibration-sources.json", "relaxation-holdout-sources-blosum62.json",
    "known-sequence-antibody-sources-v1.json",
    "cc89-prospective-holdout-v2.json",
)


def dump(path, value):
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def history():
    identifiers, sequences = set(), set()
    for name in HISTORY:
        manifest = json.loads((ROOT / "docs/research" / name).read_text())
        for case in manifest["cases"]:
            identifier = case.get("source_id", case.get("pdb_id"))
            if identifier:
                identifiers.add(identifier.upper())
            if case.get("sequence"):
                sequences.add(case["sequence"])
            sequences.update(case.get("source_observed_sequences", {}).values())
            sequences.update(case.get("observed_sequences", {}).values())
    return identifiers, sequences


def screen(args):
    if args.sources.exists() or args.source_manifest.exists():
        raise ValueError("prospective source destinations must be new")
    args.sources.mkdir(parents=True)
    prior_ids, prior_sequences = history()
    protocol = {
        "status": "fixed-before-source-screening-and-inference",
        "release_windows": {"general-protein": [args.start_date, "2026-10-19"],
                            "antibody-cdr": [args.antibody_start_date, "2026-10-19"]},
        "sequence_identity_grouping": {"general-protein": 30, "antibody-cdr": args.antibody_identity},
        "query_rows_per_stratum": 500, "download_limit_per_stratum": 32,
        "selection": "RCSB identity-group representatives per stratum; SHA256 rank; new distinct source IDs; no outcome replacement; antibody domains reserved for the CDR stratum",
        "maximum_cif_bytes": 10_000_000,
        "criteria": "X-ray <=2.5A; whole canonical protein model <=512 residues; complete heavy atoms; no altlocs, internal breaks or nonwater heterogens; terminal tails disclosed",
        "history_sha256": {name: execution.sha(ROOT / "docs/research" / name) for name in HISTORY},
        "general_sequence_policy": "maximum historical/selected target overlap <=0.30 under existing >=80-residue/80%-coverage local-alignment rule",
        "antibody_sequence_policy": "reject exact previously observed target sequence; framework homology allowed and disclosed; require paired IMGT H and K/L",
        "selected_source_limits": {"general-protein": 4, "antibody-cdr": 2},
        "mask_lengths": [5, 10], "seeds": [7, 19], "no_replacement": True,
        "primary_endpoint": "existing geometry/source-preservation acceptance after unchanged CUDA refinement",
        "reference_rmsd": "secondary only; never a gate or selection criterion",
        "training_membership_independently_attested": False,
        "producer_sha256": execution.sha(Path(__file__).resolve()),
    }
    dump(args.sources / "screening-protocol.json", protocol)
    records = []
    for stratum in ("general-protein", "antibody-cdr"):
        seen = set(prior_ids)
        window = protocol["release_windows"][stratum]
        query = search_request(*window, protocol["query_rows_per_stratum"])
        query["request_options"]["group_by"]["similarity_cutoff"] = protocol["sequence_identity_grouping"][stratum]
        query["query"]["nodes"][2]["parameters"]["value"]["to"] = 250
        query["query"]["nodes"][3]["parameters"]["value"] = ["X-RAY DIFFRACTION"]
        query["query"]["nodes"][4]["parameters"]["value"] = 2.5
        query["query"]["nodes"].append({"type": "terminal", "service": "text", "parameters": {
            "attribute": "rcsb_entry_info.nonpolymer_entity_count", "operator": "equals", "value": 0}})
        if stratum == "antibody-cdr":
            query["query"]["nodes"].append({"type": "terminal", "service": "full_text", "parameters": {"value": "Fab"}})
        dump(args.sources / f"{stratum}-query.json", query)
        response = post_json(SEARCH_URL, query)
        dump(args.sources / f"{stratum}-response.json", response)
        identifiers = [item if isinstance(item, str) else item["identifier"] for item in response.get("result_set", [])]
        ranked = sorted(identifiers, key=lambda item: hashlib.sha256(f"cc89-source-holdout-v1:{stratum}:{item}".encode()).hexdigest())
        selected = []
        for identifier in ranked:
            pdb_id = identifier.split("_", 1)[0].upper()
            if pdb_id not in seen:
                selected.append(identifier)
                seen.add(pdb_id)
            if len(selected) == protocol["download_limit_per_stratum"]:
                break
        dump(args.sources / f"{stratum}-selected.json", selected)
        metadata = post_json(GRAPHQL_URL, {"query": ENTITY_QUERY, "variables": {"ids": selected}}) if selected else {"data": {"polymer_entities": []}}
        dump(args.sources / f"{stratum}-metadata.json", metadata)
        by_id = {entity["rcsb_id"]: entity for entity in metadata["data"]["polymer_entities"] if entity}
        for identifier in selected:
            pdb_id = identifier.split("_", 1)[0].upper()
            directory = args.sources / pdb_id
            directory.mkdir(exist_ok=True)
            record = {"source_id": pdb_id, "entity_id": identifier, "stratum": stratum, "status": "unsupported", "reasons": []}
            try:
                entity = by_id[identifier]
                date = entity["entry"]["rcsb_accession_info"]["initial_release_date"][:10]
                if not window[0] <= date <= window[1]:
                    raise ValueError("source release lies outside the frozen window")
                instance = min(entity["polymer_entity_instances"], key=lambda item: item["rcsb_id"])
                target = instance["rcsb_polymer_entity_instance_container_identifiers"]["auth_asym_id"]
                request = Request(f"https://files.rcsb.org/download/{pdb_id}.cif", headers={"User-Agent": "dvbfixer-cc89-prospective/1"})
                with urlopen(request, timeout=90) as stream:
                    data = stream.read(protocol["maximum_cif_bytes"] + 1)
                if len(data) > protocol["maximum_cif_bytes"]:
                    raise ValueError("source exceeds frozen download bound")
                source = directory / "deposited_source.cif"
                source.write_bytes(data)
                structure = gemmi.read_structure(str(source))
                info = inspect_observed_protein(structure)
                record.update(info, release_date=date, source_sha256=execution.sha(source))
                if info["reasons"]:
                    raise ValueError("source-preflight-rejected")
                normalized = normalize_structure(source, directory / "normalized.pdb")
                reference, preparation = prepare_intact_pdb(Path(sanitize_protein_hetatm(str(normalized.pdb_path))).read_text())
                if preparation["native_breaks"] or preparation["alternative_conformer_atoms_removed"]:
                    raise ValueError("source preparation changed native connectivity or conformers")
                (directory / "reference.pdb").write_bytes(reference)
                sequences = {normalized.chain_map.get(chain, chain): sequence for chain, sequence in info["sequences"].items()}
                target = normalized.chain_map.get(target, target)
                record.update(observed_sequences=sequences, target_chain=target, preparation=preparation,
                    reference_sha256=execution.sha(directory / "reference.pdb"), chain_map=normalized.chain_map)
                domains = antibody_domains(sequences)
                if stratum == "antibody-cdr":
                    if not any(d["chain_type"] == "H" for d in domains) or not any(d["chain_type"] in {"K", "L"} for d in domains):
                        raise ValueError("paired ANARCI H and K/L domains absent")
                    if any(sequences[d["chain"]] in prior_sequences for d in domains):
                        raise ValueError("exact antibody target sequence already used")
                    record["domains"] = domains
                else:
                    if domains:
                        raise ValueError("antibody-source-reserved-for-cdr-stratum")
                    overlap = max((sequence_overlap(sequences[target], previous) for previous in prior_sequences), default=0.0)
                    record["maximum_historical_target_overlap"] = overlap
                    if overlap > 0.30:
                        raise ValueError("general target overlaps historical sequences")
                record["status"] = "source-eligible"
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                record["reasons"].append(str(exc))
            records.append(record)
            print(json.dumps({key: record[key] for key in ("source_id", "stratum", "status", "reasons")}), flush=True)
    dump(args.source_manifest, {"protocol": protocol, "cases": records,
        "artifacts": {p.relative_to(args.sources).as_posix(): execution.sha(p) for p in sorted(args.sources.rglob("*")) if p.is_file()}})


def freeze(args):
    if args.cohort.exists() or args.manifest.exists() or args.protocol.exists():
        raise ValueError("prospective execution destinations must be new")
    pool = json.loads(args.source_manifest.read_text())
    execution.verify_inventory(args.sources, pool["artifacts"])
    args.cohort.mkdir(parents=True)
    cases, selected, general_sequences = [], [], []
    for stratum, limit in pool["protocol"]["selected_source_limits"].items():
        for source in pool["cases"]:
            if source["stratum"] != stratum or source["status"] != "source-eligible":
                continue
            if sum(item["stratum"] == stratum for item in selected) >= limit:
                break
            if stratum == "general-protein":
                sequence = source["observed_sequences"][source["target_chain"]]
                if any(sequence_overlap(sequence, previous) > 0.30 for previous in general_sequences):
                    continue
                general_sequences.append(sequence)
                masks = [(source["target_chain"], length, None, None) for length in (5, 10)]
            else:
                masks = []
                for family, cdr, length in (("H", "CDR1", 5), ("H", "CDR3", 10), ("L", "CDR1", 5), ("L", "CDR3", 5)):
                    domain = min((d for d in source["domains"] if d["chain_type"] in ({"H"} if family == "H" else {"K", "L"})), key=lambda d: (d["chain"], d["start"]))
                    low, high = CDRS[cdr]
                    permitted = {p["target_index"] for p in domain["positions"] if low <= p["imgt_number"] <= high}
                    masks.append((domain["chain"], length, permitted, f"{family}-{cdr.lower()}"))
            selected.append(source)
            for chain, length, permitted, label in masks:
                case_id = f"prospective-{source['source_id'].lower()}-{label + '-' if label else ''}gap{length}"
                start = choose_start(source["observed_sequences"][chain], length, case_id, permitted)
                spec = {"case_id": case_id, "source_id": source["source_id"], "stratum": stratum, "chain": chain,
                    "start": start, "length": length, "release_date": source["release_date"],
                    "source_reference_sha256": source["reference_sha256"]}
                directory = args.cohort / case_id
                directory.mkdir()
                if start is None:
                    record = {**spec, "status": "mask-unavailable", "cc89_eligible": False}
                else:
                    record = write_case(directory, (args.sources / source["source_id"] / "reference.pdb").read_bytes(), spec, atom37_terminals=True)
                    for seed in pool["protocol"]["seeds"]:
                        path = directory / f"requests/cc89-seed{seed}.json"
                        request = DiffusionRequest.from_json(path.read_text())
                        request = select_protein_context(replace(request, protein_context=None), (directory / "input/normalized.pdb").read_bytes(),
                            ProteinContextPolicy(name="atom37-terminal-preservation-v1", target_flanks=8, same_chain_spatial=True, partner_mode="local"))
                        request = replace(request, backend_options=(*request.backend_options, BackendOption("cc89_position_features", "source-physical-v1")))
                        # This is the explicit private source-position mode, whose
                        # proxy spans are intentionally outside public admission.
                        validate_context_source(request, (directory / "input/normalized.pdb").read_bytes())
                        positions, _ = source_context_position_features(request)
                        view = engine_context_view(request)
                        if len(positions) > 512 or len(positions) != sum(len(target.sequence) for target in view.request.target_sequences):
                            raise ValueError("research context does not fit the frozen engine axis")
                        path.write_text(request.to_json())
                    record["local_axis_residues"] = sum(span.stop - span.start for span in request.protein_context.spans)
                record["artifacts"] = {p.relative_to(directory).as_posix(): execution.sha(p) for p in sorted(directory.rglob("*")) if p.is_file()}
                cases.append(record)
                print(json.dumps({key: record[key] for key in ("case_id", "status", "cc89_eligible")}), flush=True)
    manifest = {"status": "frozen-before-known-sequence-holdout-inference", "cases": cases, "seeds": [7, 19],
        "no_replacement": True, "public_protenix_workflow_controls": [], "source_manifest_sha256": execution.sha(args.source_manifest),
        "producer_sha256": execution.sha(Path(__file__).resolve()), "selected_sources": [s["source_id"] for s in selected],
        "interpretation": "prospective source-disjoint test of the frozen corrected mode; geometry/source preservation primary; no parameter tuning or reference selection; antibody framework homology allowed; training membership not independently attested"}
    dump(args.manifest, manifest)
    execution.freeze(SimpleNamespace(cohort=args.cohort, manifest=args.manifest, protocol=args.protocol, supersedes=None))
    protocol = json.loads(args.protocol.read_text())
    protocol["jobs"]["modeller"] = []
    protocol["raw_parameters"]["position_feature_policy"] = "source-physical-v1"
    protocol["code_sha256"]["scripts/build_cc89_prospective_holdout.py"] = execution.sha(Path(__file__).resolve())
    protocol["comparison"] = manifest["interpretation"]
    args.protocol.write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"sources": manifest["selected_sources"], "jobs": {stage: len(jobs) for stage, jobs in protocol["jobs"].items()}}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("screen", "freeze"):
        command = commands.add_parser(action)
        names = ("sources", "source-manifest") if action == "screen" else ("sources", "source-manifest", "cohort", "manifest", "protocol")
        for name in names:
            command.add_argument("--" + name, type=Path, required=True)
        if action == "screen":
            command.add_argument("--start-date", default="2026-09-01")
            command.add_argument("--antibody-start-date", default="2026-09-01")
            command.add_argument("--antibody-identity", type=int, choices=(30, 50, 70, 90, 95, 100), default=30)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    {"screen": screen, "freeze": freeze}[args.action](args)


if __name__ == "__main__":
    main()
