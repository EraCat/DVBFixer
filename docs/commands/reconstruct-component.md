# `dvbfixer reconstruct-component`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/reconstruct-component.md)

Reconstructs missing **heavy atoms** in one exact, isolated Class A `HETATM`
residue from an explicitly selected local wwPDB CCD component CIF. It rigidly
fits CCD ideal coordinates to at least three non-collinear observed atoms. Every
observed atom coordinate and every source coordinate record remains unchanged.

## Quick start

This example requires the actual SHA-256 of the selected local CCD file.
Replace the quoted placeholder, component ID, and residue selector before use.

```bash
dvbfixer reconstruct-component input.pdb LIG \
  --ccd-cif LIG.cif \
  --ccd-sha256 '<64 lowercase hexadecimal characters>' \
  --chain A --residue 401 \
  --output-root results --bundle-name lig-A-401
```

The destination must not already exist. A successful atomic bundle contains:

```text
results/lig-A-401/
├── structure.pdb
└── provenance.json
```

`provenance.json` records exact component identity, CCD/content and graph
digests, generated atom names and coordinates, validation findings, and input
and output PDB SHA-256 values. Success still has
`geometry_approved=false` and `md_ready=false`.

## Admission and validation

The command requires:

- one exact model, case-sensitive chain, residue number, insertion code, and
  occurrence;
- a single-model, fixed-column PDB no larger than 100 MiB;
- a non-ambiguous CCD graph with ideal coordinates and representable PDB names;
- at least three non-collinear observed anchors;
- exact observed atom-name and element matching;
- no alternate locations or external `LINK`/`CONECT` bond;
- Class A organic chemistry, not a protected cofactor or metal system;
- acceptable anchor RMSD, bond geometry, stereochemistry, internal geometry,
  and no generated-heavy-atom clash below 0.70 Å with the environment.

Only absent heavy atoms are inserted. Existing hydrogens are preserved, but
new hydrogens are not generated; use the established preparation/protonation
workflow after independently reviewing the geometry.

## Explicit refusals

- **Class B:** glycans, PTMs, covalent inhibitors, and other externally linked
  components need linkage chemistry.
- **Class C:** FAD, FMN, NAD/NAP, HEM/HEME, metals, redox systems, and
  coordination complexes need an explicit state/coordination backend.
- Ambiguous CCD records, incomplete authority geometry, insufficient anchors,
  environment clashes, and PDB fixed-column overflow fail without publishing a
  bundle.

There is no MODELLER, OpenBabel, RDKit, or distance-based chemistry fallback.
The command does not parameterize the result and does not support directory
batch mode.
