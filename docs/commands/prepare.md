# `dvbfixer prepare`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/prepare.md)

Repairs missing atoms and places hydrogens. Use it for atom-level preparation;
use [model](model.md) first when missing protein sequence needs explicit loop
modeling, or [zbs](zbs.md) for the combined workflow.

## Quick start

```bash
dvbfixer prepare input.pdb -o prepared.pdb
```

**Input:** a structure with correct chain identities and intended retained components.
Most CLI structure inputs also accept [CIF](../cif-input.md).
**Outputs:** `prepared.pdb` and `prepared.dat`. Keep the sidecar for
[minimization](minimize.md); it records repaired atoms and variant overrides.

## Defaults and limits

- The default `legacy` backend handles the supported protein, glycan, ligand,
  and covalently linked heterogen input classes. This does not mean every
  arbitrary ligand or cofactor can be repaired or parameterized.
- Heterogens are retained and hydrogen addition is attempted. Use
  `--strip-heterogens` to remove them, or `--no-heterogen-h` to retain them
  without adding their H atoms. Waters require `--keep-water`.
- PROPKA selects pH-dependent protein states; MolProbity Reduce selects HIS
  tautomers and detects ASN/GLN flips. A separate `protonate` stage is not required.
- Known explicit input variants and `--mutate` overrides guide hydrogen placement.
- CONECT inference runs by default. Use `--no-infer-conect` only when you intend
  to rely on existing connectivity; inspect covalent links in either case.
- Hydrogen placement is not force-field parameterization. Unknown ligands may
  need [parametrize](parametrize.md) or strict ligand setup in [minimize](minimize.md).

## Usage

### Keep crystallographic waters

```bash
dvbfixer prepare input.pdb --keep-water -o prepared.pdb
```

### Prepare protein only

```bash
dvbfixer prepare input.pdb --strip-heterogens -o protein.pdb
```

Unlike minimize's similarly named option, this removes heterogens from the
prepared structure. Check whether your protein depends on a cofactor or ligand
before choosing it.

### Set pH or a HIS fallback

```bash
dvbfixer prepare input.pdb --ph 6.5 --his-default HID -o prepared.pdb
```

`--his-default` applies when a neutral HIS has no usable Reduce tautomer result.
`--no-propka` and `--no-protassign` disable those individual steps. The
`--cys-ss-pka` setting recognizes PROPKA's disulfide sentinel, not an alternative
CYS pKa. See [cysteine states](protonate.md#cysteine-cys-cym-and-cyx).

### Supply authoritative ligand chemistry

```bash
dvbfixer prepare complex.pdb --smiles 'LIG=C[NH3+]' -o prepared.pdb
```

Replace the example mapping with the actual chemistry of your ligand. Repeat
`--smiles` for different residue names. It supports isolated small molecules
contained in one residue, preserves heavy-atom names and coordinates, and refuses
incompatible/ambiguous graphs or externally covalent residues rather than guessing.

The SMILES selects bond orders, formal charge, and protonation for matching
residues; `--ph` does not titrate those ligands. Unmapped ligands retain automatic
handling. This option requires `legacy` and cannot be combined with
`--strip-heterogens` or `--no-heterogen-h`.

## Mutations

Substitute a residue or delete it using an exact, case-sensitive chain ID:

```bash
dvbfixer prepare input.pdb --mutate A:39:ALA -o substituted.pdb
dvbfixer prepare input.pdb --mutate H:100A:del -o deleted.pdb
```

These are alternative examples. Repeat `--mutate` for multiple changes.
Deletion supports insertion codes; substitution does not. Do not request both
substitution and deletion for the same residue.

Review these consequences before running:

- Changing/removing a glycosylation-site anchor can remove its attached glycan tree.
- Changing/removing a disulfide CYS repairs its surviving partner to CYS and
  removes the broken disulfide annotation.
- A variant-only override such as `A:83:HIP` does not change the parent residue
  and therefore does not trigger parent-change dependency cleanup.
- Affected LINK records are removed with warnings; inspect the remaining partner.
- Internal deletion can leave distant flanking residues. A warning is not proof
  of successful loop closure; inspect the result and consider modeling or pulling.

## Terminal caps

```bash
dvbfixer prepare input.pdb --cap-termini --cap-chain A --cap-chain B \
  --ff amber -o capped.pdb
```

Omit `--cap-chain` to select all protein chains. Use `_` for a blank chain ID.
ACE/NME caps are explicit residues; existing correct caps are retained. Missing
requested chains warn while the selected existing chains are still processed.

## Backend and naming choices

| Choice | Use |
|---|---|
| `--backend legacy` | Default; supports the broadest input classes |
| `--backend tleap-reduce` | Opt-in AMBER pure-protein path; requires tleap and Reduce; rejects non-canonical residues and mutations |
| `--atom-naming gromacs` | Default output naming |
| `--atom-naming standard` | Native output atom naming rather than GROMACS aliases |

GLYCAM-named glycans are handled using their templates. Protein attachment
residues become NLN/OLS/OLT only when the attached sugar is GLYCAM-named, not
merely because a PDB-named sugar is present. See the [glycoprotein recipe](../pipelines.md#glycoprotein-preparation-with-glycam).

## Options

The [generated reference](../reference/prepare.md) lists all flags and defaults.
The examples above cover common decisions; consult [force fields](../force-fields.md)
before supplying custom `--ff` values.

## The .dat File

The sidecar records added atoms, variant overrides, and mutation cleanup metadata.
Preparation merges matching upstream model metadata so minimize can distinguish
original atoms from rebuilt atoms. Custom output `prepared.pdb` produces
`prepared.dat`; `--dat` can select an explicit path.

Do not reuse a sidecar from an unrelated structure or edit it just to suppress
warnings. Advanced tooling should use the canonical `DatRecord` schema described
in [architecture](../../ARCHITECTURE.md).

## How it works

### Who places hydrogens?

On the legacy path, PDBFixer rebuilds heavy atoms, PROPKA/Reduce analyze the
completed heavy-atom structure, and OpenMM places protein hydrogens with explicit
variants. Supported heterogens use their template or chemistry-specific handling.
The alternative tleap-reduce path delegates heavy atoms to tleap and H to Reduce.

The pipeline also normalizes protein ATOM/HETATM records and malformed connectivity
before scientific parsing. Implementation contracts and repair invariants belong
in the [agent preparation context](../agent/README.md), not in user recipes.

## Batch mode

```bash
dvbfixer prepare --input-dir structures --output-dir prepared --recursive
```

Each structure is processed independently. See [batch mode](../batch-mode.md).

## See also

- [model](model.md) — rebuild missing sequence first
- [minimize](minimize.md) — relax coordinates using the matching sidecar
- [diagnose](diagnose.md) — inspect findings without changing coordinates
- [Pipelines](../pipelines.md) — complete recipes
