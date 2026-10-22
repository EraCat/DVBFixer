# `dvbfixer cluster`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/cluster.md)

Clusters glycan conformations from a matching topology and MD trajectory using
glycosidic torsion-angle RMSD and the GROMOS algorithm. Use it for trajectory
analysis, not structure preparation.

Supports both CHARMM36 and GLYCAM force field naming, including sialic acid (Neu5Ac) which links via C2 instead of C1. Two clustering modes: `global` (all torsions at once) and `per-linkage` (each linkage independently, then combined into compound states — default, better for capturing per-linkage conformational variation). Representative structures are medoids (real frames closest to circular mean), automatically aligned on the root sugar or protein attachment point.

## Quick start

Use a trajectory and its matching topology. The command writes torsion and
assignment tables, summaries, and representative PDB frames; `--plot` also
writes interactive HTML plots. See [output files](#output-files) for names.

```bash
# Basic usage — auto-detects linkages, per-linkage clustering
dvbfixer cluster topology.tpr trajectory.xtc -v

# With interactive plots
dvbfixer cluster topology.tpr trajectory.xtc --plot -v

# Global clustering mode (GFDB-style, all torsions at once)
dvbfixer cluster topology.tpr trajectory.xtc --mode global

# Custom cutoff and stride
dvbfixer cluster topology.tpr trajectory.xtc --cutoff 20 --stride 10

# PDB input (no .tpr needed)
dvbfixer cluster structure.pdb trajectory.xtc -o my_clusters --plot

# Separate PDB per cluster, no alignment
dvbfixer cluster topology.tpr trajectory.xtc --separate-pdb --no-align

# Align on specific residue
dvbfixer cluster topology.tpr trajectory.xtc --align-resid 5
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `-o`, `--output` | trajectory stem | Output file prefix |
| `--cutoff` | 30.0 | RMSD cutoff in degrees for GROMOS clustering |
| `--mode` | `per-linkage` | `global` (all torsions) or `per-linkage` (each linkage independently) |
| `--stride` | 1 | Read every Nth frame |
| `--begin` | 0 | First frame to read (0-based) |
| `--end` | last | Last frame (exclusive) |
| `--align-resid` | auto | Residue ID to align representatives on (auto: protein attachment or root sugar) |
| `--no-align` | off | Disable alignment of representative PDBs |
| `--separate-pdb` | off | Write each cluster as separate PDB (default: multi-MODEL PDB) |
| `--select` | all | MDAnalysis selection for output PDB atoms |
| `--plot` | off | Generate interactive HTML plots (requires plotly) |
| `-v`, `--verbose` | off | Verbose output |

## Output Files

| File | Description |
|------|-------------|
| `{prefix}_torsions.csv` | Torsion angles per frame |
| `{prefix}_clusters.csv` | Cluster assignment per frame |
| `{prefix}_summary.txt` | Human-readable summary with per-cluster average torsions |
| `{prefix}_summary.json` | Machine-readable JSON summary |
| `{prefix}_representatives.pdb` | Multi-MODEL PDB with cluster representative structures (aligned) |
| `{prefix}_rama_{linkage}.html` | Ramachandran scatter + free energy surface (interactive, with `--plot`) |
| `{prefix}_timeseries.html` | Torsion angle time series colored by cluster (with `--plot`) |
| `{prefix}_populations.html` | Cluster population bar chart (with `--plot`) |

## Torsion Angle Definitions

Crystallographic convention (IUPAC):

| Angle | Standard hexose | Sialic acid (Neu5Ac) |
|-------|----------------|---------------------|
| **phi** | O5–C1–Ox–C'x | O6–C2–Ox–C'x |
| **psi** | C1–Ox–C'x–C'(x-1) | C2–Ox–C'x–C'(x-1) |
| **omega** | Ox–C'6–C'5–O'5 (1→6 only) | same |

## See also

- [`top`](top.md) — generates the `.tpr` topology that `cluster` reads
- [BEST_PRACTICES.md](../../BEST_PRACTICES.md) — glycan conformational analysis recipe

## How it works

Clusters glycan conformations from MD trajectories using glycosidic torsion angle RMSD (GFDB method). Auto-detects glycosidic linkages from topology, extracts phi/psi/omega torsion angles (crystallographic convention: phi=O5-C1-Ox-C'x, psi=C1-Ox-C'x-C'(x-1), omega for 1→6 linkages), builds circular-RMSD distance matrix, runs GROMOS-style clustering. Handles both CHARMM36 and GLYCAM force field naming. Sialic acid uses C2 anomeric carbon and O6 ring oxygen. Two modes: `--mode global` (cluster all torsions simultaneously) and `--mode per-linkage` (cluster each linkage independently, combine into compound states — default, better at capturing per-linkage conformational variation). Representative structures are medoids (real frames closest to circular mean), aligned by Kabsch superposition on root sugar (auto-detected) or protein attachment point. Output: torsion CSV, cluster assignments CSV, JSON/text summary, representative PDBs (multi-MODEL or separate), interactive plotly HTML plots (Ramachandran + free energy surface, time series, population bar chart). Dependencies: MDAnalysis, numpy, plotly (for plots).

## Batch mode

`cluster` does not support directory batch input because it operates on an
explicitly selected trajectory or structure set. Invoke it separately for each
dataset. See the [batch support matrix](../batch-mode.md#support-by-tool).
