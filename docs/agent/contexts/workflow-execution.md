# Workflow Execution

Status: partial

Verified on: 2026-09-21

Verified at commit: `425f290eb85760246766f1d1500e51672c640b2d`

## Purpose

This context describes how a requested DVBFixer operation becomes a process,
files, logs, job state, and workspace artifacts. It distinguishes the shipped
Python CLI and versioned local HTTP API from public-host acceptance work.

Scientific behavior remains in Python command modules. The Node layer resolves
workspace-owned inputs, starts the CLI, records execution, and publishes files;
it must not reproduce preparation, modeling, or chemistry policy.

## Scope

Current behavior covers synchronous CLI dispatch, directory batch execution,
the in-process ZBS pipeline, CIF normalization at the CLI boundary, revisioned
GUI workspaces, and managed jobs hosted through shared Node route composition.

The HTTP routes are authenticated application infrastructure with a documented
single-host Ubuntu/systemd deployment profile behind a TLS proxy. Target-host
acceptance is still required before public exposure. Static bearer principals,
manifest-backed workspace authorization, the first versioned route, and OpenAPI
are implemented. Restrictive CORS, bounded imports, workspace accounting, and a
process-wide FIFO child limit are also implemented. A bounded pre-authentication
direct-client request limiter protects every API route. Versioned managed jobs,
durable audit events, and same-host cross-process coordination are implemented.
The reference privileged OS-limit profile passed CI acceptance; each deployment
still needs its own host/TLS/resource-enforcement acceptance. Multi-host scheduling
remains unsupported. See [deployment](../../deployment.md).

## Capabilities

| Capability | Status | Owner | Failure effect |
|---|---|---|---|
| Single-command CLI dispatch and logging | implemented | `cli.py::main` | command exit/exception propagates; files already written are not rolled back |
| Per-file directory batch execution | implemented | `batch.py::run_directory` | continue by default or stop with `--fail-fast`; successful outputs remain |
| CIF-to-PDB command boundary | implemented | `structure_input.py::normalized_command_inputs` | conversion fails before command execution; temporary normalized inputs are removed |
| ZBS stage orchestration | implemented | `zbs.py::_run_pipeline` | aborts at the failing stage; existing intermediates can remain |
| Revisioned workspace manifests | implemented | `workspace-api.ts`, `workspace-lock.ts` | same-host writers serialize and stale client revisions return 409; locks are not distributed |
| Persisted, cancellable local jobs | implemented | `managed-jobs.ts`, `workspace-lock.ts` | capped logs and state persist; same-host processes share run locks, cancellation markers, and SSE polling |
| Duplicate synchronous GUI command route | removed | `api-routes.ts` | callers use versioned managed jobs; naming retains its dedicated synchronous V1 endpoint |
| Versioned production workflow API | partial | `managed-jobs.ts`, `naming-api.ts` | versioned routes ship; target-host public acceptance is pending |

## Entry Points

- `src/dvbfixer/cli.py::main` extracts global runtime options, resolves the
  command through `command_registry.py`, wraps it in CIF normalization, and
  invokes it directly or through directory batch mode.
- `src/dvbfixer/batch.py::run_directory` derives one output per supported input
  and calls the same normalized single-file command independently.
- `src/dvbfixer/zbs.py::_run_pipeline` calls renumber, model, prepare, and
  minimize in one Python process, then copies the last result to the final path.
- `gui/server/managed-jobs.ts::createManagedJob` is the GUI's primary command
  execution path; `/api/v1/workspaces/{workspaceId}/jobs` provides creation, listing, detail, SSE, and
  cancellation.
- `gui/server/api-plugin.ts::apiPlugin` composes the same routes in Vite; the
  synchronous generic command route has been retired.

## Contracts

**CLI command contract.** `command_registry.py::CommandSpec` owns command
module, output mode/kind, batch suffix, and accepted success codes. The CLI
imports each command's `main` and passes argv; argparse and `SystemExit` remain
the command boundary. Global logging and batch flags are removed first. Registry
success codes are transport metadata; batch mode separately treats `diagnose`
exit 1 as findings rather than an execution failure.

**Normalization contract.** CIF inputs are converted once to temporary PDBs
below the output/work directory. Related chain selectors, FASTA headers, and
template plans are translated. User-visible PDB outputs receive chain-map
remarks; downstream scientific commands remain PDB-based.

**ZBS artifact contract.** Named intermediates and `.dat` sidecars are created
beside the final output, including in batch mode. The final PDB is copied before
number-from-one normalization and postflight diagnose. Cleanup occurs only at
normal pipeline completion unless `--keep-interim` is set.

**Workspace contract.** `workspace.json` is authoritative for visible
artifacts and selections. `saveWorkspace` atomically replaces JSON and
increments `revision`. Revision-aware PUT/PATCH and metadata updates must match
the current revision; artifact files are workspace-relative and containment
checked, including against symlink escape. Current workflow requests identify
inputs by these relative `file` values, not by artifact ID. Historical Antibody
Engineer artifacts remain readable: `mutationsResolved` is preserved provenance
and `mutationIds` is an opaque legacy field, with no resolution or new-write
path.

**Managed-job contract.** `runs/job_<uuid>/job.json` is written in `queued`
state before asynchronous execution, then transitions through `running` to
`succeeded`, `failed`, or `cancelled`. It records argv, timestamps, exit code,
log paths, output directory, and primary output path. At most one current run
is allowed per workspace across processes sharing one local data root. Creation returns 202; DELETE
requests cancellation and also returns 202 without claiming the process has
already exited.

## Invariants

- Batch ZBS never writes named intermediates or sidecars into the source tree;
  they follow the final output directory.
- Every GUI workflow input resolves from the named workspace and cannot escape
  its root through `..`, an absolute path, or a symlink.
- Workspace artifact identity is the manifest artifact `id`; `file` is a
  contained relative storage location. Current workflow transport still accepts
  `file`, while the production proposal requires ID lookup. Protected manifests
  are never artifacts.
- Client revision conflicts must not overwrite newer tool state or newly
  registered artifacts. Frontend retries rebase only pending fields.
- Managed jobs publish artifacts only after exit code zero. Failure and
  cancellation leave the viewer and manifest artifact list unchanged, although
  private partial files may remain in the job directory.
- Scientific materialization stays in Python. TypeScript may validate,
  resolve, schedule, capture, and register, but must not duplicate science.
- CLI CIF normalization remains the single format boundary.
- The V1 naming route accepts a workspace artifact ID rather than a caller path,
  validates the CLI report and digest, and re-reads the latest manifest before
  registering exactly one output. Dry runs and failures register nothing.

## Callers

- Shell users and automation call `dvbfixer <command>` or global batch mode.
- `zbs` is both a public command and a caller of four command modules.
- `gui/src/components/DVBFixerPanel.tsx` creates/restores managed jobs, follows
  SSE with polling fallback, requests cancellation, reloads the workspace on
  success, and opens the primary structure output.
- Homology has a specialized orchestrator. It shares workspace containment and
  artifact registration concerns but is not managed by the generic job record
  lifecycle documented here.

## Adapters

- `structure_input.py` adapts CIF inputs to internal PDB argv and temporary
  files.
- `runtime.tee_output` captures Python and inherited child stdout/stderr for
  CLI terminal/log output.
- `batch.py` adapts a directory into isolated single-input invocations.
- `dvbfixer-runner.ts` adapts a command plus argv to a child process. It uses a
  configurable executable/prefix, bounded capture, timeout, abort signal, and
  Unix process-group `SIGTERM` where available, followed by `SIGKILL` after a
  configurable grace period if the child does not exit.
- `workspace-api.ts` adapts workspace-relative paths and manifests to local
  filesystem storage.
- `api-plugin.ts` is a Vite composition adapter, not a production server.
- `api-routes.ts` is the host-neutral composition root; `api-plugin.ts` is its
  thin Vite adapter and `standalone.ts` is the loopback-default Node host.
- `naming-api.ts` is the synchronous artifact-ID-based V1 naming adapter;
  `naming-api-schema.ts` supplies its runtime and OpenAPI contracts.

## Side Effects

CLI commands write directly to command-selected outputs. Batch mode creates the
output tree and preserves successful files even when the overall batch exits 1.
It does not remove a failed command's partial destination.

ZBS may write intermediates, candidate models, `.dat` sidecars, the final PDB,
and `<output>.diagnose.json`. A non-strict ERROR finding warns and succeeds. A
strict finding raises after the final PDB/report were written. Earlier stage
failure bypasses end-of-pipeline cleanup.

Managed jobs create a private run directory and atomic `job.json`. stdout and
stderr are captured in memory, capped independently, and written to log files
when the process ends. Successful runs register all non-control files and bump
the workspace revision when at least one output exists. Failed/cancelled runs
retain their directory, logs, and possible partial outputs but register none of
them. Cancellation sends SIGTERM to the process group on Unix (the child on
Windows); terminal state is recorded only after the child closes.

The managed route honors the registry's accepted success codes; a `diagnose`
finding (exit 1) is a successful report with a registered artifact.

## Known Divergences

- Managed SSE emits persisted job snapshots, not live stdout/stderr chunks;
  capped logs become files after process completion.
- Workspace JSON replacement is atomic and every manifest publisher holds a
  same-host cross-process lock. `saveWorkspace` compares the caller revision to
  the locked on-disk revision; additive server publishers mutate the locked
  latest manifest. Output-file creation plus manifest registration remains a
  compensating transaction rather than one filesystem transaction.
- On server restart, loading an orphaned queued/running record marks it failed;
  there is no durable worker reconciliation or resume.
- Durable workspace run locks, cancellation markers, and polling of persisted
  jobs coordinate processes sharing one local filesystem on the same host.
  Multiple hosts and network filesystems are unsupported.
- Workspace quotas are logical-byte publication checks, not OS filesystem
  quotas; child output may exist before publication and failed/trash data counts.
- Cancellation and timeout have process-kill escalation; cross-process
  cancellation requests use a durable marker removed at terminal state.
- The static GUI build does not ship these Vite backend routes.
- The standalone build ships all routes with static bearer authentication and
  workspace ACLs, restrictive CORS, application quotas, and child concurrency
  limits, but remains unsuitable for untrusted networks without TLS, OS-level
  enforcement acceptance on the target host and a TLS boundary. Multi-host
  scheduling requires an external coordination service.

## Proposed Work

Complete the privileged deployment acceptance in
[`../../deployment.md`](../../deployment.md) on the actual systemd host. A
future multi-host service needs an external scheduler, distributed child
admission, and a shared state store; this repository currently supports
multiple processes sharing one local data root on one host.

## Focused Verification

```bash
pytest -q tests/test_batch.py tests/test_structure_input.py \
  tests/test_zbs_postflight.py tests/test_cli_runtime.py \
  tests/test_command_registry.py
python scripts/check_agent_docs.py
cd gui && npm test -- --run server/workspace-api.test.ts \
  server/managed-jobs.test.ts server/dvbfixer-runner.test.ts \
  src/lib/managed-jobs.test.ts
```
