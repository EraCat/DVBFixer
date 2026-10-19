# A100 raw failures and paired local-relaxation protocol

**Input-scope correction:** [visual chain-coverage auditing](a100-input-truncation-audit.md)
confirms substantial pre-gap truncation in experimental inputs. Fixed-environment
invariance below applies to the retained fragments, not to all deposited chains.

The next [accuracy, bounded-flank and prospective-validation study](relaxation-followup.md)
separates geometric acceptance from reference accuracy and tests whether small
declared flank motion improves the remaining cases.

## Raw failure analysis (completed before relaxation)

This study follows the frozen [prospective A100 calibration](cuda-calibration.md)
and its peptide-junction audit. All 92 outcomes are retained, including accepted
raw candidates and repeated seed/context arms. There are seven source structures,
not 92 independent biological examples. Reference coordinates are used only for
offline evaluation.

`scripts/analyze_a100_failures.py` verifies each raw completion inventory and
recomputes current validation, then records individual bond-length, angle,
planarity, Ramachandran, side-chain and steric findings with exact residue/atom
identities. The corresponding reference geometry is checked separately. Detailed
evidence is `.artifacts/a100-prospective-calibration/failure-analysis.json`, SHA-256
`6494fb34837e0029885e4f9da2905fe6bc4d94ed982d2c9f2405eb912c6d92b2`.
The parent independent analysis SHA-256 is
`6082551450ace7eb4278fa7dca9bada1479ae0186ce392b763e2e4d6b7f35142`.

**33/92 pass; 59/92 fail.** Failure gates overlap:

| Failure gate | Outcomes | Physical interpretation |
|---|---:|---|
| Junction C–N outside 1.20–1.45 Å | 48 | Compressed or extended fixed/generated boundary bond; not necessarily a disconnected chain |
| Severe steric overlap ≥0.90 Å | 25 | Generated atoms overlap each other or the fixed environment |
| Gross bond-length error | 11 | Topology-backed bond deviates by >50% from its nominal length |
| Gross bond-angle error | 10 | Backbone/peptide angle beyond the broad ERROR envelope |
| Non-planar amide | 5 | Peptide omega outside accepted cis/trans planarity envelopes |
| Gross Ramachandran outlier | 1 | Invalid local backbone conformation under the current broad policy |

Thirty outcomes fail **only** junction length, eleven fail **only** steric overlap,
and eighteen fail multiple gates. There are no D-Cα, fixed-coordinate drift,
atom-identity/completeness, or internal-generated-backbone-break failures.

### Localization and examples

- All 12 individual gross bond-length findings, all 12 angle findings, and all
  five non-planar-amide findings span **fixed and generated atoms**, localizing
  these errors to the boundaries rather than the middle of a generated chain.
- Of 72 individual severe-clash findings, 62 involve fixed/generated atom pairs
  and ten are generated/generated. The counts include correlated repeated arms.
- No detailed candidate finding is exactly identical to a corresponding
  reference finding. This is an exact-record control, not proof that every
  pre-existing imperfection is absent from the source.
- `25VF`, gap 5 / seed 19: one junction is 3.222 Å; the C–N–CA angle is 76.5°.
- `25II`, gap 50 / seed 7: one junction is 5.350 Å and its amide omega is −87.8°.
  Seed 19 has a 5.104 Å junction and a LEU/LEU contact with 1.404 Å vdW overlap.
- `21TW`, gap 50 / seed 19: GLU23 has phi −11.8°, psi −94.3°, in addition to
  boundary/steric failures.
- `22VH`, gap 25 / seed 7: junction 1.45068 Å, a genuinely borderline result
  relative to a 1.45 Å gate and fixed-column PDB precision. It is not representative
  of the larger failures: only three outcomes exceed a junction boundary by at
  most 0.01 Å.

The separate junction audit found 63/184 boundary C–N distances outside the
acceptance interval versus only 5/1512 internal generated C–N bonds. Reference
junctions are 1.3199–1.3483 Å. This is consistent with incomplete **closure and
packing at fixed/generated interfaces** in unrefined output; it does not prove a
specific causal defect in the denoiser or reinjection algorithm. Exact source
reinjection preserves anchors but imposes no C–N closure constraint.

### Dependence on gap length and source

| Gap length | Outcomes | Pass | Junction | Steric | Length | Angle | Planarity | Rama |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 (three arms) | 42 | 21 | 21 | 1 | 3 | 3 | 0 | 0 |
| 13 | 14 | 10 | 2 | 2 | 0 | 0 | 0 | 0 |
| 25 | 12 | 1 | 5 | 7 | 0 | 0 | 0 | 0 |
| 26 | 12 | 0 | 10 | 7 | 2 | 3 | 2 | 0 |
| 50 | 12 | 1 | 10 | 8 | 6 | 4 | 3 | 1 |

| Source | Pass/outcomes | Junction failures | Steric failures | Interpretation |
|---|---:|---:|---:|---|
| 12NP | 9/14 | 0 | 5 | Packing, not closure, limits these outcomes |
| 13EE | 6/14 | 7 | 4 | Compression/closure and long-gap packing |
| 21CH | 7/8 | 0 | 1 | Shorter eligible masks mostly pass; no 25–50 masks |
| 21TW | 0/14 | 14 | 6 | Systematic boundary difficulty; longer masks have multiple defects |
| 22VH | 8/14 | 5 | 1 | Several junction-only failures, including a borderline case |
| 25II | 2/14 | 12 | 2 | Closure dominates; severe long-gap boundary deformation |
| 25VF | 1/14 | 10 | 6 | Closure plus packing; even gap 5 can fail badly |

Geometry acceptance alone does not imply correct reference conformation. No
threshold has been tuned using these outcomes. The relaxation comparison must
report geometry rescue **and** reference quality changes, including regressions
of the 33 raw-passing candidates.

## Paired local-relaxation protocol

Freeze all 92 raw outcomes, their completion-marker digests, the implementation
digests and environment **before any relaxation**. No regeneration, replacement,
mask selection or dropping raw-passing candidates is permitted. Use separate
workspaces and output archives; raw inference evidence stays immutable.

Use the existing `dvbfixer-openmm-boundary-refinement-v6` implementation via
`refine_runner_result`, with OpenMM CUDA, no solvent and no dynamics:

- Only generated residues move. All atoms outside those residues, including
  both flanking anchors and the partner protein fragment, have zero mass.
  Final publication changes only generated heavy-atom coordinate columns.
- AMBER force-field files are the existing `BOUNDARY_REFINEMENT_FORCEFIELD`;
  temporary heavy-atom completion and hydrogen placement occur only in the
  force-field working topology. Hydrogens are not published to the heavy-only
  scientific candidate.
- Generated intra-residue heavy bonds are constrained at their input lengths;
  inter-residue C–N bonds, including boundary bonds, are not constrained and can
  relax. This is an existing boundary-refinement policy, not unrestricted repair
  of arbitrary intra-residue geometry.
- Existing chirality protection, trans-amide and peptide-angle forces remain
  enabled. This is restrained geometry refinement, not plain force-field
  minimization alone; the trans-amide bias is a protocol limitation for real cis
  peptides.
- Maximum 500 iterations for length ≤5, otherwise 250; tolerance 10 kJ/mol/nm.
  Up to eight seeded perturbed restart minimizations use the existing v6
  geometry-error/energy selection, with perturbation 0.25 Å for short gaps and
  0.75 Å otherwise (backbone perturbations use one quarter of those scales).
  No reference coordinates inform optimization or restart selection.
- No automatic device fallback. A refinement failure retains the raw candidate
  with an explicit postprocessing failure. Timeout or execution failure is
  archived and stays in the denominator; no successful-output-only summary.
- Revalidate with unchanged gates. Report paired fail→pass, pass→fail, gate
  transitions, fixed-coordinate invariance, per-length/source/split results,
  reference RMSD before/after, and refinement time. CUDA minimization is not
  claimed bitwise deterministic.

The first frozen protocol, `a100-local-relaxation-cohort.json`, encountered
`CUDA_ERROR_UNSUPPORTED_PTX_VERSION` in the existing conda OpenMM environment
before minimization. Its aborted execution diagnostics remain in
`.artifacts/a100-local-relaxation`; they are environment errors, not geometry
results. The host driver is 535.104.05 (CUDA 12.2).

A separate `test/a100-relax-env` overlays OpenMM 8.6.1 plus `openmm-cuda-12`
8.6.1 and CUDA-12.2-compatible packages onto the core scientific environment:
NVRTC/runtime/NVCC/NVJitLink 12.2.140, CUPTI 12.2.142, cuFFT 11.0.8.103.
The core environment is unchanged. An actual CUDA force-kernel preflight now
runs before freezing and before executing a queue, rather than merely checking
that a platform named CUDA is registered.

The corrected protocol was separately frozen as
`a100-local-relaxation-cuda12-cohort.json`, SHA-256
`ab94cdb9c1086e1156d3b6f8625ddd266624b146f1f646ba55a258b58763a756`.
It records the parent failed-protocol digest, all 92 original outcomes, code
hashes, and exact environment package versions. Scientific settings and cohort
membership are unchanged; failed-environment archives have not been overwritten.

The runner is `scripts/run_a100_relaxation.py`; current durable outputs go to
`.artifacts/a100-local-relaxation-cuda12`, with native work in `/tmp/opencode`.
`scripts/analyze_a100_relaxation.py` independently revalidates both members of
each pair, recomputes reference quality, verifies raw/result inventories and
checks that every outside atom record is unchanged. Execution errors stay in
the overall denominator but are distinguished from geometric pass→fail changes.
Research-only long-gap scope and existing public limits remain in force.

All 92 corrected-environment outcomes have now completed with no execution
errors or refinement-postprocessing failures and have passed the independent
paired evidence audit. Raw and relaxed artifacts remain separately addressable.

Commands for the corrected run and offline audit:

```bash
PYTHONPATH=src test/a100-relax-env/bin/python scripts/run_a100_relaxation.py run \
  --manifest docs/research/a100-local-relaxation-cuda12-cohort.json \
  --raw .artifacts/a100-prospective-calibration \
  --output .artifacts/a100-local-relaxation-cuda12 --work-parent /tmp/opencode

PYTHONPATH=src test/a100-relax-env/bin/python scripts/analyze_a100_relaxation.py \
  --manifest docs/research/a100-local-relaxation-cuda12-cohort.json \
  --outcomes .artifacts/a100-local-relaxation-cuda12 \
  --output .artifacts/a100-local-relaxation-cuda12/analysis.json
```

Use `--allow-incomplete` with a separate `partial-analysis.json` output for an
explicitly incomplete audit while the queue runs.

## Completed paired results

The final independently revalidated report is
`.artifacts/a100-local-relaxation-cuda12/analysis.json`, SHA-256
`9bc2ca1041bf699776a8b5ada77f9d13b9a61620604b93281ab0e4a903e6a2d7`.
The offline audit reports `complete: true`, no pending members, and zero
execution errors. This is an independently computed check, not external
scientific review.

**Acceptance improves from 33/92 to 86/92 (35.9% to 93.5%).** There are 53
fail→pass pairs, 33 pass→pass pairs, zero pass→fail pairs and six fail→fail pairs.
Fixed heavy-atom RMSD/displacement and detectable D-Cα are zero in every output;
outside atom records are byte-identical to their raw counterparts.

| Length | Raw accepted | Relaxed accepted | Validation split, raw → relaxed | Median backbone RMSD raw → relaxed (Å), all outcomes |
|---|---:|---:|---:|---:|
| 5, all three context arms | 21/42 | 42/42 | 6/18 → 18/18 | 0.6893 → 0.4374 |
| 13 | 10/14 | 14/14 | 4/6 → 6/6 | 0.5137 → 0.4815 |
| 25 | 1/12 | 12/12 | 0/6 → 6/6 | 0.7764 → 0.7527 |
| 26 | 0/12 | 10/12 | 0/6 → 4/6 | 1.0828 → 1.1335 |
| 50 | 1/12 | 8/12 | 0/6 → 2/6 | 1.8749 → 1.8500 |

Calibration sources improve from 23/50 to 50/50; validation sources improve from
10/42 to 36/42. Per-source relaxed acceptance is 14/14 for 12NP, 13EE, 22VH and
25VF; 8/8 for 21CH; 12/14 for 25II; and 10/14 for 21TW. These are correlated
candidate counts across only seven source structures. All short-gap arms pass
14/14 after refinement, so this result does not establish an adaptive-context
advantage.

### Gate transitions

| Gate | Raw failures | Relaxed failures | Resolved | Newly introduced |
|---|---:|---:|---:|---:|
| Junction C–N | 48 | 4 | 44 | 0 |
| Severe overlap | 25 | 4 | 21 | 0 |
| Gross bond length | 11 | 4 | 7 | 0 |
| Gross bond angle | 10 | 4 | 6 | 0 |
| Amide planarity | 5 | 5 | 1 | 1 |
| Ramachandran | 1 | 1 | 1 | 1 |
| Internal backbone break | 0 | 3 | 0 | 3 |
| Side-chain chi1/chi2 | 0 | 1 | 0 | 1 |

Thus zero overall pass→fail does **not** mean every local metric improved.
The three newly introduced internal breaks occur in already-rejected 21TW
long-gap candidates; the minimizer can redistribute strain from an impossible
boundary/packing arrangement into the generated chain. This is a plausible
interpretation of the paired coordinates, not a proof of a unique optimization
mechanism. These outputs remain rejected, without weakening gates or rerunning
them under tuned settings.

### Six remaining failures

All six belong to the validation split and have large reference backbone RMSD
(about 8–13 Å) even after refinement. Long-range conformation is therefore also
wrong; improving a local C–N distance alone would not establish reconstruction
accuracy.

| Candidate | Remaining physical defects |
|---|---|
| 25II / length 50 / seed 7 | Junctions now pass (maximum 1.386 Å), but N–CA–C is 79.4°, C–N–CA is 64.3°, and amide omega is 74.4°. No severe clash remains. |
| 25II / length 50 / seed 19 | One junction remains 3.474 Å, with several severely distorted angles and one severe clash. |
| 21TW / length 26 / seed 7 | Junction maximum 1.520 Å; internal C–N 2.245 Å; 12 severe overlaps; multiple angle/amide errors and a new Ramachandran outlier. |
| 21TW / length 26 / seed 19 | Junction maximum 1.802 Å; internal C–N 2.776 Å; 26 severe overlaps; angle and amide errors. |
| 21TW / length 50 / seed 7 | Closure and packing gates now pass, but one boundary amide remains non-planar (omega 109.7°). Reference backbone RMSD is still 9.081 Å. |
| 21TW / length 50 / seed 19 | Junction maximum 1.583 Å; internal C–N 2.160 Å; 30 severe overlaps; non-planar amides and a new ASN chi1/chi2 outlier. |

Exact residue/atom identities, angle values and clash partners are retained in
each rejected pair's `relaxed_findings` in the final report.

### Reference accuracy, cost, and conclusion

The overall median backbone RMSD is 0.7111 Å raw versus 0.5707 Å relaxed. The
median **paired** change is only −0.01545 Å; it is not the difference of those
two medians. Twenty of 92 candidates worsen by more than 0.1 Å, including 13
of the 33 originally passing candidates. The worst geometry-accepted relaxed
candidate has backbone RMSD 5.355 Å (`13EE`, length 50, seed 19). Scientific
geometry acceptance must therefore remain distinct from native-like accuracy.

Median refinement wall time is 7.20 seconds per candidate (maximum 92.05 seconds;
sum of refinement calls 1002.33 seconds). This excludes inference and independent
audit time. No inference was repeated.

**Interpretation:** most of the raw failure rate in this run is removable local
geometry/packing error, not evidence that every raw-failing reconstruction is
unusable after refinement. Conversely, the existing bounded local refinement
does not reliably recover severely wrong long-gap conformations and can create
new local defects in an already bad candidate. This completed seven-source study
does not by itself widen public gap-length scope or establish broad accuracy.
