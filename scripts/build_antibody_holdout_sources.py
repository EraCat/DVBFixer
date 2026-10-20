#!/usr/bin/env python3
"""Screen a fixed public crystal-structure pool for known-sequence CDR masking.

No structure is selected using a reconstruction outcome. Whole deposited protein
models are retained; only water is excluded by the solvent-free preparation.
Unobserved terminal tails are disclosed, never generated or used as references.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

import gemmi
from materialize_clean_protein_cohort import inspect_clean_structure
from materialize_intact_recheck import prepare_intact_pdb
from run_a100_relaxation import sha

from dvbfixer.ffutils import sanitize_protein_hetatm
from dvbfixer.structure_input import normalize_structure

IDS = ("1FVC", "1FVE", "1HIL", "1MIM", "2FBJ", "1IGF", "1REI", "1BVL", "1D5B", "1FVD", "1NQB", "1QOK")
CDRS = {"CDR1": (27, 38), "CDR2": (56, 65), "CDR3": (105, 117)}


def inspect_observed_protein(structure):
    """Allow absent terminal tails only; retain strict observed-atom criteria."""
    info = inspect_clean_structure(structure)
    reasons = []
    terminal_tails = []
    entities = {subchain: entity for entity in structure.entities for subchain in entity.subchains}
    for reason in info["reasons"]:
        if not reason.startswith("coordinate-incomplete-polymer-sequence:"):
            reasons.append(reason)
            continue
        chain_name = reason.split(":", 1)[1]
        rows = [r for r in structure[0][chain_name] if not r.is_water()]
        entity = entities.get(rows[0].subchain) if rows else None
        labels = [r.label_seq for r in rows]
        if (entity is None or any(index is None for index in labels)
                or labels != list(range(labels[0], labels[-1] + 1))
                or [r.name for r in rows] != list(entity.full_sequence)[labels[0] - 1:labels[-1]]):
            reasons.append(reason)
        else:
            terminal_tails.append({"chain": chain_name, "first_observed_label_seq": labels[0],
                "last_observed_label_seq": labels[-1], "declared_sequence_length": len(entity.full_sequence)})
    return {**info, "supported": not reasons, "reasons": reasons, "unobserved_terminal_tails": terminal_tails}


def antibody_domains(sequences):
    from anarci import anarci

    numbered, details, _ = anarci(list(sequences.items()), scheme="imgt", ncpu=1, assign_germline=False)
    domains = []
    for index, (chain, sequence) in enumerate(sequences.items()):
        if numbered[index] is None:
            continue
        for domain_index, (numbering, start, end) in enumerate(numbered[index]):
            kind = details[index][domain_index]["chain_type"]
            if kind not in {"H", "K", "L"}:
                continue
            cursor, positions = start, []
            for (number, insertion), aa in numbering:
                if aa == "-":
                    continue
                if cursor >= len(sequence) or sequence[cursor] != aa:
                    raise ValueError("ANARCI numbering does not exactly map the observed sequence")
                positions.append({"target_index": cursor, "imgt_number": number, "imgt_insertion": insertion.strip()})
                cursor += 1
            domains.append({"chain": chain, "chain_type": kind, "start": start, "end": end,
                "score": details[index][domain_index].get("bitscore"), "positions": positions})
    return domains


def build(args):
    if args.output.exists() or args.manifest.exists():
        raise ValueError("antibody source pool and manifest must be new")
    args.output.mkdir(parents=True)
    protocol = {"status": "fixed-source-pool-before-screening-and-inference", "pdb_ids": IDS,
        "source": "https://files.rcsb.org/download/<PDB>.cif", "maximum_cif_bytes": 10_000_000,
        "criteria": "X-ray; one whole canonical protein model <=512 residues; no nonwater chemistry, altlocs, incomplete heavy atoms or internal native breaks",
        "terminal_policy": "disclose absent terminal tails; target is the full observed sequence only",
        "annotation": "ANARCI IMGT on unchanged observed sequences; paired H and K/L required",
        "mask_specs": [["H", "CDR1", 5], ["H", "CDR3", 10], ["L", "CDR1", 5], ["L", "CDR3", 5]],
        "sequence_changes": False, "training_membership_independently_attested": False,
        "no_replacement": True, "producer_sha256": sha(Path(__file__).resolve())}
    (args.output / "protocol.json").write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    records = []
    for pdb_id in IDS:
        directory = args.output / pdb_id
        directory.mkdir()
        record = {"pdb_id": pdb_id, "status": "unsupported", "reasons": []}
        try:
            request = Request(f"https://files.rcsb.org/download/{pdb_id}.cif", headers={"User-Agent": "dvbfixer-known-sequence-holdout/1"})
            with urlopen(request, timeout=90) as stream:
                data = stream.read(protocol["maximum_cif_bytes"] + 1)
            if len(data) > protocol["maximum_cif_bytes"]:
                raise ValueError("source CIF exceeds the frozen bound")
            source = directory / "deposited_source.cif"
            source.write_bytes(data)
            record["source_sha256"] = sha(source)
            structure = gemmi.read_structure(str(source))
            info = inspect_observed_protein(structure)
            record.update(info)
            if not any("X-RAY" in method.method.upper() for method in structure.meta.experiments):
                record["reasons"].append("not-x-ray-crystallography")
            if record["reasons"]:
                records.append(record)
                print(json.dumps({"pdb_id": pdb_id, "status": record["status"], "reasons": record["reasons"]}), flush=True)
                continue
            normalized = normalize_structure(source, directory / "normalized.pdb")
            sanitized = sanitize_protein_hetatm(str(normalized.pdb_path))
            reference, preparation = prepare_intact_pdb(Path(sanitized).read_text())
            (directory / "reference.pdb").write_bytes(reference)
            if preparation["native_breaks"] or preparation["alternative_conformer_atoms_removed"]:
                raise ValueError("observed source preparation changed native connectivity or conformers")
            sequences = {normalized.chain_map.get(chain, chain): sequence for chain, sequence in info["sequences"].items()}
            domains = antibody_domains(sequences)
            if not any(d["chain_type"] == "H" for d in domains) or not any(d["chain_type"] in {"K", "L"} for d in domains):
                raise ValueError("paired ANARCI H and K/L domains absent")
            record.update(status="source-eligible", observed_sequences=sequences, chain_map=normalized.chain_map,
                domains=domains, reference_sha256=sha(directory / "reference.pdb"), preparation=preparation)
        except (OSError, ValueError, RuntimeError) as exc:
            record["reasons"].append(str(exc))
        records.append(record)
        print(json.dumps({"pdb_id": pdb_id, "status": record["status"], "reasons": record["reasons"]}), flush=True)
    manifest = {"status": "antibody-source-screen-completed-before-inference", "protocol": protocol, "cases": records,
        "artifacts": {path.relative_to(args.output).as_posix(): sha(path) for path in sorted(args.output.rglob("*")) if path.is_file()}}
    with args.manifest.open("x") as stream:
        stream.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"sources": len(records), "source_eligible": sum(r["status"] == "source-eligible" for r in records)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "manifest"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    build(args)


if __name__ == "__main__":
    main()
