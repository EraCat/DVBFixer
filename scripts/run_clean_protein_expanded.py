#!/usr/bin/env python3
"""Execute the clean full-complex cohort using unchanged inference/refinement workers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_a100_relaxation import runtime_environment, sha
from run_protein_context_ablations import _load

ROOT = Path(__file__).resolve().parents[1]


def freeze_protocol(args, manifest):
    probe = json.loads(args.engine_preflight.read_text())
    if not manifest.get("full_context") or not probe["complete"] or not probe["all_required_atoms_represented"]:
        raise ValueError("clean experiment requires complete full-context atom-axis preflight")
    if probe["manifest_sha256"] != sha(args.manifest) or {row["case_id"] for row in probe["cases"]} != {case["case_id"] for case in manifest["cases"]}:
        raise ValueError("engine preflight does not cover the exact frozen cases")
    paths = ("scripts/run_clean_protein_expanded.py", "scripts/run_intact_recheck.py", "scripts/audit_intact_inputs.py",
        "scripts/preflight_clean_protein_features.py", "src/dvbfixer/model/diffusion/protein_context.py",
        "src/dvbfixer/model/diffusion/scope.py", "src/dvbfixer/model/diffusion/boundary_refinement.py",
        "src/dvbfixer/model/diffusion/runner_refinement.py", "deploy/protenix-v1/build-template-input.py",
        "deploy/protenix-v1/checkpoint_gap_smoke.py", "deploy/protenix-v1/reinjection.py")
    protocol = {"status": "frozen-before-clean-full-complex-inference", "cohort_sha256": sha(args.manifest),
        "code_sha256": {relative: sha(ROOT / relative) for relative in paths}, "environment": runtime_environment(),
        "input_audit_sha256": sha(args.cohort / "input-audit.json"), "engine_preflight_sha256": sha(args.engine_preflight),
        "source_count": len(manifest["screening"]), "planned_masks": len(manifest["cases"]) + len(manifest["excluded_cases"]),
        "eligible_cases": len(manifest["cases"]), "source_native_quality_exclusions": len(manifest["excluded_cases"]),
        "context": "FULL target and ALL protein partners; every required fixed/generated atom represented; no spatial or sequential cropping; <=512 residues total",
        "chemistry": "canonical complete proteins only; no nonwater components removed to achieve admission",
        "inference": "pinned Protenix CUDA checkpoint/profile; seed7, 200 exact per-step reinjections, one cycle",
        "refinement": "unchanged rigid v6 CUDA generated-only local refinement", "solvent": False,
        "evaluation": "unchanged geometry and all-background atom preservation; no RMSD ranking or native-coordinate optimization",
        "secondary_structure": "deposited helix/sheet overlap reported separately; no loop-only restriction",
        "no_outcome_replacement": True, "public_promotion": False}
    if args.protocol.exists():
        if json.loads(args.protocol.read_text()) != protocol:
            raise ValueError("clean expanded protocol differs from the original freeze")
    else:
        args.protocol.write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "cohort", "visual", "output", "protocol", "engine-preflight", "work-parent", "checkpoint", "kalign"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    # Reuse the already tested custody, sequential subprocess, validation, export,
    # and failure-denominator machinery. Only orchestration metadata is replaced;
    # the scientific workers consume the frozen full-context request unchanged.
    module = _load("clean_full_complex_orchestration", ROOT / "scripts/run_intact_recheck.py")
    module.protocol = freeze_protocol
    module.run(args)


if __name__ == "__main__":
    main()
