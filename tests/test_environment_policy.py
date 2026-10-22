"""Dependency-policy and native-library checks for the scientific environment."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_conda_blas_and_lapack_select_one_backend() -> None:
    dependencies = {
        line.split("#", 1)[0].strip().removeprefix("- ").strip()
        for line in (ROOT / "environment.yml").read_text().splitlines()
        if line.startswith("  - ")
    }
    assert {"libblas=*=*openblas", "libcblas=*=*openblas", "liblapack=*=*openblas"} <= dependencies
    assert "python >=3.11,<3.14" in dependencies
    assert "numpy <2.5" in dependencies


def test_numpy_scipy_native_linear_algebra_smoke() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts/check_scientific_linalg.py")], check=True, timeout=30)
