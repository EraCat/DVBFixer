# Troubleshooting and known limitations

[User guide](README.md) · [Installation](installation.md) · [Recipes](pipelines.md)

Start with the symptom, not the implementation history. Keep the full run log
when reporting a problem; warnings often explain why a fallback was selected.

## Find the right check

| Symptom | First action |
|---|---|
| Missing tool, import failure, license error | Run `dvbfixer doctor` in the active environment |
| Structure has clashes, broken geometry, or missing atoms | Run `dvbfixer diagnose input.pdb` |
| GUI cannot find a newly installed executable | Restart its server in the correct environment |
| Model cannot place sequences | Check full sequence and case-sensitive FASTA chain IDs |
| Force-field template mismatch | Check component completeness, naming, and parameters |
| Output naming is unexpected | Check profile and distinguish naming from protonation |

## Save a useful log

Every command accepts `--log-file PATH`. For example:

```bash
dvbfixer prepare input.pdb -o prepared.pdb --log-file prepare.log
```

The log captures Python and inherited child-process output. It appends a versioned
UTC run header and includes a deduplicated warning/error summary when findings
exist. A clean run has no empty warning banner. See [batch mode and logging](batch-mode.md).

## Diagnostics report errors after a completed run

`diagnose` exit code `1` means analysis found ERROR-level structural findings.
It is not by itself an execution failure. Inspect the affected residues and
choose the appropriate repair tool; do not just suppress the report.

ZBS warns about postflight findings by default. Use `--strict-postflight` when
those findings must fail a pipeline. Read [diagnose](commands/diagnose.md) for
severity meanings and [zbs](commands/zbs.md) for postflight options.

## Missing MODELLER, Reduce, or sequence aligners

- Configure the [MODELLER license](installation.md#modeller-installation-and-license)
  for gap rebuilding and comparative modeling.
- Install [AmberTools and Reduce](installation.md#ambertools-and-molprobity-reduce).
  Missing Reduce is fatal for explicit `tleap-reduce`; legacy preparation can
  warn and use its documented fallback, which is not evidence that Reduce ran.
- Check [MSA engines](installation.md#multiple-sequence-alignment-executables)
  with `dvbfixer msa --list-engines`. MUSCLE must be v5.

## Missing sequence or incorrect chain mapping

Modeling needs the intended complete sequence, from SEQRES or `--fasta`.
FASTA headers must encode chain IDs: `>chain_H`, `>1abc_H`, or `>H`.
Chains `H` and `h` are different; sequences are not assigned by file order.

Use `--no-terminal` to omit missing N/C tails, not to erase internal gaps.
Inspect repeated-sequence alignments and modeled regions. See [model](commands/model.md).

## No force-field template for a ligand or cofactor

Naming, atom completeness, and parameterization are separate requirements.
Supplying an XML parameter file does not reconstruct missing cofactor atoms.

- Use [component-info](commands/component-info.md) to inspect CCD chemistry and
  heavy-atom completeness.
- Use authoritative `prepare --smiles` only for matching isolated single-residue
  ligands; it does not support externally covalent components.
- Minimize automatically attempts GAFF2 for eligible unknown organic ligands.
  Explicit `--parametrize-ligands` makes parameterization failure fatal.
- Protected cofactors such as FAD/HEM require validated state-specific parameters;
  they are not admitted to generic GAFF merely because automatic mode is non-strict.
- `minimize --strip-heterogens` excludes heterogens from optimization and restores
  them afterward. It does not jointly relax a noncovalent ligand and its pocket.

Inspect warnings and retained components in the output. See [minimize](commands/minimize.md)
and [force fields](force-fields.md).

## Glycan naming, connectivity, or drift

Use the [GLYCAM recipe](pipelines.md#glycoprotein-preparation-with-glycam) for
compatible AMBER/GLYCAM preparation and ACPYPE export. PDB names such as NAG do
not by themselves select the corresponding GLYCAM templates.

Preparation uses NLN/OLS/OLT only when the attached sugar is GLYCAM-named.
Automatic CONECT inference supplements input connectivity, but inspect links
and sugar identities rather than assuming all deposited annotations are complete.
Use [conect](commands/conect.md) for an explicit preprocessing report.

Glycan heavy atoms have weak positional restraints during minimize, not zero
restraints. A grossly displaced or clashing tree still requires investigation.
Optional universal-force-field post-passes do not replace valid initial setup.

## Unexpected residue or hydrogen names

- `rename` folds variants to parent names without rebuilding H.
- `atom-names` translates target-specific labels and preserves known variants by
  default. Its opt-in inference reads represented H patterns, not predicted pKa.
- `protonate` chooses supported states and rebuilds hydrogens.

Choose the intended [naming tool](pipelines.md#choose-a-naming-tool). Use native
`standard` or consumer-specific `gromacs` naming deliberately; they are not
interchangeable. A separate protonation run is not needed just to restore labels.

AMBER14 lacks terminal protonated ASP/GLU templates. A terminal ASH/GLH can be
reverted to ASP/GLU with a warning on affected paths. Do not interpret this as
successful preservation of the requested terminal charge state.

## Sidecar no longer matches the structure

Keep model/prepare `.dat` files beside their matching PDB. Saving through a viewer
that reassigns chain IDs or residue numbers can invalidate those identities.
Return to matching artifacts or regenerate preparation metadata rather than
reusing an unrelated sidecar.

## Large CIF structures exceed PDB limits

CIF input is normalized to internal fixed-column PDB. At most 62 chain IDs are
representable; atom/residue identifiers and coordinates must also fit. CIF
normalization refuses unrepresentable data rather than truncating it. Do not
assume downstream PDB CONECT writers support six-digit atom serials.
Split the system or use a format-capable external workflow when necessary.
See [CIF input](cif-input.md).

## GROMACS water, ions, or mixed scaling

AMBER RTP export matches ion parameters to `--water` by default; do not mix
unrelated ion and water sets. CHARMM only accepts its supported water choices.
ACPYPE uses TIP3P and ignores `--water`/`--ion-set`.

AMBER and GLYCAM have different 1–4 scaling. Use `top --acpype` for that combined
route rather than assuming one global GROMACS fudge factor covers both.
If an ACPYPE `interchain_ss.itp` include contains intermolecular interactions,
keep it below all molecule entries after solvation and ion addition.
See [top](commands/top.md).

## Chirality warnings and reproducibility

Inspect residues marked `REMARK 999 DVBFIXER CHIRALITY_REPAIR`, especially local
hydrogen angles. Minimize guards initially-L centers and rejects unresolved
D geometry; rerunning until a lucky result appears is not a repair strategy.
Seeded heavy-atom rebuilds do not imply bit-identical whole-system coordinates
across CPU/GPU backends or thread configurations.

## Experimental diffusion limits

Diffusion requires a separately installed compatible runner and checkpoint.
Availability, gap sizes, terminal support, ligands, and batch/GUI integration
depend on the selected profile and workflow. There is no silent MODELLER fallback.
Start with the current [model scope](commands/model.md#experimental-diffusion-scope)
and [runner installation](installation.md#experimental-diffusion-runner-environments),
not historical acceptance notes. A passing `doctor` handshake does not establish
broad scientific validation.

## Environment and developer notes

- Missing `libmkl_gf_lp64.so.3`: follow the [OpenBLAS repair](installation.md#numpyscipy-blas-backend).
- PROPKA on Python 3.14: retain the supported Python `<3.14` constraint.
- NumPy typing errors: development uses NumPy `<2.5` with a Python 3.11 baseline.
- macOS Docker ncurses symlink failures: put the environment/cache on the
  container's native filesystem, not a case-insensitive host bind mount.
- OpenMM CUDA/PTX errors: verify host-driver/toolkit compatibility before
  changing scientific settings.

Detailed environment diagnoses and resolved bugs are retained in the
[historical troubleshooting archive](known-issues-history.md). That archive is
implementation history, not the recommended starting path for users.
