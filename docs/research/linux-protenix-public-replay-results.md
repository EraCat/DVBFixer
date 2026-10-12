# Linux Protenix Public-CLI 231-Case Replay

- Status: completed replay and independent revalidation; deployment acceptance pending.
- Profile: `protenix-v1-cuda`, seed 7, one candidate per case.
- Runner change group: `b7675b6` (persistent archive support).
- Membership: all 231 frozen v5 cases, in screening-index order, without replacements.
- Membership manifest SHA-256:
  `fa2bd455ef44c0a413cc2a174a4dfd017af51a99617fb69eb7bdc364eba0850f`.
- Historical aggregate SHA-256:
  `55e4cbc6c16ee6bf34a14aabf61ec71afcddfb436f15edb5195c3d8b3f717ad7`.
- Completed replay report SHA-256:
  `f5f92a01d179ad08d00daaf8ff3e6c867bac072aad3cd8c8642eb445e8f8ec14`.
- Analysis artifact SHA-256:
  `58978f3d2cbaec592bdda895708ee5d0dea62b7e6e1f358a733f5f4b810e33e4`.

## Verification

All 231 archived bundles and their PDB, `.dat`, provenance, and sampler-trace
digests match the completed replay report. Frozen materialization, reference
digests, exact cohort order, scientific request identity, checkpoint/source/
profile-lock provenance, and sampler evidence were checked again. Every candidate
was then independently revalidated through the existing DVBFixer validator in a
private workspace. All statuses and failed-gate lists were reproduced.

All 231 cases have zero fixed-heavy RMSD, zero maximum fixed-heavy displacement,
zero detectable D-Cα, and zero post-projection error across all 200 callback
updates. Geometry rejects remain in the denominator. The completed run has no
remaining per-case operational failure records. Earlier timeout and temporary
storage loss are documented separately in [acceptance history](linux-protenix-acceptance.md).

## Scientific Results

| Endpoint | Frozen Protenix baseline | Public production replay |
|---|---:|---:|
| Accepted | 220/231 | **219/231** |
| Pass rate | 95.24% | **94.81%** |
| Wilson 95% CI | 91.68–97.32% | 91.14–97.00% |
| Median passing gap-backbone RMSD | 0.408 Å | **0.407 Å** |
| Gap-5 accepted | 125/128 | **125/128** |
| Gap-10 accepted | 95/103 | **94/103** |
| Gap-5 median passing RMSD | 0.326 Å | 0.328 Å |
| Gap-10 median passing RMSD | 0.623 Å | 0.639 Å |

Paired outcomes: 219 both passed, 0 replay-only passed, 1 baseline-only passed,
11 neither passed. Pass-rate difference is −0.433 percentage points, with
cluster-bootstrap 95% CI −1.299 to 0.000 percentage points. The existing 5-point
noninferiority criterion is satisfied. Median paired RMSD difference among common
passing cases is −0.000958 Å (95% CI −0.002540 to +0.000690 Å), so an RMSD
advantage is not demonstrated. The comparison is `noninferior-rmsd-inconclusive`.

These endpoints describe the production-wrapper replay against the historical
Protenix result set. They do not repeat the original MODELLER experiment or
authorize changing defaults or public scientific scope.

## Changed Case: 9eho

`9eho` is the only case whose accepted/rejected status differs. The replay
candidate is rejected on `generated-or-junction-sidechain-chi12`. Current
side-chain measurement identifies **X/GLU129**, χ1=116.531°, χ2=−64.398°.
The same checker finds no chi1/chi2 outlier in the historical refined PDB.

The old refinement summary records revision
`dvbfixer-openmm-boundary-refinement-v4`; the current production path records v6.
Both use the frozen checkpoint, but these are not coordinate-identical refined
outputs. This revision difference is evidence of changed processing, not an
isolated causal attribution for the torsion change.

A subsequent [controlled ordering investigation](linux-protenix-local-deployment-evidence.md)
showed that v4 and v6 produce identical output on the same input. The raw atom
coordinates match exactly, but file atom ordering differs; restoring only the
frozen order restores the historical refined coordinates. The replay result is
retained unchanged.

| Metric | Historical candidate | Replay candidate |
|---|---:|---:|
| Gap-backbone RMSD | 0.948909 Å | 0.885247 Å |
| Gap all-heavy RMSD | 2.015057 Å | 1.892506 Å |
| Fixed-heavy RMSD | 0.0 Å | 0.0 Å |
| Independent chi1/chi2 outlier | none | X/GLU129 |

Improved reference RMSD does not override a geometry failure. The gate remains
unchanged and the rejected structure is retained for inspection.

## All Scientific Rejects

| Case | Failed gates (generated/junction unless indicated) |
|---|---|
| `9eho` | sidechain chi1/chi2 |
| `9g9t`, `9jco`, `13ib` | amide planarity |
| `22uy`, `9ddr` | bond length |
| `24rc` | Ramachandran |
| `9jqa` | junction connectivity, bond angle, Ramachandran |
| `8xyp` | bond angle, amide planarity, Ramachandran |
| `9ejk` | junction connectivity, bond length, bond angle, amide planarity, severe steric overlap |
| `9e16` | junction connectivity, bond angle, amide planarity |
| `9jjb` | junction connectivity, bond length, bond angle, amide planarity |

## Operational Measurements

Replay runner wall time totals **24.48 hours**, median **214.0 seconds** per case.
Peak RAM is **3.72 GiB** and peak VRAM **6.61 GiB**. The historical complete-stage
totals were 22.30 hours, median 209.0 seconds, RAM 3.68 GiB, VRAM 6.61 GiB.

Timing boundaries differ: replay runner metrics cover sampling/refinement and
exclude CLI preflight/publication; historical measurements cover complete
research stages. Earlier failed attempts and interruptions are not included in
the replay runner sum. This is not a controlled speed comparison.

## Reproduction and Remaining Acceptance

```bash
PYTHONPATH=src python scripts/analyze_protenix_public_cohort.py \
  .artifacts/protenix-public-231 .artifacts/diffusion-confirmatory-cohort-500-v5 \
  --work-parent /tmp/opencode \
  --output .artifacts/protenix-public-231/analysis.json
```

The analyzer is read-only with respect to scientific inputs and bundles. It
writes a portable analysis without checkpoint locations or private host paths.
The full artifact remains under ignored `.artifacts/`; this note freezes its
digest and endpoints. It fails on incomplete membership, changed artifacts,
request/profile mismatch, or revalidation disagreement.

The full public production replay is now complete, with one explicitly retained
scientific status difference. Final OCI image/package-export acceptance and
execution of the manual self-hosted lane remain pending. MODELLER stays the
default; full deployment acceptance is not claimed.

Portable verification after analysis: focused tests `33 passed`; full non-slow
suite `1027 passed, 6 skipped, 31 deselected`. Ruff, version synchronization,
agent documentation and whitespace checks passed. GROMACS-required tests remain
skipped; existing Python 3.13 stream-teardown warnings are non-fatal.
