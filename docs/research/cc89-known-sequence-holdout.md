# Expanded known-sequence cc89 / Homology structural holdout

Started: 2026-10-19. Status: all 154 planned jobs completed and independently
revalidated. Broad cc89 full-context acceptance is not demonstrated.

**Input-audit correction:** the subsequent
[representation audit](cc89-input-representation-audit.md) found an inappropriate
whole-complex neural axis and incorrect positional treatment of proxy fragments.
With explicit local/source-position input, the same 16 CDR mask/seed pairs pass
the unchanged refinement at 0.419–1.790 Å RMSD. The original results below remain
valid for the original full-context configuration, not a general verdict on
the checkpoint. The diagnostic recheck is not an independent new holdout.

## Completed findings

- cc89 raw geometry passes **16/60**.
- After the frozen refinement, **37/60** pass: **37/44** general-protein outcomes
  and **0/16** antibody-CDR outcomes. Twenty evaluated postprocessing results
  remain rejected and three stop at the chirality guard without a refined output.
- Median backbone RMSD among accepted cc89 results is **0.493 Å**. One accepted
  result, `general-9m9n-gap10` seed7, remains at **4.068 Å**: a geometry pass is
  not a guarantee of accurate reconstruction.
- MODELLER passes **30/30** under the existing unconstrained-comparator geometry
  policy; its median observed-backbone-aligned gap RMSD is **3.063 Å**. Its
  strict source-preservation result is 0/30 because the scaffold moves. These
  two endpoints must not be conflated.
- All four public Homology/Protenix controls pass strict validation: 28VW
  **0.687 Å**, 9V77 **0.187 Å**, 1MIM H-CDR1 **0.704 Å**, and 1BVL H-CDR1
  **0.471 Å**. Accepted constrained outputs preserve source atom records exactly
  and have zero detectable D-Cα.

The repaired pilot's 6/6 result does not generalize to this full-observed-model,
native-conditioning input regime. In particular, all new full-context CDR cases
fail cc89 validation. Earlier local-crop experiments use a different context
regime. Additional controlled context/position-feature studies are needed before
widening that capability; this holdout is not used to tune or replace its own
failed outcomes.

Detailed tables: [completed results](cc89-known-sequence-results.md).
Portable independently checked report:
[`cc89-known-sequence-results-v3.json`](cc89-known-sequence-results-v3.json),
SHA-256 `df373c745aa3906256ba5e5663d34580b791b7da659ae433a8206c638ca2e41d`.
Full local revalidation report SHA-256:
`1331555b7921bcbabd5faf3d6988b2d03f019769e0d6fd099a7b8f9e9473a187`.
Visual review: `gap_visual_review_cc89_holdout_v3/`, with one directory per
mask/seed, reference, gapped input, raw/postprocessing candidates, comparator,
public control where available, identity map, and explicit rejection status.

## Scientific task

Only coordinates of already-observed residues are removed and reconstructed.
Every target sequence is the unchanged observed sequence of a public X-ray
structure. No substitutions, designed sequences, novel ligands, or deletion
constructs are introduced. Withheld coordinates are evaluation-only.

This follow-up tests whether the
[cc89 chain-phase repair](cc89-chain-phase-root-cause.md) generalizes beyond its
two-source diagnostic pilot. It also exercises authoritative Homology template
plans and public workflow publication on the same masked inputs.

## Sources and masks

- General proteins: all 11 sources selected by the earlier clean-protein screen:
  28VW, 9WGM, 9M9N, 9V77, 9NDL, 9VNW, 9Q8P, 9Y1S, 26JK, 9S91, and 9M71.
  Each has one five-residue mask retained from the pre-existing source-only
  protocol and one new fixed-hash ten-residue CYS-free internal mask.
- Antibodies: a fixed 12-entry public pool was screened before inference.
  1MIM and 1BVL satisfy the observed-protein criteria and have paired ANARCI H
  and K/L domains. Ten exclusions remain in the source manifest; incompatible
  chemistry, incomplete atoms, internal native breaks, missing paired domains,
  and the 512-residue whole-model budget are not repaired or stripped to make
  those entries eligible.
- Four masks per antibody: IMGT H-CDR1 gap5, H-CDR3 gap10, L-CDR1 gap5,
  L-CDR3 gap5. Masks contain only known-coordinate, non-CYS residues with
  observed anchors. IMGT CDR1/2/3 ranges are 27–38, 56–65, and 105–117.
- Total: **30 masks on 13 deposited structures**, seeds **7 and 19** for cc89.
  All 30 native reference windows pass the unchanged structural validator.

Whole observed protein models are retained, including all partner chains.
Antibody sources may lack terminal tails in the deposition; those absent tails
are disclosed and are not generated. The benchmark target is explicitly the
complete *observed* sequence. There are no internal native breaks in admitted
sources. Only solvent water is excluded during preparation.

The 11 general sources were previously evaluated with Protenix. They were not
used to select the cc89 phase repair, but this is not a new independent Protenix
holdout. Training membership is not attested; the two historical antibody
structures may overlap pretraining. Source IDs and two seed replicates do not
establish independent sequence-family samples.

## Leakage and identity controls

The original template itself is masked before Homology materialization. A
template-plan row describes the unchanged target sequence and its exact missing
coordinate columns. An already-masked template, not a complete native template
with only a visual mask, is passed to both modeling paths.

Source, masked template, materialized mosaic, and evaluation reference are
compared by complete atom/residue identity. Mosaic numbering is an explicitly
recorded original-to-dense bijection, not an affine realignment or greedy
sequence placement. The evaluation reference reverses exactly to the original
source coordinates and sequence.

cc89 sampling and CUDA refinement workspaces contain **no reference PDB**.
Workers reject a workspace in which it is present. The parent attaches the
reference only after execution ends, for independent scoring. The public
Homology path receives only the masked template plan and unchanged target FASTA.

## Terminal OXT preflight correction

The first source-only preflight admitted 12/30 masks to cc89: the rest included
observed OXT, absent from the model's atom37 state. No model inference was run
under that preflight. It remains frozen as
[`cc89-known-sequence-holdout-v1.json`](cc89-known-sequence-holdout-v1.json).

The successor introduces the explicit research policy
`atom37-terminal-preservation-v1`:

- OXT is allowed only at an observed C terminus.
- OXT remains in the input, output, fixed-atom set, and refinement system.
- It is recorded as `preserved-only`, not as learned atom37 conditioning.
- Every canonical atom37 heavy atom of every selected protein chain remains
  represented; no protein residue or partner chain is cropped.
- Other unsupported atom types are not silently removed.
- Ordinary public diffusion scope rejects this research policy.

All 30 masks are admitted under this declared policy. Source coordinates,
sequences, masks, and source membership are unchanged from the first preflight.

## Frozen execution

| Stage | Planned outcomes | Protocol |
|---|---:|---|
| cc89 raw | 60 | fixed sequence; neutral-v1; native conditioning; 500 steps; scale1.2; churn200 |
| cc89 refinement | 60 | unchanged rigid v6, generated-only CUDA, no solvent |
| MODELLER Homology | 30 | same masked plan; one automodel; no loop refinement; md-level none |
| Public Protenix Homology controls | 4 | first general monomer and oligomer gap5, both H-CDR1 gap5 masks; seed7 |

Each seed is reported independently. There is no reference-based best-candidate
selection, retry through a different method, replacement of failures, or
automatic scope/backend fallback. MODELLER is an unconstrained comparator:
strict fixed-atom drift is reported, while its reconstruction-geometry status
uses the existing comparator policy. Accuracy is aligned only on common
observed backbone atoms; missing fixed atoms and any reduced RMSD atom scope
remain explicit. Different candidate budgets and refinement effort prohibit a
confirmatory noninferiority or speed claim from this run.

Per-job bounds: raw 600 s; refinement and MODELLER 1,800 s; public Protenix
outer worker 1,950 s with its internal runner bound at 1,800 s. CUDA stages are
sequential; the CPU-only MODELLER stage was run alongside raw generation.

Execution protocol v2 was a setup-only freeze. Before any inference, evaluation
was clarified to disclose MODELLER's observed-backbone alignment and possible
missing fixed atoms; execution v3 supersedes it. No outcome was used to change
the method or endpoints.

## Operational interruption

The interactive shell tool's 600-second outer limit interrupted the refinement
queue before `general-9v77-gap10`, seed19, had a completed archive. The raw
sampler output was already frozen. That unarchived refinement stage was resumed
on the same raw candidate, seed, code, and internal 1,800-second protocol bound.
No terminal archived outcome was replaced and no raw generation was repeated.
Subsequent refinement/public-control execution uses a persistent logged queue.

## Custody and reproducibility

- [Antibody source pool](known-sequence-antibody-sources-v1.json).
- [Successor input cohort](cc89-known-sequence-holdout-v2.json).
- [Execution protocol](cc89-known-sequence-execution-v3.json), SHA-256
  `01ce6385f100cac0578bc9fb5a94a4794bdb9211bf87d2d3e0beb4e9673f54ce`.
- Input workspace: `.artifacts/cc89-known-sequence-holdout-v2/`.
- Results: `.artifacts/cc89-known-sequence-results-v3/`.
- Continuation log: `.artifacts/cc89-known-sequence-continuation-v3.log`.
- Frozen source snapshot: `.artifacts/cc89-known-sequence-sources-v3/`;
  snapshot manifest SHA-256
  `4865f6f806263799e5341fed476f07eee0794a6d96de74dd77a3cb6c79467c30`.
  The snapshot contains the 25 pinned source/configuration files, never weights.

The read-only analyzer verifies protocol/job and raw-to-refined bindings,
recomputes independent geometry and reference measurements, checks exact
outside-gap atom records for constrained backends, and retains pending/failure
outcomes in denominators. Visual exports contain known reference, actual gapped
input, raw and postprocessing results, the MODELLER comparator, identity maps,
and per-case status. No complete result is emitted while jobs remain pending.

## Software verification and source snapshot

The full non-slow suite passed **1,160 tests**, with seven optional-dependency
skips, during execution. Subsequent audit/denominator/snapshot checks also pass.
Ruff, agent maps, CLI reference (Python 3.12), and GUI-spec validation pass.

Expanded mypy checking exposed two existing native-segment helper typing issues.
They were corrected only after all measurements and independent revalidation:
an explicit `ResidueIdentity | None` guard and a typed span list. That helper is
not used by this study's `atom37-terminal-preservation-v1` or public anchor-shell
policies. The exact measurement-time sources remain in the hash-verified
snapshot above. Replaying the original frozen protocol requires those sources;
the runner correctly refuses a changed source hash instead of silently mixing
producer revisions. No structural experiment was rerun for the typing cleanup.

Final post-cleanup verification: **1,162 passed, 7 skipped**, 31 slow tests
deselected. Focused holdout/context/scope/adapter checks passed **79/79**. Strict
core plus the changed context/scope modules passed mypy (**15 files**); Ruff,
agent maps, generated CLI/GUI checks, and `git diff --check` pass.
