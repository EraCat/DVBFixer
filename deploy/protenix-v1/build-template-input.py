"""Build exact single-chain or selected-context Protenix template inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import gemmi

from dvbfixer.model.diffusion.contract import DiffusionRequest
from dvbfixer.model.diffusion.protein_context import sampling_entities, validate_context_source


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_input(request_path: Path, output_dir: Path) -> Path:
    request_path = request_path.resolve()
    request = DiffusionRequest.from_json(request_path.read_text(encoding="utf-8"))
    if request.protein_context is not None:
        return _build_context_input(request_path, request, output_dir)
    if len(request.target_sequences) != 1 or len(request.gaps) != 1:
        raise ValueError("Protenix hook smoke requires one target chain and one gap")
    target = request.target_sequences[0]
    placement = request.sequence_placements[0]
    if target.chain != placement.chain or request.gaps[0].chain != target.chain:
        raise ValueError("target, placement, and gap chains must match")
    if any(atom.chain != target.chain for atom in (*request.fixed_atoms, *request.generated_atoms)):
        raise ValueError("Protenix hook smoke accepts target-chain-only structures")

    pdb_path = (request_path.parent / request.normalized_pdb.path).resolve()
    if _sha256(pdb_path) != request.normalized_pdb.sha256:
        raise ValueError("normalized PDB digest mismatch")
    structure = gemmi.read_structure(str(pdb_path))
    structure.setup_entities()
    mmcif = structure.make_mmcif_document().as_string()

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    template_path = output_dir / "template.json"
    template_path.write_text(
        json.dumps(
            [
                {
                    "mmcif": mmcif,
                    "queryIndices": list(placement.observed_target_indices),
                    "templateIndices": list(range(len(placement.observed_target_indices))),
                }
            ],
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    input_path = output_dir / "input.json"
    input_path.write_text(
        json.dumps(
            [
                {
                    "name": "dvbfixer_protenix_gap_smoke",
                    "sequences": [
                        {
                            "proteinChain": {
                                "sequence": target.sequence,
                                "count": 1,
                                "templatesPath": str(template_path),
                            }
                        }
                    ],
                    "modelSeeds": list(request.seeds),
                }
            ],
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return input_path


def _build_context_input(request_path: Path, request: DiffusionRequest, output_dir: Path) -> Path:
    source = request_path.parent / request.normalized_pdb.path
    validate_context_source(request, source.read_bytes())
    structure = gemmi.read_structure(str(source))
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    sequences = []
    for index, entity in enumerate(sampling_entities(request)):
        selected = {(residue.residue_number, residue.insertion_code) for residue in entity.placement.observed_residues}
        template = gemmi.Structure()
        model = gemmi.Model("1")
        chain = gemmi.Chain(entity.engine_chain)
        for residue in structure[0][entity.target.chain]:
            key = (str(residue.seqid.num), residue.seqid.icode.strip())
            if key in selected:
                chain.add_residue(residue.clone())
        model.add_chain(chain)
        template.add_model(model)
        template.setup_entities()
        path = output_dir / f"template-{index}.json"
        path.write_text(json.dumps([{
            "mmcif": template.make_mmcif_document().as_string(),
            "queryIndices": list(entity.placement.observed_target_indices),
            "templateIndices": list(range(len(entity.placement.observed_residues))),
        }], separators=(",", ":")))
        sequences.append({"proteinChain": {"sequence": entity.target.sequence, "count": 1,
                                           "id": [entity.engine_chain], "templatesPath": str(path)}})
    input_path = output_dir / "input.json"
    input_path.write_text(json.dumps([{"name": "dvbfixer_protenix_context", "sequences": sequences,
                                       "modelSeeds": list(request.seeds)}], separators=(",", ":")))
    return input_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(build_input(args.request, args.output_dir))


if __name__ == "__main__":
    main()
