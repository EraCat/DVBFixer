#!/usr/bin/env python3
"""Read-only structural revalidation and visual export of the known-sequence study."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from pathlib import Path
from statistics import median

from analyze_a100_relaxation import equivalent, outside_records
from materialize_cc89_known_sequence_holdout import assert_mask_only, atom_records
from run_cc89_known_sequence_holdout import ROOT, STAGES, evaluate, sha, verify_inventory

from dvbfixer.model.diffusion.contract import DiffusionRequest, RunnerResult, SamplerTrace
from dvbfixer.model.diffusion.protein_context import validate_context_source
from dvbfixer.model.diffusion.publication import read_published_bundle
from dvbfixer.model.diffusion.validate import validate_runner_result


def snapshot(args):
    protocol = json.loads(args.protocol.read_text())
    if args.output.exists():
        raise ValueError("source snapshot must be new")
    verify_inventory(ROOT, protocol["code_sha256"])
    args.output.mkdir(parents=True)
    for relative in protocol["code_sha256"]:
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("source snapshot path must be repository-relative")
        destination = args.output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    verify_inventory(args.output, protocol["code_sha256"])
    marker = {"protocol_sha256": sha(args.protocol), "code_sha256": protocol["code_sha256"],
        "checkpoint_sha256": protocol["checkpoint_sha256"], "checkpoint_copied": False,
        "producer_sha256": sha(Path(__file__).resolve())}
    (args.output / "snapshot.json").write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"files": len(protocol["code_sha256"]), "snapshot_sha256": sha(args.output / "snapshot.json")}))


def summarize(rows):
    evaluated = [row for row in rows if row["status"] == "evaluated"]
    accepted = [row for row in evaluated if row["validation"]["passed"]]
    available = [row for row in evaluated if row.get("quality")]
    accepted_values = [row["quality"]["gap_backbone_rmsd_angstrom"] for row in accepted if row.get("quality")]
    return {"planned_outcomes": len(rows), "sources": len({row["source_id"] for row in rows}),
        "evaluated": len(evaluated), "statuses": dict(Counter(row["status"] for row in rows)),
        "strict_accepted": len(accepted), "strict_rejected": len(evaluated) - len(accepted),
        "comparator_geometry_accepted": sum(row.get("comparator_geometry_passed", False) for row in evaluated),
        "accuracy_available": len(available),
        "median_backbone_rmsd_all_available_angstrom": median(row["quality"]["gap_backbone_rmsd_angstrom"] for row in available) if available else None,
        "median_backbone_rmsd_strict_accepted_angstrom": median(accepted_values) if accepted_values else None,
        "maximum_backbone_rmsd_strict_accepted_angstrom": max(accepted_values, default=None),
        "accepted_rmsd_bins_angstrom": {"<=1": sum(x <= 1 for x in accepted_values), "(1,2]": sum(1 < x <= 2 for x in accepted_values),
            "(2,4]": sum(2 < x <= 4 for x in accepted_values), ">4": sum(x > 4 for x in accepted_values)},
        "rejected_gate_counts": dict(Counter(gate for row in evaluated for gate in row["validation"]["hard_gate_failures"])),
        "seed_replicates_are_not_independent_sources": True}


def validate_background(root, request, candidate):
    generated = {(r.chain, r.residue_number, r.insertion_code) for gap in request.gaps for r in gap.generated_residues}
    if outside_records((root / candidate).read_text(), generated) != outside_records((root / request.normalized_pdb.path).read_text(), generated):
        raise ValueError("candidate changed outside-gap source atom records")


def audit_inputs(args, manifest):
    for case in manifest["cases"]:
        source = args.cohort / case["case_id"]
        verify_inventory(source, case["artifacts"])
        if case["status"] != "eligible":
            continue
        request = DiffusionRequest.from_json((source / "requests/cc89-seed7.json").read_text())
        normalized = (source / request.normalized_pdb.path).read_bytes()
        validate_context_source(request, normalized)
        generated = {(r.chain, r.residue_number, r.insertion_code) for gap in request.gaps for r in gap.generated_residues}
        assert_mask_only((source / "reference.pdb").read_bytes(), normalized, generated)
        plan = json.loads((source / "template-plan.json").read_text())
        if any(Path(template["path"]).resolve() != (source / "masked-template.pdb").resolve() for template in plan["templates"]):
            raise ValueError("Homology template plan references unexpected coordinates")
        # Exact original-identity mask is checked independently of the mosaic's
        # dense numbering by reversing the disclosed original-to-mosaic map.
        source_rows = {}
        for item in case["identity_mapping"]:
            source_rows[(item["chain"], item["mosaic_residue_number"], "")] = (item["chain"], item["original_residue_number"], item["original_insertion_code"])
        if case["stratum"] == "general-protein":
            original_reference = args.clean_cohort / "cases" / f"{case['source_id'].lower()}-gap5-seed7" / "reference.pdb"
        else:
            original_reference = args.antibody_sources / case["source_id"] / "reference.pdb"
        if sha(original_reference) != case["source_reference_sha256"]:
            raise ValueError("known source reference does not match original deposited-source preparation")
        reverted = {(*source_rows[atom[:3]], atom[3]): value for atom, value in atom_records((source / "reference.pdb").read_bytes()).items()}
        if reverted != atom_records(original_reference.read_bytes()):
            raise ValueError("evaluation reference changed original source residue identities, sequences or coordinates")
        expected_missing = {tuple(value) for value in case["original_generated_residues"]}
        if {source_rows[identity] for identity in generated} != expected_missing:
            raise ValueError("mosaic mask differs from the frozen original-coordinate mask")
        template_ids = {(line[21], line[22:26].strip(), line[26].strip()) for line in (source / "masked-template.pdb").read_text().splitlines() if line.startswith("ATOM  ")}
        if template_ids & expected_missing:
            raise ValueError("withheld gap residue remains in a Homology template")
        if request.target_sequences != DiffusionRequest.from_json((source / "requests/cc89-seed19.json").read_text()).target_sequences:
            raise ValueError("target sequence changed between seeds")
        if {target.chain: target.sequence for target in request.target_sequences} != case["source_observed_sequences"]:
            raise ValueError("target differs from the known observed source sequence")


def validate_job(args, protocol, case, stage, job):
    root = args.results / stage / job["case_id"] / f"seed{job['seed']}"
    if not (root / "complete.json").exists():
        return {**job, "source_id": case["source_id"], "length": case["length"], "stratum": case["stratum"], "status": "pending"}
    marker = json.loads((root / "complete.json").read_text())
    if marker["protocol_sha256"] != sha(args.protocol) or marker["manifest_sha256"] != sha(args.manifest) or marker["job"] != job or marker["stage"] != stage:
        raise ValueError("holdout archive is bound to another input/job/protocol")
    verify_inventory(root, marker["artifacts"])
    source = args.cohort / case["case_id"]
    if sha(root / "request.json") != case["artifacts"][f"requests/cc89-seed{job['seed']}.json"]:
        raise ValueError("executed request differs from frozen seed request")
    if sha(root / "input/normalized.pdb") != case["artifacts"]["input/normalized.pdb"]:
        raise ValueError("executed normalized input differs from frozen source")
    recorded = json.loads((root / "outcome.json").read_text())
    request = DiffusionRequest.from_json((root / "request.json").read_text())
    row = {**job, "source_id": case["source_id"], "length": case["length"], "stratum": case["stratum"], **recorded}
    if stage == "refine":
        raw_marker = args.results / "raw" / job["case_id"] / f"seed{job['seed']}" / "complete.json"
        if marker["raw_complete_sha256"] != sha(raw_marker):
            raise ValueError("refinement is not bound to its exact raw archive")
    if recorded["status"] != "evaluated":
        return row
    if sha(root / "reference.pdb") != case["artifacts"]["reference.pdb"]:
        raise ValueError("evaluation reference differs from the frozen source")
    if stage in {"raw", "refine"}:
        result_file = "runner-result.json" if stage == "raw" else "refined-runner-result.json"
        result = RunnerResult.from_json((root / result_file).read_text())
        validated, = validate_runner_result(request, result, workspace=root)
        current = evaluate(root, request, validated.candidate.coordinate_artifact.path, summary=validated.summary)
        trace = SamplerTrace.from_json((root / validated.candidate.sampler_trace_artifact.path).read_text())
        if "cc89-chain-phase=neutral-v1" not in trace.patch_identity or trace.device != "cuda" or not trace.fallback_disabled or trace.denoising_update_count != 500:
            raise ValueError("cc89 holdout trace lacks pinned CUDA/phase evidence")
        validate_background(root, request, validated.candidate.coordinate_artifact.path)
        row["coordinate_origin"] = "raw-retained" if stage == "refine" and validated.candidate.coordinate_artifact.path.startswith("raw/") else stage
        row["postprocessing_failures"] = validated.candidate.postprocessing_failures
    elif stage == "modeller":
        current = evaluate(root, request, recorded["candidate"]["path"], comparator=True)
    else:
        public = DiffusionRequest.from_json((source / "requests/protenix-seed7.json").read_text())
        published = read_published_bundle(root / "protenix_homology_diffusion", request=public,
            source_root=source / "protenix-materialized", work_parent=args.work_parent)
        current = evaluate(root, request, recorded["candidate"]["path"])
        if published.status != recorded["publication_status"]:
            raise ValueError("public Homology status differs from its bounded bundle")
        validate_background(root, request, recorded["candidate"]["path"])
    for key, value in current.items():
        if not equivalent(value, recorded.get(key)):
            raise ValueError(f"independent holdout evaluation differs: {stage}/{job['case_id']}/seed{job['seed']}:{key}")
    row["independently_revalidated"] = True
    return row


def export_visual(args, manifest, stages):
    if args.visual.exists():
        raise ValueError("visual review destination must be new")
    args.visual.mkdir(parents=True)
    indexed = {(stage, row["case_id"], row["seed"]): row for stage, rows in stages.items() for row in rows}
    index = []
    for case in manifest["cases"]:
        if case["status"] != "eligible":
            continue
        source = args.cohort / case["case_id"]
        for seed in manifest["seeds"]:
            directory = args.visual / case["case_id"] / f"seed{seed}"
            directory.mkdir(parents=True)
            shutil.copyfile(source / "reference.pdb", directory / "01_known_reference.pdb")
            shutil.copyfile(source / "input/normalized.pdb", directory / "02_gapped_input.pdb")
            row_data = {"case_id": case["case_id"], "source_id": case["source_id"], "seed": seed, "length": case["length"], "stratum": case["stratum"]}
            for stage, output_name in (("raw", "03_cc89_raw.pdb"), ("refine", "04_cc89_after_refinement.pdb"), ("modeller", "05_modeller.pdb"), ("protenix", "06_public_protenix.pdb")):
                stage_seed = seed if stage in {"raw", "refine"} else 7
                outcome = indexed.get((stage, case["case_id"], stage_seed))
                if outcome is None:
                    continue
                row_data[stage] = outcome
                if outcome["status"] == "evaluated":
                    path = args.results / stage / case["case_id"] / f"seed{stage_seed}" / outcome["candidate"]["path"]
                    if sha(path) != outcome["candidate"]["sha256"]:
                        raise ValueError("visual export candidate digest mismatch")
                    shutil.copyfile(path, directory / output_name)
            (directory / "result.json").write_text(json.dumps(row_data, indent=2, sort_keys=True) + "\n")
            (directory / "identity-mapping.json").write_text(json.dumps(case["identity_mapping"], indent=2) + "\n")
            index.append({**{k: row_data[k] for k in ("case_id", "source_id", "seed", "length", "stratum")},
                "raw_passed": row_data.get("raw", {}).get("validation", {}).get("passed", False),
                "refine_status": row_data.get("refine", {}).get("status", "pending"),
                "refine_passed": row_data.get("refine", {}).get("validation", {}).get("passed", False),
                "directory": directory.relative_to(args.visual).as_posix()})
    with (args.visual / "index.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(index[0]))
        writer.writeheader()
        writer.writerows(index)
    (args.visual / "README.md").write_text("# Known-sequence structural holdout\n\n01 is evaluation-only; 02 is the actual gapped input. 03/04 are cc89 raw/postprocessing outputs. Missing 04 means no refined output was accepted for scoring; see result.json. Rejected inspection coordinates remain labelled rejected. 05 is the unconstrained single-model MODELLER comparator, repeated for viewing beside each cc89 seed. 06 is present only for the four public Homology workflow controls. Target sequences are the original observed sequences; no substitutions or new sequences are introduced.\n")


def analyze(args):
    manifest = json.loads(args.manifest.read_text())
    protocol = json.loads(args.protocol.read_text())
    if protocol["manifest_sha256"] != sha(args.manifest):
        raise ValueError("holdout manifest/protocol mismatch")
    audit_inputs(args, manifest)
    cases = {c["case_id"]: c for c in manifest["cases"]}
    stages = {stage: [validate_job(args, protocol, cases[job["case_id"]], stage, job) for job in protocol["jobs"][stage]] for stage in STAGES}
    pending = sum(row["status"] == "pending" for rows in stages.values() for row in rows)
    if pending and not args.allow_partial:
        raise ValueError(f"holdout has {pending} pending jobs; no complete report is emitted")
    report = {"complete": pending == 0, "pending": pending, "manifest_sha256": sha(args.manifest), "protocol_sha256": sha(args.protocol),
        "producer_sha256": sha(Path(__file__).resolve()), "stages": stages,
        "summaries": {stage: summarize(rows) for stage, rows in stages.items()},
        "by_stratum": {stratum: {stage: summarize([row for row in rows if row["stratum"] == stratum]) for stage, rows in stages.items()}
                       for stratum in sorted({case["stratum"] for case in manifest["cases"]})},
        "by_length": {str(length): {stage: summarize([row for row in rows if row["length"] == length]) for stage, rows in stages.items()}
                      for length in sorted({case["length"] for case in manifest["cases"]})},
        "by_source": {source: {stage: summarize([row for row in rows if row["source_id"] == source]) for stage, rows in stages.items()}
                      for source in sorted({case["source_id"] for case in manifest["cases"]})},
        "interpretation": protocol["comparison"], "public_promotion": False,
        "input_audit": "exact source-minus-mask coordinates; only already-masked templates; unchanged known target sequences; preserved OXT explicitly outside atom37 conditioning"}
    if args.output.exists():
        raise ValueError("analysis output must be new")
    with args.output.open("x") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.visual:
        export_visual(args, manifest, stages)
    print(json.dumps(report["summaries"], indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    capture = commands.add_parser("snapshot")
    for name in ("protocol", "output"):
        capture.add_argument("--" + name, type=Path, required=True)
    analysis = commands.add_parser("analyze")
    for name in ("manifest", "protocol", "cohort", "results", "output", "work-parent"):
        analysis.add_argument("--" + name, type=Path, required=True)
    analysis.add_argument("--visual", type=Path)
    analysis.add_argument("--clean-cohort", type=Path, default=ROOT / ".artifacts/clean-protein-expanded-cohort-v2")
    analysis.add_argument("--antibody-sources", type=Path, default=ROOT / ".artifacts/known-sequence-antibody-sources-v1")
    analysis.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    for name, value in vars(args).copy().items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    {"snapshot": snapshot, "analyze": analyze}[args.action](args)


if __name__ == "__main__":
    main()
