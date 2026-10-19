#!/usr/bin/env python3
"""Check real Protenix feature atom coverage without loading a model/checkpoint."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from run_a100_relaxation import sha, verify_inventory
from run_protein_context_ablations import _load

from dvbfixer.model.diffusion.contract import DiffusionRequest

ROOT = Path(__file__).resolve().parents[1]


def preflight(args):
    from configs.configs_base import configs as configs_base
    from configs.configs_data import data_configs
    from configs.configs_inference import inference_configs
    from configs.configs_model_type import model_configs
    from ml_collections.config_dict import ConfigDict
    from protenix.config.config import parse_configs
    from protenix.data.inference.infer_dataloader import get_inference_dataloader

    manifest = json.loads(args.manifest.read_text())
    work = args.output.parent / "engine-preflight-work"
    work.mkdir(exist_ok=True)
    _load("reinjection", ROOT / "deploy/protenix-v1/reinjection.py")
    adapter = _load("clean_feature_adapter", ROOT / "deploy/protenix-v1/checkpoint_gap_smoke.py")
    rows = []
    for case in manifest["cases"]:
        root = (args.cohort / "cases" / case["case_id"]).resolve()
        verify_inventory(root, case["artifacts"])
        request = DiffusionRequest.from_json((root / "request.json").read_text())
        configs = parse_configs(configs={**configs_base, "data": data_configs, **inference_configs,
            "model_name": "protenix_base_default_v1.0.0"}, fill_required_with_null=True)
        configs.update(ConfigDict(model_configs["protenix_base_default_v1.0.0"]))
        configs.model_name = "protenix_base_default_v1.0.0"
        configs.input_json_path = str(root / "preflight-features/input.json")
        configs.dump_dir = str(work.resolve())
        configs.num_workers = 0
        configs.seeds = list(request.seeds)
        configs.use_template = True
        configs.use_msa = False
        configs.use_rna_msa = False
        configs.use_seeds_in_json = False
        configs.need_atom_confidence = False
        configs.dtype = "bf16"
        configs.data.template.kalign_binary_path = str(args.kalign.resolve())
        try:
            data, atom_array, error = next(iter(get_inference_dataloader(configs=configs)))[0]
            if error:
                raise ValueError(error)
            axis, _, _ = adapter._model_atom_axis(atom_array, request)
            required = set(request.fixed_atoms) | set(request.generated_atoms)
            missing = required - set(axis)
            if missing:
                raise ValueError("engine features omit required full-source atoms: " + json.dumps([asdict(atom) for atom in sorted(missing)], sort_keys=True))
            row = {"case_id": case["case_id"], "source_id": case["source_id"], "status": "supported",
                "required_atom_count": len(required), "model_atom_count": len(axis), "token_count": int(data["N_token"])}
        except Exception as exc:
            row = {"case_id": case["case_id"], "source_id": case["source_id"], "status": "unsupported-features",
                "exception_type": type(exc).__name__, "reason": str(exc)}
        rows.append(row)
        print(json.dumps(row), flush=True)
        args.output.write_text(json.dumps({"complete": False, "manifest_sha256": sha(args.manifest), "cases": rows}, indent=2, sort_keys=True) + "\n")
    report = {"complete": True, "manifest_sha256": sha(args.manifest), "cases": rows,
        "model_loaded": False, "checkpoint_loaded": False, "inference_run": False,
        "all_required_atoms_represented": all(row["status"] == "supported" for row in rows)}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"complete": True, "cases": len(rows), "supported": sum(row["status"] == "supported" for row in rows)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "cohort", "kalign", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    preflight(parser.parse_args())


if __name__ == "__main__":
    main()
