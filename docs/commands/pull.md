# `dvbfixer pull`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/pull.md)

Pulls atoms together to form bonds (disulfide bridges, glycosidic bonds) using OpenMM partial minimization. Atoms within a configurable radius of bond endpoints move freely; the rest are frozen via mass=0. Auto-removes conflicting hydrogens (CYS HG for disulfides, ASN HD22 for glycosidic bonds). Validates bond geometry before and after pulling.

## Quick start

Select actual atom endpoints from your structure; the residue numbers below
are examples. The default output is `<input>_pulled.pdb`. Review geometry and
valence warnings afterward; they do not make the proposed chemistry valid.

```bash
# Form a disulfide bond between CYS residues (--bond takes TWO tokens)
dvbfixer pull input.pdb --bond A:22:SG A:96:SG -v

# Multiple bonds
dvbfixer pull input.pdb --bond A:22:SG A:96:SG --bond A:300:ND2 A:1301:C1 -v

# Custom radius, target distance, and output
dvbfixer pull input.pdb --bond A:22:SG A:96:SG --radius 8.0 --target-distance 2.05 -o output.pdb

# Anchor one endpoint (freeze its side, only move the other)
dvbfixer pull input.pdb --bond A:22:SG A:96:SG --anchor A:22:SG -v
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--bond` | (required) | Bond specification as **two separate tokens**: `CHAIN:RESNUM:ATOM CHAIN:RESNUM:ATOM` (e.g. `--bond H:239:SG K:239:SG`). Repeatable for multiple bonds. |
| `-o`, `--output` | `<input>_pulled.pdb` | Output file path |
| `--target-distance` | auto | Target bond distance (angstroms), auto-detected from the element pair if not given |
| `--anchor` | none | Anchor one endpoint of a `--bond` spec — freeze its side, only move the other |
| `--radius` | 10.0 | Radius around bond endpoints for free atoms (angstroms) |
| `--max-iter` | 1000 | Max minimization iterations |
| `--ff` | `auto` | Force field for the OpenMM partial minimization. Accepts a short name (`auto`, `amber`, `amber+glycam`, `charmm`, …) or explicit OpenMM XML paths. See [force-fields.md](../force-fields.md). |
| `--rename` | off | Rename non-canonical residues before processing |
| `-v`, `--verbose` | off | Print detailed progress |

## See also

- [`minimize`](minimize.md) — full-system minimization after pull
- [`transplant`](transplant.md) — alternative for assembling glycoproteins from GLYCAM-Web output

## How it works

Pulls atoms together to form bonds (disulfide bridges, glycosidic bonds) using OpenMM partial minimization. Supports multiple `--bond` specifications, each given as two separate `chain:resnum:atomname` tokens. Protein-protein bonds use `CustomBondForce`; protein-HETATM bonds use `CustomExternalForce` toward the fixed HETATM position. Atoms within `--radius` of bond endpoints are free to move (mass=0 freezing for the rest); `--anchor` freezes one specific endpoint's side even if it would otherwise fall in the free radius. Auto-removes conflicting hydrogens (CYS HG for disulfides, ASN HD22 for glycosidic bonds). Pre-pull validation checks valence (bond count vs `MAX_BONDS`) and bond type reasonableness for the pulling residues. Post-pull validation checks convergence (distance vs target), bond length range, and steric clashes within pulling residues.

## Batch mode

`pull` applies the same bond specification to each directory input independently:
`dvbfixer pull --input-dir structures --output-dir pulled --bond A:10:SG A:45:SG`.
See [Batch mode](../batch-mode.md) for shared keys.
