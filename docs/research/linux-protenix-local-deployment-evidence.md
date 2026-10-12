# Linux Protenix Local Deployment Evidence

## Status

Local checkpoint-backed deployment checks are complete on the frozen A100 host.
The full 231-case public replay, independent revalidation, two fresh public-CLI
seed-7 repeats, full package exports, and the `9eho` ordering investigation have
been performed. OCI and GitHub-hosted execution are separate portability checks
and are not claimed as complete.

## Fresh Hardware Smoke

The exact Bash hardware step from
`.github/workflows/protenix-hardware-acceptance.yml` was executed locally with
provisioned asset paths and disposable native storage. This was a local run of
the workflow's hardware step, not a GitHub Actions dispatch.

Both independent `36hb` seed-7 runs passed the portable checker and scientific
validation. They produced PDB SHA-256
`664e65f90a9a7ec6abdd762008b6f28fe20d2e47eaab576bdf1830a246b61ea4`.
Both recorded 200/200 CUDA callbacks, fallback disabled, zero projection error,
exact fixed coordinates, zero D-Cα, and completed localized refinement.
Runner times were 133.559 and 123.120 seconds; peak VRAM was 3,051,652,096 bytes
for each run. The evidence artifact
`.artifacts/protenix-hardware-acceptance.json` has SHA-256
`a5023f61232aa1c0b7d8cee807aed3d62b842d0650118722d0005701724131c0`.

## Full Provisioned Package Export

`scripts/export_protenix_environment.py` records the effective package closure
for both interpreters, including `pip freeze --all` and the core conda explicit
export. Private prefixes and editable-install paths remain only in ignored
evidence, never tracked documentation or the portable digest manifest.

The backend is a system-site-packages venv inheriting the core environment.
An OCI packaging attempt must include both layers; packing the backend venv
alone would omit its scientific dependencies. Both interpreters are Python
3.13.15. The effective inventories contain 146 core and 161 backend packages.

Export manifest: `.artifacts/protenix-deployment-environment/manifest.json`,
SHA-256 `7447093719fa271d7b3c773fb3a7a66eafee41abee989b209e64c3090d55e2be`.

| Export | SHA-256 |
|---|---|
| core conda explicit | `ab193dcf6ce12c8ee2d297780b41d142c0a8f3764b7d59017228e034494ef99a` |
| core pip freeze | `5ed9124369452ec9998395c58ba3e72204479ee2f431fadba90b7560849ac9ad` |
| backend pip freeze | `38c2447cf6558f36b3ca2ebcb862351137b4c85c371a7d2f4bb04a9f23d8ef39` |
| core package snapshot | `a92ff334722da9f7f6599cfe7dc5556b0548c93b779434c48af3084575f69331` |
| backend package snapshot | `9b7f6cb11d2088743883b4e247462faf29421ed7a0e53c572fa7cf82bb148ae9` |

## 9eho: Controlled Causal Investigation

The status difference is not caused by switching the refinement module from v4
to v6. The frozen v4 implementation at `47754cf` and current v6 were executed
on identical raw input, seed, Reference platform, and current dependencies.

| Raw input/control | v4 result | v6 result |
|---|---|---|
| Frozen raw | Historical refined coordinates, no chi outlier | Identical to v4 |
| Current raw | Replay refined coordinates, GLU129 outlier | Identical to v4 |
| Current raw, frozen ATOM order only | Historical refined coordinates, no chi outlier | Identical to v4 |

Frozen and current raw inputs have the same 972 unique atom identities and
exactly the same coordinates. Their ATOM sequence differs at 56 positions.
Changing only that ordering changes the refinement path: the ordering control
restores the historical post-coordinate digest
`5d6f8a56c5093e149c0e85437bab4c9f8c255470deed0326ce334bc169f8abb3`.
Current order produces
`08a3e347ef8c99a1986ac34c09718ad59ce1698e6515b2335e3f78f8ba52b1fc`.
This isolates input atom ordering as sufficient to explain the observed
local-minimum difference; the particular internal RNG/numerical contribution
has not been separately decomposed.

The experiment changes neither production atom ordering nor validation gates.
The production replay remains 219 accepted and 12 rejected. It does not select
the historically passing ordering after observing benchmark outcomes.

| Evidence artifact | SHA-256 |
|---|---|
| frozen-input v4/v6 comparison | `11a8ba781cafe5bf8d45825804b11a0bc901e90073f83f60d5ac6270730d0a68` |
| current-input v4/v6 comparison | `2676f5488afc82e7bf186b1cfab2d7abe5816ee8d9ea88cf604c16343c8299dc` |
| ordering-only control | `8a6bbe1e297fb9d7a6d8f730a4596e968a08daded1b5d2edc3a4ac8058887c74` |

These JSON artifacts and the captured current raw PDB remain under `.artifacts/`.
`scripts/compare_protenix_refinement_revisions.py` reproduces the controls.

## Portability Checks: Actual Infrastructure Limits

A separate tooling environment installed Podman 5.8.3, GitHub CLI and actionlint;
the scientific environments were not modified. Podman worked with native
`vfs` storage. Pulling the digest-pinned CUDA base failed while applying a layer:

```text
remount /, flags: 0x44000: permission denied
```

`unshare -Urm true` independently failed with:

```text
unshare: cannot change root filesystem propagation: Permission denied
```

Therefore an OCI build/run cannot be validated in this host's execution sandbox.
No final image digest is invented or recorded. An OCI-capable host is needed only
to finish that portability check, not to use the already-tested native backend.

GitHub Runner API returned HTTP 403, `Resource not accessible by personal access
token`. The manual workflow definition passes actionlint, but registration,
inspection and execution of a GitHub-hosted self-hosted job are not available
with the current credentials. The local execution above does not substitute for
that CI control-plane check. Repository push access and Actions/runner access
are distinct permissions.
