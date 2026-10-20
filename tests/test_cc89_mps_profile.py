"""Versioned Apple public admission, source positions and isolated refinement."""

import hashlib
import importlib
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from dvbfixer.model.diffusion.contract import (
    BackendOption,
    BackendProvenance,
    DiffusionContractError,
)
from dvbfixer.model.diffusion.protein_context import (
    CUDA_CC89_CONTEXT,
    MPS_CC89_PROFILE,
    ProteinContextError,
    context_evidence,
    prepare_cuda_cc89_request,
    prepare_mps_cc89_request,
    source_context_position_features,
    validate_mps_cc89_request,
)
from dvbfixer.model.diffusion.scope import assess_diffusion_scope
from dvbfixer.model.diffusion.trace import build_sampler_trace, validate_sampler_trace_context
from dvbfixer.model.diffusion_cli import build_cli_diffusion_request

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cli_fixture(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    return importlib.import_module("test_diffusion_cli")


def _load(relative):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location("apple_public_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_mps_auto_context_is_local_and_replay_is_exact(tmp_path, cli_fixture):
    source = cli_fixture._gap_input(tmp_path)
    request = build_cli_diffusion_request(source, {"C": "SNRFSGSKSGNTA"}, seeds=(7, 19), profile=MPS_CC89_PROFILE)
    with pytest.raises(ProteinContextError, match="frozen source-only"):
        validate_mps_cc89_request(request)
    selected = prepare_mps_cc89_request(request, source.read_bytes(), "auto")
    assert selected.protein_context.policy == CUDA_CC89_CONTEXT
    assert selected.seeds == (7, 19)
    assert assess_diffusion_scope(selected, source.read_bytes()).supported
    assert prepare_mps_cc89_request(selected, source.read_bytes(), "local") == selected
    with pytest.raises(ProteinContextError, match="declare its profile"):
        prepare_cuda_cc89_request(selected, source.read_bytes(), "auto")
    with pytest.raises(ProteinContextError, match="declare its profile"):
        prepare_mps_cc89_request(replace(selected, backend_options=tuple(
            BackendOption("profile", "protpardelle-1c-cuda") if option.name == "profile" else option
            for option in selected.backend_options)), source.read_bytes(), "auto")


@pytest.mark.parametrize("profile", [MPS_CC89_PROFILE, "protpardelle-1c-cuda"])
def test_homology_freezes_a_complete_corrected_request_before_cli_replay(tmp_path, cli_fixture, profile):
    from dvbfixer.homology_plan import build_mosaic_diffusion_request, materialize_template_plan
    from dvbfixer.model.diffusion.contract import DiffusionRequest

    source = cli_fixture._gap_input(tmp_path)
    plan = {"templates": [{"id": "observed", "path": str(source), "chain": "C", "targetChain": "C"}],
        "alignmentGroups": [{"chainId": "C", "maskModes": {"observed": "all"}, "masks": {}, "rows": [
            {"id": "C", "kind": "target", "sequence": "SNRFSGSKSGNTA"},
            {"id": "observed", "templateId": "observed", "kind": "template", "sequence": "SNRF-----GNTA"}]}]}
    path = tmp_path / "template-plan.json"
    path.write_text(json.dumps(plan))
    work = tmp_path / "materialized"
    materialize_template_plan(path, work)
    normalized, request_path = build_mosaic_diffusion_request(work / "selected_template_mosaic.coverage.json",
        [("C", "SNRFSGSKSGNTA")], work, seeds=(7,), profile=profile)
    request = DiffusionRequest.from_json(request_path.read_text())
    assert request.protein_context.policy == CUDA_CC89_CONTEXT
    assert assess_diffusion_scope(request, normalized.read_bytes()).supported
    prepare = prepare_mps_cc89_request if profile == MPS_CC89_PROFILE else prepare_cuda_cc89_request
    assert prepare(request, normalized.read_bytes(), "auto") == request


@pytest.mark.parametrize("mode", ["none", "full"])
def test_mps_rejects_explicit_nonlocal_context(tmp_path, cli_fixture, mode):
    source = cli_fixture._gap_input(tmp_path)
    request = build_cli_diffusion_request(source, {"C": "SNRFSGSKSGNTA"}, seeds=(7,), profile=MPS_CC89_PROFILE)
    with pytest.raises(ProteinContextError, match="auto\\|local"):
        prepare_mps_cc89_request(request, source.read_bytes(), mode)


def test_mps_rejects_cys_windows_and_multiple_gaps(tmp_path, cli_fixture):
    source = cli_fixture._gap_input(tmp_path)
    request = build_cli_diffusion_request(source, {"C": "SNRFCGSKSGNTA"}, seeds=(7,), profile=MPS_CC89_PROFILE)
    with pytest.raises(ProteinContextError, match="CYS-free"):
        prepare_mps_cc89_request(request, source.read_bytes(), "auto")
    source = cli_fixture._multichain_gap_input(tmp_path)
    request = build_cli_diffusion_request(source, {"C": "SNRFSGSKSGNTA", "D": "SNRFSGSKSGNTA"}, seeds=(7,), profile=MPS_CC89_PROFILE)
    with pytest.raises(ProteinContextError, match="one internal gap"):
        prepare_mps_cc89_request(request, source.read_bytes(), "auto")


def test_mps_public_numerical_policy_never_admits_cpu_or_cuda(tmp_path, cli_fixture):
    source = cli_fixture._gap_input(tmp_path)
    request = prepare_mps_cc89_request(build_cli_diffusion_request(source, {"C": "SNRFSGSKSGNTA"},
        seeds=(7,), profile=MPS_CC89_PROFILE), source.read_bytes(), "auto")
    adapter = _load("deploy/protpardelle-1c/checkpoint_gap_smoke.py")
    adapter._require_chain_phase_policy(request, "mps", "neutral-v1")
    adapter._require_position_feature_policy(request, "mps", "source-physical-v1", "neutral-v1")
    for device in ("cpu", "cuda", "mps:0"):
        with pytest.raises(ValueError, match="requires MPS"):
            adapter._require_chain_phase_policy(request, device, "neutral-v1")
    with pytest.raises(ValueError, match="explicitly declared"):
        adapter._require_chain_phase_policy(request, "mps", "native")
    assert adapter._sampler_profile("mps", False, False, False, True) == MPS_CC89_PROFILE


def test_mps_trace_requires_corrected_context_and_physical_position_provenance(tmp_path, cli_fixture):
    source = cli_fixture._gap_input(tmp_path)
    request = prepare_mps_cc89_request(build_cli_diffusion_request(source, {"C": "SNRFSGSKSGNTA"},
        seeds=(7,), profile=MPS_CC89_PROFILE), source.read_bytes(), "auto")
    atoms = tuple(item.atom for item in request.protein_context.fixed_conditioning)
    axis = (*atoms, *request.generated_atoms)
    trace = build_sampler_trace(profile=MPS_CC89_PROFILE, engine_repository="test://engine", engine_revision="test",
        patch_identity="sha256:627891e28d5055cb0d903f542af695569d7133b0480cab8f25d154dc8ccc78c9;cc89-chain-phase=neutral-v1;cc89-position-features=source-physical-v1",
        atom_order=axis, fixed_atoms=request.fixed_atoms, represented_fixed_atoms=atoms,
        device="mps", fallback_disabled=True, denoising_update_count=500, projection_errors_angstrom=(),
        final_fixed_coordinate_restoration=True, sampler_evidence_complete=True,
        protein_context_evidence=context_evidence(request, axis))
    positions, chains = source_context_position_features(request)
    digest = hashlib.sha256(np.asarray((positions, chains), dtype="<i8").tobytes()).hexdigest()
    provenance = BackendProvenance("test", 4, "test://engine", "test", device="mps",
        deterministic_flags=(f"cc89-position-features-sha256={digest}", "cc89-first-layer-rope-calls=1000"))
    validate_sampler_trace_context(trace, request, provenance)
    with pytest.raises(DiffusionContractError, match="source-position provenance"):
        validate_sampler_trace_context(trace, request, replace(provenance, deterministic_flags=()))
    with pytest.raises(DiffusionContractError, match="first-layer RoPE"):
        validate_sampler_trace_context(trace, request, replace(provenance, deterministic_flags=(provenance.deterministic_flags[0],)))
    for options in ({"device": "cpu"}, {"patch_identity": "native"}, {"protein_context_evidence": None}):
        with pytest.raises(DiffusionContractError, match="frozen sampler/context"):
            replace(trace, **options)


def test_mps_installer_requires_separate_refiner_and_preserves_venv_path(tmp_path, monkeypatch):
    installer = _load("scripts/install_diffusion_backend.py")
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    checkpoint = tmp_path / "weights.pth"
    checkpoint.write_bytes(b"test")
    monkeypatch.setattr(installer, "_sha256", lambda path: installer.BACKENDS["protpardelle"].checkpoint_sha256)
    monkeypatch.setattr(installer, "diffusion_runner_directory", lambda: tmp_path / "runners")
    arguments = [str(installer.__file__), "protpardelle", str(checkpoint)]
    monkeypatch.setattr(sys, "argv", arguments)
    with pytest.raises(SystemExit):
        installer.main()
    interpreter = tmp_path / "venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(sys.executable)
    monkeypatch.setattr(sys, "argv", [*arguments, "--refinement-python", str(interpreter)])
    installer.main()
    launcher = (tmp_path / "runners/dvbfixer-diffusion-protpardelle-1c-mps-local-v1").read_text()
    assert str(interpreter) in launcher and "mps_runner.py" in launcher
    assert "PYTORCH_ENABLE_MPS_FALLBACK=0" in launcher


@pytest.mark.parametrize("prepared", [True, False])
def test_mps_frozen_replay_never_repairs_an_incomplete_request(tmp_path, cli_fixture, monkeypatch, prepared):
    from dvbfixer.model.diffusion.runtime import DiffusionRuntime
    from dvbfixer.model.diffusion_cli import DiffusionCliError, run_diffusion_model

    source = cli_fixture._gap_input(tmp_path)
    request = build_cli_diffusion_request(source, {"C": "SNRFSGSKSGNTA"}, seeds=(7,), profile=MPS_CC89_PROFILE)
    if prepared:
        request = prepare_mps_cc89_request(request, source.read_bytes(), "auto")
    path = tmp_path / "request.json"
    path.write_text(request.to_json())
    monkeypatch.setattr("dvbfixer.model.diffusion_cli.resolve_diffusion_runtime", lambda model:
        DiffusionRuntime("protpardelle", MPS_CC89_PROFILE, "/installed/mps"))
    monkeypatch.setattr("dvbfixer.model.diffusion_cli.invoke_runner_preflight", lambda **kwargs: SimpleNamespace(passed=True))

    def pipeline(observed, *args, **kwargs):
        assert prepared and observed == request
        return SimpleNamespace(published_bundle=tmp_path / "bundle", status=SimpleNamespace(value="success"))

    monkeypatch.setattr("dvbfixer.model.diffusion_cli.run_diffusion_pipeline", pipeline)
    args = cli_fixture.parse_args([str(source), "--backend", "diffusion", "--diffusion-model", "protpardelle",
        "--diffusion-request", str(path), "-o", str(tmp_path / "bundle")])
    if prepared:
        run_diffusion_model(args)
    else:
        with pytest.raises(DiffusionCliError, match="frozen source-only"):
            run_diffusion_model(args)
    assert path.read_text() == request.to_json()


def test_frozen_legacy_cli_request_selects_legacy_runtime_without_rewriting(tmp_path, cli_fixture, monkeypatch):
    from dvbfixer.model.diffusion.runtime import DiffusionRuntime
    from dvbfixer.model.diffusion_cli import run_diffusion_model

    source = cli_fixture._gap_input(tmp_path)
    request = build_cli_diffusion_request(source, {"C": "SNRFSGSKSGNTA"}, seeds=(7,), profile="protpardelle-1c-mps")
    path = tmp_path / "legacy-request.json"
    path.write_text(request.to_json())
    selected = []

    def runtime(model, *, profile=None):
        selected.append(profile)
        return DiffusionRuntime("protpardelle", profile or MPS_CC89_PROFILE, "/installed/" + (profile or MPS_CC89_PROFILE))

    monkeypatch.setattr("dvbfixer.model.diffusion_cli.resolve_diffusion_runtime", runtime)
    monkeypatch.setattr("dvbfixer.model.diffusion_cli.invoke_runner_preflight", lambda **kwargs: SimpleNamespace(passed=True))

    def pipeline(observed, command, **kwargs):
        assert observed == request and command[-1] == "protpardelle-1c-mps"
        return SimpleNamespace(published_bundle=tmp_path / "bundle", status=SimpleNamespace(value="success"))

    monkeypatch.setattr("dvbfixer.model.diffusion_cli.run_diffusion_pipeline", pipeline)
    args = cli_fixture.parse_args([str(source), "--backend", "diffusion", "--diffusion-model", "protpardelle",
        "--diffusion-request", str(path), "-o", str(tmp_path / "bundle")])
    run_diffusion_model(args)
    assert selected == [None, "protpardelle-1c-mps"]
    assert path.read_text() == request.to_json()


def test_mps_preflight_fails_closed_on_cpu_kernel_failure_without_loading_model(tmp_path, monkeypatch):
    import subprocess

    runner = _load("deploy/protpardelle-1c/mps_runner.py")
    monkeypatch.setenv("PYTORCH_ENABLE_MPS_FALLBACK", "0")
    checkpoint = tmp_path / "cc89.pth"
    checkpoint.write_bytes(b"weights")

    def load(name):
        assert name == "production_runner", "preflight must not load the neural adapter"
        return SimpleNamespace(_verify_profile_environment=lambda: None)

    monkeypatch.setattr(runner, "_load", load)
    monkeypatch.setattr(runner, "_sha", lambda path: runner.CONFIG_SHA256 if path.name.endswith("yaml")
        else runner.METADATA.expected_checkpoint_sha256)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(__version__="2.6.0",
        backends=SimpleNamespace(mps=SimpleNamespace(is_built=lambda: True, is_available=lambda: True))))

    def fail(command, **kwargs):
        assert "--refinement-preflight" in command
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(runner.subprocess, "run", fail)
    report = runner.preflight_report(MPS_CC89_PROFILE, checkpoint, tmp_path / "venv/bin/python")
    assert {issue.code.value for issue in report.issues} == {"incompatible-refinement-platform"}


def test_sampling_provenance_does_not_predeclare_the_refiners_cpu_operation():
    runner = _load("deploy/protpardelle-1c/mps_runner.py")
    raw = runner._sampling_provenance(BackendProvenance("test", 4, "test://engine", "test", device="mps"))
    assert raw.known_nondeterministic_operations == ("PyTorch MPS sampling",)
    # This is the shared refiner's ownership boundary. It must be possible to
    # append CPU exactly once without relaxing BackendProvenance validation.
    refined = replace(raw, known_nondeterministic_operations=(
        *raw.known_nondeterministic_operations, "OpenMM CPU minimization"))
    assert refined.known_nondeterministic_operations.count("OpenMM CPU minimization") == 1
