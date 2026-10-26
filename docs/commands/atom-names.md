# `dvbfixer atom-names`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/atom-names.md)

Converts residue and atom names in a legacy PDB for native AMBER/CHARMM naming
or the bundled legacy AMBER, Amber ff19SB, or CHARMM GROMACS dialect.
Unlike `rename`, this command preserves known protonation variants by default
and applies target-specific atom naming. Unlike `convert`, it does not
convert glycan nomenclature or infer chemical connectivity.

The source is never modified. V1 accepts `.pdb` and `.ent` input only, requires
an explicit output, and rejects multi-model structures, naming collisions, and
ambiguous residue identities before publishing an output.

## Quick start

```bash
dvbfixer atom-names input.pdb -o named.pdb --target-ff amber --profile standard
```

**Result:** a separate `named.pdb` with native AMBER labels. Use `--dry-run`
to inspect a conversion without writing the PDB; add `--report-json report.json`
for a report. This is not atom repair or force-field parameterization.

## Naming profiles

`--target-ff` selects the force-field family/dialect; `--profile` selects its
consumer naming convention. Both profiles are available in the GUI's **Profile**
selector and the naming API:

- **`gromacs`** (default, unchanged): bundled GROMACS atom names, including
  dialect-specific hydrogen, cap and terminal aliases.
- **`standard`**: native force-field names, not GROMACS-specific aliases.
  For AMBER and Amber ff19SB this includes `H`, methylene `HB2`/`HB3`, and
  terminal `O`/`OXT`. For CHARMM this includes `HN`, methylene `HB1`/`HB2`, and
  free-terminal `HT1`/`HT2`/`HT3` and `OT1`/`OT2` names. Recognized GROMACS
  aliases are normalized rather than simply left unchanged. Already-native
  supported names remain unchanged on repeated conversion.

For example, use native AMBER names without preparing input for GROMACS:

```bash
dvbfixer atom-names input.pdb -o amber_native.pdb \
  --target-ff amber --profile standard
```

This is a naming operation, not a force-field parameterization or structure
repair. It does not add missing atoms, infer protonation by default, choose terminal
patches, merge separate caps into CHARMM patches, or guarantee arbitrary ligand
compatibility. Unknown atom/residue names are not guessed; naming collisions
remain errors. Selecting `standard` is not a general inverse for every naming
scheme used by other programs.

## Optional identification from observed hydrogens

By default, naming conversion uses the source residue name and explicit variant
overrides only: `HIS` stays `HIS` even if it contains HD1/HE2. Enable
`--infer-protonation` to first recognize the residue family/state from its name,
then refine that identification from existing diagnostic site hydrogens, and
finally translate the result into the selected force-field/profile dialect:

```bash
dvbfixer atom-names input.pdb -o named.pdb --target-ff amber \
  --profile gromacs --infer-protonation --report-json naming-report.json
```

| Family | Supported positive H evidence | AMBER residue identity |
|---|---|---|
| HIS (including HID/HIE/HIP and CHARMM equivalents) | HD1 only / HE2 only / both | HID / HIE / HIP |
| ASP | One carboxyl H (HD1 or HD2) | ASH |
| GLU | One carboxyl H (HE1 or HE2) | GLH |
| LYS | NZ HZ1/HZ2 or HZ2/HZ3 / HZ1/HZ2/HZ3 | LYN / LYS |
| CYS | One sulfur H (HG or HG1) | CYS; conflicting CYX identity is retained with a warning |

CHARMM output translates identified variants to HSD/HSE/HSP, ASPP, GLUP and LSN
as appropriate. No new TYR/ARG variant vocabulary is invented. No atoms are
added/deleted, coordinates moved, pKa predicted, or protonation recomputed at a
new pH. Existing atom labels still undergo the ordinary selected naming policy.
Use `protonate` when a new pH-dependent chemical state and H rebuilding are wanted.

The option reads the **represented H pattern**, so use complete, correctly named
hydrogenated residues: a partially missing set can resemble another valid state
(for example, HIP missing HE2 resembles HID). The code cannot prove that an absent
hydrogen was intentionally omitted. No diagnostic H, missing ionizable-group
heavy atoms or unsupported site patterns retain the name-derived state with a
warning. In particular, absence of CYS HG does not distinguish CYM from CYX or
missing hydrogen; disulfides are not inferred by distance. Explicit variant
overrides always win over H-based identification.

Common blank-altloc atoms are considered with each conformer independently;
different conformer H patterns are not merged into a fictitious protonation
state. Disagreement leaves the name-derived state and a diagnostic. Chain case
and insertion codes remain distinct. Conflicting explicit names versus usable H
patterns are reported before using the observed state. JSON reports record
`inferProtonation: true`, identification/uncertainty diagnostics, and
`observed-protonation` change rules when enabled. Dry runs perform the same
analysis without publishing a PDB.

The GUI **Infer Protonation** checkbox appears before **Dry Run** and is off by
default. This feature belongs to `atom-names`; `rename` remains the existing
canonicalizer and is unchanged.

## GROMACS dialects

```bash
dvbfixer atom-names input.pdb -o amber.pdb \
  --target-ff amber --profile gromacs
```

Choose `amber19sb` when the output will be consumed by `top --ff amber19sb`.
This is a distinct dialect, not an alias for `amber`: ff19SB keeps `O`/`OXT`
on C termini and PDB-style ACE/NME atom names, while the legacy AMBER bundle
uses `OC1`/`OC2` and renamed cap atoms. Naming conversion does not validate the
whole structure against ff19SB's protein-only component restrictions; `top`
still performs that fail-closed validation.

```bash
dvbfixer atom-names input.pdb -o amber19sb.pdb \
  --target-ff amber19sb --profile gromacs
```

Use `--dry-run` to validate and summarize a conversion without writing the PDB.
Use `--report-json report.json` for a machine-readable report on either success
or a validation failure.

In the `gromacs` profile, protein terminal naming respects both chain IDs and
explicit `TER` boundaries.
For example, two fragments with chain ID `A` separated by `TER` each receive
their own N- and C-terminal naming rules. Bare `TER` lines are sufficient;
residue numbering gaps alone do not create new termini. Caps such as ACE/NME
remain part of their fragment and prevent adjacent residues from being treated
as free termini. The command preserves the input boundaries; it does not infer
missing chain breaks or decide whether a break should be capped.

The same `(chain ID, residue number, insertion code)` cannot occur on both sides
of a `TER`, even with different atom names or alternate locations. Reports and
variant overrides cannot distinguish those residues, so both profiles reject
the input with `NAMING_COLLISION` before writing an output. Assign distinct
chain IDs or residue numbers to those fragments first; chain case and insertion
codes remain significant.

Variant overrides are supplied as a JSON array. Residue identity includes the
case-sensitive chain ID, residue number, and insertion code:

```json
[
  {"chainId": "H", "residueNumber": "82", "insertionCode": "A", "variant": "HIE"}
]
```

```bash
dvbfixer atom-names input.pdb -o amber.pdb --target-ff amber \
  --variant-overrides variants.json --report-json naming-report.json
```

The report uses `schemaVersion: 1` and includes the request, success state,
stable error details when applicable, output publication state, diagnostics,
summary counts, and per-coordinate changes. Exit code `2` denotes validation or
conversion failure; publication and other I/O failures use exit code `1`.

For AMBER/GROMACS output, DNA and RNA sugar-hydrogen aliases are converted for
the canonical `DA`/`DC`/`DG`/`DT` and `A`/`C`/`G`/`U` residue names. Terminal
5-prime and 3-prime hydroxyl naming and protonation have not been validated and
are unsupported; the command does not infer or rewrite those terminal states.

See the generated [CLI reference](../reference/atom-names.md) for all options.
