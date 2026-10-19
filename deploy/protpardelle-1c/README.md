# Protpardelle-1c research adapter

This directory contains the pinned DVBFixer research adapter and experimental
protocol runner for Protpardelle-1c revision
`ee378400f25b801fa481028000f9060183d7fb4c`. MODELLER remains the default and
production-supported backend.

## CUDA rich-context chain-phase diagnosis

The private CUDA adapter accepts explicit
`chain_phase_policy="neutral-v1"` only when the request also declares
`BackendOption("cc89_chain_phase", "neutral-v1")`. This neutralizes the cc89
denoiser's extra rotary chain-phase term while retaining the sampler's chain
indices, residue-index breaks, motif entities, and source mappings. The default
is `native`; this research intervention is not enabled for MPS or exposed as a
public profile.

On the frozen three-case/six-output diagnostic cohort, the change reduces raw
gap RMSD from 11–20 Å to 0.35–0.89 Å, and unchanged generated-only CUDA refinement
accepts 6/6. See the [causal diagnosis and evidence](../../docs/research/cc89-chain-phase-root-cause.md).
This replaces the earlier interpretation that local refinement could not rescue
the gaps themselves; the original configuration's 0/6 result remains preserved.

## Apple Silicon preparation

Use a native arm64 Python environment and apply the Apple patch to the clean,
pinned upstream checkout:

```bash
micromamba create -f deploy/protpardelle-1c/environment-apple-arm64.yml
micromamba activate dvbfixer-protpardelle-apple
git clone https://github.com/ProteinDesignLab/protpardelle-1c.git "$PROTPARDELLE_ROOT"
git -C "$PROTPARDELLE_ROOT" checkout ee378400f25b801fa481028000f9060183d7fb4c
git -C "$PROTPARDELLE_ROOT" apply \
  "$DVBFIXER_ROOT/deploy/protpardelle-1c/apple-portability.patch"
python -m pip install --no-deps -e "$PROTPARDELLE_ROOT"
python -m pip install -e "$DVBFIXER_ROOT"
```

Frozen identities:

| Artifact | SHA-256 |
|---|---|
| Apple portability/heterogen-guidance patch | `627891e28d5055cb0d903f542af695569d7133b0480cab8f25d154dc8ccc78c9` |
| Patched `models.py` | `8513fac0d18d3080b14673bb9b6ed3b231e1d31d30449d3b8c6cc09f0445800b` |
| cc89 config | `e9999ace79bf3044351cc982a624fc3459add3a4f91cbf97ff5b437b8942eb9d` |
| cc89 checkpoint | `dfc9895b399ec4497bf6d646502168725f01dcbd55bc0b541fc3e3cc1f2f0483` |

The checkpoint is operator-provided and is not downloaded or redistributed by
DVBFixer. Preserve an explicit environment export and `pip freeze` for every
accepted run in addition to the installable profile above.

Remove existing `__pycache__` directories from the Protpardelle checkout before
preflight. The production wrapper disables bytecode writes before loading the
engine so accepted runs do not recreate them.

The patch makes CUDA cache cleanup conditional and disables per-step host copies
of trajectory tensors when the adapter requests only final coordinates. It does
not change the denoising update or final coordinates. The existing callback patch
is not part of the frozen Apple baseline and must not be combined with this patch.

Before any MPS process starts, disable unsupported-operator fallback explicitly:

```bash
export PYTHONNOUSERSITE=1
export PYTORCH_ENABLE_MPS_FALLBACK=0
```

Freeze the remaining MPS variables rather than changing them between lanes. The
initial baseline leaves fast math and Metal preference disabled/unset and retains
PyTorch's default allocator watermarks:

```bash
unset PYTORCH_MPS_FAST_MATH
unset PYTORCH_MPS_PREFER_METAL
unset PYTORCH_MPS_HIGH_WATERMARK_RATIO
unset PYTORCH_MPS_LOW_WATERMARK_RATIO
```

Collect the host record from the Protpardelle environment before inference. The
repository must be a clean checkout and the environment export must already
exist:

```bash
python scripts/collect_apple_diffusion_inventory.py \
  .artifacts/apple-diffusion/host-inventory.json \
  --environment-lock .artifacts/apple-diffusion/protpardelle-explicit.txt
```

Before using a materialized DVBFixer request, run paired synthetic operator
smokes with the pinned config and checkpoint:

```bash
python deploy/protpardelle-1c/operator_smoke.py \
  --config "$CONFIG" --checkpoint "$CHECKPOINT" \
  --output .artifacts/apple-diffusion/cpu-operator-smoke.json --device cpu
python deploy/protpardelle-1c/operator_smoke.py \
  --config "$CONFIG" --checkpoint "$CHECKPOINT" \
  --output .artifacts/apple-diffusion/mps-operator-smoke.json --device mps
python deploy/protpardelle-1c/compare_operator_smokes.py \
  .artifacts/apple-diffusion/cpu-operator-smoke.json \
  .artifacts/apple-diffusion/mps-operator-smoke.json \
  .artifacts/apple-diffusion/cpu-mps-operator-comparison.json
```

Run the one-step MPS operator smoke with signpost profiling enabled:

```bash
python deploy/protpardelle-1c/checkpoint_gap_smoke.py \
  WORKSPACE/request.json WORKSPACE/apple-mps-one-step \
  --config "$CONFIG" --checkpoint "$CHECKPOINT" \
  --device mps --steps 1 --mps-profile
```

The adapter fails instead of relabeling CPU execution as MPS. It verifies all
model parameters and buffers, sampler inputs, and final coordinates are on the
requested device. Timings synchronize MPS before measurement boundaries. MPS
tensor allocation, Metal driver allocation, recommended working-set size, and
process peak RSS are recorded separately because they overlap in unified memory
and must not be added together.

OpenMM refinement runs in the separate DVBFixer environment with the `CPU`
platform. It is not MPS acceleration.

## Experimental CLI protocol runner

Register the frozen backend once from the native Apple environment:

```bash
python "$DVBFIXER_ROOT/scripts/install_diffusion_backend.py" \
  protpardelle "$MODEL_PARAMS/weights/cc89_epoch415.pth" \
  --engine-root "$PROTPARDELLE_ROOT"
```

The installed private launcher binds the backend Python, runner, checkpoint,
and required MPS environment. Normal use therefore contains no deployment
paths:

```bash
dvbfixer model INPUT.pdb --fasta TARGET.fasta \
  --backend diffusion -o OUTPUT_BUNDLE
```

`MODEL_PARAMS` must also contain `configs/cc89.yaml`. The wrapper derives
`PROTPARDELLE_MODEL_PARAMS` from this checkpoint layout before importing
Protpardelle. It uses the frozen 500-step float32 MPS settings, disables
per-step reinjection, performs generated-only OpenMM refinement on the CPU, and
writes the versioned `result.json` expected by core DVBFixer. Core DVBFixer
remains responsible for independent validation and atomic publication.
