# Corrected cc89 public Apple integration

The versioned experimental **`protpardelle-1c-mps-local-v1`** profile passes public
integration checks for **5/5 candidates across four model/Homology workflows**.
All five pass independent geometry/source-preservation gates with zero detectable
D-Cα, zero fixed-heavy displacement and byte-identical outside-gap atom records.
No reference RMSD was read or used for acceptance or seed selection.

This is integration on the three previously studied portable sources, not a new
holdout or wider operational acceptance. MODELLER remains default. The historical
`protpardelle-1c-mps` profile, launcher and native-position semantics remain intact.

## Public scope and runtime

- One CYS-free internal 5–10-residue gap; at most 512 whole-source canonical protein
  residues. Retain surrounding protein chains and preserve OXT outside atom37.
- `auto` selects the frozen source-only local context. Explicit `none`/`full`,
  nonwater heterogens and multiple/terminal gaps are rejected before inference.
- Native arm64 Python 3.12 / Torch 2.6.0 MPS, pinned cc89 checkpoint/config and
  upstream revision plus only the Apple portability patch; no denoising fallback.
- 500 native-conditioning updates, scale 1.2, churn 200, neutral extra chain phase,
  physical source positions and no per-step reinjection. Every candidate records
  1,000 actual first-layer RoPE query/key calls in provenance.
- Separate generated-only CPU refinement: Python 3.12, OpenMM 8.5.2, NumPy 2.4.6,
  one CPU thread, no solvent. Preflight executes a real CPU force kernel.
- New Apple registrations prefer local-v1; an explicit frozen legacy request
  selects the legacy launcher or fails, never silently converts profiles.

The installer was exercised with an isolated `HOME`, using its normal private
launcher directory and runtime discovery. Existing user launchers were not
overwritten. Publication ran on native macOS checkout storage and exercised the
real atomic no-replace bundle operation, not a mocked publication adapter.

## Complete successful v2 controls

| Public entry point | Portable mask | Seeds | Independently accepted |
|---|---|---|---:|
| Homology, mosaic-first | 9WW8 gap5 | 7 | 1/1 |
| Homology, mosaic-first | 8EK6 H-CDR1 gap5 | 7 | 1/1 |
| Homology, mosaic-first | 9Z0U H-CDR3 gap10 | 7 | 1/1 |
| model | 9WW8 gap10 | 7, 19 | 2/2 |

The [v2 machine-readable audit](cc89-public-apple-acceptance-v2.json) independently
checks exact expected requests, digest-bound bundle artifacts, geometry, source
records, generated-atom `DatRecord` sidecars and MPS/CPU trace evidence. The
[portable frozen execution record](cc89-public-apple-execution-v2.json) represents
the actual pre-execution protocol:
`f115984405832cdf0ecd475103eff336712aa6e5b57643756196ee365f32fbef`.
Raw protocols, private execution logs and source snapshots remain below
`.artifacts/apple-cc89/`; checkpoint weights are not committed or copied into
source snapshots.

Ordinary public resume succeeds for all four workflows, including the two-seed
model bundle, without changing bundle file hashes or modification times.

The harness initially supplied forbidden FASTA/seed overrides alongside
`--diffusion-request`; the CLI correctly rejected that invocation with exit 2,
leaving the bundle unchanged. A separate
[exact frozen-request replay](cc89-public-apple-frozen-replay-v2.json) then used the
unchanged two-seed request plus its exact normalized PDB in a private directory,
without overrides. Replay succeeded and all nine bundle files retained their
hashes and modification times. A discoverable poisoned backend would exit 88 if
invoked, proving that successful replay invoked neither sampling nor preflight.
The harness now materializes frozen request/source files together and excludes
conflicting arguments. This follow-up performed **no additional sampling**.

## Retained failed v1 integration

The first [frozen public execution](cc89-public-apple-execution-v1.json), protocol
`a47767d24e0fc077e1facd82a93e8ef813af040608c87032fe480225daac46fe`,
failed in all four workflows and published no successful bundle. The
[failed-outcome report](cc89-public-apple-acceptance-v1.json) and original archives
are retained; they were not replaced or resumed into success.

The new wrapper incorrectly predeclared `OpenMM CPU minimization` as a sampling
provenance operation. The shared refiner appends that operation itself, so the
unchanged contract rejected the duplicate after refinement. Four seed-7 sampling
calls ran; model's seed 19 was not reached. The correction gives the shared
refiner sole ownership of its annotation and has a regression test. No sampler,
refinement algorithm, geometry threshold, mask or seed was selected or changed
to obtain acceptance. A separate v2 protocol explicitly supersedes the failed
development protocol and repeats the same integration controls.

## Reproduction

Use the [Apple setup](../../deploy/protpardelle-1c/README.md#apple-silicon-preparation),
the tracked-control materializer in the [handoff](../plans/apple-cc89-handoff.md)
and a newly registered corrected launcher. Keep the native environment/venv path
to the CPU interpreter, not its resolved symlink target.

```bash
python scripts/run_apple_cc89_public_acceptance.py freeze \
  --root .artifacts/apple-cc89/public-new \
  --controls .artifacts/apple-cc89/controls-v1 \
  --runner "$MPS_LAUNCHER" --core-python "$REFINEMENT_PYTHON" \
  --launcher-home "$HOME"
python scripts/run_apple_cc89_public_acceptance.py run \
  --root .artifacts/apple-cc89/public-new
python scripts/run_apple_cc89_public_acceptance.py audit \
  --root .artifacts/apple-cc89/public-new \
  --report .artifacts/apple-cc89/public-new/results.json
```

Freeze only after source changes are complete; destinations must be new. The
runner refuses changed frozen artifacts and never resamples a started terminal
outcome. Request/reference isolation, fixed seeds and every outcome remain visible.

## Verification and remaining boundary

The fast suite finishes with **1,195 passed, 9 failed, 2 skipped**, with 31 slow
tests deselected. All nine failures match the clean baseline failures documented
in the [research pilot](cc89-apple-corrected-pilot.md#software-verification).
The additional frozen-command/report-coherence harness tests were added afterward
and run separately with the focused suite; there is no claim that those new tests
were included in the earlier full-suite count.

The final focused admission/runtime/Homology/handoff/harness suite passes **182
tests**; explicit seven-file mypy,
Ruff, generated CLI/GUI specs and agent-documentation maps pass. GUI typecheck
passes. GUI tests have 243 passes and one naming/dangling-symlink failure reproduced
on clean baseline `9b4fa37`; naming code was not changed for this work.

A larger frozen memory/latency/operational cohort is still required before wider
MPS acceptance. These checks do not establish a unique experimental conformation,
independent training membership, arbitrary gap support, full-complex neural
sampling, a solvent workflow or a new default scientific backend. The separate
[research portability pilot](cc89-apple-corrected-pilot.md) remains 8/8 after CPU
refinement; it must not be added to these five integration candidates as if they
were independent structures.
