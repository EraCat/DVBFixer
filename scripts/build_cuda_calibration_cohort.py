#!/usr/bin/env python3
"""Freeze prospective 2026 RCSB representatives and an A100 calibration protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from build_diffusion_confirmatory_cohort import (
    ENTITY_QUERY,
    GRAPHQL_URL,
    SEARCH_URL,
    post_json,
    search_request,
)


def build(output: Path, manifest_path: Path):
    if output.exists() or manifest_path.exists():
        raise ValueError("prospective calibration destinations must be new")
    output.mkdir(parents=True)
    query = search_request("2026-01-01", "2026-08-31", 100)
    query["query"]["nodes"][2]["parameters"]["value"]["to"] = 250
    query["query"]["nodes"][4]["parameters"]["value"] = 2.5
    response = post_json(SEARCH_URL, query)
    (output / "search-query.json").write_text(json.dumps(query, indent=2, sort_keys=True) + "\n")
    (output / "search-response.json").write_text(json.dumps(response, indent=2, sort_keys=True) + "\n")
    entities = [item if isinstance(item, str) else item["identifier"] for item in response.get("result_set", [])]
    ranked = sorted(entities, key=lambda identifier: hashlib.sha256(("dvbfixer-cuda-calibration-2026-v1:" + identifier).encode()).hexdigest())
    selected = []
    entries = set()
    for identifier in ranked:
        pdb_id = identifier.split("_", 1)[0]
        if pdb_id in entries:
            continue
        entries.add(pdb_id)
        selected.append(identifier)
        if len(selected) == 24:
            break
    if not selected:
        raise ValueError("the preregistered 2026 metadata window returned no candidates")
    metadata = post_json(GRAPHQL_URL, {"query": ENTITY_QUERY, "variables": {"ids": selected}})
    (output / "entity-metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    by_id = {entity["rcsb_id"]: entity for entity in metadata["data"]["polymer_entities"] if entity}
    cases = []
    for identifier in selected:
        entity = by_id.get(identifier)
        record = {"entity_id": identifier, "pdb_id": identifier.split("_", 1)[0]}
        if entity is None:
            cases.append({**record, "status": "unsupported", "reason": "metadata-absent"})
            continue
        date = entity["entry"]["rcsb_accession_info"]["initial_release_date"][:10]
        if not "2026-01-01" <= date <= "2026-08-31":
            raise ValueError("prospective source release is outside the frozen metadata window")
        instances = entity["polymer_entity_instances"]
        instance = min(instances, key=lambda item: item["rcsb_id"])
        target_chain = instance["rcsb_polymer_entity_instance_container_identifiers"]["auth_asym_id"]
        record.update(release_date=date, target_auth_chain=target_chain,
                      sequence="".join(entity["entity_poly"]["pdbx_seq_one_letter_code_can"].split()), status="metadata-eligible")
        source = output / (record["pdb_id"] + ".cif")
        request = Request(f"https://files.rcsb.org/download/{record['pdb_id']}.cif", headers={"User-Agent": "dvbfixer-cuda-calibration/1"})
        with urlopen(request, timeout=120) as stream:
            source.write_bytes(stream.read())
        record["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        cases.append(record)
    manifest = {"schema_version": 1, "status": "metadata-and-sources-locked-before-calibration-inference", "no_replacement": True,
        "selection": "2026 release window; RCSB 30%-identity grouped representatives; sha256 rank; first 24 distinct entries",
        "cases": cases, "seeds": [7, 19], "source_scope": "declared-target-and-first-canonical-partner-subcomplex",
        "strata": {"short": [5], "long": [13, 25, 26, 50]},
        "arms": {"short": ["static-local", "adaptive-monotonic", "adaptive-contact-gated"], "long": ["full-raw"]},
        "limits": {"steps": 200, "timeout_seconds": 3600, "residue_budget": 512, "adaptive_rounds": 2},
        "adaptive_contact_gate": {"distance_angstrom": 4.0, "minimum_new_contact_residues": 2, "minimum_supporting_backbone_atoms": 2},
        "holdout": "ranked entry index even=calibration, odd=validation; no validation-driven parameter changes",
        "promotion": "no public scope change from this bounded study; larger independent review required",
        "leakage": {"temporal_holdout": "2026 sources newer than frozen 2025 source/checkpoint releases", "training_membership": "not-independently-attested"},
        "artifacts": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in output.iterdir() if path.is_file()}}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"metadata_source_count": len(cases), "manifest": str(manifest_path)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    build(args.output, args.manifest)


if __name__ == "__main__":
    main()
