#!/usr/bin/env python3
"""Checkpoint-backed batch/resume, ZBS and mosaic Homology workflow acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from dvbfixer.ffutils.dat import DatRecord
from dvbfixer.model.diffusion.publication import read_published_bundle


def smoke(cohort: Path, work: Path, executable: Path) -> dict:
    if work.exists():
        raise ValueError("workflow smoke requires a new native work directory")
    source = cohort / "cases/36hb/workspace"
    source_bytes = (source / "input/normalized.pdb").read_bytes()
    work.mkdir()
    inputs = work / "inputs"
    inputs.mkdir()
    for name in ("first", "second"):
        (inputs / f"{name}.pdb").write_bytes(source_bytes)
    fasta = work / "target.fasta"
    shutil.copyfile(source / "target.fasta", fasta)
    outputs = work / "results"

    def run(label, arguments):
        with (work / f"{label}.log").open("xb") as log:
            subprocess.run([str(executable), *arguments], stdout=log, stderr=subprocess.STDOUT, check=True)

    batch = ["model", "--input-dir", str(inputs), "--output-dir", str(outputs),
             "--backend", "diffusion", "--diffusion-model", "protenix",
             "--fasta", str(fasta), "--diffusion-work-parent", str(work), "--diffusion-timeout", "3600"]
    run("batch", batch)
    first = read_published_bundle(outputs / "first_model_diffusion").selected()
    second = read_published_bundle(outputs / "second_model_diffusion").selected()
    if first.pdb_bytes != second.pdb_bytes:
        raise ValueError("same-input batch candidates changed between independent runs")
    run("resume", [*batch, "--diffusion-resume"])
    report = json.loads((outputs / "diffusion-batch.json").read_text())
    if not all(row["status"] == "success" and row["resumed"] for row in report["results"]):
        raise ValueError("batch resume did not reuse both validated bundles")
    run("zbs", [
        "zbs", str(inputs / "first.pdb"), "-o", str(outputs / "first_zbs.pdb"),
        "--model-backend", "diffusion", "--diffusion-model", "protenix", "--diffusion-resume",
        "--skip-renumber", "--fasta", str(fasta), "--no-solvent", "--keep-interim",
        "--no-align-to-input", "--no-propka", "--no-protassign", "--ff", "amber",
        "--atom-naming", "standard", "--max-iter", "100", "--platform", "Reference",
    ])
    prepared = DatRecord.load(outputs / "first_prepared.dat")
    if not first.dat_record.added_keys() <= prepared.added_keys():
        raise ValueError("ZBS preparation lost modeled-atom restraint identities")

    raw_request = json.loads((source / "request.json").read_text())
    target = raw_request["target_sequences"][0]
    gap = raw_request["gaps"][0]["target_interval"]
    template_sequence = target["sequence"][:gap["start"]] + "-" * (gap["stop"] - gap["start"]) + target["sequence"][gap["stop"]:]
    plan = work / "template-plan.json"
    plan.write_text(json.dumps({
        "templates": [{"id": "source", "path": str(inputs / "first.pdb"), "chain": target["chain"], "targetChain": target["chain"]}],
        "alignmentGroups": [{"chainId": target["chain"], "rows": [
            {"id": target["chain"], "kind": "target", "sequence": target["sequence"]},
            {"id": "source", "kind": "template", "templateId": "source", "sequence": template_sequence},
        ], "masks": {}, "maskModes": {"source": "all"}}],
    }))
    run("homology", ["homology", str(fasta), "--template-plan", str(plan), "-o", str(outputs / "mosaic"),
                     "--backend", "diffusion", "--diffusion-model", "protenix", "--diffusion-work-parent", str(work), "--diffusion-timeout", "3600"])
    mosaic = read_published_bundle(outputs / "mosaic_homology_diffusion").selected()
    if (source / "input/normalized.pdb").read_bytes() != source_bytes:
        raise ValueError("workflow modified the source structure")
    result = {
        "schema_version": 1, "profile": "protenix-v1-cuda", "case_id": "36hb",
        "batch_success_count": 2, "resume_verified_count": 2,
        "zbs_completed": (outputs / "first_zbs.pdb").is_file(),
        "modeled_dat_handoff_preserved": True, "homology_validated": True,
        "batch_pdb_sha256": hashlib.sha256(first.pdb_bytes).hexdigest(),
        "homology_pdb_sha256": hashlib.sha256(mosaic.pdb_bytes).hexdigest(),
    }
    (work / "workflow-smoke.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--dvbfixer", required=True, type=Path)
    parser.add_argument("--archive-root", type=Path)
    parser.add_argument("--archive-existing", action="store_true", help="Verify and archive a completed smoke without inference")
    args = parser.parse_args()
    work = args.work.resolve()
    if args.archive_existing:
        result = json.loads((work / "workflow-smoke.json").read_text())
        for name in ("first_model_diffusion", "second_model_diffusion", "mosaic_homology_diffusion"):
            read_published_bundle(work / "results" / name).selected()
        if not (work / "results/first_zbs.pdb").is_file():
            raise ValueError("completed ZBS output is missing")
    else:
        result = smoke(args.cohort.resolve(), work, args.dvbfixer.absolute())
    if args.archive_root:
        shutil.copytree(work, args.archive_root)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
