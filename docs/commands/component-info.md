# `dvbfixer component-info`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/component-info.md)

Reads one wwPDB Chemical Component Dictionary (CCD) record and reports its
formula, formal charge, atoms, bonds, ideal coordinates, source SHA-256, and
provisional DVBfixer chemistry class. With `--structure`, it also compares every
matching PDB residue with the CCD heavy-atom inventory.

This command is read-only. It does not reconstruct, protonate, parameterize, or
modify a structure.

## Quick start

Given a local CCD component record `LIG.cif` and a structure containing LIG:

```bash
dvbfixer component-info LIG --ccd-cif LIG.cif --structure input.pdb --json lig-info.json
```

**Result:** a chemistry/completeness report, not a repaired structure.

## Sources

Choose exactly one source:

```bash
# Reproducible local authority
dvbfixer component-info LBN --ccd-cif LBN.cif --structure input.pdb

# Explicit network lookup from the fixed files.rcsb.org endpoint
dvbfixer component-info FAD --online --structure input.pdb --json fad-info.json
```

Online responses are limited to 5 MiB, do not follow redirects, and are cached
under `~/.cache/dvbfixer/ccd/<ID>/<sha256>.cif` by content digest. Use
`--cache-dir` to choose another private cache. The JSON report records both the
retrieved URL and exact digest.

`--online` is discovery only. `reconstruct-component` deliberately requires an
explicit local CIF so a reconstruction cannot silently change when the remote
CCD record changes.

## Python information API

The same bounded adapter is available without invoking the CLI:

```python
from pathlib import Path
from dvbfixer.ccd import fetch_ccd_component, load_ccd_component

online = fetch_ccd_component("FAD", cache_dir=Path("ccd-cache"))
local = load_ccd_component(Path("FAD.cif"), "FAD")

print(online.name, online.formula, online.provisional_class)
print([(atom.name, atom.element, atom.ideal_position) for atom in local.heavy_atoms])
```

Both calls return an immutable `CcdComponent` with atoms, bonds, ideal
coordinates, dates, formal-charge fields (which may be `None` when CCD declares
`?`), and source provenance. For reconstruction, load the local CIF with
`expected_sha256=...`; objects returned by `fetch_ccd_component` are rejected by
the reconstruction adapter.

## Interpreting the class

The reported class is provisional because a standalone CCD record does not
contain the structure's complete external-link context:

- **A:** potentially eligible isolated organic component;
- **C:** protected cofactor or metal-containing chemistry;
- **D:** outside the generic isolated-organic contract.

An apparent Class A component becomes Class B if the selected structure
instance has an external covalent `LINK` or `CONECT` bond. Class B/C
reconstruction remains unsupported.

## Limits

- The optional structure comparison currently accepts fixed-column PDB only.
- Matching is by exact CCD/PDB atom name and explicit PDB element.
- Nonblank alternate locations are rejected rather than merged.
- Completeness says only whether the heavy-atom inventory matches. It does not
  establish protonation, parameterization, force-field compatibility, or MD
  readiness.

This command does not support directory batch mode.
