# Implementation Checklist

This is the canonical completion tracker for the plans in this directory.
Check an item only after its implementation and required verification are
complete. Detailed requirements remain in these authoritative sources:

- [API roadmap](api-roadmap.md) for API implementation and deployment.
- [DDD documentation roadmap](ddd-documentation-roadmap.md) for agent maps and domain documentation.
- [Diffusion gap-reconstruction plan](diffusion-gap-reconstruction.md) for the proposed experimental modeling backend.
- [Small diffusion and Apple Silicon plan](small-diffusion-apple-silicon-experiments.md) for compact local-model research.
- [Diffusion with heterogen context plan](diffusion-heterogen-gap-reconstruction.md) for class-specific research on retaining and conditioning on small molecules, cofactors, ions/metals, glycans, PTMs, and covalent ligands during protein-gap reconstruction.
- [Diffusion runner environment plan](diffusion-runner-environments.md) for separate core, Apple MPS, and Linux/NVIDIA dependency boundaries and production protocol wrappers.
- [Continuation context](api-ddd-continuation-context.md) for historical evidence only.

Status is binary: `[x]` means complete and verified; `[ ]` means remaining,
partially complete, optional but not accepted, or not yet verified.

## API Phase 0: Decisions And Baseline

### Accepted Decisions

- [x] Accept an ADR making Node/TypeScript the HTTP, workspace, artifact, and job shell.
- [x] Accept an ADR making Python the sole owner of scientific naming policy.
- [x] Accept an ADR for host-neutral route composition rather than a duplicate Python web service.
- [x] Record `dvbfixer atom-names` as the dedicated naming command.
- [x] Record naming conversion as synchronous and long-running workflows as asynchronous jobs.
- [x] Record workspace artifact IDs as the only V1 server-side input reference.
- [x] Record the V1 policy rejecting multiple `MODEL` blocks.

### Open Maintainer Decisions

- [x] Select an authentication model.
- [x] Define principal-to-workspace authorization semantics.
- [x] Decide whether V1 needs direct upload/download conversion.
- [x] Decide whether HTTP should accept a JSON override artifact as well as inline overrides.
- [x] Decide whether `tleap-reduce` must honor the force-field naming option.

### Baseline Evidence

- [x] Add regression coverage for naming blockers 1-6 and 9 from the API roadmap.
- [x] Complete end-to-end nucleic-acid naming coverage.
- [x] Capture and document any still-needed representative golden inputs.
- [x] Complete ADR and test evidence distinguishing current behavior from intended V1 behavior.

## API Phase 1: Naming Application Service

### Application Boundary

- [x] Add typed naming request, result, diagnostic, target, profile, override, identity, and report vocabulary.
- [x] Implement `convert_force_field_naming` as PDB text in and transformed text plus report out.
- [x] Keep file I/O outside the pure service.
- [x] Retain the atomic in-place compatibility adapter for existing pipeline callers.
- [x] Report changed atoms, residues, variants, and atom names separately.
- [x] Keep naming conversion distinct from canonical `rename` and chemical parameterization.

### V1 Semantics And Correctness

- [x] Accept PDB text and support AMBER and CHARMM with the GROMACS profile.
- [x] Preserve exact, case-sensitive chain IDs and insertion codes.
- [x] Use typed three-field override identities and restrict legacy two-field identities to blank insertion codes.
- [x] Apply explicit override, explicit source variant, then no inferred change precedence.
- [x] Do not infer HID/HIE/HIP from canonical HIS alone.
- [x] Validate before returning or committing output and leave sources untouched on failure.
- [x] Reject multiple `MODEL` blocks.
- [x] Detect source and target atom-name collisions per residue.
- [x] Update correlated `ANISOU` and parseable full `TER` records.
- [x] Preserve unrelated records and non-name atom fields.
- [x] Support four-character CHARMM names and LYN/LSN hydrogen pairs idempotently.
- [x] Remove ambiguous two-field override fallback from the public service.
- [x] Add end-to-end DNA and RNA naming tests.
- [x] Document unvalidated terminal 5-prime/3-prime hydroxyl cases as unsupported.
- [x] Resolve `tleap-reduce` naming parity.
- [x] Document `standard` as suppressing shifts, not reversing GROMACS names.
- [x] Do not claim naming compatibility proves template or bond compatibility.

### Test Matrix

- [x] Verify every `GROMACS_AMBER_ATOM_RENAMES` mapping.
- [x] Verify AMBER and CHARMM caps and termini.
- [x] Verify exact coexistence of residues such as `H:82` and `H:82A`.
- [x] Verify one-residue and multi-chain proteins.
- [x] Verify byte-identical repeat conversion across all supported mappings.
- [x] Complete malformed-line coverage.
- [x] Complete `ATOM`, `HETATM`, `ANISOU`, `TER`, and untouched-record matrix coverage.
- [x] Verify empty/no-op conversion and report counts.

Evidence: `tests/test_force_field_naming.py` checks independent expected AMBER
spellings against the complete mapping inventory, both coordinate record types,
caps/termini, variant directions/profiles, DNA/RNA, repeated conversion, malformed
identity fields, correlated records, line endings, and report counts. This
verifies naming transformations, not chemical template or bond compatibility.

## API Phase 2: Dedicated CLI Adapter

- [x] Add `dvbfixer atom-names` with one input and one explicit output.
- [x] Add `--target-ff {amber,amber19sb,charmm}` and `--profile gromacs`.
- [x] Support variant overrides from JSON, `--dry-run`, and `--report-json`.
- [x] Call the pure naming service and keep the command distinct from `rename` and `convert`.
- [x] Register the command and regenerate CLI and GUI command references.
- [x] Add subprocess-level tests and deterministic conversion.
- [x] Explicitly verify source preservation at CLI level.
- [x] Explicitly validate the report schema at CLI level.
- [x] Explicitly verify non-zero exit and no destination on unsafe input.
- [x] Explicitly verify the selected CIF boundary behavior.

## API Phase 3: Versioned Naming API

### Core Vertical Slice

- [x] Add a V1 naming-conversion route with TypeBox runtime schemas and OpenAPI 3.1.
- [x] Resolve inputs by workspace artifact ID.
- [x] Invoke the Python command instead of duplicating naming rules in Node.
- [x] Validate bounded command reports and output digests.
- [x] Reload the current manifest before publication.
- [x] Register exactly one output with reproducible provenance and none for dry runs or failures.

### Request And Artifact Transaction

- [x] Authenticate the caller.
- [x] Authorize the principal before workspace path resolution.
- [x] Validate the request body and resolve `inputArtifactId` through the manifest.
- [x] Explicitly verify accepted source artifact types.
- [x] Enforce source artifact size limits before execution.
- [x] Verify operation-directory privacy and cleanup behavior.
- [x] Parse the report, validate output existence/digest, and publish against the current manifest revision.
- [x] Return the output artifact and report.
- [x] Define and verify retained failure-log behavior.
- [x] Add bounded retention or pruning for failed operation directories.

Evidence: `gui/server/naming-retention.test.ts` and `naming-api.test.ts` verify
age/count pruning, workspace and symlink isolation, retained diagnostics,
configuration validation, and cleanup on subsequent successful execution.

### Provenance, Observability, And Tests

- [x] Record source, target, profile, overrides, report, and digest provenance.
- [x] Explicitly record command/service and DVBFixer package versions.
- [x] Add server-owned request IDs and structured API access logs.
- [x] Add bounded process-local service metrics.
- [x] Add durable audit events and retention.
- [x] Generate a client from OpenAPI.
- [x] Verify stable validation and error envelopes across V1 routes.
- [x] Add authentication and authorization tests after implementation.
- [x] Explicitly test path containment, source/request size limits, and naming timeouts.
- [x] Test artifact lookup, dry runs, one-artifact publication, concurrent manifests, and failures.
- [x] Validate OpenAPI examples against runtime schemas.

## API Phase 4: Standalone Server

### Local Standalone Host

- [x] Extract host-neutral route composition and keep Vite as a thin adapter.
- [x] Add a bundled Node entry point serving the built GUI and API.
- [x] Bind to loopback by default and require explicit insecure remote acknowledgment.
- [x] Validate host, port, roots, and shutdown configuration.
- [x] Reject lexical and symlink-resolved static/data root overlap.
- [x] Return JSON for unknown API paths and use SPA fallback only for HTML requests.
- [x] Stop intake, reject new work, terminate children, then drain HTTP.
- [x] Bound the emitted-server startup and shutdown smoke test.
- [x] Complete final review and verification of the standalone slice.
- [x] Commit the standalone slice.

### Public Deployment Hardening

- [x] Add authentication and principal-to-workspace authorization.
- [x] Add restrictive CORS.
- [x] Add upload and workspace limits plus process-wide child concurrency control.
- [x] Bound the process-wide child admission queue and reject overload before spawning.
- [x] Add bounded process-local request-rate limits before authentication.
- [x] Add OS-level CPU, memory, and filesystem quotas.
  - [x] Add a fail-closed systemd/cgroup-v2 deployment profile and bounded-storage preflight.
  - [x] Run privileged kernel-enforcement acceptance tests on the Ubuntu 24.04 reference deployment host in CI.
- [x] Document current local deployment and security boundaries.
- [x] Document the supported single-host public-deployment profile after security controls exist.
- [x] Add storage-level manifest locking or compare-and-swap.
- [x] Replace process-local locks and event subscribers for multi-instance operation.
- [x] Complete reference public-deployment smoke tests through HTTPS on the CI VM.

## API Phase 5: General DVBFixer API

### Route And Contract Policy

- [x] Version managed-job routes under `/api/v1`.
- [x] Retire the duplicate synchronous generic command route.
- [x] Classify every operation as a deterministic transform or managed workflow.
- [x] Keep minimization, modeling, and parameterization out of synchronous APIs.
- [x] Preserve cancellation for long-running operations.
- [x] Generate clients and contract tests from OpenAPI.
- [x] Define API compatibility, versioning, and deprecation policy.
- [x] Add durable scheduling, state, and event delivery before horizontal scaling.

### Operation Rollout

- [x] Expose `diagnose`.
- [x] Expose `conect`.
- [x] Expose `renumber`.
- [x] Version or migrate managed `prepare`, `minimize`, `model`, and `zbs`.

## API-Wide Quality Gates

- [x] Use one runtime-schema source for every V1 route and OpenAPI description.
- [x] Ensure no public route accepts unrestricted filesystem paths.
- [x] Keep scientific naming policy implemented once in Python.
- [x] Record reproducible inputs, options, and versions for every output artifact.
- [x] Enforce workspace ownership before path resolution.
- [x] Return structured reports for every exposed operation.
- [x] Require durable workflow state before horizontal scaling.
- [x] Adopt one common V1 error envelope and explicit compatibility policy.
- [x] Test status mappings for 400, 401, 403, 404, 409, 413, 415, 422, and 500.
- [x] Stabilize documented naming error codes.
- [x] Run release verification: GUI checks, focused Python tests, generated-file checks, agent-doc checks, and the non-slow Python suite.
- [x] Push the completed implementation and require every configured GitHub Actions CI check on that commit to pass.

Verification on 2026-09-21: the [post-push CI run for `cf56aaa`](https://github.com/lilpoundcake/DVBFixer/actions/runs/35661988827)
passed all four configured jobs. The scientific lane reported 552 passed and
3 skipped (no Modeller license); GUI reported 232 passed. Locally, the
non-slow Python suite reported 533 passed and 3 skipped, and the Python 3.11
fast-lane selection reported 220 passed. Ruff, mypy, TypeScript, generated
CLI/GUI/OpenAPI files, agent-doc validation, and `git diff --check` passed.
Python 3.13 changes argparse help formatting, so CI pins its scientific lane
to Python 3.11. This verification does not include licensed Modeller
integrations or target-host public-deployment acceptance.

Reference deployment acceptance on 2026-09-22: the
[Ubuntu 24.04 CI run for `b72e477`](https://github.com/lilpoundcake/DVBFixer/actions/runs/35695278505)
passed its new privileged deployment job. The systemd service's mandatory
preflight accepted a dedicated ext4 data mount, read-only root, private tmpfs,
CPUQuota=200%, MemoryMax=16 GiB, MemorySwapMax=0, and TasksMax=512. Scaled
probes recorded `cpu.stat nr_throttled` 1→31, `memory.events oom_kill` 0→1,
and `pids.events max` 0→2; writes stopped at the data and temporary filesystem
limits, and stopping the unit removed a session-detached child. HTTPS smoke
covered health, required bearer auth, CORS rejection, and workspace creation;
MAFFT, tleap, and Reduce produced output under a contained unit. These results
validate the Ubuntu reference profile, not an operator's future production host;
the installation-specific acceptance in `docs/deployment.md` remains required.

The versioned workflow API uses a durable workspace run lock, cross-process
cancel markers, and persisted job-record polling for SSE on a shared local
filesystem. `docs/adr/0009-versioned-workflows-and-compatibility.md` defines
the V1 error and deprecation policy. Horizontal scaling across multiple hosts
remains explicitly unsupported until an external scheduler/state store exists;
these checked workflow-state items cover one-host multi-process operation.

## Diffusion Gap Reconstruction

- [x] Complete Phase 0: policy, license inventory, corpus, leakage metadata, and predeclared thresholds.
- [x] Complete Phase 1: backend-neutral contract, masks, Kabsch/reinjection primitives, fake runner, validation, provenance, and atomic publication.
- [x] Complete Phase 2: pinned RFdiffusion v1 Linux/NVIDIA benchmark adapter and minimal digest-pinned container recipe; final container build/GPU smoke awaits a host with an OCI runtime.
- [x] Complete Phase 3: select Protenix v1 through the all-atom constrained-sampler ablation and 231-group confirmatory benchmark; retain Boltz-2 as proxy-only.
- [x] Record the confirmatory result: Protenix 220/231, MODELLER 169/231, noninferiority demonstrated, and `candidate-preferred` decision.
- [ ] Complete Phase 4: experimental `model --backend diffusion` while retaining
  MODELLER as the default and without automatic fallback. Public CLI, production
  wrappers, additive Doctor preflight, fail-closed batch/GUI admission,
  record-preserving candidate materialization, and portable protocol failure
  handling are implemented and CPU-tested. Resolved Linux environment pinning
  and hardware acceptance remain separate evidence tasks.
- [ ] Complete Phase 5: mosaic-first homology evaluation preserving authoritative template coordinates.
- [ ] Complete Phase 6: separate evidence-backed production decision.
- [x] Execute the macOS Apple Silicon CPU/MPS portability evaluation separately
  from Linux/NVIDIA acceptance and remote-runner evidence; all 231 frozen cases
  reached terminal outcomes with fallback disabled, with 213/231 selected passes.
- [x] After native GPU gates pass, define the external NVIDIA Docker runner with a digest-pinned base and digest-verified mounted checkpoint.
- [ ] Build and GPU-smoke the final image when an OCI runtime is available; defer registry signing, multi-arch, embedded weights, and orchestration until deployment creates those requirements.
- [x] Complete compact-model Linux scientific selection, the 231-case
  Protpardelle descriptive follow-up, and the frozen Apple Silicon CPU/MPS
  portability matrix on the physical Mac.
- [x] Complete Protpardelle-1c artifact audit, Linux CPU/CUDA operator smoke,
  initial three-residue withheld-coordinate pilot, and frozen six-case v5 pilot;
  generated-only CPU refinement raises the latter from `2/6` to `6/6` hard-gate
  passes, while training-membership leakage remains unresolved.
- [x] Complete the preregistered 24-case compact-model extension: raw
  Protpardelle passes `13/24`, refinement alone passes `21/24`, and validation-
  first raw/refined selection passes `22/24` versus Protenix `23/24` and MODELLER
  `21/24`; keep the result exploratory because training leakage is unresolved.
- [x] Add and exercise the optional Protpardelle post-update callback. Corrected
  internal-frame reinjection is byte-identical across two same-seed `9dvi` runs
  and exact for all 569 represented fixed atoms, but does not improve raw geometry;
  OpenMM CPU refinement passes while remaining measurably nondeterministic.
- [x] Run corrected per-step reinjection over the frozen 24-case compact follow-up.
  Exact callback control passes all operational checks, but validation-first
  coverage is `21/24` versus `22/24` for final-only projection, so per-step
  reinjection is not selected as the compact baseline.
- [x] Diagnose OpenMM's CUDA PTX failure and add an isolated CUDA-12.2-compatible
  refinement environment with digest-verified ff19SB data. Two byte-identical
  `9dvi` runs and the 440-residue `9ina` run pass every CUDA hard gate; the full
  231-case descriptive follow-up remains pending.
- [x] Freeze the full 231-case Protpardelle descriptive-follow-up manifest before
  cohort-wide inference, with 128 gap-5 and 103 gap-10 cases, CUDA refinement,
  validation-first selection, digest-tracked code/environment inputs, and no
  replacement of failures.
- [x] Preserve the stopped v5 full-run manifest after its internal CUDA
  fixed-particle tolerance rejected `35zr`; pass the v6 standalone gate and
  freeze a successor manifest before a clean namespace restart without changing
  sampling, physical refinement, validation, selection, or cohort membership.
- [x] Complete the clean v6 231-case follow-up: Protpardelle raw passes `101/231`,
  CUDA-refined and validation-first selected output pass `217/231`; retain Linux
  evidence as immutable comparator data for the Apple portability study.
- [x] Complete the staged Apple Silicon handoff: explicit CPU/MPS device
  selection, fallback-disabled operator smoke, same-seed repeat, six-case gate,
  24-case portability pilot, 100-case operational soak, and full frozen 231-case
  run. Evidence remains descriptive because training membership is unresolved.
- [ ] Benchmark at most two adapted pretrained compact candidates before training a purpose-built local gap model.
- [ ] Train and freeze a leakage-controlled gap-only model only after the public-structure dataset and sequence-cluster splits are immutable.
- [ ] Require withheld-coordinate noninferiority and Apple memory/latency gates before any local experimental backend decision.

Detailed requirements and acceptance gates are in the
[diffusion gap-reconstruction plan](diffusion-gap-reconstruction.md).

### CUDA expansion follow-up (2026-10-19)

- [x] Share profile-specific gap-length admission across CLI, mosaic construction,
  and scientific scope; preserve separate public and research capabilities.
- [x] Independently audit withheld accuracy of all 50 full-input clean-protein
  CUDA outcomes, including rejected candidates and native-quality exclusions.
- [x] Validate adaptive queries and previous source context; do not report a
  context expansion when the policy selects no additional atoms.
- [x] Exercise deletion flanks 1–5 and reject invalid Homology requests before
  writing the normalized candidate input.
- [x] Freeze and execute generated-only CUDA refinement for all six rich cc89
  frontier outputs; retain 0/6 acceptance and two guarded chirality exceptions.
- [ ] Complete prospective long-gap noninferiority and independent review.
- [ ] Achieve scientifically acceptable rich cc89 CUDA context reconstruction;
  representation and projection alone do not close this gate.
- [ ] Complete larger independently reviewed context/CDR and Homology edit cohorts.

Evidence: [CUDA expansion completion audit](../research/cuda-expansion-completion.md).
Apple MPS follow-up is deferred until CUDA implementation completes.

## DDD Documentation Roadmap

### Phases 0-2: Foundation And Domain Contexts

- [x] Define source precedence, statuses, references, delegation, and ownership rules.
- [x] Use dependency-free TOML maps and validate syntax, links, IDs, and evidence in CI.
- [x] Map force-field naming callers, boundaries, contracts, invariants, and known gaps.
- [x] Add Force-Field Naming, Structure Identity, and Parameterization contexts.
- [x] Add their task, contract, invariant, and change-group records.
- [x] Give every `dvbfixer.domain` export an active meaning or explicit vocabulary-only status.

### Phases 3-4: Artifacts And Pipelines

- [x] Document `.dat`, structure identity, connectivity, workspace, Homology, and topology artifacts.
- [x] Record owners, producers, consumers, keys, mutation policy, atomicity, cleanup, and failure behavior.
- [x] Add Structure Preparation, Topology Generation, Diagnostics, and Workflow Execution contexts.
- [x] Document boundaries without copying algorithms and reconcile cross-context contradictions.

### Phases 5-6: Tasks And Validation

- [x] Index high-risk `.dat`, rebuild, CONECT, topology, workspace, API, and fixture changes.
- [x] Add new task records only when repeated high-risk work justifies them.
- [x] Validate TOML, metadata, paths, Markdown, linked records, evidence, sections, and indexed pages.
- [x] Add symbol checks, stale-commit reporting, generated views, or PR checks only when justified.
- [x] Keep a general Python/TypeScript AST index out of the initial rollout.

### Ongoing Maintenance

- [x] Use `docs/agent/README.md` as the canonical agent-map entry point.
- [x] Maintain shared maps, contexts, validator, and tests through one coordinating editor.
- [x] Separate implemented behavior from vocabulary, proposals, research, and gaps.
- [x] Surface unresolved contradictions instead of choosing silently.
- [x] Add context pages only when structured records cannot explain the concern.
- [x] Run agent-doc validation and `git diff --check` after every map change.
