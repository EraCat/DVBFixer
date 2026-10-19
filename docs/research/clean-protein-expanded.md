# Expanded clean-protein, full-model reconstruction study

## Decision and scope

The next expansion tests **only clean canonical proteins**. Ligand/cofactor
support is a separate scientific/parameterization feature and is not implied by
this study. Entries containing incompatible chemistry are rejected whole; those
components are never removed to manufacture a protein-only example.

A new pool of 200 distinct RCSB entries was locked before source screening.
The query uses 2026-01-01 through 2026-10-15 releases, protein entities80–300,
resolution<=2.5 Å, nonpolymer entity count0, deposited polymer monomer count<=512,
and RCSB30%-identity grouped representatives. The first 200 distinct entries by a
fixed SHA ranking of the first400 representatives are retained. Metadata is only
a coarse filter: full CIF inspection also rejects branched glycans and other
polymers that the nonpolymer count alone would miss.

All candidates and exclusions stay in the screening report. The final maximum
is 20 eligible mutually nonredundant complexes before inference; this pool yields
**11** without relaxing chemical or coordinate completeness criteria. This more
than doubles the five supported protein sources in the previous intact recheck.

### Source requirements

- One deposited model, canonical L-protein polymer entities only; waters are
  allowed but removed explicitly in solvent-free PDB preparation.
- No ligands, ions, cofactors, glycans, nucleic acids, caps, noncanonical amino
  acids or nonstandard covalent links. Natural protein disulfides are allowed
  outside the non-CYS test masks.
- Every chain's declared polymer sequence is present in coordinates, including
  termini; every required heavy atom is present. No native gap, partial chain,
  alternate conformer or discarded observed segment is accepted.
- Complete deposited protein model/ASU<=512 residues, so the model receives
  **the full target chain and every partner chain**, not a local crop. Biological
  assemblies are not expanded beyond the deposited source model.
- All five planned lengths have a chemically eligible internal CYS-free window.
  There is no helix/sheet/loop exclusion; the deposited secondary-structure
  annotation overlap is recorded for every selected window. Unannotated is not
  assumed to mean loop.

## Source-only homology-screen correction before inference

The first source screen selected zero entries. Audit found that dividing all
global-alignment matches by the shorter protein length counted scattered
matches across a 1,980-residue reference as 38–49% identity to unrelated short
proteins. That is not a valid family-independence test. The failed screening
report remains in `.artifacts/clean-protein-expanded-cohort/screening.json`;
no model or reconstruction result was produced from it.

The same locked 200 sources were re-screened before inference with local
BLOSUM62 affine alignment (gap-open−10, extension−0.5). A homology exclusion
requires at least80 paired residues, at least80% coverage of the shorter chain,
and identity>30% **over all local alignment columns, including internal gaps**.
Aligned unknown residues count conservatively as possible matches. Exact shared
chains>=20 residues are also excluded. This detects intact shared domains
without classifying scattered motifs as a common protein family. Regression
tests cover both situations. The comparison includes prior screened target
sequences and all protein entities in the ten reviewed deposited sources.

This is an explicit source-only v2 screening revision, not tuning on model
outcomes. Entry IDs, pool ranking, chemistry and completeness requirements stay
unchanged. Training-set membership is not independently attested.

## Frozen cohort and preflight

The 11 selected sources are 28VW, 9WGM, 9M9N, 9V77, 9NDL, 9VNW, 9Q8P, 9Y1S,
26JK, 9S91 and 9M71. They span complete monomers, dimers and a trimer, with
141–470 total deposited protein residues.

There are **55 planned masks**, lengths5/13/25/26/50, seed7. A first fixed-hash
eligible window is chosen for each source/length. Five windows already fail the
unchanged local geometry gates in the native deposited structure: 9V77 lengths
13/25/26/50 (severe overlap) and 9Q8P length50 (amide planarity). They are retained
as source-quality exclusions, without trying another gap position. Thus **50
cases** are admitted for reconstruction.

The independent input audit verifies all55 full CIF masks, complete PDB chain
coverage and exact background coordinates. A separate CPU-only run of the real
pinned Protenix featurizer checks every one of the50 admitted cases. All required
source/generated atoms, including observed terminal atoms, are represented;
no target/partner residues or required atoms are omitted. No model or checkpoint
is loaded for that preflight. Every request has zero preserved-only atoms.

Frozen cohort: `clean-protein-expanded-cohort-v2.json`, SHA-256
`6701629456e3c071dec104fd537a333aa2c7be7d83576bba7841d45ea4a124e4`.
Pool manifest: `clean-protein-expanded-sources.json`, SHA-256
`134cd7f52270a8410f51107da3741910827ddd02e42de0200c3d04fb35336c11`.
Input/preflight evidence: `.artifacts/clean-protein-expanded-cohort-v2/`.

## Execution

The run uses the existing pinned Protenix/A100 checkpoint and worker, one cycle,
200 exact per-step reinjections, followed by the unchanged rigid v6 CUDA local
refinement. Only generated residues move; all observed background atoms remain
fixed. No solvent, dynamics, RMSD ranking or reference-coordinate optimization
is introduced. Geometry and chirality gates are unchanged. Failures and guarded
refinement exits remain in the denominator with their logs and raw artifacts.

`scripts/run_clean_protein_expanded.py` reuses the existing tested sequential
worker/custody/audit implementation, overriding only orchestration metadata to
record the new full-complex policy. The exact environment, input/preflight and
code digests are frozen in `clean-protein-expanded-run-protocol-v2.json` before
inference. Full-target conditioning differs from the earlier local-context
intact study; comparisons are whole-protocol comparisons, not an isolated
chemical-filter ablation.

Results: `.artifacts/clean-protein-expanded-results-v2/`.
Progress: `.artifacts/clean-protein-expanded-run-v2.log`.
Project-root visual review: `gap_visual_review_clean_v2/`.
The final exporter verifies PDB copies, writes per-case physical findings and
screening exclusions, and reports outcome strata by deposited helix/sheet
overlap. Public scope is not widened by this bounded study.
