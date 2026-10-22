# `dvbfixer conect`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/conect.md)

Infer missing `CONECT` records for a PDB file and write a copy with the
merged bond block. The same inference engine runs **automatically** inside
`prepare`, `top`, `minimize`, `transplant`, and `convert`, so users on a
clean pipeline rarely need to invoke this subcommand directly. Use it
when you want CONECT as a discrete preprocessing step, or to inspect
what bonds dvbfixer perceives in a given input.

## Quick start

```bash
dvbfixer conect input.pdb -o connected.pdb
```

**Result:** a separate PDB with merged existing and inferred CONECT records.
Inspect proposed links; this does not assign force-field parameters.

## Why

Many dvbfixer tools (`prepare`'s glycosylation detection, `top`'s sugar
tree builder, `transplant`'s CONECT remapping, `minimize`'s disulfide
detection) need bond connectivity that lives in `CONECT` records. Inputs
from RCSB, GROMACS, EM depositions, and GLYCAM-Web often ship without
CONECT — and `OpenMM PDBFile.writeFile` strips CONECT silently between
pipeline stages. Auto-inference makes those flows work end-to-end.

## Algorithm

Hybrid — OpenBabel `ConnectTheDots` (Blue Obelisk standard cutoff
`r < r_cov1 + r_cov2 + 0.45 Å`) for general bond perception, then three
domain-specific overrides that match the patterns dvbfixer downstream
tools consume:

| Override | Detects | Cutoff |
|---|---|---|
| **SS** | `CYS`/`CYX`/`CYM` SG-SG | 2.5 Å |
| **Glycosidic** | Sugar anomeric C (C1, or C2 for sialic) → neighbouring sugar O2/O3/O4/O6 | 2.0 Å |
| **Glycosylation** | Protein ND2/OG/OG1 (ASN/SER/THR/NLN/OLS/OLT) → sugar anomeric C | 2.5 Å |

The output is the **union** of existing CONECT (if any) and inferred
bonds, deduplicated. Bonds where both atoms are in the same standard
amino-acid residue are dropped from the inferred set — FF templates own
that chemistry and emitting them just bloats the file.

If OpenBabel is unavailable, falls back to element-aware distance
cutoffs (KDTree-accelerated for systems ≥2000 atoms).

## Usage

```bash
# Default: write <input>_conect.pdb alongside the input
dvbfixer conect input.pdb

# Explicit output path
dvbfixer conect input.pdb -o input_with_bonds.pdb

# Verbose: print counts of (existing, inferred, total)
dvbfixer conect input.pdb -v

# In-place overwrite (rare — guarded by --force)
dvbfixer conect input.pdb -o input.pdb --force
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `-o`, `--output` | `<input>_conect.pdb` | Output PDB path |
| `--force` | off | Allow `--output` to equal input (in-place overwrite) |
| `--include-protein-backbone` | off | Also emit CONECT for standard amino-acid bonds. FF templates own those chemistry, but cyclic peptides built from standard AAs need the N-to-C closure as CONECT to be detected downstream. |
| `-v`, `--verbose` | off | Print bond counts |

## Auto-inference in other tools

The `prepare`, `top`, `minimize`, `transplant`, and `convert` tools
materialise an inferred-CONECT temp PDB at the start of `main()` and
read from that copy. **The user's input file is never modified.**

To opt out (e.g. for debugging what the input actually declared), pass
`--no-infer-conect` to any of those tools:

```bash
# Default: auto-infer runs
dvbfixer top input.pdb --acpype -o gmx/

# Disable: strict CONECT-only behaviour
dvbfixer top input.pdb --acpype -o gmx/ --no-infer-conect
```

## What's NOT inferred

- Standard amino-acid backbone/sidechain bonds — owned by FF templates.
- Bond orders, aromaticity, stereo — `CONECT` is connectivity only.
- LINK records — dvbfixer downstream uses CONECT exclusively.

## See also

- [`prepare`](prepare.md) — uses inferred glycosylation sites
- [`top`](top.md) — uses inferred sugar tree + SS bonds
- [`transplant`](transplant.md) — uses inferred bonds for CONECT remapping
- [Known issues](../known-issues.md)

## References

- Open Babel `ConnectTheDots`: O'Boyle et al., *J. Cheminformatics* 3, 33 (2011).
- Cordero covalent radii: *Dalton Trans.* DOI 10.1039/B801115J (2008).
- wwPDB CONECT format spec: https://www.wwpdb.org/documentation/file-format-content/format33/sect10.html

## How it works

Standalone subcommand and shared backend for automatic CONECT-record inference. Used as the **primary** path for bond connectivity now that the previous scattered distance-based fallbacks are augmented by a single well-tested engine.

**Algorithm** (in `pdbutils.infer_conect_records`):
1. Parse existing CONECT into a canonical sorted-tuple set.
2. Load via OpenBabel; let `ReadFile` run `ConnectTheDots`+`PerceiveBondOrders` internally (do NOT call `mol.ConnectTheDots()` after ReadFile — that wipes the PDB serial mapping; `GetResidue().GetSerialNum(atom)` returns 0 afterwards).
3. Filter inferred bonds: drop intra-standard-AA bonds (FF templates own those), drop water bonds. Keep all other bonds + SS bonds (CYS-family SG-SG) regardless.
4. Force-add three domain overrides at known dvbfixer cutoffs: SS (SG-SG within 2.5 Å between CYS/CYX/CYM), glycosidic (sugar anomeric C1 / C2-sialic within 2.0 Å of any O2/O3/O4/O6 on a neighbour), glycosylation (protein ND2/OG/OG1 within 2.5 Å of sugar anomeric C).
5. Union (existing) ∪ (filtered + overrides), drop bonds referencing stale serials.

Falls back to element-aware distance cutoffs + scipy.spatial.cKDTree if OpenBabel is unavailable. Detects coarse-grained inputs (≥80% C beads with <5% H/N/O) and skips inference with a warning.

**Auto-call inside dependent tools.** `prepare`, `top`, `minimize`, `transplant`, and `convert` materialise an inferred-CONECT temp PDB at the top of `main()` via `pdbutils._materialise_inferred_pdb()` and use it for the rest of the flow. **The user's input file is never modified.** Each tool exposes `--no-infer-conect` as an opt-out (default OFF, i.e. inference runs by default).

**Standalone use.** `dvbfixer conect input.pdb -o output.pdb` writes a copy with merged CONECT. Idempotent: running twice produces identical output. Options: `--force` to allow `--output == input`, `--include-protein-backbone` to also emit standard-AA bonds (needed for cyclic peptides), `-v` for bond counts.

The legacy scattered fallbacks in `prepare.find_glycosylated_atoms_with_sugar`, `top.detect_glycan_links`, `acpype_export.detect_ss_bonds`, and `glycam._detect_glycosidic_bonds_by_distance` are kept as defence-in-depth: they're never reached on the happy path (auto-infer populates CONECT first), but they catch the `--no-infer-conect` case.

## Batch mode

`conect` can infer connectivity independently for a structure directory:
`dvbfixer conect --input-dir structures --output-dir connected --recursive`.
See [Batch mode](../batch-mode.md) for shared keys.
