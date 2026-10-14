#!/usr/bin/env python3
"""Freeze mosaic-first joint, multi-span, edit, and multi-template acceptance plans."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from dvbfixer.homology_plan import build_mosaic_diffusion_request, materialize_template_plan
from dvbfixer.model.diffusion.contract import DiffusionRequest, ProteinContextPolicy
from dvbfixer.model.diffusion.protein_context import select_protein_context


def materialize(cohort, output, manifest_path):
    if output.exists() or manifest_path.exists():
        raise ValueError("Homology cohort and manifest must be new")
    request = DiffusionRequest.from_json((cohort / "1emv-joint/request.json").read_text())
    source = (cohort / "1emv-joint/reference.pdb").resolve()
    output.mkdir(parents=True)
    cases = []
    for scenario in ("joint-vh-vl", "multiple-spans", "substitution", "deletion", "multiple-templates"):
        root = output / scenario
        root.mkdir()
        groups = []
        templates = []
        fasta = []
        for index, target in enumerate(request.target_sequences):
            logical = ("VH", "VL")[index] if scenario == "joint-vh-vl" else target.chain
            original = target.sequence
            sequence = original
            gap = next(gap for gap in request.gaps if gap.chain == target.chain)
            edit_index = gap.target_interval.start + 2
            if index == 0 and scenario == "substitution":
                sequence = sequence[:edit_index] + ("S" if sequence[edit_index] != "S" else "A") + sequence[edit_index + 1:]
            if index == 0 and scenario == "deletion":
                sequence = sequence[:edit_index] + "-" + sequence[edit_index + 1:]
            fasta.append(f">{logical}\n{sequence.replace('-', '')}\n")
            identity = f"reference-{logical}"
            templates.append({"id": identity, "path": str(source), "chain": target.chain, "targetChain": logical})
            missing = set()
            if scenario == "joint-vh-vl" or index == 0 and scenario in {"multiple-spans", "multiple-templates"}:
                missing.update(range(gap.target_interval.start, gap.target_interval.stop))
            if index == 0 and scenario == "multiple-spans":
                second = next(start for start in range(gap.target_interval.stop + 5, len(original) - 6)
                              if "C" not in original[start:start + 5])
                missing.update(range(second, second + 5))
            ranges = []
            for position in range(len(original)):
                if position in missing:
                    continue
                if ranges and ranges[-1]["end"] == position:
                    ranges[-1]["end"] += 1
                else:
                    ranges.append({"start": position, "end": position + 1})
            rows = [{"id": logical, "kind": "target", "sequence": sequence},
                    {"id": identity, "kind": "template", "templateId": identity, "sequence": original}]
            masks = {identity: ranges}
            modes = {identity: "ranges"}
            if scenario == "multiple-templates":
                shifted = root / "translated_reference.pdb"
                if not shifted.exists():
                    shifted.write_text("".join(line[:30] + f"{float(line[30:38]) + 25:8.3f}" + line[38:]
                                               if line.startswith("ATOM") else line for line in source.read_text().splitlines(keepends=True)))
                other = f"fitted-{logical}"
                templates.append({"id": other, "path": str(shifted.resolve()), "chain": target.chain, "targetChain": logical})
                rows.append({"id": other, "kind": "template", "templateId": other, "sequence": original})
                midpoint = len(original) // 2
                masks[identity] = [{"start": span["start"], "end": min(span["end"], midpoint)} for span in ranges if span["start"] < midpoint]
                masks[other] = [{"start": max(span["start"], midpoint), "end": span["end"]} for span in ranges if span["end"] > midpoint]
                modes[other] = "ranges"
            groups.append({"chainId": logical, "rows": rows, "masks": masks, "maskModes": modes})
        plan = root / "template-plan.json"
        plan.write_text(json.dumps({"templates": templates, "alignmentGroups": groups}, indent=2) + "\n")
        target_path = root / "target.fasta"
        target_path.write_text("".join(fasta))
        work = root / "materialized"
        materialize_template_plan(plan, work)
        covered_edits = scenario in {"substitution", "deletion"}
        source_path, request_path = build_mosaic_diffusion_request(work / "selected_template_mosaic.coverage.json",
                    [(group["chainId"], group["rows"][0]["sequence"].replace("-", "")) for group in groups], work,
                    seeds=(7,), regenerate_covered=covered_edits, profile="protenix-v1-cuda")
        context_request = select_protein_context(DiffusionRequest.from_json(request_path.read_text()), source_path.read_bytes(), ProteinContextPolicy(partner_mode="full"))
        (root / "context-request.json").write_text(context_request.to_json())
        if not covered_edits:
            full_groups = json.loads(json.dumps(groups))
            for group in full_groups:
                group["maskModes"] = {row["id"]: "all" for row in group["rows"] if row["kind"] == "template"}
            reference_plan = root / "reference-plan.json"
            reference_plan.write_text(json.dumps({"templates": templates, "alignmentGroups": full_groups}, indent=2) + "\n")
            materialize_template_plan(reference_plan, root / "reference-materialized")
        cases.append({"case_id": scenario, "regenerate_covered": covered_edits,
                      "gap_count": len(context_request.gaps), "gap_chains": sorted({gap.chain for gap in context_request.gaps}),
                      "artifacts": {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                    for path in root.rglob("*") if path.is_file()},
                      "template_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    manifest = {"schema_version": 1, "status": "frozen-before-homology-inference", "seed": 7, "no_replacement": True,
                "context": "full", "cases": cases, "comparison": "identical-template-plan-and-target-MODELLER-single-candidate-md-none",
                "limits": ["synthetic logical VH/VL engineering mapping; source is not an antibody",
                           "covered edits have no experimentally solved mutant reference", "no threshold changes"]}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    manifest = materialize(args.cohort, args.output, args.manifest)
    print(json.dumps([{key: case[key] for key in ("case_id", "gap_count", "gap_chains")} for case in manifest["cases"]], indent=2))


if __name__ == "__main__":
    main()
