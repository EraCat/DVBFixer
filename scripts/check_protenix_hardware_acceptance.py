#!/usr/bin/env python3
"""Verify two public-CLI Protenix 36hb repeats and emit portable smoke evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from run_protenix_public_cohort import PublicCohortError, _atomic_json, validate_bundle

from dvbfixer.model.diffusion.contract import DiffusionContractError, SamplerTrace

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PDB_SHA256 = "664e65f90a9a7ec6abdd762008b6f28fe20d2e47eaab576bdf1830a246b61ea4"


def verify_repeat(first: Path, repeat: Path) -> dict[str, object]:
    """Check digest-linked CUDA/callback/refinement evidence, without inference."""
    if first.resolve() == repeat.resolve():
        raise PublicCohortError("independent repeat bundles must be distinct")
    lock = json.loads((ROOT / "deploy/protenix-v1/profile-lock.json").read_text())
    observed = []
    request_identities = []
    for bundle in (first, repeat):
        evidence = validate_bundle(bundle, case_id="36hb", seed=7)
        if not evidence["validation_passed"]:
            raise PublicCohortError("36hb hardware smoke failed independent validation")
        pdb_digest = evidence["artifacts"]["pdb"]["sha256"]
        if pdb_digest != EXPECTED_PDB_SHA256:
            raise PublicCohortError("36hb deterministic PDB identity changed")
        provenance = json.loads(
            (bundle / evidence["artifacts"]["provenance"]["path"]).read_text()
        )
        backend = provenance["backend_provenance"]
        lock_digest = hashlib.sha256(
            (ROOT / "deploy/protenix-v1/profile-lock.json").read_bytes()
        ).hexdigest()
        if (
            backend["checkpoint_sha256"] != lock["checkpoint"]["sha256"]
            or backend["engine_revision"] != lock["protenix_revision"]
            or backend["environment_identity"] != f"linux-amd64;profile-lock-sha256={lock_digest}"
            or provenance["validation_summary"]["passed"] is not True
        ):
            raise PublicCohortError("36hb hardware smoke provenance does not match the frozen profile")
        request_identities.append(provenance["request_sha256"])
        validation_metrics = {
            metric["name"]: metric["value"]
            for metric in provenance["validation_summary"]["metrics"]
        }
        if any(validation_metrics.get(name) != 0.0 for name in (
            "fixed-heavy-atom-rmsd", "fixed-heavy-atom-max-displacement", "detectable-d-ca",
        )):
            raise PublicCohortError("36hb hardware smoke failed fixed-coordinate or chirality evidence")
        try:
            trace = SamplerTrace.from_json(
                (bundle / evidence["artifacts"]["sampler_trace"]["path"]).read_text()
            )
        except DiffusionContractError as exc:
            raise PublicCohortError("36hb hardware smoke has an invalid sampler trace") from exc
        if (
            trace.profile != "protenix-v1-cuda"
            or trace.engine_revision != lock["protenix_revision"]
            or trace.patch_identity != "sha256:" + lock["patch_sha256"]
            or not trace.device.startswith("cuda:")
            or not trace.fallback_disabled
            or not trace.sampler_evidence_complete
            or trace.callback_update_count != 200
            or trace.denoising_update_count != 200
            or [step.step_index for step in trace.steps] != list(range(200))
            or trace.max_projection_error_angstrom != 0.0
            or trace.refinement_mode != "localized-openmm-boundary-refinement"
        ):
            raise PublicCohortError("36hb hardware smoke has incomplete frozen-profile evidence")
        metrics = trace.resource_metrics
        if any(
            value is None or value <= 0
            for value in (metrics.wall_time_seconds, metrics.peak_ram_bytes, metrics.peak_vram_bytes)
        ):
            raise PublicCohortError("36hb hardware smoke has missing resource measurements")
        observed.append({
            "pdb_sha256": pdb_digest,
            "sampler_trace_sha256": evidence["artifacts"]["sampler_trace"]["sha256"],
            "callback_update_count": trace.callback_update_count,
            "max_projection_error_angstrom": trace.max_projection_error_angstrom,
            "resource_metrics": {
                "wall_time_seconds": metrics.wall_time_seconds,
                "peak_ram_bytes": metrics.peak_ram_bytes,
                "peak_vram_bytes": metrics.peak_vram_bytes,
            },
        })
    if not request_identities[0] or request_identities[0] != request_identities[1]:
        raise PublicCohortError("independent repeats used different requests")
    return {
        "schema_version": 1,
        "status": "passed",
        "scope": "public-cli-36hb-same-seed-hardware-smoke-only",
        "full_cohort_acceptance": False,
        "profile": "protenix-v1-cuda",
        "case_id": "36hb",
        "seed": 7,
        "engine_revision": lock["protenix_revision"],
        "checkpoint_sha256": lock["checkpoint"]["sha256"],
        "same_seed_pdb_identical": True,
        "runs": observed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("repeat", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        evidence = verify_repeat(args.first, args.repeat)
        _atomic_json(args.output, evidence)
    except (OSError, ValueError, KeyError, PublicCohortError):
        print("ERROR: Protenix hardware acceptance evidence failed verification")
        return 1
    print("Protenix public-CLI repeat smoke passed; full cohort acceptance remains separate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
