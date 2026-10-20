# cc89 corrected-input paired comparison

Same-source diagnostic recheck; geometry PASS is not reference accuracy or independent acceptance.

## Primary outcome: geometry and source preservation

Acceptance checks generated/junction geometry, chirality, severe overlaps, and preservation of the observed structure. Reference RMSD is descriptive and is not an acceptance gate. MODELLER is a comparator, not a structural ground truth.

| Stage | Stratum | Original PASS | Corrected PASS | PASS→FAIL | FAIL→PASS | Corrected D-Cα | Fixed max displacement Å |
|---|---|---:|---:|---:|---:|---:|---:|
| raw | antibody-cdr | 0/16 | 5/16 | 0 | 5 | 0 | 0 |
| raw | general-protein | 16/44 | 28/44 | 4 | 16 | 0 | 0 |
| refine | antibody-cdr | 0/16 | 16/16 | 0 | 16 | 0 | 0 |
| refine | general-protein | 37/44 | 44/44 | 0 | 7 | 0 | 0 |

## Secondary outcome: reference-conformation agreement

Positive RMSD deltas mean worse agreement with the withheld reference. Missing original accuracy remains missing; guarded failures stay in the acceptance denominator. No seed is selected by reference accuracy.

| Stage | Stratum | Original PASS | Corrected PASS | PASS→FAIL | FAIL→PASS | Paired accuracy n | Original median Å¹ | Corrected median Å² | Median paired Δ Å | Δ >1 Å |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| raw | antibody-cdr | 0/16 | 5/16 | 0 | 5 | 16 | 13.990 | 1.266 | -13.167 | 0 |
| raw | general-protein | 16/44 | 28/44 | 4 | 16 | 44 | 0.758 | 0.390 | -0.054 | 1 |
| refine | antibody-cdr | 0/16 | 16/16 | 0 | 16 | 14 | 14.501 | 1.152 | -13.295 | 0 |
| refine | general-protein | 37/44 | 44/44 | 0 | 7 | 43 | 0.614 | 0.408 | 0.006 | 1 |

¹ Original median uses available paired accuracy only. ² Corrected median uses all corrected results. Median paired delta is calculated per matching case/seed, not by subtracting the two medians.

## Refined acceptance losses or reference RMSD increases above 1 Å

An RMSD increase alone is not a failed reconstruction; it can reflect a different geometrically valid conformation.

| Case | Seed | Transition | Original RMSD Å | Corrected RMSD Å | Δ Å |
|---|---:|---|---:|---:|---:|
| general-9m9n-gap10 | 19 | PASS->PASS | 0.499 | 4.541 | 4.042 |

Machine-readable evidence: `cc89-input-correction-comparison-v1.json`. Original and corrected audit SHA-256 digests are recorded in that report.
