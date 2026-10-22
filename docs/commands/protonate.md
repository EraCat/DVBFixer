# `dvbfixer protonate`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/protonate.md)

Uses PROPKA to select supported protein protonation states at a target pH,
then rebuilds corresponding hydrogens. Reduce supplies neutral HIS tautomer
selection and ASN/GLN flip decisions by default.

Use for re-protonation, not label-only conversion. [prepare](prepare.md) already
runs PROPKA/Reduce, so this is not a mandatory extra preparation stage.

## Quick start

```bash
dvbfixer protonate prepared.pdb --ph 6.5 -o reprotonated.pdb
dvbfixer diagnose reprotonated.pdb
```

**Input:** a repaired structure with complete relevant heavy atoms.
**Result:** `reprotonated.pdb` with supported state labels and rebuilt H.
Read warnings about unsupported states, and inspect modified regions.

## Protonation Logic

| Family | Supported AMBER identities | Decision |
|---|---|---|
| HIS | HID, HIE, HIP | PROPKA selects charged HIP; Reduce selects neutral tautomer |
| ASP | ASP, ASH | pKa-dependent carboxyl state |
| GLU | GLU, GLH | pKa-dependent carboxyl state |
| CYS | CYS, CYM, CYX | Free thiol/thiolate versus disulfide; see below |
| LYS | LYS, LYN | pKa-dependent charged or neutral amine |

Supported force-field templates limit which states can be represented. TYR/ARG
PROPKA results do not create new TYD/TYN/ARN templates. With CHARMM output, some
AMBER-requested states cannot be expressed by the shipped OpenMM XML and revert
to parent names with warnings. Read [force fields](../force-fields.md) rather
than assuming all naming vocabularies imply supported charge models.

### Cysteine: `CYS`, `CYM`, and `CYX`

`--cys-disulfide-pka` does not set a predicted pKa. It recognizes PROPKA's high
disulfide sentinel; the default threshold is `99.99`.

- Explicit/inferred SG–SG bonds assign both linked residues to `CYX`.
- For an unlinked cysteine, predicted pKa below target pH selects thiolate `CYM`.
- A PROPKA disulfide sentinel selects `CYX`; otherwise the state is thiol `CYS`.

Changing the sentinel threshold does not disable thiolate selection.
`--no-propka` disables pKa-driven decisions, not necessarily every connectivity-
or Reduce-derived decision. A final CYM identity is intentional for a free
thiolate; absence of SG–H alone is not proof of a disulfide.

## Usage

### Print the pKa summary

```bash
dvbfixer protonate prepared.pdb --summary -o reprotonated.pdb
```

### Choose a neutral HIS fallback

```bash
dvbfixer protonate prepared.pdb --his-default HID -o reprotonated.pdb
```

The fallback is used when no usable neutral tautomer decision is available.
It does not override a pKa-driven charged HIP decision.

### Disable one decision engine

To use PROPKA without Reduce:

```bash
dvbfixer protonate prepared.pdb --no-protassign -o reprotonated.pdb
```

To use Reduce without pKa-driven reassignment:

```bash
dvbfixer protonate prepared.pdb --no-propka -o reprotonated.pdb
```

These are alternatives. Disabling both engines is rejected. This tool is not a
general ligand titration service; supplied ligand chemistry needs separate review.

## ProtAssign-style optimisation (`--protassign`, default ON)

MolProbity Reduce evaluates local H-bond geometry and clashes. DVBfixer uses
its neutral HIS HID/HIE choice and ASN/GLN atom-position swaps; PROPKA's charged
HIP decision takes priority. GLYCAM attachment sites are handled separately
because their sidechains have different chemistry.

The `reduce` executable is required for this default step. Install the explicit
Reduce package using the [installation guide](../installation.md#ambertools-and-molprobity-reduce),
select a local binary with `--protassign-binary PATH`, or deliberately disable
the step with `--no-protassign`. It is not assumed to come from AmberTools.

Method reference: Word JM, Lovell SC, Richardson JS, Richardson DC (1999),
*J Mol Biol* 285, 1735. [PubMed 9917408](https://pubmed.ncbi.nlm.nih.gov/9917408/).

## Options

Common choices are `--ph`, `--ff`, `--summary`, `--his-default`, and
`--keep-water`. The [generated reference](../reference/protonate.md) lists all
options and defaults.

`--no-hydrogens` performs label-only reassignment without rebuilding the H
inventory. Existing H can then conflict with the assigned state; do not use it
as a substitute for chemically consistent re-protonation in a normal pipeline.

## How it works

Protein variant identities are preserved while structures are normalized for
OpenMM parsing and H placement. For GLYCAM input, protein attachment residues are
temporarily mapped for analysis and restored afterward. Protein variants are
written as ATOM records. Detailed implementation and historical repair notes
are in [architecture](../../ARCHITECTURE.md) and
[historical troubleshooting](../known-issues-history.md).

## Batch mode

```bash
dvbfixer protonate --input-dir prepared --output-dir reprotonated --ph 6.5
```

The same pH and options apply to every input. See [batch mode](../batch-mode.md).

## See also

- [prepare](prepare.md) — repair atoms before re-protonation
- [atom-names](atom-names.md) — naming without pKa prediction or H rebuilding
- [minimize](minimize.md) — coordinate relaxation when needed after inspection
