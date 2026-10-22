# `dvbfixer puppet`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/puppet.md)

Strips a PDB to a minimal backbone scaffold: removes all non-ATOM lines, removes all sidechain and hydrogen atoms (keeps only N, CA, C, O, OXT), and renames every residue to GLY. Useful for creating "puppet" models for backbone-level alignment, modeling templates, or visualization.

## Quick start

**Result:** `<input>_puppet.pdb`, a scaffold for modeling or visualization, not
a chemically complete protein for simulation.

```bash
# Basic usage — writes input_puppet.pdb
dvbfixer puppet input.pdb

# Keep specific residues intact (all atoms, original name)
dvbfixer puppet input.pdb --keep A:307

# Keep a range and a list
dvbfixer puppet input.pdb --keep H:286-296 --keep K:307,309

# Custom output
dvbfixer puppet input.pdb -o backbone.pdb
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `-o`, `--output` | `<input>_puppet.pdb` | Output file path |
| `--keep` | none | Keep residue(s) intact: CHAIN:NUM, CHAIN:START-END, or CHAIN:NUM1,NUM2,START-END (repeatable) |

## See also

- [Command index](index.md)

## How it works

Strips PDB to backbone-only polyglycine model. Removes all non-ATOM lines, keeps only backbone atoms (N, CA, C, O, OXT), renames all residues to GLY. `--keep CHAIN:NUM` preserves specific residues intact (all atoms, original name) — accepts single, range (`A:100-110`), list (`A:100,105`), or mixed, repeatable. No dependencies beyond stdlib.

## Batch mode

`puppet` supports directory input with the same `--keep` selections applied to
each structure: `dvbfixer puppet --input-dir structures --output-dir puppets`.
See [Batch mode](../batch-mode.md) for shared keys.
