# Force fields in dvbfixer

[User guide](README.md) · [Command index](commands/index.md) · [Recipes](pipelines.md)

`dvbfixer` uses OpenMM's bundled force fields for every energy-based step (`prepare`, `minimize`, `protonate`, `pull`, `zbs`). To spare you from typing raw XML paths, all of those tools accept a short-name alias via `--ff <name>`, and by default they auto-detect the right FF from the input's residue names.

`top` (GROMACS topology generation) uses a **different** short-name namespace — see [Two `--ff` namespaces](#two---ff-namespaces-side-by-side) below.

## `--ff` for OpenMM-using tools

Applies to: `prepare`, `minimize`, `protonate`, `pull`, `zbs`.

### Short-name aliases

| Short name       | Expands to (OpenMM XMLs)                                                                              | When to use                                                                                          |
|------------------|-------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------|
| `auto`           | (chosen by auto-detection — see below)                                                                | **Default** for every tool.                                                                          |
| `amber`          | `amber19/protein.ff19SB.xml`, `amber19/tip3p.xml`                                                     | Plain protein, ff19SB. Same as `amber19`.                                                            |
| `amber19`        | `amber19/protein.ff19SB.xml`, `amber19/tip3p.xml`                                                     | Explicit ff19SB.                                                                                     |
| `amber14`        | `amber14/protein.ff14SB.xml`, `amber14/tip3p.xml`                                                     | Older ff14SB. Needed as base for GLYCAM.                                                             |
| `amber+glycam`   | `amber14-all.xml`, `amber14/GLYCAM_06j-1.xml`, `amber14/tip3pfb.xml`                                  | Glycoproteins with GLYCAM-named residues (NLN/OLS/OLT, 3-char sugar codes like UYB/4YB/VMB).         |
| `amber14+glycam` | same as `amber+glycam`                                                                                 | Alias.                                                                                               |
| `amber+lipid`    | `amber14-all.xml`, `amber14/lipid17.xml`, `amber14/tip3p.xml`                                         | Membrane proteins (Lipid17 phospholipids).                                                           |
| `amber+nucleic`  | `amber14-all.xml`, `amber14/DNA.OL15.xml`, `amber14/RNA.OL3.xml`, `amber14/tip3p.xml`                 | Protein-nucleic acid complexes (OL15 DNA, OL3 RNA).                                                  |
| `charmm`         | `charmm36.xml`, `charmm36/water.xml`                                                                  | CHARMM36 (covers protein + carbohydrates + lipids + nucleic acids natively). Same as `charmm36`.     |
| `charmm36`       | `charmm36.xml`, `charmm36/water.xml`                                                                  | Explicit CHARMM36.                                                                                   |
| `charmm2024`     | `charmm36_2024.xml`, `charmm36/water.xml`                                                             | Newer CHARMM36 release (2024).                                                                       |

Neutral peptide caps are supported as explicit `ACE` and `NME` residues.
AMBER XML files provide these templates directly. For CHARMM, dvbfixer loads
an explicit-residue bridge equivalent to CHARMM36's ACE and CT3 patches when
caps are present, avoiding ambiguity with OpenMM's merged terminal templates.

You can also pass **explicit XML paths** for backward compatibility:

```bash
dvbfixer minimize input.pdb --ff amber14-all.xml amber14/tip3p.xml -v
```

Any argument containing `.xml` or a path separator is treated as an explicit list and passed straight to `openmm.app.ForceField(*paths)` unchanged.

### Auto-detection rules

When you say `--ff auto` (the default) or don't pass `--ff`, dvbfixer scans the input PDB's residue names once and picks the FF from these markers:

**CHARMM markers** (any hit → `charmm`, unambiguous FF-prep signal):

- **Protonation variants**: `HSD`, `HSE`, `HSP`, `ASPP`, `GLUP`, `LSN`
- **CHARMM-GUI 4-char sugars**: `BGLC`, `AGLC`, `BMAN`, `AMAN`, `BGAL`, `AGAL`, `BFUC`, `AFUC`, `BGLCNA`, `AGLCNA`, `BGALNA`, `AGALNA`, `ANE5`, `BNE5`, `ANE5AC`, `BNE5AC`, `AIDO`, `BIDO`
- **Ceramides**: `CER1`, `CER160`, `CER180`, `CER181`, `CER2`, `CER200`, `CER220`, `CER240`, `CER241`, `CER3E`

**GLYCAM markers** (any hit → `amber+glycam`):

- **Glycoproteins**: `NLN`, `OLS`, `OLT`
- **Reducing-end caps**: `ROH`, `OME`, `TBT`, `CMET`
- **Sugar residues**: any 3-char resname matching the GLYCAM `[linkage][sugar][anomer]` pattern — e.g. `4YB`, `UYB`, `VMB`, `0YA`, `0SA`, `2MA`

**PDB Chemical Component Dictionary sugar names** (since 0.7.6): `NAG`, `NDG`, `BMA`, `MAN`, `FUC`, `FUL`, `GAL`, `BGC`, `GLC`, `SIA` (etc.). These appear in raw crystal PDBs, in GLYCAM output *before* renaming, and in CHARMM-GUI output *before* CHARMM renaming. Neither `amber14+GLYCAM` nor `charmm36.xml` has templates for these bare PDB names — but rather than surrendering to the plain `amber` default, `detect_ff_from_pdb` now auto-selects `amber+glycam` and the pipeline auto-converts the sugar names to GLYCAM canonical naming (via `dvbfixer convert`'s machinery) before the FF is applied:

```text
FF: amber+glycam  (PDB-standard sugar name(s) detected (FUC, GAL, MAN) —
  will auto-convert to GLYCAM canonical naming before FF apply. Pass
  --ff charmm to force CHARMM instead)
  → amber14-all.xml amber14/GLYCAM_06j-1.xml amber14/tip3pfb.xml
```

Pass `--ff charmm` explicitly if you actually want the CHARMM path for
these ambiguous names (`dvbfixer convert --to-charmm` first).

**Precedence when both CHARMM and GLYCAM markers appear** (rare — hand-assembled structures): CHARMM wins, because CHARMM protonation names are unambiguous full-file-prep signals.

**Upgrade behaviour**: if you explicitly asked for `amber` (or `amber14` / `amber19`) but the input clearly has CHARMM or GLYCAM markers, dvbfixer *upgrades* your choice and prints why:

```text
FF: amber+glycam  (upgraded from 'amber' → 'amber+glycam' because GLYCAM
   residue(s) detected (4YB, NLN, VMB))
  → amber14-all.xml amber14/GLYCAM_06j-1.xml amber14/tip3pfb.xml
```

Downgrading (e.g. `--ff charmm` on a plain-protein input) is respected — no auto-override.

### The startup banner

Every OpenMM-using tool prints two lines at startup so you always know what FF is in play:

```text
FF: <alias>  (<reason if auto-selected or upgraded>)
  → <expanded XML list>
```

### Overriding

- `--ff auto` — explicit auto-detection (also the default).
- `--ff <short-name>` — pick a specific alias.
- `--ff <xml> [<xml> …]` — pass raw OpenMM XML paths verbatim.

### Adding a new short name

Edit `FF_ALIASES` in `src/dvbfixer/ffutils.py`:

```python
FF_ALIASES = {
    ...
    'my-ff': ['some/openmm.xml', 'some/water.xml'],
}
```

If the new FF has residue names that unambiguously identify it, extend the marker sets (`_CHARMM_MARKERS`, GLYCAM residue lists, etc.) and add a branch to `detect_ff_from_pdb`.

## `--ff` for `top` (GROMACS topology)

Applies to: `top` **only**. Different namespace — it doesn't load OpenMM XML files. Instead, it parses **bundled GROMACS FF directories** via the RTP parser in `rtp_parser.py`. Source/editable checkouts use `FF/*.ff/`; wheels install the same complete trees under the active environment's `share/dvbfixer/FF/` directory and resolve them automatically.

| `top --ff` value | What it loads                                          |
|------------------|--------------------------------------------------------|
| `amber`          | `FF/amber99sb-ildn-lipid21.ff/` — AMBER99SB-ILDN + Lipid21 |
| `amber19sb`      | `FF/amber19sb.ff/` — official GROMACS `v2026.3` ff19SB port; explicit opt-in, fail-closed protein-only |
| `charmm`         | `FF/charmm36_ljpme-jul2022.ff/` — CHARMM36 with LJ-PME    |

`amber` remains the default and retains its existing Lipid21, custom `--ff-dir`,
and reviewed ion-substitution behavior. `amber19sb` is not an OpenMM alias and
does not change `amber19`/`amber` in the OpenMM namespace. It accepts canonical
protein residues, AMBER protonation variants, HYP/CHYP, ACE/NME caps, water,
and simple Na/K/Cl ions. It rejects nucleic acids, glycans, lipids, PTMs,
arbitrary ligands, and coordinated metals before writing output. `--acpype`
remains the separate AMBER14+GLYCAM route and cannot be combined with
`--ff amber19sb`.

Amber19SB uses only exact upstream water/ion pairs: `opc`, `opc3`, `spc`,
`spce`, `tip3p`, and `tip4pew`, each with its same-name `ions_*.itp`. Cross-pairs
and `tip4p` are rejected. See the complete
[provenance and compatibility audit](provenance/amber19sb-gromacs.md).

## `--target-ff` for `atom-names`

`atom-names` has its own naming-dialect selector: `amber`, `amber19sb`, or
`charmm`. Use `amber19sb` before `top --ff amber19sb`; it preserves ff19SB's
`O`/`OXT` C-terminal atoms and PDB-style ACE/NME names. The legacy `amber`
target instead emits the `OC1`/`OC2` and cap spellings required by
`amber99sb-ildn-lipid21.ff`. This conversion changes names only and does not
replace `top`'s force-field compatibility checks.

## Two `--ff` namespaces (side-by-side)

| Aspect                 | OpenMM tools (`prepare`, `minimize`, `protonate`, `pull`, `zbs`) | `top`                                          |
|------------------------|------------------------------------------------------------------|------------------------------------------------|
| Backend                | OpenMM `ForceField(*xmls)`                                       | GROMACS RTP parser (bundled `FF/*.ff/` dirs)   |
| Short names            | `auto`, `amber`, `amber+glycam`, `charmm`, `charmm2024`, …       | `amber`, `amber19sb`, `charmm`                 |
| Explicit path          | `--ff a.xml b.xml …`                                             | `--ff-dir /path/to/custom.ff/`                 |
| Auto-detection         | Yes (this doc)                                                   | No — user picks                                |
| `charmm` maps to       | `charmm36.xml` + water XML                                       | Full bundled CHARMM36 RTP directory            |

The two are separate because they consume completely different file formats: OpenMM parses XML; GROMACS parses `.rtp` / `.atp` / `.itp`. The bundled GROMACS FF dirs let dvbfixer emit topologies that don't need any external FF installation on the target machine. CI builds both wheel and source distribution, installs the wheel into a clean environment, and verifies all descriptor roots and required RTP/ITP inventories there.

## Handling arbitrary unknown ligands

Standard force fields do not have templates for every deposited molecule. The
safe route depends on the component, and a matching residue name alone is not
enough: OpenMM must also match the exact atom and bond graph.

Use repeatable `--extra-ff FILE` with `minimize` or `zbs` to append validated
OpenMM XML parameters after the selected base force field. This is the intended
route for retained complex cofactors and project-specific templates.

### Real force-field parameters — `minimize --parametrize-ligands`

Runs the same pipeline as `dvbfixer parametrize` (antechamber → parmchk2) on each unknown residue in the input, wraps the result in an `openmmforcefields.generators.GAFFTemplateGenerator`, and registers it on the OpenMM ForceField before `createSystem`.

```bash
dvbfixer minimize protein_with_ligand.pdb --parametrize-ligands -v
# Output includes:
#   [lig_params] extracted LIG (24 atoms)
#   [lig_params] built GAFF2 templates for: LIG (cache: ~/.cache/dvbfixer/lig_params/gaff_ligands.json)
```

- Uses AMBER GAFF2 + AM1-BCC charges via `antechamber`. Same charge model as `parametrize`'s default (`-c bcc`).
- Cached on disk between runs (default cache: `~/.cache/dvbfixer/lig_params/`; override with `$DVBFIXER_LIG_CACHE`).
- Requires `openmmforcefields`, `openff-toolkit`, and AmberTools (`antechamber`, `parmchk2`) in the env.
- **Scope**: isolated organic small molecules. Cross-residue bonds do not get
  parameters. HEM, FAD, FMN, NAD, and related complex cofactors are rejected
  from generic GAFF and require a validated `--extra-ff` template (or explicit
  `--strip-heterogens`). Metal-containing components are also outside this
  generic route.
- Forwarded by `zbs --parametrize-ligands` to the minimize step. Since 0.7.10, `minimize` also auto-attempts this (non-strict) for eligible unknown organic heterogens, even without the flag. Unknown complex cofactors raise even in non-strict mode.

### Universal-FF geometry refinement — `--xtb-refine` / `--obminimize-refine`

Different mechanism entirely. These are **post-minimize refinement passes** that run AFTER OpenMM finishes. They apply a universal force field (xtb GFN-FF; OpenBabel UFF / MMFF94 / GAFF) to the whole system or just the heterogens, without OpenMM residue-template matching during the post-pass. They still require successful completion of the preceding OpenMM stage and valid input chemistry.

```bash
# After OpenMM minimize, run xtb GFN-FF only on the heterogens
dvbfixer minimize input.pdb --xtb-refine --refine-heterogens-only -v

# OpenBabel obminimize (UFF by default; handles N-glycosidic angles correctly)
dvbfixer minimize input.pdb --obminimize-refine --refine-heterogens-only -v
```

- **When to use**: sanity-check ligand geometry when you don't want to (or can't) generate real FF parameters. Also useful for glycan systems where sugar-sugar bonds have no OpenMM template — the refinement pass fixes strain that OpenMM couldn't touch.
- Auto-switches to heterogens-only above 5000 atoms (whole-system xtb takes hours).
- **`--refine-heterogens-only` interface caveat**: with the protein frozen, only the ligand's INTERNAL geometry is refined. Protein-side accommodation is unavailable; ligand motion may relieve some contacts but does not provide joint interface relaxation. Drop the flag for whole-system refinement when the interface matters.
- **NOT a replacement** for `--parametrize-ligands`: universal FFs are less accurate than GAFF2, and running xtb/UFF on a ligand doesn't give you MD-ready parameters — you still need real FF templates for a production MD run.

### Which to use?

| Need                                                      | Use                                        |
|-----------------------------------------------------------|--------------------------------------------|
| Isolated ligand, want real FF params for MD               | `--parametrize-ligands`                    |
| Heme, flavin, metal complex, or covalently attached cofactor | Validated `--extra-ff FILE`; otherwise strip explicitly |
| Protein-ligand INTERFACE geometry matters (H-bonds, contacts) | `--parametrize-ligands` (whole system optimised together; do NOT rely on `--strip-heterogens` or `--refine-heterogens-only` which leave the interface unrelaxed) |
| Just want the ligand's internal geometry to look sensible | `--xtb-refine` or `--obminimize-refine` (add `--refine-heterogens-only` for speed if interface geometry doesn't matter) |
| Glycan tree with PDB names (NAG/BMA/MAN)                  | `dvbfixer convert --to-amber` first        |
| Glycan tree with CHARMM-GUI names (BGLC/BMAN/…)           | `--ff charmm` (auto-detected)              |
| Glycan tree with GLYCAM names (4YB/UYB/…)                 | `--ff amber+glycam` (auto-detected)        |

**About `--strip-heterogens` (opt-in) and its auto-fallback**: this mode runs the OpenMM minimize on protein only and splices the heterogens back at their raw INPUT coordinates. The protein has moved by then, so the protein-ligand interface (H-bonds, close contacts) can end up strained. The tool now emits a WARNING in both cases; if the interface matters to you, use `--parametrize-ligands` instead.

Lipid residue names are particularly unsafe as template selectors. For
example, a deposited LBN can describe POPC chemistry while using an entirely
different atom-name scheme from an installed POPC template. DVBfixer applies
generic connectivity-based phosphate and quaternary-ammonium charge rules when
building an isolated ligand, but does not blindly rename such lipids. See the
[parameterization policy](domain-model.md#parameterization-policy).

## Water models

The OpenMM aliases pick a default water XML that matches the FF (e.g. `amber` uses `tip3p`, `amber+glycam` uses `tip3pfb`). If you need a different water model, pass the water XML explicitly:

```bash
dvbfixer minimize input.pdb --ff amber19/protein.ff19SB.xml amber19/opc.xml
```

For `top`, water is a separate `--water` argument and ions come from
`--ion-set`; the selected topology descriptor validates the combination. The
global parser accepts the union of backend choices, including `opc3`, but each
backend rejects unsupported values before output. See [`top`](commands/top.md).

## Examples

```bash
# Default: auto-detect
dvbfixer minimize glycoprotein.pdb -v
# → FF: amber+glycam  (GLYCAM residue(s) detected (4YB, VMB))
#   → amber14-all.xml amber14/GLYCAM_06j-1.xml amber14/tip3pfb.xml

dvbfixer minimize plain_protein.pdb -v
# → FF: amber  (no non-standard residues detected)
#   → amber19/protein.ff19SB.xml amber19/tip3p.xml

# Force CHARMM
dvbfixer prepare input.pdb --ff charmm -v

# Force a newer CHARMM release
dvbfixer minimize input.pdb --ff charmm2024 -v

# Backward-compat: explicit XML paths still work
dvbfixer minimize input.pdb --ff amber14-all.xml amber14/tip3p.xml -v

# Whole pipeline with a specific FF
dvbfixer zbs input.pdb --ff amber+glycam -v
```

A force-field family name or a matching residue name is not proof of complete
parameter coverage. Incomplete cofactors require an explicit structural repair
decision as well as parameters; neither `--extra-ff` nor a universal-force-field
post-pass supplies absent atoms. Current template screening starts from names,
with atom/bond matching deferred to OpenMM. See the [domain boundaries](domain-model.md)
and [relaxation research](research/whole-complex-relaxation.md) for the verified
FAD example and proposed alternatives; geometry regularization is not a shipped
minimization backend.
