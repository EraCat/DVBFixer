# Quick start

[User guide](README.md) · [Installation](installation.md) · [Recipes](pipelines.md)

This example starts with a single protein structure. Use your own `input.pdb`
or `input.cif`; replace the example filename in each command. For glycans,
ligands, or cofactors, check the [appropriate recipe](pipelines.md) first.

## 1. Check the environment and input

After [installation](installation.md), activate the environment and run:

```bash
micromamba activate dvbfixer
dvbfixer doctor
dvbfixer diagnose input.pdb
```

`doctor` reports missing tools and license problems. `diagnose` reports structural
findings without modifying the input. Its exit code `1` means ERROR-level findings
were found, not necessarily that analysis failed. Read the report before continuing.

## 2. Choose one preparation path

### Repair atoms in an otherwise complete protein

Use this when you do not need to build missing sequence regions:

```bash
dvbfixer prepare input.pdb -o prepared.pdb
dvbfixer minimize prepared.pdb --dat prepared.dat --no-solvent -o minimized.pdb
dvbfixer diagnose minimized.pdb
```

Preparation writes `prepared.pdb` and `prepared.dat`. Minimization reads that
sidecar to distinguish original atoms from repaired atoms. PROPKA and Reduce
already run during preparation by default; a separate `protonate` step is not
required.

### Rebuild gaps and run the full pipeline

Use `zbs` when the input has a correct complete SEQRES sequence, or provide a
matching full-length FASTA with `--fasta sequence.fasta`:

```bash
dvbfixer zbs input.pdb --no-terminal --no-solvent -o finished.pdb
```

`--no-terminal` leaves missing terminal tails unmodeled while retaining internal
gaps for reconstruction. MODELLER and its license are required when gaps are built.
The final structure is `finished.pdb`; the postflight report is
`finished.pdb.diagnose.json`.

Both examples use `--no-solvent` for a short, vacuum-minimization workflow.
This is not solvent equilibration or production MD. Omit the flag only when you
intend the slower solvent-box minimization described in [minimize](commands/minimize.md).

## 3. Inspect the result

- Read warnings, errors, and the final diagnostic summary.
- Open the structure in the [GUI](gui.md) or another molecular viewer.
- Check rebuilt regions, chain identities, retained ligands, and covalent links.
- Keep each `.dat` file with the structure it describes; do not mix sidecars
  from unrelated outputs.

Successful execution does not prove that a model is experimentally correct or
ready for simulation. Follow the [recipes](pipelines.md) for topology export
and system-specific limits.
