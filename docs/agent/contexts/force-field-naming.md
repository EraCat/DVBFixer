# Force-field Naming

Status: partial

Verified on: 2026-09-18

Verified at commit: `5478403ee139cb8e4245e84eef1ed3927417e863`

## Purpose

This context owns representation-level residue and atom names required by
AMBER, CHARMM, and GROMACS consumers. It restores explicit protonation variants
lost by toolkit adapters and applies supported target-profile atom shifts.

It does not choose protonation states, parameterize molecules, validate complete
force-field compatibility, or generate a topology.

## Scope

Domain vocabulary and naming policy live in
`src/dvbfixer/domain/force_field_naming.py`. The pure application boundary is
`src/dvbfixer/force_field_naming.py::convert_force_field_naming`: PDB text and
typed options in, transformed text plus a structured report out. Existing
pipelines continue through
`src/dvbfixer/ffutils/ff_names.py::apply_variants_to_pdb_text`, an atomic
in-place compatibility adapter over that service.

`dvbfixer atom-names` is the non-destructive public adapter. It requires an
explicit output, supports typed JSON variant overrides, dry-run validation, and
a versioned JSON report. It calls the pure service directly rather than the
in-place compatibility wrapper.

The workspace-scoped HTTP adapter is
`gui/server/naming-api.ts::executeNamingConversion`. It accepts an artifact ID,
invokes `atom-names`, validates the report and digest, and registers a new
artifact with naming provenance. TypeBox schemas and OpenAPI live in
`gui/server/naming-api-schema.ts`.

`dvbfixer rename` is outside this operation. It collapses variant residue names
to canonical PDB parents and does not produce GROMACS atom naming.

## Capabilities

| Capability | Status | Owner | Evidence |
|---|---|---|---|
| Restore explicit AMBER variants after OpenMM normalization | implemented | `force_field_naming.py::convert_force_field_naming` | `tests/test_force_field_naming.py`, `tests/test_ff_names.py` |
| AMBER/GROMACS protein, cap, and terminal atom shifts | implemented | `domain/force_field_naming.py::atom_name_policy` | `tests/test_force_field_naming.py`, `tests/test_ff_names.py`, `tests/test_terminal_caps.py` |
| TER-aware terminal naming with repeated residue identity rejection | implemented | `force_field_naming.py::convert_force_field_naming` | `tests/test_atom_names_ter_integration.py` |
| Amber19SB-specific cap, HYP, and terminal naming | implemented | `domain/force_field_naming.py::GROMACS_AMBER19SB_ATOM_RENAMES` | bundled `amber19sb.ff/aminoacids.rtp`, `tests/test_force_field_naming.py`, `tests/test_atom_names_cli.py` |
| AMBER/GROMACS nucleic-acid sugar hydrogen shifts | partial | `domain/force_field_naming.py::GROMACS_AMBER_NA_ATOM_RENAMES` | mappings exist; terminal hydroxyl coverage remains unverified |
| CHARMM residue variants, cap names, and backbone `H` to `HN` | implemented | `domain/force_field_naming.py::atom_name_policy` | `tests/test_force_field_naming.py`, `tests/test_ff_names.py` |
| Pure text-in/result-out naming service | implemented | `force_field_naming.py::convert_force_field_naming` | `tests/test_force_field_naming.py` |
| Structured per-change report and stable failures | implemented | `NamingConversionResult`, `NamingConversionError` | `tests/test_force_field_naming.py` |
| Collision rejection | implemented | `force_field_naming.py::convert_force_field_naming` | collision regressions in pure-service and adapter tests |
| Multi-model V1 policy | implemented | `force_field_naming.py::convert_force_field_naming` | more than one `MODEL` is rejected before rendering |
| Non-destructive CLI and JSON report | implemented | `atom_names.py::main` | `tests/test_atom_names_cli.py` |
| Workspace-scoped V1 HTTP conversion | implemented | `naming-api.ts::executeNamingConversion` | `gui/server/naming-api.test.ts` |

## Entry Points

| Task | Start symbol | Required contracts |
|---|---|---|
| Change force-field naming policy/service | `force_field_naming.py::convert_force_field_naming` | `pdb-force-field-naming`, `dat-record-lifecycle` |
| Change legacy pipeline file adaptation | `ff_names.py::apply_variants_to_pdb_text` | `pdb-force-field-naming` |
| Change protonation variant identity | `variants.py::scan_variant_names` | `dat-record-lifecycle` |
| Change the public naming command | `atom_names.py::main` | `pdb-force-field-naming`, public command surface in `tasks.toml` |
| Change the HTTP naming boundary | `naming-api.ts::executeNamingConversion` | `pdb-force-field-naming`, workspace containment and artifact publication |

The complete task record and focused commands are in
[`../tasks.toml`](../tasks.toml).

## Contracts

The authoritative contract records are in
[`../contracts.toml`](../contracts.toml).

`pdb-force-field-naming` is pure and is exposed through CLI and workspace HTTP
adapters.
The legacy wrapper still mutates a path for existing pipeline callers, but it
validates first, performs no write on a no-op or failure, and commits changed
text with a same-directory atomic replacement. An HTTP adapter must call the
pure service through the planned command/application boundary and create a new
workspace artifact rather than use the in-place wrapper.

`dat-record-lifecycle` carries explicit variants across pipeline stages using
`chain:resid:icode`. New code must not collapse that identity to two fields.

Terminal classification groups residues by model, chain ID and TER-delimited
segment, including bare TER records. Segment IDs remain private: reuse of a
public residue identity across segments raises `NAMING_COLLISION` before
atom grouping, variant inference or output publication, in both profiles.

## Invariants

The relevant records in [`../invariants.toml`](../invariants.toml) are:

- `INV-NAMING-PRESERVE-STRUCTURE`;
- `INV-NAMING-EXPLICIT-VARIANTS`;
- `INV-IDENTITY-ICODE`;
- `INV-NAMING-IDEMPOTENT`;
- `INV-NAMING-NO-COLLISION`.
- `INV-NAMING-MODEL-POLICY`.

The naming-specific invariants are implemented by the pure service. The wider
insertion-code invariant remains partial because unrelated pipeline-local maps
have not all migrated to typed three-field identities.

## Callers

- `prepare/pipeline.py` applies the helper near final output on the legacy
  backend.
- `minimize/pipeline.py` restores variants and target naming after writing the
  minimized structure.
- `protonate.py` applies it on its legacy output paths.
- `zbs.py` forwards atom-naming options to prepare and minimize rather than
  owning naming rules.

The `tleap-reduce` early-return paths apply the AMBER output naming policy only
after tleap, Reduce, variant-H patching, and chirality inspection. This keeps
native names inside tleap while making `prepare` and `protonate` honor the same
public `--atom-naming` option as the legacy backend.

## Adapters

- PDB fixed-column parsing/rendering is contained in the pure application
  service; domain policy does not depend on file I/O or external toolkits.
- Atomic path replacement and legacy key coercion are adapter concerns in
  `ffutils/ff_names.py`.
- OpenMM is an upstream adapter that can canonicalize explicit variant names.
- GROMACS force-field files are evidence for target spellings, not domain code.
- `.dat` is the published pipeline language for preserving variant choices.
- The Node HTTP layer is a transport/workspace adapter and must not
  duplicate naming tables or scientific decisions.
- `atom_names.py` owns CLI path validation, atomic output/report publication,
  and the camelCase report envelope.
- `naming-retention.ts` owns age/count pruning of quarantined naming failures;
  `naming-api.ts` invokes it under the workspace run lock before execution and
  after quarantine. Successful artifacts and other workflow failures are excluded.

## Side Effects

- The pure service has no side effects.
- Its result includes transformed text, per-coordinate changes, summary counts,
  diagnostics, model identity, and stable rule/error codes.
- The compatibility wrapper reads and may atomically replace its supplied path.
- The wrapper retains the historical changed-`ATOM`/`HETATM` integer return.

## Known Divergences

- V1 rejects multiple `MODEL` blocks rather than converting them independently.
- Legacy two-tuple keys remain accepted only by the compatibility adapter and
  mean an exact blank insertion code, never an insertion-code wildcard.
- Nucleic-acid terminal hydroxyl naming is not fully validated.
- `--atom-naming standard` suppresses shifts; it is not a reverse converter.
- `amber` and `amber19sb` are separate GROMACS naming dialects; conversion does
  not replace `top --ff amber19sb` protein-only compatibility validation.
- `tleap-reduce` is an AMBER-only preparation backend; its naming option changes
  the final AMBER atom-name profile and does not select a CHARMM preparation FF.
- The HTTP adapter is available through Vite and the standalone host with static
  bearer authentication and workspace ACL enforcement. Cross-process locking is
  not implemented.

## Proposed Work

The API design is in [`../../plans/api-roadmap.md`](../../plans/api-roadmap.md).
Phases 1 and 2, the core Phase 3 HTTP vertical slice, route composition, and
authentication/authorization, restrictive CORS, workspace limits, and process
concurrency and request-rate controls are implemented. Observability, OS-level limits, and
distributed coordination remain. Do not expose the in-place
compatibility wrapper as an HTTP handler.

## Focused Verification

```bash
pytest -q tests/test_atom_names_cli.py tests/test_atom_names_ter_integration.py tests/test_force_field_naming.py tests/test_ff_names.py \
  tests/test_variants_gromacs_lyn.py tests/test_prepare_icode_variants.py \
  tests/test_terminal_caps.py tests/test_scientific_domain.py
python scripts/check_agent_docs.py
cd gui && npm test -- --run server/naming-api.test.ts server/naming-retention.test.ts server/dvbfixer-runner.test.ts
```
