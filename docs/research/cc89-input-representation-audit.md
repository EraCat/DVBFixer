# cc89 input representation and scope audit

Status: diagnostic input correction implemented and all 60 original mask/seed
combinations rechecked: 16 CDR and 44 general-protein outcomes. All 60 pass the
existing geometry/source-preservation gates after unchanged refinement. This is
not independent confirmatory acceptance.

## Corrected interpretation

The earlier full-input CDR median of 14.50 Å was not a valid general assessment
of cc89's ability to repair these loops. Our experimental adapter supplied an
entire 425/448-residue Fab/ASU as a mutable denoising axis and treated separate
serialization fragments as new positional chains. Correcting the model input
scope and preserving physical source sequence positions changes the same CDR
set from **0/16** to **16/16** after the unchanged CUDA refinement.

Sequences, original full PDBs, masks, anchors, seeds 7/19, checkpoint, native
sampling settings, geometry thresholds, and the generated-only refinement
algorithm are unchanged. References remain evaluation-only.

## Was the complex literally joined into one continuous peptide?

The answer is narrower than the earlier metadata-level assurance:

- The sampler packs chains on one tensor axis, but provides separate physical
  chain labels and residue-index breaks.
- `neutral-v1` explicitly zeros the denoiser's extra rotary chain-phase term.
  The denoiser therefore has no active independent chain-phase distinction;
  its chain separation is carried by residue-position gaps.
- We instrumented the **actual first attention layer's copied RoPE instance**,
  not the unused template `transformer.rope` attribute. Actual chain-boundary
  position jumps are **201**, not 1. RoPE consumes those supplied positions.
- The loaded cc89 network has **zero convolution layers** and patch size 1, so
  no convolution silently makes adjacent tensor rows peptide neighbors.

| Input | Actual engine chain lengths | Actual RoPE boundary jumps | Active chain-phase values |
|---|---|---|---|
| 1MIM H-CDR1 | 215, 210 | 201 | 0 |
| 1MIM L-CDR1 | 210, 215 | 201 | 0 |
| 1BVL H-CDR1 | 116, 108, 116, 108 | 201, 201, 201 | 0 |
| 1BVL L-CDR1 | 108, 116, 116, 108 | 201, 201, 201 | 0 |

Thus there is no demonstrated literal continuous-backbone concatenation here.
However, those gaps do not turn a monomer-trained checkpoint into a validated
whole-complex predictor. The original full-complex input was unsuitable for
this local-repair use. In local views there was also a genuine semantic error:
one physical chain split into proxy motif entities acquired artificial
200-position chain breaks instead of its original sequence separations.

## Data/coordinate bugs checked independently

Five native controls, including the suspect H/L inputs, reproduce their original
holdout candidates byte-for-byte under passive tensor capture. Checks establish:

- actual `gt_aatype` and sampled sequence equal the known target;
- upstream motif amino-acid types match the target positions;
- actual crop tensors equal the authoritative motif, with zero generated-region
  coordinates and source-coordinate error below 0.00001 Å after rigid conversion;
- independent upstream PDB featurization plus a deliberately perfect native
  oracle prediction round-trips through the adapter at **0.000 Å RMSD** in all
  full and local controls. These oracle tests use native coordinates explicitly
  and make zero neural forward calls; they are not restoration performance.

No shift of chains, amino-acid indexing, atom37 ordering, or Å/nm conversion was
found in these tests. They do not excuse the inappropriate sampling input scope.

## Final alignment is not the sole cause

We retain pre-restoration `x`, input motif coordinates/masks, actual sequences,
physical chain features, and first/second/last denoiser inputs. The same sampled
coordinates are decoded in three independently measured frames:

1. legacy alignment of predicted fixed atoms to the source;
2. inverse of the authoritative input-motif frame;
3. alignment using observed peptide anchors only.

| Native input | Legacy RMSD (Å) | Input-motif frame (Å) | Anchor frame (Å) |
|---|---:|---:|---:|
| 1MIM H-CDR1 | 11.623 | 10.947 | 6.898 |
| 1MIM L-CDR1 | 4.125 | 4.608 | 6.123 |
| 1BVL H-CDR1 | 31.694 | 33.647 | 14.272 |
| 1BVL L-CDR1 | 26.913 | 28.603 | 12.985 |

Alignment can amplify an error, but changing it alone does not rescue the loops.
Before any output alignment, internal C–N distances already reach **6.57 Å** in
1MIM H-CDR1 and **12.88 Å** in 1BVL H-CDR1. A rigid transform cannot create or
repair those internal bond errors. Hard projection and ODE sampling alone on
the full axis also do not restore all four CDR controls.

## Actual input correction

The whole gapped PDB remains intact. Only the neural axis is restricted using the
existing source-only selector: eight sequence flanks, complete-residue 6/10 Å
anchor shells, and two-residue sequence padding. Other observed atoms remain
explicitly `preserved-only` and remain fixed in the full refinement system.

`source_context_position_features` now separates physical chain/sequence features
from proxy motif serialization labels. It preserves source sequence separations
between discontiguous spans, and retains an explicit 200-position break between
different physical chains. No omitted span or different molecule is made into a
false peptide neighbor. Case-sensitive source identities remain distinct.

The adapter requires an explicit request option
`cc89_position_features=source-physical-v1` and matching invocation. It is
CUDA research-only, requires an explicit context plan and neutral phase, and
records a position-feature digest and numerical features in provenance/summary.
Legacy defaults and the deferred MPS profile are not silently changed. Full
context requests are not silently converted into local requests.

| Input, seed7 | Full axis | Local axis | Full/native RMSD (Å) | Local/proxy positions (Å) | Local/source positions (Å) |
|---|---:|---:|---:|---:|---:|
| 1MIM H-CDR1 | 425 | 64 | 11.623 | 2.055 | 1.348 |
| 1MIM L-CDR1 | 425 | 78 | 4.125 | 1.620 | 0.907 |
| 1BVL H-CDR1 | 448 | 66 | 31.694 | 1.320 | 1.272 |
| 1BVL L-CDR1 | 448 | 86 | 26.913 | 1.021 | 0.830 |

The largest improvement comes from correcting neural input scope. Correct
source positions then improve the local controls further. These are separate
effects; the entire improvement must not be attributed to one positional bit.

## Ordinary-adapter confirmation and complete CDR recheck

The ordinary adapter reproduces all five source-position controls byte-for-byte
at the raw-coordinate level. Five initial ordinary-adapter refinement checks
pass. All original eight CDR masks are then rechecked with both original seeds,
using the declared corrected input before inference:

- raw geometry: **5/16 PASS**;
- unchanged CUDA refinement: **16/16 PASS**, zero guarded failures;
- refined backbone RMSD: **0.419–1.790 Å**, median **1.152 Å**;
- fixed-heavy maximum displacement: **0 Å**;
- detectable D-Cα among final candidates: **0**.

OpenMM CUDA minimization remains recorded as nondeterministic; raw control-byte
identity must not be confused with guaranteed byte-identical refined outputs.
No candidate is chosen by reference RMSD. The original full-context 0/16 result
is preserved, and this same-source development recheck does not promote broad
CDR support without a new independent holdout.

## Complete general-protein recheck and primary acceptance outcome

The same frozen correction was applied to all 22 original general-protein masks,
with both original seeds, without selecting cases or candidates by reference RMSD.
Independent revalidation checks archive hashes, executed requests, source-position
digests, raw/refined lineage, geometry, and exact outside-gap atom records.

| Stratum | Original raw PASS | Corrected raw PASS | Original refined PASS | Corrected refined PASS |
|---|---:|---:|---:|---:|
| General protein | 16/44 | 28/44 | 37/44 | **44/44** |
| Antibody CDR | 0/16 | 5/16 | 0/16 | **16/16** |
| Total | 16/60 | 33/60 | 37/60 | **60/60** |

The primary outcome is valid generated/junction geometry, chirality, absence of
severe overlaps under the existing gates, and preservation of the observed
structure. Corrected refined candidates have **zero detectable D-Cα**, **zero
fixed-heavy displacement**, and byte-identical outside-gap atom records. There
are no guarded refinement failures. All 37 previously accepted general-protein
outcomes remain accepted; the other seven become accepted. Four original raw
passes become raw failures, but all four pass after the unchanged refinement:
the complete workflow, rather than raw sampling alone, is the evaluated repair.

Reference RMSD is a secondary conformation descriptor, not an acceptance gate.
The general-protein refined median is 0.408 Å; both 9M9N gap-10 candidates are
4.541–4.712 Å from the crystal reference while passing the geometry checks. This
does not by itself make them failed reconstructions. One paired refined RMSD
increases by more than 1 Å; that conformation difference remains explicitly
reported. MODELLER is a comparator, not a structural ground truth. Passing these
checks does not establish a unique or experimentally correct conformation.

The original full-context results are retained. These are corrected reruns of
the same development cases, not new independent sources or grounds for public
scope expansion. See the [paired comparison](cc89-input-correction-comparison.md)
for every acceptance transition and secondary reference-conformation changes.

## Evidence

- [Full-axis/frame controls](cc89-input-frame-audit-v1.json).
- [Local/source-feature controls](cc89-local-input-audit-v1.json).
- [Ordinary adapter confirmation inputs](cc89-source-input-confirmation-v1.json).
- [Original CDR-mask recheck inputs](cc89-cdr-source-recheck-v1.json).
- [Corrected CDR execution](cc89-cdr-source-execution-v1.json).
- [Independently checked CDR results](cc89-cdr-source-results-v1.json).
- [General-protein recheck inputs](cc89-general-source-recheck-v1.json).
- [Corrected general-protein execution](cc89-general-source-execution-v1.json).
- [Independently checked general-protein results](cc89-general-source-results-v1.json).
- [Paired comparison](cc89-input-correction-comparison.md) and
  [machine-readable transitions](cc89-input-correction-comparison-v1.json).
- Raw tensors and alternative-frame/oracle PDBs:
  `.artifacts/cc89-input-frame-audit-v1/` and
  `.artifacts/cc89-local-input-controls-v1/`.
- Actual first-attention RoPE captures:
  `.artifacts/cc89-neural-chain-positions-v2/report.json`.
- Corrected result structures: `gap_visual_review_cc89_cdr_corrected_v1/`.
- Corrected general-protein structures: `gap_visual_review_cc89_general_corrected_v1/`.

The first RoPE probe targeted the unused template module, failed its own
"probe fired" check, and was retained under `cc89-neural-chain-positions-v1`.
The successful v2 probe instruments `layers[0][0].rope`. That diagnostic setup
failure did not alter any holdout or correction result.

Verification: **1,165 passed, 7 skipped**, 31 slow tests deselected. Strict core
plus changed context typing passes mypy. Focused position-policy tests cover
source chain separation, retained omitted-residue gaps, explicit CUDA admission,
and rejection of unsupported policy combinations.
