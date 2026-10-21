# dvbfixer

A suite of Python CLI tools for preparing PDB and CIF structural biology files. Handles common issues with structures from MD simulations and structural databases: missing chain IDs, antibody insertion codes, missing loops/residues, loop rebuilding with Modeller, multi-template homology modeling, energy minimization with selective restraints, protonation state assignment, GROMACS topology generation, GLYCAM glycoprotein transplanting, small molecule parametrization (GAFF2), and glycan conformational clustering from MD trajectories.

Current release: **0.9.1**.

This README is the root of a manual-style documentation tree. Each subcommand has its own page under [`docs/commands/`](docs/commands/index.md); the [pipelines](docs/pipelines.md) page collects end-to-end recipes. For design notes see [`ARCHITECTURE.md`](ARCHITECTURE.md) and the focused [scientific domain model](docs/domain-model.md); for opinionated recipes and gotchas see [`BEST_PRACTICES.md`](BEST_PRACTICES.md).

The [whole-complex relaxation research](docs/research/whole-complex-relaxation.md) describes current limits, incomplete-cofactor findings, and proposed alternatives. The separate [reconstruction and modeling backend research](docs/research/reconstruction-and-modeling-backends.md) records PDBFixer and MODELLER comparators and the evidence behind the narrow experimental `model --backend diffusion` CLI; MODELLER remains the default and neither current dependency is deprecated.

## Quick start

```bash
micromamba create -f environment.yml
micromamba activate dvbfixer
pip install -e .
dvbfixer --help
```

## DVBfixer GUI

The repository includes a React/Mol* workspace under [`gui/`](gui/).
It exposes every CLI command through forms generated from the argparse surface,
indexes structure and non-structure artifacts, and adds a persistent
multi-template Homology workflow with MSA editing and Modeller template masks.
The complete workflow is documented in the
[GUI Homology guide](docs/gui-homology.md).
The [DVBFixer API guide](docs/api.md) covers workspace-scoped managed jobs,
the synchronous naming conversion, authentication, and OpenAPI.
The GUI requires Node.js 22 or newer and a `dvbfixer` executable that passes the
startup `--version` check. Activate the installed environment before starting it;
the development server opens the browser automatically outside test/CI mode.

```bash
cd gui
npm ci
npm run dev
```

For a built local server with the same API routes, run `npm run build` followed
by `npm start`. It binds to loopback by default; see the
[GUI deployment notes](gui/README.md#build-for-production) for configuration.
The supported single-host Ubuntu/systemd public-deployment profile and
host-specific acceptance steps are in [`docs/deployment.md`](docs/deployment.md).

The GUI uses `gui/structures/` by default. Point it at an existing Tarantino or
DVBfixer workspace without copying data by setting `DVBFIXER_GUI_DATA_DIR`.
Set `DVBFIXER_EXECUTABLE` when the executable is not directly on `PATH`. If it
needs a fixed argument prefix, provide `DVBFIXER_ARGS` as a JSON string array
(for example `["-m", "dvbfixer"]` with a Python executable).

Full install instructions (including the Modeller license step) are in [`docs/installation.md`](docs/installation.md).

Commands accept PDBx/mmCIF and small-molecule crystallographic CIF as input,
normalize them to a validated internal PDB, and retain the existing PDB output
contracts. See [CIF structure input](docs/cif-input.md) for chain-ID mapping,
metadata preservation, and fixed-column PDB limits.

## Testing

The PDB and FASTA inputs consumed by pytest are tracked under
[`tests/fixtures/`](tests/fixtures/README.md). Verify their integrity with
`sha256sum -c tests/fixtures/MANIFEST.sha256`, then run the fast suite with
`pytest -m 'not slow'`. Tests marked `slow` exercise full preparation and ZBS
pipelines and may require Modeller, AmberTools, OpenBabel, and other optional
chemistry backends.

## Commands

| Command | What it does |
|---------|--------------|
| [`split`](docs/commands/split.md) | Empirical chain splitting or REMARK 350/BIOMT biological-assembly extraction |
| [`renumber`](docs/commands/renumber.md) | FASTA/SEQRES renumbering OR antibody schemes (Kabat/Chothia/IMGT/Martin/Aho/EU) |
| [`model`](docs/commands/model.md) | Rebuild missing loops/gaps with Modeller's LoopModel |
| [`prepare`](docs/commands/prepare.md) | Missing-atom/H repair with the default legacy backend or opt-in pure-protein tleap-reduce, optional SMILES-guided ligand chemistry, and mutations |
| [`pull`](docs/commands/pull.md) | OpenMM partial minimization to form SS / glycosidic bonds |
| [`minimize`](docs/commands/minimize.md) | Energy minimization with selective restraints, optional xtb/obminimize refinement |
| [`protonate`](docs/commands/protonate.md) | PROPKA3 pKa prediction + AMBER residue renaming + H repair |
| [`rename`](docs/commands/rename.md) | Canonicalize residue names (AMBER/CHARMM/MSE → standard PDB) |
| [`atom-names`](docs/commands/atom-names.md) | Convert PDB residue/atom names for native AMBER/CHARMM or bundled GROMACS dialects without modifying the source |
| [`top`](docs/commands/top.md) | GROMACS topology from PDB/GRO (AMBER, CHARMM, or ACPYPE pipeline) |
| [`transplant`](docs/commands/transplant.md) | Transplant molecules between PDB structures (GLYCAM glycoprotein workflow) |
| [`convert`](docs/commands/convert.md) | Convert between PDB/AMBER/GLYCAM and CHARMM naming (sugars + protonation variants) |
| [`conect`](docs/commands/conect.md) | Infer missing CONECT records (SS, glycosidic, glycosylation) — runs automatically inside prepare/top/minimize/transplant/convert |
| [`cluster`](docs/commands/cluster.md) | Glycan conformational clustering from MD trajectories (GFDB-style) |
| [`homology`](docs/commands/homology.md) | Multi-template homology modeling with Modeller (antibody-aware) |
| [`msa`](docs/commands/msa.md) | Multiple protein-sequence alignment with MAFFT, MUSCLE 5, or Clustal Omega |
| [`salign`](docs/commands/salign.md) | Multiple structural superposition with Biopython (default) or Modeller SALIGN |
| [`parametrize`](docs/commands/parametrize.md) | GAFF2 + AM1-BCC/RESP small-molecule parametrization (GROMACS-ready) |
| [`component-info`](docs/commands/component-info.md) | Query authoritative wwPDB CCD chemistry and compare PDB component completeness |
| [`reconstruct-component`](docs/commands/reconstruct-component.md) | Reconstruct missing heavy atoms in one isolated Class A component from pinned CCD geometry |
| [`puppet`](docs/commands/puppet.md) | Strip a PDB to backbone-only polyglycine (template / visualization) |
| [`diagnose`](docs/commands/diagnose.md) | Report structure-quality issues (missing atoms, coincident atoms, valence, clashes, chirality) — report-only |
| [`doctor`](docs/commands/doctor.md) | Report installed backends, external executables, and OpenMM platforms |
| [`zbs`](docs/commands/zbs.md) | Full pipeline: renumber → model → prepare → minimize (PROPKA + Reduce run inside prepare) |

The [command index](docs/commands/index.md) groups the same commands by workflow stage.

Warnings and errors are printed with prominent terminal markers (and color on
interactive terminals). Every non-informational command repeats unique
warnings and errors in a diagnostic summary at the end of the run; `--log-file`
captures the same markers and summary without terminal escape codes.

## Batch mode: folder input

Batch mode runs the selected single-structure command independently on every
supported structure in a directory. One broken input does not prevent the
remaining structures from being processed. Outputs go into a separate
directory, and recursive input preserves the relative directory layout.

```bash
dvbfixer zbs --input-dir structures --output-dir fixed \
  --recursive --no-solvent
```

Supported commands are `split`, `renumber`, `model`, `pull`, `prepare`,
`minimize`, `protonate`, `rename`, `convert`, `conect`, `puppet`, `diagnose`,
and `zbs`. The remaining tools (`top`, `transplant`, `cluster`, `parametrize`,
`atom-names`, `component-info`, `reconstruct-component`, `homology`, `msa`, `salign`, and
`doctor`) remain explicit single-run workflows
because they have no per-structure directory operation. Every tool states its
status in its own `--help` and command guide; see the complete
[batch support matrix](docs/batch-mode.md#support-by-tool).

Batch processing continues after individual failures by default and prints a
success/failure summary. Add `--fail-fast` to stop at the first failure.
Shared batch options are matched by their complete names: a command's
`-o`/`--output` is never treated as an abbreviation for `--output-dir`.
For `diagnose`, exit status 1 means the analysis completed but found at least
one ERROR-severity structural issue; batch output labels these as `FINDINGS`
rather than execution failures and points to the per-structure report.

## Run logs and final numbering

Every command accepts `--log-file PATH`. DVBFixer appends a versioned UTC run
header and tees stdout/stderr from Python and child tools to that file while
retaining normal terminal output. Warning/error lines receive prominent plain
markers in logs and colored markers on interactive terminals. Runs with detected
warnings/errors end with a deduplicated diagnostic summary, including on exception
cleanup; clean runs do not emit an empty diagnostic banner.

`renumber`, `model`, and `zbs` accept `--number-from-1`. It shifts each final
chain so the first retained protein residue is 1 while preserving internal
gaps and relative heterogen numbering. ZBS applies this only to its completed
structure, immediately before postflight diagnose, so intermediate `.dat`
restraint identifiers remain stable.

Invalid counts, iteration limits, distances, radii, and cutoffs are rejected by
the command-line parser before a workflow starts. Structured selectors such as
`pull --bond`/`--anchor` and `top --ss`/`--his`/`--protonate` likewise fail with
a usage message when their shape, residue number, or state is invalid.

## Pipelines

End-to-end recipes — quick `zbs` one-liner, manual step-by-step, GLYCAM glycoprotein, CHARMM-GUI alternative, GROMACS topology export, glycan clustering, antibody homology, small-molecule parametrization — live in [`docs/pipelines.md`](docs/pipelines.md). For the all-in-one path, see [`zbs`](docs/commands/zbs.md).

## Known issues

See [`docs/known-issues.md`](docs/known-issues.md) for FF-template gaps (terminal ASH/GLH in AMBER14), mixed 1-4 scaling (ACPYPE workaround), Modeller alignment quirks, and other gotchas.

## More

- [`BEST_PRACTICES.md`](BEST_PRACTICES.md) — opinionated recipes and gotchas
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — module structure, key abstractions, design decisions
- [`AGENTS.md`](AGENTS.md) — canonical coding-agent instructions
- [`CLAUDE.md`](CLAUDE.md) — compact compatibility entry point for harnesses that discover that filename
- [`docs/agent/`](docs/agent/README.md) — task, contract, invariant, and focused-verification map
