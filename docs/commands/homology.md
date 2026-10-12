# dvbfixer homology — Multi-Template Homology Modeling

[← command index](index.md) · [← README](../../README.md)

GUI users should also read the comprehensive
[GUI Homology Workspace guide](../gui-homology.md).

Multi-template homology modeling with Modeller. Takes a target FASTA (multi-chain) and one or more template PDB files. Auto-aligns target to templates via pairwise `align2d` per chain (or `--salign` for structure-based). Each target chain is modeled independently against its best template chain, then assembled into a multi-chain PDB. Point mutations are handled naturally by the differing target sequence. Antibody mode (`--antibody`): uses ANARCI for Kabat/IMGT numbering, CDR detection, and auto-mapping of Fv/constant domains to different templates.

Loop refinement is used when the alignment contains modelable gaps. If
Modeller reports that a fully covered alignment has no loops, DVBfixer
automatically retries that build with ordinary `automodel`; this is a normal
no-loop case and does not require `--no-loop-refine` from the user.

### Selected template parts

`--template-plan plan.json` is the coordinate-preserving workflow used by the
GUI. DVBfixer structurally fits template chains by target chain, resolves the
painted alignment-column ranges, and merges them into one mosaic template
before invoking Modeller. This prevents Modeller from independently moving
non-overlapping fragment templates. Do not combine `--template-plan` with
`--template` or `--alignment`; the plan produces both internally.

With `--backend diffusion`, the template plan instead feeds the authoritative
`selected_template_mosaic.pdb` directly to the selected isolated Protenix or
Protpardelle runner (or the host-compatible installed model under auto selection).
DVBFixer exports `selected_template_mosaic.coverage.json`, preserves the
zero-based half-open masks and earlier-template-wins ownership, maps logical
target IDs such as `VH`/`VL` to distinct PDB chains, and records each covered
residue's template owner in request and publication provenance. Covered residues
whose amino-acid identity matches the target are fixed exactly; only uncovered
regions admitted by the normal diffusion scope are generated. A covered
substitution currently fails closed rather than silently fixing the wrong
residue. There is no fallback to Modeller.

| JSON key | Type | Description |
|---|---|---|
| `templates` | array | Template definitions in precedence order. Earlier templates win overlapping selected columns. |
| `templates[].id` | string | Stable identifier referenced by alignment rows. |
| `templates[].path` | path | Source PDB path. |
| `templates[].chain` | string | Source structure chain. |
| `templates[].targetChain` | string | Target chain receiving selected coordinates. |
| `alignmentGroups` | array | One rectangular alignment and selection set per target chain. |
| `alignmentGroups[].chainId` | string | Target FASTA chain identifier. |
| `alignmentGroups[].rows` | array | Aligned target/template sequences; all rows in a group must have equal length. |
| `rows[].kind` | `target` or `template` | Identifies the target reference row and template rows. |
| `rows[].templateId` | string | Links a template row to `templates[].id`. |
| `rows[].sequence` | string | Gapped aligned amino-acid sequence. |
| `alignmentGroups[].masks` | object | Template-row IDs mapped to zero-based, half-open `{start, end}` column ranges. |
| `alignmentGroups[].maskModes` | object | Template-row IDs mapped to `all`, `ranges`, or `none`. |

For multi-chain targets, every group must include a chain from the first
template structure. That structure supplies the common global coordinate
frame for the complete mosaic.

## Usage

```bash
# Basic multi-template
dvbfixer homology target.fasta --template fab.pdb --template fullsize.pdb -v

# With pipeline (prepare + minimize)
dvbfixer homology target.fasta --template fab.pdb --template fullsize.pdb --minimize -v

# Antibody mode
dvbfixer homology target.fasta --template fab.pdb --template igg.pdb --antibody -v

# Experimental coordinate-preserving mosaic completion
dvbfixer homology target.fasta --template-plan template-plan.json \
  --backend diffusion --diffusion-model protpardelle -o target

# Protenix internal-gap completion followed by preparation/minimization
dvbfixer homology target.fasta --template-plan template-plan.json \
  --backend diffusion --diffusion-model protenix --minimize --no-solvent -o target
```

## Inputs and keys

| Argument | Default | Description |
|---|---:|---|
| `fasta` | required | Multi-chain target FASTA, one header per chain. |
| `--template PDB` | — | Template structure; repeat for multiple templates. Required unless `--template-plan` is used. |
| `--template-plan JSON` | — | GUI-compatible chain/range selection plan. Cannot be combined with `--template` or `--alignment`. |
| `-o`, `--output PREFIX` | FASTA stem | Output prefix for ranked model PDB and `.dat` files. |
| `--backend` | `modeller` | `modeller` or experimental `diffusion`; diffusion requires `--template-plan`. |
| `--diffusion-model` | auto | Installed Protenix or Protpardelle model, subject to its normal scope admission. |
| `--diffusion-seed N` | `7` | Candidate seed; repeatable. |
| `--diffusion-timeout SECONDS` | `900` | Positive finite runner timeout. |
| `--diffusion-work-parent DIR` | output parent | Parent for the private isolated-runner workspace. |
| `--diffusion-resume` | off | Reuse only a verified bundle matching the current mosaic request. |
| `--alignment PIR` | auto | Use a pre-built PIR alignment instead of automatic alignment. |
| `--salign` | off | Use Modeller structure-based SALIGN rather than pairwise `align2d`. |
| `-n`, `--num-models N` | `5` | Number of candidate models to generate. |
| `--md-level LEVEL` | `fast` | Refinement level: `none`, `fast`, `slow`, `very_slow`, or `slow_large`. |
| `--no-loop-refine` | off | Use ordinary `automodel`; useful when no loops need rebuilding. |
| `--antibody` | off | Enable ANARCI-based antibody domain/CDR analysis. |
| `--prepare` | off | Run DVBFixer prepare on the selected model. |
| `--minimize` | off | Run prepare and minimize on the selected model. |
| `--ph PH` | `7.0` | Hydrogen-addition pH used by post-processing. |
| `--no-solvent` | off | Vacuum for optional downstream minimization. |
| `--keep-workdir` | off | Preserve Modeller intermediate files for debugging. |
| `-v`, `--verbose` | off | Print template mapping, alignment, and modeling details. |
| `--log-file PATH` | — | Append complete stdout/stderr to a file while retaining terminal output. |

Modeller is required for the Modeller backend. ANARCI is required only for `--antibody`. Automatic
multi-template mode maps each target chain to its best template chain;
`--template-plan` instead materializes the explicitly selected aligned ranges.
The Modeller output is the best-ranked PDB plus a matching `.dat` restraint
sidecar for downstream `prepare`/`minimize`. Diffusion writes an atomic directory
bundle named `<PREFIX>_homology_diffusion`; accepted and rejected bundles retain
the same validation/provenance semantics as `model --backend diffusion`.
`--prepare` and `--minimize` copy the first independently validated ranked PDB
and its canonical `.dat` into a separate downstream handoff, preserving the
complete bundle. They fail closed on scientific rejection. `--antibody` remains
unsupported with diffusion. Logical plan target IDs remain case-sensitive and
are not truncated before coverage/ownership validation.

## See also

- [`model`](model.md) — single-template loop rebuilding
- [`prepare`](prepare.md) — post-modeling structure preparation
- [BEST_PRACTICES.md](../../BEST_PRACTICES.md) — antibody workflow recipe

## How it works
Multi-template homology modeling with Modeller. Takes a target FASTA (multi-chain) and one or more template PDB files. Auto-aligns target to templates via Modeller's `align2d` (or `salign` with `--salign`). Builds model with `automodel` or `LoopModel` using multiple `knowns`. Point mutations handled naturally by differing target sequence from templates. Post-processing restores chain IDs and residue numbering. Writes `.dat` file for downstream `prepare`/`minimize` restraints. `--prepare` and `--minimize` flags run the full pipeline automatically. Antibody mode (`--antibody`): uses ANARCI for Kabat/IMGT numbering, CDR detection, VH/VL/CH/CL domain classification, and auto-mapping of Fv from one template + constant domains from another. Dependencies: Modeller (required), ANARCI (for `--antibody` mode).

## Batch mode

`homology` does not support directory batch input because each run requires an
explicit query, templates, and alignment relationship. Run it once per modeling
job. See the [batch support matrix](../batch-mode.md#support-by-tool).
