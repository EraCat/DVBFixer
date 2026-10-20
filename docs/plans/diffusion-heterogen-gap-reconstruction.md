# Diffusion Gap Reconstruction With Heterogen Context Research Plan

- Status (2026-10-20): narrow isolated-SMILES geometric-context slice implemented
  for the **legacy** `protpardelle-1c-mps` profile; broader chemistry classes remain
  proposed research. Corrected cc89 CUDA and `protpardelle-1c-mps-local-v1` remain
  protein-only and reject nonwater heterogens. No legacy chemistry capability is
  inherited by the corrected profiles. See the [current plan index](README.md).
- Scope owner: Structure Preparation bounded context.
- Depends on:
  - the narrow protein-only diffusion boundary in
    [`diffusion-gap-reconstruction.md`](diffusion-gap-reconstruction.md);
  - the opt-in CLI integration gates in
    [`diffusion-cli-integration.md`](diffusion-cli-integration.md);
  - chemistry-authority policies in
    [`../research/reconstruction-and-modeling-backends.md`](../research/reconstruction-and-modeling-backends.md).
- Production baseline retained: MODELLER remains the default and continues to
  preserve supported heterogen context through its existing path.
- Implemented preprocessing boundary: the explicit public
  `--strip-heterogens` option may create a private protein-only diffusion input
  and remove associated ANISOU/LINK/CONECT records without mutating the source.
  This is user-requested problem reduction, not heterogen retention or
  conditioning, and does not broaden the capability claims below.

## Research Question

Determine whether a diffusion backend can reconstruct a missing canonical
protein segment while retaining and, where scientifically justified, conditioning
on nearby non-protein chemistry without changing deposited heterogen identity,
graph, coordinates, or explicit links.

This plan separates two capabilities that must not be conflated:

1. **Heterogen-context gap reconstruction** keeps a complete, authoritative
   heterogen fixed while generating only missing protein residues. This is the
   first research target.
2. **Heterogen atom reconstruction** generates missing ligand, glycan, cofactor,
   PTM, or coordination-site atoms. This requires a chemistry-authority-first
   contract and remains out of scope until a separate evidence-backed plan is
   accepted.

Merely splicing unchanged HETATM records back after protein-only inference does
not prove heterogen-aware reconstruction. It is a retention-only baseline unless
the sampler actually consumed verified heterogen context.

## Non-Goals And Safety Boundary

- [ ] Do not broaden the initial public `model --backend diffusion` scope as part
  of this research.
- [ ] Do not treat PDB proximity, atom names, or bond perception alone as chemical
  authority.
- [ ] Do not infer missing bond order, formal charge, protonation, redox state,
  metal coordination, stereochemistry, or covalent attachment by guessing.
- [ ] Do not generate or move heterogen atoms in the first retained-context slice.
- [ ] Do not claim that a protein-only atom37 model is ligand-conditioned because
  fixed HETATM records were restored after sampling.
- [ ] Do not use successful serialization or force-field parameterization as
  evidence that chemistry is correct.
- [ ] Do not silently strip unsupported heterogens, waters, links, or coordination
  records and continue with a different scientific problem.
- [ ] Do not add automatic fallback to MODELLER or between diffusion profiles.
- [ ] Do not publish partial output after admission, runner, validation,
  refinement, or chemistry-validation failure.

## Heterogen Classification Matrix

Each class receives its own admission rules, fixtures, metrics, and promotion
decision. Passing one class does not imply support for another.

| Class | Initial research treatment | Required authority | Main risks |
|---|---|---|---|
| Complete isolated small molecule | Fixed context; generated protein only | User SMILES/SDF or versioned CCD graph, with unique atom mapping | Wrong bond order, charge, microspecies, symmetry-ambiguous mapping |
| Complete organic cofactor | Fixed context in a separately declared stratum | Curated CCD/component state plus redox/protonation declaration | State ambiguity, uncommon elements, parameterization failure |
| Monoatomic ion | Separate fixed-context stratum | Element, formal charge, occupancy, and unambiguous identity | Treating crystallization ions as functional; false contacts |
| Coordinated metal site | Separate high-risk stratum; not pooled with ions | Explicit coordination model and supported geometry policy | Coordination is not ordinary covalent bonding; ligand exchange and oxidation state |
| Glycan | Separate linked-polymer stratum | Component and linkage dictionaries plus stereochemistry | Branch identity, anomer/linkage errors, incomplete CONECT/LINK records |
| PTM | Separate residue/link stratum | Component identity and parent/link policy | Protein sequence mapping and residue identity ambiguity |
| Covalent ligand | Separate covalent-link stratum | Authoritative component graph and explicit attachment identity | Link order/stereochemistry and generated-region boundary interaction |
| Structural water | Separate optional stratum, never mixed into the first gate | Deposited identity/occupancy policy | High mobility, alternate sites, engine token explosion |
| Unknown or chemically incomplete HETATM | Unsupported | None | Hallucinated chemistry |

## Capability Levels

Every evaluated engine/profile must be labelled with exactly the capability it
demonstrates:

1. `retention-only`: the engine does not consume heterogen features; DVBFixer
   preserves fixed records and validates the resulting protein against them.
2. `heterogen-conditioned`: the engine consumes a verified representation of the
   retained heterogen and exposes an auditable atom mapping.
3. `linked-context-conditioned`: the engine additionally represents an
   authoritative protein–heterogen or heterogen–heterogen link.
4. `heterogen-generating`: the engine generates heterogen atoms or chemistry;
   excluded from this plan's first decision and never implied by levels 1–3.

Protpardelle-1c must initially be classified as protein-only unless an engine
audit proves otherwise. Final restoration of HETATM coordinates can establish
retention, not conditioning. Protenix/Boltz-class support must likewise be proven
against the pinned implementation and checkpoint rather than inferred from model
marketing or input-schema acceptance.

### Implemented narrow slice (2026-10-06)

- Public opt-in authority is repeatable
  `--diffusion-heterogen-smiles RESNAME=SMILES`.
- Admission is limited to complete isolated single-residue HETATM components
  with occupancy 1.00, explicit heavy elements, explicit CONECT connectivity,
  no external covalent edge, and one chemically equivalent graph mapping through
  the shared `prepare.smiles` graph/signature policy.
- The pinned Protpardelle patch transforms HETATM coordinates with the protein
  motif and applies differentiable 2 Å geometric repulsion only to generated
  protein atoms. Upstream previously parsed these coordinates but never consumed
  them; merely retaining HETATM records was therefore not accepted as evidence.
- Request, sampler trace, and publication provenance preserve exact PDB atom
  identities plus an authoritative canonical-SMILES graph digest. Heterogen heavy
  coordinates remain exact; local OpenMM refinement uses a protein-only temporary
  topology and writes back only generated protein coordinates.
- A 500-step MPS smoke with an isolated two-heavy-atom ligand passed independent
  validation and preserved both HETATM coordinate records exactly.
- Capability label is deliberately `fixed-geometric-repulsion`, not general
  chemical interaction conditioning. Glycans, metals, waters, PTMs, cofactors,
  covalent ligands, partial components, and inferred chemistry remain unsupported.

## Phase 0: Contract And Policy Design

- [ ] Add stable heterogen identities without collapsing
  `(chain, resid, icode, atom)` or case-sensitive chain IDs.
- [ ] Represent component identity, authoritative graph digest, formal-charge
  evidence, and microspecies provenance outside `DatRecord`.
- [ ] Extend retained explicit-link records only with typed, digest-verifiable
  bond/link semantics; do not overload peptide-link assumptions.
- [ ] Record whether each heterogen was visible to the sampler, preserved outside
  it, or excluded by an explicit study arm.
- [ ] Record engine atom/token mapping and prove a round trip back to exact PDB
  identities before scientific inference.
- [ ] Distinguish `unsupported-chemistry`, `ambiguous-chemistry`,
  `unsupported-conditioning`, `unsupported-link`, and
  `parameterization-unavailable` admission outcomes.
- [ ] Keep supplied ligand SMILES authoritative and do not apply protein `--ph`
  semantics to it.
- [ ] Reuse `domain.structure_identity`, `domain.parameterization`,
  `domain.force_field_naming`, and `ffutils.ligand_valence`; do not duplicate
  their chemistry or routing policies in diffusion code.
- [ ] Preserve CIF normalization at the CLI boundary and propagate chain mapping
  remarks before building diffusion identities.
- [ ] Require a successor ADR before any public heterogen-capable profile is
  exposed.

## Phase 1: Discovery And Admission

- [ ] Inventory all non-protein coordinate records, explicit `LINK`/`CONECT`
  records, alternate locations, occupancies, and distances to the generated and
  movable regions.
- [ ] Resolve chemistry authority in precedence order: explicit user mapping,
  versioned local CCD/component dictionary, then an explicitly documented
  built-in template. Return unsupported if no authority exists.
- [ ] Require unique graph-to-coordinate atom mapping. Permit only explicitly
  normalized resonance equivalence; never choose arbitrarily among incompatible
  mappings.
- [ ] Define distance strata before examining outcomes, including direct-contact,
  second-shell, and distant spectator context.
- [ ] Detect whether a heterogen or its explicit link crosses the generated or
  movable mask.
- [ ] Reject alternate-location ambiguity in the heterogen, its interaction
  residues, or either gap junction for the first study.
- [ ] Reject partial components, mixed occupancy, unsupported elements, unknown
  coordination state, and stale/dangling links in the first study.
- [ ] Ensure residue-number allocation cannot collide with retained HETATM
  residues after gap filling.
- [ ] Emit a stable, complete reason list before launching an external runner.

## Phase 2: Engine Representation And Controlled Ablations

For each eligible class and engine, compare the following preregistered arms on
the same cases and seeds:

1. **Context removed:** heterogen omitted from sampler input but retained only as
   a negative scientific comparator; never presented as a valid preservation
   strategy when the heterogen contacts the gap.
2. **Retention-only:** heterogen coordinates and records are restored exactly,
   while the sampler remains protein-only.
3. **Native conditioning:** the pinned engine receives the authoritative
   heterogen representation and fixed mask.
4. **Conditioning plus fixed-coordinate projection:** only when the sampler has a
   stable heterogen atom axis and a post-update projection hook.
5. **Validated local refinement:** generated protein atoms and explicitly allowed
   junction atoms may move; heterogen heavy atoms remain fixed.

- [ ] Prove which atom, bond, charge, link, and metal features actually reach the
  denoiser for each engine.
- [ ] Fail if unsupported features are silently discarded by engine preprocessing.
- [ ] Require per-step trace evidence before claiming fixed-coordinate projection.
- [ ] Treat an engine-side graph rewrite, atom reordering without a verified map,
  or implicit hydrogen/microspecies change as a hard failure.
- [ ] Keep Apple MPS and Linux CUDA profiles separate; do not infer one profile's
  chemistry capability from the other.
- [ ] On Apple Silicon, retain `PYTORCH_ENABLE_MPS_FALLBACK=0`, device assertions,
  synchronized timings, and separate MPS/RSS telemetry.

## Phase 3: Refinement Strategy Study

Heterogen-aware refinement is not automatically available merely because the
diffusion candidate exists. Evaluate these paths separately:

- [ ] Existing authoritative parameterization through
  `domain.parameterization`, including strict failure for a user-requested route.
- [ ] Fixed heterogen plus generated-protein local refinement when the complete
  system can be parameterized without changing chemistry.
- [ ] A geometry-only generated-region refinement that includes bounded
  heterogen repulsion/contact restraints without pretending to be a physical
  force field.
- [ ] No-refinement publication only if the raw candidate independently passes
  every hard gate.

The selected path must:

- keep heterogen heavy coordinates exact unless a later protocol explicitly
  authorizes movement;
- preserve the authoritative graph, charge, stereochemistry, and explicit links;
- avoid stripping ligand hydrogens that cannot be rebuilt from a known template;
- keep glycans and covalently attached components anchored;
- run `assert_all_l` after the final protein heavy-coordinate change;
- revalidate the complete structure after refinement.

## Phase 4: Benchmark Corpus

- [ ] Freeze fixtures and expected classifications before outcome-bearing runs.
- [ ] Use experimentally observed complete structures and withhold only canonical
  protein gap coordinates; do not fabricate a favourable ligand pose.
- [ ] Exclude or separately label likely training members using temporal and
  sequence/structure-cluster controls.
- [ ] Balance gap lengths, loop secondary structure, contact density, and
  heterogen distance.
- [ ] Include at minimum:
  - [ ] drug-like neutral and charged ligands with authoritative SMILES;
  - [ ] aromatic and resonance-equivalent mappings;
  - [ ] cofactors with declared chemical state;
  - [ ] monoatomic ions separated from coordinated metals;
  - [ ] one-site and multinuclear metal environments where authority exists;
  - [ ] branched glycans and protein–glycan links;
  - [ ] PTMs and covalent ligands;
  - [ ] antibody insertion codes and case-distinct chains;
  - [ ] negative controls with unknown, partial, ambiguous, and unsupported
    heterogens.
- [ ] Keep all failed and unsupported cases in denominators appropriate to their
  preregistered stratum.
- [ ] Run MODELLER as the retained-context comparator and a protein-only
  diffusion arm as the ablation comparator.

## Phase 5: Independent Validation

### Mandatory preservation gates

- [ ] Exact heterogen atom identity set; no loss, duplication, or rename.
- [ ] Exact fixed heterogen heavy coordinates at serialized PDB precision.
- [ ] Authoritative graph, bond order, formal charge, stereochemistry, and
  microspecies unchanged.
- [ ] Every retained explicit link preserved with identical endpoints and type.
- [ ] No new inferred protein–heterogen or heterogen–heterogen bond.
- [ ] No stale or remapped CONECT endpoint after serialization/renumbering.

### Protein reconstruction gates

- [ ] Complete canonical heavy atoms for every generated residue.
- [ ] Peptide junction distances, backbone continuity, clashes, Ramachandran,
  supported side-chain geometry, and final L-chirality pass.
- [ ] Fixed protein coordinates remain within the profile's declared tolerance.

### Context-sensitive metrics

- [ ] Severe protein–heterogen clash count and minimum interatomic distance.
- [ ] Recovery of reference contacts, hydrogen-bond geometry, salt bridges, and
  aromatic contacts without using them as hard gates before calibration.
- [ ] Gap-backbone and all-heavy RMSD stratified by heterogen class and distance.
- [ ] For metals, coordination number and element/geometry-specific distance and
  angle metrics under the declared coordination model.
- [ ] For glycans and covalent ligands, linkage geometry and attachment
  stereochemistry.
- [ ] Unsupported/ambiguous classification precision and recall.

Backend-native confidence or affinity scores are descriptive only and cannot
override an independent identity, chemistry, geometry, or chirality failure.

## Phase 6: Apple Silicon Evaluation

- [ ] Begin only after CPU contract/admission tests and at least one Linux
  heterogen-context engine path pass.
- [ ] Use the existing native arm64 Protpardelle environment only for capabilities
  it actually exposes; do not patch in an unreviewed ligand representation.
- [ ] Measure MPS inference and CPU heterogen-aware refinement separately.
- [ ] Record peak RSS, MPS tensor/driver allocation, latency, and terminal outcome
  for every case without summing overlapping unified-memory counters.
- [ ] Stop on silent CPU sampling fallback, wrong-device tensors, dropped
  heterogen features, identity mapping failure, or chemistry mutation.
- [ ] Do not promote a retention-only Protpardelle result as
  heterogen-conditioned support.

## Phase 7: Promotion Gates

### GO for a research-only retained-context profile

- A specific heterogen class has frozen fixtures and authority rules.
- Admission correctly rejects every ambiguous/unsupported negative control.
- The engine's conditioning capability and atom mapping are demonstrated rather
  than assumed.
- No passing candidate changes heterogen identity, chemistry, fixed coordinates,
  or links.
- Protein hard-gate pass rate is noninferior to the preregistered retained-context
  comparator within that class.
- Atomic bundle publication and provenance identify the chemistry authority,
  capability level, engine/profile, checkpoint, and validation results.

### STOP

- The engine silently ignores heterogen features or rewrites chemistry.
- A graph/charge/microspecies/coordination state is inferred without authority.
- Fixed heterogen coordinates or explicit links cannot be restored and validated
  exactly.
- Refinement requires unsupported parameterization or moves a supposedly fixed
  heterogen.
- Results pool chemically distinct classes into one success rate.
- Apple execution silently falls back to CPU or is labelled as conditioned when
  it is retention-only.

Passing these gates authorizes only a class-specific research decision. Public
CLI exposure, batch/GUI support, heterogen atom generation, broader chemistry,
or a change to the MODELLER default each require separate decisions.

## Required Tests Before Any Implementation Claim

- Contract round trips and strict schema rejection for component/link authority.
- Case-sensitive chains, insertion codes, residue-number collisions, and exact
  heterogen atom mapping.
- Resonance-equivalent mapping acceptance and genuinely ambiguous mapping
  rejection.
- Unknown/partial component, unsupported element, altloc, occupancy, stale-link,
  covalent-link, glycan, cofactor, ion, and coordinated-metal admission cases.
- Runner feature-drop, atom-reorder, graph-mutation, digest-mismatch, timeout,
  and no-partial-publication failures.
- Fixed heterogen coordinate, graph, charge, stereochemistry, link, clash,
  coordination, protein geometry, and chirality validation failures.
- macOS and Linux atomic no-replace publication paths.
- Apple MPS unavailable, fallback-enabled, wrong-device, and retention-only label
  enforcement.

## Deliverables

- Versioned heterogen-context benchmark manifest and provenance inventory.
- Capability matrix for every evaluated engine/profile and heterogen class.
- Typed contract/admission proposal with stable reason codes.
- Frozen CPU/Linux evidence before Apple outcome-bearing runs.
- Separate Apple MPS operational/scientific report where applicable.
- Evidence-backed recommendation per heterogen class: unsupported,
  retention-only, conditioned research profile, or candidate for a later public
  integration plan.
