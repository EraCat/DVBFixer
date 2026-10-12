# Protenix v1 Hook Spike

This directory contains the maintained patch, research drivers, and experimental
protocol runner used to evaluate Protenix v1 for reconstructing experimentally
unresolved internal protein segments in deposited structures. MODELLER remains
the default and production-supported backend.

Apply the patch only to revision
`85767b811c40ed46e73a9b39519cf6bfca8701ba`:

```bash
git -C /path/to/Protenix checkout --detach 85767b811c40ed46e73a9b39519cf6bfca8701ba
git -C /path/to/Protenix apply /path/to/DVBFixer/deploy/protenix-v1/per-step-callback.patch
python deploy/protenix-v1/hook-smoke.py /path/to/Protenix
```

The callback receives the mutable all-atom coordinate tensor after every
denoising update and before the next update. It must preserve tensor shape. The
benchmark adapter uses `reinjection.FixedAtomReinjector` and the stable atom
axis to perform weighted Kabsch synchronization on the active Torch device and
overwrite observed coordinates exactly.

The CPU smoke proves callback placement and exact overwrite mechanics without
loading weights. For the private checkpoint-backed gap smoke, build a template
input and run from an environment containing the pinned Protenix checkout:

```bash
python deploy/protenix-v1/build-template-input.py request.json protenix-input
PYTHONPATH=/path/to/Protenix:src \
  PROTENIX_ROOT_DIR=/path/to/Protenix \
  LAYERNORM_TYPE=torch \
  python deploy/protenix-v1/checkpoint_gap_smoke.py \
    request.json protenix-input/input.json protenix-output \
    --kalign /path/to/kalign \
    --checkpoint /path/to/protenix_base_default_v1.0.0.pt --steps 200
```

The driver resolves Protenix sequence ordinals back to request identities,
installs `FixedAtomReinjector` after featurization, records every callback, emits
only requested atoms, and runs DVBFixer-owned validation. The first full 7X35
run proved exact reinjection at all 200 steps but failed one peptide-junction
gate. Apply the existing DVBFixer localized refinement without rerunning the
checkpoint:

```bash
python deploy/protenix-v1/refine_candidate.py \
  request.json protenix-output/candidate.pdb refined-output \
  --expected-candidate-sha256 RAW_CANDIDATE_SHA256
```

The refinement wrapper preserves the raw candidate, rewrites only generated
coordinate columns, and reruns independent validation. Independent seeded 7X35
runs produced byte-identical raw and refined PDBs, and the refined candidate
passed every hard gate. The initial three-way ablation is complete: use
`--ablation-mode template-conditioning-only` for the conditioning-only arm;
the default is per-step reinjection. Broader benchmark evidence is still
required before any public backend work.

## Experimental CLI protocol runner

`production_runner.py` implements the versioned external-runner protocol for the
explicit `protenix-v1-cuda` profile. It freezes the audited Protenix revision,
callback patch, PyTorch/CUDA identity, 200-step per-step reinjection settings,
and deterministic OpenMM `Reference` boundary refinement.

The wrapper is committed, dependency-light tests run in core CI, and a
checkpoint-backed public-CLI reconstruction passed on the pinned Linux/A100
host. The frozen 231-case production-wrapper replay and independent revalidation
completed with 219 accepted and 12 rejected candidates. See
[`linux-protenix-public-replay-results.md`](../../docs/research/linux-protenix-public-replay-results.md)
for the single changed scientific status and remaining deployment gates.

On the pinned Linux environment:

```bash
/path/to/protenix-env/bin/python "$DVBFIXER_ROOT/scripts/install_diffusion_backend.py" \
  protenix /path/to/protenix_base_default_v1.0.0.pt \
  --engine-root /path/to/Protenix \
  --kalign /path/to/kalign

dvbfixer model INPUT.pdb --fasta TARGET.fasta \
  --backend diffusion -o OUTPUT_BUNDLE
```

The one-time installer verifies the frozen checkpoint and Kalign digests and
creates a private launcher bound to that Python environment, this DVBFixer
checkout, and the pinned engine source. Runtime profile, runner, checkpoint,
and digest are not per-run model options.

The runner requires Linux amd64, Python 3.13.15, PyTorch 2.13.0, CUDA 12.9, the
NVIDIA A100-SXM4-40GB device class, digest-pinned Kalign 3.6.0, the exact patched
source tree, and the operator-provided checkpoint. DVBFixer does not download or
redistribute the checkpoint. Remove existing `__pycache__` directories from the
Protenix checkout before preflight; the wrapper disables bytecode writes before
loading the engine so accepted runs do not recreate them.

`profile-lock.json` is the tracked candidate profile identity. The runner
verifies its digest, critical installed package versions, and Kalign executable
before loading Protenix. It also records the pinned CUDA base-image digest; a
built image's final digest and a complete accepted package export remain
operator evidence. The image digest may be supplied as
`DVBFIXER_PROTENIX_IMAGE_DIGEST`. The final image build and deployment acceptance
remain pending; the full public cohort replay is complete.

## Manual self-hosted hardware smoke

`.github/workflows/protenix-hardware-acceptance.yml` defines a manual
`workflow_dispatch` lane on a runner labelled `self-hosted`, `linux`, `x64`, and
`dvbfixer-protenix-acceptance`. It does not run on pushes or pull requests and
does not add CUDA or checkpoints to ordinary CI.

Provision these environment variables in the runner service:

| Variable | Provisioned asset |
|---|---|
| `DVBFIXER_CORE_PYTHON` | Python executable in the scientific DVBFixer environment; `dvbfixer` must exist beside it |
| `DVBFIXER_BACKEND_PYTHON` | Python executable in the exact profile-lock backend environment |
| `DVBFIXER_PROTENIX_CHECKPOINT` | Operator-owned digest-matching checkpoint |
| `DVBFIXER_PROTENIX_ENGINE_ROOT` | Pinned, callback-patched Protenix checkout and auxiliary data |
| `DVBFIXER_PROTENIX_KALIGN` | Digest-pinned Kalign executable |
| `DVBFIXER_PROTENIX_COHORT_ROOT` | Frozen v5 materialized cohort, including its digest-matching aggregate |

The runner must provide the frozen A100 device, the bounded memory cgroup
required by production preflight, and native `RUNNER_TEMP` storage supporting
atomic no-replace directory publication. Reserve the GPU for this lane: GitHub
concurrency serializes workflow runs, but cannot coordinate unrelated local
cohort jobs. Trigger it after those jobs finish.

Each run installs a private launcher in disposable `XDG_DATA_HOME`, leaving
other installed launchers intact. It performs two independent public-CLI
`36hb` seed-7 reconstructions. `scripts/check_protenix_hardware_acceptance.py`
checks bundle digests, independent validation, frozen PDB identity, request
identity, checkpoint/source/environment provenance, CUDA placement, 200/200
callbacks, zero projection error, and localized refinement. Only portable
digest/resource evidence is uploaded; checkpoints, input structures, host paths,
and raw logs are not included. Temporary work is removed when the step exits.

This is a repeatability smoke, not full-cohort acceptance. The workflow and
CPU-only evidence-gate tests are implemented; provisioning a GitHub runner and
executing the workflow remain operator/hardware acceptance steps.

The workflow's exact hardware step has also been executed locally, with two
accepted, byte-identical public-CLI repeats. Full package exports and the
controlled `9eho` ordering investigation are recorded in
[`linux-protenix-local-deployment-evidence.md`](../../docs/research/linux-protenix-local-deployment-evidence.md).
The GitHub dispatch and final OCI build remain separate infrastructure checks;
native usage does not require either.
