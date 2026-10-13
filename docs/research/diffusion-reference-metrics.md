# Reference-Dependent Diffusion Benchmark Metrics

## Implemented WP4 Slice

`model/diffusion/reference_metrics.py` provides pure CPU measurements for:

- generated-region local distance agreement;
- anchor/end-generated junction-neighborhood local distance agreement;
- cross-chain local distance agreement for explicitly declared interfaces;
- residue-contact precision and recall for the same declared interfaces;
- explicit coverage, denominators, undefined reasons, and paired descriptive
  cluster-bootstrap comparisons.

`CandidateQuality` retains its existing RMSD, closure and validation fields and
adds a versioned `reference_metrics` record. Metrics do not change validation,
selection, model parameters, or public scientific scope. Energy, engine-native
confidence, MODELLER molpdf, geometry findings, RMSD and distance scores remain
separate named scales.

## Measurement Definition v1

The lDDT distance test uses thresholds **0.5, 1.0, 2.0 and 4.0 Å**, with strict
`distance error < threshold`. Eligible reference neighbors have distance strictly
below **15 Å** and belong to a different residue. No rigid superposition is used.
Each selected center atom is scored over its eligible reference neighbors, then
the **mean of per-atom lDDT scores** is reported. This is explicitly atom-averaged,
not a pooled pair-count-weighted global lDDT.

Correspondence uses exact `(chain, residue number, insertion code, atom name)`
identity. Chemically symmetric atoms are not reassigned to optimize the score.
The coordinate axis is observed reference heavy atoms using the existing protein
benchmark H-prefix naming convention. The current acceptance inputs are
heavy-atom-only protein structures; general metal/ligand atom classification is
not inferred by this measurement layer.

Generated centers are observed reference atoms in declared generated residues.
Junction centers include the explicit anchors and immediately adjacent generated
residues in reference file order, within the same case-sensitive chain. Numeric
residue-number ranges are not used, preserving insertion-code boundaries.
The remaining reference axis supplies distance partners, including fixed atoms.

Missing candidate centers or partners contribute **zero**, retaining their
reference comparisons in the denominator. A center without eligible reference
neighbors is unscored and counted separately; a completely empty denominator is
undefined, not 1.0. Missing experimental reference atoms are not invented. When
canonical generated identities are supplied, their missing reference count is
recorded. Unknown reference completeness is explicitly distinguished from a
known-complete reference.

Interface measurements require declared distinct PDB chain pairs. Chains `D/d`
and residues `82/82A/82a` remain distinct. Interface lDDT considers only reference
cross-chain pairs between those declared chains. Noninterface fixed regions do
not inflate its center average. Contacts are undirected residue pairs with at
least one observed-axis heavy-atom distance **≤5 Å**. Precision and recall use
their own denominators; zero predicted or reference contacts yield explicit
undefined ratios instead of fabricated perfect agreement.

Definitions and cutoffs are serialized with each record. Aggregation rejects
mixed policies, keeps accepted/all-candidate summaries separate, and records
undefined counts rather than treating missing measurements as zeros. A perfect
lDDT can coexist with a geometry failure or rigid-body drift: independent
validation and fixed-coordinate RMSD remain authoritative.

## Frozen 231-Case Follow-up

All replay bundles were digest-verified and independently revalidated again;
the scientific outcome remains **219 accepted / 12 rejected**. This analysis
loads the archived structures and performs no checkpoint inference.

| Scope | Defined cases | Median accepted generated lDDT | Median accepted junction lDDT |
|---|---:|---:|---:|
| All | 231 | 0.9064 | 0.9511 |
| Gap-5 | 128 | 0.9162 | 0.9540 |
| Gap-10 | 103 | 0.8885 | 0.9413 |

All 231 candidates contain the required observed reference atom identities.
Thirteen cases have experimental references missing some canonical generated
side-chain atoms; this is explicitly reported, not silently interpreted as a
complete all-heavy comparison. Interfaces were not declared for this one-chain
cohort, so all interface metrics have `interface-not-declared` rather than scores.

The frozen MODELLER comparator is measured from its digest-verified original
two-model pool and summary. Existing validated ordinal identity normalization
is reused when needed. Case scores are medians of that fixed pool; models are
not reselected after viewing lDDT. Paired differences use both-valid defined
cases and resample independence groups (10,000 samples, seed 0).

| Both-valid scope | Pairs | Median Δ generated lDDT (replay − MODELLER) | 95% cluster-bootstrap CI |
|---|---:|---:|---:|
| All | 159 | +0.4260 | +0.3999 to +0.4471 |
| Gap-5 | 103 | +0.4022 | +0.3475 to +0.4283 |
| Gap-10 | 56 | +0.4854 | +0.4302 to +0.5115 |

The all-case junction delta is +0.2806 (95% CI +0.2514 to +0.2992).
These are **descriptive follow-up endpoints**, not a new preregistered selection
rule. Seventy-two defined pairs are excluded from this both-valid quality
comparison due to a scientific rejection; all 231 remain in the primary
pass/reject denominator.

Analysis schema 2 is saved separately from the frozen schema-1 replay analysis:
`.artifacts/protenix-public-231/reference-metrics-analysis.json`, SHA-256
`2d94ab632ec96469721c6f8ae43d3b631d7b438999395c867fe238cd93ad47c1`.

```bash
PYTHONPATH=src python scripts/analyze_protenix_public_cohort.py \
  .artifacts/protenix-public-231 .artifacts/diffusion-confirmatory-cohort-500-v5 \
  --work-parent /tmp/opencode --compare-modeller \
  --output .artifacts/protenix-public-231/reference-metrics-analysis.json
```

For a declared interface cohort, repeat `--interface-chain-pair H:L` as needed;
unsupported/missing reference chains produce explicit undefined measurements.

## Verification and Remaining Conditional Metrics

Tests exercise exact threshold boundaries, rigid-transform invariance,
atom-versus-pair weighting, missing-atom penalties, undefined denominators,
case-sensitive interfaces/insertion codes, aggregation and paired exclusions.
An independent Biotite `aggregation="atom"` cross-check passed in the separately
provisioned backend environment; Biotite is not added to core dependencies.

Verification: full non-slow core suite **1050 passed, 7 skipped, 31 deselected**.
Six skips require GROMACS and one optional cross-check requires Biotite; that
cross-check passed when run in the provisioned backend environment (**33 focused
tests passed**). Ruff, strict mypy and whitespace checks passed.

GDT-HA and TM-score are intentionally not reported for these five/ten-residue
local loops. Their conditional WP4 implementation still requires declared
meaningful large-region/domain cases and a reviewed global-alignment engine.
The context/interface acceptance cohort and causal conditioning studies remain
WP5–WP8 work; having interface metrics does not establish interface reconstruction
or context consumption.
