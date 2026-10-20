# Apple Silicon handoff: corrected cc89 local input

Prepared on Linux after public CUDA baseline **`cb43db6`**, branch
`feature/dvbfixer-hardening`. This handoff prepares the next machine; it does not
claim that the corrected mode has run on MPS. The existing public MPS profile
remains the historical native-phase/native-position implementation.

## Resume here

Read `AGENTS.md`, this file, then:

1. [Public CUDA acceptance](../research/cc89-public-cuda-acceptance.md).
2. [Input/position root cause](../research/cc89-input-representation-audit.md).
3. [Apple deployment and pinned identities](../../deploy/protpardelle-1c/README.md#apple-silicon-preparation).

Current evidence: corrected development recheck **60/60**, source-disjoint
follow-up **24/24 on four sources**, and public CUDA integration **5/5 across four
model/Homology workflows**, including multi-seed publication and resume.
These are separate studies, not 89 independent structures. Geometry/source
preservation is primary; reference RMSD is secondary, never a seed selector.

Public CUDA scope: one CYS-free internal 5–10-residue gap, at most 512 whole-source
canonical protein residues, fixed source-only local context, neutral extra chain
phase, physical source sequence positions, and generated-only CUDA refinement.
MODELLER remains default. Old negative full-context results remain archived.

## What travels in Git

- The source code, profile/environment definitions, frozen protocols, and reports.
- `tests/fixtures/cc89_apple_handoff/`: three whole observed protein source PDBs,
  companion unchanged FASTAs, original four mask specifications, and SHA-256
  bindings to the audited Linux cohorts. These contain **experimental input
  coordinates**, not generated candidates. They are sufficient for the first
  four-case/eight-seed corrected-MPS pilot on a fresh clone.
- `scripts/prepare_apple_cc89_handoff.py`: reconstructs exact source-minus-gap
  inputs, masked templates, explicit local research requests and position digests
  without neural inference. Evaluation references go in a separate directory.

No `.artifacts/`, historical `test/`, visual-review folders, environments,
checkpoints or credentials are required from this Linux workspace. The checkpoint
and matching cc89 config must be supplied separately by the operator. Do not
commit or redistribute them. The three source structures may overlap pretraining;
the pilot is a portability check, not a new independent holdout.

## First commands on the Mac

Use a fresh native macOS arm64 checkout (not Rosetta), then work from its root:

```bash
git fetch origin
git switch feature/dvbfixer-hardening
git pull --ff-only origin feature/dvbfixer-hardening
git status --short
shasum -a 256 -c tests/fixtures/MANIFEST.sha256

export DVBFIXER_ROOT="$PWD"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
export PYTORCH_ENABLE_MPS_FALLBACK=0
unset PYTORCH_MPS_FAST_MATH PYTORCH_MPS_PREFER_METAL
unset PYTORCH_MPS_HIGH_WATERMARK_RATIO PYTORCH_MPS_LOW_WATERMARK_RATIO
```

Provision core DVBFixer and native Apple sampling using
[`docs/installation.md`](../installation.md) and the existing
[`environment-apple-arm64.yml`](../../deploy/protpardelle-1c/environment-apple-arm64.yml).
Keep core's Python `>=3.11,<3.14` and NumPy `<2.5`. Keep the sampling Python 3.12
and Torch 2.6.0 pinned. Do not install the Linux CUDA environments on macOS.
Use a separate clean upstream checkout at
`ee378400f25b801fa481028000f9060183d7fb4c` with **only**
`apple-portability.patch`; do not combine it with `per-step-callback.patch`.
The deployment guide supplies the exact checkpoint/config/patch hashes.

Set `PROTPARDELLE_ROOT` to that clean Apple checkout, `CHECKPOINT` to the
operator-provided `model_params/weights/cc89_epoch415.pth`, and `CONFIG` to its
matching `model_params/configs/cc89.yaml`. Verify both before any neural call:

```bash
shasum -a 256 "$CHECKPOINT" "$CONFIG"
# checkpoint: dfc9895b399ec4497bf6d646502168725f01dcbd55bc0b541fc3e3cc1f2f0483
# config:     e9999ace79bf3044351cc982a624fc3459add3a4f91cbf97ff5b437b8942eb9d
```

Export the Apple environment lock, then run the existing inventory collector
from that environment; its lock path must exist and the checkout must be clean:

```bash
mkdir -p .artifacts/apple-cc89
micromamba env export -n dvbfixer-protpardelle-apple --explicit \
  > .artifacts/apple-cc89/environment-explicit.txt
micromamba run -n dvbfixer-protpardelle-apple python \
  scripts/collect_apple_diffusion_inventory.py \
  .artifacts/apple-cc89/host-inventory.json \
  --environment-lock .artifacts/apple-cc89/environment-explicit.txt

# Run this materialization in core, not in an incompletely provisioned ML env.
PYTHONPATH="$DVBFIXER_ROOT/src" micromamba run -n dvbfixer python \
  scripts/prepare_apple_cc89_handoff.py --output .artifacts/apple-cc89/controls-v1
```

`inputs.json` records **four cases, eight requests, inference_executed=false**.
Use each case's root `request-seed7.json` / `request-seed19.json` as the corrected
research request. The older files under `requests/` are materialization provenance,
not the corrected request entry points. Never copy `evaluation/` or the tracked
native source PDBs into a sampling/refinement workspace.

## Exact implementation still needed on Apple

The corrected requests deliberately **cannot run on MPS yet**. Do not remove
guards merely to get a green run. Implement an explicitly identified research
mode first, while preserving the legacy public MPS profile:

1. `checkpoint_gap_smoke.py::_require_chain_phase_policy` and
   `_require_position_feature_policy`: admit an explicit, matched corrected MPS
   research policy after device/source checks; currently both restrict it to CUDA.
2. `_run_staged`: use `_NeutralDenoiserChainPhase` and
   `source_context_position_features` on real MPS tensors, preserve physical chain
   breaks, and record the **actual** policy/profile in trace and provenance.
   Current MPS trace selection automatically labels the legacy public profile;
   corrected research must not be mislabeled as that profile.
3. Audit `_NeutralDenoiserChainPhase` against the Apple-patched source. First-layer
   instrumentation belongs on `net.transformer.layers[0][0].rope`, not the unused
   template `transformer.rope` object. Do not add per-step reinjection: the frozen
   method uses native conditioning and final exact source restoration.
4. Use generated-only `refine_runner_result(..., platform_name="CPU")` for the
   initial Apple arm. CPU **refinement** is intentional; CPU fallback during MPS
   **denoising** is forbidden. Keep the interpreter's venv path intact: resolving
   its symlink can select a different base environment.
5. Only after the pilot passes, update public MPS profile metadata, admission,
   installer/default context routing, trace contract and GUI semantics together.
   CUDA-only `prepare_cuda_cc89_request` must not be reused by simply changing its
   profile string. Preserve atomic publication and exact frozen-request replay.

## Execution order and acceptance

1. Existing synthetic CPU/MPS operator smokes and comparison, as documented in
   the deployment guide. Record real MPS availability, all tensor devices and
   synchronized timings; no fallback.
2. Corrected source-position probe and one-step device test after research-mode
   implementation. This is an operator check, not a successful reconstruction.
3. Four portable masks × original seeds 7/19, 500 steps, scale 1.2, churn 200,
   native conditioning; run sequentially and archive every outcome. Freeze the
   new execution protocol before the first corrected MPS sample.
4. Unchanged generated-only CPU refinement and independent geometry, junction,
   clashes, D-Cα, exact outside-gap records, `.dat`, trace and request checks.
   Do not choose seeds by reference RMSD; do not replace terminal failures.
5. Public model/Homology, multi-seed and resume checks on native filesystem;
   then a larger memory/latency/operational cohort before wider acceptance.

The CUDA public controls used seeds 7 for 9WW8-gap5, 8EK6-H-CDR1 and
9Z0U-H-CDR3, and seeds 7/19 for 9WW8-gap10. All eight original corrected research
outcomes remain available in the tracked prospective result reports. MPS outputs
need not be byte-identical to CUDA or CPU refinement outputs.

On Linux, the handoff materializer and coordinate-withholding regression are
tested without a checkpoint. Linux fast-suite baseline at `cb43db6` is **1,175
passed, 7 skipped**; GUI **244 passed**. Full-following mypy has 35 pre-existing
errors reproduced on `5a402cc`; the explicit API/context targets pass with
`--follow-imports=silent`. Do not spend the portability session fixing unrelated
typing errors or declaring MPS acceptance from these Linux tests.

## Suggested first instruction to the next agent

> Read AGENTS.md and docs/plans/apple-cc89-handoff.md. Continue the corrected
> cc89 local-input Apple port from the pushed branch. Verify native arm64/MPS,
> materialize the tracked controls, and implement the explicit research-mode
> gates/trace identity before inference. Keep the old public MPS profile intact
> until the new pilot passes. Geometry and preservation are primary; no hidden
> reference coordinates, no seed selection by RMSD, no denoising fallback.
