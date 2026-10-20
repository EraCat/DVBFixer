# Plan status and remaining work

Updated 2026-10-20. This is a navigation/status summary, not a new implementation
proposal. The [implementation checklist](implementation-checklist.md) is the
canonical completion tracker; older milestone lists in individual plans may
describe historical stages, capability requirements or optional experiments.
An unchecked historical box alone does not prove that code is still missing.

## Current status

| Plan | Implemented / completed | Remaining boundary |
|---|---|---|
| [API roadmap](api-roadmap.md) | Naming service/CLI/V1 HTTP API, standalone host, auth/ACL, CORS, quotas, versioned workflows and single-host multi-process coordination | Acceptance on the operator's deployment host; external scheduling/state before multi-host operation |
| [API/DDD continuation](api-ddd-continuation-context.md) | Historical handoff, not a second backlog | Consult the checklist and agent contexts rather than old next-session instructions |
| [DDD documentation](ddd-documentation-roadmap.md) | Domain/artifact/pipeline/task maps and validation foundation | Demand-driven maintenance; advanced automation only if justified |
| [Diffusion reconstruction](diffusion-gap-reconstruction.md) | Contracts, masks, validation, provenance, publication and bounded experimental CLI/Homology paths | Additional-scope evaluation, selected geometry-policy refinements and separate production/default decision |
| [CLI integration](diffusion-cli-integration.md) | Runtime discovery, Doctor, batch/resume, ZBS handoff, GUI and mosaic-first Homology | Broader hardware/scientific acceptance, not missing basic wiring |
| [Runner environments](diffusion-runner-environments.md) | Separate core/ML runtimes, pinned Protenix lock and public GPU smokes; corrected Apple launcher with isolated CPU refinement | Protenix production-wrapper full-cohort replay and final OCI image build/GPU smoke |
| [Linux expansion](linux-diffusion-expansion.md) | Measurement/context/workflow slices, profile-specific admission and corrected public cc89 CUDA | Long-gap review, larger context/CDR/Homology cohorts; validation-policy WP3 remains paused pending a separate decision |
| [Compact/Apple research](small-diffusion-apple-silicon-experiments.md) | Compact-model selection, historical 231-case studies, corrected Apple pilot and public integration | Larger corrected-mode operational cohort and training-membership uncertainty; own-model training is optional research |
| [Apple handoff](apple-cc89-handoff.md) | Corrected research 8/8 and public model/Homology 5/5, multi-seed publication and exact replay | Larger memory/latency/operational cohort; no wider acceptance or default change |
| [Heterogen context](diffusion-heterogen-gap-reconstruction.md) | Narrow isolated-SMILES geometric context on the legacy MPS profile | Chemistry-specific studies for cofactors, metals, glycans, PTMs and covalent contexts; corrected cc89 remains protein-only |
| [Nonprotein reconstruction](nonprotein-reconstruction-parameterization.md) | Offline Class A reconstruction, bounded CCD information and opt-in CLI | Linked/metal/redox classes, online reconstruction authority, dedicated GUI and actual MD parameterization gates |
| [Dependency audit](environment-dependency-audit.md) | Audit proposal and existing separate ML runtimes | Optional installation-profile migration, full dependency evidence and clean-install smokes before slimming |
| [Amber19SB topology](amber19sb-gromacs-topology.md) | Protein-only backend, upstream provenance and six water/ion pairs; external preprocessing tests now exercised | No mixed-chemistry or MD-trajectory acceptance is implied |
| [Tarantino removal](remove-tarantino-mutation-cluster.md) | Complete; historical provenance remains readable | No active removal backlog |

## Evidence, not scope expansion

- [Baseline repairs](../research/baseline-repair-2026-10-20.md): core/GUI failures
  corrected, current test results and Amber19SB preprocessing scope.
- [Workflow integration](../research/diffusion-workflow-integration.md): batch,
  ZBS, Homology and GUI custody/archival; public Linux checkpoint-backed smokes.
- [CUDA acceptance](../research/cc89-public-cuda-acceptance.md): five candidates
  in four bounded public workflows; not general long-gap acceptance.
- [Apple public acceptance](../research/cc89-public-apple-acceptance.md): 5/5,
  retained failed development evidence and no-sampling frozen replay.
- [Nonprotein status](nonprotein-reconstruction-parameterization.md): successful
  reconstruction geometry does not mean MD-ready chemistry.
- [Whole-complex relaxation](../research/whole-complex-relaxation.md): a proposed
  backend and benchmarks, not an existing minimization option.

Useful next work is the larger corrected-Apple operational cohort, targeted
independent scientific cohorts, or chemistry/deployment work driven by actual
inputs. Do not start custom training, multi-host scheduling or broad chemistry
support merely because an old roadmap lists them.
