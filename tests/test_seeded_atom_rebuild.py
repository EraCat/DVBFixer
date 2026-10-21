"""Regression tests for the seeded/retried `PDBFixer.addMissingAtoms()`
rebuild (`dvbfixer.ffutils.geometry.rebuild_missing_atoms_with_retry`).

Root cause (2026-07): `PDBFixer.addMissingAtoms(seed=None)` rebuilds a
missing sidechain via template-overlay + a short local minimization; if
the result clashes with a neighbor (< 0.13 nm, PDBFixer's own
`_findNearestDistance` cutoff), it falls back to UNSEEDED Langevin
dynamics (300 K, up to 2000 steps) to kick the new atoms apart. On a
real structure with several truncated LYS sidechains (`tests/fixtures/8cz8/
8cz8_t_u.pdb`, chain E — real crystallographic disorder, confirmed via
atom-count scan: 11 of 19 LYS residues in that chain carry only
`N/CA/C/O/CB`), this produced a genuinely different rebuilt
conformation from run to run of the exact same input, sometimes
surviving as D-Cα through the rest of the pipeline.

A second, more severe bug surfaced while verifying the fix: in
`prepare.pipeline.run_pdbfixer`, `PDBFixer.removeHeterogens()` and
`PDBFixer.replaceNonstandardResidues()` each rebuild an entirely new
Topology internally (`Modeller(...).delete(...)`), which silently
invalidates the *already-computed* `fixer.missingAtoms` dict (keyed by
Residue object identity against the topology that existed at
`findMissingAtoms()` time). The old call order — `findMissingAtoms()`
before `removeHeterogens()`/`replaceNonstandardResidues()` — meant
`addMissingAtoms()` silently added ZERO heavy atoms for every
genuinely-missing sidechain whenever heterogens were stripped (the
default), even though PDBFixer's own verbose log correctly reported
them as missing beforehand. Fixed by reordering to match PDBFixer's own
canonical usage (find/replace-nonstandard -> removeHeterogens ->
findMissingAtoms -> addMissingAtoms).
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("openmm", reason="prepare needs OpenMM")
pytest.importorskip("pdbfixer", reason="prepare needs PDBFixer")

# Chain E residues confirmed truncated to N/CA/C/O/CB only in the raw
# fixture (real crystallographic disorder) — CG/CD/CE/NZ are genuinely
# missing and must be rebuilt by PDBFixer's addMissingAtoms.
_TRUNCATED_LYS_RESIDS = [
    "299", "307", "320", "378", "386", "403", "428", "435", "503", "517", "549",
]
_LYS_SIDECHAIN_HEAVY = ("CG", "CD", "CE", "NZ")


def _extract_lys_sidechain_coords(pdb_text: str, chain: str = "E") -> dict:
    """Map resid -> {atom_name: (x, y, z)} for LYS sidechain heavy atoms."""
    out: dict = {}
    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        if line[21] != chain or line[17:20].strip() != "LYS":
            continue
        resid = line[22:26].strip()
        if resid not in _TRUNCATED_LYS_RESIDS:
            continue
        name = line[12:16].strip()
        if name not in _LYS_SIDECHAIN_HEAVY:
            continue
        xyz = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        out.setdefault(resid, {})[name] = xyz
    return out


@pytest.mark.slow
def test_prepare_rebuilds_truncated_lys_deterministically(
    eightcz8_dir: Path, tmp_workdir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every truncated LYS sidechain must be (a) fully rebuilt and (b)
    bit-identical across independent `prepare` runs on the same input.

    Before the fix: `removeHeterogens()`/`replaceNonstandardResidues()`
    invalidated `fixer.missingAtoms`'s identity keys, so these sidechains
    were never rebuilt at all (stayed backbone+CB). After fixing the
    ordering bug alone (without the seed), the rebuild would happen but
    the unseeded clash-escape MD could still make it non-deterministic.
    This test only passes once both are fixed.
    """
    from openmm import Platform
    from pdbfixer import PDBFixer

    import dvbfixer.prepare.pipeline as pipeline

    # Exact equality tests the seeded algorithm on a fixed numerical backend.
    # An automatically selected single-precision OpenCL device can differ at
    # PDB rounding boundaries even with identical seeds. Do not change the
    # production platform or loosen the coordinate assertion to hide that.
    class ReferencePDBFixer(PDBFixer):
        def __init__(self, *args, **kwargs):
            kwargs["platform"] = Platform.getPlatformByName("Reference")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(pipeline, "PDBFixer", ReferencePDBFixer)

    src = eightcz8_dir / "8cz8_t_u.pdb"
    assert src.is_file(), f"tracked fixture missing: {src}"

    runs = []
    for i in range(2):
        out = tmp_workdir / f"prep_{i}.pdb"
        pipeline.main([str(src), "-o", str(out), "--strip-heterogens"])
        assert out.exists()
        runs.append(_extract_lys_sidechain_coords(out.read_text()))

    for resid in _TRUNCATED_LYS_RESIDS:
        for run_idx, run in enumerate(runs):
            present = run.get(resid, {})
            missing = [n for n in _LYS_SIDECHAIN_HEAVY if n not in present]
            assert not missing, (
                f"run {run_idx}: LYS{resid} sidechain not fully rebuilt, "
                f"missing {missing}"
            )

    for resid in _TRUNCATED_LYS_RESIDS:
        for name in _LYS_SIDECHAIN_HEAVY:
            coords = {run[resid][name] for run in runs}
            assert len(coords) == 1, (
                f"LYS{resid}/{name} rebuilt to different coordinates across "
                f"repeated runs of the same input: {coords}"
            )


@pytest.mark.slow
def test_addmissingatoms_rebuild_no_clash_no_d_chirality(
    eightcz8_dir: Path,
) -> None:
    """The rebuilt sidechains must be clash-free and L-chiral immediately
    after the seeded `rebuild_missing_atoms_with_retry` call — i.e. what
    this fix actually guarantees. Checked right after the rebuild, BEFORE
    `Modeller.addHydrogens()` runs (`run_pdbfixer` does the H-addition
    internally before returning, so this test reproduces its own
    find/replace/remove/find-atoms call sequence directly rather than
    going through the public `run_pdbfixer` — H placement can introduce
    its own close contacts, a `repair_misplaced_hydrogens`/minimize
    concern, not this fix's, and checking post-H-addition would test
    something beyond this fix's scope).
    """
    from pdbfixer import PDBFixer

    from dvbfixer.ffutils.geometry import (
        find_clashing_atoms,
        find_d_residues,
        rebuild_missing_atoms_with_retry,
    )

    src = eightcz8_dir / "8cz8_t_u.pdb"
    assert src.is_file(), f"tracked fixture missing: {src}"

    # Mirrors run_pdbfixer's own ordering (see the comment above
    # `fixer.findNonstandardResidues()` in prepare/pipeline.py): find/
    # replace-nonstandard -> removeHeterogens -> findMissingAtoms ->
    # rebuild, so missingAtoms' identity keys match the topology the
    # rebuild will actually operate on.
    fixer = PDBFixer(filename=str(src))
    fixer.findMissingResidues()
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    fixer.removeHeterogens(keepWater=False)
    fixer.findMissingAtoms()
    rebuild_missing_atoms_with_retry(fixer, verbose=False)

    d_offenders = {
        (c, r) for (c, r, _name, _t)
        in find_d_residues(fixer.topology, fixer.positions)
    }
    for resid in _TRUNCATED_LYS_RESIDS:
        assert ("E", resid) not in d_offenders, (
            f"E/LYS{resid} rebuilt with D-Cα chirality"
        )

    rebuilt_indices = [
        a.index for a in fixer.topology.atoms()
        if a.residue.chain.id == "E" and a.residue.name == "LYS"
        and a.residue.id in _TRUNCATED_LYS_RESIDS
        and a.name in _LYS_SIDECHAIN_HEAVY
    ]
    assert rebuilt_indices, "expected to find the rebuilt LYS sidechain atoms"
    clashing = find_clashing_atoms(fixer.topology, fixer.positions, rebuilt_indices)
    assert not clashing, (
        f"{len(clashing)} rebuilt LYS sidechain atom(s) still clash with a "
        f"neighbor right after the seeded addMissingAtoms rebuild"
    )
