# Best practices for using dvbfixer

[User guide](docs/README.md) · [Recipes](docs/pipelines.md)

The maintained recipe collection is now [Pipelines](docs/pipelines.md).
Use that page for command sequences; this entry point remains for existing links.

## Choose a workflow

- [First structure](docs/quick-start.md)
- [Full protein pipeline](docs/pipelines.md#quick-full-pipeline-with-zbs)
- [Step-by-step preparation](docs/pipelines.md#manual-step-by-step)
- [Glycoproteins with GLYCAM](docs/pipelines.md#glycoprotein-preparation-with-glycam)
- [Naming tools](docs/pipelines.md#choose-a-naming-tool)
- [GROMACS export](docs/pipelines.md#gromacs-topology-generation)
- [Small-molecule parameters](docs/commands/parametrize.md)

## Before using an output

Inspect diagnostic findings and modeled regions. Keep matching `.dat` sidecars,
confirm retained ligands and covalent links, and choose compatible parameters
for every component. Naming conversion does not parameterize a structure;
minimization does not establish experimental correctness or MD readiness.

See [force-field selection](docs/force-fields.md) and
[known limitations](docs/known-issues.md) for system-specific decisions.
