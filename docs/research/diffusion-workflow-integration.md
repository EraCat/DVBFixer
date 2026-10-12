# Diffusion Workflow Integration

## Implemented Slice

- Backend-dependent directory output metadata and sequential model batch.
- Collision/containment preflight for all batch destinations before inference.
- Explicit per-input seed lists, bounded aggregate outcome reporting, and
  digest/request-verified resume with independent revalidation.
- ZBS `--model-backend diffusion`, preserving the default Modeller model backend
  and independent legacy preparation default.
- Immutable validated bundle consumption, publication-ranked candidate selection,
  and canonical PDB/`.dat` handoff through prepare and minimize.
- Protenix/Protpardelle/auto selection for mosaic-first Homology and GUI.
- Homology optional prepare/minimize after validated selection, preserving
  coverage ownership and logical case-sensitive target IDs.
- GUI native temporary scientific execution, verified workspace archival,
  per-workspace publication authorization, and rejected-bundle inspection without
  automatic primary selection. Subsequent prepare/minimize jobs copy bundle inputs
  and their verified sidecars into owned work space instead of modifying bundles.

These are orchestration capabilities within existing scientific scope. No
covered substitutions, new gap-length strata, chemistry classes, joint sampling,
or causal interface-conditioning acceptance is added. MODELLER remains default;
automatic fallback remains disabled.

## Shared Custody Contract

`model/diffusion/publication.py` verifies every bundle-linked artifact, candidate
identity, scientific summary, sampler trace, and generated-atom sidecar identity.
Accepted candidate order comes from the Python publisher, not filename or
engine-native score ordering. A rejected or malformed bundle cannot enter ZBS
or Homology post-processing. `--diffusion-resume` additionally requires the
current request hash and reproduced validation result; it launches no sampler.

The E2E investigation found that prepare's internal inferred/converted temporary
input path could hide the original model `.dat`. Prepare now merges from the
original input path, and the deterministic backend also carries upstream data.
ZBS/Homology perform idempotent `DatRecord` merges before downstream minimization.
Whitespace-only insertion codes normalize to empty identity while real `A/a`
codes and `D/d` chain IDs remain distinct.

## Checkpoint-Backed Evidence

The frozen `36hb` source was exercised through public commands on the pinned
Linux/A100 Protenix runtime:

1. Batch of two independent inputs: both scientifically accepted and byte-identical.
2. Resume of both bundles: digest/request checks and independent revalidation
   succeeded without inference.
3. ZBS from the resumed bundle: actual legacy prepare and Reference minimization
   with `--no-solvent`; all 48 modeled heavy-atom restraint identities were
   carried into prepared data. Final diagnose: 0 ERROR, 0 WARNING, 0 D-Cα.
4. Mosaic-first Homology from a template plan: Protenix candidate scientifically
   accepted with fixed mosaic ownership recorded.

Batch PDB SHA-256:
`664e65f90a9a7ec6abdd762008b6f28fe20d2e47eaab576bdf1830a246b61ea4`.
Homology PDB SHA-256:
`ee105a664c51b88c6e3d697d5ca10ab87c4c2aa374e0791a6259006077afdd36`.
Portable smoke report SHA-256:
`95ca076f2b0277def518b042b6d171b761ad09e5dc15ec3420b2a5ebcda2ee63`.
Full ignored evidence, logs and bundles are preserved under
`.artifacts/diffusion-workflow-smoke/`.

```bash
PYTHONPATH=src python scripts/smoke_diffusion_workflows.py \
  --cohort .artifacts/diffusion-confirmatory-cohort-500-v5 \
  --work /tmp/opencode/new-workflow-smoke \
  --dvbfixer /path/to/core-env/bin/dvbfixer \
  --archive-root .artifacts/new-workflow-smoke
```

GUI tests cover native-output archival, declared-rank primary selection, rejected
primary suppression, artifact corruption rejection, separate model/prep backend
controls, multi-seed argument encoding, workspace isolation, and bundle immutability
when starting a subsequent prepare job. Hardware GUI interaction is not claimed
as a browser acceptance run.

## Verification

- Full non-slow Python suite: **1037 passed, 6 skipped, 31 deselected**.
- GUI: **243 tests passed**, `npm run typecheck` and `npm run lint` passed.
- `ruff check src/dvbfixer`: passed.
- Strict mypy command from `AGENTS.md`: passed (13 source files).
- Generated GUI schema and CLI reference checks: passed. CLI references were
  regenerated using the repository's Python 3.11 argparse baseline.
- Agent-documentation maps, version synchronization and `git diff --check`: passed.

The hardware smoke used the working-tree workflow implementation atop `05c16c9`;
it is bounded workflow evidence on `36hb`, not another full-cohort scientific
scope promotion.
