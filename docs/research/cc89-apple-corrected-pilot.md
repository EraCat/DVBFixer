# Corrected cc89 Apple research portability pilot

The four frozen portable masks, each with original seeds **7/19**, pass the
existing independent geometry/source-preservation gates **8/8 after generated-only
CPU refinement**. Raw MPS candidates pass **5/8**; the three raw failures are severe
steric overlaps resolved by the unchanged refiner. No terminal failures were
replaced and no reference RMSD was computed or used for selection.

This is a portability check on **three previously studied sources**, not eight
independent structures, a new holdout, or public MPS acceptance. MODELLER remains
default. The historical public MPS profile and installer/GUI behavior are unchanged.

## Frozen execution and provenance

- Host: Apple M3 Pro, native macOS 26.6.2 arm64, 18 GiB unified memory.
- Sampling: native Python 3.12.14 / Torch 2.6.0, MPS; unsupported-operator fallback
  explicitly disabled. Fast-math/Metal preference and allocator overrides unset.
- Refinement: separate core environment, Python 3.12.13 / OpenMM 8.5.2, CPU with
  one thread; generated-only, no solvent, no denoising fallback.
- Upstream: `ee378400f25b801fa481028000f9060183d7fb4c` plus **only** the frozen Apple
  portability patch. The previously installed upstream's `models.py` did not match
  that patch, so a separate clean worktree was prepared; the old installation was
  not modified. Sampling explicitly imports the verified worktree via `PYTHONPATH`.
- Numerical policy: 500 native-conditioning updates, scale 1.2, churn 200,
  neutral chain phase and physical source positions; no per-step reinjection.
- Explicit research identity:
  `protpardelle-1c-mps-source-physical-research-v1`.
- Pre-execution protocol SHA-256:
  `243f0712aee022c79358dd64d13e9bc7de0bcbbe039fa459774e7fac99d41119`.

The [portable frozen execution record](cc89-apple-corrected-execution-v1.json)
contains request/source/code bindings and environment identities. Its paths are
repository-relative; it is a record, not an executable request. The original
digest-bound execution protocol, environment exports and source snapshot remain
under `.artifacts/apple-cc89/`. Checkpoint weights are neither copied into the
snapshot nor committed.

Host inventory was collected against a separate clean baseline worktree at
`9b4fa37`, because the development checkout contained unrelated untracked user
files. The protocol separately freezes the actual executed development code.
Those user files were not removed or ignored to bypass the inventory gate.

## Operator checks before the pilot

Paired synthetic CPU/MPS operator smokes passed. Their coordinate RMS difference
was `1.0341405492834497e-05 Å`; byte identity is not required. This is an operator
comparison, not a reconstruction result.

All four corrected one-step probes passed on MPS. The adapter instrumented the
actual copied `net.transformer.layers[0][0].rope`, verified consumed physical
positions and neutral phase, and checked tensor devices. Local neural axes were
54/93 residues for 9WW8 gap5/gap10, 80 for 8EK6 and 125 for 9Z0U. The two antibody
contexts retained physical inter-chain position jumps of 200; discontiguous spans
within a physical chain retained their source sequence separations.

## Complete mask/seed outcomes

| Mask | Seed | Raw geometry | After CPU refinement |
|---|---:|---|---|
| 9WW8 gap5 | 7 | PASS | PASS |
| 9WW8 gap5 | 19 | PASS | PASS |
| 9WW8 gap10 | 7 | PASS | PASS |
| 9WW8 gap10 | 19 | PASS | PASS |
| 8EK6 H-CDR1 gap5 | 7 | PASS | PASS |
| 8EK6 H-CDR1 gap5 | 19 | Severe overlap | PASS |
| 9Z0U H-CDR3 gap10 | 7 | Severe overlap | PASS |
| 9Z0U H-CDR3 gap10 | 19 | Severe overlap | PASS |

The [machine-readable audit](cc89-apple-corrected-pilot-v1.json) records every
refined outcome, complete validation metrics, coordinate digest and sampling
resource measurements. All eight have:

- zero detectable D-Cα and zero fixed-heavy displacement;
- byte-identical outside-gap atom records;
- passing junction, generated-region geometry and severe-clash gates;
- matching frozen request/source-position provenance and research trace identity;
- 500 MPS denoising updates, zero callback updates and 1,000 first-layer RoPE
  query/key observations;
- generated-atom `DatRecord` sidecars matching the request exactly;
- recorded CPU refinement and no postprocessing failures.

Only request JSON and the gapped normalized PDB were copied into each worker
workspace. Native/reference PDBs remained outside sampling and refinement.

Denoising took 16.72–18.73 seconds per outcome; CPU refinement took 5.17–58.77
seconds. These are descriptive pilot timings, not an isolated latency benchmark.
MPS tensor/driver allocations and process RSS overlap in unified memory and must
not be added together. Wider memory/operational coverage is still required.

Re-running the pilot command reused all eight completed archives: **112 files had
unchanged content hashes and modification times**, with no repeated sampling.
This verifies research-runner resume, not public bundle publication/replay.

## Software verification

The focused adapter/handoff/context suite passes **73 tests**. Ruff, generated
CLI/GUI spec checks, agent-documentation maps, fixture SHA-256 verification and
diff whitespace checks pass. No GUI source changed.

The general fast suite finishes with **1,180 passed, 9 failed, 2 skipped**, with
31 slow tests deselected. It is not an all-green acceptance signal on this host.
All nine unrelated failures reproduce on clean baseline `9b4fa37` in the same core
environment: the fixture-manifest completeness test excludes its already-listed
JSON manifest; one Protenix test requires Torch absent from core, another has an
environment-dependent preflight expectation; six GROMACS 2026.0 acceptance cases
reject their `pbc=no` / Verlet test setup. These were not repaired or hidden by
changing test selection. An initial launch without core's `bin` on `PATH` also
caused CLI-not-found failures; the suite was re-run through `micromamba run`.

## Remaining acceptance boundary

Subsequent [versioned public Apple integration](cc89-public-apple-acceptance.md)
passes 5/5 candidates across four workflows, including multi-seed publication and
exact frozen-request replay. It uses a new profile identity and retains the
historical profile; the larger operational cohort is still pending. The paragraph
below records the boundary at the end of this original research pilot.

At pilot completion, public MPS profile metadata/admission, installer/context
defaults, trace contract and GUI semantics still required a coordinated separate
integration step. Real `model`/mosaic-first Homology, multi-seed atomic publication
and exact frozen-request replay on native storage were not established by this
research pilot; they are evaluated only in the subsequent report. The larger
operational cohort remains unverified. Do not relabel these research outputs as
the old public MPS profile or infer experimental conformational accuracy from geometry.

See the [Apple handoff](../plans/apple-cc89-handoff.md) for reproduction commands
and the [CUDA acceptance](cc89-public-cuda-acceptance.md) for the separate Linux
integration evidence.
