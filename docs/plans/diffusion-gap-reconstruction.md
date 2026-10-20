# Diffusion Gap-Reconstruction Implementation Plan

**Status synchronized 2026-10-20:** the backend-neutral core, bounded experimental
CLI, batch/ZBS/GUI custody and mosaic-first Homology paths are implemented. Public
cc89 CUDA and versioned corrected Apple each pass 5/5 integration; historical MPS
remains separate. Protenix is locked and has public GPU workflow smokes, but its
full production-wrapper cohort/final OCI acceptance is still open. Larger scientific
cohorts, paused validation-policy refinements and a production/default decision
are not implied by software delivery. See the [current plan index](README.md) and
[canonical checklist](implementation-checklist.md). Older phase/task boxes retain
their original scope and must not be used alone as a present-day backlog.

- Status: Phase 4 implementation-ready for the narrow experimental scope.
- Branch: `diffusion`.
- Scope owner: Structure Preparation bounded context.
- Change group: `missing-atom-rebuild-chirality`.
- Coordination rule: assign one exclusive coordinating owner before implementation.
- Related research:
  - [`../research/reconstruction-and-modeling-backends.md`](../research/reconstruction-and-modeling-backends.md)
  - [`../research/diffusion-confirmatory-results.md`](../research/diffusion-confirmatory-results.md)
- Expansion implementation plan:
  - [`linux-diffusion-expansion.md`](linux-diffusion-expansion.md)
- Production baselines retained:
  - Salilab MODELLER for `model` and `homology`.
  - PDBFixer/OpenMM Modeller in the documented legacy preparation path.
  - `tleap-reduce` for its documented pure-protein preparation scope.

## Goals

- [x] Add an internal experimental, backend-neutral diffusion protocol path for sequence-guided protein gap reconstruction; no public engine backend is claimed.
- [x] Preserve deposited coordinates outside explicitly generated or movable regions through exact identity and fixed-heavy coordinate gates.
- [x] Implement the PATCHR-like method independently rather than importing, wrapping, vendoring, or copying PATCHR. The maintained Protenix v1 patch now integrates synchronization and exact reinjection after every real sampler update; PATCHR remains comparator-only.
- [x] Keep ML frameworks, CUDA libraries, and model-specific packages out of the core DVBFixer environment.
- [x] Record enough available provenance to reproduce or audit every generated candidate without inventing missing engine evidence.
- [x] Validate identity, connectivity, supported geometry, chirality, and clashes before publishing a candidate.
- [ ] Evaluate mosaic-first diffusion for comparative/homology modeling only after local gap reconstruction passes its acceptance gates.

## Non-goals

- [x] Do not replace or deprecate MODELLER in this work.
- [x] Do not change the default `model` or `homology` backend during the research phases.
- [x] Do not add automatic fallback from diffusion to MODELLER.
- [x] Do not use full-chain prediction as a substitute for fixed-coordinate gap repair.
- [x] Do not treat missing heavy atoms inside an otherwise present residue as the same problem as missing whole residues.
- [x] Do not move CIF parsing into the scientific modeling stage.
- [x] Do not claim support for ligands, glycans, PTMs, cofactors, metals, or covalent non-peptide links until each class has separate evidence.
- [x] Do not store model weights in Git.

## Initial Supported Slice

- [x] Accept canonical L-protein inputs only at the internal scope boundary.
- [x] Require a complete, known target sequence in the request; FASTA/SEQRES extraction remains owned by the existing CLI/model boundary.
- [x] Require unambiguous shared sequence placement.
- [x] Support internal gaps with two observed anchors.
- [x] Start with gap lengths of 3-12 residues.
- [x] Reject terminal one-anchor gaps in the first slice.
- [x] Reject alternate-location ambiguity in or adjacent to the generated region.
- [x] Reject multiple `MODEL` blocks in the first slice.
- [x] Reject retained unsupported heterogens or external covalent links near the generated region.
- [x] Return an explicit `unsupported` result without creating a public PDB for every out-of-scope case. The internal pipeline returns a typed unsupported outcome before runner launch and publication tests prove no destination bundle or staging orphan is created.

## Mandatory Identity And Publication Rules

- [x] Preserve case-sensitive chain IDs.
- [x] Preserve residue insertion codes.
- [x] Use `(chain, resid, icode, atom)` as atom identity.
- [x] Use `(chain, resid, icode)` as residue identity.
- [x] Preserve all atoms and explicit links outside the generated mask.
- [x] Preserve `keepIds=True` on every OpenMM `PDBFile.writeFile` call. The diffusion core does not currently serialize through `PDBFile.writeFile`; the repository-wide rule remains unchanged.
- [x] Normalize CIF input only at the CLI boundary. The diffusion core accepts only normalized PDB bytes and adds no CIF reader.
- [x] Use `dvbfixer.ffutils.dat.DatRecord` for the downstream `.dat` sidecar.
- [x] Publish a candidate only after every hard validation gate passes.
- [x] Write candidate PDB, `.dat`, diffusion provenance, and a bundle index atomically as one logical result through one directory rename.
- [x] Leave no partial public output after runner, parsing, validation, or publication failure.

## Engine And License Decisions

### RFdiffusion v1 Baseline

- [x] Select RFdiffusion v1 as the first external backbone-inpainting benchmark adapter. The internal adapter is implemented and GPU-smoked; it remains outside public dispatch.
- [x] Pin source revision `bf42b54c20a99dd7350456c85985ed4d83b95d48` in the research inventory.
- [x] Pin the exact checkpoint to independently measured SHA-256 `0fcf7d7c32b4848030aca3a051e6768de194616f96ba6c38186351a33bfc6eca`. Upstream still provides no signed checksum manifest, so publisher-authenticated supply-chain verification remains unavailable.
- [x] Archive BSD-3-Clause evidence for code and upstream license commit `820bfdfaded8c260b962dc40a3171eae316b6ce0`, which explicitly covers README-linked weights. A final redistribution review remains required before embedding weights in a service image.
- [x] Treat any future RFdiffusion output as a backbone-level benchmark until side-chain materialization and all-heavy-atom validation are complete.
- [x] Do not expose raw RFdiffusion output as a production DVBFixer repair result.

### All-Atom Feasibility Spike

- [x] Evaluate Protenix v1 first; revision `85767b811c40ed46e73a9b39519cf6bfca8701ba` exposes no maintainable external per-step callback, so it cannot satisfy reinjection without an upstream API change or maintained fork.
  - [x] Pin the audited v1 source revision and record the upstream Apache-2.0 code/model-parameter claim; redistribution review is still required.
  - [x] Do not substitute Protenix v2 without a new license review.
  - [x] Verify whether the denoising state can be intercepted before every next step. It is mutable only inside `sample_diffusion`; no supported external callback is exposed.
- [x] Evaluate Boltz-2 because the unmodified pinned revision `b1ebfc46ecf57f5414e0d1a6f9027bbb122c53bc` has the same hook blocker in both Boltz-2 and legacy sampler loops; a minimal maintained Boltz-2 patch now passes CPU/A100 synthetic callback smokes, while checkpoint-backed gap identity mapping remains open.
  - [x] Pin the audited MIT source revision and record the upstream code/weight claim; exact weight revision, URL, hash, and redistribution review remain unresolved.
  - [x] Treat ordinary template conditioning as insufficient for exact fixed-coordinate preservation.
  - [x] Verify whether fixed-coordinate reinjection can be implemented without an unmaintainable upstream fork. It cannot at either pinned revision: steering/projection changes the denoised estimate before the sampler computes its next state, and neither sampler exposes a post-update callback.
- [x] Add a backend-neutral conformance record that refuses to claim reinjection unless mutable state, stable identity mapping, and exact fixed-coordinate overwrite are exposed at every denoising step.
- [x] Stop before user-facing integration if neither pinned engine provides stable denoising hooks.
- [x] Record whether a maintained fork, upstream API change, or different sampler would be required after the hook spikes run. Minimal maintained Protenix v1 and Boltz-2 patches are recorded; Protenix has checkpoint-backed gap evidence, while Boltz has hook and base-model evidence only. Unmodified samplers remain unsupported. See [the hook-spike evidence](../research/all-atom-sampler-hook-spike.md).

### PATCHR Comparator

- [x] Use PATCHR only as an external scientific comparator.
- [x] Do not import PATCHR into DVBFixer.
- [x] Do not vendor PATCHR source.
- [x] Do not wrap the PATCHR CLI as the DVBFixer implementation.
- [x] Require a separate ADR before changing this repository policy.

### Excluded Distribution Candidates

- [x] Exclude FrameDiPT from the distributable backend because of CC BY-NC-SA terms.
- [x] Exclude Chroma parameters from the distributable backend because of non-commercial parameter terms and API-key distribution.
- [x] Exclude RFdiffusion2 until official checkpoint rights and optional Chai dependencies are unambiguous.
- [x] Exclude engines with unclear checkpoint redistribution rights from the shipped adapter list.
- [x] Keep unconditional-generation or motif-scaffolding engines as research comparators unless they demonstrate the required two-anchor repair contract.

### Per-Artifact License Inventory

- [x] Record code repository and revision.
- [x] Record source-code license and exact license-text revision.
- [x] Record checkpoint URL and independently measured SHA-256; retain the absence of a publisher-signed checksum as explicit provenance.
- [ ] Record checkpoint license and redistribution decision. Upstream claims and unresolved review status are recorded; no engine is approved for distribution.
- [ ] Record auxiliary model and cache URLs, hashes, and licenses. Required auxiliary artifacts remain unresolved.
- [ ] Record container base-image and package-lock provenance. Required digests and lock hashes remain unresolved.
- [x] Record relevant training-data cutoff claims for leakage analysis, including unresolved sequence-level membership.

## Backend-Neutral Contract

- [x] Add `src/dvbfixer/model/diffusion/contract.py`.
- [x] Define typed `AtomIdentity` and `ResidueIdentity` values.
- [x] Define a `GapRegion` with:
  - [x] target-chain identity;
  - [x] target-sequence interval;
  - [x] left and right anchors;
  - [x] generated residues;
  - [x] movable junction window.
- [x] Define a versioned `DiffusionRequest` with:
  - [x] normalized PDB input;
  - [x] target sequences;
  - [x] shared sequence placement;
  - [x] explicit gap ranges;
  - [x] fixed and generated atom masks;
  - [x] retained explicit links;
  - [x] candidate count;
  - [x] seed list;
  - [x] backend options.
- [x] Define a `DiffusionCandidate` with:
  - [x] candidate coordinate artifact;
  - [x] generated atom and residue identities;
  - [x] raw backend score;
  - [x] score provenance;
  - [x] warnings.
- [x] Define a `DiffusionResult` with:
  - [x] `success`, `unsupported`, or `failed` status;
  - [x] candidates;
  - [x] validation summaries;
  - [x] runner diagnostics;
  - [x] backend provenance.
- [x] Add strict JSON serialization and schema-version validation.
- [x] Reject unknown or incompatible schema versions explicitly.

## Mask And Sequence Placement Layer

- [x] Add `src/dvbfixer/model/diffusion/masks.py`.
- [x] Reuse the existing shared sequence-placement behavior instead of implementing a second alignment policy.
- [x] Construct fixed/generated masks from the authoritative alignment.
- [x] Preserve insertion-code-aware residue identity.
- [x] Preserve case-distinct chains such as `D` and `d`.
- [x] Define deterministic left and right anchor windows.
- [x] Define a separately bounded movable junction window.
- [x] Reject ambiguous placements instead of selecting a scientifically silent alternative.
- [x] Reject one-anchor and no-anchor regions in the initial slice.

## External Runner Boundary

- [x] Add `src/dvbfixer/model/diffusion/runner.py`.
- [x] Use a versioned subprocess protocol:
  - [x] DVBFixer writes `request.json` into a dedicated private workspace; this
    directory boundary is not an OS/filesystem sandbox for the trusted runner.
  - [x] The external runner writes a raw `RunnerResult` in `result.json` plus candidate artifacts; independent `DiffusionResult` validation summaries remain DVBFixer-owned.
  - [x] DVBFixer validates every returned path and digest.
- [x] Enforce workspace path containment for returned artifacts. Maintained
  wrappers promise not to write elsewhere, but core cannot enforce that promise.
- [x] Reject symlink and path-traversal escapes.
- [x] Bound runtime and captured output.
- [x] Capture exit code, stdout, and stderr without leaking credentials.
- [x] Treat malformed or missing result manifests as failures.
- [x] Add typed, CPU-testable local preflight results for missing runner, immutable image identity, local checkpoint, checkpoint digest mismatch, CUDA device, and incompatible protocol version. Engine-specific launchers still must supply real image/device discovery in Phase 2.
- [x] Add a deterministic fake CPU runner for unit and integration tests.
- [x] Keep runner-specific Python packages outside the core DVBFixer dependency set.

## PATCHR-Like Constrained Sampling

- [ ] Build the complete target topology before sampling.
- [x] Separate fixed observed atoms from generated missing-region atoms in the backend-neutral request/mask contract.
- [ ] Initialize or sample only the generated region.
- [ ] After every denoising update:
  - [x] provide a CPU-tested weighted Kabsch synchronization primitive from reliable fixed anchors;
  - [x] provide a CPU-tested generated-frame synchronization primitive;
  - [x] provide a CPU-tested exact fixed-coordinate overwrite primitive;
  - [x] verify atom identity equality in the synchronization/reinjection primitive;
  - [x] integrate all four operations inside every update of a pinned real sampler.
- [x] Run a localized post-sampling OpenMM pass around both peptide junctions for the RFdiffusion baseline; a real-sampler second diffusion pass remains pending.
- [x] Keep atoms outside the generated residue set fixed during the localized pass. Fixed request atoms take precedence over the broader movable-junction support window.
- [x] Materialize all expected canonical heavy atoms in generated residues for the RFdiffusion baseline.
- [x] Leave hydrogen placement and protonation to the downstream preparation stage contract.
- [x] Define three explicit ablation modes and their required capability evidence:
  - [x] template conditioning only;
  - [x] template conditioning plus per-step reinjection;
  - [x] reinjection plus local boundary refinement.
- [x] Execute those ablations with a pinned real sampler for the initial 7X35 case; broader corpus evidence remains pending.

## Independent Validation And Ranking

- [x] Add `src/dvbfixer/model/diffusion/validate.py`.
- [x] Compare atom and residue identities outside the generated mask exactly.
- [x] Compare explicit links outside and across the generated region.
- [x] Measure fixed-heavy-atom RMSD and maximum displacement.
- [x] Validate peptide connectivity at both junctions.
- [ ] Validate generated bond lengths, angles, planarity, and atom completeness. Canonical heavy-atom completeness, generated C-N break gates, severe local bond-length outliers, broad canonical backbone/peptide-angle gates, and peptide-amide planarity are implemented through shared diagnose policies; finer residue-specific side-chain geometry remains pending.
- [x] Validate severe intra-region and region-context clashes.
- [ ] Validate Ramachandran and rotamer quality. Gross general-residue Ramachandran outliers are rejected through the bundled MDAnalysis Lovell-reference 99% contour, and gross pooled χ1/χ2 outliers are rejected through the bundled Janin 98% contour with conservative periodic neighborhoods; GLY/PRO/pre-PRO Ramachandran, χ1-only residues, χ3-χ5, and residue/backbone-dependent full rotamer quality remain pending.
- [ ] Run `fix_ca_chirality` only as an explicitly recorded repair step. Validation currently rejects D geometry and performs no silent repair.
- [x] Run `assert_all_l` after the final heavy-atom coordinate change.
- [x] Reject any candidate that fails a hard gate.
- [x] Rank only passing candidates.
- [x] Keep backend confidence, closure metrics, geometry metrics, and physical energies as separately named score components. First-slice ranking keeps DVBFixer geometry metrics separate and does not use raw backend confidence as a shared-scale metric.
- [x] Do not compare backend confidence directly with MODELLER `molpdf` as though they share a scale.

## Provenance Manifest

- [x] Write `<stem>.diffusion.json` beside each published diffusion candidate inside its committed result bundle.
- [x] Include a manifest schema version.
- [x] Record DVBFixer version and commit, using explicit `unknown` outside a verifiable Git checkout.
- [x] Record runner protocol version.
- [x] Record engine repository and revision.
- [x] Record optional container digest or environment-lock identity/hash without inventing absent values.
- [x] Record optional checkpoint hash and source/checkpoint license identifiers without inventing absent values; auxiliary-artifact inventory remains adapter-specific.
- [x] Record request hash, target sequence, gap masks, and fixed/generated identity sets.
- [x] Record seed and optional device, precision, framework, CUDA, driver, and deterministic flags.
- [x] Record known nondeterministic kernels or operations when supplied by the runner.
- [x] Record raw score and score provenance.
- [x] Record every validation metric and pass/fail decision.
- [x] Record final PDB and `.dat` SHA-256 values.
- [x] Keep diffusion environment metadata out of `DatRecord` unless a later general sidecar decision explicitly changes that contract.

## Atomic Publication

- [x] Add `src/dvbfixer/model/diffusion/pipeline.py`.
- [x] Generate and validate candidates entirely inside a temporary workspace.
- [x] Select the ranked passing candidates before touching public destinations.
- [x] Build candidate-matched `.dat` records through `DatRecord`.
- [x] Stage PDB, `.dat`, provenance manifest, and bundle index in a hidden same-parent directory.
- [x] Commit the complete candidate artifact set atomically with one no-replace directory rename; a destination created concurrently is preserved and publication fails closed.
- [x] Remove staged or post-rename artifacts after any failed commit/durability step.
- [x] Preserve the source input on every failure path.

## Implementation Phases

### Phase 0: Policy, Corpus, And Thresholds

- [x] Update the research note with engine, licensing, and hardware findings.
- [x] Add or update the DDD implementation task without presenting the backend as shipped.
- [x] Accept an ADR covering:
  - [x] trusted subprocess protocol boundary and deployment-supplied container
    isolation when enforcement is required;
  - [x] separate diffusion provenance;
  - [x] no automatic scientific fallback;
  - [x] MODELLER remaining the default;
  - [x] independent PATCHR-like implementation.
- [x] Select reviewed benchmark fixtures.
- [x] Record fixture provenance and checksums.
- [x] Record exact masks and expected supported/unsupported classification.
- [x] Record upstream training cutoffs and sequence-identity leakage metadata where available.
- [x] Freeze numerical thresholds before comparative inference runs.

### Phase 1: CPU-Testable Core

- [x] Implement the versioned request/result contract.
- [x] Implement deterministic mask construction.
- [x] Implement weighted Kabsch and coordinate-reinjection primitives.
- [x] Implement the isolated runner protocol.
- [x] Implement the deterministic fake runner.
- [x] Implement independent validation and ranking for the accepted initial hard gates. Finer residue-specific geometry, GLY/PRO/pre-PRO Ramachandran, χ1-only and χ3-χ5 torsions, and residue/backbone-dependent full rotamer validation remain explicitly outside the current claim.
- [x] Implement atomic publication.
- [x] Implement separate provenance manifests.
- [x] Keep public CLI behavior unchanged through the runner slice.
- [x] Keep MODELLER execution unchanged through the runner slice.

### Phase 2: RFdiffusion v1 GPU Baseline

- [x] Build a pinned native Linux/NVIDIA runner environment for the first benchmark host; immutable service-container packaging remains separate.
- [x] Add checksum-verified checkpoint acquisition instructions.
- [x] Map the supported one-chain/one-gap `DiffusionRequest` slice to RFdiffusion contig/inpainting inputs.
- [x] Map generated coordinates back to stable DVBFixer identities through target-sequence ordinals.
- [x] Materialize canonical side chains through the explicitly recorded PDBFixer pure-protein route.
- [x] Re-run all all-heavy-atom validation after side-chain materialization.
- [x] Keep outputs inside benchmark workspaces until hard gates pass.
- [x] Measure fixed-atom drift, closure, withheld quality, runtime, RAM, VRAM, same-seed raw/refined repeatability, and seed variability for the reviewed 5- and 10-residue smoke cases. Raw candidates failed junction/chirality/clash gates; repeated v3 post-refinement candidates pass all hard gates and are byte-identical within each same-seed pair.
- [x] Add the minimal NVIDIA Docker runner recipe with a digest-pinned
  linux/amd64 base, pinned RFdiffusion source, isolated adapter/sampler
  environments, and a mounted checkpoint verified before model loading.
- [ ] Build the final image and repeat the GPU smoke on a host with an OCI
  runtime. The current A100 benchmark host has no Docker, Podman, Apptainer,
  Skopeo, or Crane executable, so no final image digest is claimed.
- [x] Defer registry publication/signing, multi-architecture builds, embedded
  checkpoint distribution, orchestration manifests, and remote scheduling
  until a real deployment requires them; these do not address a current
  Phase 2 benchmark problem.

### Phase 3: All-Atom Constrained Sampler

- [x] Complete the Protenix v1 hook feasibility spike; the pinned source lacks a maintainable per-step hook.
- [x] Complete the Boltz-2 source audit and maintained callback smoke on CPU/A100; the official checkpoint also strictly loads and produces byte-identical two-step A100 baseline samples. Stable gap identity mapping remains open.
- [x] Add a minimal maintained Protenix v1 post-update callback patch and verify exact callback execution in a two-step CPU smoke and a 200-step checkpoint-backed A100 gap run.
- [x] Verify that the official digest-pinned Protenix v1 checkpoint loads strictly, accepts deposited-structure template conditioning, preserves a stable request-identity atom axis, and performs exact callback-backed reinjection at every step.
- [x] Select the maintained Protenix v1 patch for the next boundary-refinement spike after per-step control was demonstrated; this is not public-backend acceptance.
- [x] Integrate the backend-neutral weighted Kabsch synchronization primitive with the real Protenix sampler.
- [x] Integrate the backend-neutral exact fixed-coordinate reinjection primitive with the real Protenix sampler.
- [x] Implement localized post-sampling boundary refinement for the RFdiffusion baseline; this does not satisfy the per-step all-atom sampler ablation.
- [x] Reuse localized boundary refinement for the checkpoint-backed Protenix candidate; the repeated deterministic 7X35 candidate passes every hard gate byte-identically with `1.964 Å` gap-backbone RMSD.
- [x] Run the initial-case three-way ablation benchmark. Template-only moves fixed atoms (`1.986 Å` RMSD), reinjection preserves them exactly but leaves a `1.600 Å` junction, and generated-only refinement passes every hard gate with byte-identical repeats.
- [x] Repeat the Protenix reinjection/refinement path on 8CZ8-10, 7X35 Pro/Gly-7, and 7K8S insertion-code-3. All raw and refined repeats are byte-identical; every refined candidate passes all hard gates with `0.0 Å` fixed-heavy movement.
- [x] Require complete canonical heavy atoms.
- [x] Require final `assert_all_l` after every candidate's last heavy-coordinate change.
- [x] Complete the 231-group confirmatory evaluation for Protenix v1, MODELLER
  10.8, and proxy-only Boltz-2.
- [x] Demonstrate Protenix noninferiority and superiority to MODELLER within the
  tested one-chain internal-gap scope: 220/231 versus 169/231 hard-gate passes
  and median valid gap-backbone RMSD `0.408 A` versus `5.330 A`.
- [x] Select Protenix v1 as the only engine eligible for the experimental public
  backend; retain Boltz-2 as proxy-only because training leakage is unresolved.

### Phase 4: Experimental `model` CLI

- [x] Complete the Phase 3 scientific selection gate for the narrow supported slice.
- [x] Accept a successor ADR or ADR 0010 update that authorizes an opt-in
  experimental public backend without authorizing a default-backend change.
- [x] Add `--backend {modeller,diffusion}`.
- [x] Keep `modeller` as the default while diffusion requires explicit opt-in.
- [x] Expose only the selected Protenix profile and the separately evaluated
  Protpardelle Apple profile; do not expose Boltz-2 as a selectable backend.
- [x] Add profile, runner, checkpoint, digest, repeatable seed, timeout, and work
  parent options in a separate argparse group; do not expose automatic device
  selection.
- [x] Reject MODELLER-only options when `--backend diffusion` is selected.
- [x] Reject unsupported diffusion scope before starting an external process and
  direct users to rerun explicitly with `--backend modeller` when appropriate.
- [x] Preserve FASTA/SEQRES semantics where the diffusion scope supports them.
- [x] Do not fall back automatically to MODELLER.
- [x] Do not propagate diffusion options through `zbs` in this phase.
- [ ] Expose diffusion through the existing asynchronous managed-job API only after the experimental CLI gates pass; do not add a synchronous inference route or duplicate adapter science in Node.

#### Production Orchestration Boundary

- [ ] Extract backend-neutral model input, options, candidate, and outcome types
  instead of embedding diffusion branches throughout `model/pipeline.py`.
- [ ] Keep common preprocessing responsible for CIF-normalized PDB input, CONECT
  inference, content selection, FASTA/SEQRES extraction, case-sensitive chain
  discovery, output naming, and final publication.
- [x] Wrap the existing MODELLER path behind the backend boundary without changing
  its default behavior or output naming.
- [x] Route diffusion generation through `model/diffusion/pipeline.py` and keep
  engine-specific Python/CUDA packages outside the core environment.
- [x] Keep `zbs` and `homology` on their existing MODELLER paths during Phase 4.

#### Production Request Builder

- [x] Build `DiffusionRequest` directly from the shared production
  sequence placement rather than reconstructing placement inside the runner.
- [x] Allocate generated identities without collisions: use reserved integer
  numbers when available and insertion codes when deposited numbering leaves no
  room, preserving every observed protein identity. HETATM inputs remain outside
  the admitted diffusion scope and are rejected before runner launch.
- [x] Preserve `(chain, resid, icode)` and `(chain, resid, icode, atom)` identity
  without case normalization or insertion-code loss.
- [x] Require complete canonical generated-heavy-atom identities from the target
  sequence, independent of deposited side-chain completeness.
- [x] Include every supported fixed heavy atom and retained explicit link in the
  request, with deterministic source and identity digests.
- [x] Fail closed on ambiguous placement, terminal gaps, multiple MODEL blocks,
  unsupported noncanonical chemistry, unsupported heterogens, and unsupported
  external covalent links.
- [x] Freeze the first public scope to one canonical protein target chain and one
  internal two-anchor gap of 3-12 residues unless additional strata pass the
  same confirmatory gates.

#### Protenix Protocol Adapter

- [x] Replace the research-only build, checkpoint-smoke, and refinement sequence
  with one protocol-compliant Protenix runner executable.
- [x] Verify the pinned source revision, maintained patch digest, checkpoint
  SHA-256, protocol version, and device before model loading.
- [x] Build the stable atom axis and reject unresolved or duplicate request mapping.
- [x] Apply weighted frame synchronization and exact fixed-coordinate reinjection
  after every denoising update.
- [x] Run localized boundary refinement only on eligible generated or temporarily
  completed atoms and record every chirality repair.
- [x] Attach bounded sampler trace evidence to each returned candidate: profile,
  capability, sampler atom order, complete request fixed set, represented fixed
  subset, atom-order/fixed-mask digests, evidence-completeness marker, separate
  denoising-update and observed callback counts, fixed-coordinate tolerance,
  maximum observed post-projection error (or `null` without callbacks), final
  restoration, device/fallback, refinement, and resource metrics.
- [x] Materialize original fixed records without losing chain IDs, insertion codes,
  occupancies, B factors, ANISOU, or unrelated headers.
- [x] Return protocol `unsupported` or `failed` outcomes without refinement or
  candidate publication.

#### Validation And Public Output

- [x] Preserve every confirmatory hard gate and threshold without backend-specific
  relaxation in the public path.
- [x] Rank only candidates that pass identity, fixed-coordinate, completeness,
  connectivity, geometry, clash, and chirality gates.
- [x] Convert the internal bundle into the public `model` contract: matched PDB,
  `.dat`, diffusion provenance, and optional bundle index.
- [x] Build `.dat` only through `DatRecord`, including insertion-code-aware added
  atoms and residue summaries.
- [x] Stage all selected outputs below the destination parent, verify their digests,
  publish as one logical transaction, and remove every destination on failure.
- [x] Guarantee that unsupported input, runner failure, validation failure, and
  publication failure leave no final PDB, `.dat`, provenance file, or staging orphan.
- [x] Apply `--number-from-1` only at a defined pre-request boundary or reject it
  for diffusion until post-numbering identity and validation can be proven.

#### Runtime, Distribution, And Diagnostics

- [x] Add diffusion preflight to `doctor` without removing stable report sections.
- [x] Keep Torch, Protenix, CUDA, checkpoints, and engine caches outside the core
  wheel and `environment.yml`.
- [x] Require an operator-supplied checkpoint and exact digest verification until
  checkpoint redistribution review is complete.
- [ ] Pin the production environment or image, package lock, maintained patch,
  source revision, base image, and final image digest.
- [ ] Enforce bounded timeout, output, RAM/VRAM, workspace use, and subprocess cleanup.
- [ ] Build and GPU-smoke the final environment on representative NVIDIA hardware.
- [ ] Document local and future remote-runner operation without placing credentials
  in command lines, logs, manifests, or provenance.

#### Tests, Documentation, And Rollout

- [ ] Add production request-builder tests for FASTA, SEQRES, insertion codes,
  case-distinct chains, numbering collisions, unsupported chemistry, and complete
  canonical heavy-atom masks.
- [ ] Add fake-runner dispatch tests proving no runner launch for unsupported input
  and no automatic MODELLER fallback.
- [ ] Add publication fault-injection tests for every commit and cleanup boundary.
- [ ] Add protocol tests for checkpoint mismatch, callback-count mismatch, mapping
  mismatch, fixed-coordinate drift, malformed results, timeout, and process failure.
- [ ] Add a manual/self-hosted GPU acceptance lane for the pinned Protenix runner;
  keep the CPU protocol/validation lane mandatory and CUDA-independent.
- [ ] Update `docs/commands/model.md`, installation, known-issues, pipelines,
  domain/agent maps, and the experimental support matrix.
- [x] Regenerate CLI reference and GUI command schema through their generators.
- [x] Release the backend as opt-in experimental functionality first.
- [ ] Require a separate evidence-backed Phase 6 decision before calling the
  backend production-supported or changing any default.

### Phase 5: Mosaic-First Homology

- [x] Keep `selected_template_mosaic.pdb` as the authoritative coordinate frame.
- [x] Export companion coverage metadata from `materialize_template_plan` instead of recomputing template ownership later.
- [x] Preserve zero-based half-open template-plan masks.
- [x] Mark covered template atoms as fixed and persist ownership in provenance.
- [ ] Generate uncovered substitutions through explicit bounded junction windows;
  uncovered insertion/terminal regions are implemented, while covered sequence
  mismatches fail closed.
- [x] Pass one-chain internal-insertion checkpoint-backed MPS acceptance.
- [ ] Add multi-chain and multi-template cases only after one-chain acceptance.
- [x] Preserve distinct antibody H/L chain allocation; insertion-code promotion
  remains part of the broader cohort.
- [ ] Compare against MODELLER using the same target and template plan.
- [ ] Use OpenFold or Boltz full-chain prediction only as an independent plausibility comparator.
- [x] Expose the accepted slice as explicit experimental
  `homology --backend diffusion`, including the GUI workflow; never change the
  default or silently fall back to Modeller.

### Phase 6: Production Decision

- [ ] Complete code, weight, auxiliary-artifact, and container license review.
- [ ] Complete representative GPU deployment and reliability evaluation.
- [ ] Compare against MODELLER across every claimed supported stratum.
- [ ] Document supported and unsupported inputs.
- [ ] Make production promotion a separate evidence-backed decision.
- [x] Do not remove MODELLER or PDBFixer as a side effect of any future promotion.

## Benchmark Corpus

- [x] Declare a reviewed withheld-coordinate internal 3-5-residue case.
- [x] Declare a reviewed withheld-coordinate internal 6-12-residue case.
- [ ] Add a separate research stratum for gaps of 13-25 residues.
- [x] Expand beyond the initial 8CZ8 cases to an independent 8B01 regular-loop stratum with reviewed 5-/10-residue masks, same-seed repeats, independent hard-gate validation, and a same-configuration MODELLER comparator.
- [x] Include isolated target-chain-only glycine/proline-rich 7X35 masks (`AGQGP` and `PPGGPVP`) with same-seed repeats, independent validation, and MODELLER comparators. The partner chains and PLM are explicitly excluded, so these do not satisfy interface/ligand-context coverage.
- [x] Declare a reviewed interface-adjacent 7X35 `AWVPR` mask with retained
  protein partner chain `B`, a `2.36 Å` generated-region partner contact, and no
  retained PLM. The adapter now supplies that partner as fixed RFdiffusion
  receptor context and fail-closes on post-sampling partner-backbone drift.
- [x] Complete pinned A100 same-seed, independent-validation, and MODELLER
  measurements for the declared interface-adjacent case. Independent seed-7
  workspaces are byte-identical, pass every hard gate, and measure `1.195 Å`
  gap-backbone RMSD versus MODELLER median `3.472 Å`; fixed-heavy RMSD is
  `0.0 Å` versus `2.940 Å`.
- [x] Complete the reviewed antibody insertion-code case using the isolated
  7K8S heavy-chain `H/82A-H/82C` mask. Independent seed-7 A100 workspaces are
  byte-identical, restore all three insertion-code identities, pass every hard
  gate, and measure `0.445 Å` gap-backbone RMSD versus MODELLER median
  `6.483 Å`; fixed-heavy RMSD is `0.0 Å` versus `9.171 Å`.
- [x] Exercise case-sensitive chain identity in CPU unit tests; add a reviewed benchmark structure with case-distinct chains before real-engine claims.
- [x] Declare terminal one-anchor gaps only as a separate unsupported/later stratum.
- [x] Declare retained-heterogen cases as a separate unsupported/later stratum; add covalent-link fixtures when that stratum is reviewed.
- [x] Keep current reviewed structures under `tests/fixtures/`.
- [x] Document current fixture provenance in `tests/fixtures/README.md`.
- [x] Validate current fixture checksums against `tests/fixtures/MANIFEST.sha256`; regenerate it whenever fixtures change.

## Initial Hard Gates

- [x] Preserve 100% of atom and residue identities outside the generated mask.
- [x] Preserve 100% of applicable explicit links.
- [x] Require fixed-heavy-atom RMSD no greater than `0.01 Å` after final serialization.
- [x] Require fixed-heavy-atom maximum displacement no greater than `0.03 Å`.
- [x] Require zero detectable D-C-alpha centers.
- [x] Require complete expected heavy atoms for every generated canonical residue.
- [x] Require both junction C-N distances to fall within `1.20-1.45 Å`.
- [x] Reject any backbone break greater than `1.8 Å` in the generated region.
- [x] Reject severe steric overlaps in the generated and junction neighborhoods.
- [x] Reject gross general-residue Ramachandran outliers in the generated and junction neighborhoods; class-specific GLY/PRO/pre-PRO validation remains pending.
- [x] Reject gross pooled χ1/χ2 side-chain torsion outliers where both torsions are defined; this is not complete residue/backbone-dependent rotamer validation.
- [x] Require unsupported or ambiguous inputs to create no public PDB or result bundle.
- [x] Provide a CPU-testable same-seed repeatability classifier at `0.01 Å` and apply it to independent pinned A100 workspaces. Both initial v3 refined mask pairs measure `0.0 Å` generated-heavy RMSD and maximum displacement.
- [x] Version threshold changes instead of adjusting them after viewing benchmark outcomes. The current threshold is a named module constant and recorded in each repeatability assessment.

## Comparative Metrics

- [x] Compute gap backbone RMSD against withheld coordinates in the benchmark API and record pinned real-engine values for the initial 5-/10-residue subset.
- [x] Compute gap all-heavy-atom RMSD in the benchmark API and record pinned real-engine values for the initial 5-/10-residue subset.
- [ ] Report lDDT and GDT-HA or TM-score where meaningful after a reviewed implementation and real candidates exist.
- [x] Compute fixed-heavy and anchor-heavy RMSD.
- [x] Summarize peptide closure and independent-validation pass rates from explicit per-candidate decisions.
- [x] Preserve bond, angle, planarity, Ramachandran, pooled χ1/χ2, chirality, and clash metrics from independent validation manifests.
- [x] Compute top-1 and oracle top-k backbone quality from a declared ranking order.
- [x] Compute pairwise candidate diversity and ranking enrichment.
- [x] Compute success, unsupported, and failure rates by stratum from explicit run outcomes; no real-engine rates are claimed yet.
- [x] Aggregate observed wall time, model-load time, peak RAM, and peak VRAM while preserving missing values instead of fabricating them; no real-engine values are claimed yet.
- [x] Compute external-process timeout and crash rates from explicit failed-run evidence; no real-engine rates are claimed yet.
- [x] Report conditioning/reinjection/boundary-refinement ablation results for the initial 7X35 case; broader strata remain pending.
- [x] Encode and measure the gap-backbone RMSD gate as no more than `0.25 Å` worse than MODELLER. Refined RFdiffusion beats the MODELLER median on all six measured 8CZ8/8B01/7X35 masks; MODELLER's best `PPGGPVP` candidate is nevertheless better than the single RF candidate (`3.54 Å` versus `4.28 Å`).
- [x] Encode and measure the junction-pass gate as no lower than MODELLER. Both measured backends pass both junctions on all six masks after refinement.
- [x] Encode and measure fixed-coordinate adherence as strictly better than MODELLER: refined RFdiffusion is `0.0 Å` on all six masks, while every measured MODELLER comparator moves deposited coordinates.

## Hardware And CI Matrix

### CPU-Only Linux

- [x] Run contract serialization tests in the focused diffusion suite.
- [x] Run mask and identity tests in the focused diffusion suite.
- [x] Run Kabsch and reinjection primitive tests in the focused diffusion suite.
- [x] Run fake-runner tests, including same-seed measurement across independent workspaces.
- [x] Run provenance, checksum, local immutable-artifact preflight, and license-inventory tests.
- [x] Run timeout, crash, containment, hard-link/symlink, and atomic no-replace publication tests.
- [x] Run PDB validation, `.dat`, chirality, and benchmark-scoring tests.
- [x] Treat any tiny CPU inference as an optional smoke test only when upstream officially supports it; no real-engine CPU inference is claimed.
- [x] Do not use CPU inference for representative ensembles or acceptance benchmarks.

### macOS Apple Silicon — Deferred Follow-Up

Native Apple Silicon diffusion inference is intentionally deferred until the
Linux/NVIDIA implementation has a stable main framework and has completed its
Phase 2 backbone baseline and Phase 3 all-atom constrained-sampler tests. It is
not part of the current Phase 2-4 implementation cycle and must not delay or
weaken the A100 acceptance gates.

The separate
[`small-diffusion-apple-silicon-experiments.md`](small-diffusion-apple-silicon-experiments.md)
plan now owns compact-model and local M-series experiments.

- [ ] Reassess pinned-engine CPU/MPS feasibility only after the main framework and Linux/NVIDIA Phase 2/3 tests are stable.
- [ ] Run the same core, fake-runner, and validation suites as CPU Linux on an actual Apple Silicon host before claiming platform support.
- [x] Define a separate Apple Silicon research matrix covering upstream arm64 packages, unsupported operators, precision, unified-memory use, repeatability, and runtime.
- [x] Treat MPS inference as exploratory unless the selected pinned engine officially supports it.
- [x] Do not use MPS output as a release acceptance gate or as evidence for the Linux/NVIDIA gates.
- [x] Keep macOS usable as a DVBFixer core/client platform; a future remote Linux/NVIDIA runner may remain the practical inference path.
- [x] Document that Docker Desktop on macOS does not provide NVIDIA CUDA.

### Linux/NVIDIA

- [x] Use Linux x86_64 with NVIDIA driver 535.104.05 and the pinned native CUDA 11.1 environment; the future container runtime is not yet pinned.
- [x] Start short-gap evaluation on an A100-SXM4-40GB.
- [ ] Prefer 48-80 GB VRAM for larger complexes, all-atom models, multi-sample ensembles, and profiling.
- [x] Provide at least 64 GB system RAM and fast local temporary/model-cache storage.
- [x] Record actual peak memory instead of treating 24 GB as an upstream guarantee. The first instrumented run observed approximately 5.96 GB RAM and 3.70 GB VRAM.
- [x] Add a documented representative smoke profile before selecting long-term hardware.

### CI Separation

- [ ] Make the CPU contract lane mandatory in repository CI configuration; the suite itself is CPU-only and passing locally.
- [x] Keep the GPU inference lane opt-in or self-hosted until its environment is stable; no required GPU lane exists.
- [x] Return a clear typed preflight issue when no CUDA device is reported by an adapter launcher.
- [x] Do not let missing CUDA fail the core test suite.

## Expected Files

- [x] Add `src/dvbfixer/model/diffusion/__init__.py`.
- [x] Add `src/dvbfixer/model/diffusion/contract.py`.
- [x] Add `src/dvbfixer/model/diffusion/masks.py`.
- [x] Add `src/dvbfixer/model/diffusion/scope.py`.
- [x] Add `src/dvbfixer/model/diffusion/geometry.py`.
- [x] Add `src/dvbfixer/model/diffusion/runner.py`.
- [x] Add `src/dvbfixer/model/diffusion/validate.py`.
- [x] Add `src/dvbfixer/model/diffusion/pipeline.py`.
- [x] Add `src/dvbfixer/model/diffusion/provenance.py`.
- [x] Add `src/dvbfixer/model/diffusion/benchmark.py`.
- [x] Add `src/dvbfixer/model/diffusion/preflight.py`.
- [x] Add `src/dvbfixer/model/diffusion/sampler.py`.
- [ ] Change `src/dvbfixer/model/cli.py` only in the experimental CLI phase.
- [ ] Change `src/dvbfixer/model/pipeline.py` only for explicit backend dispatch after gates pass.
- [x] Change `src/dvbfixer/doctor.py` for runner, checkpoint, and device preflight.
- [ ] Change `src/dvbfixer/homology_plan.py` only in the mosaic-first phase.
- [ ] Change `src/dvbfixer/homology.py` only after the homology contract passes focused tests.
- [ ] Avoid changing `src/dvbfixer/ffutils/dat.py` unless a general sidecar requirement is demonstrated.
- [x] Add the isolated native runner environment lock, license inventory, and
  digest-pinned linux/amd64 container base. Final image identity remains an
  operational verification item because this host has no OCI runtime.
- [x] Add focused diffusion unit and integration tests for the contract, masks, geometry, research inventory, runner protocol, fake runner, independent validation, publication, provenance, adapter preflight, sampler conformance, repeatability, and benchmark metrics.
- [x] Add reproducible internal builders/analyzers for frozen withheld-coordinate requests, same-seed workspace pairs, and MODELLER comparator outputs.
- [ ] Add reviewed fixtures and regenerate their manifest when benchmark structures are added.

## Focused Verification

- [x] Run the diffusion core tests:

  ```bash
  pytest -q tests/test_diffusion_benchmark.py tests/test_diffusion_contract.py \
    tests/test_diffusion_geometry.py tests/test_diffusion_masks.py \
    tests/test_diffusion_pipeline.py tests/test_diffusion_preflight.py \
    tests/test_diffusion_provenance.py \
    tests/test_diffusion_research_inventory.py tests/test_diffusion_runner.py \
    tests/test_diffusion_sampler.py tests/test_diffusion_scope.py \
    tests/test_diffusion_validate.py
  ```

- [x] Run existing model and chirality regression tests:

  ```bash
  pytest -q tests/test_model_fasta_case.py tests/test_model_renumber.py \
    tests/test_model_strip_heterogens.py tests/test_ffutils_chirality.py
  ```

- [ ] Run homology tests when Phase 5 changes begin:

  ```bash
  pytest -q tests/test_homology_plan.py tests/test_homology.py \
    tests/test_homology_fasta.py
  ```

- [x] Run repository documentation and whitespace checks:

  ```bash
  python scripts/check_agent_docs.py
  git diff --check
  ```

- [ ] Run generated-reference updates and checks after argparse changes:

  ```bash
  python scripts/gen_cli_reference.py
  python scripts/gen_gui_spec.py
  python scripts/gen_cli_reference.py --check
  python scripts/gen_gui_spec.py --check
  ```

- [x] Run a pinned GPU smoke test on the reviewed 8CZ8 five-residue internal gap.
- [x] Run a same-seed deterministic repeat on the pinned GPU environment; the raw PDB was byte-identical and coordinate RMSD was `0.0 Å`.
- [x] Run the initial representative RFdiffusion subset and MODELLER comparator: repeated post-refinement seed-7 workspaces in each reviewed 5-/10-residue case are byte-identical, pass every hard gate, and pass the measured MODELLER comparison. Broader strata remain pending.

## First Implementation Iteration Exit Criteria

- [x] Complete all locally implementable Phase 0 and Phase 1 work; externally pinned GPU adapters remain later phases.
- [x] Keep the public CLI unchanged.
- [x] Keep the MODELLER default path unchanged.
- [x] Add no ML dependencies to the core environment.
- [x] Provide a versioned backend-neutral contract.
- [x] Provide deterministic mask construction.
- [x] Provide weighted Kabsch and reinjection primitives.
- [x] Provide a deterministic fake external runner.
- [x] Provide independent validation and atomic no-replace publication.
- [x] Provide a separate diffusion provenance manifest.
- [x] Provide a benchmark manifest with predeclared thresholds.
- [x] Provide CPU-testable adapter preflight and sampler-conformance decisions without claiming a real engine adapter.
- [x] Pass the CPU/Linux core suite and the separate native Apple Silicon MPS
  public-CLI smoke without making MPS part of core CI.

## Remaining External Gates

- [x] Phase 2 scientific implementation is complete: repeatable passing
  refined candidates and MODELLER comparisons cover 8CZ8, independent 8B01
  regular loops, target-chain-only 7X35 glycine/proline-rich difficult loops,
  retained-partner 7X35 interface context, and 7K8S antibody insertion codes.
  The minimal container recipe is implemented; final image build/GPU smoke is
  deferred until an OCI runtime is available. Checkpoint embedding and final
  redistribution review belong to Phase 6; Phase 2 keeps the checkpoint as a
  digest-verified read-only mount.
- [x] Phase 3 is complete for the narrow one-chain internal-gap slice. The
  confirmatory cohort selects Protenix v1 over MODELLER; Boltz-2 remains
  proxy-only. Multichain/interface and retained chemistry remain unsupported
  expansion scopes rather than blockers for the narrow Phase 4 implementation.
- [ ] Phase 4 is partially implemented. Public CLI dispatch, separate production
  wrappers, atomic public output, and per-candidate digest-linked sampler traces
  are present. Resolved Linux environment pinning and
  checkpoint-backed NVIDIA acceptance remain open.
- [ ] Phases 5-6 remain intentionally separate and make no homology,
  default-backend, or production-support claim.
- [x] Record the narrow backend as Phase 4 implementation-ready while keeping
  MODELLER/PDBFixer as the supported production baselines until the experimental
  integration and separate Phase 6 production decision pass.
