# Rich cc89 context, adaptive rounds, deletion windows, and longer gaps

## Scope and preregistration

[`reconstruction-frontiers-cohort.json`](reconstruction-frontiers-cohort.json)
freezes 26 cases / 31 outcomes before inference. The cases reuse tracked deposited
sources and explicitly declared earlier masked/mosaic inputs; no rejected candidate
is replaced. Geometry/chirality/fixed-coordinate gates are unchanged. CUDA sampling
is sequential on the pinned A100. Long-gap results below are raw, without refinement.

The manifest SHA-256 is
`af0b102e90c032214d97c6fd3f69c72da19f25335d64cb04a58dcbb5bdeac25e`.
Durable evidence is under `.artifacts/reconstruction-frontiers-cohort/` and
`.artifacts/reconstruction-frontiers-results/`. Checkpoints remain operator-provided.

## 2. Rich Protpardelle adapter

The private adapter now accepts joint gap-bearing chains and discontiguous source
spans. Each selected span becomes a separate real engine chain, with an explicit
bijective atom mapping back to case-sensitive source chains and insertion codes.
The engine receives separate chain lengths, chain indices, motif segments, and
fixed positions. It does not receive a fake continuous concatenated protein.

Joint outputs use one sampler invocation and one shared rigid-frame alignment;
they are not independently fitted per repaired chain. Native fixed-fit measurements
also use the common frame. Legacy independent-chain requests retain their earlier
behavior. Public MPS admission retains its audited boundaries pending MPS evidence.

Three frozen cases (joint 1EMV, discontiguous 1EMV, insertion-coded 7K8S) were run
with both native conditioning and per-step projection, 500 steps, seed 7, step scale
1.2, churn 200. All six executed with correct mappings, source preservation, and
declared CUDA evidence. All six failed existing geometry gates. Representation
support therefore does not imply reconstruction acceptance. MPS hardware is not
available on this Linux/A100 host; no MPS acceptance is claimed.

**Subsequent causal diagnosis (2026-10-19):** the extra rotary chain-phase term
is incompatible with this monomer-trained cc89 checkpoint in these cases.
Explicitly neutralizing only that denoiser feature reduces raw gap RMSD to
0.35–0.89 Å; unchanged generated-only CUDA refinement then accepts 6/6. All
original failures remain preserved. This is a same-seed diagnostic repair, not
broader scientific promotion. See the [chain-phase investigation](cc89-chain-phase-root-cause.md).

## 3. Adaptive context

`adaptive_context.py` implements bounded **between-round** expansion: sample once,
select additional complete source residues near the sampled generated backbone,
then rebuild features for a second complete sampling round. It never resizes a
running model's atom tensors or consults withheld/reference coordinates.

The context plan records sampled backbone coordinates, prior plan digest, source
candidate artifact/digest, and retained conditioning identities. Expansion is
monotonic; budget overflow rejects rather than evicts required neighbors. The
auditor re-derives each transition from the actual prior sampled PDB and verifies
the previous request/result. Optional fields are omitted for legacy static plans.
Public scope rejects trajectory-adaptive plans as research-only.

Two sources were compared with equal two-round static-repeat controls:

| Source | Static repeat | Adaptive | Selected fixed atoms, initial → adaptive |
|---|---|---|---:|
| 1EMV | accepted | accepted | 639 → 639 |
| 7K8S | accepted | rejected | 804 → 826 |

The unchanged 1EMV selection is a valid no-expansion control. The 7K8S result
demonstrates real additional context, but not improved geometry. Adaptive selection
is implemented and audited, not promoted as a default or universal improvement.

## 4. Deletion edit windows

Homology now exposes `--diffusion-edit-flanks 1..5`, requiring explicit
`--diffusion-regenerate-covered`. It chooses declared windows of 3, 5, 7, 9, or 11
residues for this frozen deletion, within the existing 3–12 range. CLI and GUI forward
the same option to Python; no scientific window logic is duplicated in Node/React.
The previous one-flank default remains unchanged. No outcome-based auto-expansion
or retry through different scientific windows is introduced.

| Flanks per side | Generated window | Independent result |
|---:|---:|---|
| 1 | 3 | rejected |
| 2 | 5 | rejected |
| 3 | 7 | accepted |
| 4 | 9 | accepted |
| 5 | 11 | accepted |

There is no solved experimental deletion reference, so only independent geometry
and exact scaffold preservation are evaluated. A fresh public CLI Homology run
with three flanks also passed and its verified bundle was durably archived at
`.artifacts/reconstruction-frontiers-results/public-deletion-flanks3-bundle/`.
Selected PDB SHA-256:
`b5e969a0d6615e41ac21dee9ed97f00e62b55e8fe7b0fe352808abd0477c9659`.

Example:

```bash
dvbfixer homology target.fasta --template-plan plan.json \
  --backend diffusion --diffusion-model protenix --diffusion-context full \
  --diffusion-regenerate-covered --diffusion-edit-flanks 3 -o target
```

## 5. Longer-gap strata

`gap_capabilities.py` separates accepted profile ranges from research input capacity.
The public accepted range remains 3–12; 13–25 and 26–50 have explicit research-only
capabilities. A private runner can evaluate those strata without bypassing or
weakening the public gate. More than 50 residues remains unsupported.

Two complete observed source sequences (1UBQ and 1EMV A, with 1EMV B retained as
protein context) were masked centrally at each declared length and run with seeds
7 and 19, full supported context, 200 Protenix steps, no refinement.

| Gap length | Accepted / completed | Median backbone RMSD, all candidates (Å) |
|---:|---:|---:|
| 13 | 3/4 | 0.32228 |
| 25 | 3/4 | 0.43933 |
| 26 | 4/4 | 0.44474 |
| 50 | 2/4 | 1.14648 |

All 1UBQ length-50 candidates failed, whereas both 1EMV length-50 candidates
passed. That is a source-dependent descriptive result, not evidence that 26–50
is easier than 13–25. These old structures may overlap model training; two source
structures and two seeds cannot support broad length-stratum promotion.

## Independent verification and remaining decisions

All 31 complete inventories were digest-verified and their final candidates
independently revalidated. Static/adaptive per-stage requests, previous sampled
artifact bindings, atom-axis evidence, callbacks, device/fallback, and zero final
fixed-source displacement were checked. Integer counts, warnings, and pass/fail
gates match exactly. Cross-environment floating measurements use an absolute
comparison tolerance of 1e-12 (a 3e-15 NumPy norm rounding difference was observed);
this does not alter any geometry acceptance threshold.

Verified analysis SHA-256:
`829c16f56f156a90a20a582c55d668722414f48004062d6b580c32cde2dd2f98`.

Remaining: MPS execution/causal acceptance, improved cc89 reconstruction geometry,
larger leakage-controlled independent cohorts, adaptive-policy calibration, and
separate evidence-backed public promotion of longer gaps. A purpose-trained model
is still a conditional research decision, not a consequence established by this
small audit. MODELLER remains default and WP3 policy expansion stays paused.

The subsequent chain-phase repair closes the catastrophic geometry failure for
the original six cc89 probes, but needs additional sources/seeds and independent
review before wider acceptance. MPS expansion is deferred until CUDA work is
complete.
