# Changelog

All notable changes to dvbfixer are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Backfilled from git history — commits before v0.3.0 are grouped by
feature area rather than by strict release. Older entries are
best-effort summaries; consult `git log` for exact provenance.

## [0.9.0] — 2026-10-20

### Added

- Added an explicit experimental `model --backend diffusion` CLI for a narrow
  canonical-protein internal-gap scope, backed by a versioned isolated runner,
  independent validation, bounded digest-linked sampler traces, provenance, and
  atomic directory-bundle publication.
- Added pinned Protenix, Boltz, RFdiffusion, and Protpardelle research adapters,
  benchmark tooling, fixtures, and frozen evidence records without adding ML
  frameworks or checkpoints to the core environment.
- Added preliminary Apple Silicon/MPS portability support for the pinned
  Protpardelle research adapter, including fail-closed device assertions,
  disabled CPU fallback, synchronized timing, memory telemetry, and exact final
  fixed-coordinate restoration.
- Added experimental diffusion workflows across sequential model batch/resume,
  ZBS, mosaic-first Homology and the GUI, with verified bundle custody and
  provenance-preserving PDB/`.dat` handoff.
- Added corrected cc89 CUDA and versioned Apple MPS local-context profiles with
  physical source positions, neutral chain phase, isolated refinement runtimes,
  multi-seed publication and frozen-request replay. Historical MPS behavior
  remains a separate profile rather than being silently replaced.
- Added authoritative offline `reconstruct-component` and `component-info`
  commands for the admitted isolated-component scope. Linked, metal and redox
  chemistry and MD parameterization retain separate acceptance requirements.
- Added reference-distance benchmark metrics, protein-context conditioning and
  frozen expanded-cohort research records without widening public admission
  merely because a research adapter supports a larger scope.

### Changed

- Kept diffusion-only Ramachandran and pooled chi1/chi2 hard gates inside the
  experimental diffusion package so generic `diagnose` retains its current
  report-only contract and dependency boundary.
- Added separate protocol runners for the Apple MPS Protpardelle profile and the
  Linux/CUDA Protenix profile, plus a bounded no-inference `doctor` handshake
  that is also enforced before public diffusion inference. The Apple public CLI
  smoke and frozen 231-case production-wrapper cohort completed. Public Linux
  checkpoint-backed workflow smokes also passed; the complete selected Protenix
  production-wrapper replay and final OCI image build/GPU smoke remain pending.
- Raised the runner contract to schema 4 with mandatory per-candidate sampler
  traces, exact generated/fixed sampler-axis identity checks, profile evidence
  labels in publication provenance, and frozen source-tree verification.
- Replaced per-run diffusion profile, runner, checkpoint, and digest arguments
  with one-time private backend registration, hardware-aware discovery, and an
  optional model-level selector.
- Allowed explicit `model --backend diffusion --strip-heterogens` preprocessing;
  the private normalized input drops HETATM records and associated
  ANISOU/LINK/CONECT metadata while leaving the source untouched.
- Extended the Apple Protpardelle path to reconstruct gaps on multiple protein
  chains through explicitly reported independent chain-level sampler invocations,
  merge them into one structure, and locally refine generated regions while
  retaining fixed atoms exactly. Added `--no-terminal` support to crop missing
  tails, a 900-second multi-chain default timeout, and an 8 MB bounded trace
  limit. Each invocation can now include deterministic fixed partner-chain crops
  within 12 Å of a gap anchor as real multi-chain denoiser context. Exact context
  atom identities are recorded in the sampler trace; gap-bearing chains remain
  independently sampled rather than jointly generated.
- Validation failures now publish an atomic `validation_failed` inspection bundle
  with failed gates and warnings instead of discarding a successfully materialized
  candidate; runner, protocol, digest, and containment failures still publish
  nothing.
- Localized OpenMM boundary-refinement failures now retain the unchanged raw
  sampler candidate and publish it as an explicitly rejected inspection bundle;
  the candidate carries a machine-readable postprocessing failure gate.
- Added one-anchor N- and C-terminal diffusion generation for the Protpardelle
  profile, including explicit gap kinds, deterministic PDB numbering, terminal
  materialization, single-junction validation, localized refinement, provenance,
  and fail-closed rejection on profiles without accepted terminal evidence.
- Added an opt-in Protpardelle fixed-heterogen geometric-conditioning slice for
  complete isolated ligands with authoritative SMILES and explicit CONECT graphs.
  The pinned sampler now consumes transformed HETATM coordinates through
  generated-atom repulsion guidance; request/trace/provenance retain exact atom
  mappings and graph digests, while unsupported chemistry remains fail closed.
- Added experimental mosaic-first Homology diffusion in both CLI and GUI.
  Template-plan materialization now exports explicit coverage/ownership metadata;
  Protpardelle keeps covered matching template atoms exact, generates admitted
  uncovered regions, and publishes the standard validated bundle without a
  MODELLER fallback. Covered substitutions remain fail closed.
- Synchronized plan status to separate delivered software, bounded hardware
  evidence and remaining scientific/production gates; retained historical
  protocols and experiment hashes unchanged.

### Fixed

- Kept Doctor and diffusion contract imports usable without OpenMM by deferring
  scientific execution re-exports; retained the public execution API and added
  fresh-process import-boundary regression coverage.
- Updated Vite/Vitest and vulnerable transitive GUI dependencies; the locked
  dependency tree passes `npm audit` without lowering the CI audit threshold.
- Made Homology diffusion dispatch tests independent of installed ML launchers,
  covering explicit Protenix and legacy Protpardelle profile selection.
- Deferred optional Torch/reinjection imports in Protenix research helpers so
  pure helpers can run in the core environment; made simulated Linux preflight
  tests independent of the actual host's cgroup RAM limits.
- Corrected fixture-manifest completeness checks for explicitly tracked Apple
  provenance metadata and rejected duplicate manifest entries.
- Hardened naming-output symlink cleanup, including dangling links, dry runs,
  child failures and malformed reports, without touching link targets or
  registering failed outputs.
- Disabled the development API plugin during Vitest collection so tests do not
  migrate or lock live workspace manifests; development hosting is unchanged.
- Corrected Amber19SB external preprocessing fixtures to use a periodic box
  compatible with Verlet cutoffs while retaining `grompp -maxwarn 0`.

### Compatibility

- MODELLER remains the default and production-supported backend of
  `dvbfixer model`. Diffusion remains explicit and experimental, including its
  GUI, batch, Homology and ZBS integrations, and introduces no automatic
  scientific fallback or checkpoint download. Corrected cc89 CUDA/MPS public
  profiles remain protein-only with their bounded internal-gap admission;
  legacy terminal/heterogen capabilities do not transfer to corrected profiles.

### Verification

- Initial hardware-independent integration passed Python 3.11 non-slow tests
  (907 passed, 9 skipped), GUI tests (235 passed), mypy, Ruff and generated/map
  checks. Final baseline repairs passed Python non-slow tests (1212 passed,
  2 optional-dependency skips), GUI tests (251 passed), TypeScript typecheck,
  ESLint, Ruff, generated-reference/schema, version and agent-map checks.
- Corrected Apple research acceptance passed 8/8 and public model/Homology
  integration passed 5/5; corrected CUDA public integration passed 5/5 across
  four workflows. These are bounded results, not general scientific acceptance.
- All six Amber19SB water/ion pair selections passed actual GROMACS 2026.0
  preprocessing. This does not claim solvated trajectories or mixed-chemistry
  acceptance. See [baseline-repair evidence](docs/research/baseline-repair-2026-10-20.md)
  and the [remaining-work index](docs/plans/README.md).

## [0.8.9] — 2026-09-30

### Added

- Added opt-in, protein-only `top --ff amber19sb` support using the verified
  GROMACS v2026.3 distribution, descriptor-driven chemistry admission, CMAP,
  and exact upstream water/ion pairs. Unsupported mixed chemistry fails before
  topology artifacts are written.
- Added reusable diagnose geometry measurements, structured numeric finding
  details, topology-backed backbone-angle checks, deterministic steric evidence,
  and exact residue/boundary scopes.
- Added typed, fail-closed nonprotein reconstruction contracts for pinned local
  CCD extracts and user-mapped Class A chemistry, with atomic geometry/provenance
  publication and a separate non-MD-ready parameterization decision.
- Added end-to-end batch ZBS regressions proving intermediates and `.dat`
  sidecars remain below the output root without modifying source directories.

### Changed

- Force-field selection, bundle inventory, optional metadata, writer features,
  and water/ion compatibility are represented by declarative topology
  capabilities while preserving the existing default `top --ff amber` route.
- `atom-names` and the V1 naming API now expose a distinct `amber19sb` dialect
  for ff19SB-specific cap, HYP, and terminal atom names without changing the
  legacy `amber` output.
- Expanded domain task, contract, invariant, and context documentation for
  diagnostics, nonprotein reconstruction, and topology force-field selection.

### Fixed

- Package smoke tests now require the bundled `amber19sb.ff` tree, generated CLI
  references match the Python 3.11 CI baseline, and the GUI lockfile no longer
  carries the high-severity `brace-expansion` advisory.

### Removed

- Removed the PostgreSQL-backed mutation library and Antibody Engineer GUI/API
  cluster, its development Compose service, and cluster-only dependencies.
  Historical workspace provenance fields remain readable but cannot start new
  retired workflows.

### Verification

- Python, GUI, generated-reference, packaging, and documentation checks cover
  the integrated release. External `gmx grompp` acceptance remains conditional
  on a compatible GROMACS executable and is skipped when `gmx` is unavailable.

## [0.8.6] — 2026-09-22

### Added

- Versioned workspace APIs for managed DVBFixer jobs, including durable
  same-host run state, cancellation, SSE status, and output provenance.
- Workspace-scoped naming conversion and a generated OpenAPI document/client.
- A single-host Ubuntu 24.04 systemd deployment profile with fail-closed
  resource preflight, audit logging, metrics, and privileged CI acceptance.

### Changed

- Refreshed the user guides for the current GUI, API, CLI defaults, and
  supported public-deployment boundary.

### Fixed

- The deployment preflight treats Linux `binfmt_misc` as a kernel filesystem
  rather than an unexpected writable data mount.

## [0.8.5] — 2026-09-09

### Fixed

- Fixed Split changing atom serials without updating CONECT records. Empirical
  splitting now preserves serials in every mode, preventing unrelated ligand
  bonds from propagating into Model. Regression checks compare bond endpoints
  through both Split and Model's bond-restoration routine.

- Workspace viewers display the first complete coordinate model instead of
  automatically filtering by deposited biological-assembly chain lists. Split
  updates HELIX/SHEET references after residue and chain renumbering.

- Added Split `--keep-heterogens` (GUI: Keep Heterogens) to retain all input
  heterogens, including solvent, ions and buffers, within each MODEL and
  preserve atom serials. Unique-chain assignment leaves retained solvent and
  protein residues encoded as HETATM intact.

### Documentation

- Documented implemented domain policies, whole-complex minimization limits,
  incomplete FAD inputs, and proposed relaxation benchmarks with sources.
- Removed duplicate numbering inputs from tracking; canonical fixtures remain
  under `tests/fixtures/`, and `/test/` is reserved for local experiments.

## [0.8.4] — 2026-09-09

### Fixed

- Workspace autosaves recover from revision conflicts caused by tool output
  registration. Recovery merges pending form edits into the latest workspace,
  preserving output artifacts and unrelated panel state. Reload preserves edits
  made while its request is pending and ignores superseded workspace responses.
- Clean CLI runs no longer print an empty diagnostic summary. Warnings and
  errors retain emphasis and their final summary, including in log files.
- GUI negative switches describe the option actually sent to the CLI;
  mutually exclusive switches clear their peers. The per-chain FASTA editor
  has a visible caret and updates coordinate-presence highlighting after edits.
- Modeller license setup uses the selected environment's Python, avoids
  printing the key, and restores the previous configuration if validation fails.

### Added

- Opt-in `split --unique-molecule-chains` and scientific domain documentation.
- Repeatable `--extra-ff FILE` for minimize and ZBS, early rejection of
  unsupported complex cofactors from generic GAFF, and PDB input validation
  for standalone small-molecule parametrization.
- Connectivity-based quaternary-ammonium charge correction for ligand export.

### Changed

- The full environment explicitly requests Reduce and Node.js >=22.

## [0.8.3] — 2026-08-14

### Added

- CLI, GUI, and batch structure inputs accept PDBx/mmCIF and crystallographic
  CIF. Inputs are converted through Gemmi or Open Babel to a validated internal
  PDB, with deterministic long-chain mapping and preserved assembly metadata.

### Changed

- GUI dependency locks use patched releases that clear the npm security audit,
  including Vite 6.4.3, without forced or major-version upgrades.
- GUI installation and CI no longer use the obsolete `--legacy-peer-deps`
  workaround, and CI rejects high/critical npm advisories.
- npm install-script policy explicitly permits the pinned esbuild verifier while
  denying optional native watcher builds and Scarf installation telemetry.

### Security

- Scarf analytics are disabled explicitly in addition to blocking its
  postinstall script, preventing third-party installation metadata reporting.

### Fixed

- NumPy is constrained below 2.5 so the Python 3.11 mypy baseline does not
  attempt to parse Python 3.12-only syntax from newer NumPy stubs.
- The GUI managed-job request includes the selected DVBfixer command, avoiding
  `unknown command: undefined` when starting a run.
- Generated GUI fields use the correct `PROPKA` and `ProtAssign` names, and the
  native Rollup repair verifies the binding itself rather than its directory.
- Homology toolbars and subtab headers no longer render a separate colored
  background behind their controls.

## [0.8.2] — 2026-08-14

### Changed

- Batch failures retain the command's concrete error and end with per-structure
  causes and actionable next steps instead of only numeric exit statuses.
- Cysteine protonation documentation and CLI help now distinguish the
  disulfide-sentinel cutoff from ordinary pH-driven `CYS` → `CYM` assignment.
- GUI dependencies use MUI Material and Icons 7.3.11, satisfying the supported
  peer range of MUI X Data Grid 8.28.6.

### Fixed

- Diagnose clash messages identify both atoms explicitly and JSON findings
  include structured chain/residue/atom details for the clash partner.
- Free cysteine thiolate `CYM` is translated to OpenMM's equivalent no-SH
  hydrogen state `CYX` during hydrogen placement, then restored to `CYM` for
  AMBER template selection and output, preventing `Illegal variant ... CYM`.

## [0.8.1] — 2026-08-12

### Added

- Diagnose and minimize warn when complete protein chains have identical atom
  identities and coordinates, indicating frames likely concatenated without
  `MODEL` / `ENDMDL` separators.
- Unified CLI output emphasizes warnings/errors and repeats unique diagnostics
  in an end-of-run summary block.
- Mol* viewports show the basename of the structure loaded independently into
  each viewer.

### Changed

- Homology Target, Templates, Alignment, and Model subtabs share compact,
  consistently aligned, opaque toolbars.
- Production inputs for the C-terminal GLH, addHydrogens warning, and
  overlapping-chain regressions are tracked under `tests/fixtures/`.

### Fixed

- Diagnose writes human-readable Unicode in JSON reports instead of escaped
  sequences such as `\\u2014` and `\\u00c5`.
- Batch ZBS intermediates are written below `--output-dir` rather than beside
  source structures in `--input-dir`.
- FASTA chain identifiers remain case-sensitive, allowing distinct chains such
  as `D` and `d` in the same structure.
- A missing `--cap-chain` selection warns and is skipped instead of aborting
  the preparation pipeline.
- CONECT inference accepts peptide C–N links only between consecutive residues
  in the same chain and sanitizes inherited records, preventing false external
  carbon bonds and OpenMM `addHydrogens` template failures.
- Diagnose checks each explicit PDB chain independently, so a normal boundary
  such as `A/GLY86` to `B/MET1` is not reported as an internal chain break.

## [0.8.0] — 2026-08-11

### Fixed

- Revert unsupported AMBER protonation variants (`ASH`, `GLH`, `LYN`, and
  `CYM`) at uncapped protein chain ends to their standard parent residues,
  updating both the PDB and `.dat` handoff and warning the user. Explicit
  ACE/NME caps preserve protonation, and CHARMM terminal protonation is left
  unchanged.
- Prevent `zbs --no-terminal --fasta` from carrying a protonated artificial
  coordinate endpoint into AMBER minimization when the complete FASTA extends
  beyond the observed structure.

## [0.7.28] — 2026-08-11

### Fixed
- Hardened Workspace ordering and persistence against filtered-list corruption and stale writes.
- Corrected unified CLI option dispatch so command `--output` is never consumed
  as an abbreviation for the batch-only `--output-dir` option.
- Recognized four-character CHARMM protonation names such as ASPP and GLUP
  during residue classification and force-field detection.
- Preserved crystallographic waters end to end when `zbs --keep-water` is used,
  including through the minimize stage without retaining temporary solvent.
- Packaged the bundled AMBER and CHARMM GROMACS force-field trees in wheels and
  resolved them from the active environment instead of requiring a checkout.
- Validated GUI workspace paths and Homology command options at the server boundary.

### Changed
- Added bounded, cancellable GUI subprocess execution with explicit executable/argument configuration.
- Centralized command/module/category/batch/output metadata in one declarative
  registry shared by CLI dispatch, CLI-reference generation, and GUI-schema generation.
- Added argparse-time positive/non-negative numeric checks and structured
  selector checks for pull bonds/anchors and topology SS/HIS/protonation inputs.
- Added release CI that builds wheel and source distributions, installs the
  wheel cleanly, and checks version/help plus bundled force-field resources.
- Moved CLI reference and GUI schema freshness checks into the fast CI lane.
- Made the `pyproject.toml` version authoritative and synchronized Python, GUI,
  lockfile, and latest-changelog versions at 0.7.28.

### Removed
- Removed the deprecated `dvbfixer glycam` command alias; use
  `dvbfixer convert`.
- Removed the deprecated `zbs --skip-protonate` compatibility option; use
  `--no-propka --no-protassign` when both preparation-time assignments should
  be disabled.
- Removed the deprecated Python keyword `include_gromacs_lyn`; callers must use
  `include_gromacs_shifts`.
- Removed the deprecated `create_forcefield_with_openff` keyword sink for the
  obsolete `small_mol_ff` and `extra_molecules` arguments.
- Removed the deprecated `parametrize --psi4-method`, `--psi4-nthreads`, and
  `--psi4-memory` aliases; use the shared `--qm-*` options.
- Removed the GUI server's `DVBFIXER_CMD` fallback. Configure
  `DVBFIXER_EXECUTABLE` and, when needed, the `DVBFIXER_ARGS` JSON array.

## [0.7.27] — 2026-08-11

### Added

- Homology template-chain selectors show pairwise sequence identity to the
  selected target chain, automatically choose the highest-identity chain,
  and can be filtered by target chain.
- Empty template rows can be added without first loading a structure in the
  3D viewer; an active workspace structure is still used as the default.
- Library now lists workspaces only; a separate Workspace panel contains the
  active workspace's files and file actions.

### Changed

- The GUI command schema includes every current CLI option, presents help for
  every field type, and retains the CLI's semantic grouping.
- Homology workflow tabs use numbered labels with punctuation.
- Workspace and file renaming uses an in-app dialog instead of a browser
  prompt, fixing context-menu rename handling.

## [0.7.26] — 2026-08-11

### Fixed

- `--atom-naming gromacs` now emits ACE/NME atom names that exactly match the
  bundled GROMACS AMBER and CHARMM RTP entries (`HH31/HH32/HH33`, NME `CH3`,
  and CHARMM NME `HN`). The previous cap hydrogen conversion was reversed.

## [0.7.25] — 2026-08-11

### Added

- `prepare` and `zbs` can add neutral ACE/NME peptide caps with
  `--cap-termini`, optionally restricted with repeatable `--cap-chain`.
- Explicit CHARMM36 ACE/NME OpenMM templates allow capped structures to pass
  hydrogen placement and minimization without patched-template ambiguity.

### Fixed

- `top --ff amber|charmm` retains explicit ACE/NME residues and their peptide
  bonds instead of silently dropping them from the protein chain.
- `--strip-heterogens` preserves requested or pre-existing peptide caps while
  continuing to remove ordinary heterogens.

## [0.7.24] — 2026-08-11

### Changed

- Every subcommand now has a dedicated Batch mode section in both `--help` and
  its command guide. Unsupported tools explicitly explain that directory input
  is unavailable instead of silently omitting batch information.
- The batch guide now contains a complete support matrix for all 21 tools.

## [0.7.23] — 2026-08-11

### Added

- `--log-file PATH` tees complete command and child-process output to an
  append-only log, with a versioned UTC run header.
- `--number-from-1` normalizes final `renumber`, `model`, and `zbs` structures
  without changing intermediate ZBS identifiers.
- Every batch-capable command now documents folder processing in its own help
  and guide; homology documentation lists its complete CLI surface.

### Changed

- OpenMM minimization now prevents Cα inversion with a non-singular signed-
  volume guard. Emergency reflection is audited in PDB REMARK records and must
  pass guarded local minimization before output is written.
- Diagnose reports current D-isomer status and prior forced chirality repairs
  in text and JSON, including a hydrogen-geometry inspection warning.

## [0.7.22] — 2026-08-06

### Added

- `split --assembly ID|all` extracts PDB biological assemblies from REMARK 350,
  including BIOMT-generated coordinate copies. Assembly mode preserves residue
  numbers by default and regenerates chain-sensitive structural records.
- The tracked 8XJ0 regression verifies its four deposited Fab assemblies:
  AB, CD, EF, and GH.

### Fixed

- The argparse-only `dvbfixer.prepare.cli` module no longer imports the heavy
  OpenMM/PDBFixer pipeline through its package initializer, restoring the
  lightweight CI lane that deliberately runs without OpenMM.

## [0.7.21] — 2026-08-06

### Changed

- All PDB and FASTA inputs actively used by pytest are now tracked under
  `tests/fixtures/`, with descriptive names, provenance documentation, and a
  SHA-256 integrity manifest. Fixture-dependent tests no longer silently skip
  because the historical local `test/` tree is absent.
- Corrected the test taxonomy: the former `default.pdb` is a GLYCAM-named
  hinge/CH3 glycoprotein, not a pure protein. Pure-protein smoke tests now use
  the protein-only 8CZ8 input.
- SMILES graph ambiguity handling recognizes ionized carboxylate/sulfonate
  resonance-equivalent oxygens. A real 1VCU regression now prepares DAN and
  both EPE molecules from explicitly selected near-physiological microspecies
  while retaining separate coverage of the automatic no-SMILES path.

## [0.7.20] — 2026-08-06

### Added

- `prepare` and `zbs` accept repeatable optional
  `--smiles 'RESNAME=SMILES'` mappings for isolated one-residue ligands.
  Mapped ligands retain their PDB heavy atoms and coordinates while SMILES
  supplies authoritative bond orders, aromaticity, formal charge, and
  hydrogen counts. Unmapped ligands—and every invocation without
  `--smiles`—continue through the existing automatic RDKit/OpenBabel path.
- SMILES graph matching fails clearly on missing or incompatible residues,
  chemically ambiguous mappings, and covalently attached ligands instead of
  silently guessing their chemistry.

## [0.7.19] — 2026-08-04

### Fixed

- Batch `diagnose` now distinguishes a successful analysis containing
  ERROR-severity findings (diagnose exit status 1) from a command execution
  failure. Summaries label these structures as `FINDINGS` and link their
  individual reports.

## [0.7.18] — 2026-08-04

### Changed

- Folder processing now continues after failures by default. Use
  `--fail-fast` to stop immediately.
- Batch completion output now reports succeeded, failed, and unprocessed
  counts and lists failed files on separate lines.

## [0.7.17] — 2026-08-04

### Added

- Shared folder input for single-structure commands via `--input-dir`,
  `--output-dir`, `--recursive`, and `--continue-on-error`.
- Default ZBS postflight diagnostics that write a JSON report and warn on
  ERROR-level findings; `--strict-postflight` promotes findings to pipeline
  failure, while `--no-postflight` skips the check.
- `dvbfixer doctor` text/JSON capability reporting for optional Python
  packages, chemistry executables, and OpenMM platforms.

### Changed

- Temporary working paths are now reserved safely instead of using the
  race-prone `tempfile.mktemp()` API.
- Corrected FASTA/SEQRES, ZBS stage, and minimization-restraint documentation.
- Diagnose no longer flags valid four-coordinate sulfur in sulfonates and
  buffer molecules as an impossible valence state.
- CI dependency guards now skip OpenMM integration tests in the lightweight
  lane and treat an installed but unlicensed Modeller as unavailable instead
  of aborting test collection.

## [0.7.16] — 2026-08-04 (branch: `fix/fasta-alignment`)

### Fixed

- **`model --no-terminal` could turn missing terminal sequence into an
  enormous internal loop.** Three independent code paths greedily matched
  each observed residue to the next same letter in FASTA/SEQRES. On 8B01
  chain C this anchored the first observed alanine at reference position 27
  and scattered 104 resolved residues through position 507, inventing 377
  internal residues even though the resolved chain is an exact contiguous
  match at positions 404-507. Renumbering, terminal trimming, Modeller PIR
  correction, and post-model numbering now share one affine semi-global
  alignment. `--no-terminal` crops only outside the first and last observed
  anchors while retaining genuine gaps between them.
- **`zbs --fasta` was not forwarded to its initial renumber step.** Standalone
  `renumber` now accepts `--fasta`, and `zbs` passes it through so residue
  numbers consistently use full-reference positions before modeling. Equal
  best alignments use a deterministic leftmost placement and emit a warning.

## [0.7.15] — 2026-07-31

Three follow-ups from the user after 0.7.14's audit pass: a reported
"strange links between lipid atoms" bug, a perceived `model`-step
slowdown, and the `top/pipeline.py` glycan-tree split that 0.7.14 had
deliberately deferred.

### Fixed

- **HETATM ligand resSeq colliding with a gap-filled protein residue,
  causing coordinate cross-contamination.** The standalone, FASTA-blind
  `renumber.py` numbers ATOM and HETATM residues in one shared
  sequential space; when `model`'s FASTA-aware gap-fill later expanded
  a chain, a ligand's naive resSeq could land on a newly-created
  protein residue's resSeq. `minimize`'s legacy strip-and-splice
  position-restore merge (keyed by `(chain, resid, atomname)`, no
  resname check) then silently overwrote the ligand's colliding atoms
  with the protein residue's minimized coordinates — confirmed on a
  real fatty-acid ligand (`test/lipid/`), reproducing the user's report
  exactly (an atom teleported tens of Å away from the rest of its own
  molecule). Fixed in `model/renumber.py`'s `build_resnum_mapping`
  (detects the collision, renumbers clear of it, warns); hardened
  `minimize/pipeline.py`'s restore-merge key to `(chain, resid,
  parent_resname, atomname)` as defense-in-depth.
- **`top/pipeline.py` silently dropped any HETATM chain it couldn't
  classify as protein/sugar/ceramide/known-small-molecule** — no
  warning, no error, the chain just never appeared in the output
  `.top`'s `[ molecules ]` section. Found while adding baseline test
  coverage for `TopologyBuilder` on the same fatty-acid ligand above.
  Now emits a `WARNING` naming the dropped chain and its resname(s);
  does not add new topology support for arbitrary small molecules
  (that's `--acpype` / `minimize --parametrize-ligands`'s job).

### Investigated, no fix needed

- **Perceived `model`-step slowdown.** Timed `dvbfixer model` on the
  same input/flags at `241710a` (pre-0.7.10) vs current `HEAD`: both
  22 seconds, identical `molpdf`. No regression in this branch —
  likely inherent Modeller loop-refinement variance or an
  input-dependent effect.

### Refactor

- **Completed the `top/pipeline.py` glycan-tree split that 0.7.14
  deferred as "too risky."** A precise line-boundary re-read found the
  prior session's characterization was wrong — `TopologyBuilder` was
  never nested inside `build_glycan_trees`; it's a separate,
  self-contained top-level class. Split into `top/types.py` (shared
  dataclasses: `PDBResidue`, `PDBChain`, `AtomEntry`, `ChainTopology`),
  `top/glycan.py` (`detect_glycan_links`, `build_glycan_trees`,
  `_is_ceramide`, `_parse_conect_bonds`), and
  `top/topology_builder.py` (`TopologyBuilder`, `_match_atom_names`,
  `_resolve_sugar_rtp`). `top/pipeline.py` shrank from ~2966 to ~1305
  lines and is now CLI orchestration + PDB I/O only. Added
  `tests/test_top_pipeline_baseline.py` — the first test coverage
  `TopologyBuilder` has ever had (protein / glycan / unrecognized-chain
  paths) — before performing the move, then verified every moved
  function/dataclass byte-identical via `inspect.getsource()` /
  `dataclasses.fields()`, plus real `dvbfixer top` runs on protein,
  glycan, and lipid fixtures comparing output before/after (identical
  modulo a pre-existing, unrelated set-iteration-order
  non-determinism in `build_glycan_trees`'s root-finding, reproduced
  even between two runs of the same already-split code).

## [0.7.14] — 2026-07-31 (branch: `fix/audit-2026-07-31`, not yet merged to main)

A 6-agent parallel codebase audit (excluding `homology.py`) found and
this branch fixes every confirmed finding — High + Medium + Low
severity, plus suggested improvements. Full detail per item is in the
branch's commit messages (4 commits, one per severity bucket); summary
below.

### Fixed — High severity

- **Insertion-code collapse corrupted protonation-variant names.**
  `prepare/pipeline.py` collapsed `(chain, resid, icode)` variant keys
  down to `(chain, resid)`, silently overwriting one insertion-code
  sibling's variant with another's (e.g. a Kabat CDR-loop `H:82`/
  `H:82A` pair). Fixed end to end: the merge/collapse, `_restore_variants`'s
  PDB-line matching, the `.dat` `variant_overrides` encoding (now
  `"chain:resid:icode"`, unambiguous), and `ffutils.variants`'
  `build_variants_list`/`rename_variants_to_parent_in_topology`/
  `restore_variants_post_addhydrogens`/`fix_lyn_hz_naming`. Ported the
  same fix into `minimize/pipeline.py`'s parallel `amber_renames`
  system, which had the identical collapse.
- **`minimize` computed restraint tiers against stale, pre-rebuild atom
  indices** — silently applying strong/weak/free restraints to the
  wrong atoms on any input with missing atoms or protonation variants
  (i.e. almost any real structure from `model`/`prepare`). Fixed by
  capturing `(chain, resid, icode, atom_name)` keys instead of raw
  indices and re-resolving them against the final topology.
- **`dvbfixer top --merge` silently zeroed every atom's coordinates**
  in `--pdb` output (`_merge_chains`'s `AtomEntry` construction omitted
  `x`/`y`/`z`/`chain_id`/`orig_resseq`/`orig_resname`). Also fixed
  `resnr` to offset per chain (was colliding across chains).
- **Same-residue sugar-bond distance guard used the wrong (narrower)
  name table** in `pdbutils/inference.py`, letting spurious same-residue
  CONECT records through for NGA/A2G/CHARMM-GUI-named sugars.
  Consolidated the PDB/CHARMM-GUI sugar-name sets — independently
  drifted in ≥3 places — into one canonical `ffutils.is_pdb_sugar_resname`
  helper. `top/ff_data.py`'s `PDB_TO_CARB` was also missing a `BNE5AC`
  (beta-anomer sialic acid) entry entirely, silently dropping its bonds.

### Fixed — Medium severity

- `ffutils.geometry.rebuild_missing_atoms_with_retry` (0.7.13) only
  covered `fixer.missingAtoms`, never `fixer.missingResidues` (whole
  gap-filled residues) — both go through PDBFixer's identical
  clash-escape MD. Reworked to diff the post-call topology against a
  pre-call snapshot, covering both uniformly.
- Disulfide-bond snapshot/cleanup was out of sync across 3 call sites
  (`minimize/pipeline.py`'s two branches + `protonate.py`, which had
  none at all). Moved the shared helpers into `ffutils.geometry`.
- Standalone `renumber.py`'s `align_to_seqres` had zero mutation
  tolerance — a single point mutation vs. wild-type SEQRES silently
  misplaced that residue (and everything after it) to the sequence
  tail. Bounded the forward search and fall back to a point-substitution
  interpretation instead of leaving it unmapped.
- `transplant.py`'s CONECT remap keyed by `(chain, resseq, name)`,
  omitting insertion code — unlike every other identity key in the file.
- `top/pipeline.py`'s `_count_water` used a single hardcoded
  atom-count/3 divisor, wrong for TIP4/TIP5/HOH.

### Fixed — Low severity / cleanup

- `split_chains.py` never emitted a closing `TER` for the last chain.
- Temp-file leaks in `prepare/pipeline.py` (exception path) and
  `minimize/pipeline.py` (`--ff amber+glycam` auto-convert, `--rename`,
  `--ff charmm` output auto-convert) — wrapped in `try/finally` or
  deferred to `atexit`, matching the existing
  `pdbutils._materialise_inferred_pdb` pattern.
- `model/modeller_run.py`'s post-refinement chirality sweep silently
  skipped any candidate whose PDB failed to load, with no diagnostic.
- Removed dead code: `minimize/refine.py::_restore_glycosylated_h`
  (confirmed zero callers) and `cluster.py::gromos_cluster`'s
  unreachable `neighbor_counts[best_local] == 0` check.
- Removed a stale comment in `protonate.py` claiming a nonexistent
  `Modeller.addHydrogens(ignoreExternalBonds=...)` parameter, and fixed
  `diagnose/steric.py`'s docstring citing the wrong default clash-mode
  cutoffs.

### Fixed — found during this branch's own regression-test writing

- **CRITICAL: `prepare` could silently delete the user's own input
  file.** `run_pdbfixer` compared `preprocessed_path`/`canon_path`
  (always plain `str`) against `input_path` (a `Path` object) with
  `!=` — always `True` in Python regardless of whether they name the
  same file. A completely no-op preprocess+canonicalize pass (a clean
  PDB needing neither fix — the common case) still unconditionally
  unlinked `canon_path`, which in that case IS `input_path`. Confirmed:
  `dvbfixer prepare <file> --no-infer-conect` on an already-clean input
  permanently deleted the file. Fixed by normalizing to `str` once at
  the top of `run_pdbfixer`.
- The "capture AMBER/CHARMM variant names from input" loop read
  `fixer.topology.residues()`, but PDBFixer's own parser already
  normalizes variant names (HIE/HID/HIP/... → HIS) at construction
  time — the loop was a silent no-op the whole time despite its own
  comment's stated intent. Fixed to scan the raw input text via
  `ffutils.variants.scan_variant_names` instead.

### Improvements

- Narrowed two `except (ValueError, Exception)`/`except Exception`
  catches around `createSystem` in `minimize/pipeline.py` to
  `except (ValueError, KeyError)` — the two types this codebase has
  actually observed from that call — so an unrelated real bug surfaces
  as a crash instead of masquerading as an expected template failure.
- `protonate.py`: removed a pointless `findNonstandardResidues()` call
  whose result was immediately discarded, plus its bare
  `except Exception: pass`.
- Evaluated splitting `top/pipeline.py`'s glycan-tree builder into its
  own module; found the actual structure is a ~1278-line function
  containing a nested class with zero test coverage for its riskiest
  path (glycolipids) — decided not to attempt this move blind. Left as
  a documented follow-up requiring test coverage first.
- Added regression tests for every fix above (11 new tests).

## [0.7.13] — 2026-07-31

### Fixed

- **`model`'s residue renumbering could silently produce duplicate
  `(chain, resid)` keys when an internal gap's flanking residues left
  no numeric "room" for it in the input's own numbering.** Confirmed
  on a real scFv construct (`test/8cz8/8cz8_a_u.pdb` /
  `8cz8_a_b.pdb`, chain C): the disordered (GGGS)×4 linker between VL
  and VH has no electron density, and the depositor numbered VH's
  first residue (111+1=112) immediately after VL's last one (111) —
  never reserving the 16 resSeqs the missing linker actually needs.
  `dvbfixer zbs 8cz8_a_u.pdb --fasta 8cz8_renamed.fasta --atom-naming
  standard --no-solvent -v` reproduced it: the rebuilt linker got
  renumbered to resSeqs 96-111 (colliding with the already-used 1-111
  stretch) and every residue after it was off by a constant -16 for
  the rest of the chain (final range 1-231 instead of 1-247 for 247
  actual residues).

  Root cause: `src/dvbfixer/model/renumber.py`'s `_interpolate_gaps`,
  internal-gap branch — when `available = right - left - 1 < gap_len`,
  it numbered the gap BACKWARD from `right` (`right - gap_len + k`)
  with no collision check at all, unlike the N-terminal-gap branch
  immediately above it (which already detects an equivalent
  "not enough room" condition and shifts the rest of the chain
  forward instead of colliding). Confirmed NW alignment itself was
  not confused by the linker's periodicity — the real trigger is any
  internal gap whose flanking anchors are numerically adjacent (or too
  close) in the input's own resSeq, independent of sequence
  composition. A byte-for-byte duplicate of the same bug existed a
  second time in `build_resnum_mapping`'s own hand-rolled fallback
  gap-loop (the align2d-mask last-resort path), which had drifted out
  of sync with `_interpolate_gaps` (no `renumber_from_1` handling).

  Fixed by making the internal-gap "not enough room" branch place the
  gap sequentially from `left + 1` (matching the "enough room"
  branch) and shift every already-placed resSeq downstream by the
  deficit — mirroring the N-terminal branch's existing
  shift-the-rest-of-the-chain pattern (WARN emitted). The fallback
  path's duplicate loop was replaced with a direct call to the fixed
  `_interpolate_gaps` instead of carrying two copies of the same
  logic. Verified: both `8cz8_a_u.pdb` and `8cz8_a_b.pdb` now produce
  chain C with resSeq range 1-247, zero duplicates, matching the FASTA
  1:1.

  Two other functions have the same theoretical vulnerability pattern
  but were NOT touched (no concrete repro found): the standalone
  `renumber` subcommand's `align_to_seqres`
  (`src/dvbfixer/renumber.py`) and `model/modeller_run.py`'s
  `_fix_terminal_alignment`.

## [0.7.12] — 2026-07-31 (branch: `fix/seeded-atom-rebuild`, not yet merged to main; merged to `main` in 0.7.13's session)

### Fixed

- **`PDBFixer.addMissingAtoms()` was called unseeded at all 5 call
  sites** (`prepare/pipeline.py`, `minimize/pipeline.py` ×2,
  `protonate.py`, `top/pipeline.py`). When rebuilding a missing
  sidechain (e.g. a LYS truncated to backbone+CB by real
  crystallographic/cryo-EM disorder — confirmed 11 of 19 LYS residues
  in `test/8cz8/8cz8_t_u.pdb` chain E), PDBFixer superposes the
  missing atoms from an ideal template, minimizes locally, and — if
  the result clashes with a neighbor (< 0.13 nm, its own
  `_findNearestDistance` cutoff) — runs genuine UNSEEDED Langevin
  dynamics (300 K, up to 2000 steps) to kick the atoms apart. The
  escaped conformation differed run to run on the *exact same input*,
  occasionally leaving a rebuilt sidechain non-deterministic or
  D-chiral, which downstream `minimize` could only react to after the
  fact (reflect + re-minimize) — not prevent.

  Fixed by adding `dvbfixer.ffutils.geometry.
  rebuild_missing_atoms_with_retry`: calls `addMissingAtoms(seed=1, 2,
  3...)` up to 5 times, checking after each attempt whether the
  rebuilt residues are L-chiral and clash-free
  (`find_clashing_atoms`, new helper, matches PDBFixer's own 0.13 nm
  cutoff but — unlike PDBFixer's own check — excludes the whole same
  residue, not just directly-bonded atoms, since a flexible sidechain
  can legitimately place two of its own atoms this close in a gauche
  conformation). Keeps the first clean attempt, or the last attempt
  with a printed warning if none passed. Wired into all 5 call sites.

  Verified: the 11 truncated LYS residues in `test/8cz8/8cz8_t_u.pdb`
  chain E now rebuild to bit-identical, clash-free, L-chiral
  coordinates across repeated `prepare` runs (previously varied run to
  run). Full end-to-end `zbs` flakiness is reduced but not fully
  eliminated — a second, independent source of run-to-run variation
  exists in `minimize`'s own full-system energy minimization
  (confirmed: a residue with zero missing atoms, `SER212`, still
  drifted to D-Cα in 1 of 5 repeated `zbs` runs); the existing
  unconditional force-reflect safety net in `minimize` continues to
  guarantee a zero-D-Cα final structure in every case.

- **`prepare.pipeline.run_pdbfixer`'s `PDBFixer` call order silently
  discarded missing-heavy-atom rebuilds whenever heterogens were
  stripped** (the default). `PDBFixer.removeHeterogens()` and
  `PDBFixer.replaceNonstandardResidues()` each rebuild an entirely new
  `Topology` internally (`Modeller(...).delete(...)`), which
  invalidates the `fixer.missingAtoms` dict computed by an earlier
  `findMissingAtoms()` call — it's keyed by Residue *object identity*
  against the topology that existed at that time, and PDBFixer's own
  `_addAtomsToTopology` looks residues up in it by identity. The old
  order (`findMissingAtoms()` before `removeHeterogens()`/
  `replaceNonstandardResidues()`) meant `addMissingAtoms()` silently
  added **zero** heavy atoms for every genuinely-missing sidechain on
  every default (heterogens-stripped) run — confirmed on `main`
  (pre-existing, not introduced by this branch): `E/LYS299` in
  `test/8cz8/8cz8_t_u.pdb` stayed backbone+CB straight through
  `prepare`, even though PDBFixer's own verbose log correctly reported
  `CG`/`CD`/`CE`/`NZ` as missing beforehand.

  Fixed by reordering `run_pdbfixer` to match PDBFixer's own canonical
  usage: `findNonstandardResidues()` -> `replaceNonstandardResidues()`
  -> `removeHeterogens()` -> `findMissingAtoms()` ->
  `rebuild_missing_atoms_with_retry()`. `findMissingResidues()` (and
  its deletion-scrub logic) stays where it was — it's keyed by
  `(chain.index, indexInChain)`, a positional pair that survives the
  later rebuilds, unlike Residue-object identity.

## [0.7.11] — 2026-07-31

### Fixed

- **`prepare` could crash unrecoverably on a HIS residue with an
  incomplete imidazole ring** — `ValueError: HIS residue (N) has the
  wrong set of atoms` from OpenMM's `Modeller.addHydrogens`, on both
  the whole-topology attempt and the protein-only fallback, since both
  share the same fragile internal auto-detect logic (requires exactly
  one `ND1` and one `NE2`; no recovery path if the count is off).
  Confirmed on a real structure (`test/8cz8/8cz8_t_u.pdb`, chain E
  resid 371): a genuine crystallographic-disorder case where the whole
  ring (`CG`/`ND1`/`CD2`/`CE1`/`NE2`) is missing from the deposited
  file, only backbone + CB survive.

  Root cause: PROPKA + MolProbity Reduce ran on the **raw input**,
  *before* `PDBFixer`'s own `findMissingAtoms`/`addMissingAtoms`
  rebuilds a residue's missing heavy atoms — confirmed PDBFixer's
  repair is otherwise correct here (verified directly: it detects and
  rebuilds all five missing ring atoms when run on this file in
  isolation). Since PROPKA can't even identify a titratable HIS group
  without ND1/NE2 to look at, it silently emitted *no* pKa result at
  all for this residue (not "neutral" — absent), so the existing
  `decide_protonation`/`--his-default` fallback (which only fires for
  residues PROPKA *did* analyze and found ambiguous) never got a
  chance to run, and the variant decision fell all the way through to
  `variants.append(None)`, deferring to OpenMM's own fragile
  auto-detect — the actual crash site.

  Fixed by reordering: `run_pdbfixer` (`src/dvbfixer/prepare/pipeline.py`)
  now runs PROPKA + MolProbity Reduce *after* `PDBFixer.addMissingAtoms()`
  and the chirality fix, on the now heavy-atom-complete structure
  (written to a temp PDB), instead of on the raw input. `main()` no
  longer runs `_run_propka_reduce_variants` itself — that call, and the
  SS-bond detection feeding it, moved inside `run_pdbfixer` between its
  heavy-atom-repair and hydrogen-placement phases. Once PROPKA sees a
  complete (rebuilt) ring, it behaves like any other HIS residue and
  the *already-correct* `his_default` fallback machinery covers it
  automatically — no new fallback logic was needed for the primary
  fix. A defensive backstop was added anyway (belt-and-braces): if a
  HIS residue still lacks a complete ND1/NE2 pair at the point the
  `variants` list is built — for whatever reason, even one not yet
  seen — it resolves directly to `--his-default` instead of `None`,
  with a one-line warning naming the residue, so this class of crash
  can never recur regardless of the specific trigger.

### Changed

- `run_pdbfixer`'s signature dropped the `extra_variants` parameter
  (PROPKA/Reduce results are now computed internally) in favor of
  `his_default`, `cys_ss_pka`, `use_propka`, `use_reduce` — the raw
  inputs `_run_propka_reduce_variants` needs. It has exactly one call
  site (`prepare/pipeline.py`'s own `main()`), so this isn't a public
  API change for any other caller.

## [0.7.10] — 2026-07-30

### Fixed

Real production `zbs` runs on `test/3ry6/3ry6.pdb` and
`test/protein_ligand/1VCU.pdb` still showed broken glycan geometry and
ligand clashes after 0.7.9's connectivity/valence fixes — the pytest
regressions only checked bond *existence*, not 3D sanity. Root-caused
via two live Explore-agent investigations plus manual verification;
five further, independent, compounding causes found and fixed:

- **`renumber.py` fabricated bonds from a stale/dangling CONECT
  record.** The deposited `3ry6.pdb` itself has a `CONECT` record
  referencing serial numbers with no matching ATOM/HETATM line at all
  (leftover cruft, not something dvbfixer produced). `update_conect`'s
  fallback (`serial_map.get(old_serial, old_serial)`) passed such an
  unmapped serial through UNCHANGED — and because dvbfixer renumbers
  everything into a dense, small range, that stale number collided
  with the NEW serial assigned to a real, unrelated atom (a glycan's
  own C1/C2/C3), fabricating a chemically-impossible bond
  (`C1-C3`/`C3-C5`/etc. — the literal "tons of incorrect bonds"
  reported). This was the true final blocker: with it fixed, the
  whole-system GLYCAM+GAFF2 minimize path succeeds outright with zero
  fallback, where before it silently degraded to the ligand-losing
  legacy strip-and-splice path. `update_conect` now drops the whole
  CONECT record when any referenced serial isn't a real atom, rather
  than keeping a partially-wrong one.

- **`add_glycam_bonds` has been dead code since 0.7.8.**
  `acpype_export.py` imported `KNOWN_GLYCAN_SMILES` from
  `dvbfixer.ffutils` — a symbol that never existed there. The
  resulting `ImportError` was caught by a `try/except Exception` that
  also (incidentally) wrapped the unrelated `openmm.unit.nanometer`
  import, silently defeating unit conversion too. Every call to
  `add_glycam_bonds` (from both `prepare` and `minimize`) has therefore
  never successfully populated sugar-sugar/protein-glycosylation
  distance-based bonds in production. Fixed by importing
  `nanometer` directly and reusing the module's own broader
  `_is_glycam_sugar` (already covers both GLYCAM-canonical codes and
  plain PDB sugar names — closer to the original, never-implemented
  `KNOWN_GLYCAN_SMILES` intent than `ffutils.is_glycam_sugar` alone).

- **No spurious-bond filter for sugar/GLYCAM residues in CONECT
  inference or in `prepare`'s heterogen-H passes.**
  `pdbutils/inference.py::_apply_filter` already guarded standard
  amino acids against OpenBabel `ConnectTheDots` same-residue false
  positives (proximity-based, no actual bond) but had no equivalent
  guard for sugars; the same unfiltered proximity-bonding also fed
  `prepare/glycan.py`'s `add_heterogen_h_via_rdkit` (RDKit
  `proximityBonding=True`) and `_process_single_residue`'s OpenBabel
  per-residue harvest independently. All three now drop a same-residue
  bond on a GLYCAM/PDB sugar residue unless it's within a real covalent
  distance (~1.7 Å).

- **Heterogen heavy atoms got zero positional restraint during
  minimize by design** (`build_restraint_force`, "BioLuminate-style:
  protein is fixed-ish, ligands relax") — reasonable for a small,
  torsion-poor ligand, but a multi-residue glycan tree with many free
  glycosidic torsions and no restoring force could drift a mean of
  4+ Å (up to 10+ Å) off its covalent anchor into an unrelated,
  clashing part of the protein surface, worse under `--no-solvent`'s
  unscreened electrostatics. Web research on glycoprotein MD/structure-
  prep best practice (CHARMM-GUI equilibration protocols, published
  setups) confirmed protein *and* glycan heavy atoms should be
  restrained together during initial minimization, commonly
  ~1-10 kcal/mol/Å² — squarely in this restraint scheme's existing
  `weak_k` tier (5.0), now reused for heterogens instead of leaving
  them fully free.

- **Plain `zbs` (no `--parametrize-ligands`) silently degraded to a
  ligand-losing fallback for any unknown heterogen.** `minimize`'s
  whole-system `createSystem` fails on a ligand with no FF template
  (e.g. DAN), which used to trigger the legacy strip-and-splice
  fallback: the ligand is removed entirely before the real minimize
  runs, nearby pocket residues relax into the now-empty cavity, and
  the ligand is spliced back at its ORIGINAL pre-minimize coordinates
  with no tracking mechanism (`_rigid_track_glycan_trees` only follows
  covalently-bonded trees, not free ligands) — producing a severe
  clash. `minimize` now auto-attempts GAFF2 parametrization
  (`lig_params.build_ligand_generator`, non-strict) whenever an
  unknown heterogen is present, regardless of the flag; environments
  without AmberTools/openff fall through to today's behaviour
  unchanged. Two more bugs in the same area, found while making this
  actually work end-to-end: (1) `Modeller.addHydrogens()`'s internal
  `createSystem` can raise `KeyError` (not `ValueError`) when its own
  temporary re-matching invokes the GAFF2 generator — now caught
  alongside `ValueError` in the existing "fall back to protein-only H
  placement" handler; (2) minimize's strip-and-readd-H path (for
  AMBER protonation variants) unconditionally stripped H from EVERY
  residue including arbitrary ligands, which `addHydrogens` then has
  no way to restore (no hydrogens.xml entry) — now scoped to protein
  residues only, since this whole mechanism is about protein-side
  protonation variants, not heterogens.

Net result: `zbs --no-solvent` on `3ry6.pdb` now reaches the real
whole-system minimize with zero fallback and zero glycan/protein
clashes (previously 68-86 non-bonded contacts < 1.5 Å); on `1VCU.pdb`
(plain `zbs`, no extra flags) clashes dropped from 11 down to a single
mild ~1 Å H-H contact (a real, but far smaller, remaining
openmmforcefields/OpenMM limitation around invoking a dynamic
template generator from inside `addHydrogens`'s own internal
matching).

## [0.7.9] — 2026-07-30

### Fixed

- **Ligand H/valence bugs on `prepare`'s heterogen-H passes** (both
  the RDKit and OpenBabel code paths in `prepare/glycan.py`), plus
  the identical root cause in `--parametrize-ligands`
  (`lig_params.py`):
  - **DAN's ring alkene (C2=C3, "2,3-didehydro" sialic acid) and its
    amide carbonyl (C10=O10)** weren't recognised by geometry-only
    bond perception (the crystal C2-C3 distance reads as an ordinary
    single bond at this resolution), so C2/C3 were saturated to sp3
    (spurious H on C2, one too many on C3), and DAN's SDF for GAFF2
    had an unfillable radical. New `dvbfixer.ffutils.ligand_valence`
    module carries a small per-ligand `_KNOWN_DOUBLE_BONDS` /
    `_H_COUNT_OVERRIDES` table for exactly this class of problem —
    note that both RDKit's `AddHs` and OpenBabel's `addh()` compute
    added-H count from atom DEGREE, not bond-order-weighted valence,
    so a bond-order override alone has zero effect; only the direct
    H-count override works.
  - **Carboxylate/sulfonate over-protonation** — DAN's carboxylate
    and EPE's (HEPES) sulfonate (`S, O1S, O2S, O3S` — fully ionized
    -SO3⁻ at physiological pH) were getting spurious hydroxyls added.
    `ligand_valence.find_ionizable_terminal_oxygens_{rdkit,openbabel}`
    detects these purely from connectivity (any C/S/P center with
    ≥2/≥3 single-bonded terminal oxygens) rather than hardcoding more
    per-ligand exceptions, so it generalizes to any current or future
    ligand with these very common groups.
  - **`lig_params._extract_residue_sdf`'s OpenBabel bond perception
    was badly broken whenever hydrogens were already present** (as
    they always are, post-`prepare`) — nearly every bond, including
    N-C and C-H, came back as order 2, independent of any
    ligand-specific issue. Fixed by rebuilding a heavy-atom-only
    sub-`OBMol` (`ConnectTheDots()` + `PerceiveBondOrders()` on heavy
    atoms alone) and re-attaching hydrogens afterward at their
    existing positions with forced bond order 1, since `OpenFF`'s
    `Molecule.from_file` trusts the SDF's bond orders/formal charges
    directly with no independent re-derivation.

- **`dvbfixer convert` (`glycam.py`) silently dropped every non-ATOM/
  HETATM/CONECT header record** (SEQRES, HELIX, SHEET, CRYST1, ...)
  — `_parse_pdb` only ever read ATOM/HETATM/CONECT/LINK. Losing
  SEQRES specifically broke downstream `model` gap-filling for anyone
  piping `convert` straight into `model`/`zbs`. Fixed via
  `_extract_passthrough_header_lines`, mirroring `align.py`'s
  existing `_apply_transform_preserving_headers` pattern.

- **`convert_to_glycam`'s glycosidic-bond detection was an
  either/or CONECT gate**: if the input had *any* CONECT records,
  they were trusted exclusively for every residue, with no distance
  cross-check. A real PDB can have CONECT for some but not all of its
  N-glycosylation sites (a genuine annotation gap in the deposited
  file, not something dvbfixer caused) — the undocumented sites'
  Asn stayed unrenamed and their sugar trees ended up floating,
  unbonded, in the final output. `_merge_glycosidic_bonds` now always
  supplements CONECT-derived bonds with the distance-based detector
  for any site CONECT doesn't already cover.

- **`model.py`'s Modeller step could reposition an undocumented
  glycan chain arbitrarily far from its protein anchor.** Modeller
  has no way to know two chains are covalently linked unless a bond
  is already documented (CONECT) before it runs. `model.main` now
  calls the same `_materialise_inferred_pdb` CONECT-inference helper
  `convert`'s CLI already used, early, before Modeller reads the
  file. New `--no-infer-conect` flag opts out; threaded through
  `zbs.py` to the `model` step. Fixing CONECT *after* Modeller ran
  was tried and found ineffective — by then the arbitrary
  repositioning has already happened.

- **`renumber.py` silently dropped atoms following a bare/minimal
  `TER\n` record** (as short as 4 characters — valid PDB, but
  `line[11:]` on it returns `''`, not an IndexError, since Python
  doesn't raise on an out-of-range slice). The constructed output
  line then had no newline at all, merging directly into the next
  physical line (`TER    4748HETATM 4749  C1  ...`) — every
  downstream parser's line-start check silently dropped that atom
  (and everything else on the merged line). This was the true final
  root cause of an anomeric-carbon loss that broke glycosidic-bond
  detection several steps downstream, chained together with the two
  fixes above. Fixed by explicitly ensuring the output TER line ends
  with `\n`.

- **`minimize`'s unconditional force-reflect fallback (0.7.4) could
  leave a real inter-residue steric clash**, not just "minor
  strain" as previously assumed — a rigid sidechain mirror can swing
  a hydrogen into a neighbouring residue's atom, and hydrogens carry
  no restraint at all so they can't dodge during the reflect itself.
  Root-caused a flaky `2VLQ_original.pdb` regression failure
  (`test_zbs_shit_inputs.py`) that only ever reproduced inside a full
  test-suite run, never in isolation, because whether any residue
  needs forced reflection depends on Modeller's stochastic loop/MD
  refinement. Fixed by re-anchoring the reflected residue's restraint
  targets to their NEW post-reflection position (backbone atoms are
  untouched by `fix_ca_chirality`, so this is a no-op for them) before
  a bounded local `minimizeEnergy` — this lets the unrestrained
  neighbouring hydrogens relax away from the clash with no
  restraint-driven or energetic path back to D. The zero-D-Cα
  guarantee is unchanged: a `find_d_residues` check still runs after,
  falling back to an unconditional re-reflect (no minimize) if a
  residue ever reverts.

### Changed

- `tests/test_prepare_broken_geom.py::test_prepare_fixes_coincident_hg_and_oxt`
  no longer depends on the git-ignored `test/broken_SER/SER.pdb`
  fixture (previously skipped whenever that fixture wasn't present
  locally) — it now builds the same coincident-HG/OXT SER scenario
  as an in-test PDB string, matching the pattern already used by the
  adjacent missing-HG regression test.

## [0.7.8] — 2026-07-30

### Fixed

- **`environment.yml` / `pyproject.toml` now cap Python at `<3.14`.**
  Previously only documented (see below) — the actual dependency
  pins were still unbounded (`python >=3.11`), so a fresh env/install
  could still resolve Python 3.14 and hit the propka crash. Both now
  pin `>=3.11,<3.14`.

- **Spurious duplicate disulfide (SG-SG) bonds crashing `minimize`.**
  OpenMM's own `PDBFile.__init__` unconditionally calls
  `Topology.createDisulfideBonds()` on every load, and
  `PDBFixer.addMissingAtoms()` does the same internally on rebuild —
  both are pure distance-cutoff scans with no 1:1 matching. On
  structures where several CYS SG atoms sit close together (e.g. two
  chain copies whose N-termini pack near each other), this gives one
  SG atom two or three "partners", and `createSystem` then fails with
  `No template found for residue N (CYS) ... has 1 S atom too many`.
  Fixed at two levels: `pdbutils.inference.infer_conect_records` now
  runs a centralized dedup (`_dedupe_ss_bonds`) across every bond
  source (OpenBabel, the distance fallback, and `_domain_overrides`),
  preferring pairs already in the file's own CONECT records and
  resolving the rest by greedy nearest-distance 1:1 matching; and
  `minimize.pipeline._drop_spurious_inter_aa_bonds` gained the same
  resolution (a `positions`-driven nearest-match pass right after the
  initial `PDBFile` load, plus a `valid_ss_pairs` snapshot-and-restore
  around the strip-and-readd branch's `PDBFixer.addMissingAtoms()`
  rebuild) so the correct pairing survives every subsequent rebuild.

- **`add_glycam_bonds` never established the protein→sugar
  glycosylation bond** (ND2 on ASN/NLN, OG on SER/OLS, OG1 on
  THR/OLT, distance-matched to a sugar's anomeric carbon) — only
  `pdbutils.inference`'s file-level CONECT inference did, and
  `prepare`'s own `PDBFixer.addMissingAtoms()` rebuild doesn't trust
  on-disk CONECT for non-heterogen-only bonds, so the glycosidic
  linkage silently vanished before `minimize` ever saw it, and
  NLN/OLS/OLT's forcefield template failed to match
  ("missing 1 N/O atom. Is the chain missing a terminal capping
  group?"). `add_glycam_bonds` now also detects and adds this bond.

- **`minimize`'s strip-and-readd `addHydrogens` had no fallback** for
  a heterogen whose template genuinely can't match the input geometry
  (e.g. a glycosylation site with no sugar close enough to link to in
  this specific structure) — it would crash the whole run instead of
  degrading gracefully. Now mirrors `prepare`'s existing "falling
  back to protein-only" pattern: on `ValueError`, retry
  `addHydrogens` without a `forcefield` argument (plain geometric H
  placement, no `createSystem`/template matching), matching the
  resilience `prepare` already had.

- **`prepare`'s `_restore_variants` corrupted TER records.** It
  processes `ATOM `/`HETATM`/`TER   ` lines alike when rewriting a
  residue's variant name, but unconditionally hardcoded the output
  record type as `"ATOM  "` — so a TER line whose chain/resid matched
  a variant override (e.g. a C-terminal CYX) got rewritten into a
  malformed, coordinate-less `ATOM` line
  (`ATOM   3251      CYX L 214`, no atom name, no coordinates),
  which later crashed `minimize`'s strict `PDBFile` parser with
  `ValueError: could not convert string to float: ''`. Now preserves
  the original record type.

- **`protonate`'s `--cys-disulfide-pka` was still at the pre-0.7.7
  default (90.0)** — commit c6cebb0 fixed the equivalent `--cys-ss-pka`
  default to `99.99` (PROPKA's actual disulfide sentinel) on
  `prepare`/`zbs`/`prep_backend`, but never touched `protonate`'s own,
  differently-named flag. Now `99.99` there too.

- **Test fixture (`tests/conftest.py` / `test_zbs_e2e.py`) glycan-count
  assertion didn't recognise GLYCAM-canonical sugar residue codes**
  (`0fA`, `2MA`, `4YB`, `VMB`, `UYB`, ...) — only PDB-standard names
  (`BMA`, `NAG`, ...). `amber+glycam` intentionally renames sugars to
  GLYCAM canonical form, so the assertion now also checks
  `ffutils.is_glycam_sugar`.

### Added

- **`zbs --backend {legacy,tleap-reduce}`.** `prepare` and `protonate`
  already exposed this; `zbs` silently hardcoded `legacy` and had no
  way to reach `tleap-reduce`. Threaded through to the internal
  `prepare` invocation, with the same `--mutate` incompatibility
  guard `prepare` already enforces.

### Documented (carried over from Unreleased)

- **propka 3.5.1 × Python 3.14 incompatibility.** propka reads
  `self.__annotations__` (instance-level) inside its `Parameters`
  dataclass; Python 3.14's PEP 649/749 lazy-annotations change makes
  instance `__annotations__` raise `AttributeError` instead of falling
  through to the class dict, crashing `dvbfixer protonate` (and the
  PROPKA step inside `prepare` / `zbs`) at
  `propka.parameters.parse_line` with
  `AttributeError: 'Parameters' object has no attribute '__annotations__'`.
  `environment.yml` / `pyproject.toml` pin `python >=3.11,<3.14` to
  keep the env on 3.12/3.13 where propka works — do not loosen it.
  Documented in [CLAUDE.md](../CLAUDE.md) and
  [docs/known-issues.md](known-issues.md).

- **micromamba env creation fails on macOS Docker host bind mounts.**
  When `MAMBA_ROOT_PREFIX` lives under a host bind mount such as
  `/home/agent` (a `fakeowner` / VirtioFS bind of macOS `/Users`),
  `micromamba create` aborts during `Linking 'ncurses'` with
  `filesystem error: cannot copy symlink: Invalid argument` on the
  case-variant terminfo pair `share/terminfo/32/2621A` vs `2621a`.
  The mount is case-insensitive and rejects libmamba's `copy_symlink`
  for these case-colliding entries; `always_copy` / `--copy` do not
  help (copy mode still recreates in-package symlinks rather than
  dereferencing them), and no micromamba flag dereferences or skips
  them. Workaround: create the env + package cache on the container's
  native overlay filesystem (`export MAMBA_ROOT_PREFIX=/opt/mamba`).
  Documented in [docs/known-issues.md](known-issues.md) and
  [docs/installation.md](installation.md).

## [0.7.7] — 2026-07

### Added

- **PROPKA + MolProbity Reduce now run INSIDE legacy prepare.**
  Prior to 0.7.7 the default pipeline (`dvbfixer prepare` /
  `dvbfixer zbs`) built its `Modeller.addHydrogens(variants=[...])`
  list only from user `--mutate` overrides + HIS HD1/HE2 presence.
  Neither PROPKA nor Reduce was invoked, so pKa-driven ASH / GLH /
  HIP / LYN / CYM variants and per-residue HIS tautomer picks
  never appeared in output. Only the opt-in `--backend tleap-reduce`
  ran them. Fixed via new helper
  `dvbfixer.prepare.pipeline._run_propka_reduce_variants` which
  mirrors the tleap-reduce backend's PROPKA-decide + Reduce-tautomer
  overlay logic (fixed in 0.7.4) and is called by
  `dvbfixer.prepare` before addHydrogens. PROPKA drives ASP/GLU/
  LYS/CYS/HIS→HIP; Reduce fills in HID vs HIE for neutral HIS; user
  `--mutate` overrides win on collision; CONECT-detected SS pairs
  force CYX regardless of PROPKA's CYS pKa.

- **New CLI flags on `prepare` and `zbs`**:
  - `--propka / --no-propka` (default: on).
  - `--protassign / --no-protassign` (default: on).
  - `--his-default {HIE,HID}` (default: HIE) — fallback tautomer
    when both PROPKA and Reduce are ambiguous.
  - `--cys-ss-pka` (default: 8.0) — PROPKA pKa cutoff for CYX.

  zbs propagates the flags to prepare.

- New tests `tests/test_prepare_propka_integration.py` (6 tests).

### Changed

- **`zbs` docstring** updated: "renumber → model → prepare
  (with PROPKA + Reduce) → minimize". The stale "protonate step"
  language from pre-0.7.0 finally removed.

- **`--skip-protonate` on zbs is deprecated**. Kept for backward
  compat: now maps to `--no-propka --no-protassign` on prepare
  (with a stderr warning). Standalone `dvbfixer protonate` command
  is unchanged and can still be used as a post-hoc re-protonation
  tool (e.g. to switch pH on an already-prepared PDB).

## [0.7.6] — 2026-07

### Changed

- **`detect_ff_from_pdb` no longer surrenders on PDB-standard sugars.**
  Previously an input with IUPAC/PDB sugar codes (BGL / BMA / AMA /
  NAG / …) fell back to `amber` with a WARNING telling the user to
  run `dvbfixer convert` manually first. Now returns `amber+glycam`
  with a reason string; downstream prepare + minimize invoke
  `convert_to_glycam` under the hood so the tool Just Works on
  downloaded RCSB glycoproteins.

- **`zbs` no longer force-overrides minimize `--ff` to
  `amber14-all.xml`.** Previously when the user passed `--ff auto`,
  zbs auto-detected the FF for prepare but forced minimize back to
  plain `amber14`, breaking glycoprotein pipelines. Now the same
  `--ff` value flows to both steps; each runs its own auto-detection
  independently.

### Added

- **CHARMM + PDB-sugars hybrid path.** When `--ff charmm` is
  requested (or auto-selected) AND the input has PDB-standard sugar
  names `charmm36.xml` can't parametrise, prepare + minimize
  process the run under `amber+glycam` (which has sugar templates)
  and rewrite output residue names to CHARMM convention (`BGLCNA`,
  `BMAN`, …) via `convert_to_charmm` after the pipeline completes.
  Coordinates and topology unchanged; only sugar residue names
  differ between amber and charmm output.

- **`--atom-naming {gromacs,standard}` CLI flag** on `prepare`,
  `minimize`, `protonate`, and `zbs`. Default `gromacs` preserves
  the current behaviour (GROMACS amber99sb-ildn shifts: HB3→HB1
  keeping HB2, HZ3→HZ1 on LYN, O/OXT→OC2/OC1, H→HN for CHARMM).
  Pass `standard` to keep IUPAC/AMBER-native names (HB2/HB3,
  HZ1/HZ2/HZ3, O/OXT, plain H) — matches ff14SB / VMD / most PDB
  downloaders.

- New helper `dvbfixer.ffutils.has_pdb_standard_sugars(pdb_path)`
  — text-level scan for the auto-convert trigger.

- New tests `tests/test_ff_auto_detect_sugar.py` covering
  auto-detect on glycoproteins, amber→amber+glycam upgrade, and
  the has_pdb_standard_sugars helper.

## [0.7.5] — 2026-07

### Changed

- **Default prep backend flipped from `tleap-reduce` back to `legacy`
  (Modeller+PDBFixer).** The tleap-reduce backend hard-fails on
  glycoproteins, ligands, PTMs, and any covalent-HETATM input
  (tleap has no template for those). Legacy prep handles them via
  the existing `build_glycam_system` + `--parametrize-ligands`
  paths. The chirality invariant that motivated the switch
  originally is now enforced downstream in
  `minimize/pipeline.py`'s post-phase-2 unconditional force-reflect
  fallback (added in 0.7.4), which is prep-backend-agnostic — so
  legacy prep's PDBFixer.addMissingAtoms D-Cα risk is neutralised
  where it matters. Applies to `prepare`, `protonate`, and
  transitively to `zbs`. `tleap-reduce` remains fully functional
  via explicit `--backend tleap-reduce` for pure-protein inputs.

### Added

- Comprehensive integration test suite covering every subcommand
  (except `homology`) against real PDB inputs across the input
  classes dvbfixer supports: pure protein, antibody, glycoprotein,
  protein+ligand, multi-MODEL, and the curated `test/shit/`
  regression set.

## [0.7.4] — 2026-07

### Fixed

- **PROPKA-driven variant assignment on the tleap+reduce backend was
  broken end-to-end.** The 0.7.3 code stuffed
  `propka_dict[(chain, resnum)] = (restype, pka)` and iterated the PDB.
  PROPKA emits multiple `Group` records per residue (side-chain
  acid/base + terminal N+/C-), so last-write-wins silently clobbered
  side-chain pKas with terminal pKas — ASH/GLH/LYN were correct only
  when PROPKA's iteration order happened to land the right entry
  last. HIS→HIP was NEVER assigned because HIP was inferred from
  HD1+HE2 atom presence, but `reduce -build` picks a single tautomer.
  Rewrote to route through `dvbfixer.protonate.decide_protonation`
  (group-type-filtered, `(chain, resnum, icode)`-keyed) then overlay
  Reduce's HID/HIE tautomer for neutral HIS. `_patch_variant_hydrogens`
  gained an HIP branch that places the missing imidazole H. Deleted
  dead `_STD_PKA` and `_classify_variant`.

- **AMBER variant residue names silently broke minimize.** OpenMM's
  `PDBFile._standardResidues` set covers only the 20 canonical AAs;
  LYN/ASH/GLH/CYX/CYM/HID/HIE/HIP load with zero intra-residue bonds
  → `createSystem` fails "no bonds between its atoms". Additionally
  `Modeller.addHydrogens` copies input bonds but does NOT rebuild
  missing ones from templates, and only ADDS missing H, never
  REMOVES extras. Fix in `minimize/pipeline.py`:
  1. `text_rename_variants_to_parent` runs BEFORE `PDBFile.load` so
     OpenMM infers proper intra-residue bonds from parent templates.
  2. When `amber_renames` is non-empty, force strip-H + variant-aware
     addHydrogens rebuild.
  3. Cap the pH passed to `addHydrogens` at 9.99 to bypass the
     `hydrogens.xml` `maxph="10.0"` HZ3 gate that broke terminal LYS
     at high pH.
  4. `pdbutils/inference.py::_apply_filter` keeps intra-residue
     bonds for variant-named residues in emitted CONECT.

- **Disulfide bonds dropped during minimize.**
  `_drop_spurious_inter_aa_bonds` treated every inter-residue bond
  between two protein residues that wasn't a C-N peptide bond as
  spurious. After `text_rename_variants_to_parent` folded CYX → CYS,
  SG-SG disulfides were between two "CYS"-named residues → dropped.
  Added an SG-SG exception for the CYS family (CYS/CYX/CYM).

- **D-Cα residues occasionally survived minimize.** The prior
  WARN-only design left D residues in the output when the FF's local
  minimum for a residue genuinely sat on the D side (rare, exotic
  packing). Replaced with two-tier enforcement:
  1. Bounded reflect-and-re-minimize loop (max 3 iterations).
  2. If any residue is still D after the loop, do a final
     unconditional `fix_ca_chirality` reflection and skip any
     follow-up minimize. Since `fix_ca_chirality` mirrors the whole
     sidechain through the CA-N-C plane, all internal bond lengths
     and angles are preserved (CA-CB ≈ 0.154 nm, CB-HB ≈ 0.109 nm);
     only CB's position relative to backbone neighbours changes. The
     chirality invariant is now non-negotiable: zero D-Cα in output.

### Added

- `tests/test_prep_backend_variants.py` — 16 focused tests for the
  PROPKA + variant-H paths, covering ASH, GLH, LYN, HIP, HID, HIE,
  CYX-from-SS, terminal skip.

## [0.7.0] — 2026-07

### Fixed
- **Full GROMACS-canonical atom naming on every user-visible PDB
  output.** Prior 0.6.5 fix only handled LYN NZ hydrogens. Full
  sub-agent survey (Jul 2026) identified pervasive naming
  differences OpenMM ff14SB (IUPAC) vs GROMACS amber99sb-ildn
  (older AMBER numbering) that GROMACS's own `aminoacids.arn`
  does NOT rewrite at `pdb2gmx` read time. User reported
  `pdb2gmx -ff amber99sb-ildn` errors on dvbfixer output for
  many residues. Now handled by `apply_variants_to_pdb_text`:
  - **Methylene H shift** on all β/γ/δ/ε methylenes: `HB3 → HB1`
    (HB2 stays; result `{HB1, HB2}` matches GROMACS). Same for
    HG, HD, HE. Applied to every AA that has the corresponding
    methylene (LYS/ARG/PRO get all four; SER/CYS/etc get just
    HB; GLN/GLU/MET get β+γ; etc.).
  - **GLY α-methylene**: `HA3 → HA1`
  - **ILE γ-methylene**: `HG13 → HG11`
  - **LYN NZ H**: `HZ3 → HZ1` (already in 0.6.5, kept)
  - **ACE/NME cap H**: `HH31/HH32/HH33 → H1/H2/H3` (amber14→amber19/GROMACS)
  - **N-terminal residues**: `H → H1` on first residue of each
    protein chain (only if a bare H exists; skip if Modeller
    already placed H1/H2/H3 for a charged terminus).
  - **N-terminal proline (NPRO)**: `H3 → H1` on the ring N.
  - **C-terminal residues**: `O → OC2`, `OXT → OC1` on last
    residue of each protein chain. Applied atomically.
  - **CHARMM output**: universal backbone `H → HN` on every
    protein residue when `target_ff='charmm'`.
  - **DNA / RNA**: `H2' / H2'' → H2'1 / H2'2`, `H5' / H5'' →
    H5'1 / H5'2`, `HO'2 → HO2'` (RNA). Map exposed but
    end-to-end testing deferred pending column-perfect
    fixture handling.

  All renames are single-source (no shift-pair) so they're
  naturally idempotent — running `apply_variants_to_pdb_text`
  twice produces the same output.

### Renamed
- `apply_variants_to_pdb_text` parameter `include_gromacs_lyn` →
  `include_gromacs_shifts`. Old name kept as a deprecated alias
  for one release.

## [0.6.6] — 2026-07

### Added
- **`dvbfixer model --strip-heterogens`** — remove HETATM records
  (ligands, sugars, ions, cofactors) before Modeller runs. Off by
  default (Modeller usually benefits from heterogen context for
  loop refinement) but useful when heterogen geometry causes loop
  artifacts. Waters are preserved when `--keep-water` is also
  passed. Orphan CONECT records referencing dropped serials are
  filtered too.
- **zbs propagation**: when `dvbfixer zbs --strip-heterogens` is
  invoked, the flag is now forwarded to the model step (previously
  it was only forwarded to prepare and both minimize passes, so
  Modeller saw all heterogens even when the user had explicitly
  asked to strip them for the pipeline).

## [0.6.5] — 2026-07

### Fixed
- **AMBER protonation variants (GLH/ASH/HID/HIE/HIP/CYX/CYM)
  finally survive `dvbfixer zbs`.** User verified failure across
  0.6.3 and 0.6.4 with multiple fixtures (2VLP, 1TM7). Empirical
  test on OpenMM 8.5.1 showed `PDBFile` canonicalises variant
  residue names on both read AND write — the topology-level
  `_rename_variants_to_parent → addHydrogens → _restore_variants_in_topology`
  dance was a no-op because the "restore" walked a topology that
  only ever had canonical names.
  Fix: text-level rewrite of every user-visible output PDB using
  `amber_renames` (populated from the RAW input text via
  `scan_variant_names`, which OpenMM never sees). Verified on
  2VLP at pH 5: GLH=48, ASH=13, HIP=126 all in final output.
- **`dvbfixer zbs --rename` no longer destroys protonate's work.**
  The flag was being propagated to minimize step 2 (which runs
  AFTER protonate); canonicalising there threw away every AMBER
  variant PROPKA assigned. Removed the propagation — `--rename`
  now only applies to prepare + minimize step 1 (both run BEFORE
  protonate), where its "strip non-canonical names" behaviour is
  actually useful.

### Added
- **New shared FF-name module `dvbfixer.ffutils.ff_names`** —
  central place for AMBER↔CHARMM protonation-variant residue
  and atom-name maps + a text-level PDB rewrite primitive
  (`apply_variants_to_pdb_text`). Reused by `prepare`,
  `minimize`, `protonate`. `convert` (glycam.py) is unchanged;
  a future PR will migrate it to use the shared module too.

## [0.6.4] — 2026-07

Three bugs surfaced by a `dvbfixer zbs test/stereo_bug/1TM1.pdb
--no-solvent --strip-heterogens` reproduction.

### Fixed
- **GLH/ASH/HIE/HID/HIP/CYX STILL canonicalized after 0.6.3.**
  The 0.6.3 fix wired `amber_renames` into Branches 2 and 3 of
  minimize's `keep_h=True` path but missed **Branch 1** (the
  `if n_missing or n_terminals:` branch, which fires on virtually
  every real input). Branch 1 called `PDBFixer.addMissingHydrogens`
  — a hard-rule violation from CLAUDE.md, because PDBFixer's
  `_describeVariant` only recognises standard PDB names and
  rewrites variant residues to canonical HIS/ASP/GLU/CYS before
  placing H. Fixed by making Branch 1 follow the same
  `_rename → Modeller.addHydrogens(variants=...) → _restore`
  pattern as Branches 2/3.
- **`fix_ca_chirality` didn't run on inputs with all atoms
  present.** SER224 in 1TM1 came out as D-chirality after zbs.
  Root cause: `fix_ca_chirality` was gated by
  `if n_missing or n_terminals:` — if PDBFixer detected no missing
  atoms, chirality was never checked. Also: reflecting only CB
  (leaving OG/CG/etc on the wrong side) broke sidechain geometry.
  Fixed: `fix_ca_chirality` now reflects EVERY sidechain atom
  through the CA-N-C plane (not just CB), and runs unconditionally
  at the end of minimize before `createSystem`.
- **"1 C-O bond too many" createSystem failure.** Over-eager
  CONECT inference wired backbone amide H atoms to CA/HA/O
  simultaneously, exceeding hydrogen valence and making residue
  templates fail to match. Added
  `minimize.pipeline._drop_spurious_inter_aa_bonds` which:
  (1) drops non-peptide inter-residue bonds between two standard
  AAs, and (2) enforces H valence = 1 by dropping every second
  bond involving each H atom. Called after every `Modeller(...)`
  reconstruction and before every `createSystem`.

### Known limitation
`dvbfixer zbs --parametrize-ligands` on inputs with badly
corrupted CONECT records (like 1TM1) still fails downstream
because OpenMM's `Modeller.addHydrogens` hits a zero-division on
degenerate geometry after the H-valence filter reshapes the bond
graph. Investigation continues; use `--strip-heterogens` in the
meantime.

## [0.6.3] — 2026-07

### Fixed
- **zbs canonicalized all AMBER variants except LYN.** User reported
  that after `dvbfixer zbs`, output PDB had GLU (was GLH), ASP (was
  ASH), HIS (was HIE/HID/HIP), CYS (was CYX) — only LYN survived.
  Root cause: `minimize/pipeline.py:_rename_variants_to_parent`
  walked the topology, but OpenMM's intermediate
  `PDBFile.writeFile` normalizes HID/HIE/HIP/ASH/GLH/CYX/CYM to
  canonical names (LYN is the only variant OpenMM doesn't
  normalize). The `_saved` dict therefore captured only LYN, and
  the restore step only put LYN back. Fixed by making
  `_rename_variants_to_parent` consult `amber_renames` (the
  raw-text-derived variant dict populated by `_read_amber_renames`
  before any OpenMM parsing) as the ground truth.

### Changed
- **LYN output PDBs now use GROMACS-compatible `HZ1` + `HZ2`.** User
  reported that feeding dvbfixer's PDB into `pdb2gmx -ff amber99sb-ildn`
  failed on LYN residues because ff14SB's LYN template names its two
  NZ hydrogens `HZ2 + HZ3`, but GROMACS amber99sb-ildn's
  `aminoacids.hdb` H-add rule expects `HZ1 + HZ2`. Sub-agent survey
  (Jul 2026) confirmed LYN is the ONLY protein atom-name difference
  between ff14SB and GROMACS amber99sb-ildn for standard residues +
  HID/HIE/HIP/CYX/CYM/ASH/GLH/LYN. Added
  `ffutils.variants.rename_lyn_hz_for_gromacs` (topology-level) and
  `rename_lyn_hz_for_gromacs_in_pdb_text` (file-level) helpers.
  Wired into the final user-visible PDB write step of `prepare`,
  `minimize`, and `protonate` (both H-adding and text-rename paths).
  Intermediate temp writes remain ff14SB so OpenMM's `createSystem`
  still matches the LYN template.

## [0.6.2] — 2026-07

### Fixed
- **Cα chirality inversion on PDBFixer sidechain rebuild.** User
  reported `dvbfixer zbs` producing `B/VAL98:CA` as a D-amino acid
  (triple product (N×C)·CB = -0.0017 nm³). Root cause:
  `PDBFixer.addMissingAtoms()` rebuilds missing sidechain heavy
  atoms from ideal AMBER templates; on branched-Cβ residues
  (VAL/ILE/THR) the template alignment can pick the D face.
  Nothing in the pipeline detected this. Added
  `dvbfixer.ffutils.geometry.fix_ca_chirality` which reflects any
  D-configured CB through the CA-N-C plane. Wired into `prepare`
  and `minimize` immediately after `addMissingAtoms`. Diagnose
  now reports 0 chirality findings after zbs.

### Docs
- `docs/known-issues.md` — new sections documenting the PDBFixer
  chirality behaviour and the LYN hydrogen naming FF-vs-hydrogens.xml
  quirk (the latter is not a bug — ff14SB template ground truth is
  `HZ2 + HZ3`, dvbfixer output already matches).
- `ffutils.variants.fix_lyn_hz_naming` docstring polish making it
  explicit that ff14SB is authoritative.

## [0.6.1] — 2026-07

### Changed
- **`diagnose`: default clash overlap thresholds now match ChimeraX**
  (WARN 0.6 Å / ERROR 0.9 Å), not MolProbity (0.4 / 0.5 Å). User
  reported that BioLuminate and ChimeraX report no clashes on inputs
  where diagnose reported many — MolProbity's clashscore floor is a
  strict-validation setting, not a "does this look OK" setting.

### Added
- **`--clash-mode {chimerax,molprobity,bioluminate}`** preset flag.
  - `chimerax` — 0.6 / 0.9 Å (new default; matches ChimeraX `clashes`)
  - `molprobity` — 0.4 / 0.5 Å (restores pre-0.6.1 strict floor)
  - `bioluminate` — 0.75 / 1.0 Å (matches BioLuminate "Bad" / "Ugly")
- **`--clash-cutoff WARN,ERROR`** escape hatch for explicit tuning
  (overrides `--clash-mode`). E.g. `--clash-cutoff 0.35,0.45` for
  extra-strict validation.

## [0.6.0] — 2026-07

Follow-up on a cross-validated assessment (two independent agents: one
code-review, one functional test on real PDB fixtures). Addresses the
noisiest failure modes plus adds test coverage for previously
untested code paths.

### Added
- **Multi-MODEL detection.** Multi-model PDBs used to silently produce
  meaningless reports (chain breaks across MODEL boundaries, spurious
  valence violations from CONECT superposition). Now diagnose extracts
  MODEL 1 to a temp file, emits a WARNING banner, and reports on
  MODEL 1 only.
- **SEQRES-vs-ATOM check.** Terminal truncations (e.g. Fab His-tag in
  SEQRES but not resolved in ATOM) are now flagged as WARNING. PDBFixer's
  `findMissingResidues` only catches internal gaps.
- **Disulfide-geometry check.** SS bond length (2.05 ± 0.10 Å),
  Cα-Cα distance (5.5 – 7.0 Å), CB-SG-SG-CB dihedral (χ_ss = 60 – 120°)
  reported as `disulfide_geometry` findings.
- **`--format json` output.** Machine-readable findings + summary
  for CI gating and scripting.
- **`-v/--verbose` implementation.** Prints per-check-family timing
  and finding counts to stderr.

### Fixed
- **Waters no longer generate massive chain-break noise.** Every
  crystallographic water used to trigger a "chain break after HOH..."
  WARNING. Waters (HOH/WAT/SOL/TIP3/TIP4/TIP5/SPC/SPCE/DOD/H2O) are
  now excluded from chain-break AND steric checks by default. Add
  `--include-water` to keep the old behaviour.
- **Heavy-atom H-bonds no longer flagged as clashes.** Structures
  without explicit hydrogens (unprotonated inputs) had every salt
  bridge and backbone amide interaction reported as an ERROR clash
  ("LYS:NZ clashes with GLU:OE1 — overlap 0.4 Å"). Any pair of
  H-bond-capable heavy atoms (N/O/S/F ↔ N/O/S/F) at 2.5 – 3.4 Å is
  now skipped as a heavy-atom H-bond, matching CCP4's envelope.
- **Intra-residue vdW pairs skipped from clash detection.** Anything
  within the same residue is FF-template geometry — 1-4 exclusion
  already covered most cases, but glycan / non-standard-AA close
  contacts within a single residue no longer surface as clashes.

### Test coverage
Added 16 new tests covering previously-untested paths:
- Dihedral computation (trans-peptide → 180°, cis → 0°)
- Cα chirality (L-Ala pass, D-Ala flagged)
- Valence (5-bond C flagged, 4-bond OK)
- Bond length (canonical, sub-WARN stretched, above-ERROR stretched)
- Disulfide geometry (canonical, stretched, non-bonded pair)
- Multi-model input handling
- Water suppression (both directions of `--include-water`)
- JSON output format

## [0.5.2] — 2026-07

### Fixed
- **`diagnose`: hydrogen bonds no longer reported as clashes.** Every
  backbone N-H..O=C amide interaction, sidechain O-H..O, and
  ARG/LYS..carboxylate salt bridge in a well-folded structure showed
  up as an ERROR ("O clashes with H — overlap 0.7 Å"). MolProbity's
  ``probe`` handles these by classifying them as ``hbond`` contacts;
  our Python engine now applies the same filter — a pair is
  suppressed when one atom is a polar H (covalently bonded to N/O/S),
  the other is an acceptor (N/O/S/F), and their distance falls in
  the 1.4 – 2.6 Å H-bond envelope. Fixes the "α-helix reported as
  15 ERRORs" complaint on 0.5.1.

## [0.5.1] — 2026-07

### Fixed
- **`diagnose`: bond exclusion now covers HETATMs and non-standard
  residues.** `steric._build_bond_exclusion` previously used only
  `topology.bonds()`, which is empty for every glycan, ligand,
  AMBER protonation variant (HIE / CYX / LYN / ASH / GLH), and
  CHARMM variant (HSD / HSE / HSP) that OpenMM's PDBFile can't
  match to a standard template. Their real covalent bonds were
  reported as ERROR clashes (bonded C-C at 1.53 Å read as 1.87 Å
  overlap). Fixed by augmenting the topology bond set with a
  distance-inferred graph (heavy-heavy ≤ 1.9 Å, X-H ≤ 1.3 Å,
  S-S ≤ 2.25 Å) built from the same cKDTree used for clash search.

### Changed
- **`diagnose`: thresholds recalibrated for lower false-positive
  rate.** Matches BioLuminate's Protein Report and MolProbity's
  official clashscore floor.
  - Bond-length WARNING at 20 % deviation (was 10 %); ERROR at 50 %
    (was 30 %). The SER HG-on-OXT bug case sits at 75 %, so genuine
    breakage is still caught.
  - Steric clash WARNING at 0.4 Å overlap (was 0.2 Å) — matches
    MolProbity's official clashscore threshold. ERROR unchanged at
    0.5 Å.

## [0.5.0] — 2026-07

### Added
- **`dvbfixer diagnose`** — new standalone subcommand. Inspects a PDB
  file and emits a plain-text per-residue findings report; **never
  mutates the input**. Inspired by BioLuminate's Protein Report
  widget and MolProbity's all-atom validation. Three check families:
  - **Structural integrity** — missing atoms / residues / terminals
    (via PDBFixer), coincident atoms + misplaced hydrogens (reusing
    the 0.4.1 / 0.4.2 detection extracted into shared
    `ffutils.geometry.detect_coincident_atoms` +
    `detect_misplaced_hydrogens`), altLoc conflicts, chain breaks,
    insertion codes.
  - **Chemistry / bond geometry** — valence violations (reusing
    `pull.MAX_BONDS`), bond-length outliers (atom-name-aware canonical
    table distinguishes backbone C=O 1.23 Å from sidechain C-O
    1.43 Å, backbone C-N 1.33 Å from sidechain C-N 1.47 Å), cis
    peptides (INFO for cis-PRO, WARNING elsewhere), non-planar
    amides, Cα chirality via triple-product sign check.
  - **Steric analysis** — all-atom clash detection. Python engine
    (scipy cKDTree + MolProbity-standard vdW radii; excludes 1-2,
    1-3, and 1-4 bonded pairs) by default; shells to MolProbity's
    `probe` binary if it's on PATH. WARNING for ≥ 0.2 Å overlap,
    ERROR for ≥ 0.5 Å.
  - 3-tier ERROR / WARNING / INFO classification; exit-code convention
    (0 clean, 1 has ERROR, 2 I/O error) makes it usable in shell
    gates: `dvbfixer diagnose input.pdb --severity ERROR && dvbfixer prepare …`.
  - `--only {all,structural,chemistry,steric}` restricts categories;
    `--severity` filters minimum severity; `-o` writes report to file.
  - Documentation at `docs/commands/diagnose.md`; auto-generated
    reference at `docs/reference/diagnose.md`.

### Refactor
- **`ffutils.geometry`** — extracted `detect_misplaced_hydrogens` and
  `detect_coincident_atoms` as pure detection helpers (return findings
  as new `MisplacedHydrogen` / `CoincidentAtoms` dataclasses).
  `repair_misplaced_hydrogens` now composes `detect + place`, and
  `prepare.pipeline`'s pre-strip and the new `diagnose.structural`
  share the same detection code.

## [0.4.2] — 2026-07

### Fixed
- **`prepare` / `protonate` / `minimize`** — post-`addHydrogens` geometry
  sanity check. The 0.4.1 pre-strip only caught inputs where the (H,
  heavy-atom) pair was already coincident. The real failure mode — HG
  MISSING and OXT PRESENT on a C-terminal SER — bypassed it because the
  input had no coincident pair to detect; OpenMM's `Modeller.addHydrogens`
  then placed the newly-added HG right on top of the existing OXT via
  its CSER template path. dvbfixer now runs
  `dvbfixer.ffutils.geometry.repair_misplaced_hydrogens` immediately after
  every `addHydrogens` invocation across `prepare`, `protonate`, and
  `minimize`. The helper walks every hydrogen, verifies distance to its
  bonded heavy-atom parent, and repairs any H that landed > 1.5 Å from
  its parent OR within 0.5 Å of another atom in the same residue by
  re-placing it in linear-anti direction at the canonical O-H / N-H /
  C-H bond length. Verified on the reported reproducer: `HG` moves from
  0.001 Å apart from `OXT` (broken) to 0.97 Å from `OG` (canonical).

### Added
- `src/dvbfixer/ffutils/geometry.py` — new module hosting
  `repair_misplaced_hydrogens(topology, positions, verbose=False)`.

## [0.4.1] — 2026-07

### Fixed
- **`prepare`** — coincident-atom detection before hydrogen strip. When
  an input file placed a hydrogen at exactly another atom's position
  (reported against `test/broken_SER/SER.pdb`: SER 126's `HG` sitting
  0.001 Å from `OXT`), `Modeller.addHydrogens` was re-placing `HG` at
  the same coincident position, leaving it 1.7 Å from its own `OG`
  after prepare — a broken sp3 hydroxyl geometry that then corrupted
  the downstream `zbs` protonate step. Prepare now scans every protein
  residue for `(H, heavy_atom)` pairs within 0.5 Å and, when found,
  strips BOTH atoms so PDBFixer's `addMissingAtoms` re-adds the heavy
  atom in its correct position (typically the OXT terminal-atom slot)
  and `addHydrogens` places `H` without the interfering coincident
  atom. Verified by a new regression test at
  `tests/test_prepare_broken_geom.py` that runs on the reported fixture.

## [0.4.0] — 2026-07

### Refactor
- **Guardrails (Phase 0)** — added `tests/` with pytest scaffolding,
  22 seed regression tests for the lightweight subcommands, `[tool.ruff]`
  / `[tool.mypy]` / `[tool.pytest.ini_options]` in `pyproject.toml`,
  `.github/workflows/ci.yml` (fast + full lanes), and a mechanical
  `ruff --fix` pass across `src/dvbfixer/`.
- **Dedup shared helpers (Phase 1)**:
  - `ffutils/variants.py` — consolidates AMBER/CHARMM variant capture,
    text-level rename, and post-`addHydrogens` restore that
    prepare/minimize/protonate/transplant each re-implemented.
  - `ffutils/dat.py` — `DatRecord` dataclass codifying the pipeline's
    `.dat` schema (added_atoms, variant_overrides, removed_residues,
    residue_summary, templates, target_chains). `total_added` is
    derived on save. Six modules were hand-rolling `json.load` /
    `json.dump`; all now go through this.
  - `ffutils.build_glycam_system` — one-call wrapper for the
    `create_forcefield_with_openff` + `loadHydrogenDefinitions` +
    `add_glycam_bonds` ritual.
  - `pdbutils/` split into `inference.py` (OpenBabel-based CONECT
    perception + domain overrides) and `io.py` (line-level serial
    remap / append-before-end helpers).
- **God-module splits (Phase 2)** — `minimize`, `model`, `prepare`,
  `top` converted from flat modules to packages. The follow-up wave
  after the initial argparse extraction cleaned the rest along the
  boundaries the plan called out:
  - `minimize/` → `cli.py` / `pipeline.py` / `refine.py`.
  - `model/` → `cli.py` / `pipeline.py` / `renumber.py` (the
    three-tier residue-numbering strategy) / `modeller_run.py`
    (`_PinnedLoopModel` + `run_modeller` + PIR helpers +
    `_fix_terminal_alignment` + `_explain_modeller_error`).
  - `prepare/` → `cli.py` / `pipeline.py` / `mutations.py`
    (`parse_mutations` + `apply_deletions_to_pdb_text` + SSBOND
    repair + glycan-walk BFS) / `glycan.py` (glycosylation detection,
    NLN/OLS/OLT rename, RDKit/OpenBabel heterogen-H).
  - `top/` → `cli.py` / `pipeline.py` / `ff_data.py` (data-only
    constants: PDB_TO_*, ION_PARAMS, `_GLYCAN_LINKAGE_PARAMS`) /
    `writers.py` (moleculetype/PDB/posre + FF-content splicing).
    Remaining `TopologyBuilder` + `--acpype` extractions
    documented as follow-ups in the package `__init__.py`.
- **Types + hardening (Phase 3)** — annotated the API-surface modules
  (`cli.py`, `ffutils/`, `pdbutils/`, `align.py`); flipped mypy CI
  gate from advisory to required for those paths.
- **Documentation (Phase 4)**:
  - `scripts/gen_cli_reference.py` generates `docs/reference/{cmd}.md`
    from each subcommand's `parse_args()`. CI runs
    `gen_cli_reference.py --check` on the full lane so committed
    reference pages never drift from the actual `--help`.
  - `CLAUDE.md` shrunk from ~85 KB to ~3.6 KB (pure index of the
    docs tree + hard rules). Historical design notes moved verbatim
    to `docs/DESIGN_NOTES.md`, then split into their targeted homes:
    the 4 architecture-adjacent Notes sections went to
    `ARCHITECTURE.md`; the 17 per-subcommand "algorithm" sections
    went to `docs/commands/{cmd}.md` under a `## How it works`
    heading. `DESIGN_NOTES.md` now a ~20-line stub pointer.
  - `CHANGELOG.md` (this file) created and backfilled.

## [0.3.0] — 2026-07

### Added
- **`protonate`** — FF-aware output naming: renames AMBER protonation
  variants to CHARMM equivalents (HID → HSD, HIE → HSE, HIP → HSP,
  CYX → CYS via SSBOND, CYM → CYM) when `--ff charmm` is resolved.
  ASH/GLH/LYN fall back to standard names with a warning (no CHARMM XML
  templates).
- **`protonate`** — `--protassign` (default ON) wraps MolProbity Reduce
  for HIS tautomer picking and ASN/GLN side-chain flip detection.
- **`model`** — fast Python-only no-gap pre-check: string-compares
  ATOM-derived sequence against SEQRES per chain; on match, skips
  Modeller entirely (~2 min → ~0.25 s on gap-free TCR/MHC inputs).
- **`model`** — `--pin-input` (default ON) freezes flankers during
  Modeller's loop-refinement MD via `_PinnedLoopModel` subclass. The
  initial automodel CG still runs on all atoms.
- **`model`** — `--num-output N` saves the top-N ranked candidates by
  molpdf; filenames get `_N` suffix.
- **`minimize`** — `--parametrize-ligands`: on-the-fly GAFF2 + AM1-BCC
  template generation for unknown ligands via antechamber /
  `GAFFTemplateGenerator`. Cached to `~/.cache/dvbfixer/lig_params/`
  (override with `$DVBFIXER_LIG_CACHE`).
- **`zbs`** — `--align-to-input` (default ON): line-level Kabsch
  rewrite after each pipeline step keeps interim outputs in the
  original input's Cartesian frame. Preserves SEQRES / CONECT / all
  non-ATOM records.

### Changed
- **`glycam`** subcommand renamed to **`convert`**, with a
  deprecation-warning alias. Now supports `--to-charmm` in addition
  to the default `--to-amber`; also renames AMBER↔CHARMM protonation
  variants and stale protonation H atoms.
- **`ffutils`** — new `--ff` short-name aliases (`auto`, `amber`,
  `amber+glycam`, `charmm`, ...) accepted by every OpenMM-using tool.
  Auto-detect scans for CHARMM protonation names, GLYCAM sugar codes,
  and CHARMM-GUI 4-char sugars; ambiguous PDB sugar names emit a
  "convert first" warning.
- **`prepare`** — heterogen hydrogen addition switched from the broken
  SMIRNOFF path to real AMBER14+GLYCAM_06j-1 templates via
  `ffutils.create_forcefield_with_openff`. SMIRNOFF failed on
  cross-residue glycosidic bonds.
- **`minimize`** — default is now full-system minimization (protein +
  glycans + ligands). Legacy strip-and-splice behaviour available via
  `--strip-heterogens`; auto-fallback when GLYCAM parametrization
  fails on PDB-named sugars.
- **`top`** — `--water` now drives ion LJ parameter selection via
  new `--ion-set` flag. TIP3P → Joung-Cheatham; SPC-E → JC-SPCE;
  TIP4P-Ew → JC-TIP4P-Ew; OPC → Li-Merz HFE. Prevents the pre-flag
  bug where OPC water + Dang Cl⁻ ions crashed LINCS in ~8 ps.
- **`zbs`** — reduced from 7 to 6 steps; the two `protonate
  --no-hydrogens` calls were replaced by one full `protonate` between
  the minimize passes.

### Fixed
- **`protonate`** — text-level pre-rename of AMBER/CHARMM variants to
  standard parents before OpenMM parses. Fixes the LYN-blocks-
  peptide-bond crash where a mid-chain LYN would cause `addHydrogens`
  to fail on the PREVIOUS residue with "missing 1 externally bonded
  C atom".
- **`model`** — three-tier deterministic residue-number strategy
  (K-finder → Needleman-Wunsch → align2d mask). Fixes FcgRI chain A
  regression where 5 modeled residues at 219-223 ended up numbered
  283-287. HETATM resseqs are preserved verbatim.
- **`model`** — N-terminal gaps extend BACKWARD from the first
  template residue instead of starting at 1.
- **`model`** — `_reorder_chains_for_modeller` groups each chain ID
  into one contiguous block, fixing silent NAG drops (3ry6 chain C)
  and BLK alignment crashes (FcgRI).

## [0.2.0] and earlier

Historical, best-effort roll-up of the pre-0.3.0 milestones. Consult
git log for exact commit provenance.

### Added
- **`transplant`** — Kabsch-aligned graft of GLYCAM-Web output into
  an acceptor PDB; `--relax` runs AMBER14+GLYCAM minimization;
  `--gromacs` exports via ACPYPE with `[ pairs_nb ]` for mixed 1-4
  scaling.
- **`top`** — RTP-based GROMACS topology generation (AMBER99SB-ILDN
  + CHARMM36) with modular `.itp` output; `--acpype` alternative
  mode via OpenMM → ParmEd → ACPYPE for the mixed 1-4 case.
- **`top`** — glycan and glycolipid support (CHARMM36) with distance-
  based glycosidic-bond detection, charge redistribution, and
  ceramide-sugar linkage parameters.
- **`parametrize`** — GAFF2 small-molecule pipeline (antechamber →
  parmchk2 → tleap → ParmEd) with AM1-BCC default. RESP available
  via `--qm-engine gaussian` (existing two-step flow),
  `--qm-engine psi4` (free, subprocess to a separate conda env), or
  `--qm-engine pyscf` (recommended, pure-Python in the main env).
- **`homology`** — multi-template Modeller with automatic chain
  mapping; `--antibody` mode uses ANARCI for Kabat / IMGT numbering
  and CDR detection.
- **`cluster`** — glycan conformational clustering from MD
  trajectories via glycosidic-torsion RMSD (GFDB method); global vs
  per-linkage modes; interactive Plotly output.
- **`renumber`** — antibody scheme support (Kabat / Chothia / IMGT /
  Martin / Aho / EU) via ANARCI for V-domains + bundled human IgG1 /
  Cκ / Cλ EU references for C-domains.
- **`prepare`** — `--mutate` with substitution (`A:39:CYX`) and
  deletion (`A:39:del`) support, including glycan-walk BFS and
  disulfide-partner repair.
- **`conect`** — standalone subcommand + shared inference engine
  auto-called by prepare / top / minimize / transplant / convert.
- **`puppet`** — strip PDB to backbone-only polyglycine (with
  `--keep` for residues to preserve intact).
- **`split`** — multi-MODEL detection: preserves per-MODEL chain-ID
  consistency instead of cascading letters (A B C / D E F / …).

### Environment
- Migrated from separate CLI scripts to a single `dvbfixer` command
  with subcommand dispatch (`dvbfixer.cli`).
- Bundled AMBER99SB-ILDN and CHARMM36 force-field directories in
  `FF/` for RTP parsing; no external GROMACS FF dir needed at
  runtime.
- Added optional runtime deps: `plotly` (cluster), `hmmer` + `anarci`
  (antibody modes), `xtb` + `openbabel` (minimize refinement), and
  `pyscf` (parametrize RESP).
