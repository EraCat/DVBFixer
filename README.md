# dvbfixer

Prepare structural biology files from PDB and CIF inputs: repair missing atoms,
rebuild protein gaps, assign protonation states, minimize structures, and export
GROMACS topologies. Use the command line or the browser-based GUI with Mol*.

Current release: **0.9.1**.

## Install

With [micromamba](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html)
installed, clone this repository and create the scientific environment:

```bash
git clone https://github.com/lilpoundcake/DVBFixer.git
cd DVBFixer
micromamba create -f environment.yml
micromamba activate dvbfixer
pip install -e .
dvbfixer doctor
```

MODELLER requires a license for gap rebuilding and comparative modeling.
See [installation](docs/installation.md) for the license step, dependencies,
and environment troubleshooting.

## First structure

For a protein with no missing sequence regions, repair its atoms and hydrogens:

```bash
dvbfixer prepare input.pdb -o prepared.pdb
dvbfixer diagnose prepared.pdb
```

This writes `prepared.pdb` and a `prepared.dat` sidecar for later minimization.
Inspect the diagnostic findings before using the structure downstream.
Preparation is not a guarantee of MD readiness for arbitrary ligands or cofactors.

For gap rebuilding and minimization, follow the [quick start](docs/quick-start.md)
or choose an [end-to-end recipe](docs/pipelines.md).

## Open the GUI

Keep the `dvbfixer` environment active. With Node.js 22 or newer installed:

```bash
cd gui
npm ci
npm run dev
```

The local development server opens the browser. Follow the
[GUI guide](docs/gui.md) to import files, run tools, and inspect results.

## User manual

| I want to… | Read |
|---|---|
| Find my starting point | [User guide](docs/README.md) |
| Process my first structure | [Quick start](docs/quick-start.md) |
| Prepare proteins, glycans, or topology inputs | [Recipes](docs/pipelines.md) |
| Find a particular tool | [Command index](docs/commands/index.md) |
| Look up exact CLI options | [CLI reference](docs/reference/index.md) |
| Process a folder or save logs | [Batch mode and logging](docs/batch-mode.md) |
| Choose a force field | [Force fields](docs/force-fields.md) |
| Understand CIF conversion | [CIF input](docs/cif-input.md) |
| Resolve an error or limitation | [Troubleshooting](docs/known-issues.md) |

## Developers and administrators

- [GUI setup and server configuration](gui/README.md)
- [API](docs/api.md) and [public deployment](docs/deployment.md)
- [Architecture](ARCHITECTURE.md) and [domain policies](docs/domain-model.md)
- [Agent instructions](AGENTS.md) and [task map](docs/agent/README.md)

Scientific inputs are tracked in [tests/fixtures](tests/fixtures/README.md).
After installing development extras with `pip install -e ".[dev]"`, run
`pytest -m 'not slow' -q`. The full suite needs the external scientific tools
declared in `environment.yml`.
