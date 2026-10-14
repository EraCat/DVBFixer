"""Torch-native frame synchronization for the patched Protenix sampler."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import torch

from dvbfixer.model.diffusion.contract import AtomIdentity


class FixedAtomReinjector:
    """Align each sampled frame and restore observed atoms exactly."""

    def __init__(
        self,
        atom_identities: tuple[AtomIdentity, ...],
        fixed_coordinates: Mapping[AtomIdentity, np.ndarray],
        anchor_weights: Mapping[AtomIdentity, float] | None = None,
        alignment_atoms: tuple[AtomIdentity, ...] | None = None,
    ) -> None:
        if len(set(atom_identities)) != len(atom_identities):
            raise ValueError("atom identities must be unique")
        if len(fixed_coordinates) < 3:
            raise ValueError("at least three fixed anchors are required")
        index_by_identity = {
            identity: index for index, identity in enumerate(atom_identities)
        }
        missing = set(fixed_coordinates) - set(index_by_identity)
        if missing:
            raise ValueError("fixed coordinate identity is absent from sampled atoms")
        if anchor_weights is not None and set(anchor_weights) != set(fixed_coordinates):
            raise ValueError("anchor weights must cover exactly the fixed identities")

        selected_alignment = set(fixed_coordinates) if alignment_atoms is None else set(alignment_atoms)
        if not selected_alignment <= set(fixed_coordinates) or len(selected_alignment) < 3:
            raise ValueError("alignment atoms must contain at least three selected fixed atoms")
        ordered = tuple(sorted(selected_alignment))
        coordinates = np.asarray(
            [fixed_coordinates[identity] for identity in ordered], dtype=np.float64
        )
        if coordinates.shape != (len(ordered), 3) or not np.isfinite(coordinates).all():
            raise ValueError("fixed coordinates must be finite three-vectors")
        weights = np.asarray(
            [
                1.0 if anchor_weights is None else anchor_weights[identity]
                for identity in ordered
            ],
            dtype=np.float64,
        )
        if not np.isfinite(weights).all() or np.any(weights <= 0.0):
            raise ValueError("anchor weights must be finite and positive")

        self._atom_count = len(atom_identities)
        self._fixed_indices = tuple(index_by_identity[identity] for identity in ordered)
        self._fixed_coordinates = coordinates
        self._weights = weights
        self._overwrite_indices = tuple(index_by_identity[identity] for identity in sorted(fixed_coordinates))
        self._overwrite_coordinates = np.asarray([fixed_coordinates[identity] for identity in sorted(fixed_coordinates)])

    def __call__(
        self, coordinates: torch.Tensor, step_index: int, step_count: int
    ) -> torch.Tensor:
        if step_count <= 0 or not 0 <= step_index < step_count:
            raise ValueError("invalid denoising step")
        if coordinates.ndim < 2 or coordinates.shape[-2:] != (self._atom_count, 3):
            raise ValueError("coordinate tensor has unexpected atom axis")
        if not coordinates.is_floating_point():
            raise TypeError("coordinate tensor must be floating point")

        device = coordinates.device
        dtype = coordinates.dtype
        indices = torch.as_tensor(self._fixed_indices, device=device)
        target = torch.as_tensor(self._fixed_coordinates, device=device, dtype=dtype)
        weights = torch.as_tensor(self._weights, device=device, dtype=dtype)
        weight_sum = weights.sum()

        mobile = coordinates.index_select(-2, indices)
        mobile_center = (mobile * weights[:, None]).sum(dim=-2) / weight_sum
        target_center = (target * weights[:, None]).sum(dim=-2) / weight_sum
        mobile_centered = mobile - mobile_center[..., None, :]
        target_centered = target - target_center
        covariance = torch.einsum(
            "...ki,k,kj->...ij", mobile_centered, weights, target_centered
        )
        left, _singular_values, right_transpose = torch.linalg.svd(covariance)
        determinant = torch.linalg.det(
            right_transpose.transpose(-2, -1) @ left.transpose(-2, -1)
        )
        correction = torch.eye(3, device=device, dtype=dtype).expand(
            *determinant.shape, 3, 3
        ).clone()
        correction[..., 2, 2] = torch.where(
            determinant > 0.0,
            torch.ones_like(determinant),
            -torch.ones_like(determinant),
        )
        rotation = (
            right_transpose.transpose(-2, -1)
            @ correction
            @ left.transpose(-2, -1)
        )
        translation = target_center - torch.einsum(
            "...i,...ji->...j", mobile_center, rotation
        )
        synchronized = torch.einsum(
            "...ni,...ji->...nj", coordinates, rotation
        ) + translation[..., None, :]
        overwrite = torch.as_tensor(self._overwrite_indices, device=device)
        overwrite_target = torch.as_tensor(self._overwrite_coordinates, device=device, dtype=dtype)
        synchronized[..., overwrite, :] = overwrite_target
        return synchronized
