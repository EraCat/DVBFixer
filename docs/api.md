# DVBFixer API

DVBFixer exposes versioned HTTP operations through a host-neutral Node
route composition shared by the Vite development adapter and the bundled
standalone server. Static bearer authentication and manifest-backed workspace
authorization, restrictive browser-origin handling, request-rate and workspace/
upload limits, and process-wide child concurrency limits are available. The host
supports the documented single-host Ubuntu/systemd deployment profile behind a
TLS-terminating proxy. Each installation must pass resource-enforcement
acceptance on its own host before opening internet access.

Workspace manifests and active runs use same-host cross-process filesystem
locks. Cancellation markers and persisted-record polling deliver job state to
other local processes. This requires one shared local data root with atomic
filesystem operations and reliable process identity. It does not support
multiple hosts or network filesystems; crash recovery marks interrupted jobs
failed rather than rerunning them.

A Linux systemd/cgroup-v2 profile for aggregate OS resource containment is
available in [`deployment.md`](deployment.md). The reference Ubuntu 24.04
profile passed privileged acceptance in CI; a real host still needs its own
trusted TLS certificate, operational controls, and acceptance record.

The OpenAPI 3.1 document is available at:

```http
GET /api/v1/openapi.json
```

Runtime validation and OpenAPI are generated from the same TypeBox schemas in
`gui/server/naming-api-schema.ts` and `managed-jobs-schema.ts`.
`gui/openapi.json` and `gui/src/generated/dvbfixer-api.ts` are checked-in
artifacts. Run `cd gui && npm run gen:openapi` after a schema change;
`npm run check:openapi` enforces synchronization in CI. The GUI uses the
generated client for managed jobs and synchronous naming requests, and the
authenticated transport for SSE.

## Managed Workflows

`POST /api/v1/workspaces/{workspaceId}/jobs` starts a managed command and
returns `202` with a persisted job record. `GET` on the same path lists jobs;
`GET /api/v1/workspaces/{workspaceId}/jobs/{jobId}` reads one record;
`DELETE` requests cancellation; and `GET .../{jobId}/events` streams persisted
record changes as server-sent events. Job records contain status, logs, output
location, and provenance. Workspace artifact downloads use the existing
workspace API. Every current CLI command except `atom-names` is a managed
workflow, including `diagnose`, `conect`, `renumber`, `prepare`, `minimize`,
`model`, `zbs`, and parameterization. Naming is the bounded synchronous
transform. An unsupported command returns `422`.

For example, after importing `input.pdb` into a workspace, start a diagnostic
job with a workspace-relative file name:

```http
POST /api/v1/workspaces/{workspaceId}/jobs
Authorization: Bearer <token>
Content-Type: application/json

{"command":"diagnose","inputFile":"input.pdb"}
```

The response is a `202` job record. Poll its `GET` URL or subscribe to its
`/events` stream until the status is `succeeded`, `failed`, or `cancelled`.
`inputFile` and entries in `inputs` must resolve inside that workspace; the
request cannot pass an unrestricted server path. Command-specific flags go in
`values` using their CLI flag names, such as `{"--no-solvent":true}`.

Input files are resolved inside the authorized workspace. Each published
output artifact records the command, request options, input artifact identities
and SHA-256 digests, service/DVBFixer versions, and output SHA-256 digest.
Commands writing to stdout publish a `.txt` or `.json` artifact. Terminal job
records and artifacts provide structured status and provenance; diagnostic
command output remains in its native CLI format. Jobs interrupted by a server
crash are marked failed on recovery and can be submitted again explicitly.

V1 compatibility and deprecation rules are in
[`ADR 0009`](adr/0009-versioned-workflows-and-compatibility.md). The old
`/api/jobs` and synchronous `/api/dvbfixer/:command` routes have been retired.

## Authentication

`GET /api/health` and `GET /api/v1/openapi.json` are public. Every other API
route requires:

```http
Authorization: Bearer <43-character base64url token>
```

Missing or invalid credentials return `401` with `WWW-Authenticate: Bearer`.
The protected `GET /api/session` endpoint returns the authenticated principal.
Tokens are stored only in browser `sessionStorage` and are never sent in URLs.

Configure token digests, not raw tokens:

```bash
node -e "const c=require('node:crypto');const t=c.randomBytes(32).toString('base64url');console.log('token:',t);console.log('sha256:',c.createHash('sha256').update(t).digest('hex'))"
export DVBFIXER_AUTH_PRINCIPALS='{"version":1,"principals":[{"id":"alice","tokenSha256":"<sha256>"}]}'
```

Keep the printed token for the client and place only its digest in server
configuration. With multiple principals, set
`DVBFIXER_LEGACY_WORKSPACE_OWNER` to the principal that should own existing
workspaces.

Workspace manifests contain one owner and optional `reader`/`writer` ACL
entries. Unlisted principals receive `404`; readers receive `403` for writes.
Owners update sharing through the revisioned
`PATCH /api/workspaces/{workspaceId}/acl` endpoint.

## Naming Conversion

```http
POST /api/v1/workspaces/{workspaceId}/naming-conversions
Content-Type: application/json
```

The operation converts PDB residue and atom names through `dvbfixer atom-names`.
It accepts an artifact ID, never a filesystem path, and resolves the artifact
inside the named workspace with traversal and symlink containment checks.
`target.forceField` accepts `amber`, `amber19sb`, or `charmm`. The two AMBER
values are distinct naming dialects; `amber19sb` matches the bundled ff19SB RTP
cap and terminal names under the `gromacs` profile. `target.profile` accepts
`gromacs` or `standard` and is required by the API request schema (the CLI defaults
to `gromacs`). `standard` selects native force-field names and normalizes supported
consumer aliases. It is a naming operation, not force-field parameterization or
a general inverse for arbitrary naming schemes; see the
[naming guide](commands/atom-names.md#naming-profiles).

```json
{
  "inputArtifactId": "2a4d4d4e-2c82-4ea0-98ef-92df4cdd57f0",
  "target": {
    "forceField": "amber",
    "profile": "gromacs"
  },
  "variantOverrides": [
    {
      "chainId": "H",
      "residueNumber": "82",
      "insertionCode": "A",
      "variant": "HIE"
    }
  ],
  "outputName": "complex_gromacs.pdb",
  "dryRun": false
}
```

`variantOverrides`, `outputName`, and `dryRun` are optional. Overrides use exact,
case-sensitive chain, residue-number, and insertion-code identity. V1 accepts
PDB artifacts (`.pdb` or `.ent`) only. The artifact must be a visible workspace
`structure` whose contained source resolves to a regular file. Extension
matching is case-insensitive. The server generates an output name when one is
omitted, including the selected force field and profile in the default filename.
The GUI's Atom Names Run action calls this endpoint, never `/jobs`.

Optional `inferProtonation: true` forwards `--infer-protonation` to the Python
CLI: identify supported titratable variants from names and observed site H before
dialect conversion. Omitted/false preserves the existing name-only behavior.
Explicit overrides remain authoritative. Diagnostics distinguish identified,
conflicting and unresolved H patterns; no H rebuilding or pKa prediction occurs.
See [identification limits](commands/atom-names.md#optional-identification-from-observed-hydrogens).
The report and published provenance record the enabled option; Node verifies
that the CLI acknowledged the requested inference mode before publication.

A successful conversion returns `201` and registers exactly one new structure
artifact. Its manifest metadata records the source artifact ID, request options,
hosting-service and DVBFixer package versions, operation/report schema versions,
and source/report/output SHA-256 digests. Helper reports, overrides, and logs are removed before
successful publication. A successful dry run returns `200`, includes the same conversion
result and candidate digest, and does not change the manifest or retain output.

All failures use a versioned error envelope with a request ID:

```json
{
  "error": {
    "code": "NAMING_COLLISION",
    "message": "Target atom name already exists",
    "details": {},
    "requestId": "req_..."
  }
}
```

Every request reaching the shared `/api` composition receives a server-generated
`X-Request-Id`; client-supplied values are ignored. V1 error envelopes reuse the
same ID. Allowed cross-origin responses expose this header.

## Access Logs

Set `DVBFIXER_ACCESS_LOG=json` to emit one compact JSON record to stdout when an
API response finishes or aborts. The default is `off`. Records use schema
`dvbfixer.http_access.v1` and include the request ID, method, coarse route label,
status, monotonic duration, completion outcome, and authenticated principal ID.

Logs intentionally omit headers, bearer credentials, client addresses,
forwarded headers, query strings, request/response bodies, workspace and
artifact IDs, filenames, subprocess output, exception messages, and raw paths.
Client-supplied request IDs are never trusted. Route labels are bounded templates
or coarse API groups to avoid sensitive high-cardinality data.

This access log covers
the shared API composition, including CORS, rate-limit, authentication, public
endpoint, route, and unknown-API responses. A standalone loopback Host-header
rejection occurs before that boundary and is not included.

Set `DVBFIXER_AUDIT_LOG=jsonl` to append durable `dvbfixer.audit.v1` events to
`<data-root>/_audit/audit-YYYY-MM-DD.jsonl` (private directory and mode `0600`
files). The default is `off`. Events cover V1 requests, mutations, and denied
authentication/authorization. Each contains a timestamp, request ID, principal
ID when authenticated, method, bounded route label, status, and outcome;
credentials, request contents, filenames, and scientific data are omitted.
`DVBFIXER_AUDIT_RETENTION_DAYS` defaults to 90 (range 1–3650); expired daily
files are removed on the next event after midnight. Back up or ship these
records according to the deployment's retention requirements. A disk error is
reported to the service log; operators must monitor it to ensure audit delivery.

## Metrics

Set `DVBFIXER_METRICS=prometheus` to enable the protected `GET /api/metrics`
endpoint. The default is `off`. It returns Prometheus text format with bounded
HTTP request counters, route-only duration histograms, active-request gauges,
and DVBFixer child-process active/queued/limit/admission gauges.

Metrics never label by principal, request ID, client address, workspace,
artifact, job, filename, raw path, query, command arguments, exception text, or
subprocess output. The scrape excludes itself from HTTP metrics. Metrics are
process-local and reset on restart; scrape each instance independently and
aggregate externally. Scrapes remain authenticated and rate-limited.

Scientific conversion failures use their stable Python error codes and HTTP
`422`. Transport and workspace failures use API-specific codes. Unexpected
subprocess and filesystem details are not returned to clients.

The naming service's stable `422` codes are `INVALID_VARIANT`,
`AMBIGUOUS_VARIANT`, `MALFORMED_PDB`, `MULTI_MODEL_UNSUPPORTED`,
`NAMING_COLLISION`, and `UNSUPPORTED_NAMING_DIRECTION`. Request validation
returns `400 INVALID_REQUEST` or `INVALID_JSON`; a changed source returns
`409 SOURCE_ARTIFACT_CHANGED`; incompatible inputs return
`415 UNSUPPORTED_SOURCE_FORMAT`; an oversized input returns
`413 SOURCE_TOO_LARGE`; and timeout returns `504 NAMING_TIMEOUT`.
New codes may be added within V1, but existing meanings and status mappings
follow [ADR 0009](adr/0009-versioned-workflows-and-compatibility.md).

## Limits

The JSON body uses the shared 2 MiB request limit. General server defaults are:

| Environment variable | Default | Purpose |
|---|---:|---|
| `DVBFIXER_GUI_MAX_UPLOAD_BYTES` | 256 MiB | Maximum workspace import request body |
| `DVBFIXER_GUI_WORKSPACE_QUOTA_BYTES` | 5 GiB | Logical bytes per workspace; `0` disables |
| `DVBFIXER_MAX_CONCURRENT_PROCESSES` | 1 | FIFO child-process limit, from 1 through 64 |
| `DVBFIXER_MAX_QUEUED_PROCESSES` | 16 | Maximum waiting child-process requests, from 1 through 256 |
| `DVBFIXER_RATE_LIMIT_REQUESTS` | 120 | Requests per direct client address/window; `0` disables |
| `DVBFIXER_RATE_LIMIT_WINDOW_MS` | 60,000 ms | Fixed rate-limit window, 1–3,600 seconds |
| `DVBFIXER_RATE_LIMIT_MAX_KEYS` | 10,000 | Maximum tracked client addresses |
| `DVBFIXER_ACCESS_LOG` | `off` | `off` or one-line `json` API access records on stdout |
| `DVBFIXER_AUDIT_LOG` | `off` | `off` or durable daily `jsonl` audit records |
| `DVBFIXER_AUDIT_RETENTION_DAYS` | 90 | Expiration window for local audit files |
| `DVBFIXER_METRICS` | `off` | `off` or protected Prometheus metrics via `/api/metrics` |
| `DVBFIXER_OS_RESOURCE_LIMITS_REQUIRED` | `0` | Require the Linux cgroup/filesystem preflight when set to `1` |
| `DVBFIXER_OS_DATA_FILESYSTEM_MAX_BYTES` | unset | Maximum dedicated data-filesystem capacity; required by the OS preflight |
| `DVBFIXER_OS_TEMP_FILESYSTEM_MAX_BYTES` | unset | Maximum capacity of each private `/tmp` and `/var/tmp`; required by the OS preflight |
| `DVBFIXER_OS_CPU_QUOTA_PERCENT` | unset | Maximum accepted cgroup CPU quota percentage; required by the OS preflight |
| `DVBFIXER_OS_MEMORY_MAX_BYTES` | unset | Maximum accepted cgroup memory limit; required by the OS preflight |
| `DVBFIXER_OS_MEMORY_SWAP_MAX_BYTES` | unset | Maximum accepted cgroup swap limit; `0` disables swap; required by the OS preflight |
| `DVBFIXER_OS_TASKS_MAX` | unset | Maximum accepted cgroup task limit; required by the OS preflight |

Workspace accounting includes regular files in hidden, failed-run, and trash
directories and refuses symlinks. Request-size failures return `413`; a
workspace publication that exceeds its quota returns `507`. The storage limit
is an application-level, single-process steady-state check, not an OS filesystem
quota. A child process can temporarily create data before publication checks,
and multiple server instances do not coordinate limits.

The opt-in OS preflight verifies cgroup CPU, memory, swap, and task limits
against configured ceilings, a read-only root, a dedicated capacity-bounded
data filesystem, bounded private temporary filesystems, and containment of
mutable home and cache paths. These limits
apply to the whole service and all descendants, not independently per workspace
or job. See [`deployment.md`](deployment.md).

The request limiter runs before authentication. CORS invokes the same limiter
before rejecting an Origin, so rejected Origins, invalid-token attempts, and
public endpoints consume the same direct-address allowance. Valid CORS
preflights terminate before admission; malformed and plain `OPTIONS` requests do
not bypass it. Exhausted clients receive
`429` with `Retry-After` and `RateLimit-*` headers. If the bounded address
tracker is full, an untracked client receives `503`; active entries are never
evicted to admit a new address. The server intentionally ignores forwarded-
address headers. Allowed cross-origin responses expose the rate-limit headers.
A reverse proxy therefore appears as one shared client and
should enforce its own edge limit; do not disable the backend limit without an
equivalent trusted control.

Child-process admission starts work immediately when a permit is available and
otherwise waits FIFO up to `DVBFIXER_MAX_QUEUED_PROCESSES`. Further requests are
rejected before spawning with an overload result; HTTP command and naming routes
map that condition to `503`. Command timeouts begin after admission, not while
waiting in the queue. Queue and concurrency limits are process-local rather than
distributed scheduling controls.

Naming-specific defaults are:

| Environment variable | Default | Purpose |
|---|---:|---|
| `DVBFIXER_NAMING_MAX_SOURCE_BYTES` | 50 MiB | Maximum source artifact size |
| `DVBFIXER_NAMING_MAX_REPORT_BYTES` | 20 MiB | Maximum CLI report size |
| `DVBFIXER_NAMING_TIMEOUT_MS` | 60,000 ms | Subprocess timeout |
| `DVBFIXER_NAMING_FAILED_MAX_RUNS` | 20 | Maximum retained failed naming runs per workspace |
| `DVBFIXER_NAMING_FAILED_MAX_AGE_HOURS` | 168 (7 days) | Maximum age of failed naming runs at pruning time |

These settings must be positive safe integers; the timeout may not exceed
2,147,483,647 ms, Node's timer maximum, and retention hours must remain a safe
integer after conversion to milliseconds. The source is read through a bounded
file descriptor before the operation directory or child-process admission is
created. The command reads that private snapshot rather than the mutable
workspace path, and publication still verifies that the workspace source has
not changed. Generated output is bounded by the same byte limit before digest
validation, then atomically replaced with those validated bytes inside the
private operation directory. The subprocess receives `SIGTERM` on timeout and
escalates to `SIGKILL` after a short grace period; the API returns `504
NAMING_TIMEOUT`.

Operation directories and the shared `runs/_failed` directory use mode `0700`
on POSIX hosts. Server-owned logs, validated reports, and variant-override files
use mode `0600`. Successful publication removes those helpers, and a dry run
removes the whole operation directory. Other failures retain the bounded stdout,
stderr, report when available, overrides, and any partial output below
`runs/_failed`; publication-stage failures restore diagnostics removed during
the commit attempt. Normal failure cleanup excludes the private source snapshot
from retained data. Failed runs are never registered as visible artifacts, are
counted against workspace quota, and pruned under the workspace run lock before
the next naming execution and after each retained failure. By default, pruning
keeps at most the 20 newest failed naming directories and removes those at least
seven days old, measured from quarantine time (directory modification time for
existing failures). This is lazy cleanup, not a background timer: idle workspaces
are cleaned when naming next runs. Only `runs/_failed/naming_<UUID>` directories
are eligible; successful outputs, active runs, other workflow failures, and
symlink targets are preserved. A quota-exhaustion failure deletes its operation
data instead of retaining more bytes. Filesystem errors during failure cleanup
do not replace the original conversion error; operators must repair storage
permissions if cleanup cannot run. Failure diagnostics are not a durable audit
log.

## Browser Origins

Requests without an `Origin` header remain available to non-browser clients.
Browser requests are allowed from the request's exact same origin. Configure
additional origins as a bounded JSON array of exact canonical HTTP(S) origins:

```bash
export DVBFIXER_CORS_ALLOWED_ORIGINS='["https://structures.example.org"]'
```

When TLS terminates or `Host` is rewritten at a reverse proxy, list the public
HTTPS origin explicitly; the backend does not trust forwarded scheme or host
headers.

Wildcard origins, `null`, credentials mode, private-network preflights, malformed
or duplicate Origin headers, and unlisted cross-origin requests are rejected.
Preflights permit only the API methods and the `Authorization`, `Content-Type`,
`Accept`, and `X-File-Name` request headers.

## Standalone Host

From `gui/`, build and start the browser client and API together:

```bash
npm run build
npm start
```

The server defaults to `127.0.0.1:5173`, serves only the built `dist/` tree as
static content, and keeps workspace files behind contained API routes. Unknown
`/api/*` paths return JSON `404` responses rather than the SPA shell. Shutdown
stops accepting requests, cancels tracked DVBFixer subprocesses with signal
escalation, and drains HTTP work.

Remote binding requires configured authentication and
`DVBFIXER_ALLOW_INSECURE_REMOTE=1` as an explicit acknowledgment. Keep the
Node listener private behind a TLS proxy; the public deployment requires
privileged resource-enforcement acceptance on its target host. Multi-host
scheduling is outside the current single-host storage contract.
