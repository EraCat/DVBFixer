"""Focused tests for the private Protenix research wrappers."""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    ArtifactReference,
    AtomIdentity,
    BackendProvenance,
    DiffusionStatus,
    RunnerCandidate,
    RunnerDiagnostics,
    RunnerResourceMetrics,
    RunnerResult,
)
from dvbfixer.model.diffusion.runner import DIFFUSION_RUNNER_PROTOCOL_VERSION

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_SMOKE = REPO_ROOT / "deploy/protenix-v1/checkpoint_gap_smoke.py"
PROFILE_LOCK = REPO_ROOT / "deploy/protenix-v1/profile-lock.json"
PROTENIX_PATCH = REPO_ROOT / "deploy/protenix-v1/per-step-callback.patch"


@dataclass(frozen=True)
class _FakeSeedRequest:
    candidate_count: int
    seeds: tuple[int, ...]

    def to_json(self) -> str:
        return json.dumps({"candidate_count": self.candidate_count, "seeds": list(self.seeds)})


def _fake_seed_result(seed: int, *, engine_revision: str = "test") -> RunnerResult:
    candidate = RunnerCandidate(
        candidate_id=f"candidate-{seed}",
        seed=seed,
        coordinate_artifact=ArtifactReference(f"candidate-{seed}.pdb", "a" * 64),
        sampler_trace_artifact=ArtifactReference(f"trace-{seed}.json", "b" * 64),
        generated_atoms=(),
        generated_residues=(),
        raw_backend_score=None,
        score_provenance="test",
    )
    return RunnerResult(
        schema_version=DIFFUSION_SCHEMA_VERSION,
        status=DiffusionStatus.SUCCESS,
        candidates=(candidate,),
        runner_diagnostics=RunnerDiagnostics(exit_code=0, timed_out=False),
        backend_provenance=BackendProvenance(
            backend="fake-protenix",
            runner_protocol_version=DIFFUSION_RUNNER_PROTOCOL_VERSION,
            engine_repository="builtin://test",
            engine_revision=engine_revision,
        ),
        resource_metrics=RunnerResourceMetrics(
            wall_time_seconds=float(seed),
            peak_ram_bytes=seed,
            peak_vram_bytes=seed * 2,
        ),
    )


def _load_refinement_script() -> ModuleType:
    path = REPO_ROOT / "deploy/protenix-v1/refine_candidate.py"
    spec = importlib.util.spec_from_file_location("protenix_refine_candidate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_checkpoint_smoke() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "protenix_checkpoint_gap_smoke", CHECKPOINT_SMOKE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(CHECKPOINT_SMOKE.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def test_legacy_refinement_does_not_claim_sampler_evidence() -> None:
    source = (REPO_ROOT / "deploy/protenix-v1/refine_candidate.py").read_text(
        encoding="utf-8"
    )

    assert 'profile="unknown-source-legacy-refinement"' in source
    assert "denoising_update_count=None" in source
    assert "sampler_evidence_complete=False" in source


def _load_production_runner() -> ModuleType:
    path = REPO_ROOT / "deploy/protenix-v1/production_runner.py"
    spec = importlib.util.spec_from_file_location("protenix_production_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _atom_line(serial: int, residue_number: int, atom_name: str, x: float) -> str:
    return (
        f"ATOM  {serial:5d}  {atom_name:<3} ALA A{residue_number:4d}    "
        f"{x:8.3f}{2.0:8.3f}{3.0:8.3f}  1.00  0.00           C\n"
    )


def test_refinement_rewrites_only_requested_coordinate_columns() -> None:
    module = _load_refinement_script()
    fixed = _atom_line(1, 1, "CA", 1.0)
    generated = _atom_line(2, 2, "CA", 4.0)
    text = "HEADER preserved\n" + fixed + generated + "END\n"
    identity = AtomIdentity("A", "2", "", "CA")

    rewritten = module._rewrite_generated_coordinates(
        text,
        {identity: np.asarray([7.0, 8.0, 9.0])},
    )

    original_lines = text.splitlines(keepends=True)
    rewritten_lines = rewritten.splitlines(keepends=True)
    assert rewritten_lines[0] == original_lines[0]
    assert rewritten_lines[1] == original_lines[1]
    assert rewritten_lines[2][:30] == original_lines[2][:30]
    assert rewritten_lines[2][30:54] == "   7.000   8.000   9.000"
    assert rewritten_lines[2][54:] == original_lines[2][54:]
    assert rewritten_lines[3] == original_lines[3]


def test_refinement_rejects_missing_or_duplicate_generated_atoms() -> None:
    module = _load_refinement_script()
    generated = _atom_line(2, 2, "CA", 4.0)
    identity = AtomIdentity("A", "2", "", "CA")
    coordinates = {identity: np.asarray([7.0, 8.0, 9.0])}

    with pytest.raises(ValueError, match="omits 1 generated atoms"):
        module._rewrite_generated_coordinates("END\n", coordinates)
    with pytest.raises(ValueError, match="duplicate generated atom"):
        module._rewrite_generated_coordinates(generated + generated, coordinates)


def test_checkpoint_smoke_reports_peak_vram() -> None:
    smoke = CHECKPOINT_SMOKE.read_text(encoding="utf-8")

    assert "torch.cuda.reset_peak_memory_stats()" in smoke
    assert "peak_vram_bytes=torch.cuda.max_memory_allocated()" in smoke
    assert '"peak_vram_bytes": runner_result.resource_metrics.peak_vram_bytes' in smoke


def test_checkpoint_writer_projects_out_unrequested_model_atoms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke = _load_checkpoint_smoke()
    requested = AtomIdentity("A", "1", "", "CA")
    model_only = AtomIdentity("A", "1", "", "OXT")
    source = tmp_path / "input.pdb"
    source.write_text(_atom_line(1, 1, "CA", 1.0) + "END\n")
    observed: dict[str, object] = {}

    def fake_materialize(
        _source_text: str,
        atom_axis: tuple[AtomIdentity, ...],
        coordinates: np.ndarray,
        residue_names: tuple[str, ...],
        _request: object,
        *,
        elements: tuple[str, ...],
    ) -> str:
        observed.update(
            atom_axis=atom_axis,
            coordinates=coordinates,
            residue_names=residue_names,
            elements=elements,
        )
        return "END\n"

    monkeypatch.setattr(smoke, "materialize_candidate_pdb", fake_materialize)
    smoke._write_candidate(
        tmp_path / "candidate.pdb",
        source,
        np.asarray(((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))),
        (requested, model_only),
        ("ALA", "ALA"),
        ("C", "O"),
        SimpleNamespace(fixed_atoms=(requested,), generated_atoms=(), protein_context=None),
    )

    assert observed["atom_axis"] == (requested,)
    assert np.array_equal(observed["coordinates"], ((1.0, 2.0, 3.0),))
    assert observed["residue_names"] == ("ALA",)
    assert observed["elements"] == ("C",)


def test_production_runner_writes_protocol_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = _load_production_runner()
    checkpoint = tmp_path / "protenix_base_default_v1.0.0.pt"
    checkpoint.write_bytes(b"checkpoint")
    (tmp_path / "request.json").write_text("{}")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(production.shutil, "which", lambda _name: "/usr/bin/true")
    monkeypatch.setattr(production, "_verify_checkpoint", lambda path: path.resolve())
    monkeypatch.setattr(production, "_verify_kalign", lambda path, _lock: path)
    monkeypatch.setenv(
        "DVBFIXER_DIFFUSION_PROTOCOL_VERSION",
        str(DIFFUSION_RUNNER_PROTOCOL_VERSION),
    )

    expected = RunnerResult(
        schema_version=DIFFUSION_SCHEMA_VERSION,
        status=DiffusionStatus.FAILED,
        candidates=(),
        runner_diagnostics=RunnerDiagnostics(exit_code=1, timed_out=False),
        backend_provenance=BackendProvenance(
            backend="fake-protenix",
            runner_protocol_version=DIFFUSION_RUNNER_PROTOCOL_VERSION,
            engine_repository="builtin://test",
            engine_revision="test",
            device="cuda:0",
            framework_version="2.13.0+cu129",
            cuda_version="12.9",
        ),
        message="test result",
    )

    class FakeBuilder:
        @staticmethod
        def build_input(_request: Path, output: Path) -> Path:
            output.mkdir(parents=True)
            path = output / "input.json"
            path.write_text("{}")
            return path

    class FakeAdapter:
        @staticmethod
        def run(*args: object, **kwargs: object) -> tuple[RunnerResult, Path]:
            assert kwargs["cycles"] == 1
            assert kwargs["steps"] == 200
            assert (
                kwargs["ablation_mode"].value
                == "template-conditioning-plus-reinjection"
            )
            return expected, Path("summary.json")

    observed = production.run(
        profile="protenix-v1-cuda",
        checkpoint=checkpoint,
        scripts=(FakeBuilder(), FakeAdapter()),
        refiner=lambda *_args: pytest.fail("failed results must not be refined"),
        preflight=lambda: None,
    )

    assert observed.status is DiffusionStatus.FAILED
    assert observed.message == expected.message
    assert observed.backend_provenance.source_license == "Apache-2.0"
    assert observed.backend_provenance.environment_identity.startswith("linux-amd64")
    assert RunnerResult.from_json((tmp_path / "result.json").read_text()) == observed


def test_production_runner_executes_and_merges_each_requested_seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = _load_production_runner()
    checkpoint = tmp_path / "protenix_base_default_v1.0.0.pt"
    checkpoint.write_bytes(b"checkpoint")
    (tmp_path / "request.json").write_text(json.dumps({"candidate_count": 2, "seeds": [7, 11]}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(production.shutil, "which", lambda _name: "/usr/bin/true")
    monkeypatch.setattr(production, "_verify_checkpoint", lambda path: path.resolve())
    monkeypatch.setattr(production, "_verify_kalign", lambda path, _lock: path)
    monkeypatch.setattr(production, "_verify_success_result", lambda *_args, **_kwargs: None)
    monkeypatch.setenv(
        "DVBFIXER_DIFFUSION_PROTOCOL_VERSION",
        str(DIFFUSION_RUNNER_PROTOCOL_VERSION),
    )

    monkeypatch.setattr(
        production.DiffusionRequest,
        "from_json",
        classmethod(lambda _cls, _text: _FakeSeedRequest(2, (7, 11))),
    )
    observed_builder_seeds: list[int] = []
    observed_adapter_seeds: list[int] = []

    class FakeBuilder:
        @staticmethod
        def build_input(request_path: Path, output: Path) -> Path:
            seed = json.loads(request_path.read_text())["seeds"][0]
            observed_builder_seeds.append(seed)
            output.mkdir(parents=True)
            path = output / "input.json"
            path.write_text("{}")
            return path

    class FakeAdapter:
        @staticmethod
        def run(
            request_path: Path,
            *_args: object,
            **_kwargs: object,
        ) -> tuple[RunnerResult, Path]:
            seed = json.loads(request_path.read_text())["seeds"][0]
            observed_adapter_seeds.append(seed)
            return _fake_seed_result(seed), Path("summary.json")

    result = production.run(
        profile="protenix-v1-cuda",
        checkpoint=checkpoint,
        scripts=(FakeBuilder(), FakeAdapter()),
        refiner=lambda _request, raw, _output: raw,
        preflight=lambda: None,
    )

    assert observed_builder_seeds == [7, 11]
    assert observed_adapter_seeds == [7, 11]
    assert [candidate.seed for candidate in result.candidates] == [7, 11]
    assert result.resource_metrics.wall_time_seconds == 18.0
    assert result.resource_metrics.peak_ram_bytes == 11
    assert result.resource_metrics.peak_vram_bytes == 22
    assert RunnerResult.from_json((tmp_path / "result.json").read_text()) == result
    assert not tuple(tmp_path.glob(".protenix-seed-*.request.json"))


def test_production_runner_fails_all_candidates_when_one_seed_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = _load_production_runner()
    checkpoint = tmp_path / "protenix_base_default_v1.0.0.pt"
    checkpoint.write_bytes(b"checkpoint")
    (tmp_path / "request.json").write_text(
        json.dumps({"candidate_count": 2, "seeds": [7, 11]})
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(production.shutil, "which", lambda _name: "/usr/bin/true")
    monkeypatch.setattr(production, "_verify_checkpoint", lambda path: path.resolve())
    monkeypatch.setattr(production, "_verify_kalign", lambda path, _lock: path)
    monkeypatch.setattr(production, "_verify_success_result", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        production.DiffusionRequest,
        "from_json",
        classmethod(lambda _cls, _text: _FakeSeedRequest(2, (7, 11))),
    )
    monkeypatch.setenv(
        "DVBFIXER_DIFFUSION_PROTOCOL_VERSION",
        str(DIFFUSION_RUNNER_PROTOCOL_VERSION),
    )
    observed_seeds: list[int] = []

    class FakeBuilder:
        @staticmethod
        def build_input(_request_path: Path, output: Path) -> Path:
            output.mkdir(parents=True)
            return output / "input.json"

    class FakeAdapter:
        @staticmethod
        def run(request_path: Path, *_args: object, **_kwargs: object) -> tuple[RunnerResult, Path]:
            seed = json.loads(request_path.read_text())["seeds"][0]
            observed_seeds.append(seed)
            if seed == 7:
                return _fake_seed_result(seed), Path("summary.json")
            return (
                RunnerResult(
                    schema_version=DIFFUSION_SCHEMA_VERSION,
                    status=DiffusionStatus.FAILED,
                    candidates=(),
                    runner_diagnostics=RunnerDiagnostics(exit_code=1, timed_out=False),
                    backend_provenance=_fake_seed_result(seed).backend_provenance,
                    message="sampling failed",
                ),
                Path("summary.json"),
            )

    result = production.run(
        profile="protenix-v1-cuda",
        checkpoint=checkpoint,
        scripts=(FakeBuilder(), FakeAdapter()),
        refiner=lambda _request, raw, _output: raw,
        preflight=lambda: None,
    )

    assert observed_seeds == [7, 11]
    assert result.status is DiffusionStatus.FAILED
    assert result.candidates == ()
    assert result.message == "Protenix seed 11 failed: sampling failed"
    assert RunnerResult.from_json((tmp_path / "result.json").read_text()) == result
    assert not tuple(tmp_path.glob(".protenix-seed-*.request.json"))


def test_production_runner_rejects_changed_multi_seed_provenance() -> None:
    production = _load_production_runner()

    with pytest.raises(RuntimeError, match="provenance changed"):
        production._merge_candidate_results(
            (_fake_seed_result(7), _fake_seed_result(11, engine_revision="changed"))
        )


def test_production_runner_rejects_wrong_profile(tmp_path: Path) -> None:
    production = _load_production_runner()
    with pytest.raises(ValueError, match="unsupported Protenix profile"):
        production.run(
            profile="protpardelle-1c-mps",
            checkpoint=tmp_path / "checkpoint.pt",
        )


def test_production_runner_rejects_missing_execution_protocol(
    tmp_path: Path,
) -> None:
    production = _load_production_runner()

    with pytest.raises(RuntimeError, match="protocol version"):
        production.run(
            profile="protenix-v1-cuda",
            checkpoint=tmp_path / "checkpoint.pt",
            preflight=lambda: pytest.fail("protocol check must run first"),
        )


def test_production_runner_verifies_checkpoint_before_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = _load_production_runner()
    monkeypatch.setenv(
        "DVBFIXER_DIFFUSION_PROTOCOL_VERSION",
        str(DIFFUSION_RUNNER_PROTOCOL_VERSION),
    )
    checkpoint = tmp_path / production.CHECKPOINT_NAME
    checkpoint.write_bytes(b"wrong checkpoint")

    with pytest.raises(RuntimeError, match="digest mismatch"):
        production.run(
            profile=production.PROFILE,
            checkpoint=checkpoint,
            preflight=lambda: pytest.fail("checkpoint must be checked first"),
        )


def test_production_profile_lock_matches_runner_and_patch() -> None:
    production = _load_production_runner()
    lock = json.loads(PROFILE_LOCK.read_text())

    assert production._sha256(PROFILE_LOCK) == production.PROFILE_LOCK_SHA256
    assert production._sha256(PROTENIX_PATCH) == production.PATCH_SHA256
    assert lock["patch_sha256"] == production.PATCH_SHA256
    assert lock["checkpoint"]["sha256"] == production.CHECKPOINT_SHA256
    assert lock["protenix_revision"] == production.ENGINE_REVISION
    assert set(lock["patched_source_sha256"]) == {
        "protenix/model/generator.py",
        "protenix/model/protenix.py",
    }
    assert set(lock["auxiliary_artifact_sha256"]) == {
        "common/clusters-by-entity-40.txt",
        "common/components.cif",
        "common/components.cif.rdkit_mol.pkl",
        "common/obsolete_release_date.csv",
        "common/obsolete_to_successor.json",
        "common/release_date_cache.json",
    }


def test_production_result_write_is_atomic_and_exclusive(tmp_path: Path) -> None:
    production = _load_production_runner()
    result = RunnerResult(
        schema_version=DIFFUSION_SCHEMA_VERSION,
        status=DiffusionStatus.FAILED,
        candidates=(),
        runner_diagnostics=RunnerDiagnostics(exit_code=1, timed_out=False),
        backend_provenance=BackendProvenance(
            backend="fake-protenix",
            runner_protocol_version=DIFFUSION_RUNNER_PROTOCOL_VERSION,
            engine_repository="builtin://test",
            engine_revision="test",
        ),
        message="expected failure",
    )
    path = tmp_path / "result.json"

    production._write_result_atomic(path, result)

    assert RunnerResult.from_json(path.read_text()) == result
    assert not (tmp_path / ".result.json.tmp").exists()
    with pytest.raises(RuntimeError, match="already exists"):
        production._write_result_atomic(path, result)


def test_production_runner_rejects_malformed_container_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = _load_production_runner()
    monkeypatch.setenv("DVBFIXER_PROTENIX_IMAGE_DIGEST", "latest")

    with pytest.raises(RuntimeError, match="not a SHA-256 digest"):
        production._container_digest()


def test_production_source_tree_rejects_unapproved_python_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = _load_production_runner()
    untracked = ""

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        if "--name-only" in command:
            return SimpleNamespace(
                stdout="protenix/model/generator.py\nprotenix/model/protenix.py\n"
            )
        return SimpleNamespace(stdout=untracked)

    monkeypatch.setattr(production.subprocess, "run", fake_run)

    assert production._source_tree_is_frozen(tmp_path)
    untracked = "protenix/model/__pycache__/generator.cpython-313.pyc\n"
    assert not production._source_tree_is_frozen(tmp_path)
    untracked = "protenix/model/debug_hook.cpython-313.so\n"
    assert not production._source_tree_is_frozen(tmp_path)


def test_production_preflight_reports_cuda_without_loading_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = _load_production_runner()
    checkpoint = tmp_path / production.CHECKPOINT_NAME
    checkpoint.write_bytes(b"checkpoint")
    patch_text = (REPO_ROOT / "deploy/protenix-v1/per-step-callback.patch").read_text()
    monkeypatch.setattr(production.sys, "platform", "linux")
    monkeypatch.setattr(production.sys, "version_info", (3, 13, 15))
    monkeypatch.setattr(production.platform, "machine", lambda: "x86_64")
    monkeypatch.setenv("PYTHONNOUSERSITE", "1")
    monkeypatch.setattr(production.shutil, "which", lambda _name: "/usr/bin/kalign")
    monkeypatch.setattr(production, "_source_root", lambda: tmp_path)
    monkeypatch.setattr(production, "_source_tree_is_frozen", lambda _root: True)
    monkeypatch.setattr(
        production,
        "_sha256",
        lambda path: production.PATCH_SHA256
        if path.name == "per-step-callback.patch"
        else production.CHECKPOINT_SHA256,
    )
    monkeypatch.setattr(
        production.subprocess,
        "run",
        lambda command, **_kwargs: SimpleNamespace(
            stdout=production.ENGINE_REVISION if command[-2:] == ["rev-parse", "HEAD"] else patch_text
        ),
    )
    fake_torch = SimpleNamespace(
        __version__="2.13.0+cu129",
        version=SimpleNamespace(cuda="12.9"),
        cuda=SimpleNamespace(
            is_available=lambda: False,
            current_device=lambda: 0,
            is_bf16_supported=lambda: True,
            get_device_name=lambda _device: production.GPU_NAME,
            get_device_capability=lambda _device: production.GPU_COMPUTE_CAPABILITY,
        ),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(production, "_profile_lock", lambda: {"packages": {}})
    monkeypatch.setattr(production, "_verify_kalign", lambda path, _lock: path)
    monkeypatch.setattr(production, "_verify_patched_sources", lambda _root, _lock: None)
    monkeypatch.setattr(production, "_verify_auxiliary_artifacts", lambda _root, _lock: None)
    monkeypatch.setattr(
        production,
        "_load_production_scripts",
        lambda: pytest.fail("preflight must not load production adapters"),
    )

    report = production.preflight_report(production.PROFILE, checkpoint)

    assert {issue.code.value for issue in report.issues} == {"missing-cuda"}
    assert report.facts.accelerator_available is False
