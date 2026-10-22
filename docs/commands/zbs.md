# `dvbfixer zbs`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/zbs.md)

Runs the combined structure-preparation pipeline:
**renumber → model → prepare → minimize**.
Use individual commands when you need to inspect or customize each intermediate.

## Quick start

```bash
dvbfixer zbs input.pdb --no-terminal --no-solvent -o finished.pdb
```

**Input:** a structure with correct complete SEQRES, or add
`--fasta sequence.fasta`. MODELLER needs a license when gaps are rebuilt.
**Results:** `finished.pdb` and `finished.pdb.diagnose.json`.

`--no-terminal` leaves missing terminal tails unmodeled while rebuilding internal
gaps. `--no-solvent` selects shorter vacuum minimization, not solvent equilibration.

## Pipeline

| Stage | Purpose |
|---|---|
| [renumber](renumber.md) | Align residue numbering to the complete sequence |
| [model](model.md) | Rebuild missing sequence regions |
| [prepare](prepare.md) | Repair atoms and place H using selected protein states |
| [minimize](minimize.md) | Relax coordinates using the repair metadata |
| [diagnose](diagnose.md) | Report remaining structural findings |

PROPKA and Reduce run inside prepare. No separate protonation or label-restoration
stage is required. Re-run [protonate](protonate.md) only when you intend to derive
states again, for example at a different pH.

## Defaults and limits

- Preparation uses `legacy` by default. The pure-protein `tleap-reduce` backend
  is opt-in and rejects unsupported residue classes and mutations.
- Modeling uses MODELLER by default. `--model-backend` and preparation's
  `--backend` choose different stages; neither selects a different minimizer.
- Intermediate files are cleaned up unless `--keep-interim` is enabled. Named
  intermediates live beside the final output, including during batch runs.
- Waters are removed by default. `--keep-water` preserves input crystallographic
  waters through all enabled stages, not temporary minimization solvent.
- Whole-complex minimization still requires compatible parameters for every
  retained component. A pipeline does not make arbitrary cofactors supported.

## Usage

### Supply a complete sequence and pH

```bash
dvbfixer zbs input.pdb --fasta sequence.fasta --ph 6.5 \
  --no-terminal --no-solvent -o finished.pdb
```

FASTA headers identify exact chain IDs, for example `>chain_H` and `>chain_L`.
Use the intended full sequence, not just the residues visible in the structure.

### Preview or retain intermediates

```bash
dvbfixer zbs input.pdb --no-solvent --dry-run
```

Dry run prints stages and paths without processing the structure. For a real
run with inspectable intermediates:

```bash
dvbfixer zbs input.pdb --no-solvent --keep-interim -o finished.pdb
```

### Skip stages deliberately

```bash
dvbfixer zbs input.pdb --skip-model --skip-minimize -o prepared_only.pdb
```

Use when you intend to omit gap reconstruction and relaxation. Stage skips do
not establish that the skipped work was unnecessary. Each enabled stage must
still receive a suitable input.

### Require a clean postflight

```bash
dvbfixer zbs input.pdb --no-terminal --no-solvent --strict-postflight -o finished.pdb
```

ERROR-level findings warn by default because some findings need scientific
interpretation. `--strict-postflight` makes them fail the pipeline. It is not an
atomic rollback: inspect any output and report already written by the failed run.
Use `--no-postflight` only when you validate separately.

## Options

Use the [generated reference](../reference/zbs.md) for exact flags and defaults.
Important decisions are grouped by stage:

### General

`--ff`, `--ph`, `--atom-naming`, output paths, `--keep-interim`, and
`--number-from-1`. Final numbering normalization runs before postflight without
changing intermediate sidecar identities.

### `renumber` (step 1)

`--skip-renumber` skips full-sequence renumbering.

### `model` (step 2)

`--fasta`, `--no-terminal`, `--num-loops`, `--num-output`, and `--pin-input`.
Pinning applies during MODELLER loop-refinement MD, not the entire initial
optimization. See [model](model.md) for candidate outputs and experimental scope.

### `prepare` (step 3)

`--backend`, `--mutate`, `--smiles`, `--cap-termini`, `--cap-chain`,
`--no-propka`, and `--no-protassign`. See [prepare](prepare.md) for mutation
dependency cleanup and authoritative ligand chemistry restrictions.

### `minimize` (step 4)

`--no-solvent`, `--max-iter`, `--restraint-k`, `--parametrize-ligands`, and
optional `--refine`. A post-pass does not bypass an earlier parameter/setup
rejection. See [minimize](minimize.md).

## Experimental modeling

`--model-backend diffusion` requires an independently installed compatible runner.
The full model bundle is retained even without `--keep-interim`. Only a verified,
accepted ranked candidate is handed to prepare/minimize; rejected or corrupted
bundles are not silently replaced by MODELLER results.
Follow [model scope](model.md#experimental-diffusion-scope) and the selected
runner's installation guide before enabling it.

## How it works

Repair metadata flows from model through prepare into minimize's restraint
selection. Outputs are aligned back to the original protein backbone frame by
default; `--no-align-to-input` disables this. Alignment moves protein and retained
components together, not independently.

## Batch mode

```bash
dvbfixer zbs --input-dir structures --output-dir fixed --recursive --no-solvent
```

Each input has its own pipeline and outputs. See [batch mode](../batch-mode.md).

## See also

- [Quick start](../quick-start.md)
- [Manual recipe](../pipelines.md#manual-step-by-step)
- [Troubleshooting](../known-issues.md)
