# Known-sequence cc89 / Homology holdout: completed results

All targets are unchanged observed sequences from public X-ray structures. Known coordinates were removed before template construction and model conditioning. Withheld reference files were absent from cc89 sampling and refinement workspaces.

30 masks on 13 deposited structures; cc89 seeds 7 and 19. Whole observed protein models and partners are retained. Terminal OXT is explicitly preserved-only outside atom37 conditioning.

## Overall outcomes

| Stage | Planned | Evaluated | Strict PASS | Operational/guarded statuses | Median backbone RMSD, all available (Å) |
|---|---:|---:|---:|---|---:|
| modeller | 30 | 30 | 0 | {} | 3.063 |
| protenix | 4 | 4 | 4 | {} | 0.579 |
| raw | 60 | 60 | 16 | {} | 1.157 |
| refine | 60 | 57 | 37 | {"guarded-chirality-rejection": 3} | 0.955 |

MODELLER's strict source-preservation status is separate from reconstruction geometry: **30/30** pass the existing unconstrained-comparator geometry policy. It is one automodel without loop refinement, versus two cc89 samples plus local refinement; this is a descriptive workflow comparison, not a confirmatory noninferiority or speed benchmark. MODELLER accuracy is rigidly aligned on common observed backbone atoms only.

## cc89 postprocessing by stratum

| Stratum | Planned | Strict PASS | Evaluated | Median RMSD, all available (Å) | Median RMSD, accepted (Å) | Maximum RMSD, accepted (Å) |
|---|---:|---:|---:|---:|---:|---:|
| antibody-cdr | 16 | 0 | 14 | 14.501 | undefined | undefined |
| general-protein | 44 | 37 | 43 | 0.614 | 0.493 | 4.068 |

## cc89 postprocessing by gap length

| Length | Planned | Strict PASS | Median RMSD, all available (Å) |
|---|---:|---:|---:|
| 10 | 26 | 18 | 1.180 |
| 5 | 34 | 19 | 0.499 |

## cc89 postprocessing by source

| PDB | Planned | Strict PASS | Statuses | Median RMSD, all available (Å) |
|---|---:|---:|---|---:|
| 1BVL | 8 | 0 | {"evaluated": 7, "guarded-chirality-rejection": 1} | 26.904 |
| 1MIM | 8 | 0 | {"evaluated": 7, "guarded-chirality-rejection": 1} | 9.276 |
| 26JK | 4 | 4 | {"evaluated": 4} | 0.356 |
| 28VW | 4 | 4 | {"evaluated": 4} | 0.914 |
| 9M71 | 4 | 4 | {"evaluated": 4} | 0.358 |
| 9M9N | 4 | 4 | {"evaluated": 4} | 0.474 |
| 9NDL | 4 | 1 | {"evaluated": 3, "guarded-chirality-rejection": 1} | 2.244 |
| 9Q8P | 4 | 4 | {"evaluated": 4} | 0.979 |
| 9S91 | 4 | 4 | {"evaluated": 4} | 0.503 |
| 9V77 | 4 | 0 | {"evaluated": 4} | 6.433 |
| 9VNW | 4 | 4 | {"evaluated": 4} | 0.446 |
| 9WGM | 4 | 4 | {"evaluated": 4} | 0.840 |
| 9Y1S | 4 | 4 | {"evaluated": 4} | 0.176 |

## Public Homology / Protenix controls

| Case | Status | Strict PASS | Backbone RMSD (Å) |
|---|---|---|---:|
| general-28vw-gap5 | evaluated | True | 0.687 |
| general-9v77-gap5 | evaluated | True | 0.187 |
| antibody-1mim-H-cdr1-gap5 | evaluated | True | 0.704 |
| antibody-1bvl-H-cdr1-gap5 | evaluated | True | 0.471 |

The study is a method holdout for the cc89 repair. The general sources were previously used in Protenix research; the two historical antibody structures may overlap pretraining. Two seeds are not independent source structures. Raw-retained inspection candidates remain failed postprocessing outcomes, not successful refinements. Guarded failures without a scored candidate remain in the denominator. No public capability is promoted by this report.

An external 600-second shell limit interrupted one unarchived refinement stage (general-9v77-gap10, seed19). It was resumed from the exact immutable raw archive under the unchanged 1,800-second per-job bound. Raw generation was not repeated and no terminal archived result was replaced.

Portable report: `cc89-known-sequence-results-v3.json`, SHA-256 `df373c745aa3906256ba5e5663d34580b791b7da659ae433a8206c638ca2e41d`. Full read-only revalidation report SHA-256: `1331555b7921bcbabd5faf3d6988b2d03f019769e0d6fd099a7b8f9e9473a187`.
