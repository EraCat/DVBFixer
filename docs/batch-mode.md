# Batch mode

[User guide](README.md) · [Command index](commands/index.md) · [Troubleshooting](known-issues.md)

Batch mode runs one supported single-structure command independently for every
`.pdb`, `.ent`, `.cif`, or `.mmcif` file in a directory (`split` also accepts `.gro`). Outputs are
written under a separate directory; `--recursive` preserves relative paths and
processing continues after individual failures unless `--fail-fast` is used.

```bash
dvbfixer zbs --input-dir structures --output-dir fixed --recursive --no-solvent
```

The shared keys are `--input-dir DIR`, `--output-dir DIR`, `--recursive`, and
`--fail-fast`.

Shared keys use exact option matching. In particular, `-o` and `--output`
remain subcommand output options and are not accepted as abbreviations for
`--output-dir`, regardless of their position in the command. This makes both
forms below unambiguous:

```bash
dvbfixer prepare input.pdb --output prepared.pdb
dvbfixer prepare --input-dir structures --output-dir prepared
```

Positive/non-negative numeric constraints and structured selector syntax are
validated once by each subcommand's parser before batch processing begins, so
an invalid shared invocation cannot fail differently from file to file.

## Support by tool

| Tool | Batch input | Notes |
|---|---:|---|
| `split` | Yes | Accepts PDB, ENT, CIF/mmCIF, and GRO files. |
| `renumber` | Yes | Renumbers each structure independently. |
| `model` | Yes | Models each structure independently. |
| `pull` | Yes | Pulls each structure independently. |
| `prepare` | Yes | Prepares each structure independently. |
| `minimize` | Yes | Minimizes each structure independently. |
| `protonate` | Yes | Protonates each structure independently. |
| `rename` | Yes | Renames each structure independently. |
| `convert` | Yes | Converts each structure independently. |
| `conect` | Yes | Rebuilds connectivity for each structure independently. |
| `puppet` | Yes | Applies the requested operation to each structure independently. |
| `diagnose` | Yes | Writes one diagnostic report per structure. |
| `zbs` | Yes | Runs the selected ZBS stages independently per structure. |
| `top` | No | Requires one explicit input per invocation. |
| `transplant` | No | Its source/target relationship is not a directory batch operation. |
| `cluster` | No | Operates on an explicitly selected trajectory or structure set. |
| `parametrize` | No | Requires explicit ligand/parameterization inputs. |
| `component-info` | No | Queries one explicitly selected CCD component. |
| `reconstruct-component` | No | Requires one exact component identity and one pinned CCD authority. |
| `homology` | No | Requires explicit query, template, and alignment relationships. |
| `msa` | No | Operates on an explicitly selected sequence set. |
| `salign` | No | Operates on explicitly selected structures/sequences. |
| `doctor` | No | Checks the installation once; it has no structure input. |

Every tool repeats its status in `dvbfixer TOOL --help` and in its command
guide. Passing `--input-dir` to an unsupported tool fails with a message that
lists the supported commands.

## Findings versus failures

Processing continues after individual failures by default. `--fail-fast` stops
at the first failure. Each input has separate outputs and a success/failure
summary; recursive mode preserves relative directory layout.

For `diagnose`, exit status `1` means analysis completed with ERROR-severity
findings. Batch output labels these as `FINDINGS` rather than execution failures
and points to the per-structure report.

## Run logs

Every command, including those without folder input, accepts `--log-file PATH`:

```bash
dvbfixer prepare input.pdb -o prepared.pdb --log-file prepare.log
```

Logs append a versioned UTC header and capture Python and inherited child-process
stdout/stderr while retaining terminal output. Log files have no terminal color
escapes. Actual warnings/errors are repeated in a deduplicated final summary,
including during exception cleanup; clean runs have no empty warning banner.

## Final numbering

`renumber`, `model`, and `zbs` accept `--number-from-1`. This shifts each final
chain to start at protein residue 1 while preserving internal gaps and relative
heterogen numbering. ZBS applies it only to final output, before postflight
diagnostics; intermediate sidecar identifiers remain unchanged.
