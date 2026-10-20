# Diffusion Runner Environment Plan

**Current status (2026-10-20):** separate environments, profile locks, installer,
Doctor and bounded protocol wrappers are implemented. Corrected Apple local-v1
uses a separately verified CPU-refinement interpreter and passes public 5/5
integration; the legacy native-position MPS identity remains available. Protenix's
resolved profile lock and public NVIDIA smokes exist; the remaining Linux gate is
the full selected production-wrapper cohort and final OCI build/GPU smoke, not
initial environment pinning. See the [current index](README.md) and
[Apple evidence](../research/cc89-public-apple-acceptance.md). Historical milestones
below do not supersede these versioned profile boundaries.

- Status: implementation in progress.
- Scope: platform-specific environments and protocol wrappers for the
  experimental `dvbfixer model --backend diffusion` CLI.
- Core rule: ML frameworks, engine packages, CUDA libraries, and checkpoints do
  not become DVBFixer core dependencies.
- Related plans:
  - [`diffusion-cli-integration.md`](diffusion-cli-integration.md)
  - [`diffusion-gap-reconstruction.md`](diffusion-gap-reconstruction.md)
  - [`small-diffusion-apple-silicon-experiments.md`](small-diffusion-apple-silicon-experiments.md)

## Environment Boundary

DVBFixer core owns request construction, scope admission, subprocess isolation,
independent validation, provenance, and atomic bundle publication. Each diffusion
engine runs in a separate environment through the versioned `request.json` /
`result.json` protocol.

The core environment retains OpenMM/PDBFixer and does not install PyTorch,
Protenix, Protpardelle, CUDA, or model checkpoints. Research tests that import an
engine must run in that engine's environment or skip cleanly when it is absent;
missing Torch in the core environment is not repaired by adding Torch to core.

## Linux/NVIDIA Profile

Profile: `protenix-v1-cuda`.

- Use a pinned Linux `amd64` environment or digest-pinned OCI image.
- Pin Python, PyTorch, CUDA runtime, Protenix source revision, maintained callback
  patch digest, OpenMM refinement stack, and all auxiliary executables.
- Require an operator-provided checkpoint and exact SHA-256 verification.
- Assert CUDA availability and the effective model/input/output device before
  inference.
- Preserve per-step fixed-coordinate reinjection evidence.
- Keep the engine checkout free of untracked importable modules and bytecode
  caches; the maintained wrapper disables bytecode writes before importing the
  engine adapter.
- Keep the ordinary CI lane CUDA-independent; run checkpoint-backed acceptance on
  a self-hosted NVIDIA machine.
- Do not expose `device=auto` or silently switch to CPU/Apple runners.

An NVIDIA host is required before claiming the production wrapper reproduces the
frozen confirmatory baseline. Before moving work to that host, commit and push all
portable code and documentation.

## Apple Silicon Profile

Profile: `protpardelle-1c-mps`.

- Use a native arm64 environment, not Docker Desktop emulation.
- Freeze Python 3.12, PyTorch 2.6.0, Protpardelle-1c revision
  `ee378400f25b801fa481028000f9060183d7fb4c`, and
  `deploy/protpardelle-1c/apple-portability.patch`.
- Do not combine the frozen Apple profile with the callback patch.
- Set `PYTHONNOUSERSITE=1` and `PYTORCH_ENABLE_MPS_FALLBACK=0` before Python
  starts.
- Assert MPS availability and model/input/output device placement.
- Use float32 MPS sampling and record synchronized timing plus separate MPS,
  Metal-driver, and process-RSS counters.
- Record final fixed-coordinate restoration honestly; do not claim per-step
  reinjection.
- Keep the engine checkout free of untracked importable modules and bytecode
  caches; the maintained wrapper disables bytecode writes before importing the
  engine adapter.
- Run OpenMM boundary refinement on CPU and label it separately from MPS
  inference.

## Production Wrapper Contract

Add one small executable wrapper per profile:

```text
deploy/protenix-v1/production_runner.py
deploy/protpardelle-1c/production_runner.py
```

Each wrapper must only:

1. read the protocol request from the isolated workspace;
2. validate its fixed profile, checkpoint, engine revision, patch, and device;
3. run candidate generation and the selected refinement path;
4. write contained candidate/trace artifacts and protocol `result.json`.

Wrappers must not publish public outputs or duplicate DVBFixer validation. Core
DVBFixer remains authoritative for scope, identities, geometry, chirality, result
selection, provenance, and publication.

## Dependency Records

For each profile, retain:

- a minimal environment specification;
- an explicit conda package export and `pip freeze` for accepted runs;
- Python/framework/device runtime versions;
- engine source revision and patch SHA-256;
- checkpoint SHA-256 and license status;
- config and auxiliary artifact digests;
- container/base-image digest where applicable.

DVBFixer does not download or redistribute checkpoints automatically.

## Preflight And Doctor

- [x] Verify runner presence and protocol version.
- [x] Verify checkpoint presence and digest before model loading.
- [x] Verify source, patch, config, and environment identity. Optional image
  identity remains deployment-specific because maintained wrappers are local executables.
- [x] Verify CUDA for `protenix-v1-cuda` or MPS for
  `protpardelle-1c-mps`.
- [x] Verify effective device and fallback-disabled state.
- [x] Report refinement platform separately from sampling platform.
- [x] Return stable, actionable failure reasons without launching inference when
  preflight fails.

## Test And Acceptance Matrix

- Core CI: fake runner, strict protocol parsing, scope, validation, timeout,
  containment, digest checks, and atomic publication without Torch.
- Apple self-hosted: production wrapper operator smoke, one-step checkpoint smoke,
  then comparison with the frozen 231-case descriptive baseline.
- Linux self-hosted: production wrapper checkpoint smoke, then comparison with the
  frozen 231-case confirmatory baseline.
- Any silent device fallback, wrong-device tensor, checkpoint mismatch, feature
  loss, or partial publication is a hard failure.

## Implementation Order

1. Implement and locally test the `protpardelle-1c-mps` protocol wrapper on the
   current Apple Silicon host.
2. Add Apple profile preflight and focused core tests.
3. Commit and push all portable changes.
4. Move to a Linux/NVIDIA host only for the `protenix-v1-cuda` wrapper's real
   checkpoint/CUDA smoke and frozen acceptance run.
5. Record Linux results, commit, push, and report the hardware-dependent outcome.

No successful platform smoke changes MODELLER's default status or enables batch,
GUI, `zbs`, `homology`, heterogen support, or automatic profile selection.

## Implementation Status (2026-10-02)

- [x] Apple arm64 environment profile and frozen artifact digests documented.
- [x] `protpardelle-1c-mps` protocol wrapper implemented with strict native-MPS
  preflight and CPU OpenMM boundary refinement.
- [x] Public CLI smoke passed on Apple M3 Pro; the refined candidate passed every
  hard validation gate with zero fixed-heavy-atom movement and zero D-Cα.
- [x] Protocol-v4 `doctor` and public CLI handshakes passed again on a clean
  Protpardelle checkout on 2026-10-05. The production wrapper now derives
  `PROTPARDELLE_MODEL_PARAMS` from the operator-provided checkpoint layout, so
  source attestation no longer conflicts with an untracked model-parameter link.
- [x] Bound private runner workspace growth and terminate the complete process
  group when the limit is exceeded; this applies equally to the Apple MPS lane.
- [x] Replace per-run profile/runner/checkpoint arguments with one-time private
  backend registration and hardware-aware launcher discovery. The normal Apple
  command is now `dvbfixer model ... --backend diffusion`; an optional
  `--diffusion-model protpardelle` only disambiguates model choice. A public CLI
  smoke using no deployment paths passed on Apple M3 Pro on 2026-10-06.
- [x] Accept explicit `--strip-heterogens` before diffusion admission. A native
  Apple MPS smoke with a synthetic retained ligand and CONECT record confirmed
  private-input stripping, unchanged source digest, successful reconstruction,
  and protein-only publication on 2026-10-06.
- [x] Torch-dependent Boltz research imports made lazy so core CI remains
  Torch-free.
- [x] Add the diffusion profile report and bounded no-inference handshake to
  `dvbfixer doctor`.
- [x] Implement the portable `protenix-v1-cuda` protocol wrapper and core tests.
- [x] Pin the resolved Linux environment/source/auxiliary identities in
  `deploy/protenix-v1/profile-lock.json` and exercise public NVIDIA workflows;
  see [workflow evidence](../research/diffusion-workflow-integration.md).
- [ ] Replay the complete selected 231-case cohort through the final Protenix
  production wrapper and build/GPU-smoke its final OCI image.
- [x] Implement versioned corrected Apple local-v1 with isolated CPU refinement,
  bounded public 5/5 integration and exact frozen replay, retaining legacy MPS.
- [ ] Complete the larger corrected-Apple operational/memory/latency cohort.
