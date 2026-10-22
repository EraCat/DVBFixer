# `dvbfixer diagnose`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/diagnose.md)

Inspects a PDB file and emits a plain-text per-residue findings report.
**Report-only** — never mutates the input. Users pick the appropriate
dvbfixer tool (`prepare` / `minimize` / `protonate` / `pull`) to
actually fix any issue.

## Quick start

```bash
dvbfixer diagnose input.pdb
```

**Result:** a terminal findings report; no coordinates are changed. Exit code `1`
means ERROR-level findings were detected, not necessarily that analysis failed.
Use [doctor](doctor.md) instead to check installed tools and licenses.

## What is checked

Modelled after MolProbity's all-atom validation and BioLuminate's
Protein Report widget. Three families of checks run against every
input:

- **Structural integrity** — missing atoms, missing residues,
  missing terminals, coincident atoms, misplaced hydrogens, altLoc
  conflicts, internal chain breaks, insertion codes. Existing PDB chain-ID
  transitions are treated as explicit boundaries and are not reported as
  breaks.

Diagnose also warns when two protein chains have the same atom identities and
coordinates throughout. This usually indicates that coordinate frames were
concatenated into one PDB without `MODEL` / `ENDMDL` separators. Such merged
structures should be split or corrected before minimization.

- **Chemistry / bond geometry** — valence violations, bond-length
  outliers, broad topology-backed protein backbone and peptide-angle
  outliers, cis peptides, non-planar amides, Cα chirality.
- **Steric analysis** — all-atom clashes using OpenMM's neighbor
  search + van der Waals radii (or MolProbity's `probe` binary if
  it's on `PATH`).

## Usage

```bash
# Full report on stdout
dvbfixer diagnose input.pdb

# Write report to file
dvbfixer diagnose input.pdb -o report.txt

# Restrict to one category
dvbfixer diagnose input.pdb --only steric

# Show only ERROR findings (usable in CI / pre-commit gates)
dvbfixer diagnose input.pdb --severity ERROR

# Verbose (per-check timing + expanded atom detail)
dvbfixer diagnose input.pdb -v

# Exact local geometry evidence for residues and an ordered boundary
dvbfixer diagnose input.pdb --format json \
  --scope-residue 'H:82:A' --scope-boundary 'H:81,H:82:A'
```

## Exit codes

- **0** — no ERROR-level findings (structure is pipeline-safe).
- **1** — at least one ERROR-level finding remains after the severity
  filter. Suitable for shell gates:

  ```bash
  dvbfixer diagnose input.pdb --severity ERROR && \
      dvbfixer prepare input.pdb -o prepared.pdb
  ```

- **2** — argument or I/O error (input file not found, etc.).

## Severity levels

- **ERROR** — would break downstream tools if left as-is (missing
  atoms, coincident atoms, valence violations, hard clashes with
  overlap at or above the selected ERROR cutoff; 0.9 Å by default).
- **WARNING** — tolerated by the pipeline but suspect (moderate
  clashes, altLoc conflicts, internal chain breaks, near-cis peptides,
  and coordinate-identical protein chains that suggest merged frames).
- **INFO** — noted for user review (insertion codes on antibody
  CDRs, cis-PRO — natural but worth flagging).

Protein angle checks are deliberately broad broken-geometry checks, not a
replacement for residue-specific force-field validation. They run only for
complete, uniquely named canonical-protein atoms connected by topology bonds.
The accepted ranges are N-CA-C 95–125°, CA-C-O 105–135°, CA-C-N 100–135°,
O-C-N 105–140°, and C-N-CA 105–140°. An outlier within 15° of its accepted
range is WARNING; a farther outlier is ERROR. Undefined geometry, unsupported
residues, duplicate/missing atoms, and absent peptide bonds are skipped.

## Options

```text
usage: dvbfixer diagnose [-h] [-o OUTPUT]
                         [--only {all,structural,chemistry,steric}]
                         [--severity {ERROR,WARNING,INFO}] [--include-water]
                         [--clash-mode {bioluminate,chimerax,molprobity}]
                         [--clash-cutoff WARN,ERROR]
                         [--scope-residue CHAIN:RESID[:ICODE]]
                         [--scope-boundary LEFT,RIGHT] [--format {text,json}]
                         [-v] [--log-file PATH] [--input-dir DIR]
                         [--output-dir DIR] [--recursive] [--fail-fast]
                         input
```

See the auto-generated [reference page](../reference/diagnose.md) for
the full `--help` output.

Notable non-default behaviours:

- **Waters are excluded from chain-break AND steric checks by default.**
  Crystallographic waters generate massive noise (every ordered water
  triggers a chain break vs its neighbour). Pass `--include-water` to
  restore the old behaviour.
- **Multi-MODEL PDBs are analysed on MODEL 1 only.** A WARNING banner
  is emitted at the top of the report noting how many MODELs were
  detected. Use `dvbfixer split` if you need per-frame analysis.
- **JSON output** is available via `--format json` — a
  machine-readable list of findings suitable for CI gating or
  scripted post-processing. Unicode is emitted directly, so Å, arrows,
  em dashes, and non-Latin input paths remain readable.
- **Exact local scope** is opt-in and JSON-only. Repeat `--scope-residue
  CHAIN:RESID[:ICODE]` to select individual residues, and repeat
  `--scope-boundary LEFT,RIGHT` to request an ordered C(left)-N(right)
  measurement. Selectors are exact and case-sensitive: chains `D` and `d`, and
  residues `82` and `82A`, remain distinct. Numeric ranges are never inferred,
  and requested termini or unrelated chains are not labelled as gaps.
- **Coordinate-identical chains** are compared by protein residue/atom
  identity and coordinates to PDB precision. Equal sequences at different
  positions are legitimate homomers and are not flagged.

Every report includes `D-isomer error: YES`, `NO`, or `NOT CHECKED`. Inputs
carrying a DVBFixer emergency-reflection REMARK also list the repaired
residue(s), even when their final chirality is L, and warn that local hydrogen
angles should be inspected. JSON exposes the same information under
`chirality` with `checked`, `d_isomer_error`, `forced_repairs`, and
`hydrogen_geometry_review_recommended` fields.

JSON findings for bond lengths, bond angles, peptide omega, chirality, and
clashes include additive `details` under schema `dvbfixer.geometry.v1`. The
details retain ordered full atom identities `(chain, resid, icode, atom)` and
unit-bearing observed/reference/deviation values. `geometry.finding_aggregates`
contains deterministic category counts and named maxima for the findings that
remain after check and severity filtering; existing top-level fields are
unchanged.

When exact scope is requested, `scope` uses schema
`dvbfixer.diagnostic-scope.v1` and reports requested/selected residue identities,
residue and backbone-atom completeness, explicit boundary status and C-N
distance, scoped finding aggregates (including zero counts), and deterministic
Python steric evidence. A boundary is measured only when its C and N identities
each resolve to exactly one atom. `topology_bonded` records whether the loaded
topology has the C-N bond; proximity alone never establishes continuity.

## Sample output

```text
================================================================================
dvbfixer diagnose — input.pdb
================================================================================
Loaded: 23 atoms, 2 residues, 1 chains

Structural integrity
----------------------------------------
  ERROR   B/SER126:HG            coincident with OXT (0.001 Å apart)
                                 fix: dvbfixer prepare (0.4.1 pre-strip re-places both)
  ERROR   B/SER126:HG            1.68 Å from parent OG (expected ~0.97 Å)
                                 fix: dvbfixer prepare (0.4.2 post-check re-places)

Chemistry / bond geometry
----------------------------------------
  ERROR   B/SER126:HG-OG         bond H-O: 1.677 Å (expected 0.960 Å, deviation 74.7%)
                                 fix: dvbfixer minimize

Steric analysis
----------------------------------------
  ERROR   B/SER126:OG            clashes with B/SER126:OXT — overlap 1.36 Å

Summary
----------------------------------------
  ERROR:   4 findings across 1 residues
  WARNING: 0 findings across 0 residues
  INFO:    0 findings

Suggested next step: `dvbfixer prepare input.pdb`
================================================================================
```

## Clash-detection engine

Two engines with the same output shape:

- **Python (default)** — `scipy.spatial.cKDTree.query_pairs` for the
  neighbor search, then a vdW-overlap test against the standard
  MolProbity radius table (H=1.20 Å, C=1.70 Å, N=1.55 Å, O=1.52 Å,
  S=1.80 Å, P=1.80 Å). Excludes 1-2, 1-3, and 1-4 bonded pairs so
  tight but chemically-valid rotamers aren't flagged. The bond graph
  is built from BOTH the OpenMM topology bond set AND distance-based
  inference (heavy-heavy ≤ 1.9 Å, X-H ≤ 1.3 Å, S-S ≤ 2.25 Å) — this
  catches HETATMs, glycans, and AMBER/CHARMM protonation variants
  whose real bonds OpenMM's PDBFile parser doesn't infer. Pairs that
  fit a hydrogen-bond envelope (polar H covalently bonded to N/O/S,
  paired with an N/O/S/F acceptor at 1.4 – 2.6 Å) are also skipped
  — MolProbity's `probe` classifies those as `hbond` contacts, not
  clashes.
- **MolProbity `probe`** — used automatically when the `probe` binary
  is on `PATH` (bundled with Phenix / MolProbity). Higher fidelity
  matching MolProbity's own reports. Falls back to the Python engine
  on any probe failure.

Every clash finding records its engine and engine version in JSON. Interactive
whole-structure diagnosis remains Probe-first for compatibility. Scoped and
reusable steric evidence always uses the deterministic Python engine, records
`dvbfixer-python-steric` version `1`, and pins severe overlap at 0.90 Å rather
than allowing Probe availability to change that evidence.

Clash thresholds are selectable via `--clash-mode`. The default
`chimerax` preset matches what you'd see in ChimeraX's `clashes`
report. `molprobity` is our pre-0.6.1 strict-validation floor;
`bioluminate` matches BioLuminate's "Bad" / "Ugly" split.

| Mode | WARN | ERROR |
|---|---|---|
| `chimerax` (default) | 0.6 Å | 0.9 Å |
| `molprobity` | 0.4 Å | 0.5 Å |
| `bioluminate` | 0.75 Å | 1.0 Å |

For explicit tuning, `--clash-cutoff WARN,ERROR` overrides the
preset — e.g. `dvbfixer diagnose --clash-cutoff 0.35,0.45 in.pdb`.

## When to run this

- **Before every `dvbfixer prepare` / `minimize` / `zbs` run** on
  input you don't fully trust (RCSB downloads, upstream-tool output,
  hand-edited PDBs). Saves debugging a downstream crash.
- **As a pre-commit gate** for structural data checked into a repo:
  `dvbfixer diagnose file.pdb --severity ERROR` in the hook.
- **After suspicious pipeline output** to check whether a step
  produced something reasonable. Complementary to
  `dvbfixer.ffutils.geometry.repair_misplaced_hydrogens` which runs
  automatically inside `prepare` / `protonate` / `minimize`.

## See also

- [`prepare`](prepare.md) — auto-fixes coincident atoms + misplaced H
- [`minimize`](minimize.md) — energy-minimize to relax bond lengths /
  clashes
- [`pull`](pull.md) — targeted geometry fixes (SS bonds, glycosidic
  linkages)
- [BEST_PRACTICES.md](../../BEST_PRACTICES.md) — recipe for QA-first
  glycoprotein preparation

## Batch mode

`diagnose` writes one report per structure and distinguishes quality findings
from execution failures: `dvbfixer diagnose --input-dir structures --output-dir reports`.
See [Batch mode](../batch-mode.md) for shared keys and exit behavior.
