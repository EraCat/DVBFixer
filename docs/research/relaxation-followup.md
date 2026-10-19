# Relaxation follow-up: accuracy, bounded flanks, and new-source validation

**Input-scope correction after visual review:** the
[chain-truncation audit](a100-input-truncation-audit.md) confirms that the
materializer discarded observed chain segments and other chains before creating
test gaps. All results below concern those cropped fragments/subcomplexes, not
preservation or reconstruction in the complete deposited environment.

## Completed accuracy and six-failure audit

This follows [the 92-outcome local-relaxation study](a100-failure-and-relaxation.md).
The original 92 outcomes include repeated context arms. For further development,
use one predefined arm per mask/seed (`static-local` for length 5, `full-raw`
otherwise): **64 mask/seed cases, 32 masks, seven source structures**. These are
not 64 independent biological examples. All previously inspected cases are now
development data; their old calibration/validation labels do not constitute a
new untouched holdout.

`scripts/analyze_relaxed_accuracy.py` separates geometry acceptance from
withheld-reference accuracy. In the 64-case development set, 58 pass geometry:

| Reference backbone RMSD, geometry-accepted only | Cases |
|---|---:|
| ≤1 Å | 44 |
| >1 to 2 Å | 8 |
| >2 to 4 Å | 5 |
| >4 Å | 1 |

These are descriptive bins, not new acceptance gates. The median accepted-case
RMSD is 0.628 Å and median generated-region lDDT is 0.870. The worst accepted
case is `13EE`, length 50, seed 19: fixed-frame RMSD 5.355 Å, generated lDDT
0.728. Even an independent rigid fit of the generated backbone leaves 3.083 Å
RMSD. Whole-interface scores can be dominated by unchanged protein atoms and
must not stand in for gap-specific accuracy.

The six rejected cases remain substantially wrong even after fitting their
generated backbone independently of the surrounding protein:

| Case | Fixed-frame RMSD (Å) | Gap-only fitted RMSD (Å) |
|---|---:|---:|
| 25II / 50 / seed 7 | 8.304 | 4.622 |
| 25II / 50 / seed 19 | 8.443 | 4.620 |
| 21TW / 26 / seed 7 | 8.064 | 6.118 |
| 21TW / 26 / seed 19 | 12.648 | 7.886 |
| 21TW / 50 / seed 7 | 9.081 | 5.710 |
| 21TW / 50 / seed 19 | 10.587 | 7.276 |

Thus their problem is not only a rigid translation/rotation or a slightly
incorrect junction. Intrinsic conformation is also wrong. The physical
bond/angle/amide/clash findings are retained in the earlier study and in
`.artifacts/a100-local-relaxation-cuda12/accuracy-audit.json`. Small flank motion
is a testable closure intervention, not a presumed remedy for a wrong fold.
Accuracy-audit SHA-256:
`89bce7b76178e17e5882ead459d16ca87baaf389f9d67787067dddaccddaff5d`.

## Frozen bounded-flank development experiment

Compare the existing rigid v6 results against the same raw 64 mask/seed cases
with **one complete immediate anchor residue on each side** allowed to move.
Do not regenerate gaps, select only rejected cases, change geometry thresholds,
or look at new-source outcomes to choose the method.

The private adapter in `scripts/research_flank_refinement.py` loads an isolated
v6 module and extends its mobile atom/residue mask to those two anchors. A
private ForceField subclass adds positional harmonic restraints (10,000
kJ/mol/nm²), with a 1,000,000 kJ/mol/nm² outer wall starting at 0.25 Å.
The independently checked maximum permitted flank displacement is **0.30 Å**;
all other observed atoms must stay fixed. Existing iteration/restart settings,
chirality, amide and angle forces are retained. The expanded mask also expands
the local restart-scoring scope and changes RNG draw allocation; the experiment
compares two complete refinement protocols, not one isolated force term.

**Public fixed-coordinate invariants are not relaxed.** Every output has two
separately labeled checks:

- original strict validation under the original fixed-atom mask;
- research bounded-flank validation, excluding only the declared flank atoms
  from the fixed mask and enforcing the explicit 0.30 Å displacement cap.

Other geometry and identity gates are unchanged. No modified sampler trace or
public RunnerResult claims that the moving anchors remained fixed. Research
PDBs and reports are separate artifacts.

The selection rule, frozen before scientific comparison results, chooses the
bounded-flank protocol only if it accepts **more** cases, loses **none** of the
rigid-passing controls, has no execution errors, and its median paired original-
gap RMSD change is no worse than +0.10 Å. Otherwise choose rigid refinement.

An initial adapter invocation failed during OpenMM argument introspection before
minimization. Its diagnostics and first manifest are retained. The corrected
adapter preserves the wrapped ForceField method signature; a real TIP3P
createSystem regression verifies the fix. The corrected frozen manifest is
`bounded-flank-comparison-v2-cohort.json`, SHA-256
`01f5e1c9d5ede1082ab737bf27af888b53b80c99687fd6afad372d245353bdf0`.
Artifacts: `.artifacts/bounded-flank-comparison-v2`.

### Completed development comparison

All 64 cases completed without execution errors and passed the independent
coordinate/quality revalidation. Final analysis SHA-256:
`a7d14e727fe6963fc520eb39fa40928d695d1cdc5d870aab09ef2cb255245b3f`.

- Rigid: **58/64** accepted; bounded-flank: **57/64** research-accepted.
- No rejected rigid case is rescued. One rigid-passing control fails the flank
  displacement cap: `13EE`, length 50, seed 19, moves an anchor atom 0.302736 Å.
  This is a cap-only regression, not a newly broken bond; the preregistered cap
  has not been loosened to accept it.
- Ignoring only the displacement cap, the geometry-passing count is 58/64,
  still no improvement. Six proposals exceed the flank cap; the maximum
  displacement is 0.659598 Å in an already-rejected 25II long-gap case. The soft
  wall is not a mathematical hard constraint; cap-violating proposals are
  explicitly rejected rather than clipped or relabeled as bounded.
- Median paired original-gap backbone RMSD change versus rigid is **+0.01729 Å**.
  All six original failures remain rejected, consistent with their much larger
  conformational errors.
- Under the original public fixed-atom mask, **0/64** flank proposals pass the
  full strict validation. Their research acceptance must not be substituted for
  public fixed-coordinate acceptance.

The frozen rule therefore selects **rigid v6 refinement**. This is a negative
result for this one-flank, strongly restrained protocol, not a general proof
that every possible flexible-boundary method is ineffective.

## New-source holdout frozen before inference

The new source window is **2026-09-01 through 2026-10-15**, disjoint from the
previous January–August source window. Selection locks the first 24 distinct
entries in fixed SHA rank among the first 100 RCSB 30%-identity grouped
representatives, with the same 80–250 residue and ≤2.5 Å resolution query.
All 24 previous entry IDs are excluded. The initial sequence screen compares
the 22 fully canonical sequences among those 24 sources, not only the seven
eligible development structures. The two development sequences containing X
receive a separate sensitivity audit described below. No excluded entry is
replaced.

The initial simple match/mismatch alignment screen was excessively conservative
for short sequences (23/24 exclusions); it is archived without inference. Before
any new inference, the same locked 24 entities and metadata were re-screened
using protein-appropriate global BLOSUM62 alignment, gap-open −10, extension
−0.5. The >30% identity-over-shorter-full-sequence exclusion threshold is
unchanged; this is an explicit pre-inference screening revision, not a response
to model outcomes. Exact sequences and computed overlaps are in
`relaxation-holdout-sources-blosum62.json`. Seven entries pass metadata/sequence
screening; three pass the unchanged complete-fragment selection.

The final structural cohort is `relaxation-holdout-cohort.json`:
**23IT, 29HO, 24BT**, one source-only hash-selected mask per length 5/13/25/26/50,
seed 7, **15 outcomes**, all explicitly validation-only. CIF/source and derived
input digests are retained. These are protein fragments/subcomplexes, not
complete assemblies. The original 24 screened entries remain documented.
Release time and sequence exclusion do not independently attest absence from
training, and three eligible sources cannot support broad production acceptance.

`scripts/audit_relaxation_holdout.py` additionally checks the three final sources
against **all 24** development sequences, including 23EO and 23EF (one unknown X
each). All measured overlaps remain ≤30%, even when adding one possible match
for each unknown residue on the computed alignment. This sensitivity is not a
formal bound over every possible alignment. Pairwise identity among the three
holdout sequences is also ≤30%. The audit does not inspect model outputs and
changes no cohort member; its durable report is
`.artifacts/relaxation-holdout-cohort/independence-audit.json`.
Independence-audit SHA-256:
`29926aefe515957f3718aa8813ed6ef0f01cf5ff6e4a50fa70ca803f0035cfca`.

`scripts/run_relaxation_followup.py` waits for the development comparison,
independently audits it, and writes the chosen protocol/digests **before**
running any new-source inference. It then runs pinned Protenix/CUDA with 200
reinjection updates, audits raw results, applies the selected solvent-free
refinement once, and independently recomputes final validation and accuracy.
All errors remain in the denominator. Holdout outcomes never select parameters
or trigger a fallback to the other method. Public length scope stays unchanged.

Selection was frozen as `relaxation-holdout-selected-protocol.json`, SHA-256
`a2a12261010e8de4fbcf28188f046e89d32716fb1440a79908e26837834bc721`,
**before new-source inference began**. The input cohort SHA-256 is
`26daf56de5ac8fbd0f05b4d9e97d1809fb2010b2c02cec0c3642668d104f2ca8`.
New-source execution and final audit are tracked in
`.artifacts/prospective-relaxation-holdout.log` and the
`.artifacts/prospective-relaxation-holdout/` archive.

## Completed prospective holdout results

All 15 new-source outcomes completed. No inference or refinement execution error
occurred, no case was replaced, and the method was not retuned. The selected
rigid protocol improves geometry acceptance from **6/15 to 12/15**: six rescues,
six preserved passes, zero pass→fail changes and three remaining rejections.

| Gap length | Raw accepted | Rigid-refined accepted | Median backbone RMSD, all three cases, raw → refined (Å) |
|---|---:|---:|---:|
| 5 | 0/3 | 3/3 | 0.7666 → 0.4249 |
| 13 | 2/3 | 3/3 | 1.3143 → 1.3216 |
| 25 | 0/3 | 1/3 | 4.7431 → 4.7431 |
| 26 | 2/3 | 3/3 | 6.2239 → 6.3098 |
| 50 | 2/3 | 2/3 | 5.8881 → 5.9395 |

Per-source acceptance is 23IT 1/5→3/5, 29HO 2/5→4/5, and 24BT 3/5→5/5.
Junction failures decrease 7→2, severe-overlap failures 6→2, gross bond-length
failures 4→2, and angle failures 5→3. One internal backbone break is introduced
in an already-rejected candidate; planarity and Ramachandran errors remain in
the most deformed cases. Every selected output retains zero fixed-heavy-atom
RMSD/displacement and zero detectable D-Cα.

### Remaining holdout rejections

| Case | Remaining defects | Reference backbone RMSD (Å) |
|---|---|---:|
| 23IT / 25 / seed 7 | Boundary C–N 2.075 and 2.580 Å; an internal C–N is 2.060 Å; eight gross angle errors, two non-planar amides, one Ramachandran outlier and three severe overlaps | 24.325 |
| 23IT / 50 / seed 7 | Junctions/packing pass, but one N–CA–C angle is 141.0° and an amide omega is 122.0° | 18.928 |
| 29HO / 25 / seed 7 | One boundary C–N is 2.127 Å, O–C–N is 41.1°, and one severe overlap remains | 4.743 |

`scripts/analyze_followup_holdout.py` independently checks the full original and
refined RunnerResult/sampler traces, source inventories, frozen custody,
unchanged validation decisions, reference-quality metrics and per-residue
findings. It confirms the direct-coordinate evaluation in the execution report.

### Geometry versus reference reconstruction

Among the **12 geometry-accepted** new-source candidates:

- seven have backbone RMSD ≤1 Å;
- one is >1–2 Å;
- one is >2–4 Å;
- **three exceed 4 Å**: 23IT/26 at 6.345 Å, 29HO/26 at 6.310 Å, and 29HO/50 at
  5.940 Å.

The all-case median RMSD changes from 1.6079 to 1.3216 Å, but the length-specific
table shows no corresponding reference-accuracy improvement for several long
strata. Local relaxation reproducibly improves geometry; it does not guarantee
reconstruction of the withheld reference conformation. The new cohort exposes
this distinction more clearly than the original seven-source development set.
Reference differences do not alone prove that every alternative conformation is
biologically impossible.

### Evidence and decision

- Final execution/coordinate audit:
  `.artifacts/prospective-relaxation-holdout/analysis.json`, SHA-256
  `61716399a41ee77118ea1440f441023b63e5219d65e3606e03c669f58f85b383`.
- Independent full-trace and failure-detail audit:
  `.artifacts/prospective-relaxation-holdout/final-audit.json`, SHA-256
  `ed0ea2431393b134c6a4403f521e7885db4cb2eb096fccf79906f9e94007c255`.
- Both reports are complete. Model output, raw failures and rejected refined
  candidates remain archived with digests. There was no MPS run or solvent box.

**Retain rigid refinement and the current public scope.** This study finds no
benefit from the tested bounded-flank variant. It confirms local geometry rescue
on disjoint inputs, but does not establish reliable native-like reconstruction
for 25–50-residue gaps. Three new sources and one generation seed are too small
for broad acceptance. A next scientific study would need candidate diversity and
reference-independent selection, followed by a larger untouched validation set;
loosening geometry gates would not solve the observed accuracy limitation.
