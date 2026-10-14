import json
import shutil
from pathlib import Path

import pytest

from dvbfixer.homology_plan import (
    build_mosaic_diffusion_request,
    materialize_template_plan,
    prepare_mosaic_diffusion_inputs,
)
from dvbfixer.model.diffusion.contract import DiffusionRequest


def _atom(serial, residue, number, x):
    return (f"ATOM  {serial:5d}  CA  {residue} A{number:4d}    "
            f"{x:8.3f}   0.000   0.000  1.00 20.00           C  \n")


def test_template_plan_builds_one_fitted_mosaic(tmp_path, monkeypatch):
    left = tmp_path / "left.pdb"
    right = tmp_path / "right.pdb"
    left.write_text(_atom(1, "ALA", 1, 1) + _atom(2, "GLY", 2, 2))
    right.write_text(_atom(1, "ALA", 1, 31) + _atom(2, "GLY", 2, 32))

    def fake_fit(specs, output, fit_dir, **kwargs):
        fit_dir.mkdir(parents=True)
        fitted = []
        for index, spec in enumerate(specs, 1):
            source_text, chain = spec.rsplit(":", 1)
            target = fit_dir / f"template_{index}_{chain}_fit.pdb"
            shutil.copy2(source_text, target)
            fitted.append(target)
        output.write_text("test\n")
        return fitted

    monkeypatch.setattr("dvbfixer.homology_plan.run_biopython_superposition", fake_fit)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({
        "templates": [
            {"id": "left", "path": str(left), "chain": "A", "targetChain": "A"},
            {"id": "right", "path": str(right), "chain": "A", "targetChain": "A"},
        ],
        "alignmentGroups": [{
            "chainId": "A",
            "rows": [
                {"id": "A", "kind": "target", "sequence": "AG"},
                {"id": "left", "kind": "template", "templateId": "left", "sequence": "AG"},
                {"id": "right", "kind": "template", "templateId": "right", "sequence": "AG"},
            ],
            "masks": {"left": [{"start": 0, "end": 1}], "right": [{"start": 1, "end": 2}]},
            "maskModes": {"left": "ranges", "right": "ranges"},
        }],
    }))
    templates, alignment = materialize_template_plan(plan, tmp_path / "work")
    assert len(templates) == 1
    mosaic = (tmp_path / "work" / "selected_template_mosaic.pdb").read_text()
    assert "   1.000" in mosaic
    assert "  32.000" in mosaic
    assert ">P1;selected_template_mosaic" in open(alignment).read()
    coverage = json.loads(
        (tmp_path / "work" / "selected_template_mosaic.coverage.json").read_text()
    )
    assert coverage["maskConvention"] == "zero-based-half-open"
    assert coverage["overlapPolicy"] == "earlier-template-wins"
    assert [item["templateId"] for item in coverage["groups"][0]["coverage"]] == [
        "left",
        "right",
    ]
    assert [item["pdbResidue"]["residueNumber"] for item in coverage["groups"][0]["coverage"]] == [
        "1",
        "2",
    ]


def test_vh_vl_groups_get_distinct_pdb_chain_ids(tmp_path):
    template = tmp_path / "complex.pdb"
    template.write_text(
        _atom(1, "ALA", 1, 1).replace(" A   1", " H   1") +
        _atom(2, "GLY", 1, 2).replace(" A   1", " L   1")
    )
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({
        "templates": [
            {"id": "heavy", "path": str(template), "chain": "H", "targetChain": "VH"},
            {"id": "light", "path": str(template), "chain": "L", "targetChain": "VL"},
        ],
        "alignmentGroups": [
            {"chainId": "VH", "rows": [
                {"id": "VH", "kind": "target", "sequence": "A"},
                {"id": "heavy", "kind": "template", "templateId": "heavy", "sequence": "A"},
            ], "masks": {}, "maskModes": {"heavy": "all"}},
            {"chainId": "VL", "rows": [
                {"id": "VL", "kind": "target", "sequence": "G"},
                {"id": "light", "kind": "template", "templateId": "light", "sequence": "G"},
            ], "masks": {}, "maskModes": {"light": "all"}},
        ],
    }))
    templates, _ = materialize_template_plan(plan, tmp_path / "work")
    atom_lines = [line for line in open(templates[0]) if line.startswith("ATOM")]
    assert [line[21] for line in atom_lines] == ["H", "L"]


def test_mosaic_diffusion_inputs_preserve_ownership_and_chain_mapping(tmp_path):
    coverage = tmp_path / "selected_template_mosaic.coverage.json"
    coverage.write_text(json.dumps({
        "schemaVersion": 1,
        "groups": [{
            "targetChain": "VH",
            "pdbChain": "H",
            "targetSequence": "AGST",
            "coverage": [
                {
                    "targetIndex": index,
                    "targetResidue": residue,
                    "covered": index in {0, 3},
                    "templateId": "left" if index == 0 else "right" if index == 3 else None,
                    "templateResidue": residue if index in {0, 3} else None,
                    "pdbResidue": {
                        "chain": "H",
                        "residueNumber": str(index + 1),
                        "insertionCode": "",
                    },
                }
                for index, residue in enumerate("AGST")
            ],
        }],
    }))

    fasta, ownership = prepare_mosaic_diffusion_inputs(
        coverage,
        [("VH", "AGST")],
        tmp_path,
    )

    assert fasta.read_text() == ">H\nAGST\n"
    assert [(item.chain, item.target_index, item.template_id) for item in ownership] == [
        ("H", 0, "left"),
        ("H", 3, "right"),
    ]


def test_mosaic_diffusion_rejects_covered_substitution(tmp_path):
    coverage = tmp_path / "selected_template_mosaic.coverage.json"
    coverage.write_text(json.dumps({
        "schemaVersion": 1,
        "groups": [{
            "targetChain": "A",
            "pdbChain": "A",
            "targetSequence": "AGGG",
            "coverage": [
                {
                    "targetIndex": index,
                    "targetResidue": "A" if index == 0 else "G",
                    "covered": index != 2,
                    "templateId": "template" if index != 2 else None,
                    "templateResidue": "S" if index == 1 else "A" if index == 0 else "G" if index == 3 else None,
                    "pdbResidue": {
                        "chain": "A",
                        "residueNumber": str(index + 1),
                        "insertionCode": "",
                    },
                }
                for index in range(4)
            ],
        }],
    }))

    with pytest.raises(ValueError, match="covered substitutions"):
        prepare_mosaic_diffusion_inputs(coverage, [("A", "AGGG")], tmp_path)


@pytest.mark.parametrize("scenario", ["multiple", "substitution", "deletion", "joint"])
def test_explicit_mosaic_requests_keep_authoritative_positions_and_edit_ownership(tmp_path, scenario):
    template = tmp_path / "template.pdb"
    chains = ("D", "d") if scenario == "joint" else ("A",)
    template.write_text("".join(_atom(index + 1 + offset * 14, "ALA", index + 1, index * 3.8)
                               .replace("ALA A", f"ALA {chain}")
                               for offset, chain in enumerate(chains) for index in range(14)) + "END\n")
    target = "A" * 14
    if scenario == "substitution":
        target = target[:6] + "S" + target[7:]
    if scenario == "deletion":
        target = target[:6] + "-" + target[7:]
    groups = []
    for chain in chains:
        spans = [{"start": 0, "end": 1}, {"start": 4, "end": 14}] if scenario == "joint" else (
            [{"start": 0, "end": 1}, {"start": 4, "end": 9}, {"start": 12, "end": 14}]
            if scenario == "multiple" else [])
        groups.append({"chainId": chain, "rows": [
            {"id": chain, "kind": "target", "sequence": target},
            {"id": f"known-{chain}", "kind": "template", "templateId": f"known-{chain}", "sequence": "A" * 14},
        ], "masks": {f"known-{chain}": spans}, "maskModes": {f"known-{chain}": "ranges" if spans else "all"}})
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"templates": [{"id": f"known-{chain}", "path": str(template), "chain": chain, "targetChain": chain}
                                            for chain in chains], "alignmentGroups": groups}))
    work = tmp_path / "work"
    materialize_template_plan(plan, work)
    coverage = work / "selected_template_mosaic.coverage.json"
    if scenario in {"substitution", "deletion"}:
        with pytest.raises(ValueError, match="substitutions|deletions"):
            build_mosaic_diffusion_request(coverage, [(chain, target.replace("-", "")) for chain in chains], work, seeds=(7,))
    input_path, request_path = build_mosaic_diffusion_request(coverage, [(chain, target.replace("-", "")) for chain in chains], work,
                                                          seeds=(7, 19), regenerate_covered=scenario in {"substitution", "deletion"})
    request = DiffusionRequest.from_json(request_path.read_text())
    assert request.seeds == (7, 19)
    assert {item.chain for item in request.target_sequences} == set(chains)
    assert {owner.residue for owner in request.template_ownership}.isdisjoint(
        {residue for gap in request.gaps for residue in gap.generated_residues})
    assert all(atom.residue_number not in {residue.residue_number for gap in request.gaps if gap.chain == atom.chain
                                         for residue in gap.generated_residues} for atom in request.fixed_atoms)
    if scenario == "multiple":
        assert [(gap.target_interval.start, gap.target_interval.stop) for gap in request.gaps] == [(1, 4), (9, 12)]
        assert request.sequence_placements[0].observed_target_indices == (0, 4, 5, 6, 7, 8, 12, 13)
    elif scenario == "joint":
        assert [gap.chain for gap in request.gaps] == ["D", "d"]
    else:
        assert len(request.gaps) == 1
        assert request.regenerated_template_ownership
        assert {owner.residue for owner in request.regenerated_template_ownership} == set(request.gaps[0].generated_residues)
        assert not any(line[22:26].strip() in {residue.residue_number for residue in request.gaps[0].generated_residues}
                       for line in input_path.read_text().splitlines() if line.startswith("ATOM"))


@pytest.mark.parametrize("distance, linked", [(2.05, True), (12.0, False)])
def test_covered_regeneration_cannot_erase_an_existing_disulfide(tmp_path, distance, linked):
    template = tmp_path / "template.pdb"
    sequence = "AACAAAACAAA"
    lines = []
    for index, aa in enumerate(sequence):
        name = "CYS" if aa == "C" else "ALA"
        lines.append(_atom(len(lines) + 1, name, index + 1, index * 3.8))
        if aa == "C":
            point = 0 if index == 2 else distance
            lines.append(_atom(len(lines) + 1, name, index + 1, point).replace(" CA ", " SG ").replace(" C  \n", " S  \n"))
    template.write_text("".join(lines) + "END\n")
    target = sequence[:2] + "S" + sequence[3:]
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"templates": [{"id": "known", "path": str(template), "chain": "A", "targetChain": "A"}],
        "alignmentGroups": [{"chainId": "A", "rows": [{"id": "A", "kind": "target", "sequence": target},
            {"id": "known", "kind": "template", "sequence": sequence}], "maskModes": {"known": "all"}}]}))
    work = tmp_path / "work"
    materialize_template_plan(plan, work)
    before = (work / "selected_template_mosaic.pdb").read_bytes()
    if linked:
        with pytest.raises(ValueError, match="disulfide-linked"):
            build_mosaic_diffusion_request(work / "selected_template_mosaic.coverage.json", [("A", target)], work,
                                          seeds=(7,), regenerate_covered=True)
        assert not (work / "mosaic_diffusion_input.pdb").exists()
    else:
        build_mosaic_diffusion_request(work / "selected_template_mosaic.coverage.json", [("A", target)], work,
                                      seeds=(7,), regenerate_covered=True)
    assert (work / "selected_template_mosaic.pdb").read_bytes() == before


def test_modeller_comparator_mapping_preserves_original_and_case_distinct_chains(tmp_path, monkeypatch):
    import importlib.util
    from types import SimpleNamespace

    script = Path(__file__).resolve().parents[1] / "scripts/run_context_homology_acceptance.py"
    monkeypatch.syspath_prepend(str(script.parent))
    spec = importlib.util.spec_from_file_location("context_comparator", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = tmp_path / "model.pdb"
    payload = (_atom(1, "ALA", 1, 1).replace("ALA A", "ALA D") + "TER       2      ALA D   1\n"
               + _atom(2, "GLY", 2, 2).replace("GLY A", "GLY d"))
    original.write_text(payload)
    destination = tmp_path / "comparator.pdb"
    request = SimpleNamespace(target_sequences=[SimpleNamespace(chain="D", sequence="A"), SimpleNamespace(chain="d", sequence="G")])
    mapping = module.normalize_comparator_ids(original, destination, request)
    assert original.read_text() == payload
    assert [line[21:27] for line in destination.read_text().splitlines() if line.startswith("ATOM")] == ["D   1 ", "d   1 "]
    assert len(destination.read_text().splitlines()) == 3
    assert mapping[1]["original_residue_number"] == "2"
    request.target_sequences[1].sequence = "A"
    with pytest.raises(ValueError, match="complete declared target"):
        module.normalize_comparator_ids(original, tmp_path / "bad.pdb", request)
    assert not (tmp_path / "bad.pdb").exists()
