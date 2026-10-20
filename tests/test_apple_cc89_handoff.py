"""Portable Apple controls preserve sources and withhold gap coordinates."""

import importlib
import json
from pathlib import Path

from dvbfixer.model.diffusion.contract import DiffusionRequest


def test_fresh_clone_controls_need_no_linux_archives_or_checkpoint(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    helper = importlib.import_module("prepare_apple_cc89_handoff")
    masking = importlib.import_module("materialize_cc89_known_sequence_holdout")
    output = tmp_path / "controls"
    helper.materialize(output)
    report = json.loads((output / "inputs.json").read_text())
    assert len(report["requests"]) == 8
    assert report["inference_executed"] is False
    assert report["corrected_mps_port_status"] == "not-yet-implemented"
    for row in report["requests"]:
        directory = output / row["case_id"]
        request = DiffusionRequest.from_json((directory / f"request-seed{row['seed']}.json").read_text())
        generated = {(r.chain, r.residue_number, r.insertion_code) for gap in request.gaps for r in gap.generated_residues}
        assert not (directory / "reference.pdb").exists()
        reference = (output / "evaluation" / row["case_id"] / "reference.pdb").read_bytes()
        masking.assert_mask_only(reference, (directory / request.normalized_pdb.path).read_bytes(), generated)
        masking.assert_mask_only(reference, (directory / "masked-template.pdb").read_bytes(), generated)
        assert row["request_sha256"] == helper.sha(directory / f"request-seed{row['seed']}.json")
