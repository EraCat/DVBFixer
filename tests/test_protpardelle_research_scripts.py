"""Dependency-light tests for the private Protpardelle research adapter."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    ArtifactReference,
    AtomIdentity,
    BackendProvenance,
    DiffusionRequest,
    DiffusionStatus,
    GapRegion,
    ResidueIdentity,
    RunnerDiagnostics,
    RunnerResult,
    SequencePlacement,
    TargetInterval,
    TargetSequence,
)
from dvbfixer.model.diffusion.runner import DIFFUSION_RUNNER_PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parents[1]
DIGEST = "a" * 64
PATCH = ROOT / "deploy/protpardelle-1c/per-step-callback.patch"
APPLE_PATCH = ROOT / "deploy/protpardelle-1c/apple-portability.patch"


def _load_adapter() -> ModuleType:
    path = ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py"
    spec = importlib.util.spec_from_file_location("protpardelle_checkpoint_gap_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_production_runner() -> ModuleType:
    path = ROOT / "deploy/protpardelle-1c/production_runner.py"
    spec = importlib.util.spec_from_file_location("protpardelle_production_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_neutral_chain_phase_changes_only_the_denoiser_phase_feature(monkeypatch):
    adapter = _load_adapter()

    class Tensor:
        def __init__(self, values):
            self.values = np.asarray(values)
            self.shape = self.values.shape

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.values

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(zeros_like=lambda value: Tensor(np.zeros_like(value.values))))
    chain = Tensor([[0, 0, 1, 1]])
    positions = Tensor([[1, 2, 203, 204]])
    args = (object(), object(), object())
    crop = object()
    kwargs = {"chain_index": chain, "residue_index": positions, "struct_crop_cond": crop}
    hook = adapter._NeutralDenoiserChainPhase()
    new_args, new_kwargs = hook(None, args, kwargs)
    assert new_args is args
    assert new_kwargs["residue_index"] is positions
    assert new_kwargs["struct_crop_cond"] is crop
    assert kwargs["chain_index"] is chain
    assert chain.values.tolist() == [[0, 0, 1, 1]]
    assert new_kwargs["chain_index"].values.tolist() == [[0, 0, 0, 0]]
    assert hook.calls == 1
    assert hook.chain_labels == (0, 1)
    with pytest.raises(ValueError, match="residue-index chain breaks"):
        adapter._NeutralDenoiserChainPhase()(None, args, {**kwargs, "residue_index": Tensor([[1, 2, 3, 4]])})


def test_neutral_chain_phase_requires_an_explicit_matching_cuda_request():
    from dataclasses import replace

    from dvbfixer.model.diffusion.contract import BackendOption

    adapter = _load_adapter()
    request = _request()
    adapter._require_chain_phase_policy(request, "mps", "native")
    with pytest.raises(ValueError, match="explicitly declared"):
        adapter._require_chain_phase_policy(request, "cuda", "neutral-v1")
    declared = replace(request, backend_options=(BackendOption("cc89_chain_phase", "neutral-v1"),))
    adapter._require_chain_phase_policy(declared, "cuda:0", "neutral-v1")
    with pytest.raises(ValueError, match="CUDA research-only"):
        adapter._require_chain_phase_policy(declared, "mps", "neutral-v1")
    with pytest.raises(ValueError, match="explicitly declared"):
        adapter._require_chain_phase_policy(declared, "cuda", "native")


def _request() -> DiffusionRequest:
    residues = (
        ResidueIdentity("d", "82"),
        ResidueIdentity("d", "82", "A"),
        ResidueIdentity("d", "83"),
        ResidueIdentity("d", "84"),
    )
    fixed_atoms = (
        AtomIdentity("d", "82", "", "N"),
        AtomIdentity("d", "82", "", "CA"),
        AtomIdentity("d", "82", "", "C"),
        AtomIdentity("d", "84", "", "N"),
        AtomIdentity("d", "84", "", "CA"),
        AtomIdentity("d", "84", "", "C"),
    )
    generated_atoms = (
        AtomIdentity("d", "82", "A", "N"),
        AtomIdentity("d", "82", "A", "CA"),
        AtomIdentity("d", "82", "A", "C"),
        AtomIdentity("d", "82", "A", "O"),
        AtomIdentity("d", "83", "", "N"),
        AtomIdentity("d", "83", "", "CA"),
        AtomIdentity("d", "83", "", "C"),
        AtomIdentity("d", "83", "", "O"),
    )
    return DiffusionRequest(
        schema_version=DIFFUSION_SCHEMA_VERSION,
        normalized_pdb=ArtifactReference("input/normalized.pdb", DIGEST),
        target_sequences=(TargetSequence("d", "AGGA"),),
        sequence_placements=(
            SequencePlacement(
                chain="d",
                target_length=4,
                observed_target_indices=(0, 3),
                observed_residues=(residues[0], residues[3]),
            ),
        ),
        gaps=(
            GapRegion(
                chain="d",
                target_interval=TargetInterval(1, 3),
                left_anchor=residues[0],
                right_anchor=residues[3],
                generated_residues=residues[1:3],
                movable_junction_residues=residues,
            ),
        ),
        fixed_atoms=fixed_atoms,
        generated_atoms=generated_atoms,
        retained_explicit_links=(),
        candidate_count=1,
        seeds=(20260929,),
        backend_options=(),
    )


def _multichain_request() -> DiffusionRequest:
    first = _request()
    second_residues = (
        ResidueIdentity("E", "10"),
        ResidueIdentity("E", "11"),
        ResidueIdentity("E", "12"),
        ResidueIdentity("E", "13"),
    )
    second_fixed = tuple(
        AtomIdentity("E", number, "", atom)
        for number in ("10", "13")
        for atom in ("N", "CA", "C")
    )
    second_generated = tuple(
        AtomIdentity("E", number, "", atom)
        for number in ("11", "12")
        for atom in ("N", "CA", "C", "O")
    )
    return DiffusionRequest(
        schema_version=first.schema_version,
        normalized_pdb=first.normalized_pdb,
        target_sequences=(*first.target_sequences, TargetSequence("E", "AGGA")),
        sequence_placements=(*first.sequence_placements, SequencePlacement(
            chain="E",
            target_length=4,
            observed_target_indices=(0, 3),
            observed_residues=(second_residues[0], second_residues[3]),
        )),
        gaps=(*first.gaps, GapRegion(
            chain="E",
            target_interval=TargetInterval(1, 3),
            left_anchor=second_residues[0],
            right_anchor=second_residues[3],
            generated_residues=second_residues[1:3],
            movable_junction_residues=second_residues,
        )),
        fixed_atoms=(*first.fixed_atoms, *second_fixed),
        generated_atoms=(*first.generated_atoms, *second_generated),
        retained_explicit_links=(),
        candidate_count=1,
        seeds=first.seeds,
        backend_options=(),
    )


def test_callback_patch_runs_after_update_and_preserves_jump_state() -> None:
    patch = PATCH.read_text(encoding="utf-8")
    update = patch.index("xt = x0")
    callback = patch.index("updated = step_callback")

    assert callback > update
    assert "step_callback must preserve tensor shape" in patch
    assert "step_callback must preserve tensor device" in patch
    assert "step_callback must preserve tensor dtype" in patch
    assert "atom73_state_t[mask73] = xt[mask37]" in patch
    assert "motif_all_atom" in patch
    assert "motif_atom_mask" in patch


def test_apple_patch_removes_cuda_only_side_effects_and_host_trajectory_copies() -> None:
    patch = APPLE_PATCH.read_text(encoding="utf-8")

    assert 'if self.device.type == "cuda"' in patch
    assert "if record_trajectory:" in patch
    assert "xt_traj.append(scaled_xt.cpu())" in patch
    assert 'sample_options["record_trajectory"] = False' in (
        ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py"
    ).read_text(encoding="utf-8")
    assert "hetero_repulsion" in patch
    assert "torch.cdist" in patch


def test_adapter_keeps_per_step_reinjection_opt_in() -> None:
    adapter = (ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py").read_text(
        encoding="utf-8"
    )

    assert 'parser.add_argument("--per-step-reinjection", action="store_true")' in adapter
    assert 'sample_options["step_callback"] = callback' in adapter
    assert '"per_step_reinjection": per_step_reinjection' in adapter


class _FakeDevice:
    def __init__(self, name: str) -> None:
        device_type, _, index = name.partition(":")
        self.type = device_type
        self.index = int(index) if index else None

    def __str__(self) -> str:
        return self.type if self.index is None else f"{self.type}:{self.index}"


class _FakeMPSBackend:
    def __init__(self, *, built: bool = True, available: bool = True) -> None:
        self._built = built
        self._available = available

    def is_built(self) -> bool:
        return self._built

    def is_available(self) -> bool:
        return self._available


class _FakeCUDA:
    def __init__(self, available: bool = True) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available


class _FakeTorch:
    def __init__(
        self,
        *,
        mps_built: bool = True,
        mps_available: bool = True,
        cuda_available: bool = True,
    ) -> None:
        self.backends = type(
            "Backends",
            (),
            {"mps": _FakeMPSBackend(built=mps_built, available=mps_available)},
        )()
        self.cuda = _FakeCUDA(cuda_available)

    @staticmethod
    def device(name: str) -> _FakeDevice:
        return _FakeDevice(name)


def test_mps_device_fails_closed_when_unavailable_or_fallback_is_not_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    monkeypatch.delenv("PYTORCH_ENABLE_MPS_FALLBACK", raising=False)

    with pytest.raises(RuntimeError, match="MPS_FALLBACK=0"):
        adapter._resolve_device(_FakeTorch(), "mps")
    monkeypatch.setenv("PYTORCH_ENABLE_MPS_FALLBACK", "0")
    with pytest.raises(RuntimeError, match="unavailable"):
        adapter._resolve_device(_FakeTorch(mps_available=False), "mps")

    assert str(adapter._resolve_device(_FakeTorch(), "mps")) == "mps"


def test_requested_cuda_device_fails_instead_of_using_cpu() -> None:
    adapter = _load_adapter()

    with pytest.raises(RuntimeError, match="CUDA was requested but is unavailable"):
        adapter._resolve_device(_FakeTorch(cuda_available=False), "cuda")


def test_adapter_records_resolved_device_not_requested_label() -> None:
    source = (ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py").read_text(
        encoding="utf-8"
    )

    assert 'device=str(device)' in source
    assert '"device": str(device)' in source
    assert 'load_model(config_path, checkpoint_path, device=str(device))' in source
    assert source.index("sampler_atom_order = tuple(") < source.index(
        "identities, coordinates, residue_names = _synchronize_and_restore_fixed_atoms("
    )
    assert "atom_order=sampler_atom_order" in source
    assert "represented_fixed_atoms=represented_fixed_atoms" in source


def test_adapter_copies_mps_coordinates_to_cpu_before_float64_conversion() -> None:
    adapter = _load_adapter()
    calls: list[dict[str, object]] = []

    class FakeTensor:
        device = "mps"

        def detach(self) -> FakeTensor:
            return self

        def to(self, **kwargs: object) -> FakeTensor:
            calls.append(kwargs)
            if kwargs.get("dtype") == "float64" and self.device == "mps":
                raise TypeError("MPS does not support float64")
            if "device" in kwargs:
                self.device = str(kwargs["device"])
            return self

        @staticmethod
        def numpy() -> np.ndarray:
            return np.zeros((1, 1, 3), dtype=np.float64)

    torch = type("Torch", (), {"float64": "float64"})()

    converted = adapter._coordinates_to_numpy(torch, FakeTensor())

    assert converted.dtype == np.float64
    assert calls == [{"device": "cpu"}, {"dtype": "float64"}]


def _atom_line(
    serial: int,
    atom_name: str,
    residue_number: int,
    *,
    insertion_code: str = "",
    chain: str = "d",
) -> str:
    element = atom_name[0]
    return (
        f"ATOM  {serial:5d}  {atom_name:<3} ALA {chain}{residue_number:4d}"
        f"{insertion_code or ' ':1}   {float(serial):8.3f}{2.0:8.3f}{3.0:8.3f}"
        f"  1.00  0.00          {element:>2}\n"
    )


def test_target_mapping_preserves_case_and_insertion_codes() -> None:
    adapter = _load_adapter()

    mapping = adapter._target_residue_map(_request())

    assert mapping == {
        0: ResidueIdentity("d", "82"),
        1: ResidueIdentity("d", "82", "A"),
        2: ResidueIdentity("d", "83"),
        3: ResidueIdentity("d", "84"),
    }


def test_multichain_target_mapping_and_motif_placement() -> None:
    adapter = _load_adapter()
    request = _multichain_request()

    mapping = adapter._target_residue_map(request)
    placement, fixed_positions = adapter._motif_placement(request)

    assert mapping[0] == ResidueIdentity("d", "82")
    assert mapping[4] == ResidueIdentity("E", "10")
    assert mapping[7] == ResidueIdentity("E", "13")
    assert placement == "A1-1/2/A4-4;/;B1-1/2/B4-4"
    assert fixed_positions == [0, 3, 4, 7]


def test_multichain_request_is_split_into_gap_bearing_chain_invocations() -> None:
    adapter = _load_adapter()

    requests = adapter._chain_sampling_requests(_multichain_request())

    assert [request.target_sequences[0].chain for request in requests] == ["d", "E"]
    assert [len(request.target_sequences) for request in requests] == [1, 1]
    assert [{gap.chain for gap in request.gaps} for request in requests] == [
        {"d"},
        {"E"},
    ]
    assert [{atom.chain for atom in request.fixed_atoms} for request in requests] == [
        {"d"},
        {"E"},
    ]


def test_multichain_invocations_include_nearby_partner_crops() -> None:
    adapter = _load_adapter()
    request = _multichain_request()
    coordinates = {
        atom: np.asarray(
            [
                float(index % 3),
                0.0 if atom.chain == "d" else 2.0,
                0.0,
            ]
        )
        for index, atom in enumerate(request.fixed_atoms)
    }

    requests = adapter._chain_sampling_requests(request, coordinates)

    assert [tuple(target.chain for target in item.target_sequences) for item in requests] == [
        ("d", "E"),
        ("E", "d"),
    ]
    assert all(len(item.target_sequences[1].sequence) >= 1 for item in requests)
    assert [
        {atom.chain for atom in item.fixed_atoms}
        for item in requests
    ] == [{"d", "E"}, {"d", "E"}]


def test_multichain_invocations_exclude_distant_partner_chains() -> None:
    adapter = _load_adapter()
    request = _multichain_request()
    coordinates = {
        atom: np.asarray([
            float(index % 3),
            0.0 if atom.chain == "d" else 100.0,
            0.0,
        ])
        for index, atom in enumerate(request.fixed_atoms)
    }

    requests = adapter._chain_sampling_requests(request, coordinates)

    assert [tuple(target.chain for target in item.target_sequences) for item in requests] == [
        ("d",),
        ("E",),
    ]


def test_motif_writer_renumbers_observed_residues_to_target_ordinals(
    tmp_path: Path,
) -> None:
    adapter = _load_adapter()
    request = _request()
    source = tmp_path / "source.pdb"
    destination = tmp_path / "motif.pdb"
    source.write_text(
        "".join(
            _atom_line(index, atom.atom_name, int(atom.residue_number), chain=atom.chain)
            for index, atom in enumerate(request.fixed_atoms, 1)
        )
        + "END\n",
        encoding="ascii",
    )

    adapter._write_motif_input(source, destination, request)

    atom_lines = [
        line
        for line in destination.read_text(encoding="ascii").splitlines()
        if line.startswith("ATOM  ")
    ]
    assert {line[21:22] for line in atom_lines} == {"A"}
    assert [line[22:26].strip() for line in atom_lines] == ["1"] * 3 + ["4"] * 3
    assert all(line[26:27] == " " for line in atom_lines)


def test_motif_writer_fails_when_a_fixed_atom_is_missing(tmp_path: Path) -> None:
    adapter = _load_adapter()
    request = _request()
    source = tmp_path / "source.pdb"
    source.write_text(
        "".join(
            _atom_line(index, atom.atom_name, int(atom.residue_number), chain=atom.chain)
            for index, atom in enumerate(request.fixed_atoms[:-1], 1)
        ),
        encoding="ascii",
    )

    with pytest.raises(ValueError, match="missing=1, extra=0"):
        adapter._write_motif_input(source, tmp_path / "motif.pdb", request)


def test_candidate_writer_preserves_requested_atom_set_and_insertion_code(
    tmp_path: Path,
) -> None:
    adapter = _load_adapter()
    request = _request()
    identities = request.fixed_atoms + request.generated_atoms
    coordinates = np.arange(len(identities) * 3, dtype=np.float64).reshape((-1, 3))
    residue_names = tuple("ALA" if atom in request.fixed_atoms else "GLY" for atom in identities)
    output = tmp_path / "candidate.pdb"
    source = tmp_path / "source.pdb"
    source.write_text(
        "".join(
            _atom_line(index, atom.atom_name, int(atom.residue_number), chain=atom.chain)
            for index, atom in enumerate(request.fixed_atoms, 1)
        )
        + "END\n",
        encoding="ascii",
    )

    adapter._write_candidate(
        output,
        source,
        identities,
        coordinates,
        residue_names,
        request,
    )

    atom_lines = [
        line
        for line in output.read_text(encoding="ascii").splitlines()
        if line.startswith("ATOM  ")
    ]
    observed = {
        AtomIdentity(line[21:22], line[22:26].strip(), line[26:27].strip(), line[12:16].strip())
        for line in atom_lines
    }
    assert observed == set(identities)
    assert sum(line[26:27] == "A" for line in atom_lines) == 4


def test_candidate_writer_rejects_incomplete_generated_atom_set(tmp_path: Path) -> None:
    adapter = _load_adapter()
    request = _request()
    identities = request.fixed_atoms + request.generated_atoms[:-1]
    coordinates = np.zeros((len(identities), 3), dtype=np.float64)
    source = tmp_path / "source.pdb"
    source.write_text(
        "".join(
            _atom_line(index, atom.atom_name, int(atom.residue_number), chain=atom.chain)
            for index, atom in enumerate(request.fixed_atoms, 1)
        )
        + "END\n",
        encoding="ascii",
    )

    with pytest.raises(ValueError, match="omits 1 generated atoms"):
        adapter._write_candidate(
            tmp_path / "candidate.pdb",
            source,
            identities,
            coordinates,
            ("ALA",) * len(identities),
            request,
        )


def test_synchronization_restores_source_only_fixed_atom_exactly() -> None:
    adapter = _load_adapter()
    represented = (
        AtomIdentity("A", "1", "", "N"),
        AtomIdentity("A", "1", "", "CA"),
        AtomIdentity("A", "1", "", "C"),
        AtomIdentity("A", "2", "", "N"),
    )
    source_only = AtomIdentity("A", "2", "", "OXT")
    sampled = np.asarray(
        [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [2.0, 1.0, 0.0], [3.0, 1.0, 0.0]]
    )
    fixed = {
        represented[0]: np.asarray([0.0, 0.0, 0.0]),
        represented[1]: np.asarray([1.0, 0.0, 0.0]),
        represented[2]: np.asarray([1.0, 1.0, 0.0]),
        source_only: np.asarray([4.0, 2.0, 0.0]),
    }

    identities, coordinates, names = adapter._synchronize_and_restore_fixed_atoms(
        represented,
        sampled,
        ("ALA", "ALA", "ALA", "GLY"),
        fixed,
        {identity: "ALA" if identity.residue_number == "1" else "GLY" for identity in fixed},
    )

    assert identities[-1] == source_only
    np.testing.assert_array_equal(coordinates[-1], fixed[source_only])
    assert names[-1] == "GLY"
    for identity in represented[:3]:
        np.testing.assert_array_equal(coordinates[identities.index(identity)], fixed[identity])


def test_per_step_reinjector_excludes_source_only_atom37_entries() -> None:
    adapter = (ROOT / "deploy/protpardelle-1c/checkpoint_gap_smoke.py").read_text(
        encoding="utf-8"
    )

    assert "target_indices = tuple(item[0] for item in represented)" in adapter
    assert "motif_rows = tuple(motif_row_by_target[index] for index in target_indices)" in adapter
    assert "projected[0, target_indices, atom_indices] = authoritative" in adapter


def test_native_conditioning_fit_is_measured_before_reinjection() -> None:
    adapter = _load_adapter()
    identities = tuple(AtomIdentity("A", "1", "", name) for name in ("N", "CA", "C", "O"))
    coordinates = np.asarray(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.2, 0.0]]
    )
    fixed = {
        identity: coordinate
        for identity, coordinate in zip(
            identities[:3],
            np.asarray([[2.0, 3.0, 0.0], [3.0, 3.0, 0.0], [3.0, 4.0, 0.0]]),
        )
    }
    fixed[AtomIdentity("A", "1", "", "OXT")] = np.asarray([2.0, 4.0, 0.0])

    fit = adapter._native_conditioning_fit(identities, coordinates, fixed)

    assert fit["represented_fixed_atom_count"] == 3
    assert fit["source_only_fixed_atom_count"] == 1
    assert fit["rmsd_angstrom"] == pytest.approx(0.0, abs=1e-12)
    assert fit["max_displacement_angstrom"] == pytest.approx(0.0, abs=1e-12)


def test_run_removes_staging_directory_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    output = tmp_path / "result"

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected failure")

    monkeypatch.setattr(adapter, "_run_staged", fail)

    with pytest.raises(RuntimeError, match="injected failure"):
        adapter.run(
            request,
            output,
            tmp_path / "config.yaml",
            tmp_path / "checkpoint.pth",
            steps=1,
            step_scale=1.0,
            s_churn=0.0,
        )

    assert not output.exists()
    assert list(tmp_path.glob(".result.*")) == []


def test_production_runner_writes_protocol_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = _load_production_runner()
    params = tmp_path / "model_params"
    checkpoint = params / "weights" / "cc89_epoch415.pth"
    config = params / "configs" / "cc89.yaml"
    checkpoint.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"checkpoint")
    config.write_text("config")
    (tmp_path / "request.json").write_text("{}")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTORCH_ENABLE_MPS_FALLBACK", "0")
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
            backend="fake-protpardelle",
            runner_protocol_version=DIFFUSION_RUNNER_PROTOCOL_VERSION,
            engine_repository="builtin://test",
            engine_revision="test",
            device="mps",
            framework_version="2.6.0",
        ),
        message="test result",
    )

    class FakeAdapter:
        @staticmethod
        def _run_staged(*args: object, **kwargs: object) -> tuple[RunnerResult, Path]:
            output = Path(args[1])
            summary = output / "summary.json"
            summary.write_text("{}")
            assert kwargs["device_name"] == "mps"
            assert kwargs["per_step_reinjection"] is False
            return expected, summary

    observed = production.run(
        profile="protpardelle-1c-mps",
        checkpoint=checkpoint,
        adapter=FakeAdapter(),
        refiner=lambda *_args: pytest.fail("failed results must not be refined"),
        preflight=lambda: None,
    )

    assert observed.status is DiffusionStatus.FAILED
    assert observed.message == expected.message
    assert observed.backend_provenance.source_license == "MIT"
    assert observed.backend_provenance.environment_identity.startswith("macos-arm64")
    assert os.environ["PROTPARDELLE_MODEL_PARAMS"] == str(params.resolve())
    assert RunnerResult.from_json((tmp_path / "result.json").read_text()) == observed


def test_production_runner_rejects_wrong_profile_and_enabled_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = _load_production_runner()
    checkpoint = tmp_path / "weights" / "model.pth"
    checkpoint.parent.mkdir()
    checkpoint.write_bytes(b"checkpoint")

    with pytest.raises(ValueError, match="unsupported Protpardelle profile"):
        production.run(profile="protenix-v1-cuda", checkpoint=checkpoint)

    monkeypatch.delenv("PYTORCH_ENABLE_MPS_FALLBACK", raising=False)
    with pytest.raises(RuntimeError, match="MPS_FALLBACK=0"):
        production.run(profile="protpardelle-1c-mps", checkpoint=checkpoint)


def test_production_source_tree_requires_only_the_frozen_patch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = _load_production_runner()
    changed = "src/protpardelle/core/models.py\n"

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        if "--name-only" in command:
            return SimpleNamespace(stdout=changed)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(production.subprocess, "run", fake_run)

    assert production._source_tree_is_frozen(tmp_path)
    changed = "src/protpardelle/core/models.py\nsrc/protpardelle/core/sampling.py\n"
    assert not production._source_tree_is_frozen(tmp_path)


def test_production_preflight_reports_mps_and_fallback_without_loading_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = _load_production_runner()
    params = tmp_path / "model_params"
    checkpoint = params / "weights/cc89_epoch415.pth"
    config = params / "configs/cc89.yaml"
    checkpoint.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"checkpoint")
    config.write_text("config")
    source = tmp_path / "checkout/src/protpardelle/__init__.py"
    models = tmp_path / "checkout/src/protpardelle/core/models.py"
    source.parent.mkdir(parents=True)
    models.parent.mkdir(parents=True)
    source.write_text("")
    models.write_text("")
    monkeypatch.setattr(production.sys, "platform", "darwin")
    monkeypatch.setattr(production.sys, "version_info", (3, 12))
    monkeypatch.setattr(production.platform, "machine", lambda: "arm64")
    monkeypatch.setenv("PYTHONNOUSERSITE", "1")
    monkeypatch.delenv("PYTORCH_ENABLE_MPS_FALLBACK", raising=False)
    monkeypatch.setattr(
        production.importlib.util,
        "find_spec",
        lambda _name: SimpleNamespace(origin=str(source)),
    )
    monkeypatch.setattr(production, "_source_tree_is_frozen", lambda _root: True)
    monkeypatch.setattr(
        production,
        "_sha256",
        lambda path: {
            "checkpoint": production.CHECKPOINT_SHA256,
            "cc89_epoch415.pth": production.CHECKPOINT_SHA256,
            "cc89.yaml": production.CONFIG_SHA256,
            "apple-portability.patch": production.APPLE_PATCH_SHA256,
            "models.py": production.PATCHED_MODELS_SHA256,
        }[path.name],
    )
    monkeypatch.setattr(
        production.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=production.ENGINE_REVISION),
    )
    fake_torch = SimpleNamespace(
        __version__="2.6.0",
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)),
        device=lambda name: name,
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(
        production,
        "_load_adapter",
        lambda: pytest.fail("preflight must not load the sampling adapter"),
    )

    report = production.preflight_report(production.PROFILE, checkpoint)

    assert {issue.code.value for issue in report.issues} == {
        "fallback-enabled",
        "missing-mps",
    }
    assert report.facts.effective_device == ""
