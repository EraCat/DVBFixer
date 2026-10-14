# Protenix protein-context implementation and mechanistic pilot

## Decision and scope

The experimental Protenix context-v1 slice implements a source-only selector,
exact engine mappings, per-update fixed-coordinate projection, and independently
validated publication. The frozen pilot demonstrates a causal denoiser response
to neighboring protein coordinates. It does **not** establish broad interface
acceptance or change the default modeling backend.

Public opt-in: `--diffusion-context local|full` with
`--diffusion-model protenix` on diffusion model, ZBS, and Homology workflows.
`none` remains the default. Context-v1 requires one gap-bearing chain and
canonical protein context; unsupported selections fail closed.

## Implemented contract and adapter

- Additive schema-4 context fields are omitted when absent, retaining legacy
  canonical request/trace serialization.
- Four disjoint roles distinguish generated interior, movable generated
  junction residues, fixed conditioning atoms, and preserved-only source atoms.
  Observed anchors remain fixed.
- Source digest, exact coordinates, selected spans, selection policy, context
  digest, represented atom axis, and mapping evidence are checked against a
  deterministic recomputation from the normalized source.
- Local selection uses eight sequence flanks, same-chain spatial context,
  neighboring-chain contacts, 6/10 Å anchor-based shells, and two observed
  sequence neighbors of each contact. It never uses withheld gap coordinates.
  Full selection includes the supported protein sequences. Complete selected
  residues and a 512-residue budget are required; exceeding the budget rejects
  the request rather than trimming context.
- Discontiguous spans become distinct engine entities, with reversible exact
  residue mappings and allocated engine chain IDs. Case-distinct source chains
  and insertion codes remain distinct.
- Alignment uses fixed atoms of the gap-bearing primary span; projection
  overwrites all represented fixed atoms after every update. Unrepresented
  source atoms are preserved without claiming conditioning.
- The existing Protpardelle selector has not yet migrated to this shared policy.

## Frozen pilot

Manifest: [`protein-context-cohort.json`](protein-context-cohort.json), SHA-256
`c6e12749d8a6c8cffddfc338e623743647d793847fd898863c5dc9801f0d4e5b`.
Four source structures were screened in locked order, with no replacements.
7K8S Fv, 1EMV complex, and 1DQJ antibody–antigen were eligible; 8XJ0 was
unsupported because source residue B/1 lacked heavy atoms. Reference contacts
were used only to freeze a contact-bearing five-residue mask before inference.
The runtime selector sees only the masked observed source.

All eight arms used the same masks and seed 7. The 24 GPU outcomes include
scientific rejections; none were replaced or removed from the summaries.
RMSD medians below include all three eligible outcomes, including rejections.

| Arm | Independently accepted | Median gap backbone RMSD (Å) |
|---|---:|---:|
| Anchors and gap | 0/3 | 4.2649 |
| Sequence flanks 8 | 0/3 | 4.1957 |
| Sequence flanks 16 | 0/3 | 4.0901 |
| Same-chain spatial | 1/3 | 2.5373 |
| Local partner | 2/3 | 1.2807 |
| Full protein | 2/3 | 0.3653 |
| Template only, without per-step projection | 0/3 | 10.5151 |
| Local partner plus localized refinement | 3/3 | 0.6469 |

For all non-template-only arms, the verified trace records 200 callbacks,
zero post-projection error, and zero final fixed-heavy-atom displacement.
Full context does not guarantee acceptance: 7K8S full-protein was rejected for
severe steric overlap despite its low backbone RMSD.

### Causal intervention

At update 100, the probe holds state, features, sigma, and RNG state constant.
It repeats the baseline denoiser evaluation, then translates only partner XYZ
coordinates by (+25, 0, 0) Å and measures generated-atom response **before**
projection. RNG state is restored before continuing the original trajectory.

All six local/full partner probes passed the frozen gate: baseline repeat maximum
delta exactly zero and generated response maximum at least 0.0001 Å. For 7K8S
local context, generated response RMSD was 0.848700 Å and maximum displacement
1.286509 Å. Its selected fixed partition contained 840 of 1,730 fixed atoms;
890 atoms were preserved-only. This demonstrates dependence on partner
coordinates, rather than merely their restoration in the output.

## Environment and custody

- Protenix source: `85767b811c40ed46e73a9b39519cf6bfca8701ba`.
- Checkpoint SHA-256:
  `2b7d5a8b30494514fc47fd2271a16260528cdba170ba09cc112fdecd8f85ec04`.
- Callback patch SHA-256:
  `cc4153be3dfd241124ea183d592884799300046b6ea7d3eccae8409b9fe21aa0`.
- Profile-lock SHA-256:
  `3fb3661be2b6748650b90bf9b0aaa7a09cbba9accc13253a6c29f644001b5d2e`.
- NVIDIA A100-SXM4-40GB; Torch 2.13.0, CUDA 12.9, OpenMM 8.6.1.
- Native private execution below `/tmp/opencode`; durable evidence under ignored
  `.artifacts/protein-context-cohort/` and
  `.artifacts/protein-context-acceptance/`.
- Each completed outcome has a manifest-bound artifact digest inventory.
  Failed harness execution archives diagnostics under `failures/` before
  private-workspace cleanup and does not create a completion marker.

The analyzer verifies artifact custody, source selection, trace mapping,
projection evidence, and causal gates, then independently reruns the current
DVBFixer validator for every candidate and compares the complete recorded
summary. Reference quality fields remain digest-verified worker measurements.
Analysis SHA-256:
`6e09c54a6ddd50e0140bf7f5fa5f71faf1750702df7db524090ae1737a1ac41f`.

The successful public 7K8S local-context bundle is archived at
`.artifacts/protein-context-acceptance/public-cli-bundle/`; its verified selected
PDB SHA-256 is
`f2b8f9d88854ba418c21c65bd3d1d8ba0dabcf5bfd0adaf5315bde90401806ea`.
The legacy 36HB public smoke retained its previous selected PDB SHA-256,
`664e65f90a9a7ec6abdd762008b6f28fe20d2e47eaab576bdf1830a246b61ea4`.

Re-audit the durable archive:

```bash
PYTHONPATH=src python scripts/analyze_protein_context_ablations.py \
  --manifest docs/research/protein-context-cohort.json \
  --outcomes .artifacts/protein-context-acceptance \
  --output .artifacts/protein-context-acceptance/analysis.json \
  --public-bundle .artifacts/protein-context-acceptance/public-cli-bundle
```

## Verification and remaining acceptance

Verification: 1,055 fast Python tests passed, seven skipped (optional Biotite
and GROMACS), 31 slow tests deselected; subsequent focused context/adapter tests
passed 24/24, including new discontiguous template round-trip and failure-custody
tests. Strict core mypy passed; GUI typecheck and all 243 tests passed.

WP5–WP8 remain partially complete. Pending work includes broader independently
evaluated interface cohorts, distant-context negative controls, shell/budget
sensitivity, ranking enrichment, explicit gap orientation measurements,
Protpardelle causal acceptance and shared-selector migration, and multiple
gap-bearing-chain/joint-sampling support. Three eligible structures, one seed,
and contact-selected masks cannot establish generalization. WP3 validation-policy
expansion remains paused; the existing policy was used without threshold changes.
