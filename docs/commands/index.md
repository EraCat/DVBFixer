# Command index

[User guide](../README.md) · [Recipes](../pipelines.md) · [CLI reference](../reference/index.md)

Choose by task below. Each command page starts with practical usage and links
to its generated reference for exact flags and defaults.

## Check an environment or structure

| Command | Purpose |
|---|---|
| [doctor](doctor.md) | Installed backends, executables, licenses, and platforms |
| [diagnose](diagnose.md) | Structural findings without modifying coordinates |
| [component-info](component-info.md) | CCD chemistry and heavy-atom completeness |

## Prepare a structure

| Command | Purpose |
|---|---|
| [zbs](zbs.md) | Combined renumber → model → prepare → minimize pipeline |
| [split](split.md) | Empirical chain assignment or metadata-defined biological assembly |
| [renumber](renumber.md) | Full-sequence positions or antibody numbering schemes |
| [model](model.md) | Coordinates for missing protein sequence |
| [prepare](prepare.md) | Missing-atom repair, hydrogen placement, mutations, and caps |
| [minimize](minimize.md) | Coordinate relaxation with selective restraints |
| [protonate](protonate.md) | Reassign supported pH-dependent states and rebuild H |
| [pull](pull.md) | Local relaxation to bring selected bond endpoints together |
| [conect](conect.md) | Explicit inference of missing connectivity records |

## Change naming

| Command | Purpose |
|---|---|
| [rename](rename.md) | Canonical parent residue names, without H rebuilding |
| [atom-names](atom-names.md) | Native or GROMACS atom/residue labels; optional observed-H inference |
| [convert](convert.md) | GLYCAM/CHARMM glycan conventions and protein variants |

See [choosing a naming tool](../pipelines.md#choose-a-naming-tool) before
using these commands interchangeably. Naming is not parameterization.

## Model and compare sequences or templates

| Command | Purpose |
|---|---|
| [homology](homology.md) | Target modeling from one or more templates |
| [msa](msa.md) | Multiple protein-sequence alignment with external engines |
| [salign](salign.md) | Sequence-guided structural superposition |
| [puppet](puppet.md) | Backbone-only polyglycine scaffold |

## Glycans, ligands, topology, and trajectories

| Command | Purpose |
|---|---|
| [transplant](transplant.md) | Transfer selected components or graft external glycan-builder output |
| [reconstruct-component](reconstruct-component.md) | Fixed-anchor reconstruction of one eligible isolated component |
| [parametrize](parametrize.md) | GAFF2/charge assignment for eligible isolated small molecules |
| [top](top.md) | GROMACS topology and matching coordinates |
| [cluster](cluster.md) | Glycan conformational clustering from trajectories |

## Shared behavior

Most structure commands accept PDB or normalized [CIF input](../cif-input.md);
individual guides document narrower input requirements. Directory support is
listed in the [batch matrix](../batch-mode.md#support-by-tool). Every command
accepts [run logging](../batch-mode.md#run-logs).

See [force fields](../force-fields.md) for compatible aliases and
[troubleshooting](../known-issues.md) for limitations.
