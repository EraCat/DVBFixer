#!/usr/bin/env python
"""Exercise the NumPy/SciPy native BLAS/LAPACK stack before running CLI tests."""

from __future__ import annotations

import numpy as np
from scipy.linalg import solve


def main() -> int:
    matrix = np.array([[3.0, 1.0], [1.0, 2.0]])
    rhs = np.array([9.0, 8.0])
    expected = np.array([2.0, 3.0])
    for label, result in (("NumPy", np.linalg.solve(matrix, rhs)), ("SciPy", solve(matrix, rhs))):
        if not np.allclose(result, expected) or not np.allclose(matrix @ result, rhs):
            raise RuntimeError(f"{label} BLAS/LAPACK solve failed")
    print(f"NumPy {np.__version__} / SciPy native linear algebra smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
