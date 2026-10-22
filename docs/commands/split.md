# `dvbfixer split`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/split.md)

Splits chains in PDB or GRO files that lack chain IDs (e.g. GROMACS MD output). Assigns unique chain IDs (A-Z, a-z, 0-9), inserts TER records, and renumbers residues per chain. GRO files are converted to PDB via MDAnalysis, preserving all residue names including protonation variants (GLUP, ASPP, etc.). Water, ions, and buffer particles (BUF/BUFF) are removed before chain detection to prevent false breaks, then optionally re-appended.

## Quick start

```bash
dvbfixer split md_output.pdb -o split.pdb
```

**Result:** a PDB with empirically assigned chains. Inspect boundaries and
numbering before using it for sequence-aware modeling. Use the explicit assembly
mode below for metadata-defined biological assemblies instead.

## Biological assemblies

For deposited PDB files with biological-assembly metadata, explicit
`--assembly ID|all` mode reads `REMARK 350`, selects the declared chains, and
applies every BIOMT rotation/translation. This mode preserves source residue
numbers by default and does not use empirical distance cutoffs. Existing
`split` behavior is unchanged when `--assembly` is absent.

Chain breaks are detected by three criteria, applied in priority order:

1. **Residue number backward jump** — residue sequence number decreases (insertion codes like 82->82A are handled correctly and NOT treated as breaks)
2. **C->N peptide bond distance** — distance exceeds 2.5 A (any residue with backbone C/N atoms)
3. **Nearest-atom gap** — minimum distance between any atoms of consecutive residues exceeds 15 A (fallback for sugars, ligands, ions that lack peptide bonds)

**Multi-MODEL inputs** (multi-state PDBs, NMR ensembles, GROMACS trajectory exports with MODEL records) are handled as one complex sampled at multiple states: every MODEL gets the SAME chain IDs (A, B, C in every MODEL — not A B C / D E F / G H I as a naive walk would produce). The per-MODEL chain signature (atom count + residue count + first/last resname per chain) is compared across MODELs; when all match, chain IDs are reused. If MODELs differ structurally the tool falls back to independent per-MODEL chain IDs with a warning. Input atom serials are preserved within each MODEL.

**Small-molecule threshold (`--max-chains`)** — when more than N chains are detected (default 26), only **protein** chains get chain IDs. Small-molecule chains (ions, ligands, lipids, single-residue HETATMs, glycan trees) keep a blank chain ID. A chain is classified "protein" when ≥50% of its residues are standard amino acids (incl. AMBER protonation variants HID/HIE/HIP/ASH/GLH/CYX/CYM/LYN, GLYCAM glycoprotein NLN/OLS/OLT, ACE/NME caps, MSE). Useful for structures with dozens of crystallographic ions/ligands/lipids that don't need their own letter. Raise the threshold with `--max-chains 62` to keep the original assign-all behaviour (cap is `len(CHAIN_IDS) = 62`: A-Z + a-z + 0-9).

## Usage

```bash
# Basic usage — writes input_split.pdb
dvbfixer split input.pdb

# GRO file input (output is always PDB)
dvbfixer split simulation.gro -v

# Verbose output showing detected chains
dvbfixer split input.pdb -v

# Custom output and cutoffs
dvbfixer split input.pdb -o output.pdb -d 3.0 -g 20.0

# Disable distance-based detection (use only residue numbering)
dvbfixer split input.pdb --no-distance

# Keep original residue numbers
dvbfixer split input.pdb --no-renumber

# Give every retained non-solvent molecule its own chain identity
dvbfixer split structure.pdb --unique-molecule-chains --no-renumber

# Retain ALL heterogens, including waters, ions and buffers
dvbfixer split structure.pdb --keep-heterogens --unique-molecule-chains

# Extract one biological assembly to an exact output path
dvbfixer split 8XJ0.pdb --assembly 1 -o 8XJ0_AB.pdb

# Extract every declared assembly
dvbfixer split 8XJ0.pdb --assembly all
# writes 8XJ0_assembly_1.pdb ... 8XJ0_assembly_4.pdb
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `-o`, `--output` | `<input>_split.pdb` | Output file path |
| `--assembly ID\|all` | none | Extract one or all PDB biological assemblies from REMARK 350/BIOMT. With `all`, `-o` is treated as an output prefix. PDB only. |
| `-d`, `--distance-cutoff` | 2.5 | C->N peptide bond cutoff (angstroms) |
| `-g`, `--gap-cutoff` | 15.0 | Nearest-atom gap cutoff for non-protein residues (angstroms) |
| `--no-distance` | off | Disable all distance-based detection |
| `--renumber` / `--no-renumber` | mode-dependent | Empirical mode renumbers by default; assembly mode preserves deposited numbering by default. |
| `--keep-water` | off | Keep water and ions in output (removed by default) |
| `--keep-heterogens` | off | Keep all input heterogens, including waters, ions and buffers, inside their original MODEL blocks. Preserve atom serials so CONECT references remain valid. Combine with `--unique-molecule-chains` to assign non-solvent molecules distinct IDs. |
| `--unique-molecule-chains` | off | Preserve polymer chains and assign unique IDs to non-solvent heterogen molecules. Assembly metadata IDs are reserved, CONECT is preserved, and a REMARK 999 provenance record is added. |
| `--max-chains` | 26 | Above this many detected chains, small-molecule chains (ions, ligands, lipids, single-residue HETATMs, glycan trees) get blank chain ID; only protein chains get IDs. |
| `-v`, `--verbose` | off | Print detected chain info |

## See also

- [`renumber`](renumber.md) — SEQRES-based residue renumbering after chain splitting
- [`model`](model.md) — rebuild missing loops in the split structure
- [`zbs`](zbs.md) — full pipeline that includes splitting + renumbering + modeling
- [Scientific domain model](../domain-model.md) — structure identity and parameterization invariants

## How it works

In empirical mode, HELIX and SHEET references are updated with residue and chain numbering so
viewers draw secondary structure on the correct residues. An annotation that
cannot be mapped uniquely, or crosses a new chain boundary, is omitted with a
warning rather than attached to the wrong part of the protein.

Atom serials are preserved independently of residue renumbering in every
empirical Split mode. CONECT entries therefore continue to reference the same
atoms; inserted TER records have no serial number. If an older Split output
has incorrect ligand bonds, rerun Split from the original input before Model.
Model cannot infer which atoms a corrupted input CONECT record originally meant.

Splits chains in PDB or GRO files lacking chain IDs (e.g. GROMACS output). GRO files are converted to PDB via MDAnalysis (preserves all residue names including protonation variants like GLUP, ASPP). Water, ions, and buffer particles (BUF/BUFF) are stripped before chain detection to prevent false breaks (`--keep-water` re-appends them). Three detection criteria:
1. Residue number backward jump (insertion codes handled — equal resSeq with different iCode is NOT a break)
2. C->N peptide bond distance > 2.5 A (any residue with backbone C/N atoms — no name-based filtering)
3. Nearest-atom gap > 15 A (fallback for residues lacking C/N backbone atoms: sugars, ligands)

**Multi-MODEL handling** (`find_model_blocks` + `_process_multi_model`): when the input contains multiple MODEL/ENDMDL records (multi-state PDB, NMR ensemble, GROMACS trajectory dumped with MODEL records), each MODEL is the SAME complex sampled at different states. Per-MODEL chain signatures (atom count + residue count + first/last resname per chain) are compared across MODELs; when all match, every MODEL is rewritten with the SAME chain IDs (A B C in MODEL 1, A B C in MODEL 2, …) instead of cascading (A B C / D E F / G H I). If MODELs differ structurally the tool falls back to per-MODEL independent chain IDs with a warning. Input atom serials are preserved within each MODEL; TER records inserted between chains in every MODEL.

**Small-molecule threshold** (`--max-chains`, default 26): when total detected chains > threshold, only PROTEIN chains get chain IDs from `CHAIN_IDS`; small-molecule chains (ions, ligands, lipids, single-residue HETATMs, glycan trees) keep blank chain ID. Classification via `_classify_chains` (per-chain ≥ 50% standard-AA residues = protein; STANDARD_RESIDUES now also includes AMBER protonation variants HID/HIE/HIP/ASH/GLH/CYX/CYM/LYN, GLYCAM NLN/OLS/OLT, and MSE). `_assign_chain_ids` returns the per-chain ID list honouring the threshold. Applies to both single-block and multi-MODEL paths. Protein-chain count above `len(CHAIN_IDS)` (62) still aborts with an error.

**Biological-assembly handling** (`biological_assembly.py`): parses each
BIOMOLECULE, APPLY/AND CHAINS group, and complete BIOMT1/2/3 operator. Atom
coordinates and ANISOU tensors are transformed per operator; duplicated chains
receive unused PDB chain IDs. SEQRES, SSBOND, LINK, CONECT, TER, and atom
serials are regenerated for each standalone output. Missing chains, malformed
operators, unknown IDs, GRO input, and the 62-chain PDB limit fail before any
output is written.

## Batch mode

`split` can process every `.pdb`, `.ent`, or `.gro` in a directory independently:
`dvbfixer split --input-dir structures --output-dir split --recursive`.
See [Batch mode](../batch-mode.md) for failure policy and shared keys.
