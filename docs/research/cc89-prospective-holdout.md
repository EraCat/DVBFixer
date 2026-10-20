# Prospective source-disjoint check of corrected cc89 input routing

Status: both prospective cohorts are complete and independently revalidated:
**24/24** outcomes on **four new source structures** pass after unchanged
refinement. Neither cohort changes the checkpoint, input policy, sampler,
refinement, or geometry thresholds established by the corrected development
recheck.

## Primary endpoint and fixed method

The primary endpoint is acceptance by the existing generated/junction geometry,
chirality, severe-overlap, and observed-source-preservation checks after the
unchanged generated-only CUDA refinement. Reference RMSD is descriptive only.
MODELLER is not treated as ground truth; no comparator is run in this follow-up.

- Known observed sequences and experimental coordinates only; no substitutions.
- Complete whole protein source models up to 512 residues; water is excluded.
  Nonwater heterogens, alternate conformers, incomplete heavy atoms, and internal
  native breaks are excluded during source preflight, before inference.
- Native terminal tails may be absent and are disclosed; they are not generated.
- Mask windows are internal, CYS-free, deterministically hash-ranked; CDR windows
  must lie inside ANARCI IMGT annotations. Both original seeds 7/19 are retained.
- Coordinates are removed before template materialization and conditioning.
  Reference files are absent from raw/refinement worker workspaces and are
  attached only after worker exit for evaluation.
- Source-only local context: eight flanks, the existing 6/10 Å anchor shells and
  two-residue padding; the full observed source remains preserved.
- Explicit `neutral-v1` chain phase and `source-physical-v1` positions, cc89
  checkpoint SHA-256
  `dfc9895b399ec4497bf6d646502168725f01dcbd55bc0b541fc3e3cc1f2f0483`,
  500 updates, step scale 1.2, churn 200, native conditioning, CUDA, no solvent.
- Every planned seed is reported separately; terminal failures are not replaced.
  No candidate or parameter is selected by reference agreement.

## Source selection and coverage

Historical source IDs are excluded using the manifests recorded in each source
screening protocol. General-protein targets also use the existing historical
sequence-overlap filter (maximum 0.30, with the disclosed 80-residue/80%-coverage
local-alignment rule). Antibodies exclude exact historical target sequences but
allow homologous frameworks. These are source-disjoint checks, not proof of
family independence or absence from checkpoint training.

The first screening used 2026-09-01 through 2026-10-19, RCSB 30%-identity grouped
representatives, a resolution limit of 2.5 Å, deterministic ranking, and bounded
downloads. Only **9WW8** qualified for general-protein masking. No separate Fab
source was admitted. A first materialization attempt mistakenly applied public
Protpardelle capability admission to the private research mode and stopped
before any neural call. Its incomplete local v1 directory is retained; v2 uses
the research mode's source/axis checks without weakening public admission.

The source selector then reserved ANARCI antibody domains for the CDR stratum
and stopped allowing discovery in the general search to suppress subsequent CDR
screening of the same entry. A regression test covers that routing. This changes
source screening, not the repair method. Before further inference, a separate
screening protocol widened general releases to 2026-01-01 through 2026-10-19 and
Fab releases to 2020-01-01 through 2026-10-19, with 95%-identity Fab grouping to
retain distinct variable-loop examples. Every exclusion is retained. Source
selection takes the first eligible sources under the fixed rank and count limits,
without replacing sources based on generated outcomes.

The expanded cohort contains **8EK6, 9Z0U, and 9LDN**: eight CDR masks and two
general masks, each with both seeds (**20 raw + 20 refinement jobs**). 9WW8 is
excluded from this second cohort. Source-native checks pass for all ten masks.

## First completed result: 9WW8

| Stage | Planned | Evaluated | Geometry/source-preservation PASS |
|---|---:|---:|---:|
| Raw | 4 | 4 | 3 |
| Refined | 4 | 4 | **4** |

One raw gap-5 seed is rejected for severe steric overlap; the unchanged refinement
resolves it. Independent revalidation confirms the frozen source-minus-mask
inputs, original sequence/coordinate mapping, executed request/archive digests,
physical-position provenance, raw-to-refined lineage, and exact outside-gap atom
records. No guarded failure occurs. Secondary refined backbone RMSD is
0.363–0.516 Å, median 0.450 Å. Four seed/mask outcomes are **one independent
source**, not four independent structures.

## Evidence and execution state

### Expanded cohort: complete results

| Source | Stratum | Raw PASS | Refined PASS |
|---|---|---:|---:|
| 8EK6 | Antibody CDR | 3/8 | **8/8** |
| 9Z0U | Antibody CDR | 2/8 | **8/8** |
| 9LDN | General protein | 0/4 | **4/4** |
| Expanded total | Three new sources | 5/20 | **20/20** |
| 9WW8, first cohort | General protein | 3/4 | **4/4** |
| Combined prospective total | Four new sources | 8/24 | **24/24** |

All 24 refined candidates have zero detectable D-Cα and byte-identical
outside-gap atom records; there are no guarded/operational failures or failed
final geometry gates. In the expanded raw cohort, 14 outcomes fail the severe
overlap check and five fail junction connectivity (some fail both). The unchanged
refinement recovers all 15 raw-rejected expanded outcomes. Raw diffusion alone is
not the accepted repair workflow.

The expanded secondary median backbone RMSD is 0.511 Å. The 9Z0U H-CDR3 gap-10
seed19 conformation remains 4.426 Å from the crystal reference and passes all
geometry/source-preservation gates; it is not discarded on RMSD grounds. These
results support transfer beyond the original development sources, while four
sources remain a bounded check rather than broad family-independent acceptance.

### Archived evidence

- [Initial source screening](cc89-prospective-sources-v1.json).
- [First completed inputs](cc89-prospective-holdout-v2.json),
  [execution](cc89-prospective-execution-v2.json), and
  [independent results](cc89-prospective-results-v2.json).
- [Expanded source screening](cc89-prospective-sources-v2.json).
- [Expanded inputs](cc89-prospective-holdout-v3.json) and
  [frozen execution](cc89-prospective-execution-v3.json), with
  [independently revalidated results](cc89-prospective-results-v3.json).
- First result structures: `gap_visual_review_cc89_prospective_v2/`.
- Expanded result structures: `gap_visual_review_cc89_prospective_v3/`.
- Expanded archives: `.artifacts/cc89-prospective-results-v3/`;
  live log: `.artifacts/cc89-prospective-continuation-v3.log`.
- Frozen producer snapshots: `.artifacts/cc89-prospective-producer-v2/` and
  `.artifacts/cc89-prospective-producer-v3/`; checkpoints are not copied.

Prospective outcomes remain separate from the corrected same-source development
recheck. Public scope and the deferred MPS profile are unchanged.

Verification after the new source-selector regression: **1,166 passed, 7 skipped**,
31 slow tests deselected; Ruff, agent-documentation maps, CLI reference, and
`git diff --check` pass.
