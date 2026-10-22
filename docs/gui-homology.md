# GUI Homology Workspace

[User guide](README.md) · [GUI basics](gui.md) · [`dvbfixer homology`](commands/homology.md)

The Homology panel is a persistent, workspace-scoped interface for assembling
a target from selected parts of structurally related templates. It combines
target parsing, template-chain assignment, editable multiple-sequence
alignment, 2D/3D residue selection, structural fitting, mosaic-template
construction, and Modeller comparative modeling.

For importing files, opening viewers, running ordinary tools, and downloading
results, start with [GUI basics](gui.md). This page covers template-based modeling.

## Start with MODELLER

Prepare a full target sequence and one or more related template structures.
Check the requirements below, then follow **Target → Templates → Alignment → Model**.
Inspect chain assignments and selected template regions before building a model.

## Experimental diffusion

The Model tab can select either **Modeller** or experimental **diffusion**, with
Auto, Protenix, and Protpardelle model selection. Diffusion uses the same fitted mosaic and painted ownership masks,
keeps covered matching residues exact, and publishes a validated directory
bundle without falling back to Modeller. The GUI registers the candidate and
its bundle artifacts; a scientifically rejected candidate is labeled as
rejected rather than reported as a successful model. The server still requires
an independently installed, preflight-compatible runner for the selected model.

On Linux/NVIDIA, installed Protpardelle uses `protpardelle-1c-cuda`. **Protein
context → Profile default** selects its fixed local context automatically. The
initial CUDA slice is one CYS-free internal gap of 5–10 residues in canonical
protein sources of at most 512 residues. Explicit Legacy/none or Full is rejected
for this profile; the GUI forwards the choice without silently changing it.
See the [CUDA setup](../deploy/protpardelle-1c/README.md#public-linuxnvidia-cuda-profile).

Rejected candidates remain inspectable and are labeled `[rejected]`; they are
not automatically selected as primary output. A published bundle is not by itself
proof of a scientifically acceptable model. Check its validation report.

## Requirements

- A working DVBfixer environment on the GUI server's `PATH`.
- Modeller and its license for the default comparative-modeling step, or an
  installed compatible Protenix or Protpardelle runner for the explicit diffusion backend.
- At least one external sequence aligner: MAFFT, MUSCLE 5, or Clustal Omega.
- Biopython, installed by the DVBfixer environment, for the default structural
  superposition engine.

See [installation](installation.md#multiple-sequence-alignment-executables)
for executable names and platform-specific commands. Check discovery with:

```bash
dvbfixer msa --list-engines
```

## Workspaces and Homology projects

A Library entry is a workspace, not merely a directory. It owns imported
files, active viewer A/B files, tool state, Homology projects, generated runs,
and output artifacts. Its on-disk layout is:

```text
gui/structures/projects/<workspace-id>/
├── workspace.json
├── files/
├── homology/<homology-project-id>/
└── runs/dvb_homology_<timestamp>/
```

Helper inputs, manifests, fitted intermediates, and stdout/stderr logs remain
on disk but are hidden from ordinary file pickers. Visible files can be
renamed, reordered, selected with Shift or Cmd/Ctrl, downloaded, and moved to
recoverable workspace trash. Drag handles show the insertion position, and the
Workspace toolbar switches between **Show structures only** and **Show all files**
without changing stored order. The structure filter retains CIF/mmCIF as well as
PDB and other recognized structure formats. Category icons, format badges, and
path/provenance tooltips identify files even when their display names omit an
extension. Use **Import files** or drop local files onto Workspace to import them.
Library workspace downloads are `.tar.gz` archives. Text-like artifacts open
in the read-only **Text Files** tab.

## Workflow

### 1. Target

Choose any workspace FASTA, PIR, PDB, or mmCIF file. **Parse sequence** reads
all records or protein chains and writes normalized FASTA into the editor.
Review record identifiers before continuing: they become target-chain group
names. `VH` and `VL` are mapped to PDB output chains `H` and `L`; other
multi-character identifiers receive unique one-character PDB chain IDs.

Editing the target invalidates the existing alignment because its columns no
longer describe the same sequence.

### 2. Templates

Press **+ Add new** to create a template row. The active viewer structure is
selected when available; otherwise choose a workspace structure from the row.
Choose the target chain from the selector above the template list. Rows shown
below belong to that target-chain group. After choosing a structure, the GUI
automatically selects its chain with the highest global pairwise identity to
the target. Every chain option shows its identity percentage and remains
manually selectable.

The same structure can be added more than once with different chains. For a
multi-chain target, every target-chain group must contain a chain from the
first template structure. This common reference preserves the relative
orientation of the chains in the final mosaic.

### 3. Alignment

Generate the MSA with MAFFT, MUSCLE 5, or Clustal Omega. Each target chain is
aligned only with template chains assigned to that target. When several
target chains exist, use the target-chain selector above the alignment.

The view scrolls continuously and uses the same residue-class colors as the
Sequence tab. The consensus row and each per-template comparison row use:

| Mark | Meaning |
|---|---|
| `*` | Identical residue |
| `:` | Strong conservative substitution |
| `.` | Weak conservative substitution |
| `×` | Non-conservative difference from the target |
| blank | Gap or unavailable comparison |

Alignment editing moves gaps without changing the ungapped amino-acid
sequence. Undo/redo, aligned-FASTA import/export, whole gap-column insertion,
and removal of all-gap columns are available.

### 4. Select template parts

Paint residues on every template row:

- click: replace the selection and establish an anchor;
- drag: select a continuous range;
- Shift-click: extend from the newest anchor while retaining older ranges;
- Cmd/Ctrl/Option-click: add or remove a residue and establish a new anchor;
- **Select all** / **Clear**: set the persisted modeling mask to the whole row
  or no residues;
- **Use selection as modeling span**: copy the transient selection into the
  persisted modeling mask.

Selecting an alignment residue loads its structure into viewer A when needed
and highlights the corresponding residue in 3D. Selections made in viewer A
are synchronized back to the active template row while the link button is
enabled. Unlinking keeps the alignment and 3D selections independent.
Transient selection never changes a modeling mask by itself, and clearing a
3D selection does not erase the persisted mask.

Masks are zero-based, half-open alignment-column ranges internally. Template
insertions aligned against a target gap cannot contribute a target residue.
If selections overlap, the earlier template in the Templates tab has
precedence. Reorder templates before building when that precedence matters.

### 5. Structural fitting and mosaic construction

At build time, the Python CLI performs the following operations:

1. Group template chains by assigned target chain.
2. Align their sequences to establish residue correspondence.
3. Superpose Cα atoms with Biopython onto the group's reference chain.
4. Verify that every aligned template row matches its fitted coordinate
   sequence exactly.
5. Resolve masks and overlapping columns.
6. Rewrite selected residues into target numbering and target chain IDs.
7. Merge all selected parts into one `selected_template_mosaic.pdb`.
8. Write the matching two-entry PIR alignment: mosaic plus target.

The single mosaic is essential. Passing every non-overlapping span to
Modeller as an independent template allows those spans to move independently
and destroys their common structural frame.

The GUI serializes the project as `template-plan.json` and invokes:

```bash
dvbfixer homology target.fasta \
  --template-plan template-plan.json \
  --num-models 5 --md-level fast -o target
```

See the [CLI Homology documentation](commands/homology.md#selected-template-parts)
for the complete plan-key table.

### 6. Modeling and results

Choose the number of models and Modeller refinement level, then run the build.
When real uncovered loops exist, DVBfixer uses `LoopModel`. A fully covered
target legitimately has no loops; DVBfixer catches that exact Modeller
condition and retries with ordinary `automodel`. Other alignment and PDB
errors are not hidden.

Each run records its arguments, stdout, stderr, target FASTA, plan, mosaic,
PIR, fitted structures, and final PDB under the workspace run directory. The
final model is registered as a visible workspace artifact; helper files stay
hidden but remain available for diagnosis on disk.

## Validation and failure messages

The build stops before Modeller when:

- alignment rows have unequal lengths;
- an aligned template sequence differs from its coordinate sequence;
- masks select no target-aligned residues;
- a selected chain is absent;
- a multi-chain group lacks the common reference structure;
- structural fitting produces no expected fitted file;
- target chain IDs cannot be mapped uniquely.

For a Modeller residue-count error, compare the non-gap mosaic PIR residue
count with unique `(chain, residue number, insertion code)` records in
`selected_template_mosaic.pdb`. The `VH`/`VL` workflow specifically maps to
distinct `H`/`L` PDB chains to prevent accidental chain collapse.

## Structural-alignment engines

The GUI build uses the license-free Biopython engine. It uses the configured
MSA engine for correspondence and an SVD Cα fit. The standalone
[`dvbfixer salign`](commands/salign.md) command also exposes Modeller SALIGN as
`--engine modeller`, but Modeller SALIGN is not required for GUI fitting.

## Current boundaries

- The mosaic contains protein residues selected against target residues;
  template-only insertions are excluded.
- Overlap resolution is deterministic precedence, not coordinate averaging.
- The first template structure defines the global frame for multi-chain work.
- The text viewer is read-only; edit alignments through the Homology Alignment
  tab or an external editor and re-import them.
