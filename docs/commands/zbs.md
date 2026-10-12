# dvbfixer zbs — Full Pipeline

[← command index](index.md) · [← README](../../README.md)

Runs the complete preparation workflow in one command: **renumber → model → prepare → minimize**.

Since 0.7.7, PROPKA + MolProbity Reduce run **inside** the prepare step — PROPKA drives pKa-dependent variant renames (ASH/GLH/HIP/LYN/CYM/CYX) and Reduce picks the HIS tautomer (HID/HIE) + flags ASN/GLN amide flips. There is no separate `protonate` step and no second minimize pass; the older 7-step design (`... → minimize → protonate --no-hydrogens → minimize → protonate` name-restore) was dropped because `--no-hydrogens` left existing H atoms in the wrong positions relative to the newly-assigned variant names. `minimize` preserves AMBER variant names on write via its own capture-restore path, so no separate name-restore step is needed either. Standalone `dvbfixer protonate` still exists as a post-hoc re-protonation tool (e.g. to re-run PROPKA/Reduce on an already-prepared PDB at a different pH).

Intermediate files are cleaned up by default — use `--keep-interim` to preserve them. The `.dat` file flows from model (gap atoms) through prepare (merged with PDBFixer additions) to minimize (selective restraints). Water is removed by default. With `--keep-water`, crystallographic input waters are forwarded through renumber, model, prepare, and minimize and remain in the final structure; the minimize stage preserves those input waters rather than keeping any temporary solvent box it creates. Each step can be skipped individually. `--dry-run` prints the planned steps + output filenames without running anything.

The modeling backend is selected independently via `--model-backend` (default:
`modeller`). `--backend` continues to select only the preparation backend.
Diffusion retains the complete `<stem>_model_diffusion/` bundle, even without
`--keep-interim`, and copies the first independently validated ranked candidate
plus its `.dat` into a separate downstream handoff. Rejected or corrupted bundles
never enter prepare/minimize; no fallback is attempted. Model bundles are not
realigned or modified by the pipeline. All named intermediates stay beside the
final output, including under batch operation.

## Pipeline

| # | Step | What it does |
|---|---|---|
| 1 | `renumber` | FASTA/SEQRES-based renumbering; removes insertion codes |
| 2 | `model` | Rebuild missing loops via Modeller (`--num-output` saves top-N candidates) |
| 3 | `prepare` | Fix missing atoms + hydrogens via PDBFixer; PROPKA pKa + MolProbity Reduce (`--protassign` default ON) pick the correct AMBER variants (ASH/GLH/HIP/LYN/CYM/CYX, HIS tautomer, ASN/GLN flips) and place final H accordingly |
| 4 | `minimize` | Relax the whole system under the resolved force field; preserves AMBER variant names on write. Optional post-minimize refinement via `--refine {xtb, obminimize}`. |

After the transformation stages, ZBS runs `diagnose`, writes
`<output>.diagnose.json`, and warns if ERROR-level structural findings remain.
Use `--strict-postflight` to make those findings fail the pipeline, or
`--no-postflight` when validation is performed separately. Report-first is the
default because diagnostic clash thresholds are intentionally conservative and
some supported ligand chemistries require user interpretation.

## Usage

```bash
# Full pipeline
dvbfixer zbs input.pdb -v

# Skip terminal modeling and use vacuum minimization
dvbfixer zbs input.pdb --no-terminal --no-solvent -v

# Skip model and minimize steps
dvbfixer zbs input.pdb --skip-model --skip-minimize -v

# Custom output and pH
dvbfixer zbs input.pdb -o output.pdb --ph 6.5 -v

# With point mutations
dvbfixer zbs input.pdb --mutate A:39:ALA --mutate B:100:GLY -v

# Save top 3 candidate loop models from Modeller (best is used downstream)
dvbfixer zbs input.pdb --num-loops 4 --num-output 3 -v

# xtb refinement pass after minimize (organic ligands)
dvbfixer zbs input.pdb --refine xtb --refine-heterogens-only -v

# Optionally guide preparation of every LIG residue with authoritative SMILES
dvbfixer zbs input.pdb --smiles 'LIG=C[NH3+]' -v

# Disable MolProbity Reduce (fall back to pure PROPKA + --his-default)
dvbfixer zbs input.pdb --no-protassign -v

# Preview the pipeline without running it
dvbfixer zbs input.pdb --skip-model --dry-run

# Opt-in Protenix modeling with the default legacy preparation backend
dvbfixer zbs input.pdb --fasta sequence.fasta --model-backend diffusion \
  --diffusion-model protenix --no-solvent -o output.pdb

# Restart modeling from its verified, matching bundle
dvbfixer zbs input.pdb --fasta sequence.fasta --model-backend diffusion \
  --diffusion-model protenix --diffusion-resume --no-solvent -o output.pdb
```

## Options

Organised by which pipeline step each flag flows into.

### General
| Flag | Default | Description |
|------|---------|-------------|
| `-o`, `--output` | `<input>_zbs.pdb` | Final output PDB file |
| `--ph` | 7.0 | pH for protonation and hydrogen addition (used by prepare, minimize) |
| `--ff` | `auto` | Force field forwarded to prepare / minimize. Accepts a short name (`auto`, `amber`, `amber+glycam`, `charmm`, …) or explicit OpenMM XML paths. See [force-fields.md](../force-fields.md). |
| `--atom-naming` | `gromacs` | Atom-naming convention for the final output PDB: `gromacs` (HZ3→HZ1 on LYN, O→OC2, OXT→OC1) or `standard` (keep IUPAC/AMBER-native names). Propagated to prepare + minimize. |
| `--keep-water` | off | Preserve crystallographic input waters through every enabled stage and in the final structure. Temporary minimization solvent is not retained. |
| `--no-infer-conect` | off | Skip auto CONECT inference in model/prepare/minimize |
| `--keep-interim` | off | Keep all intermediate files (default: only final output) |
| `--dry-run` | off | Print the planned pipeline steps + output filenames without running anything |
| `--number-from-1` | off | Normalize only the final PDB so each chain's first retained protein residue is 1; runs before postflight diagnose and leaves intermediate `.dat` IDs unchanged. |
| `--align-to-input` / `--no-align-to-input` | **on** | After every pipeline step, Kabsch-align the output back to the ORIGINAL input on protein backbone atoms. Prevents accumulated rigid-body drift so residue-by-residue comparisons in a viewer line up. Pass `--no-align-to-input` for the legacy behaviour (each step's output in its own frame). |
| `--platform` | auto | OpenMM platform (`CPU`, `CUDA`, `OpenCL`, `Reference`) |
| `-v`, `--verbose` | off | Print detailed progress for all steps |

### `renumber` (step 1)
| Flag | Default | Description |
|------|---------|-------------|
| `--skip-renumber` | off | Skip this step |

### `model` (step 2)
| Flag | Default | Description |
|------|---------|-------------|
| `--skip-model` | off | Skip this step |
| `--model-backend` | `modeller` | Modeling backend; `diffusion` is explicit and remains scope-gated |
| `--diffusion-model` | auto | Installed model choice: `protenix` or `protpardelle` |
| `--diffusion-seed` | 7 | Repeatable seeds; scientific ranking selects the accepted downstream candidate |
| `--diffusion-timeout` | 900 | Runner timeout in seconds; increase for long/high-cost targets |
| `--diffusion-work-parent` | output parent | Existing directory for private runner workspaces |
| `--diffusion-resume` | off | Reuse a matching verified bundle; invalid/incomplete results fail closed |
| `--no-terminal` | off | Trim reference sequence outside the first/last observed anchors and model only genuine internal gaps between them. |
| `--num-loops` | 2 | Number of loop refinement models per initial model |
| `--md-level` | fast | Modeller MD refinement level (`none`, `fast`, `slow`, `very_slow`, `slow_large`) |
| `--fasta` | none | FASTA file with complete sequence(s) |
| `--num-output` | 1 | Save top-N candidate models; zbs uses the best (`_1`) downstream, other candidates remain on disk |
| `--pin-input` / `--no-pin-input` | **on** | Freeze input residues during Modeller's MD refinement (only gap residues move). Prevents flanking drift. Pass `--no-pin-input` for legacy LoopModel behaviour (gap ±~3 residue flank mobile). |

### `prepare` (step 3)
| Flag | Default | Description |
|------|---------|-------------|
| `--skip-prepare` | off | Skip this step |
| `--strip-heterogens` | off | Strip heterogens (protein-only pipeline); default keeps them |
| `--backend` | `legacy` | Prep backend. `legacy`: PDBFixer + Modeller.addHydrogens; handles glycans, ligands, heterogens, covalent-HETATM links. `tleap-reduce`: opt-in deterministic AmberTools + MolProbity pipeline (tleap for heavy atoms, reduce for H); pure-protein only, rejects non-canonical residues, incompatible with `--mutate`. |
| `--no-heterogen-h` | off | Skip H addition on heterogens in prepare (default: add H BioLuminate-style) |
| `--smiles RESNAME=SMILES` | none | Optional, repeatable SMILES chemistry forwarded to prepare for isolated matching ligand residues. Unmapped heterogens retain automatic preparation. Requires the legacy backend and an enabled prepare/heterogen-H step. |
| `--mutate CHAIN:RESNUM:NEW_AA` | none | Mutate a residue; repeatable |
| `--rename` | off | Canonicalise non-standard residue names before prepare/minimize |
| `--cap-termini` | off | Add neutral ACE/NME caps during prepare; incompatible with `--skip-prepare`. |
| `--cap-chain CHAIN` | all protein chains | Restrict capping to selected chains; repeatable. Use `_` for a blank chain ID. |
| `--no-propka` | off | Skip PROPKA3 during prepare; Reduce (`--protassign`) becomes the only source of HIS tautomer picks and ASN/GLN flip detection. Combined with `--no-protassign`, leaves variants = `--mutate` only. |
| `--no-protassign` | off | Skip MolProbity Reduce (HIS tautomer / ASN-GLN flip detection) during prepare. Default: run Reduce. |
| `--his-default` | `HIE` | Default HIS tautomer when PROPKA says neutral AND Reduce didn't place either HD1 or HE2 (`HIE` or `HID`) |
| `--cys-ss-pka` | 99.99 | Disulfide-sentinel cutoff for CYS → CYX; it does not override predicted pKa, so pKa < pH still produces thiolate CYM. Explicit SG–SG bonds override PROPKA. |

### `minimize` (step 4)
| Flag | Default | Description |
|------|---------|-------------|
| `--skip-minimize` | off | Skip this step |
| `--no-solvent` | off | Minimize in vacuum |
| `--rebuild-h` | off | Force `--rebuild-h` on the minimize step (default off; prepare already produced correct H via PROPKA/Reduce) |
| `--restraint-k` | 100.0 | Restraint force constant for original atoms |
| `--max-iter` | 1000 | Max minimization iterations per phase |
| `--refine` | `none` | Post-minimize refinement pass: `xtb` (GFN-FF) or `obminimize` (UFF). Off by default. |
| `--refine-heterogens-only` | off | Restrict `--refine` pass to heterogen residues (protein frozen). Only meaningful with `--refine != none`. |
| `--parametrize-ligands` | off | Forward `--parametrize-ligands` to the minimize step: GAFF2 + AM1-BCC for each heterogen residue with no template in the resolved `--ff`. Since 0.7.10, minimize also auto-attempts this (non-strict) whenever an unknown heterogen is present, even without this flag — explicit `--parametrize-ligands` makes a failure fatal instead of falling back. See [force-fields.md](../force-fields.md). |

## See also

- [`model`](model.md), [`prepare`](prepare.md), [`minimize`](minimize.md), [`protonate`](protonate.md) — the individual steps (`protonate` is a standalone post-hoc tool, not part of the zbs pipeline)
- [Pipelines](../pipelines.md) — manual step-by-step recipes and alternatives

## How it works

Full pipeline in 4 steps: renumber → model → prepare → minimize. Interim files are deleted by default (`--keep-interim` to preserve). PROPKA + MolProbity Reduce run inside prepare (0.7.7+) — there is no separate protonate stage and no second minimize pass. `minimize`'s own capture-restore path preserves AMBER variant names on write, so no name-restore step is needed after minimize either. Water is removed by default; `--keep-water` preserves the input waters end to end without retaining the temporary minimization solvent box. `.dat` flows from model → prepare (merged) → minimize.

**`--align-to-input` / `--no-align-to-input`** (default ON): after every pipeline step, `_maybe_align(out)` runs `dvbfixer.align.kabsch_align_pdb(out, original_input, out, selection='backbone')` in-place. Kabsch rotation + translation is computed on backbone atoms (N/CA/C/O of standard AAs) matched by `(chain, resseq, icode, atomname)` and applied to EVERY atom in the file — protein + heterogens stay in a consistent relative frame with the user's original input, no accumulated rigid-body drift from successive OpenMM minimizations. Alignment is pure numpy (~30 lines in `align.py`), no extra deps. Legacy behaviour (each step's output in its own frame) via `--no-align-to-input`. No standalone `dvbfixer align` subcommand — kept as a pipeline-internal helper per user preference.

## Batch mode

`zbs` runs the complete pipeline separately for every directory input:
`dvbfixer zbs --input-dir structures --output-dir fixed --recursive --number-from-1`.
See [Batch mode](../batch-mode.md) for shared keys.
