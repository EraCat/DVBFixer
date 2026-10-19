# Structure Preparation

Status: partial

Verified on: 2026-10-02

Verified at commit: `68d878f50d069268b60250cb162da2b9adf486cb`

## Purpose

Define the bounded context from sequence-guided residue rebuilding through
heavy-atom completion, protonation, hydrogen placement, and the `.dat` handoff
to minimization. It records ownership, ordering, and externally visible
contracts; it does not reproduce scientific algorithms.

## Scope

- `src/dvbfixer/model/` owns sequence/SEQRES placement, Modeller invocation,
  restoration of PDB identity/connectivity, and modeled-atom provenance.
- `src/dvbfixer/prepare/` owns the public preparation command and the default
  broad-input `legacy` path, including mutations, heterogens, and ligand SMILES.
- `src/dvbfixer/prep_backend.py` owns the opt-in `tleap-reduce` implementation.
- `src/dvbfixer/protonate.py` owns standalone post-hoc protonation. It is not a
  ZBS stage because legacy prepare already runs PROPKA and Reduce internally.
- `src/dvbfixer/ffutils/geometry.py` owns shared rebuild, hydrogen-geometry,
  disulfide-bond, clash, and C-alpha chirality guards.
- `src/dvbfixer/ffutils/dat.py` owns the sidecar schema and merge semantics.
- `src/dvbfixer/zbs.py` owns stage order, option propagation, artifact placement,
  final numbering, cleanup, and postflight, not scientific decisions.

## Capabilities

| Capability | Status | Owner | Boundary |
|---|---|---|---|
| Sequence/SEQRES gap rebuilding | implemented | `model/pipeline.py::main` | Modeller changes protein gaps; post-processing restores retained structure context |
| Broad-input preparation | implemented | `prepare/pipeline.py::run_pdbfixer` | Default `legacy`; supports glycans, ligands, PTMs, mutations, and covalent HETATM links |
| Pure-protein tleap/Reduce preparation | implemented | `prep_backend.py::run_prep` | Opt-in; unsupported chemistry fails rather than falling back automatically |
| Protonation decisions and H placement | implemented | `protonate.py::decide_protonation`, `prepare/pipeline.py::_run_propka_reduce_variants` | Decision evidence, topology H placement, and output naming remain separate concerns |
| Preparation provenance handoff | implemented | `ffutils/dat.py::DatRecord` | Model/homology produce; prepare merges; minimize consumes |
| Experimental diffusion gap reconstruction | partial | `model/diffusion_cli.py`, `model/diffusion/contract.py`, `scope.py`, `gap_capabilities.py`, `protein_context.py`, `adaptive_context.py`, `runner.py`, `validate.py`, `pipeline.py`, `provenance.py`, `deploy/protenix-v1/production_runner.py`, `deploy/protpardelle-1c/production_runner.py` | Explicit `model --backend diffusion`, sequential batch/resume, ZBS, and GUI/Homology publish independently validated atomic bundles with digest-linked sampler traces. Protenix supports explicit joint multichain/multi-gap context and authoritative mosaic edit windows. Public length admission is shared across CLI/mosaic/scope and remains profile-specific 3–12. Longer gaps, richer cc89 CUDA context, and source-verified between-round adaptive context are implemented research slices awaiting scientific acceptance. MODELLER remains default; Apple MPS expansion is deferred until CUDA implementation completes. |
| Uniform hard L-chirality output gate | partial | `ffutils/geometry.py::assert_all_l` | Modeled candidates assert; prepare/protonate paths can only repair or warn before minimize |

## Entry Points

| Change | Start symbol |
|---|---|
| Gap-model workflow | `src/dvbfixer/model/pipeline.py::main` |
| Experimental diffusion CLI | `src/dvbfixer/model/diffusion_cli.py::run_diffusion_model` |
| Diffusion contract | `src/dvbfixer/model/diffusion/contract.py::DiffusionRequest`, `DiffusionResult` |
| Diffusion scope boundary | `src/dvbfixer/model/diffusion/scope.py::assess_diffusion_scope` |
| Diffusion pipeline | `src/dvbfixer/model/diffusion/pipeline.py::run_diffusion_pipeline` |
| Diffusion adapter preflight | `src/dvbfixer/model/diffusion/preflight.py::assess_adapter_preflight` |
| Diffusion provenance | `src/dvbfixer/model/diffusion/provenance.py::DiffusionProvenanceManifest` |
| Proposed diffusion CPU benchmarks | `src/dvbfixer/model/diffusion/benchmark.py::assess_same_seed_repeatability` |
| Proposed diffusion sampler conformance | `src/dvbfixer/model/diffusion/sampler.py::assess_sampler_conformance` |
| Diffusion runner boundary | `src/dvbfixer/model/diffusion/runner.py::run_diffusion_runner` |
| Internal RFdiffusion v1 benchmark adapter | `src/dvbfixer/model/diffusion/rfdiffusion_v1.py::run_adapter` |
| Diffusion validation boundary | `src/dvbfixer/model/diffusion/validate.py::validate_runner_result`, `build_validated_result` |
| Legacy atom completion | `src/dvbfixer/prepare/pipeline.py::run_pdbfixer` |
| Backend selection/final prepare writes | `src/dvbfixer/prepare/pipeline.py::main` |
| tleap/Reduce behavior | `src/dvbfixer/prep_backend.py::run_prep` |
| Standalone protonation | `src/dvbfixer/protonate.py::main` |
| Missing-atom rebuild policy | `src/dvbfixer/ffutils/geometry.py::rebuild_missing_atoms_with_retry` |
| Sidecar schema/merge policy | `src/dvbfixer/ffutils/dat.py::DatRecord` |
| Full pipeline order/propagation | `src/dvbfixer/zbs.py::_run_pipeline` |

## Contracts

- Scientific stages consume normalized PDB. CIF normalization and chain mapping
  belong at the CLI boundary; do not add stage-local CIF readers.
- PDB identity is case-sensitive. Atom identity is `(chain, resid, icode, atom)`;
  variant identity is `(chain, resid, icode)`. Preserve `keepIds=True` on every
  `PDBFile.writeFile` call.
- `DatRecord` is the only `.dat` reader/writer. `added_atoms` uses four-field
  atom identity; `variant_overrides` serializes as `chain:resid:icode`;
  `total_added` is derived. Merge deduplicates atoms and gives the downstream
  record precedence on variant collisions.
- Model marks every atom in a rebuilt residue as added. Prepare records its own
  additions and merges an adjacent upstream sidecar when found. Minimize
  re-resolves those identities against its final topology before restraint use.
- Diffusion is explicit opt-in and never falls back to MODELLER or another
  profile/device. Its `-o` destination is a new directory bundle; MODELLER keeps
  the existing file-output contract.
- Supplied ligand SMILES is authoritative for mapped, isolated, single-residue
  molecules. It is legacy-only, incompatible with heterogen stripping and
  disabled heterogen-H placement, and must fail rather than guess on an
  incompatible, ambiguous, or covalently attached target.

## Invariants

- Legacy PDBFixer order is fixed: `findMissingResidues` plus deletion scrub,
  `findNonstandardResidues`, `replaceNonstandardResidues`, `removeHeterogens`,
  `findMissingAtoms`, then rebuild. Topology-rebuilding calls invalidate
  residue-object-keyed missing-atom data.
- Never call `fixer.addMissingAtoms()` directly. Call
  `rebuild_missing_atoms_with_retry`; it owns explicit seeds, retries, topology
  snapshots, and post-attempt chirality/clash checks.
- Legacy PROPKA/Reduce runs only after heavy-atom rebuilding and chirality
  repair. Hydrogen placement uses `Modeller.addHydrogens(variants=...)`, never
  `PDBFixer.addMissingHydrogens`.
- Follow every legacy `Modeller.addHydrogens` call with
  `repair_misplaced_hydrogens`. Preserve the shared variant-parent rename and
  post-hydrogen restoration flow.
- Explicit disulfide evidence forces CYX and genuine SG-SG bonds survive bond
  cleanup; extra SG-SG partners are reduced to one partner per sulfur.
- Any stage claiming a hard chirality gate must run `assert_all_l` after the
  final heavy-atom coordinate change. ZBS catches `ChiralityError`; minimize is
  the unconditional final safety net for warn-only preparation paths.
- Model performs CONECT inference before Modeller, uses shared affine sequence
  placement, restores chain/residue identity, makes atom serials unique, then
  remaps retained CONECT records. Bare `TER` records must remain newline-ended.
- `--number-from-1` applies to each model candidate and matching sidecar, but in
  ZBS only to the copied final output before postflight. Never renumber an
  intermediate sidecar independently of its PDB.

## Callers

- The command dispatcher invokes `model`, `prepare`, `protonate`, and `zbs`.
- ZBS orders `renumber -> model -> prepare -> minimize`; any stage may be
  skipped. It forwards sequence, heterogen, CONECT, force-field, backend,
  protonation, mutation, cap, SMILES, and minimization options to their owners.
- `minimize/pipeline.py` consumes the prepared PDB and merged sidecar. Homology
  can publish a model plus stub sidecar before invoking preparation/minimization.

## Adapters

- Modeller supplies sequence-guided coordinates. PDBFixer supplies legacy
  topology repair. OpenMM Modeller supplies legacy protein H placement.
- tleap supplies opt-in heavy-atom completion; Reduce supplies H placement and
  local HIS/ASN/GLN evidence; PROPKA supplies pKa evidence. Python owns evidence
  precedence and identity preservation.
- RDKit/Open Babel handle unmapped legacy heterogens. SMILES graph matching is a
  distinct authoritative adapter and does not inherit the requested protein pH.
- PDB fixed-column rewrites, subprocess execution, temporary files, and `.dat`
  JSON are adapters around the scientific stage contracts.

## Side Effects

- Model may materialize an inferred-CONECT input, creates a temporary workspace,
  and writes one or more candidate PDBs with candidate-matched sidecars when
  provenance exists. The no-SEQRES/no-FASTA shortcut only copies the PDB.
- The diffusion scope boundary verifies the normalized-input digest
  before parsing and returns explicit unsupported reasons for out-of-slice target
  sequence, gap, model, altloc, chemistry, heavy fixed-mask, placement, retained
  source-link, and detectable D-chirality cases. The runner creates an isolated
  workspace, copies and verifies the normalized input, writes `request.json`,
  launches one shell-free child process with bounded diagnostics, then verifies a
  raw `RunnerResult` manifest and candidate digests. Runner-provided data cannot
  claim independent validation. Validation reopens verified source/candidate
  artifacts, applies first-slice hard gates, calls final `assert_all_l`, rejects
  failed candidates, and deterministically ranks passing candidates without
  treating backend-native scores as commensurate. The pipeline launches
  no runner for unsupported scope, publishes nothing for failed results, builds
  each candidate `.dat` through `DatRecord`, writes sanitized separate provenance,
  fsyncs a hidden same-parent bundle, and exposes the complete set with one
  atomic no-replace directory rename. The public single-input `model` dispatcher
  builds the request and requires an explicit profile, runner, and local
  checkpoint. Local adapter preflight checks executable,
  immutable image identity, checkpoint presence/digest, CUDA availability, and
  protocol compatibility without downloading artifacts. Sampler conformance
  keeps ordinary template conditioning distinct from evidence-backed per-step
  reinjection and boundary refinement. Batch, GUI, ZBS, and Homology do not
  expose this path.
- Legacy prepare can create temporary inferred, renamed, deletion-cleaned,
  capped, GLYCAM, PROPKA, and canonical-CONECT PDBs. It writes/replaces the
  output PDB and sidecar and may rewrite the output for variants, heterogen H,
  CONECT, force-field naming, and terminal normalization.
- The tleap backend creates an isolated temporary directory, launches `tleap`
  and `reduce`, restores residue metadata, and includes subprocess diagnostics
  in failures. It writes a prepared PDB and sidecar.
- Protonate launches configured decision engines, writes one PDB, and creates
  sanitized/intermediate temporary PDBs. It does not publish a `.dat` sidecar.
- ZBS places named intermediates beside the final output, optionally aligns each
  stage to the original input, deletes tracked intermediates unless retained,
  and writes a diagnose JSON report unless postflight is disabled.

## Known Divergences

- `legacy` is the default and broad-input backend. `tleap-reduce` is opt-in,
  pure-protein-oriented, rejects `--mutate` and SMILES, and bypasses final
  `apply_variants_to_pdb_text` shifts that would break OpenMM terminal templates.
- Prepare's tleap wrapper always runs Reduce and variant assignment; it does not
  currently honor `--no-propka` or `--no-protassign`. Standalone tleap protonate
  uses `--no-propka` only to disable variant assignment and still runs Reduce.
- Legacy prepare degrades PROPKA/Reduce failures to reduced evidence. Standalone
  legacy protonate requires at least one engine and treats missing default
  Reduce, empty required PROPKA results, and H-placement failures as fatal.
- Model's no-gap sidecar emits legacy two-field variant keys, and model/protonate
  still contain local two-field variant restoration maps. These are known gaps,
  not alternatives to the three-field `DatRecord` identity contract.
- Model's rebuilt-candidate path hard-asserts L chirality. Legacy prepare repairs
  before H placement without a final assertion; tleap prepare and both protonate
  paths warn on residual D centers. Standalone outputs therefore have a weaker
  guarantee than a completed ZBS run through minimize.
- tleap metadata restoration is residue-ordinal-based and leaves unmatched extra
  output residues unchanged; supported pure-protein input is expected to keep
  residue order and count stable.

## Proposed Work

- Make protonation flags consistent across backends and migrate remaining local
  variant maps to insertion-code-aware identity.
- Add uniform final `assert_all_l` gates before changing the page status to
  `implemented`.
- No geometry-regularization backend is shipped. The
  [`whole-complex relaxation note`](../../research/whole-complex-relaxation.md)
  is research, not current preparation behavior.
- Alternative atom-reconstruction, loop-modeling, and homology-modeling
  backends remain research or proposed work. The accepted
  [`experimental diffusion boundary ADR`](../../adr/0010-experimental-diffusion-gap-reconstruction-boundary.md)
  and its [`public CLI successor`](../../adr/0011-experimental-diffusion-cli.md)
  fix the isolation, provenance, no-fallback, default-backend, narrow-scope, and
  profile-evidence policies. See
  the [`reconstruction and modeling backend note`](../../research/reconstruction-and-modeling-backends.md),
  its versioned
  [`diffusion research inventory`](../../research/diffusion-gap-reconstruction-inventory.toml),
  and the active
  [`diffusion gap-reconstruction implementation plan`](../../plans/diffusion-gap-reconstruction.md).
  PDBFixer and Salilab MODELLER remain supported production baselines; the
  experimental diffusion CLI does not deprecate either dependency.

## Focused Verification

```bash
pytest -q tests/test_ffutils_dat.py tests/test_ffutils_chirality.py \
  tests/test_seeded_atom_rebuild.py tests/test_model_renumber.py \
  tests/test_model_fasta_case.py tests/test_model_strip_heterogens.py \
  tests/test_prep_backend_variants.py tests/test_prepare_icode_variants.py \
  tests/test_prepare_input_file_safety.py tests/test_prepare_propka_integration.py \
  tests/test_prepare_smiles.py tests/test_ffutils_variants.py \
  tests/test_zbs_postflight.py
python scripts/check_agent_docs.py
git diff --check -- docs/agent/contexts/structure-preparation.md
```

External-tool and end-to-end coverage lives in
`tests/test_prepare_by_input_class.py`, `tests/test_zbs_e2e.py`, and
`tests/test_zbs_shit_inputs.py`. Use `--no-solvent` for development ZBS runs.
