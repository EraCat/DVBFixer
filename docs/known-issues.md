# Known issues

[← README](../README.md)

- **The diffusion model backend is experimental and profile-specific.** It
  accepts only one canonical protein chain with one internal 3-12-residue gap
  and is unavailable through batch, GUI, `zbs`, and `homology`. It requires an
  operator-managed external environment and checkpoint and never falls back to
  MODELLER or another device. The Apple MPS smoke passed, but its evidence is
  descriptive and training membership remains unresolved. The Linux/CUDA
  production wrapper passed a checkpoint-backed public-CLI case on the pinned
  A100 host, but its frozen 231-case replay remains pending.
  Each candidate bundle includes a bounded, digest-verified sampler trace.
  `doctor` now reports static profile status and can perform a selected-profile,
  no-inference runner handshake; a passing handshake does not replace the
  outstanding hardware acceptance. Operator-supplied runner commands are
  trusted code: core containment checks validate returned artifacts but do not
  prevent the process from writing outside its workspace. Maintained wrappers
  are required to keep writes inside that workspace; use an external sandbox
  or container when this must be enforced. See
  [the model command](commands/model.md#experimental-diffusion-scope).
  Bundle publication also requires filesystem support for atomic no-replace
  directory rename (`renameat2(RENAME_NOREPLACE)` on Linux). Some bind-mounted
  or shared filesystems reject it; place both `--diffusion-work-parent` and the
  output bundle on a native local filesystem rather than weakening publication
  atomicity.

- **OpenMM CUDA must not use a toolkit newer than the host driver supports.**
  The A100 research host uses NVIDIA driver `535.104.05` (CUDA 12.2
  compatibility), while the main environment resolved CUDA/NVRTC 12.9 alongside
  OpenMM 8.6.1. OpenMM's runtime JIT then failed with
  `CUDA_ERROR_UNSUPPORTED_PTX_VERSION (222)`. Keep the main environment unchanged
  and use the isolated, pinned
  [`deploy/openmm-cuda122/environment.yml`](../deploy/openmm-cuda122/environment.yml)
  for CUDA boundary-refinement experiments, then install the digest-verified
  OpenMM 8.3 ff19SB data with `deploy/openmm-cuda122/install-forcefields.sh`.
  Repeated short-target and long-target CUDA refinement gates pass; details are in
  [`docs/research/openmm-cuda-refinement.md`](research/openmm-cuda-refinement.md).

- **Linux NumPy import can fail with MKL 2026.2:** a fresh conda solve selected
  MKL BLAS/LAPACK wrappers requiring the absent `libmkl_gf_lp64.so.3`. The process
  aborts before normal Python exception handling, so CI can fail at CLI reference
  generation without any actual documentation drift. The main `environment.yml`
  now selects consistent OpenBLAS wrappers and CI exercises native NumPy/SciPy
  solves before the reference/test steps. See the
  [BLAS repair instructions](installation.md#numpyscipy-blas-backend). Isolated
  runner/RESP environments retain their own independently pinned dependencies.

- **Mypy must use NumPy `<2.5` while targeting Python 3.11.** NumPy 2.5
  dropped Python 3.11 and its bundled stubs use Python 3.12-only `type`
  statements. Running dvbfixer's Python 3.11-targeted mypy configuration from
  a Python 3.12 environment with NumPy 2.5 therefore fails while parsing
  `numpy/__init__.pyi`, before project files are checked. Project metadata,
  `environment.yml`, and CI consistently constrain NumPy to `<2.5`. Repair an
  existing environment with `python -m pip install --upgrade "numpy<2.5"`;
  do not change mypy's `python_version = "3.11"` or hide NumPy's types.

- **PROPKA 3.5.1 is incompatible with Python 3.14** — `dvbfixer
  protonate` (and the PROPKA step inside `prepare` / `zbs`) crashes with
  `AttributeError: 'Parameters' object has no attribute '__annotations__'`
  at `propka.parameters.parse_line`. propka reads the dataclass attribute
  `self.__annotations__` at the instance level, which Python 3.14's
  PEP 649/749 lazy-annotations change makes raise instead of falling
  through to the class dict. `environment.yml` therefore pins
  `python >=3.11,<3.14`; do not loosen it. On a working env the repro
  `python -c "from propka.parameters import Parameters; Parameters().__annotations__"`
  returns a dict (on <3.14) rather than raising (on 3.14).

- **micromamba env creation fails on macOS Docker host bind mounts
  (VirtioFS / gRPC-FUSE).** When `MAMBA_ROOT_PREFIX` (and thus the env
  + package cache) lives under a host bind mount such as `/home/agent`
  (the container's `fakeowner` mount of macOS `/Users`), the
  `Linking 'ncurses'` step aborts with
  `filesystem error: cannot copy symlink: Invalid argument` on the
  case-variant terminfo symlink pair
  `share/terminfo/32/2621A` ↔ `.././68/hp2621` vs `2621a`. The bind
  mount is case-insensitive and rejects libmamba's `copy_symlink` for
  these case-colliding entries (the colliding inode surfaces as a
  corrupt orphan with `nlink=0`, `readlink` → `EINVAL`). The
  `always_copy` / `--copy` / `MAMBA_ALWAYS_COPY` flags and the
  `always_copy: true` config do **not** fix it — copy mode still
  recreates in-package symlinks via `copy_symlink` rather than
  dereferencing them, and no micromamba/conda flag dereferences or
  skips broken in-package symlinks. The fix is to create the env (and
  package cache) on the container's **native overlay filesystem**:
  ```bash
  sudo mkdir -p /opt/mamba && sudo chown -R agent:agent /opt/mamba
  export MAMBA_ROOT_PREFIX=/opt/mamba          # env + pkgs now on overlay
  micromamba create -f environment.yml -n dvbfixer -y
  micromamba run -n dvbfixer pip install -e ".[dev]"
  ```
  Persist `MAMBA_ROOT_PREFIX=/opt/mamba` (and put
  `/opt/mamba/envs/dvbfixer/bin` on `PATH`) in your shell rc, otherwise
  `micromamba run -n dvbfixer` defaults back to the broken bind-mount
  root. The micromamba binary itself runs fine from anywhere; only the
  prefix/cache location matters.

- **CIF input still has PDB output limits.** CIF/mmCIF is normalized to an
  internal PDB because downstream tools depend on fixed-column PDB records.
  DVBfixer maps at most 62 chains and rejects atom serials, residue identifiers,
  names, models, or coordinates that cannot be represented safely. It never
  truncates them silently. See [CIF structure input](cif-input.md).

- **CONECT records limited to atom serials ≤ 99999** (PDB v3.30 spec). Every dvbfixer CONECT writer uses fixed-width 5-char serial fields (`f"{serial:5d}"`), which is spec-compliant but silently produces malformed CONECT lines for systems with > 99999 atoms — adjacent 6-digit serial fields run together without a separator. Workarounds: (a) split the system, (b) renumber atoms to fit under 99999 (drop water/heterogens before topology export), (c) retain the original mmCIF in an external tool if you need full-system connectivity in a large complex. Hybrid-36 encoding (BIOVIA/Phenix extension) is on the roadmap for a future release once a real user surfaces the need.

- **Default prep backend flipped back to `legacy` in 0.7.5** —
  `prepare` and `protonate` default to `--backend legacy`
  (Modeller+PDBFixer). Motivation: the tleap-reduce backend
  introduced in 0.7.0 solved the D-Cα problem but broke coverage
  for glycans, ligands, PTMs, and any covalent HETATM link
  (tleap has no template for those). The chirality invariant is
  now enforced downstream in minimize via the unconditional
  force-reflect fallback (0.7.4), so legacy prep's PDBFixer.addMissingAtoms
  D-Cα risk is neutralised there. `tleap-reduce` remains
  fully functional as opt-in via `--backend tleap-reduce` for
  pure-protein inputs where deterministic L-only tleap output is
  wanted.

- **PROPKA on tleap+reduce backend (fixed 0.7.4)**: The initial
  `prep_backend` shipped an ad-hoc PROPKA→variant map keyed on
  `(chain, resnum)`. PROPKA emits multiple `Group` records per residue
  (side-chain acid/base + terminal `N+` / `C-` on the same
  `(chain, resnum)`) so the second one silently overwrote the first —
  ASH/GLH/LYN were only assigned by accident when the collision
  landed the right way, and HIS→HIP was never assigned because HIP
  was inferred solely from H atoms and `reduce -build` almost never
  places both HD1 and HE2. Fixed by routing through the existing
  `dvbfixer.protonate.decide_protonation` (group-type-filtered,
  `(chain, resnum, icode)`-keyed) then overlaying Reduce's HID/HIE
  tautomer for neutral HIS. `_patch_variant_hydrogens` gained an HIP
  branch that adds whichever imidazole H Reduce didn't place.

- **AMBER variant residue names on the minimize path (fixed 0.7.4)**:
  OpenMM's `PDBFile._standardResidues` set covers only the 20 canonical
  amino acids — it does NOT know LYN/ASH/GLH/CYX/CYM/HID/HIE/HIP.
  Loading a PDB with variant names via `PDBFile` produces a topology
  with the correct atoms but **zero intra-residue bonds** for the
  variant residues; every downstream `createSystem` template match
  then fails with "residue X has no bonds between its atoms". Fixed
  in `minimize/pipeline.py`:
  1. Before `PDBFile.load`, `text_rename_variants_to_parent` folds
     variant names to their standard parents in a temp file — OpenMM
     infers proper intra-residue bonds from parent templates.
  2. When any variant is present in the input (via `amber_renames`),
     force the strip-H + `Modeller.addHydrogens(variants=[...])`
     rebuild path. Reason: `addHydrogens` copies input bonds but does
     NOT rebuild missing ones from templates, and it only ADDS
     missing H — never REMOVES extras. Strip-and-readd sidesteps
     both limitations.
  3. Cap the pH passed to `addHydrogens` at 9.99 so OpenMM's
     `hydrogens.xml` `maxph="10.0"` HZ3 gate doesn't break terminal
     LYS residues at high pH (variants already carry PROPKA's
     protonation decisions).
  4. `pdbutils/inference.py::_apply_filter` now keeps intra-residue
     bonds for variant-named residues in emitted CONECT (defense in
     depth for any path that still loads variants directly).

- **SS bonds dropped by `_drop_spurious_inter_aa_bonds` (fixed 0.7.4)**:
  Minimize's spurious-bond filter treated every inter-residue bond
  between two protein residues that wasn't a C-N peptide bond as
  spurious. After `text_rename_variants_to_parent` folded CYX → CYS,
  SG-SG disulfides were between two "CYS"-named residues → dropped.
  Fixed by adding an SG-SG exception for the CYS family (CYS/CYX/CYM).

- **D-Cα inversion and reflected hydrogen geometry (prevention added
  0.7.23)**: minimize now installs a one-sided Cartesian signed-volume guard
  on every N–CA–C–CB centre. It prevents inversion without a singular improper
  torsion and leaves normal L geometry unforced. Reflection is emergency-only,
  followed by guarded local minimization; unresolved D geometry aborts output.
  Emergency repairs are persisted as `REMARK 999 DVBFIXER
  CHIRALITY_REPAIR`; diagnose names those residues and recommends inspection
  of hydrogen angles and local geometry.

- **Historical D-Cα repair behavior (fixed 0.7.4, superseded in 0.7.23)**: The prior
  design was WARN-only when a residue drifted into D-Cα geometry
  during phase-2 minimize (rationale: reflecting an equilibrated
  sidechain can stretch CA-CB to ~2 Å). Replaced with a two-tier
  fix that guarantees zero D-Cα in output:
  1. **Reflect + re-minimize loop** (max 3 iterations): reflect via
     `fix_ca_chirality`, run a short follow-up minimize under the
     already-weakened phase-2 restraints so the reflected sidechain
     relaxes into a compatible position.
  2. **Unconditional force-reflect fallback** — if a residue still
     prefers D after the loop (the FF's local minimum genuinely
     sits on the D side; happens rarely for residues in tight
     packing), reflect once more and skip the follow-up minimize.
     `fix_ca_chirality` mirrors the whole sidechain through the
     CA-N-C plane, so ALL internal bond lengths and angles are
     preserved (CA-CB ≈ 0.154 nm, CB-HB ≈ 0.109 nm, sidechain
     torsions unchanged); only CB's position RELATIVE to backbone
     neighbours changes, which may introduce a small local packing
     strain the user can further relax if desired. A WARNING lists
     each forced residue with its residual triple product.
  3. **Post-reflect local relax (added 0.7.9)** — the rigid mirror
     in step 2 can swing a sidechain hydrogen into a neighbouring
     residue's atom (both unrestrained H's — this is what
     "local packing strain" meant in practice, occasionally bad
     enough to be a genuine < 0.5 Å clash rather than just strain).
     Confirmed as the root cause of a flaky `2VLQ_original.pdb`
     regression failure that only reproduced in the full test-suite
     run, never in isolation, because Modeller's stochastic loop/MD
     refinement makes whether *any* residue needs forced reflection
     nondeterministic between runs. Fix: before any follow-up
     minimize, re-anchor the reflected residue's restraint targets
     (`restraint.setParticleParameters`) to their NEW post-reflection
     position instead of leaving them pointed at the old
     D-favouring one — backbone atoms are untouched by
     `fix_ca_chirality` so their anchor update is a no-op, only the
     reflected sidechain's anchor actually moves. A bounded local
     `minimizeEnergy` then lets the genuinely unrestrained
     neighbouring hydrogens relax out of the way, with no energetic
     or restraint-driven path back to D. A `find_d_residues` sanity
     check still runs afterward; if a residue ever reverts anyway,
     it's reflected again unconditionally with no further minimize
     (same non-negotiable "zero D-Cα in output" guarantee as before).

- **N-terminal ASH/GLH in ACPYPE mode**: AMBER14 has no N/C-terminal protonated ASP/GLU templates (NASH/NGLH — never parameterized via RESP in any AMBER version). When `--acpype` encounters ASH or GLH at chain termini, it strips the protonation hydrogen (HD2/HE2) and uses the standard deprotonated template (NASP/NGLU). A `UserWarning` is emitted. Internal (non-terminal) ASH/GLH residues are preserved correctly.

- **Chain ID mismatch in .dat workflow**: The `.dat` file stores chain IDs from PDBFixer. If the prepared PDB is saved through a tool that reassigns chain IDs (PyMOL, VMD), the `.dat` entries won't match the new chain letters. Workaround: ensure chain IDs remain consistent between prepare and minimize steps, or manually edit the `.dat` file.

- **Hydrogen handling in minimize**: By default, existing hydrogens are kept. Use `--rebuild-h` to strip and re-add via OpenMM (needed when protonation state changes). When AMBER protonation names (GLH, HIE, CYX, etc.) are detected in the input PDB, they are passed as `variants` to `addHydrogens` to ensure correct protonation hydrogens.

- **OpenMM normalizes AMBER names**: `PDBFile` may fold variants such as
  GLH/HIE/CYX into parent residue names. Minimize captures raw variant identity
  before loading, then the shared naming adapter restores requested output names
  after serialization. A separate `protonate` run is not needed merely to restore
  names. Use the relevant command's `--atom-naming` policy, or the non-destructive
  [`atom-names`](commands/atom-names.md) converter for an existing PDB.

- **Pull valence checking**: The `pull` tool validates bonds before and after pulling. Pre-pull: checks valence (bond count vs element max), warns about unusual element pairs. Post-pull: checks convergence (distance vs target), bond length range, and steric clashes within the pulling residues. All checks are warnings only — they do not prevent the operation.

- **Glycoprotein minimization in `minimize`**: Default minimizes the WHOLE system (protein + glycans + ligands) with the resolved `--ff` (AMBER14 + GLYCAM_06j-1 for GLYCAM-named glycoproteins, CHARMM36 for CHARMM inputs). Heterogen heavy atoms get the same weak restraint tier as newly-modeled backbone atoms (0.7.10 — previously free, which let a multi-residue glycan tree drift off its covalent anchor; see the 0.7.10 entry below). Strip-and-splice mode (`--strip-heterogens`) is an opt-in protein-only flow with HETATM coords spliced back from the input. When the full-system path can't parametrize the residue set (e.g. an unknown ligand with no template in either GLYCAM or CHARMM), the tool now auto-attempts GAFF2 parametrization (0.7.10, non-strict — same mechanism as `--parametrize-ligands` but triggered automatically) before falling back to strip-and-splice; `_rigid_track_glycan_trees` does Kabsch tracking + canonical trans-amide C1/HD21 placement to preserve glycan geometry in that fallback path. Pass `--parametrize-ligands` explicitly to make a parametrization failure fatal instead of silently falling back.

- **Mixed 1-4 scaling (AMBER+GLYCAM)**: AMBER uses fudgeLJ=0.5/fudgeQQ=0.8333, GLYCAM uses 1.0/1.0. GROMACS only supports one global value. The `--acpype` flag on `top` and `--gromacs` on `transplant` solve this via ACPYPE's `[ pairs_nb ]` directive with per-pair LJ/Coulomb parameters.

- **AMBER14 has no terminal protonated ASP/GLU**: AMBER14 lacks NASH/NGLH/CASH/CGLH templates (no RESP charges were ever computed for terminal protonated ASP/GLU — a 15+ year gap). Affects both `dvbfixer top --acpype` and `dvbfixer top --ff amber --protonate`. When ASH/GLH is requested at a terminus, the protonation H is dropped, the residue is converted to standard ASP/GLU (using the existing NASP/CASP/NGLU/CGLU templates), and a `UserWarning` is emitted. HIS variants (HID/HIE/HIP) are unaffected — terminal templates exist (NHIE/CHIE etc.). CHARMM is unaffected — it uses TDB patches that combine cleanly with ASPP/GLUP.

- **Modeller terminal alignment**: `align2d` can misplace terminal gaps (e.g. matching last template residue to last target residue). This is auto-corrected by `_fix_terminal_alignment` which forces gaps to the actual N/C termini.

- **FASTA chain IDs required**: `dvbfixer model --fasta` matches sequences to PDB chains by chain ID embedded in the FASTA header. Accepted forms: `>chain_X`, `>PDBID_X` (e.g. `>1abc_A`), or bare `>X`. Sequences are NOT matched by file order. Headers without a parseable chain ID produce a clear error.

- **HIS tautomer selection**: PROPKA only predicts the overall pKa, not which nitrogen is protonated. The `--his-default` flag sets a global default (HIE or HID). For accurate per-residue tautomer assignment, use tools like MolProbity's Reduce or Schrodinger's ProtAssign.

- **PDBFixer sidechain rebuild can flip Cα chirality (fixed 0.6.2)**: `PDBFixer.addMissingAtoms()` rebuilds missing sidechain heavy atoms from ideal AMBER templates. When only the backbone (N, CA, C, O) is present in the input, the template alignment sometimes picks the D configuration — putting CB on the wrong side of the CA-N-C plane. Branched-Cβ residues (VAL, ILE, THR) are the highest-risk case. `dvbfixer.ffutils.geometry.fix_ca_chirality` runs immediately after `addMissingAtoms` in `prepare` and `minimize` and reflects any D-CB back to L via a plane-mirror. Zero-cost when the input is clean.

- **LYN hydrogen naming across three FF conventions (0.6.3)**: the force-field
  template, hydrogen-placement definition and consumer dialect must be distinguished.
  - **OpenMM ff14SB** (`protein.ff14SB.xml`): LYN uses `HZ2 + HZ3` (HZ1 absent). Needed for `createSystem` to match the LYN template.
  - **OpenMM `hydrogens.xml`**: gates HZ3 under `variant="LYS"` — a quirk that makes `Modeller.addHydrogens(variants=['LYN'])` produce `HZ1 + HZ2` instead. `dvbfixer.ffutils.variants.fix_lyn_hz_naming` renames `HZ1 → HZ3` post-`addHydrogens` to satisfy ff14SB during OpenMM operations.
  - **GROMACS amber99sb-ildn** (`aminoacids.rtp` + `.hdb`): LYN uses `HZ1 + HZ2`.
    Default GROMACS-profile final writes rename `HZ3 → HZ1`; native `standard`
    AMBER output retains `HZ2 + HZ3`. Intermediate OpenMM writes retain native
    ff14SB names. Choose the output profile for the intended consumer rather than
    assuming every final PDB uses the GROMACS dialect.
  Sub-agent survey (Jul 2026) verified LYN is the ONLY protein atom-name difference between ff14SB and GROMACS amber99sb-ildn for standard residues plus HID/HIE/HIP/CYX/CYM/ASH/GLH/LYN.

- **Water + ion mismatch causes LINCS failure**: Prior to the `--ion-set` flag, `dvbfixer top --water` only changed the water moleculetype while keeping bundled Aqvist Na⁺/Dang Cl⁻ ions regardless of water choice. Combining OPC water with Dang Cl⁻ caused Cl⁻ to over-attract to protein cations; in a real user case a 4× trastuzumab + OPC system saw atomic pressure crash to −9000 bar in 10 ps of NPT and LINCS died at step 8027. Now `--ion-set auto` (default) picks the matched set: TIP3P→JC-TIP3P, SPC/E→JC-SPCE, TIP4P-Ew→JC-TIP4P-Ew, OPC→Li-Merz HFE-OPC. Pass `--ion-set dang-legacy` only when reproducing pre-flag runs.

- **CHARMM water restriction**: CHARMM ions (SOD/CLA/POT/CAL/MGA) are fitted to CHARMM-TIP3P. `dvbfixer top --ff charmm` only accepts `--water tip3p|spc|spce`; `--water opc|tip4p|tip4pew` is rejected at the CLI level. To use OPC water with this protein, switch to `--ff amber`. `--ion-set` is a no-op with `--ff charmm`.

- **`--acpype` mode is TIP3P-locked**: The `--acpype` pipeline (OpenMM → ParmEd → ACPYPE) hardcodes TIP3P water + AMBER14+GLYCAM ions and ignores `--water`/`--ion-set`. A future enhancement could add OPC support there; today, use the RTP-based `dvbfixer top --water opc` path if you need OPC.

- **Inputs without CONECT (RESOLVED)**: Previously `prepare`, `top`, `minimize`, `transplant`, and `convert` could silently mis-detect glycosylation sites, disulfide bonds, and glycan trees on PDBs that lacked CONECT records (downloaded RCSB files, GROMACS-saved frames, EM depositions, GLYCAM-Web output). Each tool now runs automatic CONECT inference (OpenBabel `ConnectTheDots` + domain overrides for SS / glycosidic / glycosylation) into a temp PDB copy before processing. See [`conect`](commands/conect.md). Pass `--no-infer-conect` to any affected tool to opt out (e.g. for debugging what the input actually declared).

- **Glycan trees drifting into unrelated protein pockets / spurious sugar bonds (fixed 0.7.10)**: pytest regressions only checked that glycosylation-site bonds EXIST, not that the resulting 3D geometry was sane — a real production `zbs` run on a glycoprotein could still show a glycan tree collapsed 4-10 Å off its covalent anchor into a clashing, unrelated part of the protein surface, or a sugar residue with chemically-impossible CONECT entries, even though every bond-existence check passed. Five independent, compounding causes, found via live debugging:
  1. **`renumber.py` fabricated bonds from a stale/dangling CONECT record already present in the deposited PDB itself** (referencing a serial with no matching ATOM/HETATM line at all — leftover cruft from whatever tool produced the file). The old fallback (`serial_map.get(old_serial, old_serial)`) passed such an unmapped serial through UNCHANGED, and since dvbfixer renumbers everything into a dense range, that stale small number could coincide with the NEW serial assigned to a real, unrelated atom, fabricating a bond. `update_conect` now drops the whole record instead.
  2. **`acpype_export.add_glycam_bonds` had been dead code since 0.7.8** — a broken `KNOWN_GLYCAN_SMILES` import was silently swallowed by an overly-broad `try/except` that also defeated the unrelated `nanometer` import, so sugar-sugar/protein-glycosylation bond population never actually ran in production.
  3. **No same-residue distance guard for sugar/GLYCAM residues** in CONECT inference or in `prepare`'s RDKit/OpenBabel heterogen-H bond-carrying loops — three independent code paths, all needed the same ~1.7 Å covalent cutoff.
  4. **Heterogen heavy atoms got zero positional restraint during minimize** ("ligands relax" — fine for a small ligand, but let a multi-residue glycan tree drift on its many free glycosidic torsions). Now restrained at the same weak tier as new backbone atoms, matching established glycoprotein MD/structure-prep practice.
  5. **An unknown ligand with no FF template silently triggered the ligand-losing legacy strip-and-splice fallback** even on a plain `zbs` run with no `--parametrize-ligands` flag. `minimize` now auto-attempts GAFF2 parametrization on any template miss (non-strict unless the flag is explicit).

  Net effect verified on real fixtures: a glycoprotein `zbs --no-solvent` run went from 68-86 non-bonded contacts < 1.5 Å to zero, reaching the real whole-system minimize with no fallback at all. A residual, real `openmmforcefields`/OpenMM limitation remains for non-covalent ligands: `Modeller.addHydrogens()`'s own internal `createSystem` call can raise `KeyError` (not `ValueError`) when its temporary re-matching invokes a dynamically-registered GAFF2 generator — caught alongside `ValueError`, but the affected ligand still ends up on the strip-and-splice path (with a much smaller residual clash than before, since the fallback no longer strips the ligand's already-correct hydrogens).

- **Seeded rebuild versus whole-system determinism:** the unseeded missing-
  sidechain rebuild was fixed in 0.7.12 by
  `ffutils.geometry.rebuild_missing_atoms_with_retry`, used by all rebuild call
  sites. The 11 truncated LYS regression in `tests/fixtures/8cz8/8cz8_t_u.pdb`
  reproduces identical rebuilds on the fixed Reference backend, with a separate
  default-platform test checking clash-free L chirality. That result does not imply
  bit-identical whole-system minimization: platform/thread-dependent floating-
  point effects can still change relaxed coordinates. Historical reports of
  minimization-induced inversion predate the signed-volume chirality guard
  introduced in 0.7.23. Current minimize protects initially-L centres, uses
  reflection only for emergency recovery, and aborts output if L geometry is
  not restored. Do not treat rerunning until a lucky L result appears as a
  workaround. See [chirality protection](commands/minimize.md) and the
  [architecture](../ARCHITECTURE.md).

- **HETATM ligand resSeq colliding with a gap-filled protein residue, causing coordinate cross-contamination (fixed 0.7.15)**: on an input with no SEQRES records, the standalone `renumber.py` numbers ATOM and HETATM residues in one shared sequential space, with no isolation between the two. If `model`'s FASTA-aware gap-fill later expands a chain (e.g. an unresolved C-terminal loop), a HETATM ligand's naive resSeq can land exactly on a newly-created protein residue's resSeq. `minimize`'s legacy strip-and-splice position-restore merge, keyed too loosely, then silently overwrote the ligand's colliding atoms with the protein residue's minimized coordinates — the tracked fatty-acid regression under `tests/fixtures/lipid/` showed an atom teleported tens of Å away. Fixed in `model/renumber.py`'s `build_resnum_mapping` (detects the collision and renumbers the HETATM clear of it, with a `WARNING`); hardened minimize's restore key to `(chain, resid, insertion code, parent resname, atom name)` as defense-in-depth against future collisions.

- **`top` silently dropped any HETATM chain it couldn't classify as protein/sugar/ceramide/known-small-molecule (fixed 0.7.15)**: no `WARNING`, no error — the chain simply never appeared in the output `.top`'s `[ molecules ]` section. Confirmed on the same fatty-acid ligand above (`top/ff_data.PDB_TO_LIPID` only maps CHARMM-GUI ceramide codes, not plain fatty acids). Now emits a `WARNING` naming the dropped chain and its resname(s). This does not add topology support for arbitrary small molecules — use `--acpype` or `minimize --parametrize-ligands` (GAFF2) for that.

## See also

- [Command index](commands/index.md)
- [Pipelines](pipelines.md)
- [BEST_PRACTICES.md](../BEST_PRACTICES.md) — additional gotchas and recipes
