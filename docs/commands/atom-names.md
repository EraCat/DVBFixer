# `dvbfixer atom-names`

Converts residue and atom names in a legacy PDB for native AMBER/CHARMM naming
or the bundled legacy AMBER, Amber ff19SB, or CHARMM GROMACS dialect.
Unlike `rename`, this command preserves explicit protonation
variants and applies target-specific atom naming. Unlike `convert`, it does not
convert glycan nomenclature or infer chemical connectivity.

The source is never modified. V1 accepts `.pdb` and `.ent` input only, requires
an explicit output, and rejects multi-model structures, naming collisions, and
ambiguous residue identities before publishing an output.

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
repair. It does not add missing atoms, infer protonation, choose terminal
patches, merge separate caps into CHARMM patches, or guarantee arbitrary ligand
compatibility. Unknown atom/residue names are not guessed; naming collisions
remain errors. Selecting `standard` is not a general inverse for every naming
scheme used by other programs.

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
