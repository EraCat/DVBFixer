"""Run Protpardelle-1c cc89 on one materialized DVBFixer gap request."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import shutil
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np

from dvbfixer.model.diffusion.benchmark import candidate_quality, load_pdb_coordinates
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
    SamplerConditioningContext,
    SequencePlacement,
    TargetSequence,
)
from dvbfixer.model.diffusion.geometry import synchronize_and_reinject, weighted_kabsch
from dvbfixer.model.diffusion.pdb_materialize import materialize_candidate_pdb
from dvbfixer.model.diffusion.protein_context import (
    context_evidence,
    engine_context_view,
    select_legacy_partner_spans,
    source_context_position_features,
    validate_context_source,
)
from dvbfixer.model.diffusion.runner import DIFFUSION_RUNNER_PROTOCOL_VERSION
from dvbfixer.model.diffusion.trace import build_sampler_trace, write_sampler_trace
from dvbfixer.model.diffusion.validate import validate_runner_result

_REVISION = "ee378400f25b801fa481028000f9060183d7fb4c"
_CHECKPOINT_SHA256 = "dfc9895b399ec4497bf6d646502168725f01dcbd55bc0b541fc3e3cc1f2f0483"
_CONFIG_SHA256 = "e9999ace79bf3044351cc982a624fc3459add3a4f91cbf97ff5b437b8942eb9d"
_APPLE_PATCH_SHA256 = "627891e28d5055cb0d903f542af695569d7133b0480cab8f25d154dc8ccc78c9"
_MPS_ENVIRONMENT_KEYS = (
    "PYTORCH_ENABLE_MPS_FALLBACK",
    "PYTORCH_MPS_FAST_MATH",
    "PYTORCH_MPS_PREFER_METAL",
    "PYTORCH_MPS_HIGH_WATERMARK_RATIO",
    "PYTORCH_MPS_LOW_WATERMARK_RATIO",
)
_INTERCHAIN_CONTEXT_CUTOFF_ANGSTROM = 12.0
_INTERCHAIN_CONTEXT_SEQUENCE_PADDING = 2
_HETEROGEN_REPULSION_CUTOFF_ANGSTROM = 2.0


def _resolve_device(torch: Any, requested: str) -> Any:
    """Resolve an explicitly requested device without automatic fallback."""
    device = torch.device(requested)
    if device.type not in {"cpu", "cuda", "mps"}:
        raise ValueError(f"unsupported Protpardelle device: {requested}")
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    if device.type == "mps":
        if not torch.backends.mps.is_built():
            raise RuntimeError("MPS was requested but this PyTorch build has no MPS support")
        if not torch.backends.mps.is_available():
            raise RuntimeError("MPS was requested but is unavailable on this host")
        if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") != "0":
            raise RuntimeError(
                "MPS acceptance runs require PYTORCH_ENABLE_MPS_FALLBACK=0 "
                "before Python starts"
            )
    return device


def _same_device(actual: Any, expected: Any) -> bool:
    actual_device = actual if hasattr(actual, "type") else None
    if actual_device is None or actual_device.type != expected.type:
        return False
    return expected.index is None or actual_device.index == expected.index


def _assert_model_device(model: Any, expected: Any) -> None:
    mismatches = [
        f"parameter:{name}:{value.device}"
        for name, value in model.named_parameters()
        if not _same_device(value.device, expected)
    ]
    mismatches.extend(
        f"buffer:{name}:{value.device}"
        for name, value in model.named_buffers()
        if not _same_device(value.device, expected)
    )
    if mismatches:
        preview = ", ".join(mismatches[:5])
        raise RuntimeError(f"model state is not entirely on {expected}: {preview}")


def _assert_tensor_device(name: str, value: Any, expected: Any) -> None:
    if not _same_device(value.device, expected):
        raise RuntimeError(f"{name} is on {value.device}, expected {expected}")


def _synchronize(torch: Any, device: Any) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    elif device.type == "mps":
        torch.mps.synchronize()


def _coordinates_to_numpy(torch: Any, coordinates: Any) -> np.ndarray:
    """Copy coordinates to CPU before widening beyond MPS-supported dtypes."""
    cpu_coordinates = coordinates.detach().to(device="cpu")
    return cpu_coordinates.to(dtype=torch.float64).numpy()


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


class _AcceleratorTelemetry:
    """Collect device-aware allocator data without reporting absent data as zero."""

    def __init__(self, torch: Any, device: Any) -> None:
        self._torch = torch
        self._device = device
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._mps_current_samples: list[int] = []
        self._mps_driver_samples: list[int] = []
        self._sampling_error: str | None = None

    @staticmethod
    def _optional_mps_value(torch: Any, name: str) -> int | None:
        function = getattr(torch.mps, name, None)
        return int(function()) if callable(function) else None

    def _sample_mps(self) -> None:
        current = self._optional_mps_value(self._torch, "current_allocated_memory")
        driver = self._optional_mps_value(self._torch, "driver_allocated_memory")
        if current is not None:
            self._mps_current_samples.append(current)
        if driver is not None:
            self._mps_driver_samples.append(driver)

    def _sample_until_stopped(self) -> None:
        while not self._stop.wait(0.05):
            try:
                self._sample_mps()
            except Exception as exc:  # pragma: no cover - requires a failing MPS runtime
                self._sampling_error = f"{type(exc).__name__}: {exc}"
                return

    def start(self) -> None:
        if self._device.type == "cuda":
            self._torch.cuda.reset_peak_memory_stats(self._device)
        elif self._device.type == "mps":
            self._sample_mps()
            self._thread = threading.Thread(
                target=self._sample_until_stopped,
                name="dvbfixer-mps-memory",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> dict[str, int | None]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        if self._sampling_error is not None:
            raise RuntimeError(f"MPS memory telemetry failed: {self._sampling_error}")
        if self._device.type == "mps":
            self._sample_mps()
        peak_accelerator: int | None = None
        if self._device.type == "cuda":
            peak_accelerator = int(self._torch.cuda.max_memory_allocated(self._device))
        elif self._device.type == "mps" and self._mps_driver_samples:
            peak_accelerator = max(self._mps_driver_samples)
        recommended = (
            self._optional_mps_value(self._torch, "recommended_max_memory")
            if self._device.type == "mps"
            else None
        )
        return {
            "peak_accelerator_allocated_bytes": peak_accelerator,
            "peak_mps_tensor_allocated_bytes": (
                max(self._mps_current_samples) if self._mps_current_samples else None
            ),
            "peak_mps_driver_allocated_bytes": (
                max(self._mps_driver_samples) if self._mps_driver_samples else None
            ),
            "mps_recommended_max_memory_bytes": recommended,
            "peak_rss_bytes": _peak_rss_bytes(),
        }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _target_residue_map(request: DiffusionRequest) -> dict[int, ResidueIdentity]:
    placements = {placement.chain: placement for placement in request.sequence_placements}
    mapping: dict[int, ResidueIdentity] = {}
    offsets: dict[str, int] = {}
    offset = 0
    for target in request.target_sequences:
        try:
            placement = placements[target.chain]
        except KeyError as exc:
            raise ValueError("target sequence omits its placement") from exc
        if placement.target_length != len(target.sequence):
            raise ValueError("sequence placement length differs from target sequence")
        offsets[target.chain] = offset
        mapping.update({
            offset + index: residue
            for index, residue in zip(
                placement.observed_target_indices,
                placement.observed_residues,
            )
        })
        offset += len(target.sequence)
    for gap in request.gaps:
        chain_offset = offsets[gap.chain]
        for index, residue in zip(
            range(gap.target_interval.start, gap.target_interval.stop),
            gap.generated_residues,
        ):
            flat_index = chain_offset + index
            if flat_index in mapping:
                raise ValueError(f"target index {index} is mapped more than once")
            mapping[flat_index] = residue
    total_length = sum(len(target.sequence) for target in request.target_sequences)
    if set(mapping) != set(range(total_length)):
        raise ValueError("request does not map every target residue exactly once")
    return mapping


def _target_sequence(request: DiffusionRequest) -> str:
    return "".join(target.sequence for target in request.target_sequences)


def _chain_sampling_requests(
    request: DiffusionRequest,
    fixed_coordinates: dict[AtomIdentity, np.ndarray] | None = None,
) -> tuple[DiffusionRequest, ...]:
    """Build gap-chain invocations with optional local fixed partner context."""
    if request.protein_context is not None:
        view = engine_context_view(request)
        if len(view.request.target_sequences) > 26:
            raise ValueError("cc89 supports at most 26 selected engine entities")
        return (view.request,)
    gap_chains = {gap.chain for gap in request.gaps}
    requests: list[DiffusionRequest] = []
    for target in request.target_sequences:
        if target.chain not in gap_chains:
            continue
        chain = target.chain
        if len(target.sequence) > 512:
            raise ValueError(
                f"target chain {chain} length {len(target.sequence)} exceeds "
                "the cc89 fixed-size limit of 512 residues"
            )
        context_targets: tuple[TargetSequence, ...] = ()
        context_placements: tuple[SequencePlacement, ...] = ()
        context_atoms: tuple[AtomIdentity, ...] = ()
        if fixed_coordinates is not None:
            context_targets, context_placements, context_atoms = (
                _local_partner_context(
                    request,
                    chain,
                    fixed_coordinates,
                    residue_budget=512 - len(target.sequence),
                )
            )
        selected_fixed = set(context_atoms)
        selected_fixed.update(
            atom for atom in request.fixed_atoms if atom.chain == chain
        )
        selected_fixed.update(
            atom
            for context in request.heterogen_contexts
            for atom in context.atoms
        )
        requests.append(replace(
            request,
            target_sequences=(target, *context_targets),
            sequence_placements=tuple(
                placement
                for placement in request.sequence_placements
                if placement.chain == chain
            ) + context_placements,
            gaps=tuple(gap for gap in request.gaps if gap.chain == chain),
            fixed_atoms=tuple(
                atom for atom in request.fixed_atoms if atom in selected_fixed
            ),
            generated_atoms=tuple(
                atom for atom in request.generated_atoms if atom.chain == chain
            ),
            template_ownership=tuple(
                ownership
                for ownership in request.template_ownership
                if ownership.chain == chain
            ),
            regenerated_template_ownership=(tuple(owner for owner in request.regenerated_template_ownership if owner.chain == chain)
                                            if request.regenerated_template_ownership is not None else None),
            retained_explicit_links=(),
        ))
    if not requests:
        raise ValueError("cc89 request contains no gap-bearing target chains")
    return tuple(requests)


def _local_partner_context(
    request: DiffusionRequest,
    target_chain: str,
    fixed_coordinates: dict[AtomIdentity, np.ndarray],
    *,
    residue_budget: int,
) -> tuple[
    tuple[TargetSequence, ...],
    tuple[SequencePlacement, ...],
    tuple[AtomIdentity, ...],
]:
    """Materialize the shared legacy-compatible source-only selection policy."""
    targets = {target.chain: target for target in request.target_sequences}
    placements = {placement.chain: placement for placement in request.sequence_placements}
    selected_targets: list[TargetSequence] = []
    selected_placements: list[SequencePlacement] = []
    selected_residues: set[ResidueIdentity] = set()
    for span in select_legacy_partner_spans(request, target_chain, fixed_coordinates, residue_budget=residue_budget):
        placement = placements[span.chain]
        selected = tuple((index, residue) for index, residue in zip(placement.observed_target_indices, placement.observed_residues)
                         if span.start <= index < span.stop)
        sequence = targets[span.chain].sequence[span.start:span.stop]
        selected_targets.append(TargetSequence(span.chain, sequence))
        selected_placements.append(SequencePlacement(
            chain=span.chain,
            target_length=len(sequence),
            observed_target_indices=tuple(index - span.start for index, _ in selected),
            observed_residues=tuple(residue for _, residue in selected),
        ))
        selected_residues.update(residue for _, residue in selected)

    selected_atoms = tuple(
        atom
        for atom in request.fixed_atoms
        if ResidueIdentity(
            atom.chain,
            atom.residue_number,
            atom.insertion_code,
        ) in selected_residues
    )
    return tuple(selected_targets), tuple(selected_placements), selected_atoms


def _motif_chain_labels(request: DiffusionRequest) -> dict[str, str]:
    labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if len(request.target_sequences) > len(labels):
        raise ValueError("cc89 benchmark supports at most 26 protein chains")
    return {
        target.chain: labels[index]
        for index, target in enumerate(request.target_sequences)
    }


def _local_target_indices(request: DiffusionRequest) -> dict[ResidueIdentity, int]:
    return {
        residue: index
        for placement in request.sequence_placements
        for index, residue in zip(
            placement.observed_target_indices,
            placement.observed_residues,
        )
    }


def _motif_placement(request: DiffusionRequest) -> tuple[str, list[int]]:
    labels = _motif_chain_labels(request)
    offset = 0
    placements: list[str] = []
    fixed_positions: list[int] = []
    gaps_by_chain = {
        target.chain: sorted(
            (gap for gap in request.gaps if gap.chain == target.chain),
            key=lambda gap: gap.target_interval.start,
        )
        for target in request.target_sequences
    }
    for target in request.target_sequences:
        segments: list[str] = []
        cursor = 0
        for gap in gaps_by_chain[target.chain]:
            start = gap.target_interval.start
            stop = gap.target_interval.stop
            if start < cursor:
                raise ValueError("diffusion gaps overlap on a target chain")
            if cursor < start:
                segments.append(f"{labels[target.chain]}{cursor + 1}-{start}")
                fixed_positions.extend(range(offset + cursor, offset + start))
            segments.append(str(stop - start))
            cursor = stop
        if cursor < len(target.sequence):
            segments.append(
                f"{labels[target.chain]}{cursor + 1}-{len(target.sequence)}"
            )
            fixed_positions.extend(range(offset + cursor, offset + len(target.sequence)))
        placements.append("/".join(segments))
        offset += len(target.sequence)
    return ";/;".join(placements), fixed_positions


def _read_fixed_coordinates(
    path: Path,
    fixed_atoms: tuple[AtomIdentity, ...],
) -> dict[AtomIdentity, np.ndarray]:
    expected = set(fixed_atoms)
    coordinates: dict[AtomIdentity, np.ndarray] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")) or line[16:17] not in {"", " ", "A"}:
            continue
        identity = AtomIdentity(
            line[21:22], line[22:26].strip(), line[26:27].strip(), line[12:16].strip()
        )
        if identity in expected:
            if identity in coordinates:
                raise ValueError(f"duplicate fixed atom: {identity}")
            coordinates[identity] = np.asarray(
                [float(line[30:38]), float(line[38:46]), float(line[46:54])],
                dtype=np.float64,
            )
    missing = expected - set(coordinates)
    if missing:
        raise ValueError(f"normalized PDB omits {len(missing)} fixed atoms")
    return coordinates


def _read_fixed_residue_names(
    path: Path,
    fixed_atoms: tuple[AtomIdentity, ...],
) -> dict[AtomIdentity, str]:
    expected = set(fixed_atoms)
    names: dict[AtomIdentity, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")) or line[16:17] not in {"", " ", "A"}:
            continue
        identity = AtomIdentity(
            line[21:22], line[22:26].strip(), line[26:27].strip(), line[12:16].strip()
        )
        if identity in expected:
            names[identity] = line[17:20].strip()
    if set(names) != expected:
        raise ValueError(f"normalized PDB omits {len(expected - set(names))} fixed atom names")
    return names


def _write_motif_input(
    source: Path,
    destination: Path,
    request: DiffusionRequest,
    source_to_engine: dict[AtomIdentity, AtomIdentity] | None = None,
) -> None:
    fixed_atom_set = set(request.fixed_atoms)
    target_index = _local_target_indices(request)
    chain_labels = _motif_chain_labels(request)
    heterogen_atoms = {
        atom for context in request.heterogen_contexts for atom in context.atoms
    }
    lines: list[str] = []
    serial = 1
    seen: set[AtomIdentity] = set()
    for line in source.read_text(encoding="ascii").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")) or line[16:17] not in {"", " ", "A"}:
            continue
        identity = AtomIdentity(
            line[21:22], line[22:26].strip(), line[26:27].strip(), line[12:16].strip()
        )
        if source_to_engine is not None:
            if identity not in source_to_engine:
                continue
            identity = source_to_engine[identity]
        residue = ResidueIdentity(identity.chain, identity.residue_number, identity.insertion_code)
        if identity not in fixed_atom_set:
            continue
        if identity in seen:
            raise ValueError(f"duplicate motif atom: {identity}")
        seen.add(identity)
        if identity in heterogen_atoms:
            record = "HETATM" + f"{serial:5d}" + line[11:]
        else:
            if residue not in target_index:
                continue
            ordinal = target_index[residue] + 1
            record = (
                "ATOM  " + f"{serial:5d}" + line[11:21]
                + chain_labels[residue.chain] + f"{ordinal:4d}" + " " + line[27:]
            )
        lines.append(record + "\n")
        serial += 1
    if seen != fixed_atom_set:
        raise ValueError(
            "motif input atom set mismatch: "
            f"missing={len(fixed_atom_set - seen)}, extra={len(seen - fixed_atom_set)}"
        )
    lines.append(f"TER   {serial:5d}\nEND\n")
    destination.write_text("".join(lines), encoding="ascii")


def _model_atoms(
    request: DiffusionRequest,
    coordinates: np.ndarray,
) -> tuple[tuple[AtomIdentity, ...], np.ndarray, tuple[str, ...]]:
    from protpardelle.common import residue_constants

    target_sequence = _target_sequence(request)
    residue_map = _target_residue_map(request)
    if coordinates.shape != (len(target_sequence), 37, 3):
        raise ValueError(f"unexpected cc89 coordinate shape: {coordinates.shape}")
    identities: list[AtomIdentity] = []
    values: list[np.ndarray] = []
    residue_names: list[str] = []
    for index, amino_acid in enumerate(target_sequence):
        aatype = residue_constants.restype_order[amino_acid]
        residue = residue_map[index]
        residue_name = residue_constants.restype_1to3[amino_acid]
        for atom_index, present in enumerate(residue_constants.restype_atom37_mask[aatype]):
            if not present:
                continue
            identities.append(
                AtomIdentity(
                    residue.chain,
                    residue.residue_number,
                    residue.insertion_code,
                    residue_constants.atom_types[atom_index],
                )
            )
            values.append(coordinates[index, atom_index])
            residue_names.append(residue_name)
    return tuple(identities), np.asarray(values, dtype=np.float64), tuple(residue_names)


def _synchronize_and_restore_fixed_atoms(
    identities: tuple[AtomIdentity, ...],
    coordinates: np.ndarray,
    residue_names: tuple[str, ...],
    fixed_coordinates: dict[AtomIdentity, np.ndarray],
    fixed_residue_names: dict[AtomIdentity, str],
    request: DiffusionRequest | None = None,
    *,
    joint_frame: bool = False,
) -> tuple[tuple[AtomIdentity, ...], np.ndarray, tuple[str, ...]]:
    represented = set(identities)
    synchronized = coordinates.copy()
    index_by_identity = {identity: index for index, identity in enumerate(identities)}
    if joint_frame:
        alignment = tuple(sorted(set(fixed_coordinates) & set(identities)))
        transform = weighted_kabsch(np.asarray([coordinates[index_by_identity[atom]] for atom in alignment]),
                                    np.asarray([fixed_coordinates[atom] for atom in alignment]))
        synchronized = transform.apply(coordinates)
        for atom in alignment:
            synchronized[index_by_identity[atom]] = fixed_coordinates[atom]
    elif request is None:
        for chain in dict.fromkeys(identity.chain for identity in identities):
            indices = [
                index for index, identity in enumerate(identities) if identity.chain == chain
            ]
            chain_identities = tuple(identities[index] for index in indices)
            alignment_fixed = {
                identity: coordinate
                for identity, coordinate in fixed_coordinates.items()
                if identity.chain == chain and identity in represented
            }
            synchronized[indices] = synchronize_and_reinject(
                chain_identities,
                coordinates[indices],
                alignment_fixed,
            )
    else:
        for gap in request.gaps:
            anchor_residues = {
                anchor
                for anchor in (gap.left_anchor, gap.right_anchor)
                if anchor is not None
            }
            anchor_atoms = tuple(
                identity
                for identity in identities
                if ResidueIdentity(
                    identity.chain,
                    identity.residue_number,
                    identity.insertion_code,
                ) in anchor_residues
                and identity in fixed_coordinates
            )
            if len(anchor_atoms) < 3:
                raise ValueError("gap synchronization requires at least three anchor atoms")
            mobile = np.vstack([
                coordinates[index_by_identity[identity]] for identity in anchor_atoms
            ])
            target = np.vstack([fixed_coordinates[identity] for identity in anchor_atoms])
            transform = weighted_kabsch(mobile, target)
            generated_residues = set(gap.generated_residues)
            generated_indices = [
                index
                for index, identity in enumerate(identities)
                if ResidueIdentity(
                    identity.chain,
                    identity.residue_number,
                    identity.insertion_code,
                ) in generated_residues
            ]
            synchronized[generated_indices] = transform.apply(
                coordinates[generated_indices]
            )
        for identity, coordinate in fixed_coordinates.items():
            if identity in index_by_identity:
                synchronized[index_by_identity[identity]] = coordinate
    source_only = tuple(sorted(set(fixed_coordinates) - represented))
    if not source_only:
        return identities, synchronized, residue_names
    if set(fixed_residue_names) != set(fixed_coordinates):
        raise ValueError("fixed residue names must cover every fixed atom")
    restored_coordinates = np.vstack(
        [synchronized, *(fixed_coordinates[identity] for identity in source_only)]
    )
    return (
        identities + source_only,
        restored_coordinates,
        residue_names + tuple(fixed_residue_names[identity] for identity in source_only),
    )


def _native_conditioning_fit(
    identities: tuple[AtomIdentity, ...],
    coordinates: np.ndarray,
    fixed_coordinates: dict[AtomIdentity, np.ndarray],
    *,
    joint_frame: bool = False,
) -> dict[str, float | int]:
    index_by_identity = {identity: index for index, identity in enumerate(identities)}
    represented = tuple(sorted(set(fixed_coordinates) & set(index_by_identity)))
    if len(represented) < 3:
        raise ValueError("native conditioning fit requires at least three represented fixed atoms")
    displacement_groups: list[np.ndarray] = []
    groups = [represented] if joint_frame else [tuple(identity for identity in represented if identity.chain == chain)
                                               for chain in dict.fromkeys(identity.chain for identity in represented)]
    for chain_atoms in groups:
        if len(chain_atoms) < 3:
            raise ValueError(
                "native conditioning fit requires at least three fixed atoms per alignment group"
            )
        mobile = np.vstack([
            coordinates[index_by_identity[identity]] for identity in chain_atoms
        ])
        target = np.vstack([fixed_coordinates[identity] for identity in chain_atoms])
        aligned = weighted_kabsch(mobile, target).apply(mobile)
        displacement_groups.append(np.linalg.norm(aligned - target, axis=1))
    displacements = np.concatenate(displacement_groups)
    return {
        "represented_fixed_atom_count": len(represented),
        "source_only_fixed_atom_count": len(fixed_coordinates) - len(represented),
        "rmsd_angstrom": float(np.sqrt(np.mean(np.square(displacements)))),
        "max_displacement_angstrom": float(np.max(displacements)),
    }


def _make_per_step_reinjector(
    request: DiffusionRequest,
    fixed_coordinates: dict[AtomIdentity, np.ndarray],
) -> tuple[Callable[..., Any], dict[str, float | int]]:
    import torch
    from protpardelle.common import residue_constants

    target_index_by_residue = {
        residue: index for index, residue in _target_residue_map(request).items()
    }
    target_sequence = _target_sequence(request)
    represented: list[tuple[int, int, np.ndarray]] = []
    for identity in sorted(fixed_coordinates):
        residue = ResidueIdentity(
            identity.chain,
            identity.residue_number,
            identity.insertion_code,
        )
        target_index = target_index_by_residue.get(residue)
        atom_index = residue_constants.atom_order.get(identity.atom_name)
        if target_index is None or atom_index is None:
            continue
        aatype = residue_constants.restype_order[target_sequence[target_index]]
        if not residue_constants.restype_atom37_mask[aatype][atom_index]:
            continue
        represented.append((target_index, atom_index, fixed_coordinates[identity]))
    if len(represented) < 3:
        raise ValueError("per-step reinjection requires at least three represented fixed atoms")

    target_indices = tuple(item[0] for item in represented)
    atom_indices = tuple(item[1] for item in represented)
    stats: dict[str, float | int] = {
        "callback_count": 0,
        "represented_fixed_atom_count": len(represented),
        "maximum_post_projection_error_angstrom": 0.0,
    }

    def callback(
        state: Any,
        step_index: int,
        step_count: int,
        motif_indices: list[list[int]] | None,
        motif_coordinates: Any,
        motif_mask: Any,
    ) -> Any:
        if state.ndim != 4 or state.shape[0] != 1 or state.shape[-1] != 3:
            raise ValueError("per-step reinjection expects coordinate shape (1, L, A, 3)")
        if step_index != stats["callback_count"] or step_count <= step_index:
            raise ValueError("per-step callback sequence is inconsistent")
        if motif_indices is None or motif_coordinates is None or motif_mask is None:
            raise ValueError("per-step reinjection requires internal motif coordinates")
        if len(motif_indices) != state.shape[0]:
            raise ValueError("motif index batch does not match coordinate batch")
        with torch.no_grad():
            projected = state.clone()
            positions = motif_indices[0]
            coordinates = motif_coordinates[0].to(device=state.device, dtype=state.dtype)
            mask = motif_mask[0].to(device=state.device, dtype=torch.bool)
            if len(positions) != coordinates.shape[0] or mask.shape != coordinates.shape[:-1]:
                raise ValueError("motif callback context has inconsistent shapes")
            motif_row_by_target = {target_index: row for row, target_index in enumerate(positions)}
            try:
                motif_rows = tuple(motif_row_by_target[index] for index in target_indices)
            except KeyError as exc:
                raise ValueError("represented fixed residue is absent from motif placement") from exc
            if not bool(mask[motif_rows, atom_indices].all()):
                raise ValueError("represented fixed atom is absent from internal motif mask")
            authoritative = coordinates[motif_rows, atom_indices]
            projected[0, target_indices, atom_indices] = authoritative
            error = torch.linalg.vector_norm(
                projected[0, target_indices, atom_indices] - authoritative,
                dim=-1,
            ).max()
        stats["callback_count"] = int(stats["callback_count"]) + 1
        stats["maximum_post_projection_error_angstrom"] = max(
            float(stats["maximum_post_projection_error_angstrom"]),
            float(error.item()),
        )
        return projected

    return callback, stats


def _write_candidate(
    path: Path,
    source_path: Path,
    identities: tuple[AtomIdentity, ...],
    coordinates: np.ndarray,
    residue_names: tuple[str, ...],
    request: DiffusionRequest,
) -> None:
    path.write_text(
        materialize_candidate_pdb(
            source_path.read_text(encoding="ascii"),
            identities,
            coordinates,
            residue_names,
            request,
        ),
        encoding="ascii",
    )


def _artifact(workspace: Path, path: Path) -> ArtifactReference:
    return ArtifactReference(path.resolve().relative_to(workspace.resolve()).as_posix(), _sha256(path))


class _DenoiserContextProbe:
    """Research-only, same-input intervention before projection at forward call 100."""

    def __init__(self, request):
        from protpardelle.common import residue_constants

        mapped = _target_residue_map(request)
        index = {residue: position for position, residue in mapped.items()}
        gap_chains = {gap.chain for gap in request.gaps}
        def address(atom):
            residue = ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code)
            return index[residue], residue_constants.atom_order[atom.atom_name]
        self.partners = tuple(address(atom) for atom in request.fixed_atoms if atom.chain not in gap_chains)
        self.generated = tuple(address(atom) for atom in request.generated_atoms)
        if not self.partners or not self.generated:
            raise ValueError("causal probe requires represented fixed partner and generated atoms")
        self.calls = 0
        self.result = None

    def __call__(self, module, args, kwargs):
        import torch

        index = self.calls
        self.calls += 1
        if index != 100:
            return
        if len(args) != 3:
            raise RuntimeError("unexpected Protpardelle denoiser positional signature")
        state = args[0]
        cpu_rng = torch.random.get_rng_state()
        cuda_rng = torch.cuda.get_rng_state_all() if state.device.type == "cuda" else None
        mps_rng = torch.mps.get_rng_state() if state.device.type == "mps" else None
        try:
            base = module.forward(*args, **kwargs).clone()
            repeat = module.forward(*args, **kwargs).clone()
            shifted = state.clone()
            for residue, atom in self.partners:
                shifted[:, residue, atom, 0] += 25.0
            changed = module.forward(shifted, *args[1:], **kwargs)
            delta = torch.stack([changed[:, residue, atom] - base[:, residue, atom]
                                 for residue, atom in self.generated], dim=1)
            self.result = {
                "forward_call_index": index, "partner_translation_angstrom": [25.0, 0.0, 0.0],
                "same_features_and_sigma": True, "before_projection": True,
                "repeat_max_abs_delta_angstrom": float((repeat - base).abs().max().item()),
                "generated_response_rmsd_angstrom": float(torch.sqrt(torch.mean(torch.sum(delta * delta, dim=-1))).item()),
                "generated_response_max_displacement_angstrom": float(torch.linalg.vector_norm(delta, dim=-1).max().item()),
            }
        finally:
            torch.random.set_rng_state(cpu_rng)
            if cuda_rng is not None:
                torch.cuda.set_rng_state_all(cuda_rng)
            if mps_rng is not None:
                torch.mps.set_rng_state(mps_rng)


@contextmanager
def _probe_hook(module, probe):
    hook = module.register_forward_pre_hook(probe, with_kwargs=True) if probe else None
    try:
        yield
    finally:
        if hook:
            hook.remove()


class _NeutralDenoiserChainPhase:
    """cc89 compatibility intervention: neutral phase, unchanged residue breaks.

    cc89 is a monomer-trained rotary model. Its source chain identities remain
    intact in the sampler, motif mapping, and output; only the denoiser's extra
    chain-frequency term is disabled. Residue-index gaps still separate chains.
    """

    def __init__(self):
        self.calls = 0
        self.chain_labels = ()

    def __call__(self, module, args, kwargs):
        import torch

        if len(args) != 3 or "chain_index" not in kwargs or "residue_index" not in kwargs:
            raise ValueError("unexpected denoiser positional-feature signature")
        chain_index = kwargs["chain_index"]
        residue_index = kwargs["residue_index"]
        if chain_index is None or chain_index.shape != residue_index.shape:
            raise ValueError("chain phase control requires explicit matching position features")
        if self.calls == 0:
            labels = chain_index.detach().cpu().numpy()
            positions = residue_index.detach().cpu().numpy()
            boundaries = labels[:, 1:] != labels[:, :-1]
            if np.any(boundaries & (positions[:, 1:] - positions[:, :-1] <= 1)):
                raise ValueError("neutral chain phase requires explicit residue-index chain breaks")
            self.chain_labels = tuple(int(value) for value in np.unique(labels))
        self.calls += 1
        return args, {**kwargs, "chain_index": torch.zeros_like(chain_index)}


def _require_chain_phase_policy(request, device_name, policy):
    declared = next((option.value for option in request.backend_options if option.name == "cc89_chain_phase"), "native")
    if policy not in {"native", "neutral-v1"} or declared != policy:
        raise ValueError("cc89 chain phase policy must match the explicitly declared request")
    if policy != "native" and device_name.split(":", 1)[0] != "cuda":
        raise ValueError("neutral cc89 chain phase is CUDA research-only")


def _require_position_feature_policy(request, device_name, policy, chain_phase):
    declared = next((option.value for option in request.backend_options if option.name == "cc89_position_features"), "native")
    if policy not in {"native", "source-physical-v1"} or declared != policy:
        raise ValueError("cc89 position feature policy must match the explicitly declared request")
    if policy != "native" and (device_name.split(":", 1)[0] != "cuda" or request.protein_context is None or chain_phase != "neutral-v1"):
        raise ValueError("source-physical cc89 positions require explicit CUDA context and neutral-v1 phase")


def _run_staged(
    request_path: Path,
    output_dir: Path,
    config_path: Path,
    checkpoint_path: Path,
    *,
    steps: int,
    step_scale: float,
    s_churn: float,
    per_step_reinjection: bool,
    device_name: str,
    mps_profile: bool,
    context_probe: bool = False,
    crop_strategy: str = "backbone-sidechain",
    replacement_guidance: bool = False,
    chain_phase_policy: str = "native",
    position_feature_policy: str = "native",
) -> tuple[RunnerResult, Path]:
    import torch
    from protpardelle.common import residue_constants
    from protpardelle.core.models import load_model
    from protpardelle.utils import seed_everything

    if steps <= 0:
        raise ValueError("steps must be positive")
    if crop_strategy not in {"backbone-sidechain", "backbone", "sidechain", "sidechain-tip"}:
        raise ValueError("unsupported crop conditioning strategy")
    if _sha256(config_path) != _CONFIG_SHA256 or _sha256(checkpoint_path) != _CHECKPOINT_SHA256:
        raise ValueError("cc89 config or checkpoint digest mismatch")
    request_path = request_path.resolve()
    workspace = request_path.parent
    request = DiffusionRequest.from_json(request_path.read_text(encoding="utf-8"))
    _require_chain_phase_policy(request, device_name, chain_phase_policy)
    _require_position_feature_policy(request, device_name, position_feature_policy, chain_phase_policy)
    cuda_production = any(option.name == "profile" and option.value == "protpardelle-1c-cuda" for option in request.backend_options)
    if cuda_production:
        from dvbfixer.model.diffusion.protein_context import validate_cuda_cc89_request

        validate_cuda_cc89_request(request)
        if (device_name.split(":", 1)[0] != "cuda" or steps != 500 or step_scale != 1.2
                or s_churn != 200.0 or per_step_reinjection or replacement_guidance
                or position_feature_policy != "source-physical-v1" or chain_phase_policy != "neutral-v1"):
            raise ValueError("public CUDA cc89 requires its frozen numerical policy")
    if request.candidate_count != 1 or len(request.seeds) != 1:
        raise ValueError("cc89 benchmark requires one candidate")
    if any(
        amino_acid not in residue_constants.restype_order
        for target in request.target_sequences
        for amino_acid in target.sequence
    ):
        raise ValueError("target sequence contains a non-canonical residue")
    source = workspace.joinpath(*Path(request.normalized_pdb.path).parts)
    if _sha256(source) != request.normalized_pdb.sha256:
        raise ValueError("normalized PDB digest mismatch")
    if request.protein_context is not None:
        validate_context_source(request, source.read_bytes())
    fixed_coordinates = _read_fixed_coordinates(source, request.fixed_atoms)
    fixed_residue_names = _read_fixed_residue_names(source, request.fixed_atoms)
    sampling_requests = _chain_sampling_requests(request, fixed_coordinates)
    view = engine_context_view(request) if request.protein_context else None
    engine_to_source = dict(view.atom_to_source) if view else None
    source_to_engine = {original: engine for engine, original in view.atom_to_source} if view else None

    device = _resolve_device(torch, device_name)
    if mps_profile and device.type != "mps":
        raise ValueError("--mps-profile requires --device mps")
    telemetry = _AcceleratorTelemetry(torch, device)
    start = time.perf_counter()
    telemetry.start()
    seed = request.seeds[0]
    model_load_start = time.perf_counter()
    model = load_model(config_path, checkpoint_path, device=str(device))
    _synchronize(torch, device)
    model_load_seconds = time.perf_counter() - model_load_start
    _assert_model_device(model, device)
    if chain_phase_policy != "native" and model.config.model.struct_model.uvit.position_embedding_type != "rotary":
        raise ValueError("neutral chain phase is specific to the pinned cc89 rotary checkpoint")
    conditional = {
        "enabled": True,
        "discontiguous_motif_assignment": {
            "enabled": True,
            "strategy": "fixed",
            "fixed_motif_pos": [],
        },
        "num_recurrence_steps": 1,
        "crop_conditional_guidance": {
            "enabled": True,
            "start": 0.0,
            "end": 2.0,
            "freq": 1,
            "freq_start": 0.0,
            "freq_end": 0.0,
            "strategy": crop_strategy,
        },
        "reconstruction_guidance": {
            "enabled": False,
            "start": 0.0,
            "end": 2.0,
            "schedule": "custom",
            "max_scale": 10.0,
            "loss_weights": {"motif": 1.0},
        },
        "replacement_guidance": {"enabled": replacement_guidance, "start": 0.0, "end": 0.92},
    }
    callback_stats: dict[str, float | int] = {
        "callback_count": 0,
        "represented_fixed_atom_count": 0,
        "maximum_post_projection_error_angstrom": 0.0,
    }
    denoising_seconds = 0.0
    placements: list[str] = []
    sampler_atom_order_parts: list[AtomIdentity] = []
    candidate_identities: list[AtomIdentity] = []
    candidate_coordinates: list[np.ndarray] = []
    candidate_residue_names: list[str] = []
    fit_count = 0
    fit_source_only = 0
    fit_squared_displacement = 0.0
    fit_max_displacement = 0.0
    conditioning_contexts: list[SamplerConditioningContext] = []
    context_probes = []
    phase_control = _NeutralDenoiserChainPhase() if chain_phase_policy == "neutral-v1" else None
    position_evidence = None
    for invocation_index, sampling_request in enumerate(sampling_requests):
        invocation_seed = seed + invocation_index
        seed_everything(invocation_seed)
        torch.manual_seed(invocation_seed)
        if device.type == "cuda":
            torch.cuda.manual_seed_all(invocation_seed)
        elif device.type == "mps":
            torch.mps.manual_seed(invocation_seed)

        target_sequence = _target_sequence(sampling_request)
        motif_path = output_dir / f"motif-{invocation_index + 1}.pdb"
        _write_motif_input(source, motif_path, sampling_request, source_to_engine)
        seq_mask, residue_index, chain_index = model.make_seq_mask_for_sampling(
            prot_lens_per_chain=torch.tensor([[
                len(target.sequence) for target in sampling_request.target_sequences
            ]])
        )
        if position_feature_policy == "source-physical-v1":
            source_indices, source_chains = source_context_position_features(request)
            if view is None or len(sampling_requests) != 1 or residue_index.shape != (1, len(source_indices)):
                raise ValueError("source position features do not match the explicit context token axis")
            residue_index = torch.as_tensor([source_indices], device=residue_index.device, dtype=residue_index.dtype)
            chain_index = torch.as_tensor([source_chains], device=chain_index.device, dtype=chain_index.dtype)
            digest = hashlib.sha256(np.asarray((source_indices, source_chains), dtype="<i8").tobytes()).hexdigest()
            position_evidence = {"policy": position_feature_policy, "feature_sha256": digest,
                "source_chains": tuple(dict.fromkeys(span.chain for span in request.protein_context.spans)),
                "engine_entities": len(sampling_request.target_sequences), "residue_index": source_indices,
                "physical_chain_index": source_chains}
        seq_mask = seq_mask.to(device=device)
        residue_index = residue_index.to(device=device)
        chain_index = chain_index.to(device=device)
        gt_aatype = torch.tensor(
            [[
                residue_constants.restype_order[amino_acid]
                for amino_acid in target_sequence
            ]],
            dtype=torch.long,
            device=device,
        )
        for name, value in (
            ("seq_mask", seq_mask),
            ("residue_index", residue_index),
            ("chain_index", chain_index),
            ("gt_aatype", gt_aatype),
        ):
            _assert_tensor_device(name, value, device)
        placement, fixed_positions = _motif_placement(sampling_request)
        placements.append(placement)
        conditional["discontiguous_motif_assignment"]["fixed_motif_pos"] = (
            fixed_positions
        )
        invocation_callback_stats: dict[str, float | int] = {
            "callback_count": 0,
            "represented_fixed_atom_count": 0,
            "maximum_post_projection_error_angstrom": 0.0,
        }
        sample_options: dict[str, Any] = {}
        if device.type == "mps":
            sample_options["record_trajectory"] = False
        chain_fixed_coordinates = {
            source_to_engine[atom] if source_to_engine else atom: coordinate
            for atom, coordinate in fixed_coordinates.items()
            if (source_to_engine.get(atom) if source_to_engine else atom) in set(sampling_request.fixed_atoms)
        }
        chain_fixed_residue_names = {
            source_to_engine[atom] if source_to_engine else atom: name
            for atom, name in fixed_residue_names.items()
            if (source_to_engine.get(atom) if source_to_engine else atom) in set(sampling_request.fixed_atoms)
        }
        primary_chain = request.gaps[0].chain if view else sampling_request.gaps[0].chain
        partner_chains = tuple(
            target.chain
            for target in (request.target_sequences if view else sampling_request.target_sequences)
            if target.chain != primary_chain
        )
        partner_atoms = tuple(
            engine_to_source[atom] if engine_to_source else atom for atom in sampling_request.fixed_atoms
            if (engine_to_source[atom].chain if engine_to_source else atom.chain) in partner_chains
        )
        if partner_atoms:
            conditioning_contexts.append(SamplerConditioningContext(
                target_chain=primary_chain,
                partner_chains=partner_chains,
                partner_atoms=partner_atoms,
            ))
        if per_step_reinjection:
            callback, invocation_callback_stats = _make_per_step_reinjector(
                sampling_request,
                chain_fixed_coordinates,
            )
            sample_options["step_callback"] = callback
        _synchronize(torch, device)
        denoising_start = time.perf_counter()
        profile_context = torch.mps.profiler.profile() if mps_profile else nullcontext()
        probe = _DenoiserContextProbe(sampling_request) if context_probe else None
        with profile_context, _probe_hook(model.struct_model, phase_control), _probe_hook(model.struct_model, probe):
            sampled = model.sample(
                seq_mask=seq_mask,
                residue_index=residue_index,
                chain_index=chain_index,
                gt_aatype=gt_aatype,
                num_steps=steps,
                step_scale=step_scale,
                s_churn=s_churn,
                motif_file_path=str(motif_path),
                motif_placements_full=[placement],
                dummy_fill_mode=model.config.data.dummy_fill_mode,
                partial_diffusion={
                    "enabled": False,
                    "pdb_file_path": None,
                    "num_steps": 100,
                },
                conditional_cfg=conditional,
                sidechain_mode=False,
                skip_mpnn_proportion=1.0,
                use_fullmpnn=False,
                use_fullmpnn_for_final=False,
                jump_steps=False,
                uniform_steps=True,
                **sample_options,
            )
        if probe:
            if probe.result is None:
                raise RuntimeError("causal denoiser probe did not execute")
            context_probes.append(probe.result)
        _assert_tensor_device("sampled coordinates", sampled["x"], device)
        _synchronize(torch, device)
        denoising_seconds += time.perf_counter() - denoising_start
        observed_callbacks = int(invocation_callback_stats["callback_count"])
        if per_step_reinjection and observed_callbacks != steps:
            raise RuntimeError(
                "per-step callback count mismatch: "
                f"expected {steps}, observed {observed_callbacks}"
            )
        callback_stats["callback_count"] = (
            int(callback_stats["callback_count"]) + observed_callbacks
        )
        callback_stats["represented_fixed_atom_count"] = (
            int(callback_stats["represented_fixed_atom_count"])
            + int(invocation_callback_stats["represented_fixed_atom_count"])
        )
        callback_stats["maximum_post_projection_error_angstrom"] = max(
            float(callback_stats["maximum_post_projection_error_angstrom"]),
            float(invocation_callback_stats["maximum_post_projection_error_angstrom"]),
        )

        raw = _coordinates_to_numpy(torch, sampled["x"][0])
        identities, coordinates, residue_names = _model_atoms(sampling_request, raw)
        requested_atoms = set(sampling_request.fixed_atoms) | set(
            sampling_request.generated_atoms
        )
        sampler_atom_order = tuple(
            identity for identity in identities if identity in requested_atoms
        ) + tuple(
            atom
            for context in sampling_request.heterogen_contexts
            for atom in context.atoms
        )
        sampler_atom_order_parts.extend(engine_to_source[atom] if engine_to_source else atom for atom in sampler_atom_order)
        fit = _native_conditioning_fit(
            identities,
            coordinates,
            chain_fixed_coordinates,
            joint_frame=view is not None,
        )
        represented_count = int(fit["represented_fixed_atom_count"])
        fit_count += represented_count
        fit_source_only += int(fit["source_only_fixed_atom_count"])
        fit_squared_displacement += float(fit["rmsd_angstrom"]) ** 2 * represented_count
        fit_max_displacement = max(
            fit_max_displacement,
            float(fit["max_displacement_angstrom"]),
        )
        identities, coordinates, residue_names = _synchronize_and_restore_fixed_atoms(
            identities,
            coordinates,
            residue_names,
            chain_fixed_coordinates,
            chain_fixed_residue_names,
            sampling_request,
            joint_frame=view is not None,
        )
        for identity, coordinate, residue_name in zip(
            identities,
            coordinates,
            residue_names,
        ):
            if engine_to_source:
                identity = engine_to_source[identity]
            if (
                identity in (set(request.fixed_atoms) | set(request.generated_atoms) if view else requested_atoms)
                and (view is not None or identity.chain == primary_chain)
                and all(
                    identity not in context.atoms
                    for context in sampling_request.heterogen_contexts
                )
            ):
                candidate_identities.append(identity)
                candidate_coordinates.append(coordinate)
                candidate_residue_names.append(residue_name)

    sampler_atom_order = tuple(dict.fromkeys(sampler_atom_order_parts))
    sampler_atom_set = set(sampler_atom_order)
    represented_fixed_atoms = tuple(
        atom for atom in request.fixed_atoms if atom in sampler_atom_set
    )
    native_conditioning_fit = {
        "represented_fixed_atom_count": fit_count,
        "source_only_fixed_atom_count": fit_source_only,
        "rmsd_angstrom": float(np.sqrt(fit_squared_displacement / fit_count)),
        "max_displacement_angstrom": fit_max_displacement,
        "independent_chain_invocations": len(sampling_requests),
    }
    identities = tuple(candidate_identities)
    coordinates = np.asarray(candidate_coordinates, dtype=np.float64)
    residue_names = tuple(candidate_residue_names)
    candidate_path = output_dir / "candidate.pdb"
    _write_candidate(
        candidate_path,
        source,
        identities,
        coordinates,
        residue_names,
        request,
    )
    elapsed = time.perf_counter() - start
    memory = telemetry.stop()
    resource_metrics = RunnerResourceMetrics(
        wall_time_seconds=elapsed,
        model_load_seconds=model_load_seconds,
        peak_ram_bytes=memory["peak_rss_bytes"],
        peak_vram_bytes=memory["peak_accelerator_allocated_bytes"],
    )
    production_profile = device.type == "mps" and not per_step_reinjection
    callback_count = int(callback_stats["callback_count"])
    if phase_control is not None and phase_control.calls != steps * len(sampling_requests):
        raise RuntimeError("cc89 chain-phase control did not reach every denoising update")
    projection_error = float(
        callback_stats["maximum_post_projection_error_angstrom"]
    )
    trace_artifact = write_sampler_trace(
        workspace,
        output_dir / "sampler-trace.json",
        build_sampler_trace(
            profile=(
                "protpardelle-1c-cuda" if cuda_production else
                "protpardelle-1c-mps"
                if production_profile
                else "protpardelle-1c-research"
            ),
            engine_repository="https://github.com/ProteinDesignLab/protpardelle-1c",
            engine_revision=_REVISION,
            patch_identity=(
                f"sha256:{_APPLE_PATCH_SHA256}" if phase_control is None else
                f"adapter-sha256:{_sha256(Path(__file__))};cc89-chain-phase=neutral-v1"
                + (";cc89-position-features=source-physical-v1" if position_evidence else "")
            ),
            atom_order=sampler_atom_order,
            fixed_atoms=request.fixed_atoms,
            represented_fixed_atoms=represented_fixed_atoms,
            device=str(device),
            fallback_disabled=(
                device.type != "mps"
                or os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "0"
            ),
            denoising_update_count=steps,
            projection_errors_angstrom=(projection_error,) * callback_count,
            final_fixed_coordinate_restoration=True,
            resource_metrics=resource_metrics,
            sampler_evidence_complete=True,
            conditioning_contexts=tuple(conditioning_contexts),
            conditioned_heterogen_atoms=tuple(
                dict.fromkeys(
                    atom
                    for context in request.heterogen_contexts
                    for atom in context.atoms
                )
            ),
            protein_context_evidence=(
                context_evidence(request, sampler_atom_order) if request.protein_context else None
            ),
        ),
    )

    candidate = RunnerCandidate(
        candidate_id=f"protpardelle-1c-cc89-seed-{seed}",
        seed=seed,
        coordinate_artifact=_artifact(workspace, candidate_path),
        sampler_trace_artifact=trace_artifact,
        generated_atoms=request.generated_atoms,
        generated_residues=tuple(
            residue for gap in request.gaps for residue in gap.generated_residues
        ),
        raw_backend_score=None,
        score_provenance="protpardelle-1c-cc89:unranked",
    )
    backend_label = (
        "protpardelle-1c-cc89-local-interchain-conditioning"
        + ("+per-step-reinjection" if per_step_reinjection else "")
        if conditioning_contexts
        else (
            "protpardelle-1c-cc89-independent-chain+per-step-reinjection"
            if per_step_reinjection
            else "protpardelle-1c-cc89-independent-chain"
        )
    )
    if request.heterogen_contexts:
        backend_label += "+heterogen-geometric-context"
    if phase_control is not None:
        backend_label += "+neutral-denoiser-chain-phase-v1"
    if position_evidence is not None:
        backend_label += "+source-physical-positions-v1"
    result = RunnerResult(
        schema_version=DIFFUSION_SCHEMA_VERSION,
        status=DiffusionStatus.SUCCESS,
        candidates=(candidate,),
        runner_diagnostics=RunnerDiagnostics(exit_code=0, timed_out=False),
        backend_provenance=BackendProvenance(
            backend=backend_label,
            runner_protocol_version=DIFFUSION_RUNNER_PROTOCOL_VERSION,
            engine_repository="https://github.com/ProteinDesignLab/protpardelle-1c",
            engine_revision=_REVISION,
            checkpoint_sha256=_CHECKPOINT_SHA256,
            device=str(device),
            precision="float32",
            framework="torch",
            framework_version=torch.__version__,
            cuda_version=str(torch.version.cuda or "") if device.type == "cuda" else "",
            deterministic_algorithms=False,
            deterministic_flags=(
                f"seed={seed}",
                "fixed-sequence",
                "mpnn-disabled",
                f"independent-chain-invocations={len(sampling_requests)}",
                f"local-interchain-contexts={len(conditioning_contexts)}",
                "interchain-context-cutoff-angstrom="
                f"{_INTERCHAIN_CONTEXT_CUTOFF_ANGSTROM}",
                f"conditioned-heterogens={len(request.heterogen_contexts)}",
                "heterogen-repulsion-cutoff-angstrom="
                f"{_HETEROGEN_REPULSION_CUTOFF_ANGSTROM}",
                f"per-step-reinjection={per_step_reinjection}",
                f"mps-fallback={os.environ.get('PYTORCH_ENABLE_MPS_FALLBACK', 'unset')}",
                *(("cc89-denoiser-chain-phase=neutral-v1",) if phase_control is not None else ()),
                *(("cc89-position-features=source-physical-v1", f"cc89-position-features-sha256={position_evidence['feature_sha256']}") if position_evidence else ()),
            ),
        ),
        resource_metrics=resource_metrics,
    )
    validation = validate_runner_result(request, result, workspace=workspace)[0]
    quality_summary: dict[str, float | None] = {
        "gap_backbone_rmsd_angstrom": None,
        "gap_all_heavy_rmsd_angstrom": None,
        "fixed_heavy_rmsd_angstrom": None,
    }
    reference_path = workspace / "reference.pdb"
    if reference_path.is_file():
        reference = load_pdb_coordinates(
            workspace,
            ArtifactReference("reference.pdb", _sha256(reference_path)),
        )
        candidate_coordinates = load_pdb_coordinates(
            workspace,
            candidate.coordinate_artifact,
        )
        quality = candidate_quality(
            candidate.candidate_id,
            reference,
            candidate_coordinates,
            generated_residues={
                residue for gap in request.gaps for residue in gap.generated_residues
            },
            fixed_atoms=set(request.fixed_atoms),
            anchor_residues={
                residue
                for gap in request.gaps
                for residue in (gap.left_anchor, gap.right_anchor)
                if residue is not None
            },
            closure_passed=(
                "junction-peptide-connectivity"
                not in validation.summary.hard_gate_failures
            ),
            validation_passed=validation.summary.passed,
        )
        quality_summary = {
            "gap_backbone_rmsd_angstrom": quality.gap_backbone_rmsd_angstrom,
            "gap_all_heavy_rmsd_angstrom": quality.gap_all_heavy_rmsd_angstrom,
            "fixed_heavy_rmsd_angstrom": quality.fixed_heavy_rmsd_angstrom,
        }
    summary = {
        "candidate_sha256": candidate.coordinate_artifact.sha256,
        "config_sha256": _CONFIG_SHA256,
        "checkpoint_sha256": _CHECKPOINT_SHA256,
        "diffusion_steps": steps,
        "total_denoising_updates": steps * len(sampling_requests),
        "independent_chain_invocations": len(sampling_requests),
        "local_interchain_conditioning": [
            {
                "target_chain": context.target_chain,
                "partner_chains": list(context.partner_chains),
                "partner_atom_count": len(context.partner_atoms),
            }
            for context in conditioning_contexts
        ],
        "heterogen_conditioning": [
            {
                "residue": asdict(context.residue),
                "residue_name": context.residue_name,
                "atom_count": len(context.atoms),
                "authoritative_graph_sha256": context.authoritative_graph_sha256,
                "conditioning_mode": context.conditioning_mode,
            }
            for context in request.heterogen_contexts
        ],
        "step_scale": step_scale,
        "crop_strategy": crop_strategy,
        "replacement_guidance": replacement_guidance,
        **({"cc89_position_features": position_evidence} if position_evidence else {}),
        **({"cc89_chain_phase": {
            "policy": chain_phase_policy,
            "denoiser_calls": phase_control.calls,
            "original_chain_labels": phase_control.chain_labels,
            "sampler_chain_and_residue_indices_preserved": True,
        }} if phase_control is not None else {}),
        "s_churn": s_churn,
        "motif_placements": placements,
        **({"denoiser_context_probes": context_probes} if context_probe else {}),
        "native_conditioning_fit": native_conditioning_fit,
        "per_step_reinjection": per_step_reinjection,
        "per_step_callback": callback_stats,
        "quality": quality_summary,
        "validation": asdict(validation.summary),
        "ranking_metrics": [asdict(metric) for metric in validation.ranking_metrics],
        "wall_time_seconds": elapsed,
        "peak_vram_bytes": result.resource_metrics.peak_vram_bytes,
        "device": str(device),
        "mps_profile_enabled": mps_profile,
        "mps_environment": {key: os.environ.get(key) for key in _MPS_ENVIRONMENT_KEYS},
        "resource_metrics": {
            "model_load_seconds": model_load_seconds,
            "denoising_seconds": denoising_seconds,
            **memory,
        },
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result, summary_path


def run(
    request_path: Path,
    output_dir: Path,
    config_path: Path,
    checkpoint_path: Path,
    *,
    steps: int,
    step_scale: float,
    s_churn: float,
    per_step_reinjection: bool = False,
    device: str = "cuda",
    mps_profile: bool = False,
    context_probe: bool = False,
) -> None:
    request_path = request_path.resolve()
    workspace = request_path.parent
    output_dir = output_dir.resolve()
    try:
        output_dir.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("cc89 benchmark output must be inside the request workspace") from exc
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        _run_staged(
            request_path,
            staging,
            config_path,
            checkpoint_path,
            steps=steps,
            step_scale=step_scale,
            s_churn=s_churn,
            per_step_reinjection=per_step_reinjection,
            device_name=device,
            mps_profile=mps_profile,
            context_probe=context_probe,
        )
        staging.rename(output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(output_dir / "summary.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--steps", default=500, type=int)
    parser.add_argument("--step-scale", default=1.2, type=float)
    parser.add_argument("--s-churn", default=200.0, type=float)
    parser.add_argument("--device", choices=("cpu", "cuda", "mps"), default="cuda")
    parser.add_argument("--mps-profile", action="store_true")
    parser.add_argument("--per-step-reinjection", action="store_true")
    parser.add_argument("--context-probe", action="store_true")
    args = parser.parse_args()
    run(
        args.request,
        args.output_dir,
        args.config,
        args.checkpoint,
        steps=args.steps,
        step_scale=args.step_scale,
        s_churn=args.s_churn,
        per_step_reinjection=args.per_step_reinjection,
        device=args.device,
        mps_profile=args.mps_profile,
        context_probe=args.context_probe,
    )


if __name__ == "__main__":
    main()
