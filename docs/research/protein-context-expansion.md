# Expanded context and mosaic-first Homology studies

## Implementation slice

The shared source-only selector now represents multiple gap-bearing chains and
multiple sequence windows. Protenix consumes the selected entities in **one**
sampler invocation, with a common frame and per-update fixed projection. This
implements joint sampling rather than independently repositioning repaired chains.
The four atom roles and source/selection/mapping digests retain their schema-4
semantics; absent optional fields retain legacy serialization.

Protpardelle's previous 12 Å crop selection has moved into the shared module as
an explicitly named compatibility policy. Its legacy behavior is preserved.
Explicit plans use the same complete-residue, fail-closed selector as Protenix.
The adapter currently accepts one gap-bearing chain and one contiguous span per
represented source chain. Joint chains, discontiguous source-chain entities,
more than 26 engine chains, and atoms outside its audited canonical-heavy mask
fail before public runner launch. This is an adapter acceptance boundary, not a
claim that the upstream model fundamentally cannot represent richer inputs.

Homology now builds exact requests from authoritative coverage instead of
re-aligning a FASTA against the sparse mosaic. This preserves repeated-sequence
placements and supports multiple uncovered spans and multichain requests.
`--diffusion-regenerate-covered` explicitly regenerates bounded substitution and
deletion-boundary windows, with separate original template ownership for regenerated
covered residues. Windows retain the existing 3–12 residue admission range.
Existing disulfide-linked residues cannot be removed by covered regeneration;
noncanonical template chemistry is rejected before edits. Original mosaic inputs
are preserved and request/input destinations cannot overwrite existing files.

The GUI exposes the context and covered-edit controls; MODELLER remains default.
Protenix multichain/multi-gap requests require an explicit context plan. No context,
engine, device, or MODELLER fallback is introduced.

## Frozen studies

### Expanded protein-context cohort

[`protein-context-expansion-cohort.json`](protein-context-expansion-cohort.json)
was frozen before expanded inference. It declares six masks, 15 source/seed/control
variants, and 24 outcome-bearing runs:

- 1UBQ low/high nonlocal-contact masks, with seeds 7 and 19;
- 1TIM A/B and 1A3N A/B interface pairs;
- 7K8S H/L with an explicitly insertion-coded generated window;
- 1EMV A/B with a five-residue gap in each chain, sampled jointly;
- three negative controls translating the selected partner by +80 Å, in both
  normalized input and reference, without changing the target mask.

The first-seed arms are same-chain spatial conditioning and local partner
conditioning plus localized Reference-platform refinement. Every source has a
second-seed refined arm. Negative controls use both first-seed arms.

The analyzer independently validates **raw and refined** candidates and computes
raw context-only contrasts, so refinement cannot masquerade as a context effect.
It verifies negative-control raw byte equality, reports reference lDDT/contact
metrics, fixed-environment-aligned gap RMSD, centroid displacement, anchor-vector
angle, minimum generated interchain distance, and descriptive pairs below 1.2 Å.
It also reruns current-policy two-seed ranking for matched masks/context plans.
These measurements do not add or relax scientific gates.

The five independent deposited source digests must not be confused with 15
independent structures. Contact counts are not SASA measurements; the insertion
window is not automatically a CDR label. Selected chain pairs are declared
subcomplexes, not complete biological assemblies. Heterogens, including 1A3N
hemes, are excluded explicitly. Training membership is unknown. The study is
descriptive and does not establish broad interface promotion.

### Shell/budget sensitivity

[`protein-context-sensitivity-cohort.json`](protein-context-sensitivity-cohort.json)
uses all six base masks with the already-declared 6 Å shell and 64-residue budget
policies. It was derived after the main expansion began but before any sensitivity
inference; that timing is recorded explicitly. Source masks and geometry thresholds
are unchanged. Unsupported budgets remain pre-inference outcomes rather than
silently trimmed context or replacement cases.

### Protpardelle causal audit

[`protpardelle-context-audit-cohort.json`](protpardelle-context-audit-cohort.json)
freezes a cc89 CUDA partner-on/off audit of the original 1EMV pilot mask, seed 7,
200 steps, and per-step projection. At forward call 100, the probe repeats a
same-state/features/sigma baseline and translates only represented partner XYZ
by +25 Å; generated response is measured before projection and RNG state restored.
The frozen gate requires repeat delta zero and response at least 0.0001 Å.
Source revision, patched module, config, checkpoint, and frozen inputs are verified.
CUDA research evidence does not by itself establish MPS acceptance.

### Public Homology integration and MODELLER comparison

[`context-homology-cohort.json`](context-homology-cohort.json) freezes five plans:

1. Two jointly reconstructed chains, with logical VH/VL mapped to distinct H/L.
2. Two uncovered spans in one chain, with a fixed partner.
3. An opt-in covered substitution.
4. An opt-in deletion-boundary repair.
5. Two rigidly displaced templates fitted into one reference frame and mosaicked.

All use the same 1EMV source frame, seed 7, and full supported protein context.
Each public diffusion run is compared with one MODELLER candidate from the
identical target and template plan (`md-level none`, no loop refinement).
MODELLER is an **unconstrained** comparator: full validation and scaffold drift
are reported without claiming a diffusion sampler trace. Mutant/deletion cases
have no solved experimental reference and receive no invented reference-quality
score. VH/VL here is an engineering mapping test on a non-antibody source.

## Execution and custody

Execution is sequential on the A100. Native public work/publication uses
`/tmp/opencode`; durable archives live under:

- `.artifacts/protein-context-expansion-cohort/`
- `.artifacts/protein-context-expansion-acceptance/`
- `.artifacts/protein-context-sensitivity-acceptance/`
- `.artifacts/protpardelle-context-audit-cohort/`
- `.artifacts/context-homology-cohort/`
- `.artifacts/context-homology-acceptance/`

Frozen input and outcome inventories are digest-bound. Geometry rejection is
retained without replacement; missing outcomes cannot be treated as passing.
Large structures can spend substantially longer in Reference-platform hydrogen
placement/refinement than in CUDA sampling. Existing parameters and execution
timeouts remain explicit, rather than being changed after viewing geometry.

## Completed context results

All 24 expansion outcomes completed and were independently revalidated, including
their raw candidates. Every non-template trace recorded 200 callbacks, zero
projection error, and zero final fixed-heavy displacement.

| Study arm | Completed candidates | Independently accepted | Unsupported before inference | Median backbone RMSD (Å), including rejects |
|---|---:|---:|---:|---:|
| Same-chain spatial, expansion | 9 | 3 | 0 | 0.38394 |
| Local partner plus refinement, expansion | 15 | 15 | 0 | 0.33742 |
| Direct 6 Å shell, sensitivity | 6 | 2 | 0 | 0.74992 |
| 64-residue budget, sensitivity | 2 | 1 | 4 | 0.58957 |

Acceptance rates in the first two rows do not isolate context from refinement.
The independently scored raw contrast improves backbone RMSD by 0.23149 Å for
1TIM and 0.08401 Å for the insertion-coded 7K8S window, but worsens 1A3N by
0.11476 Å. Thus context use does not guarantee improved reconstruction.
All three distant negative controls have byte-identical raw outputs between
same-chain and local-partner arms. Monomer controls and the two-gap-chain joint
case also have identical raw outputs when the declared selected environment is
unchanged. The joint case is nevertheless sampled in one real multichain invocation.

Two-seed current-policy ranking selects the reference-better valid candidate in
five of six mask families. The 1EMV joint family selects seed 7 at 0.77932 Å instead
of the seed-19 oracle at 0.68395 Å (regret 0.09537 Å). This is descriptive ranking
evidence, not a calibrated ranking guarantee.

The cc89 CUDA causal gate passed: partner intervention response RMSD 2.38128 Å,
maximum 3.35034 Å, baseline repeat difference zero, and 200 zero-error callbacks.
Both raw candidates failed independent geometry. Partner-on backbone RMSD is
11.98188 Å versus 0.63096 Å partner-off. Full-partner representation and a causal
response therefore do **not** justify geometry promotion; the existing accepted
MPS/native-conditioning settings are not replaced by this 200-step CUDA research
configuration.

| Frozen manifest / verified analysis | SHA-256 |
|---|---|
| Expansion manifest | `06dfe00e30dc478ffe2d8c10caa75cd3b72596ebcefa05e07940719ae8f721bb` |
| Expansion analysis | `403ad99b8b9b6ca5dc465e514f24929a36b543c8c709ba880fd440be944dc8ac` |
| Sensitivity manifest | `bccede3d18d292eb719c7cc22cf25c50636846916f6929a6f9f027162191ae37` |
| Sensitivity analysis | `305b112b33beacf98c238aa62fd3c80610b45afd1f10f9dda364bda629b61ece` |
| cc89 manifest | `a0dad45378a4fba18c348df361a4a5974b53e904f60ae68f8b9442cf22238b91` |
| cc89 analysis | `777236ab4872e19ac839728849980bc50fc691e6d779e9e0ef9023db6ccc4403` |
| Homology manifest | `987c8f591eca4ba29b53aedaeaca79c03f671dd3a94370a5b9b7bbd3ace430c0` |

The Homology comparator retains MODELLER's original result and separately maps
its globally numbered segments to mosaic per-chain numbering only after exact
full-target sequence verification. The mapping is disclosed; coordinates and the
original model are unchanged. Failure diagnostics are retained before private
workspace cleanup. A short TER newline issue in the derived comparator copy was
fixed and regression-tested; derived metrics were recomputed from retained originals
without new scientific samples. Earlier derived outcomes are preserved in the archive.

All five public Homology scenarios completed and their bundles were independently
revalidated against the exact frozen requests:

| Scenario | Public result |
|---|---|
| Joint logical VH/VL → H/L | accepted |
| Two uncovered spans | accepted |
| Covered substitution | accepted |
| Deletion-boundary window | rejected: `junction-peptide-connectivity` |
| Fitted multiple-template mosaic | accepted |

The deletion rejection remains a terminal inspection bundle; it is not promoted
to a downstream prepared model. No experimental mutant/deletion reference score
is invented. The completed Homology report SHA-256 is
`45a584643e35a156a1cdc59765bda8db1472d2354cab81752b098e8d7b7fe3db`.

Verification: 1,068 fast Python tests passed (seven optional-dependency skips);
the subsequently added comparator/TER regression and context/Homology focused
checks passed 26/26. Strict core plus context/Homology mypy passed, as did Ruff,
GUI typecheck/lint and all 243 GUI tests, generated CLI/GUI checks, agent maps,
version synchronization, and fixture checksums.

## Remaining scientific and adapter work

- A larger independently reviewed interface cohort, including genuinely
  solvent-accessibility-defined strata, additional CDRs, and training-leakage
  controls is still needed for broad promotion. Five source structures are not
  sufficient confirmatory evidence.
- Protpardelle joint/discontiguous adapters and MPS causal acceptance remain
  pending. The failed full-partner CUDA geometry audit motivates controlled
  crop/projection/sampling-configuration studies; it does not by itself prove
  that a purpose-trained replacement model is necessary.
- Trajectory-adaptive context selection is not implemented.
- Covered deletion windows are mechanically supported and fail closed, but
  the frozen deletion scenario did not meet the current closure gate. Broader
  bounded edit-window acceptance needs a separately frozen study.
- Independent scientific review cannot be replaced by the implementing agent's
  current-policy revalidation.
