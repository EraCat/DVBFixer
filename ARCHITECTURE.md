# dvbfixer architecture

## Implemented domain boundaries

`domain/structure_identity.py` owns immutable identity vocabulary and chain-ID
allocation used by Split, including exact model/altloc/component occurrence
identity for nonprotein reconstruction. `domain/parameterization.py` defines routing policy;
`lig_params.py` uses it to reject unsupported complex cofactors from generic
GAFF. `domain/force_field_naming.py` owns naming vocabulary and policy, while
`force_field_naming.py` provides the pure PDB text conversion service with
typed request/result/error contracts. `ffutils/ff_names.py` is the atomic
in-place compatibility adapter used by existing pipelines. Naming changes
representation only and does not establish force-field template or bond
compatibility. Topology construction, atom matching, and minimization remain in
their existing adapters and pipelines. These are focused uses of domain-driven
design (DDD), not a completed domain-layer migration.

`domain/nonprotein_reconstruction.py` defines the backend-neutral contract for
one exact nonprotein component. `nonprotein_reconstruction.py` is an opt-in,
geometry-only Class A application service with bounded pinned-local and
user-mapped authority, deterministic explicit-pH state selection, structured
Class B/C/online refusals, validation, and atomic bundle publication. Its
separate parameterization decision selects only a candidate route and always
returns `md_ready=False`. `ccd.py` adds bounded component-CIF information and
locked heavy-atom graph conversion; `pdb_component_reconstruction.py` maps one
exact PDB instance and atomically publishes a whole-PDB/provenance bundle. The
`component-info` and `reconstruct-component` commands expose those opt-in
boundaries; no existing preparation default or MD adapter changed.

`model --backend diffusion` is an explicit experimental path with profile-specific
scope: internal gaps and, on admitted Protpardelle profiles, multi-chain or terminal
reconstruction. The [model guide](docs/commands/model.md#experimental-diffusion-scope)
is the current scope reference; the original single-gap boundary in ADR 0011 is
historical. `model/diffusion_cli.py` builds the request;
`model/diffusion/` owns scope admission, the versioned external-runner boundary,
independent validation, provenance, and atomic directory-bundle publication.
The Protenix CUDA and Protpardelle MPS runners live in separate environments
under `deploy/`; ML frameworks and checkpoints are not core dependencies.
`model/diffusion/preflight.py` owns immutable profile metadata and the strict,
bounded no-inference handshake contract exposed by the additive Doctor report.
MODELLER remains the default and keeps its existing PDB-file output contract.
See [ADR 0011](docs/adr/0011-experimental-diffusion-cli.md).

OpenMM is the current minimizer. The optional xtb/OpenBabel passes run after it;
`legacy` and `tleap-reduce` select preparation, not minimization. There is no
geometry-dictionary regularization backend or shared backend capability
negotiation. See [domain model](docs/domain-model.md) for current boundaries
and [whole-complex relaxation research](docs/research/whole-complex-relaxation.md)
for unimplemented alternatives and proposed benchmarks.
Coding agents should start with the [agent knowledge map](docs/agent/README.md)
for task-to-symbol navigation, contracts, invariants, and safe delegation.

## Module structure

```
src/dvbfixer/
├── cli.py                         — entry point, runtime options and subcommand dispatch
├── command_registry.py            — authoritative public command/module/category/batch/output metadata
├── cli_types.py                   — shared argparse numeric and structured-selector validators
├── force_field_naming.py          — pure typed PDB naming conversion application service
├── nonprotein_reconstruction.py   — offline Class A geometry-only reconstruction and atomic publication
├── ccd.py                         — bounded wwPDB CCD lookup, parsing, provenance, and graph conversion
├── pdb_component_reconstruction.py — strict PDB instance mapping/materialization and atomic bundles
├── domain/                        — scientific value objects and policies: structure identity,
│                                     nonprotein reconstruction, parameterization routing, and force-field naming
├── __init__.py                    — __version__, MDAnalysis warning filters
│
│   STRUCTURE PREP PIPELINE (composable subcommands)
├── split_chains.py                — empirical chain splitting; assembly dispatch
├── biological_assembly.py         — REMARK 350 parsing, BIOMT transforms, assembly rendering
├── renumber.py                    — FASTA/SEQRES and antibody numbering
├── model/                         — default Modeller loop/gap rebuilding plus the explicit
│                                     experimental diffusion CLI and isolated diffusion package
├── prepare/                       — missing-atom/H repair, glycans, SMILES and mutations
├── minimize/                      — restrained OpenMM minimization; optional post-refinement
├── prep_backend.py                — opt-in pure-protein tleap+reduce preparation
├── protonate.py                   — PROPKA/Reduce protonation and H repair
├── pull.py                        — geometry-only bond pulling via partial minimization
├── rename.py                      — text-based variant → canonical residue names
├── atom_names.py                  — non-destructive naming CLI and bounded JSON report
├── puppet.py                      — strip to backbone polyglycine
├── zbs.py                         — renumber→model→prepare→minimize orchestration
│
│   FF / TOPOLOGY GENERATION
├── top/                           — RTP-based GROMACS topology; types, glycan detection,
│                                     topology_builder, writers and pipeline orchestration
├── rtp_parser.py                  — GROMACS RTP/ARN/R2B/TDB/ATP parsing
├── acpype_export.py               — OpenMM→ParmEd→ACPYPE topology export
├── ffutils/                      — FF selection, GLYCAM helpers, geometry/chirality,
│                                     variants, naming adapter, DatRecord and ligand valence
│
│   GLYCAN / SMALL-MOLECULE TOOLS
├── glycam.py                      — PDB/CHARMM ↔ GLYCAM nomenclature conversion
├── transplant.py                  — residue grafting with Kabsch alignment
├── parametrize.py                 — GAFF2 and AM1-BCC/RESP small-molecule parameterization
├── lig_params.py                  — on-demand GAFF2 ligand template generation
├── component_info.py              — authoritative CCD chemistry/completeness CLI
├── reconstruct_component.py       — isolated Class A component reconstruction CLI
├── cluster.py                     — glycosidic torsion clustering from MD trajectories
│
│   ANTIBODY / HOMOLOGY
├── homology.py                    — multi-template homology orchestration
├── homology_plan.py               — shared-frame template mosaics and masks
├── msa.py                         — external MAFFT, MUSCLE 5 and Clustal Omega adapters
├── salign.py                      — Biopython fitting; optional Modeller SALIGN
├── antibody.py                    — antibody-scheme numbering and EU references
│
│   SHARED HELPERS
├── pdbutils/                      — CONECT remapping/inference, identity and coordinate checks
├── sequence_alignment.py          — shared affine semi-global sequence placement
├── structure_input.py             — CLI-boundary CIF normalization and identity mapping
├── runtime.py                     — fd-level stdout/stderr capture and diagnostic summaries
├── batch.py                       — directory execution, resume and output isolation
├── align.py                       — sequence-paired Kabsch fitting with header preservation
├── conect.py                      — standalone CONECT inference CLI
│
│   DIAGNOSTIC / QA
├── doctor.py                      — environment, executable and backend diagnostics
└── diagnose/                      — report-only structural, chemistry and steric checks
```

This is a responsibility map, not an exhaustive file inventory. Stale per-file
line counts have been removed; use the source and agent task map for exact symbols.

## Data flow

```
input.pdb ──split──→ split.pdb
            │            │
            │            └── renumber ──→ renumbered.pdb  (+ SEQRES → ATOM alignment)
            │                                  │
            │                                  └── model ──→ modeled.pdb + .dat (gap atoms)
            │                                                  │
            │                                                  └── prepare ──→ prepared.pdb + .dat (merged)
            │                                                                          │
            │                                                                          └── minimize ──→ minimized.pdb
            │
            └── For glycoproteins: glycam ─→ ... ─→ transplant ─→ minimize ─→ top

input.pdb + target sequence ──model --backend diffusion──→ validated directory bundle
                                                    ├── candidate PDB + .dat
                                                    ├── sampler trace
                                                    ├── diffusion provenance
                                                    └── bundle.json
```

The `.dat` file is the structured handoff between pipeline stages. It is
JSON with a list of "added atoms" (chain, resid, icode, atom, element)
plus `variant_overrides` (protonation state). Each tool merges its
additions with upstream `.dat` so `minimize` can apply tiered restraints:

| Atom class | Source | Restraint |
|---|---|---|
| Original heavy | input crystal | strong (100 kcal/mol/Å²) |
| New backbone | model + prepare | weak (5 kcal/mol/Å²) |
| New sidechain + all H | prepare | free |
| Heterogens (ligands, glycan trees) | input or prepare | weak (5 kcal/mol/Å²), same tier as new backbone — was free before 0.7.10, see `minimize.build_restraint_force` below |

## Three force-field paths

dvbfixer supports three independent paths to a GROMACS topology, chosen
by `dvbfixer top` flags:

### 1. RTP path (`--ff amber` or `--ff charmm`) — `top/` + `rtp_parser.py`

Parses GROMACS `.rtp`/`.arn`/`.r2b`/`.tdb`/`.atp` files directly in Python
(no `pdb2gmx`, no GROMACS install). Builds bond graphs, enumerates angles
and dihedrals, applies terminal patches. CHARMM path loads ~2400 residue
templates across 9 RTP files (aminoacids, carb, lipid, na, cgenff,
ethers, metals, silicates, solvent).

Output: modular `.itp` files (`ffparams.itp`, per-chain `{chain}.itp`,
`water.itp`, `ions.itp`, `posre_*.itp`, `interchain_ss.itp`) with a
compact `topol.top` containing only `#include` directives. No FF dir
needed at runtime.

Strengths: fast, deterministic, no per-ligand setup. Strong glycan
support via CHARMM `carb.rtp`. Glycolipid support via auto-detection
of ceramide+sugar trees.

Weaknesses: only handles residues with RTP templates. A chain with no
protein/sugar/ceramide/known-small-molecule residue is dropped from the
topology entirely, with a `WARNING` naming the chain and its resname(s)
(since 0.7.15 — was previously silent, confirmed on a plain fatty-acid
ligand with no RTP entry). Use `--acpype` or `minimize
--parametrize-ligands` (GAFF2) for arbitrary organic ligands instead.

**Water + ion handling (AMBER):** `--water` choices `{tip3p, spc, spce,
tip4p, tip4pew, opc}` drive both the water moleculetype AND the ion LJ
parameters via the `ION_PARAMS` dict in `top/ff_data.py`. `--ion-set auto`
(default) selects the JC/LM set matched to the water model; manual
overrides include `jc-tip3p`, `jc-spce`, `jc-tip4pew`, `lm-hfe-opc`,
`lm-iod-opc`, and `dang-legacy` (the pre-2008 bundled Aqvist/Dang
values). The helpers `_strip_ion_atomtypes()` and `_emit_ion_atomtypes()`
replace ion lines in `ffnonbonded.itp` before write; `_emit_ions_itp()`
generates a fresh `ions.itp` with moleculetypes matched to the chosen
set. Covers Na⁺/K⁺/Cl⁻/Ca²⁺/Mg²⁺/Zn²⁺. CHARMM is excluded from this
mechanism — `--water opc/tip4p/tip4pew` with `--ff charmm` is rejected
at the CLI because CHARMM ions are fitted to CHARMM-TIP3P.

### 2. ACPYPE path (`--acpype`) — `acpype_export.py`

OpenMM (AMBER14 + GLYCAM_06j-1) → ParmEd → ACPYPE → GROMACS. Solves
the mixed 1-4 scaling problem (AMBER fudgeLJ=0.5 vs GLYCAM fudgeLJ=1.0)
via ACPYPE's `[pairs_nb]` directive with per-pair LJ/Coulomb parameters.

Best for glycoprotein systems. Auto-detects SS bonds from CONECT,
reorders chains (protein first, glycan after), handles AMBER variant
names across PDBFile normalization, adds peptide bonds for GLYCAM
protein residues, uses `ignoreExternalBonds=True` + `residueTemplates`
for CYX disambiguation.

### 3. GAFF2 per-ligand path (`minimize --parametrize-ligands`) — `lig_params.py`

For OpenMM `createSystem` on structures with unknown organic ligands
(cofactors, drug molecules, etc. — anything not in a standard AMBER /
CHARMM / GLYCAM template set). REPLACES the previous SMIRNOFF-based path
which never actually parametrised cross-residue glycan bonds correctly.

Pipeline:
1. Load `topology + positions` in MDA-agnostic form; dump to a temp PDB
   so OpenBabel sees the same atoms we iterate.
2. For each unknown residue: extract via OpenBabel → SDF (has bond
   orders + 3D stereochemistry).
3. Wrap in `openff.toolkit.Molecule`; hand the list to
   `openmmforcefields.generators.GAFFTemplateGenerator` (GAFF-2.11 +
   AM1-BCC via antechamber under the hood).
4. Register generator on the OpenMM ForceField via `extra_generators`
   arg to `create_forcefield_with_openff`, then `createSystem` runs.

Cached to `~/.cache/dvbfixer/lig_params/gaff_ligands.json` (override
`$DVBFIXER_LIG_CACHE`). Strict-mode by default: any extraction /
generator failure raises `LigandParamError` — no silent strip-heterogens
fallback when the user explicitly asked for parametrisation.

Requires AmberTools binaries on PATH; `lig_params.py` prepends the env
bin dir + explicitly registers `AmberToolsToolkitWrapper` in the OpenFF
global registry to survive shim-invoked env-less PATH.

`ffutils.create_forcefield_with_openff` was renamed in spirit — its
current job is just GLYCAM template suppression (removes ~1400 sugar/NA
templates that fuzzy-match PDB names to wrong entries) plus registering
any `extra_generators` (GAFFTemplateGenerator etc.) the caller passes.

## Key abstractions

### `model.build_resnum_mapping` — three-stage resnum reconstruction

After Modeller produces `output.B9999*.pdb` with renumbered residues
(1..N) and reassigned chain IDs (A,B,C,...), `build_resnum_mapping`
reconstructs the original (resSeq, iCode) numbering per chain through a
three-stage pipeline:

1. `_find_seqres_offset_by_resseq` (K-finder) — deterministic resseq
   offset by letter-match tolerance. Primary path; fast and unambiguous
   when input resseq jumps line up with SEQRES missing positions.
   Tolerates up to 10% letter mismatches (mutations).
2. `_align_atoms_to_seqres` (NW fallback) — semi-global Needleman-Wunsch
   with affine gap penalties (open=-5, extend=-1, mismatch=-3, X-neutral, free end
   gaps on SEQRES side). Mutation-tolerant; handles chains where the
   deterministic offset doesn't exist.
3. align2d mask consumption (legacy) — original PIR-mask based path,
   kept as a final fallback for chains that defeat both deterministic
   paths (icode-bearing antibody Kabat numbering, etc.).

`_interpolate_gaps` is the reusable helper for all three stages (fixed
0.7.13 — stage 3's `build_resnum_mapping` fallback used to carry its
OWN second, hand-rolled copy of this same gap-filling logic, which had
drifted out of sync; it now calls `_interpolate_gaps` directly): it
fills N-terminal, internal, C-terminal, and all-gap regions in one
place, given the flanking original (resSeq, iCode) tuples. For an
internal gap, if the input's OWN numbering leaves enough numeric room
between the flanking residues, the gap is placed sequentially from
`left + 1`; if it doesn't (the depositor never reserved resSeqs for a
genuinely-absent loop/linker — confirmed on a real scFv construct
whose disordered (GGGS)×4 linker has no density and whose author
numbered VH's first residue immediately after VL's last one, leaving
zero room for the linker's 16 residues), the gap is still placed from
`left + 1` and every already-placed resSeq downstream is shifted
forward by the deficit (WARN emitted) — NOT numbered backward from the
right flank, which would collide with resSeqs already used further
left. Mirrors the N-terminal branch's existing (older)
shift-the-rest-of-the-chain pattern for the equivalent "not enough
room" case at the start of a chain.

HETATM resseqs are preserved verbatim on the deterministic paths (no
longer renumbered sequentially after the protein), so ligand and glycan
numbering from the input PDB survives Modeller round-tripping.

### `model._reorder_chains_for_modeller` — pre-Modeller chain grouping

Modeller segments chains by file-block when reading a PDB. If a single
chain ID appears in two disjoint blocks (e.g. chain A protein + chain
B sugar + chain A more protein), Modeller treats the two A-blocks as
separate chains and the PIR alignment fails with a BLK alignment error
(or silently drops the second block). This preprocessing pass groups
every chain ID's ATOM/HETATM records into a single contiguous block in
the temp PDB Modeller reads. No-op on already-contiguous inputs.

### `model.main` — CONECT inference runs BEFORE Modeller (0.7.9)

`_materialise_inferred_pdb` (same helper `convert`'s CLI already used)
now runs early in `model.main()`, before Modeller ever reads the file,
filling in missing SS/glycosidic/glycosylation CONECT records from
coordinates. Modeller has no other way to know two chains are
covalently linked — an under-annotated glycosylation site (real bond,
no CONECT/LINK in the deposited PDB) previously got repositioned
arbitrarily far from its anchor during structure-building, because
fixing CONECT *after* Modeller runs is too late: the damage (arbitrary
relative chain placement) already happened. `--no-infer-conect` opts
out. `zbs.py` threads the same flag through to the `model` step.

### `antibody.number_chain` — antibody-aware residue numbering

Module: `src/dvbfixer/antibody.py`. Used by `renumber` when `--scheme` is
not `seqres`. Three-stage pipeline per chain:

1. **V-domain numbering via ANARCI** — `_number_v_domain(seq, scheme)`
   runs `anarci.anarci(seq, scheme=...)` for one of {kabat, chothia, imgt,
   martin, aho}. EU's V-domain numbering matches Kabat. Returns per-residue
   `(input_idx, resseq, icode)` placements including CDR insertion codes
   (H100A/B/C etc.).
2. **C-domain numbering via embedded EU references** — three reference
   sequences are baked in (`IGG1_HEAVY_CONST_SEQ` covering EU 118-447,
   `CK_SEQ` covering EU 108-214 IgK, `CL_SEQ` covering EU 108-214 IgL).
   Post-V residues are aligned against all three via semi-global
   Needleman-Wunsch (`_nw_align`, affine gaps open=-10/extend=-1,
   X-neutral, free end gaps on the reference side). Best-scoring alignment
   wins; placements require ≥50% of input length matching.
3. **V/C collision shift** — when V-scheme extends past EU position 117
   (IMGT/Martin/Aho), the EU C-domain numbers are shifted forward by
   `(max_V_resseq + 5) - first_C_EU` to keep numbering monotonic. A
   warning is emitted.

Chains where neither ANARCI nor the C-domain alignment placed anything
fall back to the SEQRES path. ANARCI is OPTIONAL — `_have_anarci` checks
import availability; failure returns `None` cleanly so the SEQRES fallback
fires.

### `prepare.apply_deletions_to_pdb_text` — pre-PDBFixer raw-text residue cleanup

Module: `src/dvbfixer/prepare.py`. Implements both `--mutate CHAIN:RESNUM:del`
AND substitution-induced dependency cleanup (`--mutate H:297:ALA` on a
glycosylated ASN removes the attached glycan tree because ALA can't carry
it). Operates on PDB text BEFORE PDBFixer sees the structure. Three
passes over the input lines:

1. **Index** — build `res_lines` (reskey → [line_idx]), `res_resname`,
   `serial_to_reskey`, `serial_to_atomname`, `serial_is_hetatm`,
   `serial_to_coord`, `conect_graph` (bidirectional, from CONECT records),
   `ssbond_pairs`, `link_pairs`, `chain_seq_order`.
2. **Resolve each target** — for deletions, mark the residue's atoms for
   removal; for substitution-cleanup, the residue stays and only its
   dependents are cleaned. Both flavours run: BFS the CONECT graph from
   the sidechain anchor (`SIDECHAIN_ANCHORS` keyed by resname) into
   HETATM-only territory to collect the attached glycan tree; find the
   disulfide partner via SSBOND records or CONECT SG-SG and queue it for
   CYX→CYS rename + HG drop. For deletions only, classify the gap as
   internal/terminal_N/terminal_C/whole_chain by walking the chain's
   residue order and compute `prev.C → next.N` distance for internal gaps.
   Substitution-cleanup is filtered: skipped when the new AA's parent
   name matches the old residue name (e.g. CYS→CYX is just a protonation
   variant rename — the SS bond is preserved).
3. **Write** the cleaned PDB — filter atom lines by serial, rewrite kept
   CONECT lines without removed serials, drop SSBOND/LINK lines that
   referenced the deleted residue, rename CYX partners to CYS and drop
   their existing HG.

After PDBFixer loads the cleaned file, `run_pdbfixer` scrubs
`fixer.missingResidues` entries that correspond to user-deleted positions
— otherwise PDBFixer's SEQRES-driven gap filler would re-add the residue.
The scrub handles chains where multiple OpenMM `Chain` objects share a
chain ID (e.g. a trailing HETATM block gets its own `Chain` even though
it shares the protein's letter; both chain indices must be scrubbed).

The `.dat` file gains a `removed_residues` field with per-deletion
metadata so downstream `minimize` / `model` know which residues are
intentionally absent.

### `split._process_multi_model` — multi-MODEL chain ID consistency

Module: `src/dvbfixer/split_chains.py`. Multi-MODEL inputs (NMR ensembles,
GROMACS trajectory exports with MODEL records) are processed per-MODEL:
each MODEL's atom block runs through the existing chain-break detection
independently, then per-MODEL chain signatures (`_chain_signature`:
per-chain atom count + residue count + first/last resname) are compared
across MODELs. If all match, the same chain ID sequence is reused in
every MODEL (A B C in every MODEL — matching the natural interpretation
of a multi-state ensemble). If signatures differ, the tool falls back to
per-MODEL independent chain IDs with a warning. Atom serials reset within
each MODEL; TER records inserted between chains in every MODEL.

### `biological_assembly.py` — REMARK 350/BIOMT extraction

`split --assembly ID|all` bypasses empirical chain detection. The parser binds
each APPLY/AND CHAINS group to its complete BIOMT operators; the renderer
selects source chains, generates transformed copies, and assigns collision-free
PDB chain IDs. Coordinates and ANISOU tensors are transformed and
chain/serial-sensitive records regenerated. Every requested assembly validates
before writing, so `all` mode cannot leave a partial output set.

### `model.parse_fasta` — chain-ID-keyed FASTA parsing

Returns `dict[chain_id, sequence]` (previously a list of tuples in
file order). Chain IDs are parsed from the FASTA header via priority
patterns: `chain_X`, `PDBID_X` (PDB-style `>4ABC_H`), then a final
bare `X` fallback. Chain order in the FASTA file is no longer
significant — the mapping is by chain ID, so users can list chains in
any order.

### `prepare.add_heterogen_h_via_rdkit` — BioLuminate-style H placement

Pipes the prepared PDB through RDKit:
1. `MolFromPDBBlock(proximityBonding=True)` — full molecular graph from
   CONECT + distance perception
2. Hardcoded C=O bond-order fixups for known PDB sugars (NAG/SIA)
3. `AddHs(addCoords=True)` — places H with proper 3D geometry
4. Post-filter: skip H on carbonyl atoms (per `_NO_H_ATOM_NAMES`)
5. Map RDKit atom indices → OpenMM atoms via positional lookup
6. Insert H atoms + **bond them to their parent atom**
7. Carry over RDKit-perceived intra-sugar bonds → OpenMM topology

The H-parent bond is critical: without it, `PDBFile.writeFile` doesn't
emit CONECT for H atoms, and downstream OpenBabel/xtb proximity bonding
may miss the bond (especially for H placed >1.9 Å from parent), causing
H atoms to drift during refinement.

Step 7's "carry over RDKit-perceived intra-sugar bonds" (and the
equivalent per-residue OpenBabel harvest in `_process_single_residue`,
used by the `add_heterogen_h_via_openbabel` fallback) both cap
same-residue bonds at a ~1.7 Å covalent distance (0.7.10) — RDKit's
`proximityBonding=True` and OpenBabel's `ConnectTheDots` have no
template for sugar/GLYCAM residues (unlike the 20 canonical AAs) and
can propose same-residue bonds at 2.5+ Å (ring/branch atoms merely
close in 3D, not bonded). Same guard, same rationale, as the one in
`pdbutils/inference.py::_apply_filter` — all three are independent
code paths that need it separately, fixing one doesn't fix the others.

### `minimize.build_restraint_force` — the restraint tier scheme

`CustomExternalForce` with three tiers, chosen per-atom in
`minimize()`'s `build_restraint_force`: original protein heavy atoms
get `strong_k` (100 kcal/mol/Å² default), newly-modeled backbone atoms
get `weak_k` (5.0), everything else (new sidechain atoms, all
hydrogens) is free. Heterogen heavy atoms (ligands, glycan trees) were
originally ALSO free ("BioLuminate-style: protein is fixed-ish,
ligands relax") — fine for a small, torsion-poor ligand, but a
multi-residue glycan tree with many free glycosidic torsions and no
restoring force could drift a mean of 4+ Å (up to 10+ Å) off its
covalent anchor into an unrelated, clashing part of the protein
surface (0.7.10). Now routed through the same `weak_k` tier as new
backbone atoms — matches established glycoprotein MD/structure-prep
practice (CHARMM-GUI equilibration protocols restrain protein AND
glycan heavy atoms together, commonly ~1-10 kcal/mol/Å², squarely in
this scheme's existing `weak_k` range). Only hydrogens stay fully
free, including newly-placed heterogen H.

### `minimize`'s auto-parametrize-on-template-miss (0.7.10)

`has_heterogens` now always calls `lig_params.build_ligand_generator`
(not only under `--parametrize-ligands`), with `strict=` toggled by
whether the user explicitly passed the flag. Rationale: without a FF
template, whole-system `createSystem` fails and falls back to legacy
strip-and-splice, which has no tracking mechanism for a non-covalent
ligand (`_rigid_track_glycan_trees` only follows a covalent anchor
bond) — the ligand gets spliced back at its ORIGINAL pre-minimize
coordinates into a pocket the protein has since moved into. Since
`build_ligand_generator` is a cheap no-op when every heterogen already
has a template, and `strict=False` degrades gracefully (prints a
warning, returns `None`) when AmberTools/openff aren't installed, this
adds no cost/behaviour change for environments that can't run it.

Two related traps found making this work end-to-end:
`Modeller.addHydrogens()`'s OWN internal `createSystem` call can raise
`KeyError` (not `ValueError`) when its temporary re-matching invokes
the registered GAFF2 generator — a real openmmforcefields/OpenMM
limitation around invoking a dynamic template generator from inside
`addHydrogens`'s own internal matching, not something dvbfixer can fix
directly; caught alongside `ValueError` in the existing "fall back to
protein-only H placement" handler. And minimize's strip-and-readd-H
path (`amber_renames` non-empty) used to strip H from EVERY residue
including arbitrary ligands — `addHydrogens` has no hydrogens.xml
entry to rebuild a stripped ligand's H from, so this is unrecoverable;
now scoped to `PROTEIN_RESIDUES` only, since the whole mechanism is
about protein-side AMBER protonation variants, not heterogens.

### `minimize.refine_with_obminimize` / `refine_with_xtb` — universal-FF post-pass

After OpenMM AMBER minimization, optional refinement using:
- **OpenBabel obminimize** (MMFF94 → UFF auto-fallback) — fast, SMARTS-rule typing
- **xtb GFN-FF** — universal FF, GNN-derived parameters

Both use `_extract_heterogen_subsystem` to build a sub-topology of
heterogens + their full anchor residues (e.g. entire ASN, not just ND2).
Anchor atoms are frozen via:
- `OBFFConstraints.AddAtomConstraint()` for obminimize (Python API only —
  CLI obminimize has no freeze flag)
- `$fix atoms:` xcontrol block for xtb (1-based ranges)

After refinement, anchor coords are NOT spliced back (they didn't move;
keep OpenMM-minimized values). Auto-switches to heterogens-only when
topology > 5000 atoms (UFF OOMs, xtb hours-slow).

### `acpype_export.prepare_for_openmm` — glycoprotein normalization

Critical glue for the ACPYPE path. Handles:
- CYS → CYX renaming from CONECT-detected SS bonds, plus distance
  fallback (SG-SG within 2.5 Å) via `detect_ss_bonds`. Recognizes SG
  on CYS, CYX, and CYM residues.
- AMBER variant capture/restore across PDBFile normalization
  (PDBFile.writeFile converts ASH→ASP, HIE→HIS, CYX→CYS on output).
  Includes CYX and CYM (not just HID/HIE/HIP/ASH/GLH/LYN) so the
  downstream `res_templates` loop can disambiguate against CYM/CYX.
- Chain reordering: protein first, glycan after.
- Glycan TER record filtering (prevents chain breaks).
- Terminal atom removal (OXT/H2/H3 from mid-chain residues).
- HD21 addition for NLN (GLYCAM expects only HD21, not HD22).
- Peptide bond repair for stretched bonds after transplant.
- **Selective H stripping** via per-residue `_GLYCAM_KEEP_H` allowlist
  (NLN keeps `{H, HA, HB2, HB3, HD21}`, OLS keeps `{H, HA, HB2, HB3}`,
  OLT keeps `{H, HA, HB, HG21/HG22/HG23}`). Only disallowed atoms are
  stripped (HD22 on NLN, HG on OLS, HG1 on OLT, CHARMM HN/HT*). This
  preserves the canonical HD21 geometry from minimize through the
  acpype pipeline.

### `acpype_export.add_glycam_bonds(topology, ff, positions=None)` — glycan bond population

OpenMM's `PDBFile` doesn't infer bonds for non-standard residues.
This helper adds three classes of bonds for GLYCAM residues:
1. **Intra-residue bonds** — read from the FF template's bond list and
   added by atom-name match.
2. **Peptide bonds for NLN/OLS/OLT** — `prev.C → this.N` and
   `this.C → next.N`.
3. **Sugar-sugar glycosidic bonds** — distance-based detection (only
   when `positions` is provided). Anomeric C1 (or C2 for sialic) within
   2.0 Å of a linkage O2/O3/O4/O6 on another sugar. Without these,
   GLYCAM templates for linkage-position sugars (e.g. 6LB declares O6
   externally bonded) fail to match in `createSystem` ("missing 1
   externally bonded O atom"). All three of prepare/minimize/protonate
   call this with `positions=modeller.positions`.

This function was **dead code for the entire 0.7.8 release** (fixed
0.7.10): it imported `KNOWN_GLYCAN_SMILES` from `dvbfixer.ffutils` — a
symbol that never existed anywhere in the codebase — and the resulting
`ImportError` was caught by a `try/except Exception` that also
(incidentally) wrapped the unrelated `openmm.unit.nanometer` import,
so every call silently no-opped instead of raising loudly. Fixed by
importing `nanometer` directly (a hard dependency, not worth guarding)
and reusing the module's own `_is_glycam_sugar` (covers both
GLYCAM-canonical 3-char codes and plain PDB sugar names — closer to
`KNOWN_GLYCAN_SMILES`'s never-implemented intent than
`ffutils.is_glycam_sugar` alone, which only recognises GLYCAM codes).

### `transplant.py` — graft workflow

Designed for the GLYCAM-Web glycoprotein workflow: extract glycosylation
site residues from acceptor → submit to GLYCAM-Web → transplant graft
(NLN/OLS/OLT + glycan trees) back. Kabsch superposition aligns donor→
acceptor; same transform applied to graft. CONECT records remapped via
atom identity (chain, resseq, atomname) — NOT serial numbers (collide
between sources).

`--relax` runs 4-stage AMBER14+GLYCAM minimization with decreasing
restraints on protein heavy atoms (k=1000→100→10→0 kJ/mol/nm²).
`--gromacs DIR` exports GMX topology via the same `acpype_export.py`
helpers used by `dvbfixer top --acpype`.

### `glycam.convert_to_glycam(input_path, output_path)` — forward direction

`_parse_pdb` only ever reads ATOM/HETATM/CONECT/LINK — everything else
(SEQRES, HELIX, SHEET, CRYST1, ...) used to be silently dropped from
the output entirely (fixed 0.7.9: `_extract_passthrough_header_lines`
reads the raw input file and passes through every line whose record
type isn't ATOM/HETATM/CONECT/TER/END/MODEL/ENDMDL, mirroring
`align.py`'s `_apply_transform_preserving_headers` pattern). Losing
SEQRES specifically broke downstream gap-modeling for anyone piping
`convert` straight into `model`/`zbs`, since `model.py` needs SEQRES to
know the full sequence including missing residues.

Glycosidic-bond detection was also an either/or gate: if the input had
*any* CONECT records, they were trusted *exclusively* for every
residue, with no distance cross-check — so a real but under-annotated
glycosylation site (CONECT covers some sites but not all, a genuine
gap in the deposited PDB, not something dvbfixer caused) silently lost
its protein-sugar link. `_merge_glycosidic_bonds` (0.7.9) changes this
to always-supplement: CONECT-derived bonds win, and
`_detect_glycosidic_bonds_by_distance` fills in any child atom /
sugar not already covered by a CONECT-derived bond.

### `glycam.convert_to_charmm(input_path, output_path)` — reverse direction

Mirror of `convert_to_glycam`. Strips GLYCAM linkage characters, looks up
the (sugar_letter, anomer) pair in `_SUGAR_LETTER_TO_CHARMM` to get the
standard PDB 3-char code (NAG/NDG/BMA/MAN/GAL/FUC/FUL/SIA/NGA/A2G/...).
Reverts NLN/OLS/OLT → ASN/SER/THR via `GLYCAM_TO_STANDARD_PROTEIN`.
Drops ROH/OME/TBT/CMET caps (CHARMM has no reducing-end caps).

Atom-name inversion uses the dict-inverted forward maps:
- `_REV_HYDROXYL_H` (universal H<n>O → HO<n>)
- `_REV_NACETYL_PDB` (NAG/NDG/NGA/A2G: C2N→C7, O2N→O7, CME→C8,
  H2N→HN2, H1M/H2M/H3M→H81/H82/H83)
- `_REV_GLYCAM_ATOM_MAP['SIA']` (sialic: C5N→C10, CME→C11, O5N→O10,
  H1M/H2M/H3M→H111/H112/H113, H5N→HN5, H3A/H3E→H31/H32, H9R/H9S→H91/H92)

Output uses 3-char PDB sugar codes that work natively with both
CHARMM-GUI (as input) and `dvbfixer top --ff charmm` (which maps them
to CHARMM RTP names via `PDB_TO_CARB`). Linkage information is
preserved via CONECT records — the residue name no longer carries it.

CLI: `dvbfixer convert <input> --to-charmm -o <output>`.

### `prepare._preprocess_glycoprotein_input` — pre-PDBFixer input fixes

Runs before `_canonicalize_conect_records` in `run_pdbfixer`. Two
edits on the input PDB text:

1. **HETATM → ATOM rewrite** for any residue in `FORCE_ATOM_RESIDUES`
   (20 std AA + AMBER variants HID/HIE/HIP/ASH/GLH/CYX/CYM/LYN +
   GLYCAM glycoprotein residues NLN/OLS/OLT). HETATM gets treated as
   ligand by OpenMM, breaking peptide bond inference to neighbours.

2. **Spurious TER record removal** between two amino-acid residues on
   the SAME chain. A TER forces OpenMM to split the chain, breaking
   the polymer. Implementation buffers each TER and emits it only
   after seeing the next ATOM/HETATM — drops if both flanking residues
   are protein on the same chain.

Both edits are no-ops on clean inputs (returns the original path,
no temp file created).

### `run_pdbfixer`'s internal ordering — heavy atoms before PROPKA/Reduce (0.7.11), and PDBFixer's own canonical order (0.7.12)

`run_pdbfixer` (`prepare/pipeline.py`) does, in order: (1) load +
`PDBFixer.findMissingResidues()` (+ deletion-scrub) ->
`findNonstandardResidues()` -> `replaceNonstandardResidues()` ->
`removeHeterogens()` -> `findMissingAtoms()` ->
`rebuild_missing_atoms_with_retry()` (seeded `addMissingAtoms`, see
below) + the chirality fix — this is the ONLY step that can rebuild a
residue's missing heavy atoms; (2) write `fixer`'s current (now
heavy-atom-complete) state to a temp PDB and call
`_run_propka_reduce_variants` on THAT file; (3) merge the result with
`--mutate` overrides into the per-residue `variants` list and call
`Modeller.addHydrogens(...)`. Step 2 used to happen in `main()`,
before step 1 ever ran — on the RAW input, which can have a residue
with genuinely missing heavy atoms (crystallographic disorder). PROPKA
can't identify a titratable group with no atoms to look at, so it
silently emitted no result at all for such a residue, and the variant
decision fell through to OpenMM's own internal auto-detect in
`Modeller.addHydrogens` (requires exactly one ND1 and one NE2 for HIS),
which raises an unrecoverable `ValueError` with no fallback of its
own. `main()` no longer calls `_run_propka_reduce_variants` itself —
it only passes through the raw args (`his_default`, `cys_ss_pka`,
`use_propka`, `use_reduce`) for `run_pdbfixer` to use internally.

**Step 1's internal order (0.7.12, `fix/seeded-atom-rebuild` branch).**
Through 0.7.11, `findMissingAtoms()` was called BEFORE
`removeHeterogens()`/`replaceNonstandardResidues()`. Both of those two
PDBFixer methods rebuild an entirely new `Topology` internally
(`Modeller(...).delete(...)`), which silently invalidates the
already-computed `missingAtoms` dict — it's keyed by Residue *object
identity* against the topology that existed at `findMissingAtoms()`
time, and PDBFixer's own `_addAtomsToTopology` (inside
`addMissingAtoms()`) looks residues up in it by identity, not value.
Net effect on every default (heterogens-stripped) run: `addMissingAtoms()`
silently added ZERO heavy atoms for any genuinely-missing sidechain —
confirmed on `main` through 0.7.11 (`E/LYS299` in `tests/fixtures/8cz8/
8cz8_t_u.pdb` stayed backbone+CB straight through `prepare`, despite
PDBFixer's own verbose log correctly reporting `CG`/`CD`/`CE`/`NZ` as
missing beforehand). Fixed by reordering to match PDBFixer's own
canonical usage pattern: `findNonstandardResidues()` ->
`replaceNonstandardResidues()` -> `removeHeterogens()` ->
`findMissingAtoms()` -> rebuild. `findMissingResidues()` (+ its
deletion-scrub logic, needed early to pop gaps corresponding to
user-requested deletions) stays where it was — it's keyed by
`(chain.index, indexInChain)`, a positional pair that survives the
later rebuilds, unlike Residue-object identity.

**Seeded rebuild (0.7.12).** `PDBFixer.addMissingAtoms(seed=None)`
rebuilds a missing sidechain via template-overlay + a short local
minimization; if the result clashes with a neighbor (< 0.13 nm, its
own `_findNearestDistance` cutoff), it falls back to UNSEEDED Langevin
dynamics (300 K, up to 2000 steps) to kick the new atoms apart —
genuine stochastic MD whose escaped conformation differs run to run on
the exact same input (confirmed: 11 of 19 LYS residues in `tests/fixtures/8cz8/
8cz8_t_u.pdb` chain E are truncated to backbone+CB by real disorder).
`dvbfixer.ffutils.geometry.rebuild_missing_atoms_with_retry(fixer,
verbose=..., log_prefix=...)` retries `addMissingAtoms(seed=1..5)`
until the rebuilt residues pass both a chirality check
(`find_d_residues`) and a clash check (`find_clashing_atoms`, new
helper — same 0.13 nm cutoff as PDBFixer's own, but excludes atoms in
the SAME residue entirely rather than only directly-bonded ones, since
a flexible sidechain can legitimately place two of its own atoms this
close in a gauche conformation). It snapshots `fixer.topology`/
`fixer.positions` once before the loop and restores them before each
attempt — safe because PDBFixer builds an entirely new `Topology` per
call and only reassigns those two attributes at the very end, never
mutating the pre-call objects. All 5 `addMissingAtoms()` call sites
(`prepare/pipeline.py`, `minimize/pipeline.py` ×2, `protonate.py`,
`top/pipeline.py`) route through it. This fixes the rebuild's own
non-determinism at the source; it does not touch or replace
`minimize`'s existing reflect/re-minimize/force-reflect logic, which
remains the last-resort safety net for the separate (much rarer) case
of a residue whose full-system FF minimum genuinely prefers D.

### `prepare.find_glycosylated_atoms_with_sugar` — FF-agnostic detection

Returns `dict {(chain, resid, atom): bonded_sugar_resname}`. Two passes:

1. **CONECT-based**: scan CONECT records for bonds where one end is
   a protein anchor atom (ASN ND2, SER OG, THR OG1) and the other is
   a sugar (anomeric C of any name in `SUGAR_RESNAMES` or matching
   `is_glycam_sugar`).

2. **Distance-based fallback**: for each protein anchor atom not yet
   detected, find the nearest sugar anomeric C (C1, or C2 for sialic)
   within 2.0 Å. Catches inputs without CONECT records.

The bonded sugar name lets `rename_glycosylated_protein_residues`
branch on FF: ASN→NLN renaming fires only when `is_glycam_sugar(name)`
is True. For PDB/CHARMM sugars, ASN keeps its standard name; HD22
removal still happens via `remove_extra_glycan_hydrogens`.

### `ffutils.py` — shared GLYCAM helpers

All four GLYCAM-aware tools (`prepare`, `minimize`, `protonate`,
`top --acpype`) share these utilities:

- `is_glycam_sugar(name)` → True for GLYCAM 3-char sugar codes
  (linkage `[0-9VWUZXYTSRQPvwuzxytsr]` + sugar + anomer `[AB]`, e.g.
  UYB/4YB/VMB/0YA) or caps (ROH/OME/TBT/CMET).
- `is_glycam_residue(name)` → True for any GLYCAM sugar OR glycoprotein
  residue (NLN/OLS/OLT).
- `detect_glycam_input(topology)` → returns
  `{'glycam_proteins', 'glycam_sugars', 'pdb_sugars', 'unknown_hets'}`
  sets of (chain, res_id). Drives the FF auto-swap in `protonate` and
  the H-polish short-circuit in `prepare`.
- `fix_atom_hetatm_records(pdb_path)` → post-processes the output PDB
  to rewrite `HETATM` → `ATOM` for any residue in `FORCE_ATOM_RESIDUES`
  (= `PROTEIN_RESIDUES`, which includes the 20 std + AMBER variants
  HID/HIE/HIP/ASH/GLH/CYX/CYM/LYN + GLYCAM glycoprotein residues
  NLN/OLS/OLT). OpenMM's `PDBFile.writeFile` defaults non-standard
  residue names to HETATM; this restores them to ATOM. Idempotent.
  Called after every PDB write in the three pipeline tools.
- Constants: `GLYCAM_PROTEIN_RESIDUES = {'NLN', 'OLS', 'OLT'}`,
  `GLYCAM_CAPS = {'ROH', 'OME', 'TBT', 'CMET'}`,
  `FORCE_ATOM_RESIDUES = frozenset(PROTEIN_RESIDUES)`.

### `ffutils.resolve_ff(user_ff, pdb_path, verbose)` — shared FF selection

Called by `prepare`, `minimize`, `protonate`, `pull`, `zbs` at the top
of `main()` to translate `--ff` into an OpenMM XML list. Accepts:

- `'auto'` / None — auto-detect from residue names in the PDB.
- A short-name in `FF_ALIASES` — `amber`, `amber14`, `amber19`,
  `amber+glycam`, `amber+lipid`, `amber+nucleic`, `charmm`, `charmm36`,
  `charmm2024`. Alias also runs auto-detect to check for an *upgrade*
  (user said `amber` but input has GLYCAM → upgrades to `amber+glycam`
  with a log line).
- A list of `.xml` paths — pass through unchanged (backward compat).

Auto-detection scanner in `detect_ff_from_pdb`:
- CHARMM markers (any hit → `charmm`): `HSD/HSE/HSP/ASPP/GLUP/LSN` (CHARMM
  protonation), `BGLC/AGLC/BMAN/AMAN/BGAL/AGAL/BFUC/AFUC/BGLCNA/AGLCNA/…`
  (CHARMM-GUI 4-char sugars), `CER1/CER160/CER180/…` (ceramides).
- GLYCAM markers (any hit → `amber+glycam`): `NLN/OLS/OLT` (glycoproteins),
  `ROH/OME/TBT/CMET` (caps), any 3-char sugar matching `is_glycam_sugar`.
- Ambiguous PDB sugar names (`NAG/BMA/MAN/…`): NEVER auto-select an FF
  (neither AMBER+GLYCAM nor CHARMM36 has templates for bare PDB names).
  Falls through to `amber` with a `dvbfixer convert` hint.
- CHARMM markers win over GLYCAM (unambiguous FF-prep signal).

Every tool prints a two-line banner: `FF: <alias> (<reason>)` + `→ <XML list>`.

### `ffutils.sanitize_protein_hetatm(pdb_path)` — shared HETATM/TER fix

Rewrites protein-residue `HETATM` → `ATOM` (any name in
`FORCE_ATOM_RESIDUES`) and drops spurious mid-chain `TER` records between
same-chain AA residues. Fixes OpenMM's peptide-bond inference on messy
inputs. Called by both `prepare` and `protonate` at the top of `main()`.
No-op on clean input.

### `protonate._text_rename_variants_to_parent` — variant → parent pre-rename

OpenMM's `PDBFile` parser only recognises standard AA residue names for
peptide-bond inference — mid-chain `LYN/HIE/HSE/…` blocks the peptide
bond from the previous residue's C to its N, and downstream
`addHydrogens` then fails on the ADJACENT residue with a misleading
"missing 1 C atom externally bonded" error.

Fix: rewrite AMBER (`HID/HIE/HIP/ASH/GLH/CYX/CYM/LYN`) and CHARMM
(`HSD/HSE/HSP/ASPP/GLUP/LSN`) variant names → standard parent
(`HIS/ASP/GLU/CYS/LYS`) in the RAW PDB TEXT before OpenMM parses.
Returns a `saved_map` merged into `_saved` before `addHydrogens`, so
`_restore_variants_post_addhydrogens` renames back correctly on the
output topology.

`--ff charmm`: after `addHydrogens` (which always uses AMBER variant
names because `hydrogens.xml` only speaks AMBER), rewrite output to
CHARMM36 equivalents via `_remap_amber_variants_to_charmm_in_pdb`:
`HID→HSD, HIE→HSE, HIP→HSP, CYX→CYS, CYM→CYM`. `ASH/GLH/LYN` have no
OpenMM-charmm36.xml template → folded back to `ASP/GLU/LYS` with a
WARNING (charge state can't be expressed in the shipped CHARMM XML).

### `align.py` — Kabsch superposition via sequence-paired atom matching

Pipeline-internal helper (no standalone subcommand). Used by
`zbs._maybe_align` after every step (default ON via `--align-to-input`;
opt-out `--no-align-to-input`) to superpose interim outputs onto the
ORIGINAL user input so residue-by-residue viewer comparisons line up.

Atom correspondences via per-chain global NW (`Bio.Align.PairwiseAligner`)
on protein CA sequences — folds AMBER/CHARMM variants to canonical parent
so `protonate`'s renames don't break the match. Harvests matching atoms
by name from aligned residues, runs numpy-SVD Kabsch, applies (R, t) to
the entire mobile universe (protein + HETATMs + waters).

I/O critical: MUST be line-level, not via MDAnalysis's PDB writer. MDA's
writer strips SEQRES/HELIX/SHEET/CONECT/REMARK/HEADER/TITLE — a fatal
bug in an earlier revision when `renumber`'s SEQRES got stripped by the
align pass and downstream `model` saw no gaps to fill.
`_apply_transform_preserving_headers` reads the input file and rewrites
only cols 30-54 of ATOM/HETATM lines, passing everything else through
byte-identical.

### `lig_params.build_ligand_generator` — GAFF2 per-ligand templates

See "Three force-field paths" section 3 above. Called by
`minimize --parametrize-ligands` (and `zbs --parametrize-ligands`)
before `create_forcefield_with_openff` so the resulting
`GAFFTemplateGenerator` gets registered on the ForceField for
`createSystem`.

`_extract_residue_sdf` builds each ligand's SDF via a heavy-atom-only
sub-`OBMol` (`ConnectTheDots()` + `PerceiveBondOrders()` on heavy atoms
alone, then hydrogens re-attached at their existing positions with
forced bond order 1) rather than running OpenBabel's whole-molecule
bond perception directly on the (already-hydrogenated) prepared PDB —
the latter was badly miscalling bond orders (near-every bond, including
N-C and C-H, coming back as order 2) once explicit hydrogens were
present, independent of any ligand-specific fix. `OpenFF`'s
`Molecule.from_file` trusts the SDF's bond orders/formal charges
directly with no independent re-derivation, so a wrong SDF means a
wrong (or radical, unparsable) GAFF2 template.

### `ffutils/ligand_valence.py` — ionizable-group + known-alkene overrides

Shared by both `prepare.glycan`'s heterogen-H passes (RDKit and
OpenBabel) and `lig_params._extract_residue_sdf`. Two independent
pieces of chemistry that geometry-only bond perception can't recover:
- `find_ionizable_terminal_oxygens_{rdkit,openbabel}` — detects
  carboxylate (C + ≥2 single-bonded terminal O) / sulfonate-or-sulfate
  (S + ≥3) / phosphate (P + ≥3) groups purely from connectivity (no
  per-ligand database), since these are never protonated at
  physiological pH regardless of what a naive degree-based H-filler
  would add. Generalizes beyond the two ligands (DAN carboxylate, EPE
  sulfonate) that surfaced the bug — covers any current or future
  ligand with these common groups.
- `_KNOWN_DOUBLE_BONDS` / `_H_COUNT_OVERRIDES` — a small per-ligand
  table for genuine double bonds with no geometric signature at
  crystallographic resolution (DAN's ring alkene C2=C3, from
  "2,3-didehydro" sialic acid; its C10=O10 amide carbonyl). Both
  RDKit's `AddHs` and OpenBabel's `addh()` compute added-H count from
  atom DEGREE, not bond-order-weighted valence, so setting the bond
  order alone has zero effect — `_H_COUNT_OVERRIDES` caps the H count
  directly, the same mechanism `glycan.py`'s pre-existing
  `_NO_H_ATOM_NAMES` used for amide carbonyls. The
  `apply_double_bond_override*` functions reset the residue's
  intra-residue bonds to single FIRST, then apply only the known
  correct double bond(s) — RDKit's/OpenBabel's own proximity-bonding
  perception can independently mark a *neighbouring* bond double too
  (bond-length shortening from conjugation), so patching bonds
  one-at-a-time risks leaving an over-valent atom.

## Cross-module patterns

### CLI dispatch (`cli.py`)

Each subcommand exposes `parse_args(argv=None)` and `main(argv=None)`.
`cli.py` reads `sys.argv[1]` (command name) and dispatches `sys.argv[2:]`
to the matching module's `main()`. Entry point in `pyproject.toml`:
`dvbfixer = "dvbfixer.cli:main"`.

Before a scientific command is dispatched, `structure_input.py` normalizes
every existing `.cif`/`.mmcif` path argument to a temporary PDB beneath the
resolved output/work directory. Gemmi handles PDBx/mmCIF, including sequences,
connections, and assembly metadata; Open Babel handles fractional-coordinate
small-molecule CIF. Valid one-character author chain IDs are preserved and
long IDs are deterministically mapped before fixed-column serialization. The
command then runs entirely on PDB as before, and mapping remarks are propagated
to generated PDB outputs. This boundary is also used by directory batch runs.

Before dispatch, shared runtime arguments are removed from the command argv.
`--log-file` enters an fd-level tee so Python output and inherited subprocess
streams reach both the terminal and an append-only log. Actual runs begin with
a version/timestamp/command header on stderr. `batch.add_runtime_help()` adds
logging help and a separate Batch Mode status group to every parser; supported
commands include the directory keys while unsupported commands explicitly say
that directory batch input is unavailable. The GUI generator omits these
runtime-only help groups from its command forms.

`--number-from-1` is a final-output normalization boundary. Renumber and model
normalize their completed artifacts (model also synchronizes `.dat`); ZBS
normalizes only its final copied PDB before postflight diagnose.

### CONECT record handling (`pdbutils.py`)

Three shared helpers:
- `build_serial_map(pdb_path)` → `(chain, resid, atomname) → serial`
- `remap_conect_records(input, new_serial_map)` → list of remapped CONECT lines
- `append_before_end(path, extra_lines)` → splice lines before END record

Used by `prepare`, `transplant`, `pull`, `top` for cross-stage bond
preservation. `prepare._canonicalize_conect_records` fixes malformed
CONECT spacing (5-digit serials that don't fit fixed-width columns).

### `.dat` file format (prepare/model/minimize)

JSON. Schema:
```json
{
  "description": "...",
  "total_added": 142,
  "residue_summary": {"A/GLY105": {"heavy": 4, "hydrogen": 3}},
  "added_atoms": [
    {"chain": "A", "resid": "105", "icode": "", "resname": "GLY",
     "atom": "N", "element": "N"}
  ],
  "variant_overrides": {"A:83": "HIP"}
}
```

`prepare` merges upstream `.dat` (from `model`) with its own additions
via key matching on `(chain, resid, icode, atom)`. `minimize` uses the
merged `.dat` to classify atoms into restraint tiers.

### Topology rebuild pattern (`prepare`, `minimize`)

When new atoms are added to an OpenMM topology (e.g. H atoms from RDKit),
the pattern is to build a fresh `Topology()` rather than mutating the
existing one:

1. Iterate `chain → res → atom` of the original topology
2. `new_top.addChain`, `addResidue`, `addAtom` for each
3. For each parent atom with new H to insert: `addAtom` the H, then
   `addBond(parent, h_atom)` to preserve bond connectivity
4. Re-add all `topology.bonds()` (mapped through old→new atom dict)
5. Wrap positions in `Quantity(list_of_Vec3, nanometer)`

Always include `addBond` for new H atoms — see "Heterogen H drift" gotcha
in BEST_PRACTICES.md.

## Hydrogen placement — Modeller not PDBFixer

`prepare` (and `protonate`, and `minimize` when it needs to add H)
deliberately routes hydrogen placement through OpenMM's
`Modeller.addHydrogens(forcefield, pH=..., variants=[...])`, NOT
through PDBFixer's `addMissingHydrogens(pH)`. Responsibility split:

| Step | Owner |
|---|---|
| Missing residues (SEQRES gaps) | `PDBFixer.findMissingResidues` + `addMissingResidues` (or `model`'s Modeller path) |
| Missing heavy atoms | `PDBFixer.findMissingAtoms` + `addMissingAtoms` |
| Terminal atoms (OXT) | `PDBFixer.addMissingAtoms` (via `missingTerminals`) |
| Nonstandard residue mapping | `PDBFixer.replaceNonstandardResidues` |
| Heterogen removal | `PDBFixer.removeHeterogens` |
| **Hydrogen placement** | **OpenMM's `Modeller.addHydrogens`** |

Why not PDBFixer's `addMissingHydrogens`? It uses an internal
`_describeVariant` that only recognises standard PDB names
(`HIS` / `ASP` / `GLU` / `CYS` / `LYS`). It silently ignores AMBER
variant labels (`HIE` / `HID` / `HIP` / `ASH` / `GLH` / `CYX` / `CYM`
/ `LYN`) coming from:

- input PDB atoms already labelled with variant names,
- `dvbfixer prepare --mutate CHAIN:RESNUM:HIP` etc.,
- `dvbfixer protonate`'s PROPKA + Reduce decisions.

Only `Modeller.addHydrogens` accepts a per-residue `variants=[...]`
list, so it's the only entry point that respects user intent about
protonation state.

The consequence: OpenMM's `addHydrogens`, not PDBFixer's, is the tool
whose CSER template misplaces `HG` on top of `OXT` (a known bug in
the CSER path when both HG is missing and OXT is present). Fixed by
running
`dvbfixer.ffutils.geometry.repair_misplaced_hydrogens(topology,
positions)` immediately after every `addHydrogens` call across
`prepare`, `protonate`, and `minimize`. See
`src/dvbfixer/ffutils/geometry.py`.

Callers that also need to walk the AMBER variant name back onto the
topology after `addHydrogens` returns (which rebuilds the topology
object) use `dvbfixer.ffutils.variants.rename_variants_to_parent_in_topology`
before + `restore_variants_post_addhydrogens` after.

## CLI dispatcher notes

- Each subcommand module exposes `parse_args(argv=None)` and
  `main(argv=None)` — the `argv` parameter allows the CLI dispatcher
  in `cli.py` to pass subcommand arguments.
- `cli.py` dispatches `sys.argv[2:]` to the appropriate module's
  `main()`.
- Entry point defined in `pyproject.toml`:
  `dvbfixer = "dvbfixer.cli:main"`.
- Six of the subcommand modules are packages rather than flat files:
  `minimize/`, `model/`, `prepare/`, `top/`, `ffutils/`, and `pdbutils/`
  were all packagized in the same commit (`2dfbabe`, "0.4.0: Phase 0-4
  refactor"); `diagnose/` was born as a package at 0.5.0. The `cli.py`
  import lines are unchanged — packages re-export `main` through
  `__init__.py`.

## GROMACS topology notes

- `top/pipeline.py` parses RTP files directly — no dependency on
  `pdb2gmx` or a GROMACS installation.
- FF files bundled in `FF/amber99sb-ildn-lipid21.ff/` and
  `FF/charmm36_ljpme-jul2022.ff/`. Used at build time for RTP parsing;
  output is modular `.itp` files, so no external FF directory is needed
  at runtime.
- Output is modular: `topol.top` has only `#include` directives +
  `[ system ]` + `[ molecules ]`. FF params in `ffparams.itp`, each
  chain in `{name}.itp`, water in `water.itp`, ions in `ions.itp`,
  position restraints in `posre_*.itp`, inter-chain SS in
  `interchain_ss.itp`.
- `_dedup_atomtypes()` (in `top/writers.py`) removes duplicate atom-type
  entries (e.g. HT, OT with heavy/real mass variants from #ifdef blocks).
- `_GLYCAN_LINKAGE_PARAMS` (in `top/ff_data.py`) adds extra bond / angle
  / dihedral parameters for glycosidic-linkage sites where OC311 →
  OC3C61 creates atom-type combos not in the standard CHARMM36
  distribution (by analogy with CC321D/CC321C variants). Also includes
  sialic-acid C2 linkage params (CC3062-OC3C61). Does NOT include
  ceramide-sugar CTO2-OC301 params — those are already in `ffbonded.itp`
  with proper multi-term dihedrals.
- `_read_ff_content(path)` strips all preprocessor directives
  (`#include`, `#define`, `#ifdef`, …) for clean inlining.
- `_write_water_topology(f, path)` extracts only the rigid (settles)
  version from water `.itp` files that have `#ifndef FLEXIBLE` /
  `#else` blocks.
- RTP `[ bondedtypes ]` header defines function types for bonds /
  angles / dihedrals / impropers. Bond entries with `-C` mean previous
  residue's C atom; `+N` means next residue's N atom.
- AMBER has explicit `NXXX` / `CXXX` terminal entries in RTP;
  CHARMM uses TDB patch files.
- CHARMM FF has ~2400+ residues across 9 RTP files: aminoacids
  (protein), carb (363 sugars), lipid (401), na (79 nucleic acids),
  cgenff (924 small molecules), ethers (25), metals (8), silicates (6),
  solvent/ions (77). All loaded at startup.
- Glycosidic linkages: remove HO + charge redistribution + atom-type
  change. Linked O atoms not in PDB have their combined charge (O + HO)
  redistributed to the anomeric carbon (C1 or C2 for sialic). O1/O2
  from RTP not in PDB are always skipped defensively — even if link
  detection missed the bond.
- Glycolipids (ceramide + sugar tree) build as a single moleculetype
  via `build_glycolipid_chain()`. Ceramide from `lipid.rtp`, sugars
  from `carb.rtp`. Ceramide-sugar bond: C1S-O1 (sugar O1 bridges).
  Ceramide O1+HO1 charge → C1S. Sugar O1 type: OC301 (not OC3C61).
  CTO2-OC301 params are already in `ffbonded.itp` (multi-term
  dihedrals — must not be redefined). CHARMM-GUI 4-char resnames
  (CER1, BGLC, …) detected via `read_pdb_chains()` extended-column
  parsing.
- `interchain_ss.itp` with `[ intermolecular_interactions ]` is
  auto-included in `topol.top` after `[ molecules ]` (GROMACS requires
  this directive after the molecules section). Contains both
  inter-chain SS bonds and protein-glycan bonds (ASN ND2 - NAG C1,
  r0=0.143 nm).
- Ions and buffer particles (BUF) are auto-detected in PDB by matching
  residue names against moleculetypes in `ions.itp`. Counted and added
  to the `[ molecules ]` section. Not built as chain topologies — their
  moleculetypes are defined in `ions.itp`. BUF atomtype (dummy, no LJ)
  added to `ffnonbonded.itp`.
- Water molecules (SOL/HOH/WAT/TIP3) counted by atom count / 3, not
  resseq dedup, to handle PDB resseq overflow in large systems
  (>10 k residues wrap at 9999).
- Small CGenFF molecules (ACET, ACEH, ACEM, …) detected by
  distance-based chain splitting (`_split_chain_by_distance`, gap
  > 4 Å). Single-residue chains of known RTP types are counted and
  built as separate moleculetypes. Terminal patches are NOT applied
  to non-protein residues.
- GRO file support: auto-detected by `.gro` extension, converted to a
  temp PDB via MDAnalysis (`_gro_to_pdb`). Original input path
  preserved for output-directory naming and system name.
- 4-char resnames from GROMACS output (ACET, ACEH, TIP3) handled via
  `_KNOWN_4CHAR_RESNAMES` in `top/ff_data.py`.
- PDB serial numbers wrap at 100000 (`serial % 100000`) for large
  systems. Resseq in extra molecule lines renumbered sequentially.
- PDB atom-name format: columns 13-16 = atom name (4 chars), column 17
  = altLoc (space), columns 18-20 = residue name. 4-char atom names
  (HE21) start at column 13; shorter names start at column 14 with a
  leading space.

## GLYCAM integration notes

- GLYCAM uses 3-character residue codes encoding linkage position +
  sugar identity + anomeric config (e.g. 4YB = β-GlcNAc linked at O4;
  VMB = β-Man linked at O3+O6).
- GLYCAM protein residues: NLN (glycosylated ASN), OLS (glycosylated
  SER), OLT (glycosylated THR).
- OpenMM's `PDBFile` does NOT infer intra-residue bonds for GLYCAM
  residues — must be added from FF templates.
- OpenMM's `PDBFile` does NOT add peptide bonds involving GLYCAM
  protein residues — must be added explicitly.
- OpenMM's `PDBFile` does NOT add sugar-sugar glycosidic bonds either.
  `add_glycam_bonds(positions=...)` (in `acpype_export.py`) detects
  them by distance: anomeric C1 (or C2 for sialic) within 2.0 Å of a
  linkage O2/O3/O4/O6 on another sugar. Without these, GLYCAM
  templates like 6LB that declare an external O bond fail to match
  ("missing 1 externally bonded O atom").
- NLN template expects only HD21 (not HD22) — ND2's other bond goes
  to the sugar (external bond).
- GLYCAM fragments from GLYCAM-Web include terminal atoms (OXT, H2,
  H3) that must be stripped when the fragment is mid-chain.
- `Modeller.loadHydrogenDefinitions('glycam-hydrogens.xml')` is
  required before `addHydrogens()` for GLYCAM residues.
- CYS involved in disulfide bonds must be renamed to CYX before OpenMM
  parametrization (detected from CONECT SG-SG bonds AND distance
  fallback within 2.5 Å).

### Shared GLYCAM helpers (`ffutils/`)

All three OpenMM-using tools (prepare / minimize / protonate) share
these:

- `ffutils.is_glycam_sugar(name)` — True for GLYCAM 3-char codes
  (linkage + sugar + anomer, e.g. UYB, 4YB, VMB, 0YA, 0fA, 2MA) or
  caps (ROH, OME, TBT, CMET).
- `ffutils.is_glycam_residue(name)` — True for any GLYCAM sugar OR
  glycoprotein residue (NLN/OLS/OLT).
- `ffutils.detect_glycam_input(topology)` — returns
  `{'glycam_proteins': set, 'glycam_sugars': set, 'pdb_sugars': set,
  'unknown_hets': set}` keyed by `(chain_id, res_id)`. Used by
  `protonate` and `minimize` to trigger the GLYCAM-aware path vs. the
  PDB-sugar fallback.
- `ffutils.fix_atom_hetatm_records(pdb_path)` — post-processes the
  output PDB to rewrite `HETATM` → `ATOM` for protein residues
  (including AMBER protonation variants HID/HIE/HIP/ASH/GLH/CYX/CYM/
  LYN and GLYCAM glycoprotein residues NLN/OLS/OLT). OpenMM's
  `PDBFile.writeFile` defaults non-standard residue names to HETATM;
  this helper restores them to ATOM. Called after every PDB write in
  prepare / minimize / protonate. Idempotent.
- Constants: `PROTEIN_RESIDUES` (includes NLN/OLS/OLT + AMBER
  variants), `GLYCAM_PROTEIN_RESIDUES = {'NLN', 'OLS', 'OLT'}`,
  `GLYCAM_CAPS = {'ROH', 'OME', 'TBT', 'CMET'}`, `FORCE_ATOM_RESIDUES
  = frozenset(PROTEIN_RESIDUES)`.
- `ffutils.build_glycam_system(ff_xmls, topology, positions, ...)` —
  packages the three-step GLYCAM ritual
  (`create_forcefield_with_openff` +
  `loadHydrogenDefinitions('glycam-hydrogens.xml')` +
  `add_glycam_bonds`) into one call so every GLYCAM-aware tool uses
  the same defensive try/except semantics.

### Shared FF selection (`ffutils.resolve_ff`)

Every OpenMM-using tool (`prepare`, `minimize`, `protonate`, `pull`,
`zbs`) accepts `--ff` as either a short-name alias (`auto`, `amber`,
`amber+glycam`, `amber+lipid`, `amber+nucleic`, `charmm`,
`charmm2024`, …) or an explicit list of OpenMM XML paths (backward
compat). Default: `auto`. Wired at the top of each tool's `main()`:

```python
from dvbfixer.ffutils import resolve_ff, print_ff_selection
args.ff, alias, reason = resolve_ff(args.ff, args.input, verbose=args.verbose)
print_ff_selection(alias, reason, args.ff)
```

`FF_ALIASES` in `ffutils/__init__.py` maps short names → XML lists.
`detect_ff_from_pdb(pdb_path)` scans residue names for **unambiguous**
markers:

- **CHARMM** (any hit → `charmm`): protonation names
  `HSD/HSE/HSP/ASPP/GLUP/LSN`; CHARMM-GUI 4-char sugar names
  `BGLC/AGLC/BMAN/AMAN/BGAL/AGAL/BFUC/AFUC/BGLCNA/AGLCNA/BGALNA/
  AGALNA/ANE5/BNE5/ANE5AC/BNE5AC/AIDO/BIDO`; ceramides
  `CER1/CER160/CER180/…`.
- **GLYCAM** (any hit → `amber+glycam`): protein `NLN/OLS/OLT`; caps
  `ROH/OME/TBT/CMET`; 3-char sugar codes matching `[linkage][sugar]
  [anomer]` via `is_glycam_sugar`.
- **Ambiguous PDB sugars** (`NAG/BMA/MAN/GAL/FUC/…`): NEVER
  auto-select an FF. Neither `amber+glycam` (needs GLYCAM 3-char
  codes) nor `charmm36.xml` (needs 4-char names) has templates for
  these bare names. Falls through to `amber` with a warning telling
  the user to `dvbfixer convert --to-amber` or `--to-charmm` first.

Precedence: CHARMM markers win over GLYCAM (protonation names are
full-file FF-prep signals). If the user asked for
`amber`/`amber19`/`amber14` but the input clearly has CHARMM or
GLYCAM markers, `resolve_ff` *upgrades* the choice and logs why. If
the user asked for `charmm` on a plain-protein input, no downgrade —
user's explicit choice wins.

`top/` uses a separate `--ff` namespace (`amber` or `charmm` mapping
to bundled GROMACS FF directories in `FF/`, parsed via
`rtp_parser.py`) — different format (RTP not XML), different set of
supported FFs, different alias-to-file mapping. See
`docs/force-fields.md` for the side-by-side.

## PDB format notes

- Residue identity = `(resSeq, iCode)` not just `resSeq`. Column 26
  (0-based) is the insertion code.
- `set_resid()` must write both the 4-char resSeq (cols 22-25) AND
  clear the iCode (col 26).
- Antibody structures use Kabat/Chothia numbering: insertion codes at
  CDR loops (52A, 82A-C, 100A-J). These are NOT chain breaks.
- GROMACS PDB output often has blank chain IDs and continuous
  numbering across chains.
- `PDBFile.writeFile(..., keepIds=True)` is required to preserve chain
  IDs when writing through OpenMM.
- Glycan residues (BGL, BMA, NAG, …) have C and N atoms but NOT
  peptide bonds — `split_chains.py` detects breaks by backbone C/N
  atom *presence*, not by residue-name filtering.
- CONECT serial remapping between PDB sources (acceptor vs graft) must
  use atom identity `(chain, resseq, atomname)`, not serial numbers —
  serials from different sources collide.
- A bare/minimal `TER\n` record (as short as 4 characters, no serial,
  resname, or padding) is valid PDB — but `line[11:]` on it returns an
  empty string, not an IndexError (Python doesn't raise on an
  out-of-range slice). `renumber.py`'s TER-handling previously relied
  on `line[11:]` carrying the trailing newline through, so a bare TER
  emitted a line with no newline at all, running directly into the
  next physical line (`TER    4748HETATM 4749  C1  ...`) — every
  downstream parser's line-start check then silently dropped that
  atom (and everything else on the merged line). Fixed 0.7.9 by
  explicitly ensuring the constructed TER line ends with `\n`.
- A deposited PDB can carry a stale/dangling `CONECT` record —
  referencing a serial number with no matching ATOM/HETATM line at
  all anywhere in the file (leftover cruft from whatever tool produced
  it, confirmed on a real structure). `renumber.py`'s `update_conect`
  previously passed such an unmapped serial through UNCHANGED
  (`serial_map.get(old_serial, old_serial)`) — and because dvbfixer
  renumbers everything into a dense, small range, that stale small
  number can coincide with the NEW serial assigned to a real,
  unrelated atom elsewhere in the file, fabricating a bond that never
  existed. Fixed 0.7.10: `update_conect` now returns `None` (whole
  record dropped) rather than a partially-correct line whenever any
  referenced serial isn't a real atom.

## Recommended areas for future work

Historical items 3 ("Tests") and 4 ("Stand-alone modular monolith")
were resolved in the Phase 0 – Phase 2 revision work: a pytest suite
covers the lightweight subcommands, and `top.py` / `prepare.py` /
`model.py` / `minimize.py` are now packages with the boundaries
called out in each `__init__.py`.

1. **Per-ligand antechamber for arbitrary ligands** — the
   `GAFFTemplateGenerator` integration landed as
   `minimize --parametrize-ligands`. Remaining polish: expose the same
   path on `prepare` for whole-system H-addition, and cache the
   antechamber output under a hash of the ligand's atom set to avoid
   re-running on identical residues across a pipeline.

2. **xtb v6.8+ when conda-forge ships it** — fixes the `$fix` bug that
   causes ~0.1 Å drift on nominally-frozen anchors during `--xtb-refine`.

3. ~~**Remaining top extraction**~~ — done. `ff_data.py`, `writers.py`,
   `acpype.py`, and now `types.py` / `glycan.py` / `topology_builder.py`
   are all split out of `top.py`. `top/pipeline.py` shrank from ~2900
   to ~1300 lines and is now CLI orchestration + PDB I/O only; the
   `TopologyBuilder` class (`build_chain` / `build_glycan_chain` /
   `build_glycolipid_chain`) lives in `top/topology_builder.py`, and
   glycan-tree detection (`detect_glycan_links` / `build_glycan_trees`)
   lives in `top/glycan.py`. See `top/__init__.py` for the current
   module map.

4. ~~**Docs migration**~~ — done. Per-command behavior now lives under
   `docs/commands/`, current architecture lives here and in `docs/domain-model.md`,
   and `docs/DESIGN_NOTES.md` remains only as a historical migration stub.
   `AGENTS.md` is the canonical coding-agent instruction source; `CLAUDE.md` is a
   compact harness compatibility entry point.

## GUI workspace boundary

The GUI's Vite middleware uses `gui/server/workspace-api.ts` as the only
runtime authority for workspace files and artifact metadata. Each workspace
has a revisioned `structures/projects/<id>/workspace.json`; file reads go
through a containment-checked `/api/workspaces/:id/files/...` route. The old
global `/structures/index.json` scanner and `/api/library/{meta,star,folder,move}`
routes have been removed. Legacy top-level and per-workspace indexes are read
only by idempotent, non-destructive migrations and remain on disk as recovery
sources.

`gui/server/naming-api.ts` provides the first versioned API vertical slice:
`POST /api/v1/workspaces/:workspaceId/naming-conversions`. It resolves an input
by manifest artifact ID, invokes the non-destructive Python `atom-names` command,
validates its bounded JSON report and output digest, then re-reads the latest
manifest before registering exactly one output. `naming-api-schema.ts` is the
shared TypeBox source for runtime validation and `GET /api/v1/openapi.json`.
Scientific naming policy remains in Python.

`gui/server/api-routes.ts` is the host-neutral API composition root.
`api-plugin.ts` is a thin Vite development adapter, while `standalone.ts` uses
Node HTTP and Connect to serve the complete API plus the built `dist/` client.
The standalone process defaults to loopback, rejects overlapping static/data
roots, terminates tracked DVBFixer children during shutdown, and drains HTTP.
`auth.ts` authenticates configured static bearer principals
at the shared route boundary. Version 2 workspace manifests carry an owner and
reader/writer ACL; authorization occurs before workspace path resolution.
Restrictive CORS, bounded requests/workspace publication, process admission,
request-rate limiting, and same-host cross-process manifest locking are shared
across both hosts. `deployment-limits.ts` supplies the standalone server's
opt-in fail-closed check for the systemd/cgroup-v2 resource profile. TLS, audit
retention, durable scheduling/event delivery, and distributed coordination
remain deployment gaps.

`dvbfixer-runner.ts` owns one process-wide active permit limit and bounded FIFO
waiting queue. Vite and standalone initialize the same limits; both terminate
tracked scientific children during host shutdown. Saturated queues reject work
before process creation.
