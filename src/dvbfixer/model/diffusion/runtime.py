"""Discover installed diffusion backends without exposing deployment paths."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


class DiffusionRuntimeError(RuntimeError):
    """Raised when no installed diffusion backend matches the request."""


@dataclass(frozen=True, slots=True)
class DiffusionRuntime:
    """One installed model runner selected for the current machine."""

    model: str
    profile: str
    runner: str


@dataclass(frozen=True, slots=True)
class _RuntimeSpec:
    model: str
    profile: str
    executable: str
    platforms: tuple[tuple[str, str], ...]


_RUNTIME_SPECS = (
    _RuntimeSpec(
        model="protpardelle",
        profile="protpardelle-1c-cuda",
        executable="dvbfixer-diffusion-protpardelle-1c-cuda",
        platforms=(("linux", "x86_64"), ("linux", "amd64")),
    ),
    _RuntimeSpec(
        model="protpardelle",
        profile="protpardelle-1c-mps",
        executable="dvbfixer-diffusion-protpardelle-1c-mps",
        platforms=(("darwin", "arm64"),),
    ),
    _RuntimeSpec(
        model="protenix",
        profile="protenix-v1-cuda",
        executable="dvbfixer-diffusion-protenix-v1-cuda",
        platforms=(("linux", "x86_64"), ("linux", "amd64")),
    ),
)


def diffusion_runner_directory() -> Path:
    """Return the per-user directory populated by backend installers."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "dvbfixer" / "runners"
    data_home = os.environ.get("XDG_DATA_HOME")
    root = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return root / "dvbfixer" / "runners"


def _installed_runner(executable: str) -> str | None:
    if runner := shutil.which(executable):
        return runner
    candidate = diffusion_runner_directory() / executable
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def resolve_diffusion_runtime(model: str | None = None) -> DiffusionRuntime:
    """Select an installed launcher by optional model and host platform."""
    machine = platform.machine().lower()
    compatible = [
        spec
        for spec in _RUNTIME_SPECS
        if (sys.platform, machine) in spec.platforms
        and (model is None or spec.model == model)
    ]
    installed = [
        (spec, runner)
        for spec in compatible
        if (runner := _installed_runner(spec.executable)) is not None
    ]
    if len(installed) == 1:
        spec, runner = installed[0]
        return DiffusionRuntime(spec.model, spec.profile, runner)
    if len(installed) > 1:
        models = ", ".join(sorted({spec.model for spec, _runner in installed}))
        raise DiffusionRuntimeError(
            f"multiple compatible diffusion models are installed ({models}); "
            "select one with --diffusion-model"
        )

    requested = f" model {model!r}" if model is not None else ""
    expected = ", ".join(spec.executable for spec in compatible)
    if expected:
        detail = f"expected an installed launcher in PATH: {expected}"
    else:
        detail = f"no maintained profile supports {sys.platform}/{machine}"
    raise DiffusionRuntimeError(
        f"no compatible diffusion backend{requested} is installed; {detail}"
    )
