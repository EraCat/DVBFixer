import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dvbfixer.homology import _make_model_with_loop_fallback, main


class _BaseModel:
    outputs = [{"failure": None, "name": "model.pdb", "molpdf": 1.0}]

    def __init__(self, env, **kwargs):
        self.env = env
        self.kwargs = kwargs
        self.loop = SimpleNamespace()


def test_no_loop_alignment_falls_back_to_automodel():
    class NoLoopModel(_BaseModel):
        def make(self):
            raise RuntimeError("No loops detected for refinement: you must redefine select_loop_atoms")

    class AutoModel(_BaseModel):
        def make(self):
            self.made = True

    model, used_loops = _make_model_with_loop_fallback(
        object(), AutoModel, NoLoopModel, "alignment.pir", ("template",),
        "target", 2, False, "fast",
    )
    assert isinstance(model, AutoModel)
    assert model.made
    assert used_loops is False


def test_unrelated_modeller_error_is_not_hidden():
    class BrokenLoopModel(_BaseModel):
        def make(self):
            raise RuntimeError("Sequence difference between alignment and pdb")

    with pytest.raises(RuntimeError, match="Sequence difference"):
        _make_model_with_loop_fallback(
            object(), _BaseModel, BrokenLoopModel, "alignment.pir", "template",
            "target", 1, False, "fast",
        )


@pytest.mark.parametrize(("model", "profile"), [
    ("protenix", "protenix-v1-cuda"),
    ("protpardelle", "protpardelle-1c-mps"),
])
def test_homology_diffusion_dispatches_materialized_mosaic_with_ownership(
    tmp_path,
    monkeypatch,
    model,
    profile,
):
    from dvbfixer.model.diffusion.runtime import DiffusionRuntime

    # This tests dispatch/ownership, not deployment discovery. CI has no ML
    # launchers; a developer's installed launcher must not decide test behavior.
    runtime = DiffusionRuntime(model, profile, str(tmp_path / "unused-runner"))
    monkeypatch.setattr(
        "dvbfixer.model.diffusion.runtime._installed_runner", lambda _name: None,
    )
    selected_models = []

    def resolve_runtime(selected_model):
        selected_models.append(selected_model)
        return runtime

    monkeypatch.setattr(
        "dvbfixer.model.diffusion.runtime.resolve_diffusion_runtime", resolve_runtime,
    )
    template = tmp_path / "template.pdb"
    template.write_text(
        "ATOM      1  CA  ALA A   1       1.000   0.000   0.000  1.00 20.00           C  \n"
        "ATOM      2  CA  ALA A   5       5.000   0.000   0.000  1.00 20.00           C  \n"
    )
    fasta = tmp_path / "target.fasta"
    fasta.write_text(">A\nASGGA\n")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({
        "templates": [{
            "id": "known",
            "path": str(template),
            "chain": "A",
            "targetChain": "A",
        }],
        "alignmentGroups": [{
            "chainId": "A",
            "rows": [
                {"id": "A", "kind": "target", "sequence": "ASGGA"},
                {
                    "id": "known",
                    "kind": "template",
                    "templateId": "known",
                    "sequence": "A---A",
                },
            ],
            "masks": {},
            "maskModes": {"known": "all"},
        }],
    }))
    captured = []

    def capture(args):
        from dvbfixer.model.diffusion.contract import DiffusionRequest
        captured.append((args, DiffusionRequest.from_json(Path(args.diffusion_request).read_text())))

    monkeypatch.setattr(
        "dvbfixer.model.diffusion_cli.run_diffusion_model",
        capture,
    )

    main([
        str(fasta),
        "--template-plan",
        str(plan),
        "--backend",
        "diffusion",
        "--diffusion-model",
        model,
        "-o",
        str(tmp_path / "model"),
    ])

    assert len(captured) == 1
    assert selected_models == [model]
    args, request = captured[0]
    assert args.diffusion_model == model
    assert Path(args.input).name == "mosaic_diffusion_input.pdb"
    assert request.target_sequences[0].sequence == "ASGGA"
    assert [(item.target_index, item.template_id) for item in request.template_ownership] == [
        (0, "known"),
        (4, "known"),
    ]
    assert args.output == str(tmp_path / "model") + "_homology_diffusion"
