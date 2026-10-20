# Baseline repair and plan synchronization — 2026-10-20

This repair follows corrected Apple acceptance commit `0e2a8c8`. It fixes the
reported nine Python baseline failures and naming-API GUI failure without adding
ML dependencies to core, skipping failing cases, or relaxing scientific gates.

## Causes and corrections

| Failure | Cause | Correction / regression evidence |
|---|---|---|
| Fixture completeness | The checksum manifest already included Apple provenance JSON, but the test expected only PDB/FASTA | Explicit metadata allowlist plus duplicate-entry check; source assets and checksums unchanged |
| Protenix pure helpers | Module-level Torch/reinjection imports required the optional ML environment during core tests | Defer imports until execution/callback use; fresh-process test forbids ML imports |
| Protenix preflight | A simulated Linux profile inherited the actual test host's cgroup RAM state | Explicit bounded/unbounded mocks plus missing, zero, negative and excessive-limit rejection tests |
| Six Amber19SB external cases | `pbc=no` is incompatible with GROMACS Verlet preprocessing | Explicit periodic box, valid preprocessing MDP, unchanged `-maxwarn 0`; six actual GROMACS 2026.0 passes |
| Naming output cleanup | On this Node v24.9.0 host, `rmSync(force)` left a dangling symlink | Inspect with `lstatSync`, remove the link itself with `unlinkSync`; regular/dangling, dry-run, child-error and malformed-report regressions; targets untouched and no artifact registered |
| Additional Vitest startup conflict | Loading the dev API plugin migrated/locked live workspace manifests during collection | Exclude the plugin only for Vite test mode; test development/production inclusion too; no user lock or workspace removed |

The first full rerun exposed one related historical-hash assertion after the
Protenix import change. The research inventory now distinguishes historical and
current helper hashes. Frozen protocols and their historical source hash remain
unchanged; tests verify both identities. No CUDA checkpoint run was repeated.

## Verification

- Python non-slow suite: **1212 passed, 2 skipped, 31 deselected** (160.92 s).
  The two existing skips are optional Biotite and Torch coverage unavailable in
  the core environment. Two SWIG import deprecation warnings remain.
- GUI: **251 passed**, with TypeScript typecheck and ESLint passing.
- Ruff, agent-document maps, synchronized release metadata and generated CLI/GUI
  spec checks passed.
- [Amber19SB external evidence](../provenance/amber19sb-gromacs.md#external-acceptance)
  is preprocessing only; no solvent/ion trajectories or broader chemistry claims.

## Plan synchronization

The [plan index](../plans/README.md) and canonical checklist separate delivered
software from bounded hardware evidence and wider scientific/production gates.
Historical plans are retained, with current status headers where needed. The
corrected Apple 8/8 research and 5/5 public results are not extended to a larger
operational cohort. Protenix full production-wrapper replay/final OCI smoke,
independent scientific cohorts, optional packaging migration and separate
chemistry/MD acceptance remain open.
