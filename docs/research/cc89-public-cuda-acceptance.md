# Public corrected cc89 CUDA integration acceptance

The experimental `protpardelle-1c-cuda` profile is exposed through installed
runtime discovery, `model`, mosaic-first `homology`, the existing workflow
adapters, and the GUI. MODELLER remains the default; MPS behavior is unchanged.

## Public slice

- One CYS-free internal gap of 5–10 residues, at most 512 whole-source canonical
  protein residues; surrounding protein chains are retained.
- `--diffusion-context auto` selects the frozen source-only local policy. Explicit
  `none`/`full`, multiple/terminal gaps, and nonwater heterogens are rejected.
- Neutral denoiser chain phase and physical source sequence positions, 500 native
  updates, no per-step reinjection; generated-only OpenMM CUDA refinement runs in
  an isolated process. OXT remains explicitly preserved-only.
- Normal bounded runner execution, independent validation, `.dat` handoff,
  digest-bound atomic publication and verified resume are retained.

## Real public entry points

| Command | Source / mask | Seeds | Independently accepted |
|---|---|---|---:|
| homology | 9WW8, gap5 | 7 | 1/1 |
| homology | 8EK6, H-CDR1 gap5 | 7 | 1/1 |
| homology | 9Z0U, H-CDR3 gap10 | 7 | 1/1 |
| model | 9WW8, gap10 | 7, 19 | 2/2 |
| Total | Four public workflows | Five candidates | **5/5** |

The [machine-readable audit](cc89-public-cuda-acceptance-v3.json) reconstructs the
expected public requests and verifies exact request identity, bundle digests,
trace policy, generated-atom `.dat` records, geometry and byte-identical outside-gap
atom records. Every candidate has zero detectable D-Cα and zero fixed-heavy
displacement. Two-seed `model --diffusion-resume` independently revalidates and
reuses the bundle without sampling. These are integration checks on previously
studied sources, not a new independent scientific holdout. Reference RMSD is not
used for acceptance or selection.

## Deployment issues found and resolved

The installer must retain the path to a refinement venv's Python symlink:
resolving it selected the base environment and a different CUDA toolchain. The
regression test asserts that the venv interpreter path survives registration.
The refiner also isolates PATH/CUDA library discovery. Preflight compiles and
executes an actual CUDA force kernel, so a cached or import-only success cannot
hide an incompatible runtime.

The workspace filesystem rejects atomic no-replace directory publication. This
existing fail-closed boundary is preserved; acceptance outputs were published on
native `/tmp`. GUI Homology already publishes in private native temporary storage
and transports verified results back to the workspace. Development setup failures
did not publish a successful bundle and are not scientific cohort outcomes.

## Verification

The fast Python suite passed **1,175 tests, 7 skipped**, including the final
CYS-boundary and immutable-request replay regressions. GUI typecheck and **244 tests** pass. Ruff, generated CLI/GUI specs,
agent maps and diff checks pass.

The full-following mypy invocation reports **35 existing errors in 10 unrelated
files**, reproduced unchanged on clean baseline commit `5a402cc`. The explicit
14-file API/context target passes with `--follow-imports=silent`; no mypy ignores
or relaxed project configuration were added.
