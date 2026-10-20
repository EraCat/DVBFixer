#!/usr/bin/env python3
"""Prepare portable, source-only Apple cc89 controls without neural inference."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/cc89_apple_handoff"
CASES = (
    ("cc89-prospective-holdout-v2", "prospective-9ww8-gap5"),
    ("cc89-prospective-holdout-v2", "prospective-9ww8-gap10"),
    ("cc89-prospective-holdout-v3", "prospective-8ek6-H-cdr1-gap5"),
    ("cc89-prospective-holdout-v3", "prospective-9z0u-H-cdr3-gap10"),
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def capture():
    """Maintainer-only capture from the already audited Linux source archives."""
    if FIXTURES.exists():
        raise ValueError("portable fixture capture must be new")
    FIXTURES.mkdir()
    sources, cases = {}, []
    for cohort, case_id in CASES:
        manifest = ROOT / "docs/research" / f"{cohort}.json"
        old = next(row for row in json.loads(manifest.read_text())["cases"] if row["case_id"] == case_id)
        directory = ROOT / ".artifacts" / cohort / case_id
        source_id = old["source_id"]
        for name in ("reference.pdb", "target.fasta"):
            original = directory / name
            if sha(original) != old["artifacts"][name]:
                raise ValueError("Linux source archive changed")
            destination = FIXTURES / f"{source_id}{'.pdb' if name.endswith('.pdb') else '.fasta'}"
            if destination.exists() and destination.read_bytes() != original.read_bytes():
                raise ValueError("same-source controls have different original inputs")
            destination.write_bytes(original.read_bytes())
        sources[source_id] = {"pdb": f"{source_id}.pdb", "fasta": f"{source_id}.fasta",
            "coordinate_policy": "whole observed canonical-protein source; water/H excluded; dense mosaic numbering; no generated coordinates",
            "upstream_url": f"https://files.rcsb.org/download/{source_id}.cif"}
        cases.append({key: old[key] for key in ("case_id", "source_id", "stratum", "chain", "start", "length")}
                     | {"linux_manifest": manifest.relative_to(ROOT).as_posix(), "linux_manifest_sha256": sha(manifest)})
    dump(FIXTURES / "manifest.json", {
        "baseline_commit": "cb43db6", "status": "frozen-before-corrected-MPS-inference",
        "sources": sources, "cases": cases, "seeds": [7, 19],
        "checkpoint_sha256": "dfc9895b399ec4497bf6d646502168725f01dcbd55bc0b541fc3e3cc1f2f0483",
        "engine_revision": "ee378400f25b801fa481028000f9060183d7fb4c",
        "reference_policy": "evaluation only; never copy into a neural/refinement worker",
        "selection_policy": "frozen public CUDA integration controls; no new holdout or reference-based seed selection",
        "artifacts": {p.name: sha(p) for p in sorted(FIXTURES.iterdir()) if p.is_file()},
    })
    # Preserve existing reviewed fixture hashes; append only these new inputs.
    inventory = ROOT / "tests/fixtures/MANIFEST.sha256"
    lines = inventory.read_text().splitlines()
    lines.extend(f"{sha(p)}  {p.relative_to(ROOT).as_posix()}" for p in sorted(FIXTURES.iterdir()) if p.is_file())
    inventory.write_text("\n".join(sorted(lines, key=lambda line: line.split("  ", 1)[1])) + "\n")


def materialize(output):
    from dataclasses import replace

    import numpy as np
    from materialize_cc89_known_sequence_holdout import write_case

    from dvbfixer.model.diffusion.contract import DiffusionRequest
    from dvbfixer.model.diffusion.protein_context import (
        CUDA_CC89_CONTEXT,
        CUDA_CC89_OPTIONS,
        select_protein_context,
        source_context_position_features,
        validate_context_source,
    )

    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    for name, digest in manifest["artifacts"].items():
        if sha(FIXTURES / name) != digest:
            raise ValueError(f"portable source digest mismatch: {name}")
    if output.exists():
        raise ValueError("Apple control output must be new")
    output.mkdir(parents=True)
    rows = []
    for case in manifest["cases"]:
        directory = output / case["case_id"]
        directory.mkdir()
        source = FIXTURES / manifest["sources"][case["source_id"]]["pdb"]
        native = write_case(directory, source.read_bytes(), case, atom37_terminals=True)
        if native["status"] != "eligible":
            raise ValueError("portable known source no longer passes native preflight")
        for seed in manifest["seeds"]:
            request = DiffusionRequest.from_json((directory / f"requests/cc89-seed{seed}.json").read_text())
            request = select_protein_context(replace(request, protein_context=None),
                (directory / request.normalized_pdb.path).read_bytes(), CUDA_CC89_CONTEXT)
            options = tuple(option for option in request.backend_options if option.name not in {o.name for o in CUDA_CC89_OPTIONS})
            request = replace(request, backend_options=(*options, *CUDA_CC89_OPTIONS))
            validate_context_source(request, (directory / request.normalized_pdb.path).read_bytes())
            positions, chains = source_context_position_features(request)
            (directory / f"request-seed{seed}.json").write_text(request.to_json())
            rows.append({"case_id": case["case_id"], "seed": seed,
                "request_sha256": sha(directory / f"request-seed{seed}.json"),
                "source_position_sha256": hashlib.sha256(np.asarray((positions, chains), dtype="<i8").tobytes()).hexdigest()})
        evaluation = output / "evaluation" / case["case_id"]
        evaluation.mkdir(parents=True)
        (directory / "reference.pdb").rename(evaluation / "reference.pdb")
    report = {"fixture_manifest_sha256": sha(FIXTURES / "manifest.json"), "requests": rows,
        "inference_executed": False, "corrected_mps_port_status": "not-yet-implemented",
        "note": "These are explicit research requests. Current numerical-policy guards reject corrected MPS; do not register them as the legacy public MPS profile."}
    dump(output / "inputs.json", report)
    print(json.dumps({"cases": len(manifest["cases"]), "requests": len(rows), "inference_executed": False}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--capture-linux-sources", action="store_true")
    group.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.capture_linux_sources:
        capture()
    else:
        materialize(args.output.expanduser().absolute())


if __name__ == "__main__":
    main()
