#!/usr/bin/env python3
"""Verify completed public replay archives and compare with the frozen baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
from statistics import median

from run_protenix_public_cohort import (
    DEFAULT_MANIFEST,
    FROZEN_MANIFEST_SHA256,
    PublicCohortError,
    _atomic_json,
    _read_json,
    _sha256,
    load_manifest,
    validate_bundle,
    validate_materialized_case,
)

from dvbfixer.model.diffusion.benchmark import (
    BackendCaseResult,
    BackendEligibilityPolicy,
    candidate_quality,
    compare_paired_backends,
    load_pdb_coordinates,
    summarize_backend_cases,
)
from dvbfixer.model.diffusion.contract import (
    ArtifactReference,
    BackendOption,
    DiffusionRequest,
    RunnerResult,
    SamplerTrace,
)
from dvbfixer.model.diffusion.validate import build_validated_result


def summarize(cases: list[dict]) -> dict:
    """Report all scientific failures; RMSD distribution uses passing cases only."""
    passing = [case for case in cases if case["validation_passed"]]
    return {
        "case_count": len(cases),
        "passing_count": len(passing),
        "validation_failed_count": len(cases) - len(passing),
        "pass_rate": len(passing) / len(cases),
        "median_valid_gap_backbone_rmsd_angstrom": median(
            case["quality"]["gap_backbone_rmsd_angstrom"] for case in passing
        ) if passing else None,
        "summed_runner_wall_time_seconds": sum(
            case["resource_metrics"]["wall_time_seconds"] for case in cases
        ),
        "median_runner_wall_time_seconds": median(
            case["resource_metrics"]["wall_time_seconds"] for case in cases
        ),
        "peak_ram_bytes": max(case["resource_metrics"]["peak_ram_bytes"] for case in cases),
        "peak_vram_bytes": max(case["resource_metrics"]["peak_vram_bytes"] for case in cases),
    }


def validate_completion(report: dict, members: tuple[dict, ...]) -> None:
    if (
        report.get("complete") is not True
        or report.get("manifest_sha256") != FROZEN_MANIFEST_SHA256
        or [case["case_id"] for case in report["cases"]] != [case["case_id"] for case in members]
        or report.get("seed") != 7
    ):
        raise PublicCohortError("replay is incomplete or its frozen membership changed")


def analyze(
    archive: Path, cohort: Path, *, manifest_path: Path = DEFAULT_MANIFEST,
    work_parent: Path | None = None,
) -> dict:
    if _sha256(manifest_path) != FROZEN_MANIFEST_SHA256:
        raise PublicCohortError("frozen manifest digest changed")
    manifest, members = load_manifest(manifest_path)
    baseline_path = cohort / "aggregate.json"
    if _sha256(baseline_path) != manifest["source_aggregate_sha256"]:
        raise PublicCohortError("frozen baseline digest changed")
    baseline = _read_json(baseline_path)
    baseline_cases = baseline["case_results"]["protenix-v1"]
    baseline_by_id = {case["case_id"]: case for case in baseline_cases}
    expected_ids = [case["case_id"] for case in members]
    if len(baseline_by_id) != len(baseline_cases) or set(baseline_by_id) != set(expected_ids):
        raise PublicCohortError("baseline cohort membership changed")
    report = _read_json(archive / "report.json")
    validate_completion(report, members)

    replay_runs = []
    rows = []
    report_by_id = {case["case_id"]: case for case in report["cases"]}
    profile_lock_path = Path(__file__).resolve().parents[1] / "deploy/protenix-v1/profile-lock.json"
    lock = _read_json(profile_lock_path)
    profile_id = "linux-amd64;profile-lock-sha256=" + _sha256(profile_lock_path)
    for member in members:
        case_id = member["case_id"]
        source = validate_materialized_case(
            cohort, member, source_cohort_sha256=manifest["source_cohort_sha256"], seed=7,
        )
        bundle = archive / "cases" / case_id / "bundle"
        evidence = validate_bundle(bundle, case_id=case_id, seed=7)
        recorded = report_by_id[case_id]
        if any(evidence[key] != recorded[key] for key in (
            "bundle_json_sha256", "validation_passed", "hard_gate_failures", "artifacts",
        )):
            raise PublicCohortError(f"report evidence mismatch for {case_id}")
        provenance = _read_json(bundle / evidence["artifacts"]["provenance"]["path"])
        backend = provenance["backend_provenance"]
        if (
            backend["checkpoint_sha256"] != lock["checkpoint"]["sha256"]
            or backend["engine_revision"] != lock["protenix_revision"]
            or backend["environment_identity"] != profile_id
            or backend["device"] != "cuda:0"
            or backend["deterministic_algorithms"] is not True
        ):
            raise PublicCohortError(f"profile provenance mismatch for {case_id}")
        trace = SamplerTrace.from_json(
            (bundle / evidence["artifacts"]["sampler_trace"]["path"]).read_text()
        )
        if (
            trace.profile != "protenix-v1-cuda"
            or trace.engine_revision != lock["protenix_revision"]
            or trace.patch_identity != "sha256:" + lock["patch_sha256"]
            or trace.max_projection_error_angstrom != 0.0
        ):
            raise PublicCohortError(f"sampler evidence mismatch for {case_id}")
        raw_request = _read_json(source / "request.json")
        raw_request["schema_version"] = 4
        request = DiffusionRequest.from_dict(raw_request)
        if not any(option.name == "profile" for option in request.backend_options):
            request = replace(request, backend_options=(
                *request.backend_options, BackendOption("profile", "protenix-v1-cuda"),
            ))
        if hashlib.sha256(request.to_json().encode()).hexdigest() != provenance["request_sha256"]:
            raise PublicCohortError(f"scientific request changed for {case_id}")
        runner_result = RunnerResult.from_dict({
            "schema_version": 4, "status": "success",
            "candidates": [provenance["candidate"]],
            "backend_provenance": backend,
            "runner_diagnostics": {"exit_code": 0, "timed_out": False},
            "resource_metrics": provenance["resource_metrics"],
        })
        with tempfile.TemporaryDirectory(prefix="protenix-revalidate-", dir=work_parent) as directory:
            workspace = Path(directory)
            source_path = workspace / request.normalized_pdb.path
            source_path.parent.mkdir(parents=True)
            shutil.copyfile(source / request.normalized_pdb.path, source_path)
            for label in ("pdb", "sampler_trace"):
                relative = evidence["artifacts"][label]["path"]
                shutil.copyfile(bundle / relative, workspace / relative)
            validated = build_validated_result(request, runner_result, workspace=workspace)
        summary = validated.validation_summaries[0]
        if (
            summary.passed != evidence["validation_passed"]
            or list(summary.hard_gate_failures) != evidence["hard_gate_failures"]
        ):
            raise PublicCohortError(f"independent revalidation changed the result for {case_id}")
        accepted = _read_json(source.parent / "accepted.json")
        reference_artifact = ArtifactReference(
            "reference.pdb", accepted["artifacts"]["reference.pdb"]["sha256"],
        )
        quality = candidate_quality(
            evidence["candidate_id"],
            load_pdb_coordinates(source, reference_artifact),
            load_pdb_coordinates(bundle, ArtifactReference(**evidence["artifacts"]["pdb"])),
            generated_residues={residue for gap in request.gaps for residue in gap.generated_residues},
            fixed_atoms=set(request.fixed_atoms),
            anchor_residues={anchor for gap in request.gaps for anchor in (gap.left_anchor, gap.right_anchor) if anchor is not None},
            closure_passed="junction-peptide-connectivity" not in evidence["hard_gate_failures"],
            validation_passed=evidence["validation_passed"],
        )
        metrics = provenance["resource_metrics"]
        if any(metrics.get(key) is None for key in (
            "wall_time_seconds", "peak_ram_bytes", "peak_vram_bytes",
        )):
            raise PublicCohortError(f"missing resource evidence for {case_id}")
        fixed_metrics = {
            metric["name"]: metric["value"] for metric in provenance["validation_summary"]["metrics"]
        }
        if (
            quality.fixed_heavy_rmsd_angstrom != 0.0
            or fixed_metrics["fixed-heavy-atom-max-displacement"] != 0.0
            or fixed_metrics["detectable-d-ca"] != 0.0
        ):
            raise PublicCohortError(f"fixed coordinates or chirality invariant failed for {case_id}")
        replay_runs.append(BackendCaseResult(
            backend_id="protenix-v1-public-production-replay", case_id=case_id,
            independence_group=baseline_by_id[case_id]["independence_group"],
            validation_passed=evidence["validation_passed"], fixed_coordinates_exact=True,
            mapping_valid=True, leakage_resolved=baseline_by_id[case_id]["leakage_resolved"],
            gap_backbone_rmsd_angstrom=quality.gap_backbone_rmsd_angstrom,
            wall_time_seconds=metrics["wall_time_seconds"],
            peak_ram_bytes=metrics["peak_ram_bytes"], peak_vram_bytes=metrics["peak_vram_bytes"],
        ))
        rows.append({
            **member, "validation_passed": evidence["validation_passed"],
            "hard_gate_failures": evidence["hard_gate_failures"],
            "bundle_json_sha256": evidence["bundle_json_sha256"],
            "pdb_sha256": evidence["artifacts"]["pdb"]["sha256"],
            "baseline_validation_passed": baseline_by_id[case_id]["validation_passed"],
            "quality": asdict(quality), "resource_metrics": metrics,
        })
    baseline_runs = tuple(BackendCaseResult(**{
        **case, "eligibility_policy": BackendEligibilityPolicy(case["eligibility_policy"]),
    }) for case in baseline_cases)
    comparison = compare_paired_backends(tuple(replay_runs), baseline_runs)
    return {
        "schema_version": 1,
        "scope": "frozen-231-case-public-cli-production-replay",
        "verified_case_count": len(rows),
        "independently_revalidated_case_count": len(rows),
        "manifest_sha256": _sha256(manifest_path),
        "baseline_aggregate_sha256": _sha256(baseline_path),
        "replay_report_sha256": _sha256(archive / "report.json"),
        "summary": summarize(rows),
        "baseline_summary": asdict(summarize_backend_cases(baseline_runs)),
        "paired_comparison": asdict(comparison),
        "resource_timing_caveat": "Replay runner sampling/refinement timings exclude CLI preflight/publication; historical complete-stage timings have a different boundary.",
        "status_changes": [{
            "case_id": row["case_id"], "baseline_passed": row["baseline_validation_passed"],
            "replay_passed": row["validation_passed"], "failed_gates": row["hard_gate_failures"],
        } for row in rows if row["validation_passed"] != row["baseline_validation_passed"]],
        "failed_gate_counts": dict(Counter(gate for row in rows for gate in row["hard_gate_failures"])),
        "gap_strata": {str(length): summarize([row for row in rows if row["gap_length"] == length]) for length in (5, 10)},
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("cohort", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--work-parent", type=Path)
    args = parser.parse_args()
    result = analyze(args.archive, args.cohort, work_parent=args.work_parent)
    _atomic_json(args.output, result)
    print(json.dumps({key: result[key] for key in ("verified_case_count", "summary", "status_changes")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
