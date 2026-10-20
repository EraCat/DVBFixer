# cc89 rich-context failure: causal chain-phase diagnosis

Date: 2026-10-19. Device: NVIDIA A100, PyTorch 2.6.0+cu124, fixed cc89 checkpoint.
Apple MPS work remains deferred. No geometry threshold was changed.

**Expanded follow-up:** the subsequent
[13-source known-sequence holdout](cc89-known-sequence-holdout.md) passes 37/60
after refinement, including 0/16 full-context CDR outcomes. The causal repair
below remains reproducible on its diagnostic pilot, but it does not establish
broad full-context support. Four public Protenix/Homology workflow controls pass.

## Finding

The catastrophic rich-context failure is caused, in the three frozen cases, by
the extra **chain-frequency phase term in the denoiser's rotary encoding**.
Neutralizing that term alone reduces generated-backbone RMSD from 11–20 Å to
0.35–0.89 Å. The normal adapter reproduces these interventions byte-for-byte;
the existing generated-only CUDA refinement then passes **6/6** candidates,
compared with **0/6** for the original mode.

This is a checkpoint/feature compatibility problem in our experimental use of
cc89, not evidence that its weights cannot reconstruct these five-residue gaps.
The pinned upstream README's “Available Models” table describes cc89 as
Monomers=1, Multichain=0 and recommends it for single-chain all-atom refinement.
The generic engine accepting multichain tensors was insufficient evidence of
checkpoint compatibility. The exact learned attention response behind this
sensitivity is not established by these experiments.

## Unchanged scientific inputs

| Case | Gaps | Represented fixed conditioning atoms |
|---|---|---:|
| 1EMV joint | A:24–28 `NADTS`; B:50–54 `FDDFR` | 1,607 |
| 1EMV discontiguous | A:24–28 `NADTS` | 639 |
| 7K8S insertion-coded | H:49,50,51,52,52A `AVISY` | 804 |

These are the same inputs as the earlier
[frontier study](reconstruction-frontiers.md). The joint case represents both
selected chains completely; the two local cases retain additional observed
atoms outside the model axis as preservation-only context. They are not the
separate clean full-input long-gap study.

Gaps are removed before conditioning selection and motif construction. Runtime
audits verify zero gap coordinates in the actual learned crop-conditioning
tensor, exact atom correspondence, and conditioning coordinates matching the
remaining source under one common rigid transform. The reference is used only
after inference for accuracy measurement.

## Experimental sequence

All controls were frozen before their respective inference stages. Failures are
retained; no candidate or mask was replaced.

### 1. Tensor semantics and motif density: 18 CUDA samplings

The full/native and full/projected baselines reproduce all six original
candidates **byte-for-byte**. Actual tensors reaching the denoiser have the
expected atom mapping and no hidden gap coordinates. All checkpoint parameters
load with zero missing/unexpected keys.

Two hypotheses were tested while retaining the same token axis:

- Reduce learned motif conditioning to at most 24 complete observed residues,
  reflecting cc89's configured discontiguous training-motif limit. Retain every
  anchor; distinguish sparse learned conditioning from full fixed-state projection.
- Project fixed-atom self-conditioning as well as the mutable coordinate state.

Neither intervention rescues this configuration: **0/18** geometry passes.
Dense conditioning and self-conditioning mismatch do not explain the primary
catastrophic failure in these cases.

### 2. Chain features and monomers: 18 CUDA samplings

Two chain-feature interventions were tested on each original rich-context input:

- Restore original source-chain IDs and original target positions instead of
  compacted proxy-fragment features. This exposes a real representational
  difference, but does not rescue the cases: generated RMSD remains 8.93–13.79 Å
  in projected arms.
- Set the rotary chain-phase input to zero while retaining the original
  residue-index gaps and every token/context atom. This removes the catastrophic
  error in all three cases.

Three explicit monomer controls use the same masks on 1EMV A, 1EMV B, and 7K8S H,
with other chains excluded as a disclosed scientific ablation. Their native and
projected RMSDs are 0.87/0.91, 0.18/0.18, and 0.36/0.36 Å respectively. This is
consistent with a multichain feature incompatibility rather than inherently
unrecoverable gap sequences.

| Original rich input | Original projected RMSD (Å) | Neutral chain-phase projected RMSD (Å) | Raw neutral result |
|---|---:|---:|---|
| 1EMV joint | 13.79424 | 0.34941 | accepted |
| 1EMV discontiguous | 17.82440 | 0.87537 | rejected: severe overlap only |
| 7K8S | 20.29186 | 0.45534 | rejected: severe overlap only |

The network's input `residue_index` already carries explicit chain breaks.
Upstream `RotaryEmbedding.forward` additionally combines residue frequencies
with a chain-index phase. The successful intervention changes this extra phase;
it does **not** make residues from different chains sequential neighbors.

### 3. Ordinary adapter confirmation: six CUDA samplings and six refinements

`checkpoint_gap_smoke._run_staged(..., chain_phase_policy="neutral-v1")` now
implements the intervention through a denoiser pre-hook. Only the denoiser's
phase argument is neutralized. The sampler retains the real chain indices,
residue-index breaks, separate motif chains, exact source mapping, full declared
conditioning, and per-step fixed-coordinate projection where requested.

The request must explicitly declare
`BackendOption("cc89_chain_phase", "neutral-v1")`; request/adapter disagreement,
an unknown policy, a non-CUDA device, an unexpected positional signature, absent
residue-index breaks, or an incorrect denoiser-call count fails closed. Default
`native` behavior is retained. This is a private research selector, not a new
public backend or an MPS change. Trace patch identity, backend provenance, and
summary record the intervention.

All six ordinary-adapter candidates match the causal zero-phase controls
**byte-for-byte**. All six then receive the same previously frozen rigid v6,
generated-only CUDA refinement, with no reference-guided optimization.

| Case | Mode | Raw backbone RMSD (Å) | Refined backbone RMSD (Å) | Refined result |
|---|---|---:|---:|---|
| 1EMV joint | native conditioning | 0.35067 | **0.17131** | PASS |
| 1EMV joint | per-step projection | 0.34941 | **0.17138** | PASS |
| 1EMV discontiguous | native conditioning | 0.88970 | **0.18687** | PASS |
| 1EMV discontiguous | per-step projection | 0.87537 | **0.20314** | PASS |
| 7K8S | native conditioning | 0.45012 | **0.25402** | PASS |
| 7K8S | per-step projection | 0.45534 | **0.24771** | PASS |

Raw acceptance is 2/6; the four raw failures are severe overlaps, not the old
broken peptide geometry or D chirality. Refined acceptance is 6/6, with zero
D-Cα, zero fixed-heavy displacement, and junction C–N distances 1.326–1.346 Å.

## Independent artifact and structural audit

`scripts/analyze_cc89_chain_phase.py` checks immutable inventories/protocol
bindings, reruns independent geometry and withheld-reference measurements,
compares the six baseline and six causal-repair byte identities, verifies that
the only scientific-request addition is the declared chain-phase option, and
checks exact outside-gap atom-record preservation. All **42 sampled candidates**
and **six refined repair candidates** were audited. The implementing agent's
revalidation is not an external scientific review.

Compact report: [`cc89-chain-phase-analysis.json`](cc89-chain-phase-analysis.json),
SHA-256 `4648e5bb8bc4fe615e62c834029f0898e4e413ac45b17e3b01a9a7332d0d966e`.

| Frozen protocol | SHA-256 |
|---|---|
| [Tensor controls](cc89-tensor-semantics-controls.json) | `1210f534344e91e6cce4971b3ec3e6213e6971b96c78a3c9e6a458f3be2db332` |
| [Source-axis controls](cc89-source-axis-controls.json) | `803eb3c10f0d6dfd14b38c30228c3953e41ade639cd7c50ea49e8803ddb0745a` |
| [Adapter repair](cc89-chain-phase-repair-cohort.json) | `f294acfcfd313aa9f47008da0acadc6a500e065a2a640fb98ef7caff4ee6cc80` |
| [CUDA refinement](cc89-chain-phase-repair-refinement.json) | `197fa72291ee0dd0e01afd452d0f4910c77fc4336a883c8174a3bafaedc7d94d` |

Durable workspaces: `.artifacts/cc89-tensor-semantics-controls/`,
`.artifacts/cc89-source-axis-controls/`, `.artifacts/cc89-chain-phase-repair/`,
and `.artifacts/cc89-chain-phase-repair-refinement/`.

## Limits and verification

The repair is selected on these diagnostic cases: two deposited sources and one
seed. It is not a held-out acceptance study. Additional sources/seeds, interface
controls, and independent review are required for broader promotion. No new
checkpoint, model training, geometry-policy relaxation, or MPS acceptance is
implied.

Focused adapter/context/refinement checks: **67 passed**. Full non-slow Python
suite: **1,154 passed, 7 skipped**, 31 slow tests deselected. Ruff passed for the
source tree, modified adapter, and new diagnostic tools/tests.
