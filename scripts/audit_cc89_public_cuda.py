#!/usr/bin/env python3
"""Independently verify the public model/Homology CUDA acceptance bundles."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from analyze_a100_relaxation import outside_records
from run_cc89_known_sequence_holdout import sha

from dvbfixer.homology_plan import build_mosaic_diffusion_request
from dvbfixer.model.diffusion.contract import DiffusionRequest, SamplerTrace
from dvbfixer.model.diffusion.protein_context import prepare_cuda_cc89_request
from dvbfixer.model.diffusion.publication import read_published_bundle
from dvbfixer.model.diffusion_cli import build_cli_diffusion_request
from dvbfixer.model.pipeline import parse_fasta

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ("homology", "cc89-prospective-holdout-v2", "prospective-9ww8-gap5", "cc89-public-homology-9ww8-gap5_homology_diffusion", (7,)),
    ("homology", "cc89-prospective-holdout-v3", "prospective-8ek6-H-cdr1-gap5", "cc89-public-homology-8ek6-cdr1_homology_diffusion", (7,)),
    ("homology", "cc89-prospective-holdout-v3", "prospective-9z0u-H-cdr3-gap10", "cc89-public-homology-9z0u-cdr3_homology_diffusion", (7,)),
    ("model", "cc89-prospective-holdout-v2", "prospective-9ww8-gap10", "cc89-public-model-9ww8-gap10", (7, 19)),
)


def audit(args):
    if args.output.exists():
        raise ValueError("public acceptance report must be new")
    rows = []
    for tool, cohort, case, bundle_name, seeds in CASES:
        source = ROOT / ".artifacts" / cohort / case
        targets = parse_fasta(str(source / "target.fasta"))
        with tempfile.TemporaryDirectory(prefix="cc89-public-audit-", dir=args.work_parent) as temporary:
            work = Path(temporary)
            if tool == "homology":
                normalized, request_path = build_mosaic_diffusion_request(
                    source / "materialized/selected_template_mosaic.coverage.json", list(targets.items()), work,
                    seeds=seeds, profile="protpardelle-1c-cuda")
                request = DiffusionRequest.from_json(request_path.read_text())
                source_root = normalized.parent
            else:
                normalized = source / "input/normalized.pdb"
                source_root = normalized.parent
                request = build_cli_diffusion_request(normalized, targets, seeds=seeds, profile="protpardelle-1c-cuda")
            request = prepare_cuda_cc89_request(request, normalized.read_bytes(), "auto")
            bundle = args.bundle_root / bundle_name
            published = read_published_bundle(bundle, request=request, source_root=source_root, work_parent=work)
            if published.status != "success" or {c.seed for c in published.candidates} != set(seeds):
                raise ValueError("public bundle omitted a seed or failed validation")
            index = json.loads((bundle / "bundle.json").read_text())
            generated = {(r.chain, r.residue_number, r.insertion_code) for gap in request.gaps for r in gap.generated_residues}
            for candidate in published.candidates:
                if outside_records(candidate.pdb_bytes.decode(), generated) != outside_records(normalized.read_text(), generated):
                    raise ValueError("public result changed outside-gap atom records")
                entry = next(row for row in index["candidates"] if row["seed"] == candidate.seed)
                trace = SamplerTrace.from_json((bundle / entry["sampler_trace"]["path"]).read_text())
                provenance = json.loads((bundle / entry["provenance"]["path"]).read_text())
                summary = provenance["validation_summary"]
                metrics = {m["name"]: m["value"] for m in summary["metrics"]}
                if (metrics["detectable-d-ca"] != 0 or metrics["fixed-heavy-atom-max-displacement"] != 0
                        or trace.refinement_mode != "localized-openmm-boundary-refinement"):
                    raise ValueError("public candidate lacks exact preservation, L chirality or refinement")
                rows.append({"tool": tool, "case_id": case, "seed": candidate.seed,
                    "profile": trace.profile, "passed": summary["passed"], "failed_gates": summary["hard_gate_failures"],
                    "d_ca_count": metrics["detectable-d-ca"], "fixed_max_displacement_angstrom": metrics["fixed-heavy-atom-max-displacement"],
                    "outside_gap_atom_records_identical": True, "coordinate_sha256": sha(candidate.pdb),
                    "bundle_index_sha256": sha(bundle / "bundle.json"), "request_exactly_matched": True,
                    "denoising_updates": trace.denoising_update_count, "callback_updates": trace.callback_update_count,
                    "refinement_mode": trace.refinement_mode})
    code = ("deploy/protpardelle-1c/cuda_runner.py", "deploy/protpardelle-1c/checkpoint_gap_smoke.py",
            "scripts/install_diffusion_backend.py", "src/dvbfixer/model/diffusion/protein_context.py",
            "src/dvbfixer/model/diffusion/scope.py", "src/dvbfixer/model/diffusion/contract.py",
            "src/dvbfixer/model/diffusion/trace.py", "src/dvbfixer/model/diffusion/preflight.py",
            "src/dvbfixer/model/diffusion_cli.py")
    report = {"complete": True, "accepted": len(rows), "planned_candidates": 5, "public_workflows": 4,
        "interpretation": "public integration acceptance on previously studied sources, not a new scientific holdout",
        "producer_sha256": sha(Path(__file__).resolve()), "code_sha256": {name: sha(ROOT / name) for name in code}, "rows": rows}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--work-parent", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    audit(parser.parse_args())


if __name__ == "__main__":
    main()
