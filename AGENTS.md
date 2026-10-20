# AGENTS.md

Guidance for coding agents working in this repository. This is the canonical
agent instruction file; `CLAUDE.md` is retained for compatibility with tools
that discover that filename.

## What this project is

**dvbfixer** — a Python package providing CLI tools for preparing PDB
(Protein Data Bank) structural biology files. Installed as a single
`dvbfixer` command with 24 subcommands, plus the React/Node GUI in `gui/`.

## Prep backends: `legacy` (default) vs `tleap-reduce` (opt-in)

`feat/tleap-reduce-backend` was merged into `main` (`5ca7e17`) — it is
**not** a separate in-progress branch anymore; `src/dvbfixer/
prep_backend.py` and `--backend {legacy,tleap-reduce}` on `prepare`/
`zbs` ship on `main` today. `tleap-reduce` swaps
`PDBFixer.addMissingAtoms` + `Modeller.addHydrogens` for **AmberTools
`tleap` + MolProbity `reduce`** (subprocess-based, deterministic,
L-only by construction), fixing the D-Cα (openmm/pdbfixer#145) and
coincident-H (`Modeller.addHydrogens` bug) issues that surface on
gap-filled model outputs — verified against
`tests/fixtures/regressions/{1EMV,1FR2,2VLN,2VLQ}.pdb` (zero D-Cα, zero
coincident atoms). See the hard rules below for the full behavior
split: `legacy` remains the default because it's the only backend that
handles every input class (glycans, ligands, PTMs, covalent HETATM
links); `tleap-reduce` is opt-in for pure-protein inputs and rejects
non-canonical residues.

## Where to look

| For… | Read… |
|---|---|
| Command inventory + quick start | [`README.md`](README.md) |
| Per-command "how to use" prose | [`docs/commands/`](docs/commands/) |
| Exact `--help` output (auto-generated, matches code) | [`docs/reference/`](docs/reference/) |
| Module map, data flow, `.dat` schema | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| End-to-end recipes | [`docs/pipelines.md`](docs/pipelines.md), [`BEST_PRACTICES.md`](BEST_PRACTICES.md) |
| Known issues + active workarounds | [`docs/known-issues.md`](docs/known-issues.md) |
| Accepted architecture decisions | [`docs/adr/`](docs/adr/) |
| Historical documentation migration stub | [`docs/DESIGN_NOTES.md`](docs/DESIGN_NOTES.md) |
| Installation + Modeller license | [`docs/installation.md`](docs/installation.md) |
| Implemented domain policies | [`docs/domain-model.md`](docs/domain-model.md) |
| Agent task/contract/invariant map | [`docs/agent/README.md`](docs/agent/README.md) |
| Relaxation research and proposed benchmarks | [`docs/research/whole-complex-relaxation.md`](docs/research/whole-complex-relaxation.md) |
| Reconstruction/modeling backend research | [`docs/research/reconstruction-and-modeling-backends.md`](docs/research/reconstruction-and-modeling-backends.md) |
| Force-field selection matrix | [`docs/force-fields.md`](docs/force-fields.md) |
| Tracked structural test inputs, provenance, and checksums | [`tests/fixtures/README.md`](tests/fixtures/README.md) |
| Corrected cc89 Apple Silicon restart, portable controls, and remaining MPS port | [`docs/plans/apple-cc89-handoff.md`](docs/plans/apple-cc89-handoff.md) |

## Environment

```bash
micromamba create -f environment.yml
micromamba run -n dvbfixer pip install -e ".[dev]"
```

`.[dev]` pulls in pytest / ruff / mypy. Without dev extras the tools
still install and run.

Modeller needs a free academic license from
<https://salilab.org/modeller/registration.html>. Set the key in
`<env>/lib/modeller-10.8/modlib/modeller/config.py`.

The Homology workspace and `dvbfixer msa` shell out to external MSA engines.
`environment.yml` installs MAFFT, MUSCLE 5, and Clustal Omega; their required
`PATH` names are `mafft`, `muscle`, and `clustalo`. Keep MUSCLE pinned to v5
because v3 uses incompatible arguments. Diagnose the active environment with
`dvbfixer msa --list-engines`; `auto` prefers MAFFT, then MUSCLE, then Clustal
Omega. Keep user-facing installation details in
`docs/installation.md#multiple-sequence-alignment-executables` and link to
that section instead of duplicating platform instructions elsewhere.

The GUI Library is a workspace/project switcher. Project manifests and owned
artifacts live below `gui/structures/projects/<id>/`; workflow API requests are
scoped by `workspaceId`. Homology supports multiple workflows per workspace,
target parsing from workspace files, active-primary template capture, parsed
chain selectors, Clustal-style continuous alignments, and synchronized
template-residue selection for Modeller fragments. Preserve project path
isolation and the one-time legacy Library migration.
Homology GUI behavior is documented in `docs/gui-homology.md`. The GUI writes
`template-plan.json`; all scientific materialization belongs in Python
`dvbfixer homology --template-plan`, specifically
`src/dvbfixer/homology_plan.py`. That path groups template chains by target,
fits them into a shared reference frame, resolves zero-based half-open masks
(earlier template wins overlap), and creates ONE
`selected_template_mosaic.pdb` plus its matching PIR. Do not regress to one
Modeller `known` per selected span: Modeller independently repositions
non-overlapping knowns and destroys mosaic geometry. Multi-chain groups must
all contain a chain from the first template structure. Logical `VH`/`VL`
target IDs map to distinct PDB chains `H`/`L`; never truncate both to `V`.
`dvbfixer salign` defaults to sequence-guided Biopython Cα superposition;
Modeller SALIGN remains an explicit optional engine.

**Python is pinned `>=3.11,<3.14`** in `environment.yml`. Do not loosen
this. propka 3.5.1 reads `self.__annotations__` (instance-level) inside
its `Parameters` dataclass; Python 3.14's PEP 649/749 annotation change
makes instance `__annotations__` raise `AttributeError`, which crashes
`dvbfixer protonate` / `prepare` at the PROPKA step. Repro:
`python -c "from propka.parameters import Parameters; Parameters().__annotations__"`
returns a dict on <3.14, raises on 3.14.

**NumPy is pinned `<2.5` while mypy targets Python 3.11.** NumPy 2.5 dropped
Python 3.11 and its stubs contain Python 3.12-only `type` statements, so mypy
cannot parse them under the repository's `python_version = "3.11"` baseline.
Keep the constraint synchronized in `pyproject.toml`, `environment.yml`, and
CI until the project's minimum Python version becomes 3.12.

**On macOS Docker / VirtioFS, create the env on the container's native
overlay filesystem, not on a host bind mount.** `/home/agent` here is a
`fakeowner` (macOS `/Users`) bind mount that is case-insensitive and
rejects libmamba's `copy_symlink` on ncurses's case-variant terminfo
pairs (`share/terminfo/32/2621A` vs `2621a`), failing the install with
`filesystem error: cannot copy symlink: Invalid argument`. `always_copy`
/ `--copy` do NOT help — copy mode still recreates symlinks rather than
dereferencing them, and there is no micromamba flag to skip/deref them.
Fix: point the root at an overlay path, e.g.
`sudo mkdir -p /opt/mamba && sudo chown -R agent:agent /opt/mamba`,
then `export MAMBA_ROOT_PREFIX=/opt/mamba` before `micromamba create`,
and keep `/opt/mamba/envs/dvbfixer/bin` on `PATH` so subprocesses that
call bare `dvbfixer` resolve it. See
[docs/known-issues.md](docs/known-issues.md) for the full write-up.

## Working in this codebase — hard rules

- **Default prep backend is `legacy`** (Modeller+PDBFixer). Handles
  every input class dvbfixer supports (glycans, ligands, PTMs,
  covalent HETATM links). The chirality invariant is guaranteed by
  minimize's post-phase-2 unconditional force-reflect (0.7.4+), so
  PDBFixer's D-Cα risk is neutralised downstream — legacy is safe
  by construction now. **`tleap-reduce`** is retained as opt-in
  (`--backend tleap-reduce`) for pure-protein inputs where the user
  specifically wants deterministic L-only heavy atoms from tleap
  itself; it rejects non-canonical residues. When the tleap-reduce
  backend IS selected, all its rules below still apply.
- **Do not remove `keepIds=True`** from any `PDBFile.writeFile` call.
  Losing chain IDs mid-pipeline breaks the `.dat` handoff that
  `minimize` uses for tiered restraints.
- **`split --assembly ID|all` is metadata-driven, not empirical.** Keep
  `REMARK 350` parsing and BIOMT rendering in `biological_assembly.py`; the
  legacy distance/number-reset path in `split_chains.py` remains the default.
  Assembly output preserves residue numbers unless `--renumber` is explicit,
  transforms ANISOU with the same rotation as coordinates, and must fail
  before writing if any requested assembly is invalid.
- **PROPKA + MolProbity Reduce run INSIDE the legacy prepare backend**
  (since 0.7.7). The helper
  `dvbfixer.prepare.pipeline._run_propka_reduce_variants` produces
  the variant map for `Modeller.addHydrogens(variants=[...])`;
  disable per-flag via `--no-propka` / `--no-protassign`. Standalone
  `dvbfixer protonate` still exists as a post-hoc re-protonation
  tool.
- **Ligand SMILES input is optional and authoritative when supplied**
  (since 0.7.20). `prepare` and `zbs` accept repeatable
  `--smiles 'RESNAME=SMILES'` mappings for isolated, single-residue small
  molecules. Mapped residues preserve PDB heavy-atom names and coordinates;
  SMILES supplies bond orders, aromaticity, formal charge, and H count.
  Unmapped ligands, and every invocation without `--smiles`, retain the
  automatic RDKit/OpenBabel path. Do not apply `--ph` to a supplied ligand:
  its SMILES already selects the microspecies. Graph matching must fail rather
  than guess for incompatible, chemically ambiguous, or covalently attached
  residues. Ionized terminal oxygens may be resonance-equivalent; preserve
  the normalization in `prepare/smiles.py::_chemical_signature`.
- **`_run_propka_reduce_variants` must run AFTER
  `PDBFixer.addMissingAtoms()`, never before (since 0.7.11).** Both
  PROPKA and Reduce need a complete heavy-atom set to make any real
  decision. Running them on the raw (possibly heavy-atom-incomplete)
  input meant a residue with genuinely missing heavy atoms (confirmed
  on a real structure: a HIS with its entire imidazole ring absent —
  crystallographic disorder, not a dvbfixer bug) got no PROPKA result
  at all — not "neutral", just absent — so the *existing*
  `decide_protonation`/`--his-default` fallback (which only fires for
  residues PROPKA *did* analyze) never ran, and the variant fell
  through to OpenMM's own fragile `Modeller.addHydrogens` auto-detect,
  which raises an unrecoverable `ValueError` with no way to recover
  once inside it. `run_pdbfixer` (`prepare/pipeline.py`) now calls
  PROPKA/Reduce on a temp PDB written from `fixer`'s state right after
  `addMissingAtoms()` + the chirality fix — not on `input_path`.
- **Never call `fixer.addMissingAtoms()` directly (since 0.7.12,
  `fix/seeded-atom-rebuild` branch) — call
  `dvbfixer.ffutils.geometry.rebuild_missing_atoms_with_retry(fixer,
  ...)` instead.** PDBFixer's own `addMissingAtoms(seed=None)` rebuilds
  a missing sidechain via template-overlay + local minimization; if
  that result clashes with a neighbor (< 0.13 nm, its own
  `_findNearestDistance` cutoff) it falls back to UNSEEDED Langevin
  dynamics (300 K, up to 2000 steps) to kick the new atoms apart —
  genuine stochastic MD whose escaped conformation differs run to run
  on the *exact same input* (confirmed: 11 truncated LYS residues in
  `tests/fixtures/8cz8/8cz8_t_u.pdb` chain E). `rebuild_missing_atoms_with_retry`
  retries with explicit seeds (1..5) until the rebuild passes a
  chirality + clash check, snapshotting `fixer.topology`/`positions`
  before each attempt (PDBFixer builds an entirely new `Topology` per
  call and only reassigns those two attributes at the end — the
  pre-call objects are never mutated in place, so this is a correct,
  cheap way to retry without reconstructing PDBFixer). All 5 call
  sites (`prepare/pipeline.py`, `minimize/pipeline.py` ×2,
  `protonate.py`, `top/pipeline.py`) route through it. This fixes the
  *rebuild's* non-determinism at the source — it does not replace or
  weaken `minimize`'s existing reflect/re-minimize/force-reflect
  safety net, which still fires (rarely) for residues whose full-
  system FF minimum genuinely prefers D, a separate phenomenon this
  doesn't (and isn't meant to) eliminate.
- **`prepare.pipeline.run_pdbfixer`'s call order must be
  `findMissingResidues()` (+ deletion-scrub) ->
  `findNonstandardResidues()` -> `replaceNonstandardResidues()` ->
  `removeHeterogens()` -> `findMissingAtoms()` -> rebuild — never
  `findMissingAtoms()` before `removeHeterogens()`/
  `replaceNonstandardResidues()` (fixed 0.7.12).** Both of those two
  PDBFixer calls rebuild an entirely new `Topology` internally
  (`Modeller(...).delete(...)`), which silently invalidates an
  earlier-computed `missingAtoms` dict — it's keyed by Residue OBJECT
  IDENTITY against the topology that existed at `findMissingAtoms()`
  time, and PDBFixer's own `_addAtomsToTopology` looks residues up in
  it by identity. Getting this order wrong means `addMissingAtoms()`
  silently adds ZERO heavy atoms for every genuinely-missing sidechain
  whenever heterogens are stripped (confirmed pre-existing on `main`
  through 0.7.11: `E/LYS299` in `tests/fixtures/8cz8/8cz8_t_u.pdb` stayed
  backbone+CB straight through `prepare`, despite PDBFixer's own
  verbose log correctly reporting `CG`/`CD`/`CE`/`NZ` as missing
  beforehand). `findMissingResidues()` is safe to call early —
  it's keyed by `(chain.index, indexInChain)`, a positional pair that
  survives the later rebuilds, unlike Residue-object identity.
- **Do not call `PDBFixer.addMissingHydrogens(pH)`.** On the new
  backend, H placement is Reduce's job (subprocess). On the legacy
  backend, use `modeller.addHydrogens(forcefield, pH=..., variants=[...])`.
  PDBFixer's `addMissingHydrogens` uses its own `_describeVariant`
  that only recognises standard PDB names (HIS / ASP / GLU / CYS /
  LYS) — it ignores AMBER variant labels (HIE / HID / HIP / ASH /
  GLH / CYX / CYM / LYN). On the legacy path, follow every
  `Modeller.addHydrogens` call with
  `dvbfixer.ffutils.geometry.repair_misplaced_hydrogens(topology,
  positions)` (widened 2026-07-24 to also break sibling-H clashes
  via proper sp3 tetrahedral placement).
- **Chirality invariant**: `dvbfixer.ffutils.geometry.assert_all_l`
  must succeed after every heavy-atom repair. `find_d_residues`
  and `fix_ca_chirality` are the detector and reflector primitives.
  `build_ca_chirality_force` protects every initially-L N–CA–C–CB centre with
  a one-sided signed-volume wall during minimize. It uses Cartesian products,
  not an improper dihedral, so it has no torsion singularity. Reflection is an
  emergency-only recovery followed by guarded local minimization; if L
  geometry is not restored, raise `ChiralityError` and write no output. Record
  emergency repairs in `REMARK 999 DVBFIXER CHIRALITY_REPAIR` so diagnose can
  warn about possible hydrogen-angle strain. Zero D-Cα output remains
  non-negotiable.

- **Unified CLI runtime options**: `cli.py` removes `--log-file` and batch
  arguments before subcommand parsing. `runtime.tee_output` captures Python and
  inherited child-process stdout/stderr at file-descriptor level. Every parser
  calls `batch.add_runtime_help`; every tool's help therefore states whether
  directory batch input is supported. Supported tools show the four batch keys;
  unsupported tools show an explicit status description. The GUI generator
  excludes the informational `Global logging` and `Batch mode` groups.
- **CIF is normalized once at the CLI boundary.** `structure_input.py` uses
  Gemmi for PDBx/mmCIF and Open Babel for small-molecule crystallographic CIF,
  writes a validated temporary PDB below the output/work directory, and then
  calls the existing command unchanged. Preserve valid single-character chain
  IDs; map only incompatible IDs and propagate `CIF_CHAIN_MAP` remarks. Do not
  add ad-hoc CIF readers inside scientific pipelines or silently truncate data
  that exceeds fixed-column PDB limits.
- **Final numbering normalization**: public spelling is `--number-from-1` on
  renumber/model/zbs. ZBS applies it only after copying the final output and
  before postflight diagnose, never to intermediate `.dat` identifiers. Model
  normalizes each output candidate and its residue-keyed `.dat` sidecar.
- **Do not read a `.dat` file with hand-rolled `json.load`.** Use
  `dvbfixer.ffutils.dat.DatRecord` — the schema (added_atoms,
  variant_overrides, removed_residues, residue_summary,
  templates, target_chains) lives there, `total_added` is derived
  on save, and merge semantics ("downstream wins on collision") are
  codified.
- **Do not re-implement AMBER/CHARMM variant handling.** The four
  functions in `dvbfixer.ffutils.variants`
  (`scan_variant_names`, `text_rename_variants_to_parent`,
  `rename_variants_to_parent_in_topology`,
  `restore_variants_post_addhydrogens`) are the canonical dance for
  making OpenMM's peptide-bond inference survive a mid-chain
  LYN/HIE/HSD. `minimize/pipeline.py` calls
  `text_rename_variants_to_parent` BEFORE `PDBFile.load` so OpenMM
  can infer intra-residue bonds — its `_standardResidues` set does
  not include AMBER variants and topology has zero bonds for them
  otherwise.
- **Do not use `_classify_variant` or `_STD_PKA`** (both deleted in
  0.7.4). PROPKA-driven variant decisions belong in
  `dvbfixer.protonate.decide_protonation` — it filters by PROPKA
  group type (so N+/C- pKas don't overwrite side-chain pKas) and
  keys by `(chain, resnum, icode)`. `prep_backend.run_prep` layers
  Reduce's HID/HIE tautomer under PROPKA's HIP decision. Do NOT
  bring back the raw-pka dict path.
- **Force strip-H + `Modeller.addHydrogens(variants=[...])` when
  `amber_renames` is non-empty in minimize.** `addHydrogens` copies
  input bonds but never rebuilds missing ones from templates, and
  only ADDS missing H (never REMOVES extras). Strip-and-readd is
  the only path that produces a topology whose atoms AND bonds
  match the variant template. The keep-H fast path stays for the
  no-variant common case.
- **Cap the pH passed to `Modeller.addHydrogens` at 9.99.** OpenMM's
  `hydrogens.xml` gates HZ3 with `maxph="10.0"` and at pH > 10
  produces LYS residues that miss HZ3 (template mismatch). Variants
  from PROPKA already carry the true protonation state, so the
  auto-selection heuristic driven by pH is redundant.
- **Do not unconditionally drop SG-SG bonds in
  `_drop_spurious_inter_aa_bonds`.** The filter drops non-peptide
  inter-residue bonds between two standard AAs, but disulfides
  (SG-SG on CYS-family residues: CYS/CYX/CYM) are kept — dropping a
  *genuine* one severs the disulfide during minimize and lets it
  relax apart (fixed 0.7.4). Since 0.7.8 the function also resolves
  *spurious extra* SG-SG bonds down to one partner per atom (via
  `valid_ss_pairs` snapshot-and-restore, or nearest-distance matching
  when `positions` is given) — OpenMM's own `PDBFile.__init__` and
  `PDBFixer.addMissingAtoms()` both call `Topology.
  createDisulfideBonds()`, a pure distance-cutoff scan with no 1:1
  matching, so tightly-packed CYS clusters can otherwise give one SG
  atom two or three "partners" and crash `createSystem` with "N S
  atom(s) too many". The invariant is "every SG has at most one SG-SG
  partner, and a genuine one is never removed" — not "every SG-SG
  bond survives unconditionally."
- **Do not skip the `build_glycam_system` wrapper.** It packages
  the three-step GLYCAM ritual (`create_forcefield_with_openff` +
  `loadHydrogenDefinitions('glycam-hydrogens.xml')` +
  `add_glycam_bonds`); reproducing it inline is how prep/minimize/
  protonate got out of sync last time.
- **Do not add `# type: ignore` to files under strict mypy** without
  a concrete reason. The strict-target list in `pyproject.toml`
  (`cli.py`, `ffutils/`, `pdbutils/`, `align.py`) is enforced in CI.
- **Do not edit `docs/reference/*.md` by hand.** They're generated
  from each subcommand's `parse_args()`. Run
  `python scripts/gen_cli_reference.py` after touching any argparse.
  CI enforces this with `--check`.
- **Do not re-implement ionizable-group or ligand-alkene knowledge
  outside `dvbfixer.ffutils.ligand_valence`.** Both
  `prepare.glycan`'s RDKit and OpenBabel heterogen-H passes and
  `lig_params._extract_residue_sdf` share it. Carboxylate/sulfonate-
  or-sulfate/phosphate over-protonation is detected purely from
  connectivity (`find_ionizable_terminal_oxygens_*`) — general, not
  per-ligand. Genuine alkenes/carbonyls with no geometric signature
  at crystallographic resolution (DAN's ring C2=C3, "2,3-didehydro"
  sialic acid) need a `_KNOWN_DOUBLE_BONDS` / `_H_COUNT_OVERRIDES`
  entry — note that RDKit's `AddHs`/OpenBabel's `addh()` compute
  added-H count from atom DEGREE, not bond-order-weighted valence, so
  setting bond order alone has zero effect on H count; only
  `_H_COUNT_OVERRIDES` actually changes it.
- **`lig_params._extract_residue_sdf` builds a heavy-atom-only
  sub-`OBMol` first** (`ConnectTheDots()` + `PerceiveBondOrders()` on
  heavy atoms alone, hydrogens re-attached after at forced bond order
  1) rather than running OpenBabel's whole-molecule bond perception
  on an already-hydrogenated PDB directly — the latter badly
  miscalls bond orders once explicit H's are present (near-every
  bond, including N-C and C-H, came back order 2), independent of any
  per-ligand fix. `OpenFF`'s `Molecule.from_file` trusts the SDF's
  bond orders/formal charges as-is with no independent re-derivation.
- **`glycam.convert_to_glycam`/`convert_to_charmm` must pass through
  non-ATOM/HETATM/CONECT header records** (SEQRES, HELIX, SHEET,
  CRYST1, ...) via `_extract_passthrough_header_lines`, mirroring
  `align.py`'s `_apply_transform_preserving_headers` pattern. Losing
  SEQRES breaks downstream `model` gap-filling for anyone piping
  `convert` straight into `model`/`zbs`. Glycosidic-bond detection
  must always supplement CONECT-derived bonds with the
  distance-based detector (`_merge_glycosidic_bonds`) rather than an
  either/or gate — a real PDB can have CONECT for *some* but not all
  of its glycosylation sites (a genuine annotation gap, not something
  dvbfixer caused), and trusting CONECT exclusively whenever it's
  present at all silently drops the undocumented sites.
- **`model.main` runs CONECT inference (`_materialise_inferred_pdb`)
  BEFORE Modeller, not after.** Modeller has no other way to know two
  chains are covalently linked (e.g. an under-annotated
  N-glycosylation site with a real bond but no CONECT/LINK in the
  deposited PDB) and can reposition an undocumented chain arbitrarily
  far from its anchor during structure-building — fixing CONECT
  after Modeller runs is too late, the damage is already done.
  `--no-infer-conect` opts out; `zbs.py` threads the same flag
  through to `model`.
- **`model/renumber.py`'s `_interpolate_gaps` internal-gap branch must
  never number a gap backward from its right flank when there isn't
  enough room (since 0.7.13).** When an internal gap's two flanking
  residues are numerically adjacent (or too close) in the INPUT's own
  numbering — confirmed on a real scFv construct
  (`tests/fixtures/8cz8/8cz8_a_u.pdb`/`8cz8_a_b.pdb`, chain C: a disordered
  (GGGS)×4 linker between VL and VH has no density, and the depositor
  numbered VH's first residue immediately after VL's last one,
  reserving zero resSeqs for the missing linker) — numbering the gap
  backward from `right` (`right - gap_len + k`) collides with resSeqs
  already assigned further left. Place the gap sequentially from
  `left + 1` instead (same formula as the "enough room" branch) and
  shift every already-placed resSeq downstream by the deficit (WARN
  emitted) — mirroring the N-terminal branch's existing
  shift-the-rest-of-the-chain pattern for the equivalent case at the
  start of a chain. `build_resnum_mapping`'s align2d-mask fallback
  path must call `_interpolate_gaps` directly rather than carrying its
  own second copy of this logic — the two had already drifted out of
  sync once (the duplicate lacked the former internal
  `renumber_from_1` handling) before
  this bug was found.
- **All FASTA/SEQRES placement must use `sequence_alignment.py` (since
  0.7.16), never a greedy "find the next same residue" loop.** Greedy
  subsequence matching scattered 8B01 chain C's exact 104-residue block
  across reference positions 27-507 and fabricated a 377-residue loop.
  `renumber`, `trim_terminal_gaps`, Modeller's PIR fixer, and model residue
  restoration must share the same affine semi-global placement. Under
  `--no-terminal`, crop outside the first/last observed reference anchors
  but preserve every reference gap between those anchors for modeling.
- **A bare/minimal `TER\n` line (4 chars, no serial/resname/padding)
  is valid PDB.** `line[11:]` on one returns `''` silently (no
  IndexError on an out-of-range slice) — `renumber.py`'s TER handling
  must explicitly ensure the constructed output line ends with `\n`,
  or the next physical line merges directly onto it
  (`TER    4748HETATM 4749  C1  ...`) and every downstream parser
  silently drops that atom.
- **`minimize`'s post-reflect local relax re-anchors restraints to
  the NEW position, never the old one.** After the unconditional
  force-reflect fallback (chirality invariant above), a plain
  follow-up `minimizeEnergy` would pull the reflected sidechain back
  toward the FF's D-preferring minimum — because the restraint's
  anchor (`x0,y0,z0`) still points at the pre-reflection coordinate.
  Update `restraint`'s per-particle anchor to the reflected residue's
  current position FIRST (backbone atoms are untouched by
  `fix_ca_chirality` so this is a no-op for them), then minimize —
  this lets genuinely unrestrained neighbours (hydrogens) relax out
  of any inter-residue clash the rigid reflection introduced, with no
  energetic path back to D. Still followed by a `find_d_residues`
  sanity check with unconditional re-reflect (no minimize) as a
  fallback — the zero-D-Cα guarantee stays non-negotiable either way.
- **`renumber.py`'s `update_conect` drops a CONECT record rather than
  partially rewriting it when any referenced serial isn't a real atom
  in the file.** Some deposited PDBs carry stale/dangling CONECT
  records (confirmed on a real structure: a record referencing
  serials with no matching ATOM/HETATM line at all — leftover cruft
  from whatever tool produced the file, not something dvbfixer
  caused). The old fallback (`serial_map.get(old_serial,
  old_serial)`) passed such a serial through UNCHANGED — and because
  dvbfixer renumbers everything into a dense, small range, that stale
  number can coincide with the NEW serial assigned to a real,
  unrelated atom, fabricating a bond that never existed. This was the
  true root cause of a "tons of incorrect bonds" report on a glycan
  residue whose real chemistry (and every other bond-detection layer
  touching it) was already correct — a partially-wrong CONECT record
  is worse than a dropped one.
- **`acpype_export.add_glycam_bonds` must import `nanometer` and
  `is_glycam_sugar`/`_is_glycam_sugar` directly, never inside a
  swallowing `try/except`.** It was dead code for an entire release
  (0.7.8) because it imported `KNOWN_GLYCAN_SMILES` from
  `dvbfixer.ffutils` — a symbol that never existed — and the
  resulting `ImportError` was caught by a `try/except Exception` that
  ALSO (incidentally) defeated the unrelated `openmm.unit.nanometer`
  import, so every call silently no-opped instead of populating
  sugar-sugar/protein-glycosylation bonds. Reuse the module's own
  `_is_glycam_sugar` (covers both GLYCAM-canonical codes and plain PDB
  sugar names in one function) rather than `ffutils.is_glycam_sugar`
  alone (GLYCAM-codes-only).
- **CONECT-inference (`pdbutils/inference.py::_apply_filter`) and
  `prepare/glycan.py`'s RDKit/OpenBabel heterogen-H bond-carrying
  loops all need the SAME same-residue distance guard for sugar/GLYCAM
  residues.** OpenBabel's `ConnectTheDots` and RDKit's
  `proximityBonding=True` have no template for these residues (unlike
  the 20 canonical AAs, which `_apply_filter` already guards) and can
  propose same-residue "bonds" at 2.5+ Å — geometrically close
  ring/branch atoms that aren't actually bonded. All three independent
  call sites (CONECT inference, `add_heterogen_h_via_rdkit`,
  `_process_single_residue`'s OpenBabel harvest) must reject a
  same-residue sugar bond beyond ~1.7 Å — fixing only one of the three
  is not sufficient, they run at different pipeline stages.
- **Heterogen heavy atoms (ligands, glycan trees) get the SAME
  `weak_k` restraint tier as new protein backbone atoms during
  minimize — not zero.** The old "BioLuminate-style: protein is
  fixed-ish, ligands relax" policy (zero restraint) is fine for a
  small, torsion-poor ligand but let a multi-residue glycan tree drift
  a mean of 4+ Å (up to 10+ Å) off its covalent anchor into an
  unrelated, clashing part of the protein surface — confirmed contrary
  to established MD/structure-prep practice (CHARMM-GUI equilibration
  protocols restrain protein AND glycan together). Only hydrogens stay
  fully free.
- **`minimize` auto-attempts GAFF2 parametrization
  (`lig_params.build_ligand_generator`, non-strict) whenever an
  unknown heterogen is present, not only under `--parametrize-ligands`.**
  Without a template, whole-system `createSystem` fails and falls back
  to legacy strip-and-splice, which has no tracking mechanism for a
  non-covalent ligand (`_rigid_track_glycan_trees` only follows a
  covalent anchor bond) — the ligand gets spliced back at its
  ORIGINAL pre-minimize coordinates into a pocket the protein has
  since moved into. Explicit `--parametrize-ligands` stays `strict=True`
  (raises on failure — the user asked for it); the auto path is
  `strict=False` so environments without AmberTools/openff degrade to
  today's behaviour unchanged. Two related traps found making this
  actually work: `Modeller.addHydrogens()`'s OWN internal
  `createSystem` call can raise `KeyError` (not `ValueError`) when its
  temporary re-matching invokes the GAFF2 generator — catch it
  alongside `ValueError` in the "fall back to protein-only H
  placement" handler. And minimize's strip-and-readd-H path (for AMBER
  protonation variants) must scope its H-strip to `PROTEIN_RESIDUES`
  only — stripping H from an arbitrary ligand is unrecoverable since
  `addHydrogens` has no hydrogens.xml entry to rebuild it from.
- **Never compare a `str` temp-file path against a `Path` object with
  `!=`/`==` to decide whether to delete it (fixed 0.7.14).**
  `Path('/a') != '/a'` is `True` in Python even when they name the
  exact same file — `Path.__eq__` requires matching types. Several
  helpers (`ffutils.sanitize_protein_hetatm`,
  `prepare.pipeline._canonicalize_conect_records`) return plain `str`
  even when handed a `Path` and no rewrite happened. Confirmed this
  crashed `prepare`'s own "was this rewritten" check
  (`preprocess_was_rewritten = preprocessed_path != input_path`) so it
  was unconditionally `True`, and — when nothing had actually been
  rewritten — `run_pdbfixer`'s cleanup then deleted `canon_path`, which
  in that case IS `input_path`: **`dvbfixer prepare <file>
  --no-infer-conect` on an already-clean input permanently deleted the
  user's own input file.** Normalize to one type (str) immediately on
  entry to any function that will later compare a path against
  possibly-rewritten copies of itself; never trust a bare `!=` between
  a function parameter and a helper's return value unless both sides
  are guaranteed the same type.
- **Never collapse a `(chain, resid, icode)` key down to `(chain,
  resid)` anywhere protonation-variant names or CONECT atom identity
  are tracked (fixed 0.7.14).** This exact bug recurred independently
  in at least 5 places: `prepare/pipeline.py`'s `variant_overrides`
  merge and `_restore_variants`'s PDB-line matching, `ffutils.variants`'
  `build_variants_list`/`rename_variants_to_parent_in_topology`/
  `restore_variants_post_addhydrogens`/`fix_lyn_hz_naming`,
  `minimize/pipeline.py`'s parallel `amber_renames` system, and
  `transplant.py`'s CONECT serial map. Any two residues sharing a
  resSeq via insertion code (e.g. a Kabat CDR-loop `H:82`/`H:82A` pair
  — this project's primary use case is antibody PDBs) silently
  overwrite or cross-contaminate each other's data under a 2-tuple key.
  `ffutils.ff_names.apply_variants_to_pdb_text`/`_split_key` already
  had this right (icode-specific entry first, any-icode fallback only
  for a residue that itself has none) — mirror that pattern, don't
  reinvent a 2-tuple version.
- **`minimize`'s restraint-tier atom-index set must be re-resolved by
  `(chain, resid, icode, atom_name)` identity against the FINAL
  topology, never carried as raw integer indices across an
  `addHydrogens`/`addMissingAtoms` call (fixed 0.7.14).** Both rebuild
  an entirely new `Topology`, shifting every atom's index whenever one
  is inserted. `resolve_new_atom_indices` (already used by the `.dat`-
  driven path) is the correct, existing helper — call it again right
  before `build_restraint_force`, not just once at the top of
  `minimize()`.
- **`model/renumber.py`'s `build_resnum_mapping` must check a HETATM's
  preserved original resSeq against the (possibly gap-filled) protein
  resSeq range before placing it, and renumber it clear of a collision
  (fixed 0.7.15).** The standalone, FASTA-blind `renumber.py` numbers
  ATOM and HETATM residues in one shared sequential space with no
  isolation between them (its no-SEQRES branch matches both record
  types by file-encounter order). If `model`'s FASTA-aware gap-fill
  later expands a chain, a HETATM ligand's naive resSeq can land
  exactly on a newly-created protein residue's resSeq — confirmed on a
  real fatty-acid ligand (`tests/fixtures/lipid/`) whose resSeq collided with a
  gap-filled `VAL`. `minimize`'s legacy strip-and-splice position-
  restore merge (keyed by `(chain, resid, atomname)`, no resname check)
  then silently overwrote the ligand's colliding atoms with the
  protein residue's minimized coordinates — an atom teleported tens of
  Angstroms away, i.e. "strange bonds" in any viewer. The restore-merge
  key is now `(chain, resid, parent_resname, atomname)` as
  defense-in-depth, but the root-cause fix belongs in
  `build_resnum_mapping`, not there.
- **`top/pipeline.py`'s chain classifier must WARN, never silently
  drop, a chain it can't build a topology for (fixed 0.7.15).** A
  chain whose residues aren't protein, a single known small molecule,
  a sugar, or a ceramide used to vanish from the output `.top`'s
  `[ molecules ]` section with zero diagnostic — confirmed on a plain
  fatty-acid ligand with no `top/ff_data.PDB_TO_LIPID` entry. This does
  not add topology support for arbitrary small molecules (that's
  `--acpype` / `minimize --parametrize-ligands`'s job) — it only makes
  the existing "can't handle this" outcome loud instead of silent.
- **`top/pipeline.py` is split into `top/types.py` (shared dataclasses:
  `PDBResidue`, `PDBChain`, `AtomEntry`, `ChainTopology`), `top/glycan.py`
  (`detect_glycan_links`, `build_glycan_trees`, `_is_ceramide`,
  `_parse_conect_bonds`), and `top/topology_builder.py`
  (`TopologyBuilder`, `_match_atom_names`, `_resolve_sugar_rtp`) as of
  0.7.15.** `pipeline.py` itself is now CLI orchestration (`main`) plus
  PDB reading/writing only — it imports the three modules above rather
  than defining any of that code inline. A prior session incorrectly
  believed `TopologyBuilder` was nested inside `build_glycan_trees`
  ("~1278-line function containing a nested class") and deferred this
  split as too risky; a precise line-boundary re-read found
  `TopologyBuilder` was always a separate, self-contained top-level
  class. If you add a new glycan-detection helper or a new
  `TopologyBuilder` method, put it in the matching new module, not back
  in `pipeline.py`.

## Running tests locally

```bash
pytest -m 'not slow' -q   # fast lane
pytest                   # complete suite, including external-tool integrations
ruff check src/dvbfixer   # style
mypy src/dvbfixer/cli.py src/dvbfixer/ffutils src/dvbfixer/pdbutils src/dvbfixer/align.py
python scripts/check_agent_docs.py  # agent task/contract/invariant maps
```

The full suite needs the scientific stack and external executables from
`environment.yml`. Structural inputs and companion FASTAs are tracked under
`tests/fixtures/`; update `MANIFEST.sha256` whenever an input asset changes.

## Session preferences

- **Always pass `--no-solvent`** on every dev iteration of `minimize` /
  `zbs`. Solvent-box minimize is orders of magnitude slower and eats the
  feedback loop. Add solvent back only for real evaluation runs the user
  has explicitly asked for.
- Reply in English by default. You may reply in Russian when the user explicitly permits or requests it.

## Current agent notes and recently established invariants

- **Workspace autosaves track pending fields per workspace.** On a revision
  conflict, rebase only pending fields and tool-panel entries onto the latest
  manifest before retrying. Preserve newly registered artifacts and unrelated
  panel state. Reload must preserve edits arriving during its GET and ignore
  responses for a superseded workspace or revision.
- **The V1 naming API resolves inputs by workspace artifact ID.**
  `gui/server/naming-api.ts` must invoke `dvbfixer atom-names`, validate its
  bounded report and output digest, re-read the latest manifest immediately
  before publication, and register exactly one output with provenance. Dry runs
  and all failures register nothing; Node must not duplicate naming science.
- **Standalone API hosting is loopback-first.** `gui/server/api-routes.ts` is
  the shared route composition; Vite and `standalone.ts` are adapters. Keep
  static and workspace roots disjoint, return JSON for unknown API paths, and
  preserve shutdown ordering: stop intake, terminate tracked child processes,
  then drain HTTP. `auth.ts` owns static bearer authentication;
  workspace manifests own case-sensitive principal ownership and ACLs. Keep
  credentials out of URLs, logs, manifests, and localStorage. Remote binding
  still lacks built-in TLS and target-host resource-enforcement acceptance.
  Restrictive CORS, application quotas, durable audit retention, and same-host
  multi-process job coordination are implemented; multi-host scheduling is not.
- **Diagnostic summaries require findings.** Clean runs emit no empty warning
  banner. Preserve fd-level capture and summaries for actual warnings/errors,
  including during exception cleanup.

- **Release metadata is synchronized, not single-file.** `pyproject.toml` is
  authoritative, but a version bump must also update
  `src/dvbfixer/__init__.py`, `gui/package.json`, both root-package version
  entries in `gui/package-lock.json`, the current-release line in `README.md`,
  the installation example, version-sensitive tests, and the first release
  heading in `CHANGELOG.md`. Run `python scripts/check_versions.py`,
  `python scripts/gen_cli_reference.py --check`, and
  `python scripts/gen_gui_spec.py --check` before committing a release.
- **Tracked production structures belong under `tests/fixtures/`, never only
  under the historical untracked `test/` tree.** Copy only source inputs and
  companion FASTAs; exclude generated ZBS/prepared/minimized structures, JSON
  reports, and logs unless a test explicitly needs an expected-output golden
  file. Document provenance in `tests/fixtures/README.md` and regenerate
  `tests/fixtures/MANIFEST.sha256`. Current production regressions include
  `c_glh/`, `warnings/`, and `overlap/8dis_t_u.pdb`.
- **PDB and FASTA chain IDs are case-sensitive.** Chains `D` and `d` may both
  exist and must remain distinct through parsing, mapping, selection, capping,
  diagnostics, and output. Never normalize chain identifiers with `upper()`,
  `lower()`, or `casefold()`.
- **Diagnose checks internal chain breaks per explicit PDB chain.** A boundary
  such as `A/GLY86 -> B/MET1` is not a broken chain. Do not change the shared
  empirical `split_chains.find_chain_breaks` semantics to accomplish this;
  diagnose groups lines by chain before calling it.
- **Coordinate-identical protein chains are suspicious merged frames.** Use
  `pdbutils.duplicates.duplicate_protein_chain_coordinates`; diagnose and
  minimize warn when complete chains have matching residue/atom identity and
  coordinates to PDB precision. The real regression is 8DIS chains `d`/`D`
  with 3,695 overlapping protein atoms and no `MODEL`/`ENDMDL`. This is a loud
  warning, not a fatal error; legitimate same-sequence homodimers at different
  coordinates must not be flagged.
- **CONECT peptide C-N inference is restricted to file-order neighboring
  protein residues in the same chain.** Spatial proximity alone can fabricate
  an external C bond and make OpenMM report `1 C atom too many` for an otherwise
  valid ASN/THR. Sanitize inherited CONECT records with the same filter instead
  of permanently trusting an earlier bad inference.
- **Batch ZBS intermediates live beside the final output.** Under
  `--input-dir/--output-dir`, no renumber/model/prepare/minimize intermediate or
  `.dat` sidecar may be written into the source tree. Derive named artifacts
  from `final_output.parent`, while continuing to read the original input.
- **Missing `--cap-chain` selections warn and continue.** Preserve exact,
  case-sensitive matching, remove absent requested chains from the selection,
  and cap any requested chains that do exist. Do not turn a missing selection
  back into a fatal `ValueError`.
- **Diagnose JSON is user-facing Unicode.** Serialize with
  `ensure_ascii=False` so Å, em dashes, arrows, and non-Latin filenames remain
  readable rather than becoming `\\uXXXX` sequences.
- **Unified CLI diagnostics are fd-level.** `runtime.tee_output` must continue
  capturing Python and inherited child-process stdout/stderr, emphasize every
  line recognized as WARNING/ERROR, keep log files free of ANSI escapes, and
  emit the deduplicated diagnostic summary even when execution exits through
  an exception. Do not replace it with Python-only logging interception.
- **Homology toolbar geometry is centralized in `HomologyPanel.tsx`.** Target,
  Templates, Alignment, and Model controls use `homologyToolbarSx` and the
  shared 160x32 control/action dimensions. Compact 32 px MUI inputs require the
  custom label transforms and input padding in that shared style. Toolbars use
  an opaque `background.paper` without outline boxes. Avoid one-off sizes that
  reintroduce inconsistent alignment.
- **The Mol* viewport filename is a React overlay, not a Mol* state-tree
  label.** `MolstarViewer` reads the slot-specific `fileName` from the structure
  store, shows its basename without intercepting pointer events, and retains
  the full path as the title. Keep primary and secondary viewers independent.
- **GUI verification:** from `gui/`, run `npm run typecheck` and
  `npm test -- --run`. Backend-focused changes should run their narrow pytest
  set first, then `pytest -m 'not slow' -q` when the scientific environment and
  time budget allow.

- **Domain policies are partially integrated.** Reuse `domain.structure_identity`
  for chain allocation, `domain.parameterization` for ligand routing, and
  `domain.force_field_naming` plus the pure `force_field_naming` application
  service for residue/atom naming. Keep path mutation in the legacy adapter and
  future workspace/artifact concerns outside the scientific service. A
  geometry-regularization backend is proposed research, not a shipped feature;
  see [the research note](docs/research/whole-complex-relaxation.md).
- **Empirical Split preserves input atom serials.** Never reserialize atoms
  independently of CONECT endpoints. `--keep-heterogens` retains solvent inside
  its MODEL; unique molecule IDs exclude solvent and protein HETATMs. Keep the
  HELIX/SHEET remapping and endpoint-identity regression tests.
- **`/test/` is ignored local experimentation.** Keep reviewed source fixtures
  in `tests/fixtures/` with provenance and checksums, not duplicate tracked inputs.
