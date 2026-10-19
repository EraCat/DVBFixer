#!/usr/bin/env python3
"""Lock an expanded, nonredundant candidate pool for clean full-protein tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

from build_diffusion_confirmatory_cohort import (
    ENTITY_QUERY,
    GRAPHQL_URL,
    SEARCH_URL,
    post_json,
    search_request,
)

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(args):
    if args.output.exists() or args.manifest.exists() or args.protocol.exists():
        raise ValueError("clean-protein pool destinations must be new")
    args.output.mkdir(parents=True)
    protocol = {"status": "locked-before-source-screening-and-inference", "pool_limit": 200,
        "selected_source_limit": 20, "release_window": ["2026-01-01", "2026-10-15"],
        "query": "protein entity80..300, resolution<=2.5A, nonpolymer entity count0, deposited polymer monomer count<=512; first400 RCSB30%-identity representatives",
        "pool_ranking": "sha256(dvbfixer-clean-protein-expanded-v1:<entity>); first200 distinct entries",
        "source_screening": ["one model", "canonical proteins only; waters allowed but explicit solvent-free preparation",
            "no ions, cofactors, ligands, nucleic acids, glycans, caps or noncanonical residues",
            "all deposited chains and residues retained; <=512 protein residues total",
            "every polymer sequence coordinate-complete; no native gaps or incomplete heavy atoms",
            "no alternate conformers; no nonprotein covalent chemistry",
            "full-chain sequence overlap<=30% against prior reviewed proteins and other selected sources"],
        "mask_lengths": [5, 13, 25, 26, 50], "mask_selection": "one first fixed-SHA eligible non-CYS internal window per length; no secondary-structure exclusion; source-native quality checked before inference",
        "seeds": [7], "context": "FULL target and ALL protein partners; no engine-axis cropping; total<=512",
        "inference": "pinned Protenix CUDA, 200 exact reinjections, one cycle", "refinement": "existing rigid v6 CUDA generated-only; no solvent",
        "evaluation": "unchanged geometry and full-background preservation, no reference-RMSD ranking or acceptance",
        "secondary_structure": "deposited helix/sheet annotation overlap recorded; unannotated is not assumed loop",
        "no_outcome_replacement": True, "selection": "screen the locked pool, select first20 eligible mutually nonredundant sources before inference; retain all screening exclusions",
        "training_membership_independently_attested": False, "public_promotion": False}
    args.protocol.write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    query = search_request(*protocol["release_window"], 400)
    query["query"]["nodes"][2]["parameters"]["value"]["to"] = 300
    query["query"]["nodes"][4]["parameters"]["value"] = 2.5
    query["query"]["nodes"].extend([
        {"type": "terminal", "service": "text", "parameters": {"attribute": "rcsb_entry_info.nonpolymer_entity_count", "operator": "equals", "value": 0}},
        {"type": "terminal", "service": "text", "parameters": {"attribute": "rcsb_entry_info.deposited_polymer_monomer_count", "operator": "less_or_equal", "value": 512}},
    ])
    response = post_json(SEARCH_URL, query)
    for name, value in (("search-query", query), ("search-response", response)):
        (args.output / (name + ".json")).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    identifiers = [item if isinstance(item, str) else item["identifier"] for item in response.get("result_set", [])]
    ranked = sorted(identifiers, key=lambda value: hashlib.sha256(("dvbfixer-clean-protein-expanded-v1:" + value).encode()).hexdigest())
    selected, seen = [], set()
    for identifier in ranked:
        entry = identifier.split("_", 1)[0]
        if entry not in seen:
            selected.append(identifier)
            seen.add(entry)
        if len(selected) == protocol["pool_limit"]:
            break
    if not selected:
        raise ValueError("clean-protein metadata query returned no sources")
    by_id = {}
    for offset in range(0, len(selected), 40):
        metadata = post_json(GRAPHQL_URL, {"query": ENTITY_QUERY, "variables": {"ids": selected[offset:offset + 40]}})
        (args.output / f"entity-metadata-{offset:03d}.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        by_id.update({entity["rcsb_id"]: entity for entity in metadata["data"]["polymer_entities"] if entity})
    prior_ids = set()
    for filename in ("cuda-calibration-sources.json", "relaxation-holdout-sources-blosum62.json"):
        prior_ids.update(row["pdb_id"] for row in json.loads((ROOT / "docs/research" / filename).read_text())["cases"])
    cases = []
    for rank, identifier in enumerate(selected):
        record = {"rank": rank, "entity_id": identifier, "pdb_id": identifier.split("_", 1)[0]}
        entity = by_id.get(identifier)
        if entity is None:
            cases.append({**record, "status": "excluded", "reason": "metadata-absent"})
            continue
        date = entity["entry"]["rcsb_accession_info"]["initial_release_date"][:10]
        record.update(release_date=date, sequence="".join(entity["entity_poly"]["pdbx_seq_one_letter_code_can"].split()),
            target_auth_chain=min(entity["polymer_entity_instances"], key=lambda row: row["rcsb_id"])["rcsb_polymer_entity_instance_container_identifiers"]["auth_asym_id"])
        if not protocol["release_window"][0] <= date <= protocol["release_window"][1]:
            cases.append({**record, "status": "excluded", "reason": "outside-release-window"})
            continue
        if record["pdb_id"] in prior_ids:
            cases.append({**record, "status": "excluded", "reason": "previously-screened-entry"})
            continue
        request = Request(f"https://files.rcsb.org/download/{record['pdb_id']}.cif", headers={"User-Agent": "dvbfixer-clean-protein-expanded/1"})
        for attempt in range(3):
            try:
                with urlopen(request, timeout=120) as stream:
                    data = stream.read()
                path = args.output / (record["pdb_id"] + ".cif")
                path.write_bytes(data)
                record.update(status="downloaded", source_sha256=sha(path))
                break
            except OSError as exc:
                if attempt == 2:
                    record.update(status="download-error", reason=str(exc))
                else:
                    time.sleep(2 ** attempt)
        cases.append(record)
        print(json.dumps({"pdb_id": record["pdb_id"], "status": record["status"], "completed": len(cases), "pool": len(selected)}), flush=True)
    manifest = {"status": "clean-protein-source-pool-locked-before-materialization", "protocol_sha256": sha(args.protocol),
        "protocol": protocol, "cases": cases,
        "artifacts": {path.name: sha(path) for path in args.output.iterdir() if path.is_file()}}
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"pool_sources": len(cases), "downloaded": sum(row["status"] == "downloaded" for row in cases), "manifest_sha256": sha(args.manifest)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "manifest", "protocol"):
        parser.add_argument("--" + name, type=Path, required=True)
    build(parser.parse_args())


if __name__ == "__main__":
    main()
