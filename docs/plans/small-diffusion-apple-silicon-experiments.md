# Small Diffusion And Apple Silicon Experiment Plan

**Current restart point:** [corrected cc89 Apple handoff](apple-cc89-handoff.md),
prepared after public CUDA baseline `cb43db6`. The historical MPS studies below
predate neutral chain phase and physical source positions. Preserve that baseline;
the corrected mode needs its own explicit MPS port and hardware acceptance.

- Status: active research; Linux selection and 231-case descriptive follow-up
  complete, Apple Silicon portability handoff next.
- Scope owner: Structure Preparation bounded context.
- Relationship to production work:
  - Keep Protenix v1 as the selected experimental production-integration backend.
  - Treat this plan as an independent search for a smaller local alternative.
  - Test compact candidates on Linux CPU/CUDA first. That gate is complete for
    Protpardelle-1c; test its Apple Silicon support next on the physical Mac.
  - Do not delay or weaken the Protenix integration gates.
  - Do not use Apple Silicon evidence as a substitute for Linux/NVIDIA acceptance.
- Related evidence:
  - [`../research/diffusion-confirmatory-results.md`](../research/diffusion-confirmatory-results.md)
  - [`diffusion-gap-reconstruction.md`](diffusion-gap-reconstruction.md)
  - [`../research/reconstruction-and-modeling-backends.md`](../research/reconstruction-and-modeling-backends.md)
  - [`../research/small-diffusion-candidate-results.md`](../research/small-diffusion-candidate-results.md)
  - [`../research/apple-silicon-diffusion-operator-smoke.md`](../research/apple-silicon-diffusion-operator-smoke.md)
  - [`../research/apple-silicon-diffusion-six-case-pilot.md`](../research/apple-silicon-diffusion-six-case-pilot.md)
  - [`../research/small-diffusion-apple-24-pilot.json`](../research/small-diffusion-apple-24-pilot.json)
  - [`../research/apple-silicon-diffusion-24-case-results.md`](../research/apple-silicon-diffusion-24-case-results.md)
  - [`../research/small-diffusion-apple-100-soak.json`](../research/small-diffusion-apple-100-soak.json)
  - [`../research/small-diffusion-apple-full-231.json`](../research/small-diffusion-apple-full-231.json)
  - [`../research/apple-silicon-diffusion-100-case-results.md`](../research/apple-silicon-diffusion-100-case-results.md)
  - [`../research/apple-silicon-diffusion-full-231-results.md`](../research/apple-silicon-diffusion-full-231-results.md)

## Goals

- [ ] Identify a compact diffusion or flow model suitable for internal protein
  gap reconstruction in public PDB structures.
- [ ] Demonstrate useful local inference on an Apple Silicon M-series processor
  without CUDA, remote inference, or silent CPU fallback during denoising.
- [ ] Prefer a bounded local crop and gap-only stochastic state over a full-complex
  predictor whose cost scales with the complete structure.
- [ ] Preserve the existing `DiffusionRequest`, validation, provenance, and
  atomic-publication boundaries.
- [ ] Produce complete canonical heavy-atom output directly from the selected
  generative model before publication.
- [x] Restrict compact candidate selection to models whose generative state
  directly contains every canonical residue heavy atom. Backbone diffusion plus
  an external side-chain packer is comparator-only and cannot satisfy this goal.
- [ ] Compare quality, reliability, memory, latency, and installation footprint
  against MODELLER and the selected Protenix v1 reference.
- [ ] Keep training-data membership and public-structure leakage explicit for
  every pretrained or newly trained candidate.

## Non-goals

- [x] Do not replace the selected Protenix v1 integration before a compact model
  passes an independent confirmatory study.
- [x] Do not expose an unvalidated small model through the public CLI.
- [x] Do not treat ordinary template conditioning as fixed-coordinate preservation.
- [x] Do not use protein language models whose memory footprint defeats the local
  deployment objective.
- [x] Do not claim quality on natural unresolved gaps from geometry checks alone;
  those structures have no experimental withheld-coordinate reference.
- [x] Do not train on the locked confirmatory cohort or sequence-cluster neighbors.
- [x] Do not use proprietary, non-commercial, API-gated, or redistribution-unclear
  weights as a distributable backend.
- [x] Do not require Docker Desktop for local Apple Silicon execution.

## Initial Supported Slice

- [ ] One canonical L-protein target chain.
- [ ] One internal two-anchor gap.
- [ ] Gap length 3-12 residues.
- [ ] Complete known target sequence from FASTA or SEQRES.
- [ ] Unambiguous shared sequence placement.
- [ ] No alternate-location ambiguity in the gap or anchor neighborhood.
- [ ] No retained unsupported heterogen, PTM, metal, glycan, cofactor, or external
  covalent link in the local context.
- [ ] Case-sensitive chain identity and insertion-code-aware residue identity.
- [ ] Fixed observed atoms outside the generated mask remain exact.
- [ ] Hydrogens and protonation remain downstream preparation responsibilities.

## Compactness Classes

- [x] Define `tiny` as no more than 15 million trainable parameters.
- [x] Define `small` as more than 15 million and no more than 50 million trainable
  parameters.
- [ ] Treat 50-150 million parameter models only as local feasibility references,
  not as the preferred compact deployment target.
- [ ] Record parameter count, checkpoint bytes, installed environment bytes,
  model-load memory, peak inference memory, and peak refinement memory separately.
- [ ] Reject a candidate from the compact track if it requires a multi-billion
  parameter sequence encoder or external embedding service.

## Candidate Audit

### Priority A: Compact Pretrained Spikes

- [ ] Audit Protpardelle-1c as the first pretrained compact candidate:
  - [x] measure 25,169,439 instantiated parameters and record the difference from
    the paper's approximate 22-million description;
  - [x] pin the exact source revision and checkpoint digest;
  - [x] verify MIT code and CC-BY-4.0 weight licenses;
  - [x] record the released AI-CATH/Ingraham CATH description while treating exact
    training membership as unresolved;
  - [x] audit native motif/crop conditioning with a three-residue withheld pilot;
  - [x] locate a stable post-update state hook and preserve the maintained patch;
  - [x] map its atom or residue state to exact DVBFixer identities;
  - [x] run Linux CPU and CUDA operator smokes before the Linux quality pilot;
  - [x] run MPS operator smokes only after the Linux candidate-selection gate;
  - [ ] treat AI-CATH/ProteinMPNN/ESMFold teacher bias and public-structure
    homology as unresolved until the training inventory is audited.
- [ ] Audit Protenix Tiny and Mini as all-atom size references:
  - [ ] verify the reported parameter counts and exact weight artifacts;
  - [ ] exclude variants requiring a multi-billion-parameter ESM dependency;
  - [ ] port or reapply the required post-update callback to the exact revision;
  - [ ] test whether optimized CUDA-oriented operations have pure PyTorch MPS paths;
  - [ ] keep these models outside the preferred compact class unless measured
    memory and latency justify a documented exception.

### Priority B: Backbone Architecture References

- [ ] Audit FoldingDiff as a torsion-diffusion and MPS plumbing reference:
  - [ ] verify checkpoint parameter count, training split, and maximum length;
  - [ ] test masked torsion conditioning and two-anchor Cartesian closure;
  - [ ] reject it as a repair backend unless both junctions close without moving
    fixed atoms and downstream all-heavy completion passes every hard gate.
- [ ] Audit Genie v1 and FrameDiff as compact residue-frame references:
  - [ ] verify checkpoint size, parameter count, source revision, and training IDs;
  - [ ] test MPS support for invariant-point/pair operations;
  - [ ] prototype exact clamping of observed residue frames;
  - [ ] treat released unconditional checkpoints as architecture evidence unless
    mask-aware conditioning is independently demonstrated.
- [ ] Keep RFdiffusion v1 as a backbone scientific comparator only; do not make
  its pinned CUDA/SE(3)-Transformer stack an Apple deployment target.
- [ ] Keep full Protenix v1 and Boltz-2 as quality/teacher references only; they
  are outside the compact local-model objective.

### Excluded Candidates

- [x] Exclude FrameDiPT from distributable backend work because of non-commercial
  share-alike terms already recorded by the main diffusion plan.
- [x] Exclude Chroma pretrained parameters from distributable backend work because
  access and use restrictions do not meet the local public-tool objective.
- [x] Exclude FoldFlow checkpoints from distributable backend work when their
  non-commercial terms apply.
- [x] Keep PATCHR comparator-only under ADR 0010; it is a method/tool reference,
  not a small model dependency.
- [ ] Reject any newly discovered candidate whose code and weight licenses cannot
  both be pinned and reviewed.

## Purpose-Trained Local Gap Model

### Preferred Architecture

- [ ] Train a gap-specific model instead of compressing a whole-complex predictor.
- [ ] Compare two bounded stochastic states:
  - [ ] backbone residue frames plus torsions;
  - [ ] complete generated heavy atoms in residue-local frames.
- [ ] Keep fixed atoms outside the stochastic state where possible; retain exact
  per-step reinjection as a tested safety invariant.
- [ ] Encode only bounded local context:
  - [ ] both sequence flanks;
  - [ ] residues within a frozen spatial radius of the gap and anchors;
  - [ ] target amino-acid sequence;
  - [ ] chain-relative positions and insertion-code-aware identities;
  - [ ] observed atom masks and supported explicit links.
- [ ] Avoid full-chain pair tensors whose memory scales quadratically with total
  structure length.
- [ ] Compare an SE(3)-equivariant frame/graph denoiser with a torsion-space
  denoiser under the same data, masks, parameter budget, and sampler schedule.
- [ ] Use canonical residue templates for atom inventory and stereochemistry
  rather than independently hallucinating atom names.
- [ ] Compare a backbone-first decoder plus deterministic side-chain placement
  against a direct all-heavy-atom head.
- [ ] Apply the existing generated-only boundary refinement after learned sampling.
- [ ] Keep refinement outside the learned score so raw and refined quality remain
  separately measurable.

### Capacity And Schedule Ablations

- [ ] Train matched 5M, 15M, and 30M parameter configurations first.
- [ ] Add a 50M configuration only if smaller models fail a frozen capacity gate.
- [ ] Compare 10, 20, and 50 denoising or flow steps.
- [ ] Compare one-candidate and four-candidate generation under the same wall-time
  and memory accounting.
- [ ] Compare float32 with float16 only after float32 CPU/MPS correctness passes.
- [ ] Do not use bfloat16 unless the declared Mac generation supports it and the
  complete scientific validation remains equivalent.
- [ ] Select the smallest configuration inside the quality noninferiority region,
  not the configuration with the lowest training loss.

### Training Objectives

- [ ] Include frame, coordinate, or torsion denoising loss appropriate to the state.
- [ ] Include junction C-N distance and generated-backbone continuity losses.
- [ ] Include backbone bond, angle, peptide-planarity, and signed C-alpha volume losses.
- [ ] Include context-clash and generated-side-chain torsion losses where defined.
- [ ] Weight losses without changing independent final validation thresholds.
- [ ] Record every objective weight and schedule in the checkpoint manifest.

## Public-Structure Dataset

### Source And Filtering

- [ ] Build training examples only from public PDB coordinate releases with a
  frozen acquisition date and immutable source checksums.
- [ ] Record PDB ID, chain, entity, release date, experimental method, resolution
  where applicable, sequence, sequence cluster, and source coordinate digest.
- [ ] Start from complete canonical protein windows whose withheld coordinates can
  serve as ground truth.
- [ ] Exclude ambiguous alternate conformers, severe source geometry errors,
  noncanonical target residues, unexplained chain breaks, and unsupported local
  chemistry from the initial training scope.
- [ ] Generate artificial gaps only after sequence-cluster splitting.
- [ ] Match training masks to the declared 3-12-residue production distribution.
- [ ] Preserve difficult glycine-, proline-, charged-, and buried-loop strata
  rather than filtering only easy surface loops.

### Leakage Control

- [ ] Split train, validation, tuning, and test sets by sequence cluster before
  sampling multiple masks from a structure.
- [ ] Freeze a conservative training release cutoff before model training.
- [ ] Reserve a later temporal test set of public structures released after that cutoff.
- [ ] Exclude every locked DVBFixer confirmatory group and its sequence-cluster
  neighbors from training, validation, and hyperparameter tuning.
- [ ] Publish exact membership manifests for every split and checkpoint.
- [ ] Treat pretrained models with unavailable training membership as exploratory
  only; do not use them for leakage-sensitive model selection.
- [ ] Keep teacher-generated coordinates out of crystallographic ground-truth sets.
- [ ] Label any Protenix distillation experiment explicitly and evaluate it on a
  teacher-independent temporal holdout.

### Evaluation Strata

- [ ] Use withheld-coordinate public structures for quantitative RMSD evaluation.
- [ ] Reuse the locked 231-group confirmatory design only after the architecture,
  thresholds, and selection rule are frozen.
- [ ] Add an Apple-focused pilot balanced by:
  - [ ] 3-5 versus 6-12 residue gaps;
  - [ ] exposed versus buried gaps;
  - [ ] regular versus glycine/proline-rich sequence;
  - [ ] insertion-code versus ordinary numbering;
  - [ ] small versus large source structures under the same bounded local crop.
- [ ] Create a separate natural-gap shadow set from public structures where the
  deposited gap has no coordinate ground truth.
- [ ] Report only geometry, fixed-coordinate adherence, candidate diversity,
  method agreement, and operational reliability on natural gaps; do not report
  unobservable RMSD or claim biological correctness.

## Apple Silicon Runtime

### Baseline Environment

- [x] Use a native arm64 Python environment on a physical Apple Silicon Mac.
- [x] Record chip generation, GPU core count, physical unified memory, macOS,
  Xcode command-line tools, Python, PyTorch, and dependency-lock versions.
- [x] Start with a 16 GB M-series Mac as the minimum declared baseline where available.
- [ ] Add at least one newer 24 GB or larger machine for scaling measurements.
- [x] Keep model checkpoints and caches local and checksum-verified.
- [x] Keep Torch and model-specific packages in an external runner environment,
  not in the DVBFixer core environment.

### PyTorch MPS Track

- [x] Establish float32 CPU output as the numerical reference for each candidate.
- [x] Run one denoiser step on `mps` before attempting full sampling.
- [x] Inventory unsupported operators, implicit device transfers, synchronization
  points, and host callbacks.
- [x] Disable silent broad CPU fallback during acceptance measurements.
- [ ] Allowlist intentional CPU operations individually and include their time in
  end-to-end latency.
- [ ] Keep OpenMM boundary refinement on its independently selected macOS platform;
  do not imply that OpenMM uses PyTorch MPS.
- [ ] Compare CPU and MPS final candidates by hard-gate outcome, coordinate
  divergence, ranking, runtime, and memory; do not require cross-device byte identity.
- [ ] Require same-device, same-seed repeatability or record measured nondeterminism.

### MLX And Core ML Follow-Ups

- [ ] Begin an MLX port only if PyTorch MPS passes scientific gates but misses a
  frozen memory or latency target.
- [ ] Port only the selected stateless denoiser first; keep request handling,
  iterative sampling policy, reinjection, validation, and publication shared.
- [ ] Compare PyTorch and MLX weights through a deterministic conversion manifest.
- [ ] Consider Core ML only for the stateless denoiser after fixed-shape export
  and operator coverage are proven.
- [ ] Do not move dynamic masking, per-step identity checks, reinjection, or final
  scientific validation into an opaque converted graph.

### Apple Operational Gates

- [ ] Freeze the exact baseline Mac before collecting selection results.
- [ ] Require no unreported CPU fallback during denoising.
- [ ] Keep peak unified memory below 60% of physical memory on the baseline Mac.
- [ ] Complete 100 consecutive pilot cases without memory-pressure termination,
  process leak, or unreclaimed temporary workspace.
- [ ] Use an initial latency target of p95 below five minutes for one 3-12-residue
  candidate on the baseline Mac; revise only before outcome-bearing benchmarks.
- [ ] Record model load, feature construction, denoising, atom completion,
  refinement, validation, and publication times separately.
- [ ] Require local offline execution after checkpoints and dependencies are installed.

### Apple Silicon Handoff Runbook

This is a portability study of the already selected compact exploratory baseline,
not a new model-selection exercise. Do not tune sampling, refinement, validation,
or selection from Apple outcomes. Do not repeat all 231 cases until the bounded
lanes below pass and a full repeat has a stated decision value.

#### Frozen Configuration

- [x] Move only Protpardelle-1c `cc89_epoch415` to the first Apple test. Keep
  source revision `ee378400f25b801fa481028000f9060183d7fb4c`, checkpoint SHA-256
  `dfc9895b399ec4497bf6d646502168725f01dcbd55bc0b541fc3e3cc1f2f0483`,
  and config SHA-256
  `e9999ace79bf3044351cc982a624fc3459add3a4f91cbf97ff5b437b8942eb9d`.
- [x] Keep the selected sampling policy unchanged: request seed, 500 steps,
  `step_scale=1.2`, `s_churn=200`, supplied sequence, no MiniMPNN or
  ProteinMPNN, native conditioning followed by rigid synchronization and exact
  final fixed-atom projection. Do not enable the rejected per-step reinjection
  ablation.
- [x] Keep Linux/A100 results immutable as comparator evidence. The 231-case
  baseline is raw `101/231`, refined `217/231`, and validation-first selected
  `217/231`; Apple runs must use a separate output namespace and report rather
  than update those values.
- [x] Freeze an Apple manifest before the first outcome-bearing run. It must
  preserve sampling and validation settings, select OpenMM `CPU` refinement,
  name the exact pilot cases, and use a new output namespace. Never edit either
  Linux full-follow-up manifest for Apple execution.

#### Before Moving Machines

- [x] Add an explicit `--device {cpu,cuda,mps}` to the research adapter and pass
  the selected device through model loading and tensor creation. The current
  adapter no longer relies on ad hoc replacement of `cuda` on the Mac.
- [x] Make accelerator telemetry device-aware. Record CUDA VRAM only on CUDA;
  on Apple record Torch MPS allocated/driver memory where available plus process
  peak RSS from macOS. Missing MPS telemetry must be `null`, never zero.
- [x] Add tests proving that the requested device is honored, unavailable MPS
  fails closed, and summary metadata cannot label a CPU run as MPS.
- [ ] Materialize a transfer bundle containing the committed repository revision,
  the six frozen pilot workspaces (`36hb`, `9gtp`, `9gae`, `9ina`, `9eho`,
  `9gbg`) with relative artifact layout intact, the source `aggregate.json`,
  required comparator candidates/summaries, the Apple manifest, config, and
  checkpoint. Include a SHA-256 inventory for every transferred file.
- [ ] Keep the 24-case and 231-case workspaces off the first transfer unless the
  six-case gate passes. Do not transfer Linux environments, caches, generated
  candidates, credentials, or untracked editor/agent configuration.

#### Native Environment And Inventory

- [x] Check out the frozen repository revision and verify the transfer inventory
  before installing or running anything.
- [x] Confirm `uname -m` reports `arm64`; reject a Rosetta/x86_64 Python. Record
  `sw_vers`, `system_profiler SPHardwareDataType`, `xcode-select -p`, free disk,
  and physical unified memory.
- [x] Create separate native arm64 DVBFixer and Protpardelle environments. Record
  exact Python, PyTorch, OpenMM, NumPy, MDAnalysis, and model dependency versions
  plus the final explicit environment export and installed size.
- [x] Verify `torch.backends.mps.is_built()` and `is_available()`. Set
  `PYTORCH_ENABLE_MPS_FALLBACK=0` for every acceptance run so an unsupported
  operator fails instead of silently running on CPU.
- [x] Verify the selected OpenMM macOS `CPU` platform independently. Record its
  name, version, precision properties, thread count, and generated-only
  refinement runtime; do not describe it as MPS acceleration.
- [ ] Disconnect networking after dependency and checkpoint installation and
  repeat the one-step load smoke to prove local offline operation.

#### Ordered Test Lanes

- [x] Lane 0, core contract: run the diffusion contract, scope, mask, validation,
  geometry, provenance, pipeline, preflight, runner, Protpardelle adapter, and
  pilot-driver tests on macOS arm64 before loading the checkpoint.

  ```bash
  pytest -q \
    tests/test_diffusion_contract.py \
    tests/test_diffusion_scope.py \
    tests/test_diffusion_masks.py \
    tests/test_diffusion_validate.py \
    tests/test_diffusion_geometry.py \
    tests/test_diffusion_provenance.py \
    tests/test_diffusion_pipeline.py \
    tests/test_diffusion_preflight.py \
    tests/test_diffusion_runner.py \
    tests/test_protpardelle_research_scripts.py \
    tests/test_small_diffusion_v5_pilot.py
  ```

- [x] Lane 1, CPU reference: load the pinned checkpoint in float32 on CPU, execute
  one denoiser step, and record finite outputs, atom37 shape, load time, step time,
  peak RSS, and output digest. Then run the shortest frozen case (`36hb`) once at
  500 steps if its projected runtime is practical.
- [x] Lane 2, MPS operator smoke: repeat the same load and one-step input on MPS
  with fallback disabled. Assert model state, denoiser inputs, and outputs remain
  on `mps`; inventory every unsupported operator or intentional host transfer.
- [x] Lane 3, MPS repeatability: run `36hb` at 500 steps in two independent
  workspaces with the same request seed. Require both selected candidates to pass
  all hard gates and fixed atoms to be exact. Report RMSD and maximum displacement
  between generated atoms; do not require cross-device or same-device byte identity.
- [x] Lane 4, frozen six-case pilot: run the six cases once on MPS, then perform
  generated-only OpenMM CPU refinement and validation without resampling. Retain
  every failure in the denominator and aggregate raw, refined, and selected results.
- [x] Lane 5, frozen 24-case portability pilot: proceed only if Lane 4 passes its
  stop rules. Use the existing 12 gap-5/12 gap-10 membership with an Apple-specific
  manifest and namespace; do not inspect outcomes while deciding replacements.
- [x] Lane 6, 100-case operational soak: proceed only if Lane 5 passes. Freeze the
  first 100 eligible full-follow-up cases in manifest order, run consecutively,
  and check memory pressure, temporary cleanup, process lifetime, and p95 latency.
  A 231-case Apple repeat requires a separate written rationale after this soak.
- [x] Lane 7, user-authorized 231-case extension: reuse only digest-verified
  first-100 artifacts produced by the identical frozen protocol, then run the
  remaining 131 cases in manifest order. Keep all scientific failures in the
  denominator and require 231/231 operational completions.

#### Measurements And Stop Rules

- [x] Record model load, feature construction, denoising, synchronization,
  refinement, validation, and total wall time separately for every case. Record
  peak RSS and MPS memory, physical memory, output digests, failures, and whether
  each stage executed on CPU or MPS.
  Synchronize MPS at timing boundaries. Treat sampled MPS tensor allocation,
  Metal driver allocation, and process RSS as overlapping unified-memory views;
  report them separately and never add them together.
- [x] Stop the MPS track immediately on silent CPU fallback, wrong-device tensors,
  non-finite coordinates, identity/atom-set mismatch, non-exact published fixed
  atoms, checkpoint/config digest mismatch, or an unsupported operator without a
  narrowly documented scientifically equivalent implementation.
- [ ] If MPS is unavailable but native CPU works, classify the host as CPU-only
  feasibility; do not weaken the MPS goal or report CPU execution as an MPS result.
- [x] Require both `36hb` repeats and all six Lane 4 selected candidates to pass
  scientific hard gates before Lane 5. MPS nondeterminism is acceptable only when
  quantified and both repeats remain valid.
- [x] Require at least `21/24` selected passes in Lane 5, no systematic new failure
  class, peak unified memory below 60% of physical memory, and projected p95 below
  five minutes before the 100-case soak. This threshold is frozen before Apple
  outcomes and is one failure looser than the Linux `22/24` exploratory result.
- [x] Require 100/100 operational completions in Lane 6 with no memory-pressure
  termination, leaked process, or unreclaimed workspace. Scientific failures stay
  in the denominator but do not count as operational failures when validation
  completes normally.
- [x] Write the final hardware/environment/operator/result record under
  `docs/research/`; keep checkpoints, environments, profiles, and generated
  structures under ignored `.artifacts/` paths.

## Experiment Phases

### Linux V5 Comparator Pilot Runbook

This runbook is the resumable execution record for the next compact-model work.
It reuses the materialized v5 requests and already frozen Protenix v1, Boltz-2,
and MODELLER 10.8 results; it does not rematerialize masks or rerun those three
comparators. The pilot is adapter evidence, not an independent benchmark and not
a basis for changing the selected Protenix backend.

- [x] Freeze the source cohort as
  `.artifacts/diffusion-confirmatory-cohort-500-v5/aggregate.json`, SHA-256
  `55e4cbc6c16ee6bf34a14aabf61ec71afcddfb436f15edb5195c3d8b3f717ad7`.
- [x] Freeze one deterministic six-case pilot before inspecting new Protpardelle
  outcomes: take the first three selected five-residue cases and first three
  selected ten-residue cases in v5 `screening_index` order whose target length is
  within the released `cc89` 512-residue limit.
- [x] Freeze the case IDs and strata as `36hb` (5), `9gtp` (5), `9gae` (5),
  `9ina` (10), `9eho` (10), and `9gbg` (10). Their target lengths are 106, 225,
  103, 440, 118, and 287 residues respectively.
- [x] Promote the current `cc89` spike into a fail-closed research adapter that
  consumes each case's existing `DiffusionRequest`, verifies the pinned config
  and checkpoint digests, maps exact case-sensitive residue/atom identities,
  supplies the authoritative sequence, and disables MiniMPNN/ProteinMPNN.
- [x] Add dependency-light tests for request mapping, insertion-code handling,
  motif serialization, canonical atom inventory, exact fixed-coordinate
  reinjection, malformed requests, and output atom-set mismatch.
- [x] Add a resumable six-case pilot driver. Each case must have an isolated
  output directory, an immutable input/output digest record, captured command,
  seed, runtime, peak VRAM, validation summary, and explicit failed status.
- [x] Use the request's existing single seed and the frozen `cc89` settings of
  500 steps, `step_scale=1.2`, and `s_churn=200`; do not tune on these six cases.
- [x] Run one independent-workspace same-seed repeat on the first short case
  (`36hb`) before the remaining five cases. Stop if identity mapping, output
  digest repeatability, fixed-atom exactness, or complete generated heavy atoms
  fail.
- [x] Run the other five cases only after the repeatability gate passes. A case
  failure remains in the aggregate denominator and must not be replaced.
- [x] Compare Protpardelle against the already recorded v5 Protenix, Boltz, and
  MODELLER values case by case. Report validation pass/fail, gap-backbone and
  all-heavy RMSD where available, hard-gate failure classes, wall time, peak RAM,
  peak VRAM, and output digest; never compare backend-native scores directly.
- [x] Apply generated-only boundary refinement to the same six raw candidates
  without resampling. OpenMM CPU raised hard-gate success from `2/6` to `6/6`;
  retain the `Reference` long-case timeout and CUDA PTX incompatibility as
  operational failures rather than silently changing or omitting them.
- [x] Record raw conditioning fit separately from the final gap-only reinjected
  candidate. The final candidate must preserve every fixed heavy atom exactly;
  native motif drift is diagnostic evidence, not publishable output.
- [x] Stop the pretrained compact track if `cc89` cannot represent both anchors,
  preserve the supplied sequence, emit every requested canonical generated heavy
  atom, or satisfy the existing validation contract. Geometry failures may
  continue through all six frozen cases so their frequency and class are visible.
- [x] Write the completed command/environment/hardware/result record to
  `docs/research/small-diffusion-candidate-results.md`; keep generated structures,
  checkpoints, environments, and run bundles under ignored `.artifacts/` paths.
- [x] Run focused adapter/driver tests, the existing diffusion contract/scope/
  validation tests, Ruff on changed Python files, `git diff --check`, and
  `python scripts/check_agent_docs.py` before marking this pilot complete.
- [x] Complete failure-atomic resumable orchestration, raw native-conditioning-fit
  reporting, the preregistered 24-case extension, CUDA portability repair, and the
  frozen 231-case descriptive follow-up before beginning Apple work.

### Expanded V5 Linux Pilot

- [x] Freeze the 24-case manifest before new Protpardelle inference in
  [`../research/small-diffusion-v5-expanded-pilot.json`](../research/small-diffusion-v5-expanded-pilot.json).
- [x] Select by v5 screening order only: 12 new five-residue and 12 new
  ten-residue cases after excluding the original six-case pilot, with no
  outcome-based replacement.
- [x] Run the exact raw sampler and generated-only CPU refinement settings from
  the manifest through failure-atomic resumable orchestration.
- [x] Report raw and refined hard-gate pass rates by gap stratum, paired RMSD
  comparisons against existing v5 Protenix/Boltz/MODELLER results, native motif
  drift, runtime, memory, and every operational failure.
- [x] Keep this expanded pilot exploratory because exact Protpardelle training
  membership and sequence-cluster leakage remain unresolved.
- [x] Run the corrected per-step reinjection follow-up over all 24 frozen cases in
  an isolated, digest-tracked namespace. All callbacks completed exactly, but
  validation-first coverage fell from `22/24` to `21/24`; retain final-only exact
  projection as the compact exploratory baseline.

### Phase 0: Preregistration And Artifact Audit

- [ ] Freeze compactness classes, supported scope, datasets, masks, metrics,
  hardware, and stop rules.
- [ ] Pin candidate source revisions, checkpoint URLs, digests, parameter counts,
  code licenses, weight licenses, and training-data statements.
- [ ] Stop any candidate with incompatible distribution terms or irreducibly
  unknown artifacts before integration work.

### Phase 1: Linux Operator And Footprint Smoke

- [x] Run Linux CPU/CUDA load and one-step smokes for Protpardelle-1c.
- [ ] Run Linux CPU/CUDA load and one-step smokes for Protenix Tiny/Mini if dependencies permit.
- [ ] Run architecture-reference smokes for FoldingDiff and one frame model.
- [ ] Record unsupported operators, environment size, load time, peak memory,
  numerical divergence, and projected full-sample runtime.
- [ ] Select at most two pretrained candidates for constrained-gap adaptation.

### Phase 2: Constrained Pretrained Pilot

- [x] Implement stable request identity mapping for each selected candidate.
- [x] Implement and verify per-step fixed-coordinate overwrite. The bounded,
  same-seed `9dvi` ablation was frozen before reinjection inference in
  [`../research/small-diffusion-protpardelle-reinjection-ablation.json`](../research/small-diffusion-protpardelle-reinjection-ablation.json).
  The frozen source-frame implementation exposed a frame mismatch and was retained
  as a failed diagnostic; a disclosed follow-up uses Protpardelle's internal motif
  frame and completed 500/500 exact projections in two byte-identical runs.
- [x] Run the bounded three-way ablation with the implementation correction above:
  native conditioning plus final publication projection, corrected per-step
  reinjection, and reinjection plus generated-only boundary refinement. Reinjection
  made the fixed proposal exact but did not fix raw `9dvi` geometry; both CPU-
  refined repeats passed, while differing by `0.274 A` over generated atoms.
- [x] Extend corrected reinjection to the frozen 24-case pilot without replacing
  failures. It completed operationally in every case and handled source-only
  `OXT`, but added the `9ges` failure and showed no meaningful paired RMSD gain.
- [x] Diagnose the OpenMM CUDA PTX failure as a CUDA 12.9 runtime versus
  CUDA-12.2-capable 535 driver mismatch and freeze an isolated OpenMM 8.2/CUDA
  12.2 environment with digest-pinned ff19SB XML data. Repeated `9dvi`
  refinement is byte-identical and the 440-residue `9ina` gate passes in 13.83
  seconds, authorizing the 231-case descriptive follow-up.
- [x] Evaluate the frozen v5 short and long pilot gaps on Linux CUDA sampling
  with CPU boundary refinement.
- [x] Complete the frozen 231-case Linux/A100 descriptive follow-up with CUDA
  refinement: raw `101/231`, refined `217/231`, and validation-first selected
  `217/231`, while retaining all failures in the denominator.
- [ ] Stop a candidate that cannot represent both anchors, complete canonical
  output, or preserve fixed coordinates exactly.
- [ ] Stop backbone-only and hybrid backbone-plus-packer candidates before the
  constrained pretrained pilot, regardless of their backbone RMSD.

### Phase 3: Apple Operator And Footprint Smoke

- [x] Complete the handoff runbook above, then move only the Protpardelle-1c
  Linux survivor to a physical Apple Silicon machine.
- [x] Run native arm64 CPU/MPS load and one-step smokes without silent CPU fallback.
- [x] Record unsupported operators, device transfers, memory, runtime, and numerical
  divergence before attempting full constrained sampling.
- [ ] Stop Apple-specific work for candidates that fail the Linux scientific gates.

### Phase 4: Purpose-Trained Prototype

- [ ] Build the immutable public-structure dataset and split manifests.
- [ ] Train the capacity and sampler-step ablations.
- [ ] Select architecture and capacity using validation clusters only.
- [ ] Freeze one checkpoint before temporal and confirmatory evaluation.
- [ ] Publish checkpoint, source, dataset, and training provenance internally
  before outcome-bearing tests.

### Phase 5: Independent Benchmark

- [ ] Compare the frozen compact checkpoint against MODELLER and Protenix v1.
- [ ] Require noninferiority to MODELLER within the existing paired five-point
  pass-rate margin before calling the model useful.
- [ ] Require noninferiority to Protenix within the same margin before calling the
  model a compact substitute for the selected diffusion backend.
- [ ] Report paired pass-rate intervals, cluster-bootstrap RMSD differences,
  failure classes, runtime, memory, checkpoint size, and installation footprint.
- [ ] Count every failed or operationally incomplete case against the endpoint.

### Phase 6: Natural-Gap Shadow Evaluation

- [ ] Run only after the withheld-coordinate benchmark passes.
- [ ] Keep natural-gap outputs non-public and clearly marked experimental.
- [ ] Review geometry failures, disagreement between methods, high candidate
  diversity, and context-sensitive outliers.
- [ ] Do not tune hard gates on shadow outcomes.
- [ ] Use the shadow set to define future unsupported scopes, not to claim RMSD.

### Phase 7: Integration Decision

- [ ] Select one of four explicit outcomes:
  - [ ] no viable compact model;
  - [ ] research-only Apple backend;
  - [ ] opt-in local experimental backend;
  - [ ] compact replacement candidate requiring a separate ADR and confirmatory study.
- [ ] Reuse the existing isolated runner protocol for any accepted backend.
- [ ] Keep MODELLER as default and prohibit automatic scientific fallback.
- [ ] Publish only after existing identity, geometry, chirality, `.dat`, provenance,
  and atomic-output gates pass.
- [ ] Keep model runtime dependencies and weights outside the core wheel.

## Scientific Hard Gates

- [ ] Preserve all atom and residue identities outside the generated mask.
- [ ] Preserve all applicable explicit links.
- [ ] Fixed-heavy-atom RMSD no greater than `0.01 A`.
- [ ] Fixed-heavy-atom maximum displacement no greater than `0.03 A`.
- [ ] Complete canonical heavy atoms for every generated residue.
- [ ] Both junction C-N distances within `1.20-1.45 A`.
- [ ] No generated-region backbone break above `1.80 A`.
- [ ] Zero detectable D-C-alpha centers after the final heavy-coordinate change.
- [ ] No severe local overlap or existing bond, angle, planarity, Ramachandran,
  or pooled chi1/chi2 hard-gate failure.
- [ ] Unsupported input, runner failure, or invalid output creates no public PDB,
  `.dat`, provenance file, result bundle, or staging orphan.
- [ ] Rank only passing candidates and keep backend-native scores separate from
  MODELLER `molpdf`, physical energies, and independent geometry metrics.

## Expected Artifacts

- [x] Add a versioned small-model candidate inventory under `docs/research/`.
- [ ] Add immutable dataset, split, and mask manifests outside model code.
- [ ] Add external arm64 environment locks under a dedicated `deploy/` adapter.
- [x] Add CPU/MPS operator and resource reports with exact hardware metadata.
- [ ] Add protocol adapters only for candidates that pass artifact and license audit.
- [ ] Add no model weight to Git.
- [ ] Add no Torch, MLX, Core ML, or model-specific dependency to the core
  `environment.yml` or mandatory package dependencies.

## Verification Checklist

- [ ] Validate documentation and inventory links with `python scripts/check_agent_docs.py`.
- [ ] Run contract, scope, validation, provenance, and publication tests on macOS arm64.
- [ ] Run candidate adapter tests on CPU and MPS.
- [ ] Run same-seed repeat tests in independent workspaces.
- [ ] Run fault-injection tests for timeout, memory failure, unsupported operation,
  malformed result, failed validation, and interrupted publication.
- [ ] Record the exact command, environment lock, hardware, input digest,
  checkpoint digest, seed, and output digest for every benchmark run.
