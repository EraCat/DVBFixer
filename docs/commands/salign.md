# `dvbfixer salign`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/salign.md)

Align and superpose multiple structures. The default engine uses an external
sequence aligner to establish residue correspondence and Biopython's SVD
superposition, so it does not require Modeller or a license. Modeller SALIGN
remains available as an optional engine.

Inputs may be complete PDB files or a single chain written as `PATH:CHAIN`.
The default Biopython engine requires a chain for each input. The primary
output is PIR alignment; `--fit-dir` retains all superposed structures.

## Quick start

```bash
dvbfixer salign template1.pdb:A template2.pdb:H \
  -o templates.pir --fit-dir fitted -v
```

## Supported options

### Input and output

| Key / argument | Value | Default | Description |
|---|---|---|---|
| `template` | `PDB` or `PDB:CHAIN` | required | Two or more template structures. Add `:CHAIN` to restrict an input to one chain. |
| `-o`, `--output` | path | `structural_alignment.pir` | Output path for the PIR alignment. |
| `--fit-dir` | directory | none | Retain the fitted/superposed PDB structures in this directory. Without it, fitted structures are temporary. |

### Structural alignment

| Key | Value | Default | Description |
|---|---|---|---|
| `--engine` | `biopython`, `modeller` | `biopython` | Structural fitting implementation. Biopython is license-free; Modeller selects SALIGN. |
| `--msa-engine` | `auto`, `mafft`, `muscle`, `clustalo` | `auto` | Sequence engine used to identify corresponding residues for Biopython fitting. |
| `--fit-atoms` | atom selection | `CA` | Atoms used for fitting. The Biopython engine currently supports `CA`; Modeller accepts its SALIGN selections. |
| `--rms-cutoff` | ångströms | `3.5` | RMS-distance cutoff used only by Modeller SALIGN. |

### Diagnostics

| Key | Value | Default | Description |
|---|---|---|---|
| `-v`, `--verbose` | flag | off | Print the selected MSA engine and fit RMSD, or verbose Modeller SALIGN output. |
| `-h`, `--help` | flag | off | Print command help and exit. |

The default engine needs MAFFT, MUSCLE 5, or Clustal Omega on `PATH`; see the
[installation guide](../installation.md#multiple-sequence-alignment-executables).
Only `--engine modeller` requires a working Modeller installation and license.

## Batch mode

`salign` does not support directory batch input. Its explicitly selected
structures or sequences comprise one alignment job. See the
[batch support matrix](../batch-mode.md#support-by-tool).
