"""Public CUDA profile admission, context defaults, and isolated deployment."""

import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest

from dvbfixer.model.diffusion.contract import BackendOption
from dvbfixer.model.diffusion.protein_context import (
    CUDA_CC89_CONTEXT,
    CUDA_CC89_OPTIONS,
    ProteinContextError,
    prepare_cuda_cc89_request,
    validate_context_capability,
)
from dvbfixer.model.diffusion.runtime import resolve_diffusion_runtime
from dvbfixer.model.diffusion.scope import assess_diffusion_scope
from dvbfixer.model.diffusion_cli import build_cli_diffusion_request


@pytest.fixture
def cli_fixture(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    return importlib.import_module("test_diffusion_cli")


def test_linux_installed_cuda_cc89_is_discovered_without_mps(monkeypatch):
    monkeypatch.setattr("dvbfixer.model.diffusion.runtime.sys.platform", "linux")
    monkeypatch.setattr("dvbfixer.model.diffusion.runtime.platform.machine", lambda: "x86_64")
    monkeypatch.setattr("dvbfixer.model.diffusion.runtime._installed_runner",
                        lambda name: "/installed/cc89" if name.endswith("protpardelle-1c-cuda") else None)
    assert resolve_diffusion_runtime("protpardelle").profile == "protpardelle-1c-cuda"


def test_cuda_default_context_preserves_terminal_oxt_and_replays_identically(tmp_path, cli_fixture):
    source = cli_fixture._gap_input(tmp_path)
    lines = source.read_text().splitlines(keepends=True)
    last = next(line for line in reversed(lines) if line.startswith("ATOM  "))
    oxt = last[:6] + " 9876" + "  OXT" + last[16:76] + " O\n"
    source.write_text("".join(lines[:-2]) + oxt + "TER\nEND\n")
    request = build_cli_diffusion_request(source, {"C": "SNRFSGSKSGNTA"}, seeds=(7,), profile="protpardelle-1c-cuda")
    selected = prepare_cuda_cc89_request(request, source.read_bytes(), "auto")
    assert selected.protein_context.policy == CUDA_CC89_CONTEXT
    assert all(option in selected.backend_options for option in CUDA_CC89_OPTIONS)
    assert any(atom.atom_name == "OXT" for atom in selected.protein_context.preserved_only)
    assert selected.fixed_atoms == request.fixed_atoms
    validate_context_capability(selected, "protpardelle")
    assert assess_diffusion_scope(selected, source.read_bytes()).supported
    assert prepare_cuda_cc89_request(selected, source.read_bytes(), "auto") == selected
    assert not assess_diffusion_scope(request, source.read_bytes()).supported


@pytest.mark.parametrize("mode", ["none", "full"])
def test_cuda_profile_never_silently_replaces_an_explicit_context_mode(tmp_path, mode, cli_fixture):
    source = cli_fixture._gap_input(tmp_path)
    request = build_cli_diffusion_request(source, {"C": "SNRFSGSKSGNTA"}, seeds=(7,), profile="protpardelle-1c-cuda")
    with pytest.raises(ProteinContextError, match="auto\\|local"):
        prepare_cuda_cc89_request(request, source.read_bytes(), mode)


def test_cuda_profile_rejects_joint_gaps_and_conflicting_numerics(tmp_path, cli_fixture):
    source = cli_fixture._multichain_gap_input(tmp_path)
    request = build_cli_diffusion_request(source, {"C": "SNRFSGSKSGNTA", "D": "SNRFSGSKSGNTA"}, seeds=(7,), profile="protpardelle-1c-cuda")
    with pytest.raises(ProteinContextError, match="one internal gap"):
        prepare_cuda_cc89_request(request, source.read_bytes(), "auto")
    source = cli_fixture._gap_input(tmp_path)
    request = build_cli_diffusion_request(source, {"C": "SNRFSGSKSGNTA"}, seeds=(7,), profile="protpardelle-1c-cuda")
    request = replace(request, backend_options=(*request.backend_options, BackendOption("cc89_chain_phase", "native")))
    with pytest.raises(ProteinContextError, match="conflicts"):
        prepare_cuda_cc89_request(request, source.read_bytes(), "auto")


def test_installer_keeps_refinement_venv_symlink(tmp_path, monkeypatch):
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts/install_diffusion_backend.py"
    spec = importlib.util.spec_from_file_location("cc89_install_test", script)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.sys, "platform", "linux")
    checkpoint = tmp_path / "checkpoint.pth"
    checkpoint.write_bytes(b"test weights")
    monkeypatch.setattr(module, "_sha256", lambda path: module.BACKENDS["protpardelle-cuda"].checkpoint_sha256)
    venv = tmp_path / "venv/bin"
    venv.mkdir(parents=True)
    interpreter = venv / "python"
    interpreter.symlink_to(sys.executable)
    monkeypatch.setattr(module, "diffusion_runner_directory", lambda: tmp_path / "runners")
    monkeypatch.setattr(sys, "argv", [str(script), "protpardelle", str(checkpoint), "--refinement-python", str(interpreter)])
    module.main()
    launcher = (tmp_path / "runners/dvbfixer-diffusion-protpardelle-1c-cuda").read_text()
    assert str(interpreter) in launcher
    assert "cuda_runner.py" in launcher


def test_cuda_gap_admission_retains_the_studied_cys_free_boundary(tmp_path, cli_fixture):
    source = cli_fixture._gap_input(tmp_path)
    request = build_cli_diffusion_request(source, {"C": "SNRFCGSKSGNTA"}, seeds=(7,), profile="protpardelle-1c-cuda")
    with pytest.raises(ProteinContextError, match="CYS-free"):
        prepare_cuda_cc89_request(request, source.read_bytes(), "auto")


@pytest.mark.parametrize("prepared", [False, True])
def test_public_frozen_request_is_never_silently_given_a_new_context(tmp_path, monkeypatch, cli_fixture, prepared):
    from types import SimpleNamespace

    from dvbfixer.model.diffusion.preflight import RunnerPreflightFacts, RunnerPreflightReport
    from dvbfixer.model.diffusion.runtime import DiffusionRuntime
    from dvbfixer.model.diffusion_cli import DiffusionCliError, run_diffusion_model

    source = cli_fixture._gap_input(tmp_path)
    request = build_cli_diffusion_request(source, {"C": "SNRFSGSKSGNTA"}, seeds=(7,), profile="protpardelle-1c-cuda")
    if prepared:
        request = prepare_cuda_cc89_request(request, source.read_bytes(), "auto")
    persisted = request.to_json()
    request_path = tmp_path / "request.json"
    request_path.write_text(persisted)
    output = tmp_path / "bundle"
    monkeypatch.setattr("dvbfixer.model.diffusion_cli.resolve_diffusion_runtime", lambda model:
        DiffusionRuntime("protpardelle", "protpardelle-1c-cuda", "/installed/cc89"))

    def preflight(**kwargs):
        assert prepared, "invalid replay must fail before runner preflight"
        return RunnerPreflightReport("protpardelle-1c-cuda", 4, 4, RunnerPreflightFacts())

    def pipeline(observed, *args, **kwargs):
        assert prepared and observed == request
        return SimpleNamespace(published_bundle=output, status=SimpleNamespace(value="success"))

    monkeypatch.setattr("dvbfixer.model.diffusion_cli.invoke_runner_preflight", preflight)
    monkeypatch.setattr("dvbfixer.model.diffusion_cli.run_diffusion_pipeline", pipeline)
    args = cli_fixture.parse_args([str(source), "--backend", "diffusion", "--diffusion-model", "protpardelle",
                                  "--diffusion-request", str(request_path), "-o", str(output)])
    if prepared:
        run_diffusion_model(args)
    else:
        with pytest.raises(DiffusionCliError, match="frozen source-only local context"):
            run_diffusion_model(args)
    assert request_path.read_text() == persisted
