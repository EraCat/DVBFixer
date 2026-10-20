# DVBFixer API roadmap

Completion status is tracked in the canonical
[implementation checklist](implementation-checklist.md).

Status (2026-10-20): the naming service, dedicated CLI/V1 HTTP adapters, standalone
host, security controls and versioned managed workflows are implemented. The
[canonical checklist](implementation-checklist.md#api-phase-0-decisions-and-baseline)
records completion and reference-host verification. Operator-specific deployment
acceptance and multi-host scheduling are separate boundaries. Original milestones
below are retained as design context, not wholly unimplemented features.

This plan turns the existing local GUI middleware into a supported,
versioned HTTP API. The first vertical slice is conversion of PDB atom and
residue names to the spellings expected by GROMACS force fields.

## Goals

- Expose scientific operations without duplicating their rules in TypeScript.
- Preserve workspace path isolation and artifact provenance.
- Publish a versioned, machine-readable contract.
- Make small deterministic transformations synchronous and long-running
  scientific workflows asynchronous.
- Keep the CLI and HTTP API as adapters over the same Python application
  services.
- Return structured diagnostics and transformation reports, not only logs.

## Non-goals for the first release

- Replacing the CLI.
- Supporting arbitrary server-side paths supplied by clients.
- Inferring an unknown histidine tautomer from a canonical `HIS` name.
- Converting GROMACS names back to every source naming convention.
- Exposing minimization, modeling, or parameterization as synchronous calls.
- Claiming that an output is force-field compatible based on naming alone.
  Template and bond compatibility remain separate checks.

## Existing baseline

The repository already has most of an API application shell:

- `gui/server/api-routes.ts` composes workspace, Homology, managed-job, health,
  mutation, and command routes for both Vite and the standalone Node host.
- `gui/server/managed-jobs.ts` persists workspace-scoped jobs, logs, status,
  cancellation, and server-sent events.
- `gui/server/workspace-api.ts` provides versioned manifests, atomic writes,
  path containment, artifact registration, and recoverable deletion.
- `gui/server/dvbfixer-runner.ts` invokes the Python CLI with bounded output,
  timeout, abort, and process-group cleanup.
- `src/dvbfixer/command_registry.py` is the authoritative command inventory;
  `scripts/gen_gui_spec.py` derives the GUI command schema from argparse.

The naming route and managed workflows are versioned and publish OpenAPI; the
build includes a loopback-default standalone server. Bearer principals, workspace
ownership/ACLs, restrictive CORS, application/OS deployment quotas, durable audit
retention and single-host cross-process locks/cancellation/event delivery are
implemented. Reference Ubuntu/HTTPS deployment acceptance is recorded in the
checklist; it does not attest a future operator host. Multi-host operation still
requires an external scheduler/state store. Scientific policy remains in Python.

## Recommended architecture

Use the existing Node/TypeScript HTTP layer as the transport and workspace
application shell, but move it out of Vite-specific composition. Keep all
scientific naming policy in Python.

```text
HTTP client
    |
    v
versioned Node API route
    |
    +-- workspace authorization and artifact resolution
    +-- request validation and response mapping
    |
    v
Python command/application adapter
    |
    v
pure naming application service
    |
    v
PDB text parser/renderer adapter
```

This is the smallest path that reuses the GUI's workspace and job behavior
without moving molecular rules into the web server. A separate Python web
framework would duplicate workspace, jobs, auth, and artifact concerns and is
not recommended for the initial API.

The standalone server should call the same route-registration functions as the
Vite plugin. Vite remains a development host, not the API implementation.

## Priority 1: GROMACS-compatible naming API

### Terminology and scope

The existing `dvbfixer rename` command is not the desired operation. It
canonicalizes protonation-state residue names such as `HIE` to `HIS` and does
not make atom names GROMACS-compatible.

The relevant implementation is
`src/dvbfixer/ffutils/ff_names.py::apply_variants_to_pdb_text`. It currently:

- restores AMBER or CHARMM protonation-state residue names;
- applies AMBER methylene, terminal, cap, and nucleic-acid atom-name shifts;
- applies CHARMM residue variants, cap names, and backbone `H` to `HN`;
- rewrites a PDB file in place and returns only a changed-line count.

The first API must be described as a **naming conversion**, not as chemical
parameterization and not as the existing canonical `rename` command.

### V1 behavior

- Input format: PDB only.
- Source profile: DVBFixer/OpenMM-style PDB names plus explicit variants found
  in the source or supplied by the caller.
- Target force-field naming dialect: `amber`, `amber19sb`, or `charmm`.
- Target profile: `gromacs`.
- Output: a new workspace artifact; never overwrite the source artifact.
- `dryRun`: return the report without creating an output artifact.
- Variant overrides are authoritative and keyed by chain, residue number, and
  insertion code.
- Chain IDs and insertion codes are case-sensitive.
- Coordinates, atom serials, occupancy, B-factor, element, and unrelated PDB
  records must remain unchanged.
- The operation must be idempotent for every supported mapping.
- A target-name collision is an error, not a guessed rename.
- Multiple `MODEL` blocks must either be handled independently or rejected
  explicitly in V1. Silent cross-model terminal classification is forbidden.
- Four-character CHARMM residue names must round-trip through the parser used
  by this service or be represented through a documented output convention.

### Proposed endpoint

```http
POST /api/v1/workspaces/{workspaceId}/naming-conversions
Content-Type: application/json
```

Request:

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

Successful response:

```json
{
  "operationId": "3b743d10-1684-4027-aa4c-f0d51c6e0c5f",
  "status": "succeeded",
  "sourceArtifactId": "2a4d4d4e-2c82-4ea0-98ef-92df4cdd57f0",
  "outputArtifact": {
    "id": "944708c9-4d8e-4d80-bef4-890f857418b5",
    "file": "runs/naming-3b743d10/complex_gromacs.pdb",
    "kind": "structure"
  },
  "summary": {
    "changedAtoms": 37,
    "changedResidues": 14,
    "variantChanges": 2,
    "atomNameChanges": 35
  },
  "changes": [
    {
      "model": 1,
      "chainId": "H",
      "residueNumber": "82",
      "insertionCode": "A",
      "residueNameBefore": "HIS",
      "residueNameAfter": "HIE",
      "atomNameBefore": "HB3",
      "atomNameAfter": "HB1"
    }
  ],
  "diagnostics": []
}
```

Use an explicit array for variant overrides. JSON object keys cannot safely or
readably encode the required `(chain, residue number, insertion code)` identity.

### Error contract

All V1 failures should use one envelope:

```json
{
  "error": {
    "code": "NAMING_COLLISION",
    "message": "Target atom name HB1 already exists in residue H/82A",
    "details": {
      "chainId": "H",
      "residueNumber": "82",
      "insertionCode": "A"
    },
    "requestId": "req_01K5..."
  }
}
```

Initial status-code mapping:

| Status | Meaning |
|---|---|
| `400` | Invalid JSON or mutually incompatible fields |
| `401` | Missing or invalid credentials once authentication is enabled |
| `403` | Principal cannot access the workspace |
| `404` | Workspace or source artifact does not exist |
| `409` | Output/artifact revision conflict |
| `413` | Request or source file exceeds the configured limit |
| `415` | Unsupported source format |
| `422` | Structurally valid request cannot be converted safely |
| `500` | Unexpected application failure |

Stable error codes should include `INVALID_VARIANT`, `NAMING_COLLISION`,
`AMBIGUOUS_VARIANT`, `MULTI_MODEL_UNSUPPORTED`, `MALFORMED_PDB`, and
`UNSUPPORTED_NAMING_DIRECTION`.

### Python application boundary

The file-mutating helper now delegates to these typed, transport-independent
contracts (abridged here):

```python
@dataclass(frozen=True)
class NamingConversionRequest:
    pdb_text: str
    target: ForceFieldTarget
    profile: NamingProfile = NamingProfile.GROMACS
    variant_overrides: tuple[VariantOverride, ...] = ()

@dataclass(frozen=True)
class NamingConversionResult:
    pdb_text: str
    model: int
    changes: tuple[CoordinateNamingChange, ...]
    summary: NamingConversionSummary
    diagnostics: tuple[NamingDiagnostic, ...]

def convert_force_field_naming(
    request: NamingConversionRequest,
) -> NamingConversionResult:
    ...
```

Required design properties:

- The core function is pure: text in, text and report out.
- File I/O is a separate adapter using atomic write-and-rename.
- Existing pipeline callers can retain an in-place compatibility wrapper until
  migrated, but the HTTP path never uses it directly.
- Domain identity always includes model, chain, residue number, insertion code,
  alternate location where relevant, and atom name.
- Variant precedence is documented: explicit override, source variant, then no
  inferred change. Canonical `HIS` alone does not imply HID/HIE/HIP.
- The result distinguishes changed atoms from changed residues and records each
  rule that fired.
- Validation occurs before output is committed.

### Correctness work required before exposure

These were identified as API blockers. Phase 1 resolved items 1-6 and 9 in the
pure service; items 7-8 remain before broader workflow exposure:

1. **Implemented:** reject multi-model input before conversion.
2. **Implemented:** detect source and target atom-name collisions per residue.
3. **Implemented:** update correlated `ANISOU` and parseable full `TER` labels when corresponding atom or
   residue names change.
4. **Implemented:** make CHARMM four-character residue parsing and repeat conversion idempotent.
5. **Implemented:** make CHARMM `LYN`/`LSN` hydrogen-pair conversion idempotent.
6. **Implemented:** remove ambiguous two-tuple variant fallback from the new public service;
   preserve insertion codes explicitly.
7. Add end-to-end tests for nucleic-acid names and document unverified terminal
   5-prime/3-prime hydroxyl cases as unsupported until validated.
8. Decide whether the `tleap-reduce` preparation backend must honor the same
   naming option. Current early returns bypass the final naming helper.
9. **Implemented:** ensure service failures produce no transformed result and
   compatibility-adapter failures leave the source untouched.

### CLI adapter

The dedicated command is `dvbfixer atom-names`; it remains separate from
`rename` and `convert` because command names and semantics are long-lived.

The command should:

- accept one input and one explicit output;
- expose `--target-ff {amber,amber19sb,charmm}` and `--profile gromacs`;
- optionally consume variant overrides from a small JSON file;
- support `--dry-run` and `--report-json`;
- call the same Python application service as the HTTP adapter;
- be registered in `command_registry.py` and regenerate CLI and GUI specs.

The Node server may invoke this command through the existing bounded subprocess
runner. A later persistent Python worker is an optimization, not an MVP need.

### HTTP adapter and artifact transaction

The route should perform these steps:

1. Authenticate the caller and authorize the workspace.
2. Validate the body with a runtime schema.
3. Resolve `inputArtifactId` through the workspace manifest, never a caller path.
4. Verify the artifact type and size.
5. Create a private operation directory under the workspace.
6. Run the Python adapter and parse its JSON report.
7. Validate that the expected output exists and is non-empty.
8. Atomically register the output and provenance in the latest manifest revision.
9. Return the artifact and report.
10. On failure, retain logs in the failure area but register no visible output.

Artifact provenance should include command/service version, source artifact ID,
target force field/profile, explicit variant overrides, report checksum, and
the DVBFixer version.

### Test matrix

Python unit tests:

- every AMBER residue mapping in `GROMACS_AMBER_ATOM_RENAMES`;
- AMBER and CHARMM caps and termini;
- DNA and RNA mappings;
- exact insertion-code identity, including `H:82` and `H:82A` together;
- one-residue and multi-chain proteins;
- repeated conversion is byte-identical;
- collisions fail before writing;
- malformed lines and four-character CHARMM names;
- `MODEL` behavior;
- `ATOM`, `HETATM`, `ANISOU`, `TER`, and untouched records;
- empty/no-op conversion and report counts.

CLI integration tests:

- source is never modified;
- JSON report schema;
- non-zero exit and no destination on unsafe input;
- CIF rejection or boundary normalization, according to the chosen V1 contract;
- generated CLI reference remains synchronized.

HTTP tests:

- request validation and stable errors;
- workspace authorization and path containment;
- artifact lookup by ID, not path;
- dry run creates no artifact;
- success registers one output with provenance;
- a stale manifest update cannot discard concurrent artifacts;
- subprocess failure leaves no visible partial artifact;
- size and timeout limits;
- OpenAPI examples validate against the runtime schema.

## Delivery phases

### Phase 0: decisions and baseline

- Record ADRs for the Node transport boundary, command name, synchronous naming
  operation, workspace-only V1 input, and multi-model policy.
- Convert all known naming gaps above into failing tests.
- Capture representative golden inputs without storing generated production
  outputs unless a golden file is specifically needed.

Exit criterion: current behavior and intended V1 behavior are distinguishable
in tests and ADRs.

### Phase 1: naming application service

Core status: implemented on 2026-09-18 in
`dvbfixer.force_field_naming.convert_force_field_naming`, with typed domain
vocabulary in `dvbfixer.domain.force_field_naming` and the existing in-place
helper retained as an atomic compatibility adapter. Dedicated CLI/HTTP exposure
remains in later phases.

- Introduce typed request/result/diagnostic models.
- Extract a pure conversion function from `apply_variants_to_pdb_text`.
- Add collision detection, model handling, and structured change reporting.
- Retain the existing wrapper for prepare/minimize/protonate callers.

Exit criterion: the complete Python naming matrix passes without filesystem I/O
in core tests, and the existing pipeline tests still pass.

### Phase 2: dedicated command adapter

Status: implemented on 2026-09-18.

- Add the command, JSON report, explicit output behavior, and documentation.
- Register the command and regenerate `docs/reference/` and the GUI spec.
- Add subprocess-level tests.

Exit criterion: a caller can execute the conversion deterministically without
using an internal Python function.

### Phase 3: versioned HTTP vertical slice

Core naming slice implemented on 2026-09-18: the shared Node adapter uses
TypeBox runtime schemas, publishes OpenAPI 3.1, resolves source artifacts by ID,
validates bounded CLI reports and output digests, preserves concurrent manifest
updates by reloading before publication, and records reproducible provenance.
Server-owned request IDs, structured API access logs, bounded process-local
Prometheus metrics, durable audit retention, and a generated client are implemented. Authentication,
workspace authorization, and the standalone host are implemented in Phase 4.

- Add runtime request/response schemas and the V1 route.
- Use workspace artifact IDs and atomic artifact registration.
- Generate an OpenAPI document from the same schemas.
- Add request IDs, structured access logs, and metrics; then durable audit fields.

Exit criterion: the route passes contract, security, provenance, and concurrent
manifest tests and is usable by the GUI through a generated client.

### Phase 4: standalone server

Core host slice implemented on 2026-09-18: all existing routes compose through
`api-routes.ts`, Vite is a thin adapter, and the bundled loopback-default Node
server serves the built client plus APIs with validated configuration, static
and data-root separation, graceful HTTP/resource shutdown, and tracked child
process termination. Static bearer authentication and workspace authorization
are implemented. Restrictive CORS, bounded imports, logical workspace quotas,
and process-wide child concurrency limits followed on 2026-09-21. TLS guidance,
same-host cross-process manifest locking, and a fail-closed Linux systemd/cgroup
resource profile followed on 2026-09-21. Privileged target-host enforcement
tests on the target host remain before public deployment. Same-host processes
share durable workspace run locks and persisted job event polling; multi-host
execution remains outside the supported contract.

- Extract route composition from `api-plugin.ts` into a host-neutral module.
- Add a production Node entry point with graceful shutdown and configuration.
- Keep Vite as a thin development adapter over that composition root.
- Authentication, principal-to-workspace authorization, CORS policy,
  upload/workspace limits, global process concurrency, and deployment docs are
  implemented.

Exit criterion: the API can run without Vite and passes deployment smoke tests.

### Phase 5: general DVBFixer API

Versioned managed-job routes and checked-in OpenAPI client types are implemented.
The duplicate synchronous generic route is removed. The naming transform is
synchronous; other commands use persisted managed jobs. ADR 0009 defines
compatibility and the single-host coordination boundary.

- Version managed jobs under `/api/v1` and retire the duplicate synchronous
  generic command runner.
- Classify operations by execution policy: synchronous deterministic transform
  or asynchronous managed workflow.
- Generate clients and contract tests from OpenAPI.
- Add durable scheduling/event delivery before multi-instance deployment.

Suggested order after naming conversion: `diagnose`, `conect`, `renumber`, then
the existing long-running `prepare`, `minimize`, `model`, and `zbs` job paths.

## API-wide quality gates

- OpenAPI and runtime validators derive from one schema source.
- No route accepts an unrestricted filesystem path.
- Scientific rules have one implementation in Python.
- Every output artifact records reproducible inputs, options, and version.
- Workspace ownership is enforced before path resolution.
- Logs never substitute for structured response data.
- Long-running operations are cancellable and have durable state before the
  service is horizontally scaled.
- API compatibility changes follow explicit deprecation and versioning policy.
- `npm run typecheck`, `npm test -- --run`, focused Python tests, generated-file
  checks, and the non-slow Python suite pass before release.

## Related documents

- [DDD documentation roadmap](ddd-documentation-roadmap.md)
- [API and DDD continuation context](api-ddd-continuation-context.md)
- [Current scientific domain model](../domain-model.md)
- [Repository architecture](../../ARCHITECTURE.md)
