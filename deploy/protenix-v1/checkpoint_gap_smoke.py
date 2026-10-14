"""Run the patched Protenix checkpoint with exact per-step reinjection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import torch
from reinjection import FixedAtomReinjector

from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    ArtifactReference,
    AtomIdentity,
    BackendProvenance,
    DiffusionRequest,
    DiffusionStatus,
    ResidueIdentity,
    RunnerCandidate,
    RunnerDiagnostics,
    RunnerResourceMetrics,
    RunnerResult,
)
from dvbfixer.model.diffusion.geometry import weighted_kabsch
from dvbfixer.model.diffusion.pdb_materialize import materialize_candidate_pdb
from dvbfixer.model.diffusion.runner import DIFFUSION_RUNNER_PROTOCOL_VERSION
from dvbfixer.model.diffusion.sampler import SamplingAblationMode
from dvbfixer.model.diffusion.trace import build_sampler_trace, write_sampler_trace
from dvbfixer.model.diffusion.validate import validate_runner_result

_ONE_TO_THREE = {
    "A": "ALA",
    "C": "CYS",
    "D": "ASP",
    "E": "GLU",
    "F": "PHE",
    "G": "GLY",
    "H": "HIS",
    "I": "ILE",
    "K": "LYS",
    "L": "LEU",
    "M": "MET",
    "N": "ASN",
    "P": "PRO",
    "Q": "GLN",
    "R": "ARG",
    "S": "SER",
    "T": "THR",
    "V": "VAL",
    "W": "TRP",
    "Y": "TYR",
}

_CHECKPOINT_NAME = "protenix_base_default_v1.0.0.pt"
_CHECKPOINT_SHA256 = "2b7d5a8b30494514fc47fd2271a16260528cdba170ba09cc112fdecd8f85ec04"
_PATCH_SHA256 = "cc4153be3dfd241124ea183d592884799300046b6ea7d3eccae8409b9fe21aa0"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _target_residue_map(request: DiffusionRequest) -> dict[int, ResidueIdentity]:
    if len(request.target_sequences) != 1 or len(request.sequence_placements) != 1:
        raise ValueError("checkpoint smoke requires exactly one target chain")
    target = request.target_sequences[0]
    placement = request.sequence_placements[0]
    mapping = dict(zip(placement.observed_target_indices, placement.observed_residues))
    for gap in request.gaps:
        if gap.chain != target.chain:
            raise ValueError("all gaps must belong to the single target chain")
        for index, residue in zip(
            range(gap.target_interval.start, gap.target_interval.stop),
            gap.generated_residues,
        ):
            if index in mapping:
                raise ValueError(f"target residue index {index} is mapped more than once")
            mapping[index] = residue
    expected = set(range(len(target.sequence)))
    if set(mapping) != expected:
        raise ValueError("request does not map every target sequence residue exactly once")
    return mapping


def _model_atom_axis(
    atom_array: Any,
    request: DiffusionRequest,
) -> tuple[tuple[AtomIdentity, ...], tuple[str, ...], tuple[str, ...]]:
    if request.protein_context is not None:
        return _context_atom_axis(atom_array, request)
    target = request.target_sequences[0]
    residue_map = _target_residue_map(request)
    chain_ids = {str(value) for value in atom_array.chain_id}
    if len(chain_ids) != 1:
        raise ValueError("featurized atom axis must contain exactly one chain")

    identities: list[AtomIdentity] = []
    residue_names: list[str] = []
    elements: list[str] = []
    for model_res_id, atom_name, residue_name, element in zip(
        atom_array.res_id,
        atom_array.atom_name,
        atom_array.res_name,
        atom_array.element,
    ):
        target_index = int(model_res_id) - 1
        if target_index not in residue_map:
            raise ValueError(f"model residue ordinal {model_res_id} is outside the target")
        expected_name = _ONE_TO_THREE[target.sequence[target_index]]
        if str(residue_name) != expected_name:
            raise ValueError(
                f"model residue {model_res_id} is {residue_name}, expected {expected_name}"
            )
        residue = residue_map[target_index]
        identities.append(
            AtomIdentity(
                residue.chain,
                residue.residue_number,
                residue.insertion_code,
                str(atom_name),
            )
        )
        residue_names.append(str(residue_name))
        elements.append(str(element).strip().upper())
    axis = tuple(identities)
    if len(set(axis)) != len(axis):
        raise ValueError("featurized atom axis maps to duplicate DVBFixer identities")
    required = set(request.fixed_atoms) | set(request.generated_atoms)
    missing = required - set(axis)
    if missing:
        raise ValueError(f"model atom axis omits {len(missing)} requested atoms")
    return axis, tuple(residue_names), tuple(elements)


def _context_atom_axis(atom_array: Any, request: DiffusionRequest):
    from dvbfixer.model.diffusion.protein_context import sampling_entities

    entities = sampling_entities(request)
    identities = []
    names = []
    elements = []
    for entity_id, engine_chain, ordinal, name, residue_name, element in zip(
        atom_array.label_entity_id, atom_array.chain_id, atom_array.res_id,
        atom_array.atom_name, atom_array.res_name, atom_array.element,
    ):
        index = int(entity_id) - 1
        if not 0 <= index < len(entities):
            raise ValueError("unknown Protenix context entity ID")
        entity = entities[index]
        position = int(ordinal) - 1
        if str(engine_chain) != entity.engine_chain or not 0 <= position < len(entity.residues):
            raise ValueError("Protenix context entity/ordinal mapping changed")
        if str(residue_name) != _ONE_TO_THREE[entity.target.sequence[position]]:
            raise ValueError("Protenix context sequence changed during featurization")
        residue = entity.residues[position]
        identities.append(AtomIdentity(residue.chain, residue.residue_number, residue.insertion_code, str(name)))
        names.append(str(residue_name))
        elements.append(str(element).strip().upper())
    axis = tuple(identities)
    required = {item.atom for item in request.protein_context.fixed_conditioning} | set(request.generated_atoms)
    if len(set(axis)) != len(axis) or not required <= set(axis):
        raise ValueError("Protenix context mapping is duplicate or incomplete")
    return axis, tuple(names), tuple(elements)


def _read_fixed_coordinates(
    pdb_path: Path,
    fixed_atoms: tuple[AtomIdentity, ...],
) -> dict[AtomIdentity, np.ndarray]:
    requested = set(fixed_atoms)
    coordinates: dict[AtomIdentity, np.ndarray] = {}
    for line in pdb_path.read_text(encoding="ascii").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        altloc = line[16:17]
        if altloc not in {"", " ", "A"}:
            continue
        identity = AtomIdentity(
            line[21:22],
            line[22:26].strip(),
            line[26:27].strip(),
            line[12:16].strip(),
        )
        if identity not in requested:
            continue
        if identity in coordinates:
            raise ValueError(f"duplicate fixed atom in normalized PDB: {identity}")
        coordinates[identity] = np.asarray(
            [float(line[30:38]), float(line[38:46]), float(line[46:54])],
            dtype=np.float64,
        )
    missing = requested - set(coordinates)
    if missing:
        raise ValueError(f"normalized PDB omits {len(missing)} fixed atoms")
    return coordinates


class _TracingCallback:
    def __init__(
        self,
        atom_axis: tuple[AtomIdentity, ...],
        fixed_coordinates: dict[AtomIdentity, np.ndarray],
        alignment_atoms: tuple[AtomIdentity, ...] | None = None,
    ) -> None:
        self._reinject = FixedAtomReinjector(atom_axis, fixed_coordinates, alignment_atoms=alignment_atoms)
        index_by_identity = {identity: index for index, identity in enumerate(atom_axis)}
        ordered = tuple(sorted(fixed_coordinates))
        self._indices = tuple(index_by_identity[identity] for identity in ordered)
        self._target = np.asarray([fixed_coordinates[identity] for identity in ordered])
        self.device: torch.device | None = None
        self.dtype: torch.dtype | None = None
        self.steps: list[dict[str, float | int]] = []

    def __call__(self, coordinates: torch.Tensor, step_index: int, step_count: int) -> torch.Tensor:
        if coordinates.device.type != "cuda":
            raise RuntimeError("sampler coordinates left the CUDA device")
        if not coordinates.is_floating_point():
            raise RuntimeError("sampler coordinates are not floating point")
        if self.device is None:
            self.device = coordinates.device
            self.dtype = coordinates.dtype
        elif coordinates.device != self.device or coordinates.dtype != self.dtype:
            raise RuntimeError("sampler coordinate device or dtype changed between updates")
        projected = self._reinject(coordinates, step_index, step_count)
        indices = torch.as_tensor(self._indices, device=projected.device)
        target = torch.as_tensor(self._target, dtype=projected.dtype, device=projected.device)
        errors = torch.linalg.vector_norm(projected.index_select(-2, indices) - target, dim=-1)
        self.steps.append(
            {
                "step_index": step_index,
                "step_count": step_count,
                "post_projection_max_error_angstrom": float(errors.max().item()),
            }
        )
        return projected


def _assert_model_on_device(model: Any, device: torch.device) -> None:
    tensors = (*model.parameters(), *model.buffers())
    if not tensors:
        raise RuntimeError("Protenix model exposes no parameters or buffers")
    if any(tensor.device != device for tensor in tensors):
        raise RuntimeError("Protenix model is not wholly on the requested CUDA device")


def _requested_atom_indices(
    atom_axis: tuple[AtomIdentity, ...],
    request: DiffusionRequest,
) -> tuple[int, ...]:
    included = ({item.atom for item in request.protein_context.fixed_conditioning}
                if request.protein_context else set(request.fixed_atoms)) | set(request.generated_atoms)
    selected = tuple(
        index for index, identity in enumerate(atom_axis) if identity in included
    )
    if {atom_axis[index] for index in selected} != included:
        raise ValueError("candidate output did not contain every requested atom exactly once")
    return selected


def _write_candidate(
    output_path: Path,
    source_path: Path,
    coordinates: np.ndarray,
    atom_axis: tuple[AtomIdentity, ...],
    residue_names: tuple[str, ...],
    elements: tuple[str, ...],
    request: DiffusionRequest,
) -> None:
    if coordinates.shape != (len(atom_axis), 3) or not np.isfinite(coordinates).all():
        raise ValueError("prediction has invalid coordinate shape or non-finite values")
    selected_indices = _requested_atom_indices(atom_axis, request)
    selected_axis = tuple(atom_axis[index] for index in selected_indices)
    output_path.write_text(
        materialize_candidate_pdb(
            source_path.read_text(encoding="ascii"),
            selected_axis,
            coordinates[list(selected_indices)],
            tuple(residue_names[index] for index in selected_indices),
            request,
            elements=tuple(elements[index] for index in selected_indices),
        ),
        encoding="ascii",
    )


def _synchronize_frame(
    coordinates: np.ndarray,
    atom_axis: tuple[AtomIdentity, ...],
    fixed_coordinates: dict[AtomIdentity, np.ndarray],
) -> np.ndarray:
    index_by_identity = {identity: index for index, identity in enumerate(atom_axis)}
    ordered = tuple(sorted(fixed_coordinates))
    indices = [index_by_identity[identity] for identity in ordered]
    target = np.asarray([fixed_coordinates[identity] for identity in ordered])
    transform = weighted_kabsch(coordinates[indices], target)
    return transform.apply(coordinates)


def _relative_artifact(workspace: Path, path: Path) -> ArtifactReference:
    try:
        relative = path.resolve().relative_to(workspace.resolve())
    except ValueError as exc:
        raise ValueError("candidate output must be inside the request workspace") from exc
    return ArtifactReference(relative.as_posix(), _sha256(path))


class _DenoiserContextProbe:
    """Same state/features/sigma; perturb only partner XYZ before denoising.

    Target output is measured before projection, preventing frame-fit and RNG
    shape changes from masquerading as learned context dependence.
    """

    def __init__(self, axis, request):
        if request.protein_context is None:
            raise ValueError("denoiser probe requires an explicit protein context plan")
        target_chains = {gap.chain for gap in request.gaps}
        partner_atoms = {item.atom for item in request.protein_context.fixed_conditioning if item.atom.chain not in target_chains}
        if not partner_atoms:
            raise ValueError("denoiser probe requires selected partner atoms")
        self.partner_indices = tuple(index for index, atom in enumerate(axis) if atom in partner_atoms)
        self.generated_indices = tuple(index for index, atom in enumerate(axis) if atom in request.generated_atoms)
        self.calls = 0
        self.result = None

    def __call__(self, module, args, kwargs):
        step = self.calls
        self.calls += 1
        if step != 100:
            return
        if args:
            raise RuntimeError("denoiser probe encountered unsupported positional inputs")
        cpu_state = torch.random.get_rng_state()
        cuda_state = torch.cuda.get_rng_state()
        try:
            inputs = dict(kwargs)
            inputs["inplace_safe"] = False
            x = kwargs["x_noisy"].clone()
            inputs["x_noisy"] = x
            base = module.forward(**inputs).clone()
            repeat = module.forward(**inputs).clone()
            shifted = x.clone()
            shifted[..., self.partner_indices, :] += torch.as_tensor((25.0, 0.0, 0.0), device=x.device, dtype=x.dtype)
            inputs["x_noisy"] = shifted
            changed = module.forward(**inputs)
            delta = changed[..., self.generated_indices, :] - base[..., self.generated_indices, :]
            self.result = {
                "step_index": step, "partner_translation_angstrom": [25.0, 0.0, 0.0],
                "state_shape": list(x.shape), "same_features_and_sigma": True,
                "repeat_max_abs_delta_angstrom": float((repeat - base).abs().max().item()),
                "generated_response_rmsd_angstrom": float(torch.sqrt(torch.mean(torch.sum(delta * delta, dim=-1))).item()),
                "generated_response_max_displacement_angstrom": float(torch.linalg.vector_norm(delta, dim=-1).max().item()),
            }
        finally:
            torch.random.set_rng_state(cpu_state)
            torch.cuda.set_rng_state(cuda_state)


def run(
    request_path: Path,
    input_json: Path,
    output_dir: Path,
    kalign: Path,
    checkpoint: Path,
    *,
    cycles: int,
    steps: int,
    ablation_mode: SamplingAblationMode,
    context_probe: bool = False,
) -> tuple[RunnerResult, Path]:
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    from configs.configs_inference import inference_configs
    from protenix.data.inference.infer_dataloader import get_inference_dataloader
    from protenix.utils.seed import seed_everything
    from runner.batch_inference import get_default_runner
    from runner.inference import update_inference_configs

    request_path = request_path.resolve()
    workspace = request_path.parent
    request = DiffusionRequest.from_json(request_path.read_text(encoding="utf-8"))
    if request.candidate_count != 1 or len(request.seeds) != 1:
        raise ValueError("checkpoint smoke requires exactly one candidate and seed")
    if cycles <= 0 or steps <= 0:
        raise ValueError("cycles and steps must be positive")
    checkpoint = checkpoint.resolve()
    if checkpoint.name != _CHECKPOINT_NAME:
        raise ValueError(f"checkpoint must be named {_CHECKPOINT_NAME}")
    if _sha256(checkpoint) != _CHECKPOINT_SHA256:
        raise ValueError("checkpoint digest mismatch")
    inference_configs["load_checkpoint_dir"] = str(checkpoint.parent)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)

    start = time.perf_counter()
    torch.cuda.reset_peak_memory_stats()
    runner = get_default_runner(
        seeds=list(request.seeds),
        n_cycle=cycles,
        n_step=steps,
        n_sample=1,
        dtype="bf16",
        use_msa=False,
        trimul_kernel="torch",
        triatt_kernel="torch",
        enable_cache=False,
        enable_fusion=False,
        use_template=True,
        kalign_binary_path=str(kalign.resolve()),
    )
    device = torch.device(runner.device)
    if device.type != "cuda" or device.index != torch.cuda.current_device():
        raise RuntimeError("Protenix runner did not select the current CUDA device")
    if runner.configs.dtype != "bf16":
        raise RuntimeError("Protenix runner did not retain the frozen bf16 precision")
    _assert_model_on_device(runner.model, device)
    runner.configs.deterministic = True
    runner.configs.deterministic_seed = True
    runner.configs.input_json_path = str(input_json.resolve())
    seed = request.seeds[0]
    seed_everything(seed=seed, deterministic=runner.configs.deterministic)
    batch = next(iter(get_inference_dataloader(configs=runner.configs)))
    data, atom_array, error_message = batch[0]
    if error_message:
        raise RuntimeError(error_message)
    atom_axis, residue_names, elements = _model_atom_axis(atom_array, request)
    source_path = workspace.joinpath(*Path(request.normalized_pdb.path).parts)
    if _sha256(source_path) != request.normalized_pdb.sha256:
        raise ValueError("normalized PDB digest mismatch")
    selected_fixed = (tuple(item.atom for item in request.protein_context.fixed_conditioning)
                      if request.protein_context else request.fixed_atoms)
    fixed_coordinates = _read_fixed_coordinates(source_path, selected_fixed)
    callback = None
    from dvbfixer.model.diffusion.protein_context import context_evidence

    represented_atom_axis = tuple(atom_axis[index] for index in _requested_atom_indices(atom_axis, request))
    evidence = context_evidence(request, represented_atom_axis) if request.protein_context else None
    if ablation_mode is SamplingAblationMode.REINJECTION:
        callback = _TracingCallback(atom_axis, fixed_coordinates, evidence.alignment_atoms if evidence else None)
        runner.model.dvbfixer_step_callback = callback

    runner.update_model_configs(update_inference_configs(runner.configs, data["N_token"].item()))
    probe = _DenoiserContextProbe(atom_axis, request) if context_probe else None
    hook = runner.model.diffusion_module.register_forward_pre_hook(probe, with_kwargs=True) if probe else None
    try:
        prediction = runner.predict(data)
    finally:
        if hook:
            hook.remove()
    coordinates = prediction["coordinate"]
    _assert_model_on_device(runner.model, device)
    if coordinates.device != device or not coordinates.is_floating_point():
        raise RuntimeError("Protenix output coordinates are not on the requested CUDA device")
    if not torch.isfinite(coordinates).all().item():
        raise RuntimeError("Protenix output coordinates contain non-finite values")
    if coordinates.shape[0] != 1:
        raise ValueError("checkpoint smoke expected exactly one sample")
    callback_steps = [] if callback is None else callback.steps
    expected_callback_count = 0 if ablation_mode is SamplingAblationMode.TEMPLATE_ONLY else steps
    if (
        len(callback_steps) != expected_callback_count
        or tuple(step["step_index"] for step in callback_steps)
        != tuple(range(expected_callback_count))
        or any(step["step_count"] != steps for step in callback_steps)
    ):
        raise RuntimeError("callback count does not match the requested ablation")
    if callback is not None and (callback.device != device or callback.dtype is None):
        raise RuntimeError("callback did not observe the frozen CUDA sampling state")
    if callback is not None and callback.dtype != coordinates.dtype:
        raise RuntimeError("sampler input and output coordinate dtypes differ")
    if not torch.are_deterministic_algorithms_enabled():
        raise RuntimeError("PyTorch deterministic algorithms are not enabled")

    final = coordinates[0].detach().to(dtype=torch.float64, device="cpu").numpy()
    final_frame_synchronization = ablation_mode is SamplingAblationMode.TEMPLATE_ONLY
    if final_frame_synchronization:
        final = _synchronize_frame(final, atom_axis, fixed_coordinates)
    output_path = output_dir / "candidate.pdb"
    _write_candidate(
        output_path,
        source_path,
        final,
        atom_axis,
        residue_names,
        elements,
        request,
    )
    resource_metrics = RunnerResourceMetrics(
        wall_time_seconds=time.perf_counter() - start,
        peak_ram_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        peak_vram_bytes=torch.cuda.max_memory_allocated(),
    )
    if not resource_metrics.peak_ram_bytes or not resource_metrics.peak_vram_bytes:
        raise RuntimeError("runner did not record nonzero peak RAM and VRAM")
    represented_atom_axis = tuple(
        atom_axis[index] for index in _requested_atom_indices(atom_axis, request)
    )
    trace_artifact = write_sampler_trace(
        workspace,
        output_dir / "sampler-trace.json",
        build_sampler_trace(
            profile=(
                "protenix-v1-cuda"
                if ablation_mode is SamplingAblationMode.REINJECTION
                else "protenix-v1-template-only-research"
            ),
            engine_repository="https://github.com/bytedance/Protenix",
            engine_revision="85767b811c40ed46e73a9b39519cf6bfca8701ba",
            patch_identity=f"sha256:{_PATCH_SHA256}",
            atom_order=represented_atom_axis,
            fixed_atoms=request.fixed_atoms,
            represented_fixed_atoms=selected_fixed,
            protein_context_evidence=evidence,
            device=str(runner.device),
            fallback_disabled=True,
            denoising_update_count=steps,
            projection_errors_angstrom=tuple(
                float(step["post_projection_max_error_angstrom"])
                for step in callback_steps
            ),
            final_fixed_coordinate_restoration=False,
            resource_metrics=resource_metrics,
            sampler_evidence_complete=True,
        ),
    )
    candidate = RunnerCandidate(
        candidate_id=f"protenix-v1-{ablation_mode.value}-seed-{seed}",
        seed=seed,
        coordinate_artifact=_relative_artifact(workspace, output_path),
        sampler_trace_artifact=trace_artifact,
        generated_atoms=request.generated_atoms,
        generated_residues=tuple(
            residue for gap in request.gaps for residue in gap.generated_residues
        ),
        raw_backend_score=None,
        score_provenance="protenix-v1:unranked-checkpoint-smoke",
    )
    runner_result = RunnerResult(
        schema_version=DIFFUSION_SCHEMA_VERSION,
        status=DiffusionStatus.SUCCESS,
        candidates=(candidate,),
        runner_diagnostics=RunnerDiagnostics(exit_code=0, timed_out=False),
        backend_provenance=BackendProvenance(
            backend="protenix-v1-hook-spike",
            runner_protocol_version=DIFFUSION_RUNNER_PROTOCOL_VERSION,
            engine_repository="https://github.com/bytedance/Protenix",
            engine_revision="85767b811c40ed46e73a9b39519cf6bfca8701ba",
            checkpoint_sha256=_CHECKPOINT_SHA256,
            device=str(runner.device),
            precision=runner.configs.dtype,
            framework="torch",
            framework_version=torch.__version__,
            cuda_version=str(torch.version.cuda or ""),
            deterministic_algorithms=bool(runner.configs.deterministic),
        ),
        resource_metrics=resource_metrics,
    )
    validation = validate_runner_result(request, runner_result, workspace=workspace)[0]
    summary = {
        "candidate_sha256": candidate.coordinate_artifact.sha256,
        "ablation_mode": ablation_mode.value,
        "model_atom_count": len(atom_axis),
        "written_atom_count": len(request.fixed_atoms) + len(request.generated_atoms),
        "cycles": cycles,
        "diffusion_steps": steps,
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "sampler_device": str(callback.device) if callback is not None else str(device),
        "sampler_dtype": str(callback.dtype) if callback is not None else str(coordinates.dtype),
        "callback_count": len(callback_steps),
        "callback_steps": callback_steps,
        **({"denoiser_context_probe": probe.result} if probe else {}),
        "final_frame_synchronization": final_frame_synchronization,
        "validation": asdict(validation.summary),
        "ranking_metrics": [asdict(metric) for metric in validation.ranking_metrics],
        "wall_time_seconds": runner_result.resource_metrics.wall_time_seconds,
        "peak_vram_bytes": runner_result.resource_metrics.peak_vram_bytes,
        "peak_ram_bytes": runner_result.resource_metrics.peak_ram_bytes,
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(summary_path)
    return runner_result, summary_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("input_json", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--kalign", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--cycles", default=1, type=int)
    parser.add_argument("--steps", default=2, type=int)
    parser.add_argument(
        "--ablation-mode",
        choices=(
            SamplingAblationMode.TEMPLATE_ONLY.value,
            SamplingAblationMode.REINJECTION.value,
        ),
        default=SamplingAblationMode.REINJECTION.value,
    )
    args = parser.parse_args()
    run(
        args.request,
        args.input_json,
        args.output_dir,
        args.kalign,
        args.checkpoint,
        cycles=args.cycles,
        steps=args.steps,
        ablation_mode=SamplingAblationMode(args.ablation_mode),
    )


if __name__ == "__main__":
    main()
