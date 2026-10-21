# Scientific domain model

DVBfixer uses a focused domain model where file-format details must not
silently change molecular meaning. It is intentionally not a rewrite of the
CLI, GUI, or external-tool adapters.

Coding agents should use the [agent knowledge map](agent/README.md) for
task-to-symbol navigation, contracts, invariant status, coupled change groups,
and focused verification. This page remains the concise human summary of the
currently implemented domain model.

## Structure identity

`dvbfixer.domain.structure_identity` defines immutable atom, residue, and
molecular-component references, component kinds, and chain-ID allocation. A
generated PDB chain ID must be unique and must not reuse a polymer or
metadata-reserved ID. PDB has only 62 portable one-character IDs, so exhaustion
is reported rather than producing ambiguous output.

`split --unique-molecule-chains` applies that policy. After empirical chain
assignment, it preserves the resulting polymer chain IDs, assigns each non-solvent heterogen component a new ID, rewrites
coordinate identity records, leaves CONECT records unchanged, and records the
operation in `REMARK 999`. Waters and monatomic ions are not separately named
molecules.

`--keep-heterogens` retains all heterogen records, including solvent, ions,
and buffers. With this option atom serials remain unchanged and solvent stays
inside its source MODEL. Solvent/ion records do not consume unique molecule IDs.

For legacy PDB, a residue is currently the component boundary. Empirical Split preserves
atom serials in all modes so unchanged CONECT records retain their endpoints.
PDBx/mmCIF `label_asym_id` remains the authoritative identity whenever an input
adapter can carry it losslessly.

## Parameterization policy

`dvbfixer.domain.parameterization` expresses five routes: exact native template,
isolated organic GAFF candidate, user template, unsupported complex cofactor,
and explicit stripping.

A residue name alone is never proof of force-field compatibility. Exact atom
and bond compatibility is checked by OpenMM. Complex cofactors such as HEM and
FAD are not sent through generic isolated-ligand GAFF because coordination,
covalent attachment, and redox state require a validated model. Supply one with
repeatable `--extra-ff FILE`, or explicitly use `--strip-heterogens`.

Small organic ligands remain GAFF candidates. Charge corrections are based on
connectivity, including tetracoordinate quaternary ammonium and ionizable
phosphate groups; they do not depend on LBN/POPC atom names. Chemically similar
deposited lipids can have incompatible naming and must not be blindly renamed
to a force-field template.

Gemmi, OpenMM, Open Babel, OpenFF, and AmberTools are adapters around these
decisions, not part of the domain model.

## Nonprotein reconstruction

`dvbfixer.domain.nonprotein_reconstruction` and
`dvbfixer.nonprotein_reconstruction` provide an opt-in typed Python application
boundary for geometry-only reconstruction of known isolated Class A components.
Exact identity includes model, case-sensitive chain, residue number, insertion
code, alternate location, component occurrence, and atom name.

Chemical authority is exclusive: either a checksum-pinned bounded local CCD
snapshot extraction, a digest-pinned per-instance user graph, or the explicitly
unsupported online mode. Automatic local microstate selection requires explicit
pH and authority-declared ranges; a mapped user graph is a locked microspecies.
Observed coordinates remain fixed. Missing coordinates come only from a rigidly
fitted authority ideal geometry and carry per-atom provenance.

`dvbfixer.ccd` additionally provides a bounded raw wwPDB component-CIF
information adapter. `component-info` exposes local or explicitly requested
online discovery with content-addressed provenance. `reconstruct-component`
converts an explicitly selected local, non-ambiguous CCD record into a locked
heavy-atom graph and applies the Class A service to one exact PDB `HETATM`
instance. It checks explicit LINK/CONECT evidence, preserves source coordinate
records, validates generated atoms against the surrounding structure, and
publishes the whole PDB with provenance through one directory rename.

Class B linked chemistry and Class C cofactor/metal/redox/coordination chemistry
are structured refusals, not guessed reconstructions. Geometry validation and
atomic bundle publication do not parameterize a molecule. The separate route
decision requires explicit geometry approval, reuses the parameterization domain
policy, and always reports that MD readiness has not been established.

## Force-field naming

`dvbfixer.domain.force_field_naming` owns target/profile vocabulary, explicit
variant identity, naming rules, mapping policy, and stable conversion error
codes. `dvbfixer.force_field_naming.convert_force_field_naming` is the pure
application service: it accepts PDB text and typed options, validates the whole
conversion plan, and returns transformed text with per-atom changes, summary
counts, diagnostics, and model identity.

Explicit overrides take precedence over recognized source variants. Canonical
names such as `HIS` never cause the service to invent a protonation state.
Residue identity preserves case-sensitive chain ID, residue number, and
insertion code; reports additionally preserve model, alternate location, atom
serial, and atom name. V1 rejects multi-model input before rendering, rejects
target-name collisions, and keeps four-character CHARMM and LYN/LSN conversion
idempotent. Naming conversion changes representation only: it does not select
protonation, parameterize a molecule, or prove force-field template/bond
compatibility.

The public CLI, GUI and V1 API expose both `gromacs` (the unchanged default for
CLI/GUI) and native `standard` naming profiles. Native rules normalize supported
AMBER/CHARMM and GROMACS aliases; they do not infer missing atoms or construct
CHARMM terminal patches. See the [naming contract](commands/atom-names.md).

Existing prepare, minimize, and protonate callers use
`ffutils.ff_names.apply_variants_to_pdb_text`, an atomic in-place compatibility
adapter over the pure service. The V1 naming API invokes `dvbfixer atom-names`,
which calls the pure service, and
publishes a new workspace artifact without mutating the source.

## Integration limits

DDD is partially integrated: chain allocation, Class A nonprotein reconstruction,
the complex-cofactor routing guard, and force-field naming are active
domain/application boundaries. The
five parameterization route names are a policy vocabulary, not five completed
backend implementations. Unknown-residue screening currently uses the loaded
template names; OpenMM subsequently checks atom/bond compatibility. The
presence of an XML template name therefore does not establish that an
incomplete or differently bonded residue can be used.

There is no general connected-component inventory, metal/redox-state resolver,
or domain service for whole-complex geometry regularization. PDB multi-residue
heterogens are not yet grouped by connected-component analysis for naming.
Engine setup and fallback behavior still live in `minimize/pipeline.py` and
`lig_params.py`. See [relaxation research](research/whole-complex-relaxation.md)
for proposed regularization architecture and validation criteria, and the
[reconstruction/modeling backend research](research/reconstruction-and-modeling-backends.md)
for atom-completion, loop, homology, and diffusion comparisons. The explicit
`model --backend diffusion` CLI remains experimental, with profile-specific
internal-gap, multi-chain and terminal admission described in the
[model guide](commands/model.md#experimental-diffusion-scope). Its scope, runner, validation, and atomic
bundle boundary remain in `model/diffusion*`, not in the domain package. Static
profile metadata and the typed, bounded runner preflight report also live at
that backend-neutral boundary; `doctor` is only their CLI presentation adapter.
PDBFixer and Salilab MODELLER remain supported production baselines, and
MODELLER remains the default. Class A reconstruction is opt-in and is not wired
into `prepare`, `model`, `minimize`, `zbs`, or an automatic fallback.
