# `dvbfixer msa`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/msa.md)

Align two or more protein sequences through a consistent interface. MAFFT is
the default when several engines are installed; MUSCLE 5 and Clustal Omega can
be selected explicitly. Output is validated to ensure that row identifiers and
ungapped sequences were not changed by the external program.

## Quick start

```bash
dvbfixer msa sequences.fasta -o alignment.fasta
dvbfixer msa sequences.fasta --engine muscle --format pir -o alignment.pir
dvbfixer msa target.fasta --template template1.pdb:A --template template2.pdb:H
dvbfixer msa --list-engines
```

## Supported options

### Input and output

| Key / argument | Value | Default | Description |
|---|---|---|---|
| `input` | FASTA path | required unless `--list-engines` | Input containing at least two records, or one record when templates are appended. |
| `-o`, `--output` | path | `<input>_aligned.fasta` | Alignment output path; the automatic suffix is `.pir` with `--format pir`. |
| `--template` | `PDB[:CHAIN]` | none | Append sequence data extracted from a template PDB. Repeat the option for multiple templates. |

### Alignment

| Key | Supported values | Default | Description |
|---|---|---|---|
| `--engine` | `auto`, `mafft`, `muscle`, `clustalo` | `auto` | Select the external engine. Auto tries MAFFT, MUSCLE 5, then Clustal Omega. |
| `--format` | `fasta`, `pir` | `fasta` | Select aligned FASTA or Modeller PIR output. |

### Diagnostics

| Key | Value | Default | Description |
|---|---|---|---|
| `--list-engines` | flag | off | Print each supported engine and its detected executable path, then exit. |
| `-v`, `--verbose` | flag | off | Print the external command and any diagnostic output from the engine. |
| `-h`, `--help` | flag | off | Print command help and exit. |

The executable is resolved from `PATH` as `mafft`, `muscle`, or `clustalo`.
Install the full environment to obtain all three engines, or install only the
engine required by a headless workflow. MUSCLE must be version 5; MUSCLE 3 has
a different command-line interface. Run `dvbfixer msa --list-engines` to see
the executable paths detected by the CLI. Full conda, Homebrew, Linux, Windows,
and standalone-binary instructions are in the
[installation guide](../installation.md#multiple-sequence-alignment-executables).

## Batch mode

`msa` does not support directory batch input. Its explicit sequence inputs
already form one multiple-alignment job. See the
[batch support matrix](../batch-mode.md#support-by-tool).
