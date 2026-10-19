# Clean protein expanded cohort: completed results

Every selected source is canonical-protein-only, coordinate-complete, without native gaps or missing heavy atoms. Waters are removed explicitly for solvent-free PDB preparation. No ligand/cofactor is stripped from an otherwise incompatible entry.

Full target and every protein partner are represented in the actual model features, <=512 residues. Source coordinates outside the declared mask remain unchanged. This is the full deposited model/ASU, not a generated biological assembly.

Screened pool: 200; selected sources: 11; planned masks: 55; source-native quality exclusions before inference: 5.

Attempted: 50; generated: 50; raw geometry accepted: 26; refined accepted: 49; execution/safety failures: 0. Failed attempts remain in the denominator. Raw counts include generated candidates whose later refinement failed.

| Deposited annotation overlap | Attempted | Sources | Relaxed PASS |
|---|---:|---:|---:|
| helix-and-sheet-overlap | 14 | 6 | 14 |
| helix-overlap | 19 | 8 | 19 |
| sheet-overlap | 17 | 8 | 16 |

| Gap length | Attempted | Refined PASS | Execution/safety failures |
|---|---:|---:|---:|
| 5 | 11 | 11 | 0 |
| 13 | 10 | 9 | 0 |
| 25 | 10 | 10 | 0 |
| 26 | 10 | 10 | 0 |
| 50 | 9 | 9 | 0 |

See RESULTS.md, index.csv, source_screening.csv and per-case case.json / RESULT.md. No reference RMSD ranking or acceptance criterion is used.

Run report SHA-256: `46da06cff54064f1352cd74db486822927b6fdd075198fde0fb65ea43801294e`.
