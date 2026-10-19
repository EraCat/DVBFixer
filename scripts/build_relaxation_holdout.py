#!/usr/bin/env python3
"""Lock new post-August sources, excluding development-entry/sequence overlap."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from Bio.Align import PairwiseAligner, substitution_matrices
from build_diffusion_confirmatory_cohort import (
    ENTITY_QUERY,
    GRAPHQL_URL,
    SEARCH_URL,
    post_json,
    search_request,
)


def sequence_identity(first, second):
    aligner = PairwiseAligner(mode="global", substitution_matrix=substitution_matrices.load("BLOSUM62"), open_gap_score=-10, extend_gap_score=-0.5)
    alignment = aligner.align(first, second)[0]
    matches = sum(first[i] == second[j] for i, j in zip(*alignment.indices) if i >= 0 and j >= 0)
    return matches / min(len(first), len(second))


def build(args):
    if args.output.exists() or args.manifest.exists():
        raise ValueError("holdout source destinations must be new")
    args.output.mkdir(parents=True)
    old = json.loads(args.development_sources.read_text())
    old_ids = {case["pdb_id"] for case in old["cases"]}
    old_sequences = [case["sequence"] for case in old["cases"] if case.get("sequence")]
    query = search_request("2026-09-01", "2026-10-15", 100)
    query["query"]["nodes"][2]["parameters"]["value"]["to"] = 250
    query["query"]["nodes"][4]["parameters"]["value"] = 2.5
    response = json.loads((args.locked_metadata / "search-response.json").read_text()) if args.locked_metadata else post_json(SEARCH_URL, query)
    for name, value in (("search-query", query), ("search-response", response)):
        (args.output / (name + ".json")).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    identifiers = [item if isinstance(item, str) else item["identifier"] for item in response.get("result_set", [])]
    ranked = sorted(identifiers, key=lambda value: hashlib.sha256(("dvbfixer-relaxation-holdout-v1:" + value).encode()).hexdigest())
    selected, seen = [], set()
    for identifier in ranked:
        entry = identifier.split("_", 1)[0]
        if entry not in seen:
            selected.append(identifier)
            seen.add(entry)
        if len(selected) == 24:
            break
    if not selected:
        raise ValueError("holdout metadata window yielded no sources")
    metadata = json.loads((args.locked_metadata / "entity-metadata.json").read_text()) if args.locked_metadata else post_json(GRAPHQL_URL, {"query": ENTITY_QUERY, "variables": {"ids": selected}})
    (args.output / "entity-metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    by_id = {entity["rcsb_id"]: entity for entity in metadata["data"]["polymer_entities"] if entity}
    cases = []
    for identifier in selected:
        record = {"entity_id": identifier, "pdb_id": identifier.split("_", 1)[0]}
        entity = by_id.get(identifier)
        if entity is None:
            cases.append({**record, "status": "unsupported", "reason": "metadata-absent"})
            continue
        date = entity["entry"]["rcsb_accession_info"]["initial_release_date"][:10]
        sequence = "".join(entity["entity_poly"]["pdbx_seq_one_letter_code_can"].split())
        record.update(release_date=date, sequence=sequence)
        if not "2026-09-01" <= date <= "2026-10-15":
            raise ValueError("source release date violates holdout window")
        if set(sequence) - set("ACDEFGHIKLMNPQRSTVWY"):
            cases.append({**record, "status": "unsupported", "reason": "noncanonical-polymer-sequence"})
            continue
        identity = max((sequence_identity(sequence, other) for other in old_sequences if not set(other) - set("ACDEFGHIKLMNPQRSTVWY")), default=0)
        record["max_development_sequence_identity_over_shorter_length"] = identity
        if record["pdb_id"] in old_ids or identity > 0.30:
            cases.append({**record, "status": "unsupported", "reason": "development-entry-or-sequence-overlap"})
            continue
        instance = min(entity["polymer_entity_instances"], key=lambda item: item["rcsb_id"])
        record["target_auth_chain"] = instance["rcsb_polymer_entity_instance_container_identifiers"]["auth_asym_id"]
        request = Request(f"https://files.rcsb.org/download/{record['pdb_id']}.cif", headers={"User-Agent": "dvbfixer-relaxation-holdout/1"})
        try:
            with urlopen(request, timeout=120) as stream:
                data = stream.read()
            (args.output / (record["pdb_id"] + ".cif")).write_bytes(data)
            record.update(status="metadata-eligible", source_sha256=hashlib.sha256(data).hexdigest())
        except OSError as exc:
            record.update(status="unsupported", reason="download-failed: " + str(exc))
        cases.append(record)
    manifest = {"schema_version": 1, "status": "sources-locked-before-holdout-inference", "no_replacement": True,
        "development_sources_sha256": hashlib.sha256(args.development_sources.read_bytes()).hexdigest(),
        "selection": "first24 distinct entries by fixed SHA rank from first100 30%-grouped representatives; 2026-09-01..2026-10-15; no replacement after overlap/completeness exclusions",
        "sequence_exclusion": "global BLOSUM62 affine alignment (open=-10,extend=-0.5); identical pairs / shorter full sequence length >0.30 against prior24 canonical development-source sequences",
        "screening_revision": "BLOSUM62-v2, before any holdout inference; first simple-match scoring screening archived separately",
        "cases": cases, "seeds": [7], "arms": {"short": ["static-local"], "long": ["full-raw"]},
        "limits": {"steps": 200, "timeout_seconds": 3600, "residue_budget": 512},
        "adaptive_contact_gate": {}, "promotion": "research validation only; no public promotion",
        "leakage": {"temporal_holdout": "post-August 2026 releases; disjoint entries and <=30% sequence identity to development24",
            "training_membership": "not-independently-attested"},
        "artifacts": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in args.output.iterdir() if path.is_file()}}
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"locked_sources": len(cases), "metadata_eligible": sum(case["status"] == "metadata-eligible" for case in cases)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "manifest", "development-sources"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--locked-metadata", type=Path)
    build(parser.parse_args())


if __name__ == "__main__":
    main()
