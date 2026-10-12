"""Private package custody and ordering-only controls for deployment evidence."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_export_manifest_is_portable_while_complete_raw_exports_stay_private(tmp_path, monkeypatch):
    exporter = _load("export_protenix_environment", monkeypatch)
    core = tmp_path / "private-core/python"
    backend = tmp_path / "private-backend/python"
    snapshot = {
        "python": "3.13.15", "platform": "linux", "prefix": "/private/core",
        "base_prefix": "/private/core", "packages": {"numpy": "2.4.6"},
    }

    def fake_output(command, **_kwargs):
        if "-c" in command:
            result = {**snapshot, "prefix": "/private/backend"} if command[0] == str(backend) else snapshot
            return json.dumps(result)
        if "freeze" in command:
            return b"package @ file:///private/wheelhouse/package.whl\n"
        return b"@EXPLICIT\nhttps://public.example/conda-package.conda\n"

    monkeypatch.setattr(exporter.subprocess, "check_output", fake_output)
    output = tmp_path / "exports"
    manifest = exporter.export_environment(core, backend, output, tmp_path / "micromamba")
    assert manifest["backend_inherits_core"] is True
    assert "/private" not in json.dumps(manifest)
    assert b"/private/wheelhouse" in (output / "backend-pip-freeze.txt").read_bytes()
    assert set(manifest["artifacts"]) == {
        "core-packages.json", "backend-packages.json", "core-pip-freeze.txt",
        "backend-pip-freeze.txt", "core-conda-explicit.txt",
    }
    with pytest.raises(FileExistsError):
        exporter.export_environment(core, backend, output, tmp_path / "micromamba")


def test_atom_order_control_preserves_atom_records_and_coordinates(monkeypatch):
    comparison = _load("compare_protenix_refinement_revisions", monkeypatch)
    first = "ATOM      1  N   ALA A   1      11.000  12.000  13.000  1.00  0.00           N  \n"
    second = "ATOM      2  CA  ALA A   1      14.000  15.000  16.000  1.00  0.00           C  \n"
    reordered = comparison.restore_atom_order(second + first + "TER\nEND\n", first + second)
    assert reordered == first + second + "TER\nEND\n"
    with pytest.raises(ValueError, match="identical unique atom identities"):
        comparison.restore_atom_order(first + first, first + second)
    with pytest.raises(ValueError, match="single plain protein"):
        comparison.restore_atom_order(first + "CONECT    1    2\n", first)
