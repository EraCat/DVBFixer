#!/usr/bin/env python3
"""Freeze and run explicit shared-context cc89 CUDA causal/on-off research audits."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

from dvbfixer.model.diffusion.contract import (
    ArtifactReference,
    BackendOption,
    DiffusionRequest,
    ProteinContextPolicy,
    RunnerResult,
)
from dvbfixer.model.diffusion.protein_context import (
    select_protein_context,
    validate_context_capability,
)

ROOT = Path(__file__).resolve().parents[1]


def prepare(args):
    if args.output.exists() or args.manifest.exists():
        raise ValueError("cc89 audit destinations must be new")
    original = DiffusionRequest.from_json((args.cohort / "1emv-complex/request.json").read_text())
    source = (args.cohort / "1emv-complex/input/normalized.pdb").read_bytes()
    original = replace(original, backend_options=(BackendOption("profile", "protpardelle-1c-research"),))
    cases = []
    for name, policy in (("partner-on", ProteinContextPolicy(partner_mode="full")),
                         ("partner-off", ProteinContextPolicy(partner_mode="none"))):
        request = select_protein_context(original, source, policy)
        validate_context_capability(request, "protpardelle")
        root = args.output / name
        (root / "input").mkdir(parents=True)
        (root / "input/normalized.pdb").write_bytes(source)
        (root / "request.json").write_text(request.to_json())
        cases.append({"case_id": name, "artifacts": {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                                    for path in root.rglob("*") if path.is_file()}})
    manifest = {"status": "frozen-before-cc89-context-inference", "seed": 7, "steps": 200, "step_scale": 1.2, "s_churn": 200.0,
                "device": "cuda", "per_step_reinjection": True, "cases": cases,
                "causal_gate": {"forward_call_index": 100, "repeat_max_abs_delta_angstrom": 0.0, "minimum_generated_response_angstrom": 0.0001,
                                "partner_translation_angstrom": [25.0, 0.0, 0.0]},
                "engine_revision": "ee378400f25b801fa481028000f9060183d7fb4c",
                "config_sha256": "e9999ace79bf3044351cc982a624fc3459add3a4f91cbf97ff5b437b8942eb9d",
                "checkpoint_sha256": "dfc9895b399ec4497bf6d646502168725f01dcbd55bc0b541fc3e3cc1f2f0483",
                "patched_models_sha256": hashlib.sha256((ROOT / "test/protpardelle-1c-audit/src/protpardelle/core/models.py").read_bytes()).hexdigest(),
                "limitations": ["CUDA research audit does not establish MPS acceptance", "one source and seed", "on/off changes atom axis; same-state probe isolates coordinate intervention"]}
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(args.manifest)


def worker(args):
    manifest = json.loads((ROOT / "docs/research/protpardelle-context-audit-cohort.json").read_text())
    source_spec = importlib.util.find_spec("protpardelle.core.models")
    if source_spec is None or source_spec.origin is None:
        raise ValueError("cc89 source is unavailable")
    models_path = Path(source_spec.origin)
    engine_root = models_path.parents[3]
    revision = subprocess.check_output(["git", "-C", str(engine_root), "rev-parse", "HEAD"], text=True).strip()
    if (revision != manifest["engine_revision"]
            or hashlib.sha256(models_path.read_bytes()).hexdigest() != manifest["patched_models_sha256"]):
        raise ValueError("cc89 frozen source or patch identity changed")
    case = next(case for case in manifest["cases"] if case["case_id"] == args.request.parent.name)
    for relative, expected in case["artifacts"].items():
        if hashlib.sha256((args.request.parent / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("cc89 frozen request or input changed")
    path = ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py"
    spec = importlib.util.spec_from_file_location("cc89_audit", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    args.output.mkdir()
    result, summary = module._run_staged(args.request.resolve(), args.output.resolve(), args.config.resolve(), args.checkpoint.resolve(),
        steps=200, step_scale=1.2, s_churn=200.0, per_step_reinjection=True, device_name="cuda", mps_profile=False, context_probe=args.context_probe)
    (args.request.parent / "runner-result.json").write_text(result.to_json())
    print(summary)


def analyze(args):
    from dvbfixer.model.diffusion.benchmark import candidate_quality, load_pdb_coordinates
    from dvbfixer.model.diffusion.validate import validate_runner_result

    manifest = json.loads(args.manifest.read_text())
    digest = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    original_manifest = json.loads((ROOT / "docs/research/protein-context-cohort.json").read_text())
    original = next(case for case in original_manifest["cases"] if case["case_id"] == "1emv-complex")
    reference = load_pdb_coordinates(args.reference.parent, ArtifactReference(args.reference.name, original["artifacts"]["reference.pdb"]))
    rows = []
    for case in manifest["cases"]:
        root = args.cohort / case["case_id"]
        for relative, expected in case["artifacts"].items():
            if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
                raise ValueError("cc89 frozen artifact changed")
        marker_path = root / "complete.json"
        if marker_path.exists():
            marker = json.loads(marker_path.read_text())
            if marker["manifest_sha256"] != digest:
                raise ValueError("cc89 completion manifest changed")
            for relative, expected in marker["artifacts"].items():
                if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
                    raise ValueError("cc89 completed artifact changed")
        request = DiffusionRequest.from_json((root / "request.json").read_text())
        result = RunnerResult.from_json((root / "runner-result.json").read_text())
        summary = json.loads((root / "raw/summary.json").read_text())
        if (result.backend_provenance.engine_revision != manifest["engine_revision"]
                or result.backend_provenance.checkpoint_sha256 != manifest["checkpoint_sha256"]
                or not result.backend_provenance.device.startswith("cuda")):
            raise ValueError("cc89 frozen CUDA provenance mismatch")
        validation = validate_runner_result(request, result, workspace=root)[0].summary
        if json.loads(json.dumps(asdict(validation))) != summary["validation"]:
            raise ValueError("cc89 validation differs from independent current policy")
        if summary["per_step_callback"]["callback_count"] != manifest["steps"] or summary["per_step_callback"]["maximum_post_projection_error_angstrom"] != 0:
            raise ValueError("cc89 projection hard gate failed")
        probes = summary.get("denoiser_context_probes", [])
        if case["case_id"] == "partner-on":
            gate = manifest["causal_gate"]
            if (len(probes) != 1 or probes[0]["repeat_max_abs_delta_angstrom"] != gate["repeat_max_abs_delta_angstrom"]
                    or probes[0]["forward_call_index"] != gate["forward_call_index"]
                    or probes[0]["partner_translation_angstrom"] != gate["partner_translation_angstrom"]
                    or probes[0]["same_features_and_sigma"] is not True or probes[0]["before_projection"] is not True
                    or not math.isfinite(probes[0]["generated_response_max_displacement_angstrom"])
                    or probes[0]["generated_response_max_displacement_angstrom"] < gate["minimum_generated_response_angstrom"]):
                raise ValueError("cc89 frozen causal gate failed")
        quality = candidate_quality(result.candidates[0].candidate_id, reference, load_pdb_coordinates(root, result.candidates[0].coordinate_artifact),
            generated_residues={residue for gap in request.gaps for residue in gap.generated_residues}, fixed_atoms=set(request.fixed_atoms),
            anchor_residues={anchor for gap in request.gaps for anchor in (gap.left_anchor, gap.right_anchor) if anchor},
            closure_passed="junction-peptide-connectivity" not in validation.hard_gate_failures, validation_passed=validation.passed,
            interface_chain_pairs=(("A", "B"),), expected_generated_atoms=set(request.generated_atoms))
        rows.append({"case_id": case["case_id"], "validation": asdict(validation), "quality": asdict(quality),
                     "causal_probes": probes, "provenance": asdict(result.backend_provenance), "resources": asdict(result.resource_metrics)})
        if not marker_path.exists():
            marker = {"manifest_sha256": digest, "artifacts": {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in root.rglob("*") if path.is_file()}}
            marker_path.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n")
    report = {"manifest_sha256": digest, "scope": "cc89-CUDA-mechanistic-audit-not-MPS-or-geometry-promotion", "cases": rows}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps([{ "case_id": row["case_id"], "validation_passed": row["validation"]["passed"],
                      "gap_backbone_rmsd_angstrom": row["quality"]["gap_backbone_rmsd_angstrom"], "causal_probes": row["causal_probes"]} for row in rows], indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    preparation = sub.add_parser("prepare")
    for name in ("cohort", "output", "manifest"):
        preparation.add_argument("--" + name, type=Path, required=True)
    worker_parser = sub.add_parser("worker")
    for name in ("request", "output", "config", "checkpoint"):
        worker_parser.add_argument("--" + name, type=Path, required=True)
    worker_parser.add_argument("--context-probe", action="store_true")
    analysis = sub.add_parser("analyze")
    for name in ("manifest", "cohort", "reference", "output"):
        analysis.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    {"prepare": prepare, "worker": worker, "analyze": analyze}[args.action](args)


if __name__ == "__main__":
    main()
