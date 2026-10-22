# Pipelines

[User guide](README.md) · [Quick start](quick-start.md) · [Command index](commands/index.md)

These are independent recipes, not one long workflow. Replace the example input
files with your own. Start with a working [installation](installation.md), inspect
inputs with `diagnose`, and review outputs in a molecular viewer.

| Goal | Recipe |
|---|---|
| Run protein preparation in one command | [Full pipeline](#quick-full-pipeline-with-zbs) |
| Control intermediate files | [Step by step](#manual-step-by-step) |
| Prepare existing glycans | [GLYCAM](#glycoprotein-preparation-with-glycam) |
| Rename without structural repair | [Naming tools](#choose-a-naming-tool) |
| Export topology | [GROMACS](#gromacs-topology-generation) |
| Model an antibody from templates | [Homology](#homology-modeling-antibody-engineering) |

Minimization examples use `--no-solvent` for a shorter vacuum workflow. They do
not replace solvent equilibration or MD. All components need compatible chemistry
and parameters; see [force fields](force-fields.md).

## Quick: Full pipeline with `zbs`

Use for a protein with a complete SEQRES sequence, or supply a matching full-length
FASTA. MODELLER and its license are needed when missing regions must be built.

```bash
dvbfixer zbs input.pdb --fasta sequence.fasta --no-terminal --no-solvent -o finished.pdb
```

Omit `--fasta` when the input SEQRES is the intended complete sequence.
`--no-terminal` leaves missing terminal tails unmodeled while rebuilding internal
gaps. ZBS runs renumber → model → prepare → minimize, then postflight diagnostics.
PROPKA and Reduce run inside prepare; no separate protonation stage is required.

**Results:** `finished.pdb` and `finished.pdb.diagnose.json`.
Use `--keep-interim` to retain intermediate structures and sidecars, or `--dry-run`
to preview the plan. ERROR-level postflight findings warn by default; add
`--strict-postflight` to make them fail the run. See [zbs](commands/zbs.md).

## Manual: Step by step

Use when you want to inspect every stage. Supply `input.pdb` and a full-length
`sequence.fasta` with chain-ID headers such as `>chain_H` and `>chain_L`.
Chain IDs are case-sensitive. With correct SEQRES, omit both `--fasta` arguments.

```bash
dvbfixer renumber input.pdb --fasta sequence.fasta -o renumbered.pdb
dvbfixer model renumbered.pdb --fasta sequence.fasta --no-terminal -o modeled.pdb
dvbfixer prepare modeled.pdb -o prepared.pdb
dvbfixer minimize prepared.pdb --dat prepared.dat --no-solvent -o minimized.pdb
dvbfixer diagnose minimized.pdb
```

**Results:** each named PDB plus model/prepare `.dat` sidecars. Keep sidecars next
to their structures: prepare merges model repair metadata, and minimize uses it
for restraint selection. Inspect the rebuilt loops and diagnostic findings.

If an MD export lacks chain IDs, first use [split](commands/split.md) with an
explicit output and use that file as the pipeline input. Splitting does not
recover a missing complete sequence; provide FASTA for sequence-aware modeling.

### Optional: change pH after preparation

Re-protonation rebuilds hydrogens for a new chemical state; it is not a mandatory
follow-up to preparation:

```bash
dvbfixer protonate minimized.pdb --ph 6.5 -o reprotonated.pdb
dvbfixer diagnose reprotonated.pdb
```

Use [prepare mutations](commands/prepare.md#mutations) for explicit residue
substitutions, deletions, or variant overrides. Review attached-glycan removal
and disulfide-partner cleanup before applying mutations.

## Glycoprotein preparation with GLYCAM

Use for an existing glycoprotein with supported PDB-named sugars. Inspect glycan
composition and covalent links first. This recipe does not construct new glycans
or guarantee coverage for arbitrary ligands/cofactors.

```bash
dvbfixer convert crystal.pdb -o glycam.pdb
dvbfixer prepare glycam.pdb -o prepared.pdb
dvbfixer minimize prepared.pdb --dat prepared.dat --no-solvent -o minimized.pdb
dvbfixer diagnose minimized.pdb
dvbfixer top minimized.pdb --acpype -o gmx/
```

Skip conversion if input already uses correct GLYCAM naming. Preparation assigns
protein protonation states and adds hydrogens. Minimization restrains glycan
heavy atoms weakly, rather than leaving the entire glycan free to drift.
`top --acpype` requires AmberTools/ACPYPE and handles mixed AMBER/GLYCAM 1–4 scaling.

**Results:** prepared/minimized structures and a GROMACS topology bundle under
`gmx/`. Inspect topology-matched coordinates and glycosylation sites before MD.
See [ACPYPE mode](commands/top.md#acpype-mode---acpype) for details.

Unknown eligible organic ligands trigger automatic non-strict GAFF2 attempts in
minimize. Add `--parametrize-ligands` when failure must abort rather than fall back.
Complex cofactors such as FAD or HEM need validated parameters; missing atoms are
not repaired merely by supplying force-field XML. See [minimize](commands/minimize.md).

### Switching the same structure to CHARMM36

This is an alternative export path, not an additional required GLYCAM step:

```bash
dvbfixer convert minimized.pdb --to-charmm -o charmm.pdb
dvbfixer top charmm.pdb --ff charmm -o gmx_charmm/topol.top
```

Conversion changes naming; topology generation must still support every retained
component. See [convert](commands/convert.md) and [top](commands/top.md).

### Alternative: GLYCAM-Web workflow (for adding glycans from scratch)

Prepare your protein, extract the glycosylation-site residues in a molecular
editor as `donor.pdb`, and build glycans externally with GLYCAM-Web. Save the
returned structure as `glycam_output.pdb`.

```bash
dvbfixer transplant protein.pdb --donor donor.pdb --graft glycam_output.pdb \
  -o grafted.pdb
dvbfixer prepare grafted.pdb -o prepared.pdb
dvbfixer minimize prepared.pdb --dat prepared.dat --no-solvent -o minimized.pdb
dvbfixer diagnose minimized.pdb
dvbfixer top minimized.pdb --acpype -o gmx/
```

The donor must identify the matching acceptor residues. Inspect the graft and
linkage geometry; see [transplant](commands/transplant.md) for alignment options.

### Optional geometry refinement

OpenBabel and xtb post-passes are alternatives for particular geometry problems,
not substitutes for missing parameters during initial OpenMM setup. They do not
make arbitrary inputs supported. Read the limitations and interface-relaxation
caveats in [minimize](commands/minimize.md) before enabling them.

## Choose a naming tool

| Goal | Tool | Important difference |
|---|---|---|
| Standard parent residue names, e.g. HIE → HIS | [rename](commands/rename.md) | Removes variant labels; does not rebuild H |
| Native AMBER/CHARMM or GROMACS atom/residue labels | [atom-names](commands/atom-names.md) | Preserves known variants by default; explicit output required |
| Glycan conventions and protein variant translation | [convert](commands/convert.md) | Handles GLYCAM naming and linkage-dependent sugar identities |
| New pH-dependent state with hydrogen rebuilding | [protonate](commands/protonate.md) | Changes chemistry, not just labels |

For native AMBER labels without structural preparation:

```bash
dvbfixer atom-names input.pdb -o native.pdb --target-ff amber --profile standard
```

`atom-names --infer-protonation` is opt-in and recognizes represented site-H
patterns. It does not predict pKa, prove H completeness, or add/remove atoms.
None of these naming operations assigns force-field parameters by itself.

## GROMACS topology generation

Start with a prepared, inspected structure. Choose **one** compatible route:

```bash
dvbfixer top prepared.pdb --ff amber -o gmx_amber/
```

For CHARMM-compatible input instead:

```bash
dvbfixer top charmm.pdb --ff charmm -o gmx_charmm/
```

For GLYCAM input, use the [glycoprotein recipe](#glycoprotein-preparation-with-glycam).
The optional `--ff amber19sb` route is protein-only with stricter admission rules;
it is not the same namespace as OpenMM's `--ff amber19`.

**Results:** topology, modular includes, and topology-matched coordinates.
Use the generated coordinates rather than assuming the source PDB has the same
atom inventory/order. Export does not run solvation, ion addition, equilibration,
or production MD. GROMACS and suitable `.mdp` files are needed for those stages.

### Water and ions

For the AMBER RTP route, select a water model with `--water`; the default ion
set is matched automatically. For example:

```bash
dvbfixer top prepared.pdb --ff amber --water opc -o gmx_opc/
```

Do not mix unrelated ion and water parameter sets. CHARMM has its own supported
water choices. ACPYPE uses TIP3P and ignores `--water`/`--ion-set`; see
[water-matched ions](commands/top.md#water-matched-ions-amber).

For ACPYPE outputs with an `interchain_ss.itp` include containing
`[ intermolecular_interactions ]`, keep that include after all molecule entries,
including solvent/ions added by GROMACS. See [known issues](known-issues.md).

## Glycan conformational analysis

Use a topology and its matching MD trajectory, with supported glycan naming:

```bash
dvbfixer cluster topol.tpr md.xtc --plot
```

Inspect representative structures, the summary JSON, and HTML torsion plots.
See [cluster](commands/cluster.md) for clustering modes and output filenames.

## Homology modeling (antibody engineering)

Provide a full target FASTA and structurally related templates. Antibody mode
uses ANARCI for antibody-aware mapping:

```bash
dvbfixer homology target.fasta --template fab.pdb --template igg.pdb --antibody
```

Inspect target/template assignments and modeled regions. For selected parts of
multiple templates, use the [GUI Homology guide](gui-homology.md). For an existing
antibody structure with gaps, use [model](commands/model.md); for numbering
schemes, use [renumber](commands/renumber.md#antibody-schemes).

Model can save an ensemble with `--num-output`; each candidate has a matching
`.dat`. Default input pinning applies during loop-refinement MD, not the entire
initial optimization: it is not an exact-coordinate guarantee.

## Small molecule parametrization

Use an isolated eligible molecule with known chemistry and net charge. This
example assumes an acetate input with charge −1:

```bash
dvbfixer parametrize acetate.pdb -n ACET --net-charge -1
```

**Results:** `ACET.itp`, `ACET.gro`, and `posre_ACET.itp` in the selected output
directory. The default AM1-BCC path requires AmberTools. RESP is an explicit
alternative with a selected QM engine, not a universally better default.
See [parametrize](commands/parametrize.md) for charge methods, admission limits,
and combining ligand parameters with protein topology.

## See also

- [Batch mode and logging](batch-mode.md)
- [Force fields](force-fields.md)
- [Troubleshooting](known-issues.md)
