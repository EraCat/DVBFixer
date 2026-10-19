# Prospective A100 calibration and cc89 controls

For detailed raw failure localization and the subsequent paired refinement
study, see [A100 failures and local relaxation](a100-failure-and-relaxation.md).

## Protocol and scope

The prospective source lock is
[`cuda-calibration-sources.json`](cuda-calibration-sources.json): 24 RCSB
structures released in 2026-01-01 through 2026-08-31, selected from
30%-identity-grouped representatives by deterministic SHA ranking. Original
CIF files and metadata are archived in `.artifacts/cuda-calibration-sources`.
This is a temporal holdout, not an independently verified exclusion from model
training. Sequence grouping does not prove statistical independence.

Strict complete-chain screening yielded one eligible source. Its separate
[`cuda-calibration-cohort.json`](cuda-calibration-cohort.json) protocol was frozen
but has not been run. The subsequent fragment protocol was also frozen before
inference, without replacing excluded sources:
[`cuda-fragment-calibration-cohort.json`](cuda-fragment-calibration-cohort.json).
It selects a continuous complete target run of at least 70 residues (capped at
250), and, when eligible, a nearby canonical partner run of at least 12 residues
(capped at 120). CIF normalization uses the shared input boundary. Seven of the
original 24 sources remain eligible: 64 case/seed requests and 92 arm outcomes.
These are fragments/subcomplexes, not complete asymmetric units or biological
assemblies. Screening exclusions remain in the denominator.

The frozen source-level calibration/validation split, seeds 7/19, masks, and
parameters must remain unchanged after inspecting outcomes. Gap lengths are
5, 13, 25, 26, and 50. Short-gap arms compare one-round static local context with
two-round monotonic and contact-gated context. The gate preserves a passing first
request; otherwise it requires two new contact residues, each supported by two
sampled backbone atoms within 4 Å. Only source and sampled coordinates inform
adaptation; reference coordinates are reserved for offline scoring.

Each round uses Protenix on CUDA, 200 denoising updates, per-step reinjection,
and no geometry refinement. Adaptive arms consume an extra round, including
when the gate preserves the request; they are not compute-matched to static.
Reported per-outcome resources describe the last round, not total adaptive cost.
Long gaps and adaptive routing remain research-only.

## Offline evidence audit

`scripts/analyze_a100_calibration.py` checks frozen inputs, completed-output
inventories, source-context identity, current validation, CUDA/projection traces,
and sampled-only adaptive routing, then recomputes reference-dependent quality.
It reports calibration and validation strata separately, including source counts.
Candidate Wilson intervals are descriptive, not source-cluster confidence
intervals. Revalidation by this script is not external scientific review.

The full analysis fails on missing outcomes. An explicitly partial audit can run
while inference continues; pending members are retained and `complete` is false:

```bash
PYTHONPATH=src python scripts/analyze_a100_calibration.py \
  --manifest docs/research/cuda-fragment-calibration-cohort.json \
  --cohort .artifacts/cuda-fragment-calibration-cohort \
  --outcomes .artifacts/a100-prospective-calibration \
  --output .artifacts/a100-prospective-calibration/partial-analysis.json \
  --allow-incomplete
```

For final analysis omit `--allow-incomplete` and write `analysis.json`. All 92
outcomes have now completed and passed the offline evidence audit. Final results
are in `.artifacts/a100-prospective-calibration/analysis.json`; the automatic
audit log is `final-analysis.log` in the same directory.

| Length / arm | Geometry accepted, all | Geometry accepted, validation split |
|---|---:|---:|
| 5 / static-local | 7/14 | 2/6 |
| 5 / adaptive-monotonic | 7/14 | 2/6 |
| 5 / adaptive-contact-gated | 7/14 | 2/6 |
| 13 / full-raw | 10/14 | 4/6 |
| 25 / full-raw | 1/12 | 0/6 |
| 26 / full-raw | 0/12 | 0/6 |
| 50 / full-raw | 1/12 | 0/6 |

Adaptive context does not improve acceptance in this cohort. The contact gate
does not expand any request: seven preserve a passing first candidate and seven
lack sufficient new supported contacts. Geometry acceptance is not evidence of
reference-structure accuracy. Seven sources and correlated seeds/arms are
insufficient for broad public promotion.

## Peptide-junction validation audit

The high junction-failure frequency was audited separately using
`scripts/audit_peptide_junctions.py`. It reads the raw PDB coordinate columns in
angstroms using a separate parser and `math.dist`, checks reference-file adjacency
for the exact case-sensitive `(chain, resid, icode)` pairs, compares production
measurements and recorded decisions, and verifies archived digests. It also
checks the internal generated-backbone distances and recorded maximum.

**No measurement, unit, residue-pairing, or gate-decision mismatch was found**
in the 92 outcomes. All 184 reference junctions are within the current gate:
minimum 1.319901 Å, median 1.331703 Å, maximum 1.348292 Å.

The existing `junction-peptide-connectivity` name is broader than a literal
chain-break detector: it enforces an inclusive **1.20–1.45 Å C(i)–N(i+1)
bond-length acceptance interval**, rejecting compression as well as extension.
The internal `generated-backbone-break` check uses a separate, coarser upper
cutoff of 1.80 Å. The former is a frozen operational geometry policy, not a
residue-class-specific statistical outlier score. The checks have different
purposes; neither is a chemical-bond-order determination from distance alone.

Of 48 outcomes failing the junction gate:

- 12 have at least one junction longer than 1.80 Å;
- 15 have at least one junction shorter than 1.20 Å;
- one outcome belongs to both groups;
- the remaining 22 have extension beyond 1.45 Å but no junction below 1.20 Å or
  above 1.80 Å;
- only two outcomes exceed a threshold by at most 0.005 Å, and three by at most
  0.01 Å; one borderline example is 1.45068 Å (`22vh-gap25-seed7`), for which
  fixed-column coordinate precision matters;
- 30 fail only this gate, while the others also fail other existing gates.

Across individual junctions, 17/184 are below 1.20 Å, 46/184 above 1.45 Å, and
14/184 above 1.80 Å. The candidate range is 1.044706–5.349505 Å. In contrast,
only 5/1512 **internal generated** C–N bonds exceed 1.45 Å, none are shorter
than 1.20 Å, and none exceed 1.80 Å. All 1512 corresponding reference internal
bonds meet the 1.20–1.45 Å interval. Distortion is therefore concentrated at the
fixed/generated boundaries, consistent with a closure problem in raw,
unrefined candidates; the audit does not establish the exact sampler cause.
Counts include repeated seeds/arms and are not independent observations.

Descriptive sensitivity, keeping the lower bound and all other gates unchanged:

| Hypothetical C–N upper bound (Å) | Junction-passing outcomes | Passing all existing gates under that hypothetical bound |
|---|---:|---:|
| 1.45 (current) | 44/92 | 33/92 |
| 1.50 | 48/92 | 37/92 |
| 1.60 | 53/92 | 40/92 |
| 1.80 | 66/92 | 52/92 |

These are **not new acceptance results**. Raising the upper bound to 1.50 Å
would rescue only four outcomes, so a small change cannot explain most failures.
Conversely, using 1.80 Å as a finished-geometry acceptance threshold would admit
substantially stretched amide bonds (the nominal length is about 1.33 Å).
No scientific threshold or published outcome was changed by this audit.

Reproduce:

```bash
PYTHONPATH=src python scripts/audit_peptide_junctions.py \
  --manifest docs/research/cuda-fragment-calibration-cohort.json \
  --outcomes .artifacts/a100-prospective-calibration \
  --output .artifacts/a100-prospective-calibration/peptide-junction-audit.json
```

Audit SHA-256:
`eea261e84df6cb0fab2d5b8ce3ac2a5edfb5ac11be72d357279e986ff7ee9e58`.

## Completed cc89 CUDA controls

[`cc89-cuda-controls.json`](cc89-cuda-controls.json) freezes three earlier rich
context cases, five settings, seed 7 and 500 steps. All 15 outputs have been
revalidated from archived coordinates with current policy. The audit checks
frozen input/output digests, sampler settings, CUDA traces and fixed-coordinate
preservation; it does not rely on the runner's pass/fail report alone.

| Control | Accepted | Median pre-restoration fixed-context RMSD (Å) |
|---|---:|---:|
| Native baseline, churn 200 / step scale 1.2 | 0/3 | 10.63576 |
| Native, churn 0 / step scale 1.0 | 0/3 | 10.63678 |
| Projected, churn 0 / step scale 1.0 | 0/3 | 0.00000144 |
| Backbone-only projected conditioning | 0/3 | 0.00000144 |
| Projected with replacement guidance | 0/3 | 0.00000144 |

Every output fails junction connectivity, generated-backbone continuity, bond
lengths, bond angles, amide planarity, severe-overlap and D-Cα gates. Projection
protects fixed coordinates but does not solve generated geometry. The control
label “deterministic” denotes zero churn, not proof of fully deterministic CUDA
execution. Training-crop/domain mismatch remains a hypothesis, not a demonstrated
root cause. These results do not establish a mapping defect or a quality fix.

Reproduce the offline audit:

```bash
PYTHONPATH=src python scripts/analyze_cc89_cuda_controls.py \
  --manifest docs/research/cc89-cuda-controls.json \
  --outcomes .artifacts/cc89-cuda-controls \
  --output .artifacts/cc89-cuda-controls/analysis.json
```

The verified analysis SHA-256 is
`79fac78090b1eb5893b11267b5f93abc666765f90851e51abdfbb0b17fd0ad6f`.
Evidence lives in `.artifacts/cc89-cuda-controls`. Public scope and scientific
thresholds have not been widened by either study.
