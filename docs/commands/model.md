# `dvbfixer model`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/model.md)

Rebuilds missing loops and gaps using Modeller's LoopModel. Identifies missing regions by aligning ATOM records to the SEQRES sequence (or a user-provided FASTA), then runs Modeller's loop modeling with MD refinement to fill them.

## Quick start

```bash
dvbfixer model input.pdb --fasta sequence.fasta --no-terminal -o modeled.pdb
```

**Inputs:** a structure and its complete sequence, with case-sensitive chain-ID
FASTA headers such as `>chain_H`. Omit `--fasta` when correct SEQRES is present.
**Results:** `modeled.pdb` and `modeled.dat`. Keep them together for
[prepare](prepare.md). MODELLER needs a license when rebuilding gaps.
Inspect rebuilt regions; pinning during loop refinement is not an exact-coordinate
guarantee for the full modeling pipeline.

## Defaults and limits

MODELLER remains the default. An experimental, explicit diffusion path is also
available for canonical protein chains with internal gaps and, on the accepted
Protpardelle MPS profile, one-anchor N/C-terminal regions. It runs an
operator-provided protocol-compatible executable; DVBFixer does not install ML
frameworks, download checkpoints, or fall back to MODELLER automatically.

Non-protein chains (glycans, ligands) are included in the Modeller pipeline via `env.io.hetatm=True` with `'.'` (BLK residue) entries in the target sequence, so Modeller preserves them through loop modeling. Original chain IDs and residue numbering are restored automatically.

Writes a `.dat` file recording all atoms in rebuilt gap residues. This is merged by `dvbfixer prepare` with its own additions, so that `dvbfixer minimize` applies appropriate restraints to all rebuilt regions. Water molecules are removed by default (`--keep-water` to preserve).

<details>
<summary>Advanced input handling and implementation background</summary>

These details are not required for the first run. Use the quick start above
and the common examples below before troubleshooting implementation behavior.

**Key behaviour:**
- **Robust multi-chain handling** — chains are reordered before Modeller so disjoint file-order blocks sharing a chain ID (ATOM protein + HETATM glycans split by other chains) are grouped into one contiguous segment. Fixes silent glycan drops (e.g. 3ry6 chain C, FcgRI chain A).
- **Deterministic residue numbering** — gap-fill residues use the shared affine
  sequence placement and input residue anchors rather than a greedy repeated-
  residue match. N-terminal extras extend backward; internal gaps fill forward
  from the left anchor. If the deposited numbering reserved insufficient room,
  downstream residue numbers shift with a warning instead of colliding.
  HETATMs preserve original numbers unless gap filling creates a protein-number
  collision, in which case they are renumbered clear of the protein range.
- **`--fasta` headers must encode chain IDs**: `>chain_X`, `>PDBID_X` (e.g. `>1abc_A`), or `>X`. Matched by ID, not file order. Clear error if unparseable.
- **Shared affine sequence alignment** — terminal trimming, Modeller PIR correction, and residue restoration use the same semi-global alignment. Reference N/C overhangs are terminal; only gaps between the first and last observed anchors are internal modelable gaps. This prevents repeated residues near a terminus from creating a spurious long loop.
- **Plain-language Modeller diagnostics** — common errors (BLK alignment, sequence difference, unknown residue type) get a clear cause + remediation alongside the raw Modeller message.
- **Input residues pinned by default** — a `_PinnedLoopModel` subclass overrides `select_loop_atoms()` so only the newly-modeled gap residues move during Modeller's loop refinement MD. Prevents the ±~3 residue flank drift produced by stock LoopModel. The initial automodel CG is left untouched (all atoms) so any pre-existing input close contacts get relaxed as usual — otherwise they'd survive into the model output and trip OpenBabel's CONECT inference in the downstream `prepare` step (spurious external bonds → OpenMM template match failures on residues far from any gap). Downstream `minimize` still refines the whole system under a proper force field. Pass `--no-pin-input` to restore the legacy behaviour.
- **Fast no-gap pre-check** (since v0.3) — before invoking Modeller, model.py compares each protein chain's ATOM sequence to its SEQRES via string equality. If every chain matches, no gaps → copy input verbatim and skip Modeller entirely. Runtime drops from ~2 min (align2d on a 5-chain × 829-residue complex is O(N²)) to ~0.25 s. Falls through to the full Modeller path when any chain has a mismatch (real gaps).
- **CONECT inference runs BEFORE Modeller, by default** (since 0.7.9) — `_materialise_inferred_pdb` fills in missing SS/glycosidic/glycosylation CONECT records from coordinates on a temp copy of the input, which is what Modeller actually reads. Modeller has no other way to know two chains are covalently linked (e.g. an under-annotated N-glycosylation site with a real bond but no CONECT/LINK in the deposited PDB) and can reposition an undocumented chain arbitrarily far from its anchor during structure-building. Pass `--no-infer-conect` to skip this and use the file's CONECT/LINK records as-is.

</details>

## Usage

```bash
# Basic usage — writes input_model.pdb
dvbfixer model input.pdb -v

# Higher quality (more sampling, slower)
dvbfixer model input.pdb --num-models 2 --num-loops 4 --md-level slow -v

# Save the top 5 candidates instead of just the best one
# (useful for ensemble analysis or visual inspection)
dvbfixer model input.pdb --num-models 2 --num-loops 5 --num-output 5 -v
# → input_model_1.pdb, input_model_2.pdb, ..., input_model_5.pdb
#   (sorted ascending by Modeller's molpdf — best first; matching .dat files)

# Use FASTA instead of SEQRES for complete sequence
# (FASTA headers must encode chain IDs: >chain_A, >1abc_A, or >A)
dvbfixer model input.pdb --fasta sequence.fasta -v

# Keep Modeller working directory for debugging
dvbfixer model input.pdb --keep-workdir -v

# Experimental diffusion; -o is a new directory bundle, not a PDB file
dvbfixer model input.pdb --fasta sequence.fasta \
  --backend diffusion -o input_model_diffusion

# On the MPS profile, retain an isolated ligand as geometric denoiser context. The supplied
# SMILES is authoritative for graph/charge/stereochemistry admission.
dvbfixer model input.pdb --fasta sequence.fasta --backend diffusion \
  --diffusion-model protpardelle \
  --diffusion-heterogen-smiles 'LIG=CC(=O)[O-]' \
  -o input_model_diffusion

# Ignore missing N/C tails and reconstruct only internal gaps
dvbfixer model input.pdb --fasta sequence.fasta \
  --backend diffusion --no-terminal -o input_model_diffusion

# Replay an existing schema-4 request without reconstructing an ambiguous
# sequence placement. input/normalized.pdb must be the request's exact artifact.
dvbfixer model workspace/input/normalized.pdb --backend diffusion \
  --diffusion-request workspace/request.json -o input_model_diffusion

# Sequential directory processing; each input gets its own atomic bundle
dvbfixer model --input-dir structures --output-dir models \
  --backend diffusion --diffusion-model protenix --fasta sequence.fasta

# Reuse matching bundles after digest checks and independent revalidation
dvbfixer model --input-dir structures --output-dir models \
  --backend diffusion --diffusion-model protenix --fasta sequence.fasta \
  --diffusion-resume
```

<details>
<summary>Experimental diffusion: installation, supported scope, and bundle validation</summary>

### Experimental diffusion scope

On Linux/NVIDIA, `--diffusion-model protpardelle` selects the installed
`protpardelle-1c-cuda` profile. It accepts one CYS-free internal gap of **5–10 residues** in
a canonical-protein source totaling at most **512 residues**, including surrounding
protein chains. The default `--diffusion-context auto` applies the validated
source-only local selector, physical source-chain positions and neutral denoiser
phase. Generated-only CUDA refinement follows sampling; outside-gap atom records
remain unchanged. Terminal OXT is preserved outside atom37 conditioning. Explicit
`none`/`full`, nonwater heterogens, terminal gaps, and multiple gaps are rejected.
Installation and the two isolated runtimes are described in the
[CUDA deployment guide](../../deploy/protpardelle-1c/README.md#public-linuxnvidia-cuda-profile).

New native Apple registrations use the versioned
`protpardelle-1c-mps-local-v1` profile with the same bounded source-only local
input policy and **separate generated-only CPU refinement**. MPS denoising never
falls back to CPU. The installer requires `--refinement-python`; see the
[Apple deployment guide](../../deploy/protpardelle-1c/README.md#apple-silicon-preparation).
The historical `protpardelle-1c-mps` identity is retained for legacy requests;
installing the corrected version does not relabel or migrate those requests.

Protenix can opt into source-only protein context with
`--diffusion-model protenix --diffusion-context local` (eight sequence flanks and
observed-anchor spatial/partner shells) or `--diffusion-context full` (the
supported protein environment). For Protenix and the **legacy** MPS profile, `auto` retains the legacy
`none` behavior. Explicit context requires
complete canonical protein context and a bounded residue
axis; unsupported selections fail before inference. Protenix also supports an
explicit jointly sampled plan for multiple gap-bearing chains. Legacy MPS Protpardelle can
use the same explicit selector for one gap-bearing chain and one contiguous span
per represented source chain; discontiguous entities and joint gap-bearing chains
are rejected before runner launch. Fixed conditioning and
preserved-only atoms are distinguished in provenance. See the
[bounded causal pilot and remaining acceptance](../research/protein-context-pilot.md).

The legacy MPS and Protenix profiles accept canonical protein chains with unambiguous
missing regions of 3–12 residues and target sequences from SEQRES or `--fasta`.
Internal gaps use two anchors. The legacy Protpardelle MPS profile also supports one-anchor N-terminal and
C-terminal generation; generated terminal identities extend deterministically
before or after the observed PDB residue-number range. The materializer inserts
N-terminal atoms before the first observed residue and C-terminal atoms before
that chain's `TER`. Validation applies the single available peptide-junction gate
plus atom completeness, geometry, clashes, chirality, and exact fixed-coordinate
checks. Other diffusion profiles reject terminal requests before runner launch.
Pass `--no-terminal` to crop each target outside its first and last observed
anchors and reconstruct only internal gaps. Legacy MPS Protpardelle can retain complete,
isolated, single-residue small molecules only when every retained HETATM residue
has an authoritative repeatable `--diffusion-heterogen-smiles RESNAME=SMILES`
mapping. DVBFixer requires occupancy 1.00, explicit heavy elements, complete
intra-residue CONECT connectivity, a unique chemically equivalent graph mapping,
and no external covalent link. The fixed HETATM coordinates enter the sampler as
a differentiable 2 Å geometric-exclusion context and remain byte-coordinate exact
in the output. This does **not** claim learned bond/charge interaction energies,
ligand generation, parameterization, or support for glycans, metals, waters,
PTMs, cofactors, and covalent ligands. Unsupported chemistry fails before runner
launch. `--strip-heterogens`
explicitly creates a protein-only private input before admission and removes
associated ANISOU, LINK, and CONECT records; the source file is never changed.
Directory batch, GUI, `zbs --model-backend diffusion`, and mosaic-first
`homology --backend diffusion` expose the same scoped backend. These workflow
adapters do not widen scientific admission or enable fallback.

Batch outputs are `<stem>_model_diffusion/` under `--output-dir`, retaining
relative input subdirectories. Destinations and filename collisions are checked
before inference, source/output trees must be disjoint, and GPU jobs run
sequentially. `diffusion-batch.json` records success, scientific rejection,
unsupported input, execution failure, and skipped cases; any failed/rejected case
makes the batch exit nonzero. A shared FASTA applies to every input. An explicit
`--diffusion-request` is single-input only.

`--diffusion-resume` requires unchanged scientific request identity, intact
digest-linked artifacts, valid modeled-atom `.dat` identities, and matching
independent revalidation under the current policy. It does not overwrite or
repair incomplete bundles. Resume reads preserved results without sampling.

`--diffusion-request` accepts an existing schema-4 request when sequence
placement and masks were materialized independently. The positional input must
be the exact normalized PDB referenced by that request. Profile-bound requests
are passed unchanged and still undergo scope admission, runner preflight, independent
validation, and atomic publication. Options that reconstruct or alter request
semantics (`--fasta`, `--diffusion-seed`, `--diffusion-heterogen-smiles`,
`--no-terminal`, and `--strip-heterogens`) cannot be combined with it.
Legacy requests without a `profile` backend option require an explicit
`--diffusion-model`; DVBFixer binds that selected runtime profile while leaving
the persisted placement, masks, seeds, and artifact identity unchanged.

For a multi-chain structure, the Protpardelle profile runs each gap-bearing
protein chain as an independent sampler invocation and then DVBFixer merges the
generated regions into the original structure. Chains without generated gaps
and all fixed atoms are restored exactly. The CLI prints a warning when this
path is used. Each invocation now admits deterministic contiguous crops of
fixed residues from partner protein chains when their heavy atoms lie within
12 Å of a gap anchor. Those partner residues occupy separate chains on the
actual Protpardelle sampler axis and therefore provide real local inter-chain
denoiser context. The sampler trace records the exact partner atom identities
for each target chain. The gap-bearing chains are still sampled in independent
invocations: distant, omitted, or over-budget partner regions do not condition
the denoiser, and this is not whole-complex joint sampling. The 512-residue
axis budget includes the local crops; a single gap-bearing chain longer than
512 residues is still rejected.

An installed private launcher receives the versioned `request.json` protocol and
must write a valid `result.json` plus contained candidate artifacts. The launcher
encapsulates the backend environment, runtime profile, runner, and checkpoint;
none are per-run file arguments. DVBFixer then independently
checks identity, complete generated heavy atoms, fixed-coordinate preservation,
peptide closure, clashes, geometry, and chirality. A successful output directory
contains candidate PDB/`.dat`/provenance files, a bounded digest-verified sampler
trace for each candidate, and `bundle.json`; accepted and explicitly rejected
bundles are both published atomically with distinct status values.

If sampling and materialization complete but every candidate fails scientific
validation, DVBFixer still publishes an atomic **rejected bundle** for inspection.
Its `bundle.json` status is `validation_failed`, each candidate lists the failed
gates, and the CLI prints a prominent warning. Such a PDB is not asserted to be
simulation-ready; the user may inspect it, try another `--diffusion-seed`, or run
a deliberate full-system minimization. Runner/protocol/artifact failures still
publish nothing.

An expected localized OpenMM boundary-refinement failure follows the same policy:
the unchanged raw sampler candidate is retained, provenance records
`localized-openmm-boundary-refinement-failed`, and validation publishes it only
as a rejected bundle. Unexpected exceptions and artifact-integrity failures remain
fatal and publish nothing.

</details>

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `-o`, `--output` | `<input>_model.pdb` | Output file path |
| `--fasta` | none | FASTA file with complete sequence(s) (alternative to SEQRES) |
| `--backend` | `modeller` | Select `modeller` or the explicit experimental `diffusion` path |
| `--diffusion-model` | auto | Optional model choice: `protpardelle` or `protenix`; by default DVBFixer selects an installed model compatible with the machine |
| `--diffusion-context` | `none` | Experimental shared protein context: `local` or `full`; engine-specific capability checks |
| `--diffusion-request` | none | Existing schema-4 request with explicit sequence placement and masks; requires its exact referenced normalized PDB |
| `--diffusion-seed` | 7 | Candidate seed; repeat for multiple candidates |
| `--diffusion-timeout` | 900 | External runner timeout in seconds; the default covers sequential multi-chain sampling and local refinement |
| `--diffusion-work-parent` | output parent | Existing directory under which the private runner workspace is created |
| `--diffusion-resume` | off | Reuse only a matching, digest-verified, independently revalidated bundle |
| `-n`, `--num-models` | 1 | Number of initial models to generate |
| `--num-loops` | 2 | Number of loop refinement models per initial model |
| `--num-output` | 1 | Number of top-ranked candidates to save (ceiling: `num_models × num_loops`). Sorted ascending by Modeller's `molpdf` (best first). With `--num-output > 1`, output filenames get a `_N` suffix |
| `--md-level` | fast | MD refinement level: none, fast, slow, very_slow, slow_large |
| `--pin-input` / `--no-pin-input` | **on** | Freeze every input-structure residue during MD refinement — only gap residues move. Prevents flanking-residue drift; the downstream `minimize` step refines the whole system properly. Pass `--no-pin-input` for the legacy LoopModel behaviour (gap ±~3 residue flank mobile). |
| `--no-terminal` | off | Align to the complete reference, trim outside the first/last observed anchors, and rebuild only genuine gaps between those anchors. |
| `--number-from-1` | off | Normalize each completed candidate so its first retained protein residue is 1; matching `.dat` residue keys are shifted too. |
| `--keep-water` | off | Keep water molecules (HOH, WAT, TIP3, SOL) — removed by default |
| `--strip-heterogens` | off | Remove HETATM records and associated connectivity before modeling. For diffusion this creates a private protein-only input and removes water; for MODELLER water can be retained with `--keep-water`. |
| `--keep-workdir` | off | Keep Modeller temp directory |
| `--no-infer-conect` | off | Skip automatic CONECT inference before Modeller runs (see below) |
| `-v`, `--verbose` | off | Print Modeller progress |

## How It Works

1. Parses SEQRES (or FASTA) for the complete target sequence
2. Builds a target PIR with protein chains from SEQRES and non-protein chains as `'.'` (BLK residues)
3. Reorders chains so disjoint file-order blocks sharing a chain ID (e.g. protein + HETATM glycans on the same chain split by other chains) are grouped into one contiguous segment before Modeller runs
4. Reads the full PDB with `env.io.hetatm=True` so non-protein atoms are included
5. Creates a PIR alignment between the structure (with gaps as `-`) and the target sequence using Modeller's `align2d`
6. Runs `LoopModel` to generate initial model(s) filling the gaps
7. Refines loop regions with configurable MD level
8. Selects the best model by lowest `molpdf` score
9. Restores original chain IDs (Modeller A,B,C,... -> original letters)
10. Restores original residue numbering: template positions keep their original `(resSeq, iCode)`; gap-filled positions are numbered deterministically from input resseq jumps (N-terminal extras extend backward, internal gaps fill between input neighbours, C-terminal extras extend forward — all via `first_resseq + N - K`). HETATM residues attached to a protein chain keep their original resseqs.

## See also

- [`renumber`](renumber.md) — run before `model` when input has insertion codes
- [`prepare`](prepare.md) — next step after `model`, merges the `.dat` file
- [`homology`](homology.md) — multi-template alternative
- [ARCHITECTURE.md](../../ARCHITECTURE.md) — `build_resnum_mapping`, `_reorder_chains_for_modeller`, `parse_fasta` internals

<details>
<summary>Historical implementation background</summary>

## How it works

The notes below preserve implementation history. For current user behavior,
follow the defaults and limits above; for engineering contracts, see
[architecture](../../ARCHITECTURE.md).

Rebuilds missing loops/gaps using Modeller's LoopModel. Takes SEQRES (or --fasta) as complete sequence, aligns to ATOM records via `align2d`, runs loop modeling with configurable MD refinement. Non-protein chains (glycans, ligands) are included in the Modeller pipeline via `env.io.hetatm=True` with `'.'` (BLK) entries in the target PIR sequence so Modeller keeps them through loop modeling. Post-processing restores: (1) original chain IDs from Modeller's A,B,C,..., (2) original residue numbering with insertion codes using the alignment. `--no-terminal` first aligns the observed chain to the complete reference, trims outside the first and last observed anchors, and retains genuine internal gaps between those anchors for modeling. Terminal alignment is auto-fixed after `align2d` with the same shared mapping. Writes a `.dat` file recording all atoms in rebuilt gap residues — prepare merges this with its own additions. Water removed by default (`--keep-water` to preserve). Protonation variant names (HIE/HID/HIP/ASH/GLH etc.) are renamed to standard (HIS/ASP/GLU) before Modeller reads the PDB (Modeller only knows standard names), then restored in the output.

**Fast Python-only no-gap pre-check** (runs before Modeller loads the PDB): compares each protein chain's ATOM-derived sequence to its SEQRES via string equality. If every chain matches, no gaps → skip Modeller entirely, copy input verbatim + write empty `.dat`. Runtime drops from ~2 min (align2d on a 5-chain × 829-residue TCR/MHC complex is O(N²) DP) to ~0.25 s. The old `run_modeller` no-gap shortcut still exists as defensive fallback and now returns `[(str(input_path), 0.0)]` (list-of-one-tuple, same shape as the normal-path return) so the caller's `first_path, _ = candidates[0]` unpacking works uniformly. Prior bug: the shortcut returned raw `str(input_path)` → caller tried to unpack the first char of the path → `ValueError: not enough values to unpack (expected 2, got 1)`.

**`--pin-input` / `--no-pin-input`** (default ON): during Modeller's LOOP refinement MD, allow only the newly-modeled gap residues to move — no ±flank margin. Implemented via `_PinnedLoopModel(LoopModel)` subclass inside `run_modeller()` that overrides only `select_loop_atoms()` (loop refinement MD). Body: `self.loops(aln, minlength=1, maxlength=9999, insertion_ext=0, deletion_ext=0, include_termini=True)` + `Selection(loops).only_std_residues()` — stripping the ±~3 residue flank margin that stock `LoopModel.select_loop_atoms` adds via `insertion_ext=2, deletion_ext=1`. Conditional instantiation: `LoopModelCls = _PinnedLoopModel if getattr(args, 'pin_input', True) else LoopModel`. **Deliberately does NOT override `select_atoms`** (the initial automodel CG). An earlier version of this class did — the effect was that every non-gap atom (both flankers and entire other chains without gaps) was held at its raw input coordinates through the whole pipeline. Any pre-existing close contact in the input (crystal packing artefact, upstream tool output, etc.) then survived into the model output. `dvbfixer prepare` runs OpenBabel `ConnectTheDots` on that output, which infers a spurious bond across the close contact — most commonly a bogus external N bond on a random GLN — and OpenMM's addHydrogens then fails with `1 N atom too many externally bonded`, even for residues far from any gap. Letting the initial automodel CG run on all atoms lets those contacts relax normally, matching stock behaviour outside the loop refinement stage. The loop refinement MD is the dominant source of user-visible flank drift, so restricting only that stage is sufficient for the pinning goal. Downstream `minimize` still refines the entire system under a proper AMBER/CHARMM force field, so `--no-pin-input` remains available for the legacy full-flank-mobile behaviour. Threaded through `zbs` (same `BooleanOptionalAction` default True; forwards `--no-pin-input` when the user opts out). No-op on the no-gap shortcut path (Modeller isn't called there).

**`--num-output N`** (default 1): save the top-N candidate models instead of just the best. `run_modeller()` now returns a list of `(path, molpdf)` tuples sorted ascending (best first). `main()` wraps the post-processing block in a `for idx, (candidate_path, molpdf) in enumerate(candidates[:n_save])` loop. With `--num-output 1` the output filename is unchanged (`<stem>_model.pdb` + `<stem>_model.dat`); with `--num-output > 1` each output gets a `_N` suffix (`<stem>_model_1.pdb`, `_model_2.pdb`, ...) and matching `.dat`. The same chain-ID / residue-renumbering / variant restoration / CONECT / water-filter helpers are applied to each candidate. Validation: `--num-output < 1` errors fast (before Modeller); `--num-output > num_models × num_loops` warns but doesn't fail. The no-gap shortcut (input copied verbatim, no Modeller) emits an INFO line when `--num-output > 1` is set and falls back to a single output (no alternatives exist without gaps).

**Chain block reordering** (`_reorder_chains_for_modeller`, runs before writing the temp PDB Modeller reads): when a chain ID appears in two disjoint file-order blocks (e.g. chain A protein ATOMs early, chain A HETATM glycan late, separated by chains B/C/D/E), Modeller emits an extra template segment for the duplicate appearance. The reorderer groups each chain's records into one contiguous block (preserves chain first-appearance order, drops original TER/CONECT, emits one TER after each block). Fixes silent NAG drops on 3ry6 chain C (the glycosylation was being lost) and 'No aligned template residues for BLK residue' crashes on FcgRI.

**Terminal-alignment dot pairing** (in `_fix_terminal_alignment`): the terminal fixer strips leading/trailing dots from both target and template before shared protein-sequence alignment, then re-attaches them 1:1 (padding any imbalance with `-`). This prevents a target's trailing `.` HETATM slot from becoming a suffix gap that drops the template's matching BLK residue.

**Error diagnostics** (`_explain_modeller_error`, wired into both the `a.make()` exception handler and the all-models-failed exit path): recognises three Modeller error classes and prints a plain-language cause + remediation alongside the raw Modeller message — 'No aligned template residues for BLK residue' (chain ID in disjoint file blocks; dvbfixer reorders automatically but still warns), 'Sequence difference between alignment and pdb' (target/template misalignment, usually the same root cause), and 'Residue type ... too long: BLK' (unknown HETATM resname).

**FASTA chain-ID matching** (`parse_fasta` returns dict keyed by chain ID; `main()` maps PDB chains to FASTA sequences by chain ID, not file order): headers are parsed in priority order `>chain_X` / `>chainX`, then `>PDBID_X` (e.g. `1abc_A`), then `>X`. `parse_fasta` raises `ValueError` on missing, duplicate, or unparseable headers; `main()` reports any PDB chains absent from the FASTA dict (with both lists) so the user can correct headers. The `--fasta` help text documents the accepted header forms.

**Residue numbering — three-tier deterministic strategy** (`build_resnum_mapping`, `_find_seqres_offset_by_resseq`, `_align_atoms_to_seqres`, with the gap-fill logic extracted into reusable `_interpolate_gaps`): replaces the old brittle align2d-mask-based renumbering, which depended on BLOSUM gap placement and could shift modeled residues to the C-terminus when input resseq jumps disagreed with align2d's gap positions (FcgRI chain A regression: 5 missing residues at 219-223 ended up numbered 283-287). The new strategy is tried in order — (1) **K-finder (preferred)**: picks K = number of N-terminal SEQRES residues absent from ATOM, then assigns SEQRES position N → `resseq = first_resseq + N - K`. Trusts input resseq jumps as authoritative gap positions, tolerates up to 10% letter mismatches (mutations), and handles N-term extras, internal gaps, and C-term extras uniformly via the same formula. Only requirement: no insertion codes in input. (2) **NW (mutation-tolerant fallback)**: shared semi-global alignment with affine gaps (open=-5, extend=-1, mismatch=-3, X-neutral, free end gaps on the reference side). Used when K-finder fails due to excessive letter mismatches. (3) **align2d mask (last resort)**: walks Modeller's alignment mask, consumes input residues in order, and interpolates gaps between flanking originals via `_interpolate_gaps`. Kept for chains that defeat both deterministic paths (icode-bearing antibody Kabat numbering, etc.). The dedup loop that resolves duplicate (resSeq, iCode) tuples only runs on the fallback (mask-based) path — running it on the deterministic paths would shift HETATM resseqs (which sit numerically below protein) to wrong values.

**N-terminal gap numbering** (in `build_resnum_mapping`): N-terminal gaps now extend backward from the first template residue. Example — SEQRES has 2 extra N-term residues, input starts at resseq 235 → new residues are numbered 233, 234, then 235... Previously the gap-fill default `left=0` made N-term gaps numbered 1, 2, ..., producing a huge numbering jump at the N-term junction.

**HETATM resseq preservation** (in the deterministic paths of `build_resnum_mapping`): HETATMs attached to a protein chain (N-linked NAG and friends) keep their ORIGINAL input resseq instead of being renumbered to the next sequential integer after the last protein residue. Verified on FcgRI chain A (NAG stays at resseq 4) and 3ry6 chain C (NAG stays at resseq 206).

</details>

## Batch mode

The default MODELLER backend runs independently on every structure while applying
the same FASTA and modeling options: `dvbfixer model --input-dir structures
--output-dir models --recursive`. Experimental diffusion uses a separate,
sequential batch path with one validated directory bundle per input; see its
scope and [generated reference](../reference/model.md).
See [Batch mode](../batch-mode.md) for shared keys.
