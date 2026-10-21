# Command index

[← README](../../README.md)

Every `dvbfixer` subcommand has its own page. The first column is alphabetical; the workflow group hints at where each command typically sits in a pipeline.

Commands that accept directory input document it on their own page; see the
shared [Batch mode guide](../batch-mode.md) for supported tools and failure
behavior.

Structure inputs may be PDB, PDBx/mmCIF, or small-molecule crystallographic
CIF unless a command documents a narrower molecular requirement. See the
[CIF input guide](../cif-input.md) for conversion and chain-mapping behavior.

The dispatcher, generated CLI reference, and GUI command schema share one
declarative registry for command names, modules, workflow categories, batch
support, output behavior, and accepted success codes. Adding or changing a
public command therefore updates all three surfaces from the same contract.

| Command | What it does | Workflow group |
|---------|--------------|----------------|
| [`atom-names`](atom-names.md) | Convert PDB residue/atom names for native AMBER/CHARMM or bundled GROMACS dialects without modifying the source | Utilities |
| [`cluster`](cluster.md) | Glycan conformational clustering from MD trajectories (GFDB-style) | Analysis |
| [`component-info`](component-info.md) | Query wwPDB CCD chemistry and compare heavy-atom completeness | Topology & chemistry |
| [`conect`](conect.md) | Infer missing CONECT records (SS, glycosidic, glycosylation) into a PDB | Utilities |
| [`convert`](convert.md) | Convert between PDB/AMBER/GLYCAM and CHARMM naming (sugars + protonation variants); bidirectional | Glycoprotein prep |
| [`diagnose`](diagnose.md) | Report structure-quality issues without modifying the input | Analysis |
| [`doctor`](doctor.md) | Report installed backends, executables, and OpenMM platforms | Utilities |
| [`homology`](homology.md) | Multi-template homology modeling with Modeller (antibody-aware) | Modeling |
| [`msa`](msa.md) | Multiple protein-sequence alignment using MAFFT, MUSCLE 5, or Clustal Omega | Modeling |
| [`minimize`](minimize.md) | Energy minimization with OpenMM + selective restraints, optional xtb/obminimize refinement | Refinement |
| [`model`](model.md) | Rebuild missing loops/gaps with Modeller's LoopModel | Structure prep |
| [`parametrize`](parametrize.md) | GAFF2 + AM1-BCC/RESP small-molecule parametrization (GROMACS-ready) | Topology |
| [`prepare`](prepare.md) | PDBFixer missing-atom/H repair; optional SMILES-guided ligands; substitution and deletion mutations | Structure prep |
| [`protonate`](protonate.md) | PROPKA3 pKa prediction + AMBER residue renaming + H repair | Refinement |
| [`pull`](pull.md) | OpenMM partial minimization to form bonds (SS, glycosidic) | Refinement |
| [`puppet`](puppet.md) | Strip a PDB to backbone-only polyglycine (template / visualization) | Utilities |
| [`rename`](rename.md) | Canonicalize residue names (AMBER/CHARMM/MSE → standard PDB) | Utilities |
| [`renumber`](renumber.md) | FASTA/SEQRES renumbering OR antibody schemes (Kabat/Chothia/IMGT/Martin/Aho/EU) | Structure prep |
| [`reconstruct-component`](reconstruct-component.md) | Reconstruct one isolated Class A component from pinned CCD ideal geometry | Topology & chemistry |
| [`salign`](salign.md) | Sequence-guided Cα superposition with Biopython by default; optional Modeller SALIGN | Modeling |
| [`split`](split.md) | Empirical PDB/GRO chain splitting or REMARK 350/BIOMT assembly extraction | Structure prep |
| [`top`](top.md) | GROMACS topology from PDB/GRO (AMBER, CHARMM, or ACPYPE pipeline) | Topology |
| [`transplant`](transplant.md) | Transplant molecules between PDB structures (GLYCAM glycoprotein workflow) | Glycoprotein prep |
| [`zbs`](zbs.md) | Full pipeline: renumber → model → prepare → minimize (PROPKA + Reduce run inside prepare) | Pipeline |

## See also

- [Batch mode](../../README.md#batch-mode-folder-input) — folder processing for single-structure commands
- [CIF input](../cif-input.md) — supported dialects, metadata, and PDB limits

- [Force fields](../force-fields.md) — short-name aliases (`--ff amber`, `--ff charmm`, `--ff amber+glycam`, …), auto-detection rules, the two `--ff` namespaces
- [Pipelines](../pipelines.md) — end-to-end recipes
- [Known issues](../known-issues.md)
- [BEST_PRACTICES.md](../../BEST_PRACTICES.md) — recipe collection + gotchas
- [ARCHITECTURE.md](../../ARCHITECTURE.md) — module structure + key abstractions
