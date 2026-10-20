"""Tests for installed diffusion backend discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from dvbfixer.model.diffusion.runtime import (
    DiffusionRuntimeError,
    resolve_diffusion_runtime,
)


def test_apple_auto_selects_installed_protpardelle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("dvbfixer.model.diffusion.runtime.sys.platform", "darwin")
    monkeypatch.setattr("dvbfixer.model.diffusion.runtime.platform.machine", lambda: "arm64")
    monkeypatch.setattr(
        "dvbfixer.model.diffusion.runtime.shutil.which",
        lambda name: f"/installed/{name}" if "protpardelle" in name else None,
    )

    runtime = resolve_diffusion_runtime()

    assert runtime.model == "protpardelle"
    assert runtime.profile == "protpardelle-1c-mps-local-v1"
    assert runtime.runner.endswith("dvbfixer-diffusion-protpardelle-1c-mps-local-v1")


def test_frozen_legacy_apple_profile_can_select_its_original_launcher(monkeypatch):
    monkeypatch.setattr("dvbfixer.model.diffusion.runtime.sys.platform", "darwin")
    monkeypatch.setattr("dvbfixer.model.diffusion.runtime.platform.machine", lambda: "arm64")
    monkeypatch.setattr("dvbfixer.model.diffusion.runtime._installed_runner", lambda name: "/installed/" + name)
    runtime = resolve_diffusion_runtime("protpardelle", profile="protpardelle-1c-mps")
    assert runtime.profile == "protpardelle-1c-mps"
    assert runtime.runner.endswith("protpardelle-1c-mps")


def test_explicit_incompatible_model_reports_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("dvbfixer.model.diffusion.runtime.sys.platform", "darwin")
    monkeypatch.setattr("dvbfixer.model.diffusion.runtime.platform.machine", lambda: "arm64")

    with pytest.raises(DiffusionRuntimeError, match="no maintained profile supports darwin/arm64"):
        resolve_diffusion_runtime("protenix")


def test_missing_backend_names_expected_launcher(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("dvbfixer.model.diffusion.runtime.sys.platform", "linux")
    monkeypatch.setattr("dvbfixer.model.diffusion.runtime.platform.machine", lambda: "x86_64")
    monkeypatch.setattr("dvbfixer.model.diffusion.runtime.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "dvbfixer.model.diffusion.runtime.diffusion_runner_directory", lambda: tmp_path,
    )

    with pytest.raises(
        DiffusionRuntimeError,
        match="dvbfixer-diffusion-protenix-v1-cuda",
    ):
        resolve_diffusion_runtime()
