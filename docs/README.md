# User guide

[Project home](../README.md)

Start with a task. You do not need to read the architecture or research notes to
use DVBfixer. Examples use the command line; the [GUI guide](gui.md) explains
the graphical workflow.

## Start here

1. [Install DVBfixer](installation.md) and check the environment with `dvbfixer doctor`.
2. [Process a first structure](quick-start.md), then inspect its diagnostic report.
3. Choose a recipe below or open the [command index](commands/index.md).

## Choose a task

| Task | Guide |
|---|---|
| Repair atoms and add hydrogens | [Quick start](quick-start.md) |
| Rebuild missing protein sequence and minimize | [Full pipeline](pipelines.md#quick-full-pipeline-with-zbs) |
| Control preparation step by step | [Manual pipeline](pipelines.md#manual-step-by-step) |
| Prepare a glycoprotein | [GLYCAM workflow](pipelines.md#glycoprotein-preparation-with-glycam) |
| Change residue or atom names | [Choosing a naming tool](pipelines.md#choose-a-naming-tool) |
| Export GROMACS topology files | [Topology generation](pipelines.md#gromacs-topology-generation) |
| Build a model from templates | [Homology](commands/homology.md) or [GUI Homology](gui-homology.md) |
| Parameterize an isolated ligand | [Small molecules](commands/parametrize.md) |
| Analyze glycan trajectories | [Clustering](commands/cluster.md) |

## Common questions

- **Which files can I use?** Read [CIF input](cif-input.md). Most structure
  commands normalize CIF to PDB; individual commands may have narrower inputs.
- **Which force field should I choose?** Read [force fields](force-fields.md).
  Naming conversion alone does not parameterize a structure.
- **How do I process a folder or keep a log?** Read [batch mode and logging](batch-mode.md).
- **What does a warning mean?** Start with [troubleshooting](known-issues.md).
  `doctor` checks the environment; `diagnose` checks a structure.
- **Where are all the options?** The [CLI reference](reference/index.md) is
  generated from the program. Command guides explain typical use, not every flag.

## Terms used in this manual

- **Preparation:** repair missing atoms and place hydrogens; not full MD setup.
- **Modeling:** build coordinates for missing sequence or a target sequence.
- **Minimization:** relax coordinates under force-field restraints; not MD sampling.
- **Protonation:** select chemical states and rebuild the corresponding hydrogens.
- **Naming:** translate labels without adding atoms or predicting pKa.
- **Parameterization:** assign force-field parameters and charges.
- **Workspace:** a GUI project containing imported files, results, and tool state.
- **`.dat` sidecar:** atom-repair metadata used to select minimization restraints.
  Keep it beside its matching structure.

## Advanced material

Server operators should use the [deployment guide](deployment.md); integrations
use the [API guide](api.md). Implementation details live in
[architecture](../ARCHITECTURE.md) and [domain policies](domain-model.md).
Research notes describe experiments and proposals, not general user guarantees.
