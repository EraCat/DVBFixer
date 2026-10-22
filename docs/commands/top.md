# `dvbfixer top`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/top.md)

Generates GROMACS topology files directly from PDB or GRO files by parsing force field RTP/ARN/R2B/TDB files in Python — no `pdb2gmx` or GROMACS installation required. GRO files are auto-converted via MDAnalysis. Bundled choices are the default AMBER99SB-ILDN/Lipid21 route, opt-in protein-only Amber ff19SB, and CHARMM36. Output is a modular, self-contained set of `.itp` files plus `topol.top` and topology-matched coordinates. Broad mixed-system support remains on `amber`, `charmm`, or `--acpype`; `amber19sb` deliberately fails closed.

## Quick start

```bash
dvbfixer top prepared.pdb --ff amber -o gmx/
```

**Input:** an inspected, prepared structure with supported chemistry.
**Results:** topology, modular includes, and matching coordinates under `gmx/`.
Use the generated coordinates for GROMACS setup, not an assumed matching source
atom order. This command does not perform solvation, equilibration, or production MD.
See [force fields](../force-fields.md) for the distinction between topology and
OpenMM force-field aliases.

## Defaults and limits

ACE/NME-capped protein chains are accepted directly for both bundled force
fields. The caps remain explicit residues, their peptide bonds are retained,
and charged NH3+/COO- terminal patches are not applied at capped ends. Generate
caps with `dvbfixer prepare --cap-termini` or supply a pre-capped PDB.

## Usage

```bash
# Basic usage with AMBER (default) — writes topol.top, posre_*.itp, conf.pdb
dvbfixer top input.pdb

# GRO file input (auto-converted via MDAnalysis)
dvbfixer top system.gro --ff charmm

# Buffer system (ACET/ACEH auto-detected as small molecules)
dvbfixer top buffer.gro --ff charmm

# CHARMM36 force field
dvbfixer top input.pdb --ff charmm

# Official GROMACS ff19SB port, protein-only and explicit opt-in
dvbfixer top prepared-protein.pdb --ff amber19sb --water opc

# Explicit disulfide bonds and HIS protonation
dvbfixer top input.pdb --ss A:22:A:96 --his A:64:HID

# Protonate all ASP/GLU/HIS (CHARMM: ASPP/GLUP/HSP)
dvbfixer top input.pdb --ff charmm --protonate all

# Protonate specific residues
dvbfixer top input.pdb --ff charmm --protonate A:66,A:46:GLUP

# Glycolipid from CHARMM-GUI (ceramide + sugar tree as one moleculetype)
dvbfixer top glycolipid_charmm.pdb --ff charmm -o glycolipid_top/

# ACPYPE mode: full AMBER14+GLYCAM parametrization via OpenMM
# Handles mixed 1-4 scaling for glycoproteins via [ pairs_nb ]
dvbfixer top input.pdb --acpype

# Custom output
dvbfixer top input.pdb -o my_topology.top --pdb my_conf.pdb
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `-o`, `--output` | `topol.top` | Output .top file |
| `--ff` | `amber` | `amber`, `amber19sb`, or `charmm`. `amber19sb` is the official GROMACS `v2026.3` ff19SB port and is protein-only. This namespace is separate from OpenMM aliases. |
| `--ff-dir` | (bundled) | Custom force field directory for legacy `amber`/`charmm`; rejected for `amber19sb` so its verified inventory cannot be replaced silently. |
| `--water` | `tip3p` | Union of descriptor water choices. Amber19SB permits only `opc`, `opc3`, `spc`, `spce`, `tip3p`, and `tip4pew`; CHARMM permits `tip3p`/`spc`/`spce`; legacy AMBER behavior is unchanged. |
| `--ion-set` | `auto` | Descriptor-matched ion set. Amber19SB accepts only the exact `amber19sb-<water>` set (normally selected by `auto`); all cross-pairs are rejected. Legacy AMBER retains JC/LM/Dang choices; CHARMM uses bundled ions. |
| `--ignh` | off | Ignore hydrogens in input PDB (strip all H and let the FF templates rebuild them) |
| `--keep-all-hydrogens` | off | Preserve every input H atom (default OFF: `HO1`/`HO2`/`HO3`/`HO4`/`HO6` at glycosidic linkage sites are stripped and their charge is redistributed onto the linked O — matches the CHARMM RTP template for a formed glycosidic bond). See warning below |
| `--ss` | auto | Disulfide bond: CHAIN1:NUM1:CHAIN2:NUM2 (repeatable) |
| `--his` | auto | HIS protonation: CHAIN:NUM:STATE (HIE/HID/HIP, repeatable) |
| `--protonate` | off | Protonate residues: `all` for every ASP/GLU/HIS, or `CHAIN:NUM[:STATE],...` for specific. H placed via OpenMM Modeller with CHARMM/AMBER FF |
| `--merge` | off | Merge all chains into single moleculetype |
| `--pdb` | `conf.pdb` | Output PDB with topology-matched atom names |
| `--acpype` | off | Use ACPYPE pipeline (AMBER14+GLYCAM -> ParmEd -> GROMACS) with per-pair 1-4 scaling |
| `-v`, `--verbose` | off | Print detailed progress |

## Preserving all input hydrogens (`--keep-all-hydrogens`)

By default, `dvbfixer top` implements the CHARMM glycosidic-bond
chemistry when it detects a sugar-sugar (or ceramide-sugar) linkage:
it strips the reducing-end `HO1`/`HO2`/`HO3`/`HO4`/`HO6` at the linked
position and redistributes that H's charge onto the linked O (which
also gets its atom type changed from `OC311` hydroxyl to `OC3C61`
ether). Similarly, ceramide `HO1` is dropped at the ceramide-sugar
junction. This matches the RTP template for a formed glycosidic bond
and gives an integer residue net charge.

`--keep-all-hydrogens` skips both the H strip AND the charge/type
redistribution — the input `HO*` atoms pass through verbatim and the
O keeps its `OC311` hydroxyl type + full RTP charge. Use this when:

- The input is a free reducing-end sugar (no glycosidic link at that
  position) whose H is REAL, not vestigial.
- You need charges to round-trip untouched to a downstream tool that
  expects the un-redistributed sum.

```bash
# Default — HO atoms stripped at detected linkages
dvbfixer top glycan.pdb --ff charmm -o gmx/

# Preserve every input H
dvbfixer top glycan.pdb --ff charmm --keep-all-hydrogens -o gmx/
```

**Warning**: at a REAL glycosidic linkage this produces an over-valent O
(the H is bonded to it AND the neighbouring sugar's anomeric C bonds to
the same O). `gmx grompp` may warn and the resulting MD energy will be
chemically wrong. Use only when you know the linkage detection is a
false positive or when your downstream tool expects the un-modified
charges. The default (`--keep-all-hydrogens` off) is the right choice
for normal glycoprotein / glycolipid MD.

Also honoured by `--acpype` mode: skips the `_GLYCAM_KEEP_H` allowlist
filter in `acpype_export.prepare_for_openmm` so any GLYCAM-side H that
was going to be dropped (e.g. `HD22` on `NLN`) passes through.

## RTP-based mode (default)

Parses force field RTP files to build topology from bond graph: resolves inter-residue bonds (`-C`, `+N`), enumerates angles/dihedrals/pairs algorithmically, copies impropers and CMAP from templates, applies terminal patches. Intra-chain disulfide bonds (SG-SG between CYS2 residues) are added explicitly to the chain topology with all derived angles, dihedrals, and 1-4 pairs; inter-chain SS bonds go to `interchain_ss.itp`. For CHARMM36, loads all molecule-type RTP files (aminoacids, carb, lipid, na, cgenff, ethers, metals, silicates, solvent — ~2400+ residue types). Non-protein chains are built without terminal patches. Glycan trees are detected from C1-O distances and built with proper glycosidic bond handling (HO removal, charge redistribution, atom type changes). Output is modular: `ffparams.itp` (all FF parameters including atomtypes, bonded params, water model params), chain `.itp` files, `water.itp`, `ions.itp`, `posre_*.itp` (position restraints, `#ifdef POSRES`), and `interchain_ss.itp` (if needed). `topol.top` contains only `#include` directives, `[ system ]`, and `[ molecules ]`. Ions and buffer particles (BUF) in the input PDB are auto-detected and added to the `[ molecules ]` section.

### Amber19SB admission and compatibility

Amber19SB accepts verified canonical protein residues; ASH, GLH, HID, HIE,
HIP, CYX, CYM, and LYN variants; HYP with upstream CHYP at the C terminus; and
explicit ACE/NME caps. It preserves case-sensitive chain IDs and insertion
codes. Missing required heavy atoms, unsupported terminal variants, DNA/RNA,
carbohydrates, lipids, PTMs, ligands, coordinated metals, and mixed unsupported
systems fail before any output file is opened. Error messages identify the
component and suggest `amber`, `charmm`, or separate parameterization.

The upstream bundle has no ARN file and empty TDB files; those facts are
represented explicitly. R2B/RTP terminal blocks drive termini. CMAP is required:
both `cmap.itp` parameter tables and per-chain `[ cmap ]` terms are emitted.

| Water | Required ion set | Upstream files |
|---|---|---|
| `opc` | `amber19sb-opc` | `opc.itp`, `ions_opc.itp` |
| `opc3` | `amber19sb-opc3` | `opc3.itp`, `ions_opc3.itp` |
| `spc` | `amber19sb-spc` | `spc.itp`, `ions_spc.itp` |
| `spce` | `amber19sb-spce` | `spce.itp`, `ions_spce.itp` |
| `tip3p` | `amber19sb-tip3p` | `tip3p.itp`, `ions_tip3p.itp` |
| `tip4pew` | `amber19sb-tip4pew` | `tip4pew.itp`, `ions_tip4pew.itp` |

No cross-product, fallback, or AMBER99 `ION_PARAMS` substitution is used. Full
hashes, notices, license assessment, and the outstanding external GROMACS
acceptance are in the [provenance record](../provenance/amber19sb-gromacs.md).

## Water-matched ions (AMBER)

By default, `--water` only swapped the water moleculetype; ion atom types were
loaded unchanged from the bundled `ffnonbonded.itp` (Aqvist Na⁺, Dang Cl⁻ — fit
for TIP3P). This caused stability problems when users combined newer water models
(OPC, TIP4P-Ew) with the legacy ions.

`dvbfixer top` now swaps the ion Lennard-Jones parameters to match the water
model. Set `--ion-set auto` (default) and the right set is chosen automatically:

| `--water` | Default ion set | Source |
|-----------|-----------------|--------|
| `tip3p`   | `jc-tip3p`      | Joung & Cheatham 2008 monovalents + Li-Merz 2013 12-6 HFE divalents |
| `spce`    | `jc-spce`       | same papers, SPC/E fit |
| `spc`     | `jc-spce` (alias, warns) | plain SPC was not parametrized by JC — using SPC/E |
| `tip4pew` | `jc-tip4pew`    | same papers, TIP4P-Ew fit |
| `tip4p`   | `jc-tip4pew` (alias, warns) | original TIP4P was not parametrized by JC — using TIP4P-Ew |
| `opc`     | `lm-hfe-opc`    | Sengupta-Li-Merz 2021 monovalents + Li-Song-Merz 2020 12-6 HFE divalents (OPC) |

`--ion-set` can override the default. `lm-iod-opc` swaps to Li-Merz's
ion-oxygen-distance-fit set (better first-shell RDF for OPC, slightly worse
hydration free energy). `dang-legacy` keeps the pre-2008 Aqvist/Dang values
for backwards compatibility with older runs.

Covered ions: **Na⁺, K⁺, Cl⁻, Ca²⁺, Mg²⁺, Zn²⁺**.

**CHARMM** uses its own ions (SOD/CLA/POT/CAL/MGA in the bundled `ions.itp`),
fitted to CHARMM-TIP3P. `--ion-set` is ignored with `--ff charmm`. Using
`--water opc/tip4p/tip4pew` with `--ff charmm` is rejected at the CLI level —
combine OPC with `--ff amber` instead.

OPC water itself is a new water choice. The bundled `FF/amber99sb-ildn-lipid21.ff/opc.itp`
implements the 4-site OPC water (Izadi-Anandakrishnan-Onufriev 2014) with the
M-site as a `virtual_sites3` particle.

## ACPYPE mode (`--acpype`)

Uses OpenMM to parametrize with AMBER14 + GLYCAM_06j-1, converts via ParmEd to AMBER prmtop/inpcrd, then ACPYPE generates GROMACS `topol.top`/`.gro` with `[ pairs_nb ]` directive for per-pair 1-4 parameters. This solves the mixed 1-4 scaling problem (AMBER fudgeLJ=0.5 vs GLYCAM fudgeLJ=1.0) that GROMACS cannot express globally. Output includes position restraints (`#ifdef POSRES` / `#include "posre_{stem}.itp"` / `#endif`) and water/ion moleculetypes ready for `gmx solvate`/`genion`. Best for glycoprotein systems. Ignores `--ff`/`--water`/`--merge` flags.

## Glycolipid support (CHARMM36)

Automatically detects glycolipids — ceramide residues (CER1, CER160, CER180, etc.) covalently bonded to a sugar tree — and builds them as a single GROMACS moleculetype. Designed for CHARMM-GUI PDB output which uses 4-character residue names (CER1, BGLC, BGAL, ANE5, AFUC, etc.).

**How it works:**
- Detects sugar O atom within 2.0 A of ceramide C1S (CHARMM-GUI removes ceramide O1/HO1 at the bond site)
- Builds ceramide from `lipid.rtp` + sugar tree from `carb.rtp` into one moleculetype
- Handles linkage charge redistribution: ceramide O1+HO1 charge goes to C1S, sugar HO1 charge goes to O1
- Sugar O1 at ceramide junction gets type OC301 (linear ether); sugar-sugar junctions get OC3C61 (cyclic ether)
- Sialic acid (Neu5Ac/ANE5AC) handled correctly: links via C2, O2 removed at linkage
- Auto-detects BGAL with N-acetyl atoms (N, HN, CT) and remaps to BGALNA

**Supported ceramides:** CER160 (d18:1/16:0), CER180, CER181, CER2, CER200, CER220, CER240, CER241, CER3E.

**Example** (Fucosyl-GM1 ganglioside from CHARMM-GUI):
```bash
dvbfixer top FucGM1_Charmm.pdb --ff charmm -o gmx_top/ -v
# Output: Glycolipid_ _1.itp (251 atoms, 256 bonds, charge -1.0)
# Residues: CER160 + BGLC + BGAL + BGALNA + AFUC + ANE5AC
```

**Note:** Glycolipid support is CHARMM36 only. AMBER/GLYCAM+Lipid21 cannot be combined for glycolipids (incompatible atom type namespaces, no cross-FF parameters).

## See also

- [`parametrize`](parametrize.md) — GAFF2 small molecules to `#include` from `topol.top`
- [`transplant`](transplant.md) — `--gromacs` uses the same ACPYPE export pipeline
- [BEST_PRACTICES.md](../../BEST_PRACTICES.md) — CHARMM-GUI alternative path

## How it works

Generates GROMACS topology files directly from PDB or GRO files by parsing force field RTP/ARN/R2B/TDB files in Python (no `pdb2gmx`). GRO files are auto-converted to PDB via MDAnalysis. Supports AMBER99SB-ILDN and CHARMM36 force fields (bundled in `FF/` directory). Output is a modular set of `.itp` files with a compact `topol.top` containing only `#include` directives, `[ system ]`, and `[ molecules ]` — no external FF directory needed in the GROMACS working directory. Water (SOL/HOH/WAT/TIP3) and ions are auto-detected and counted for `[ molecules ]`. Small CGenFF molecules (ACET, ACEH, etc.) are auto-detected via distance-based chain splitting and built as independent moleculetypes.

**`--keep-all-hydrogens`** (default OFF): stored on `TopologyBuilder.keep_all_hydrogens`; when True, `build_glycan_chain` and `build_glycolipid_chain` skip populating the `remove_ho` dict (and the associated `charge_adjust` + `type_change` redistribution) at glycosidic-linkage sites, so `HO1`/`HO2`/`HO3`/`HO4`/`HO6` atoms present in the input PDB pass through to the output topology and the linked O keeps its `OC311` hydroxyl type + full RTP charge (instead of becoming `OC3C61` ether). Also plumbed into `acpype_export.export_gromacs` / `prepare_for_openmm` where it disables the `_GLYCAM_KEEP_H` allowlist filter (so `HD22` on NLN etc. survives). Intended for free-reducing-end sugars or charge-round-trip round-trips; at a real glycosidic linkage it produces over-valent O and grompp may warn — help text spells this out.

**Topology generation algorithm:**
1. Resolve PDB residue names to RTP names via `CANONICAL_MAP` + R2B mapping
2. Map PDB atom names to FF atom names via ARN file
3. Build atom list from RTP `[ atoms ]` with types, charges, masses
4. Build bond graph from RTP `[ bonds ]`, resolving inter-residue refs (`-C`, `+N`)
5. Enumerate angles (all 3-atom paths), dihedrals (all 4-atom paths), 1-4 pairs
6. Copy impropers and CMAP (CHARMM) from RTP
7. Apply terminal patches (CHARMM: NH3+/COO- from TDB files; AMBER: separate NXXX/CXXX RTP entries)

**All CHARMM molecule types:** Loads all available RTP files at startup: `aminoacids.rtp`, `carb.rtp`, `lipid.rtp`, `na.rtp`, `cgenff.rtp`, `ethers.rtp`, `metals.rtp`, `silicates.rtp`, `solvent.rtp` (~2400+ residue types). Also loads corresponding `.r2b` files. Chain filter keeps any chain with residues in `STANDARD_AA`, `PDB_TO_GMX`, `builder.residues`, or `PDB_TO_CARB`. Non-protein chains are built without terminal patches or SS bond detection.

**Glycan support (CHARMM):** Parses `carb.rtp`, maps PDB sugar names (NAG, BMA, MAN, GAL, FUC, SIA, BGL, AFU, AMA, BGA) to CHARMM RTP names via `PDB_TO_CARB`. Also accepts CHARMM-GUI native 4-char names (BGLC, BGAL, AFUC, ANE5, etc.) via extended `PDB_TO_CARB` entries. Detects glycosidic bonds from C1-O distances < 2.0 A using parsed chain data (not raw PDB). Protein-sugar links (ASN ND2, SER OG, THR OG1) use 2.5 A cutoff (bonds stretch after minimization). Also recognizes GLYCAM protein residue names (NLN, OLS, OLT). Sialic acid (Neu5Ac) links via C2 anomeric carbon, not C1. Builds glycan trees via BFS. Handles charge redistribution (HO removal → charge to O) and atom type changes (OC311→OC3C61 at linkage sites). When linked O atoms are not in PDB (CHARMM-GUI removes them at glycosidic bond sites), their combined charge (O + HO) is redistributed to the anomeric carbon (C1 or C2). O1/O2 atoms from RTP templates not present in PDB are always skipped (prevents zero-coordinate atoms when glycosidic bond detection misses a link). `_resolve_sugar_rtp()` auto-detects BGAL with N-acetyl atoms (N, HN, CT) and remaps to BGALNA. Inter-residue glycan angles use default ftype (5 for CHARMM, with Urey-Bradley) to match GROMACS parameter lookup. `_GLYCAN_LINKAGE_PARAMS` provides extra bond/angle/dihedral parameters for glycosidic linkage sites where OC311→OC3C61 creates atom type combos not in the standard CHARMM36 distribution (parameters by analogy with CC321D/CC321C variants). Also includes sialic acid C2 linkage params (CC3062-OC3C61 angles/dihedrals for Neu5Ac-galactose junctions).

**Glycolipid support (CHARMM):** Detects ceramide residues (`PDB_TO_LIPID` maps CHARMM-GUI names like CER1→CER160) bonded to sugar trees. Detection: sugar O atom within 2.0 A of ceramide C1S atom (CHARMM-GUI removes ceramide O1/HO1 at the glycosidic bond). `build_glycolipid_chain()` builds the entire glycolipid (ceramide + sugar tree) as a single moleculetype from `lipid.rtp` + `carb.rtp`. Linkage chemistry: ceramide O1+HO1 charge redistributed to C1S, sugar root O1 type changed to OC301 (linear ether, not OC3C61 which is sugar-sugar cyclic ether), sugar HO1 charge redistributed to O1. Inter-residue bond: ceramide C1S → sugar O1. Ceramide-sugar CTO2-OC301 bond/angle/dihedral parameters already exist in `ffbonded.itp` (no extras needed). `read_pdb_chains()` handles 4-char resnames (CER1, BGLC, etc.) that extend into PDB column 21. Chains containing ceramide+sugar are skipped in the main chain loop and built by the glycolipid builder. `_is_ceramide()` checks both PDB and RTP names. `CERAMIDE_RTP` set: CER160, CER180, CER181, CER2, CER200, CER220, CER240, CER241, CER3E.

**Chain splitting in `read_pdb_chains()`:** Detects resseq backward jumps within a chain (e.g. two glycan trees with same chain ID and overlapping residue numbers from `transplant`) and splits into separate sub-chains with generated chain IDs. Sugar-only chains are skipped in the main chain-building loop (handled by glycan detection).

**Water-matched ions (AMBER):** `--water` choices `{tip3p, spc, spce, tip4p, tip4pew, opc}` now drive ion LJ parameters via a new `ION_PARAMS` dict in `top.py`. `--ion-set auto` (default) maps water → ion set: tip3p→`jc-tip3p`, spce→`jc-spce`, tip4pew→`jc-tip4pew`, opc→`lm-hfe-opc`. `spc` and `tip4p` alias to spce/tip4pew with a warning (JC never parametrized plain SPC or original TIP4P). Override via `--ion-set {auto, jc-tip3p, jc-spce, jc-tip4pew, lm-hfe-opc, lm-iod-opc, dang-legacy}`. `dang-legacy` keeps the pre-2008 Aqvist Na⁺/Dang Cl⁻ values for backwards compat. Covers Na⁺/K⁺/Cl⁻/Ca²⁺/Mg²⁺/Zn²⁺ across all four water models with HFE-fit (and IOD-fit for OPC). Sources: Joung-Cheatham *JPCB* 112, 9020 (2008) for monovalents on TIP3P/SPC-E/TIP4P-Ew; Li-Roberts-Chakravorty-Merz *JCTC* 9, 2733 (2013) for 12-6 HFE divalents on the same waters; Sengupta-Li-Wynn-Merz *JCIM* 61, 869 (2021) for monovalents on OPC; Li-Song-Merz *JCTC* 16, 4429 (2020) for 12-6 HFE divalents on OPC. Implementation: `write_top()` calls `_strip_ion_atomtypes()` to remove `Na/K/Cl/C0/MG/Zn` lines from the bundled `ffnonbonded.itp` content, then appends the chosen ion set's atom types via `_emit_ion_atomtypes()`; the output `ions.itp` is generated fresh by `_emit_ions_itp()` instead of copied from the FF dir. For CHARMM the code path is unchanged (CHARMM ions stay bundled). `--ion-set` is ignored with `--ff charmm` (INFO line), and `--water opc/tip4p/tip4pew` with `--ff charmm` is rejected at the CLI (hard error) because CHARMM ions are fit to CHARMM-TIP3P.

**OPC water (AMBER):** New `FF/amber99sb-ildn-lipid21.ff/opc.itp` implements the 4-site OPC water (Izadi-Anandakrishnan-Onufriev *J Phys Chem Lett* 5, 3863, 2014). Geometry doh=0.08724 nm, dhh=0.13712 nm; M-site via `virtual_sites3` funct=1 with a=b=0.14772; charges HW=+0.6791, M=-1.3582, OW=0; LJ on OW only (σ=0.31666 nm, ε=0.89036 kJ/mol). New atom types `OW_opc`/`HW_opc` added to `FF/amber99sb-ildn-lipid21.ff/ffnonbonded.itp`. MW (dummy mass) was already defined for TIP4P/TIP5P and is reused for OPC's M-site.

**Protonation (`--protonate`):** `--protonate all` protonates ALL ASP→ASPP, GLU→GLUP, HIS→HSP (CHARMM) or ASP→ASH, GLU→GLH, HIS→HIP (AMBER). `--protonate CHAIN:NUM[:STATE],...` protonates specific residues (STATE defaults to protonated form based on FF). Missing protonation H atoms (e.g. HD2 for ASPP, HE2 for GLUP, HD1 for HSP) are added with proper geometry using OpenMM's `Modeller.addHydrogens(forcefield, variants=variants)` — same approach as the `protonate` tool. Uses CHARMM FF (`charmm36.xml`) or AMBER FF (`amber14-all.xml`) matching the `--ff` selection. OpenMM variant names (ASH, GLH, HIP, HID, HIE) work with both FFs. The full protein is loaded, H stripped, non-protein residues (glycans) removed, then `addHydrogens` places all H with correct geometry; only the specific protonation H atoms are extracted back into the chain data. Coordinates are near-optimal — should still be refined by energy minimization. **Terminal ASH/GLH limitation (AMBER):** When `--ff amber` is used and ASH/GLH is requested at an N or C terminus, the variant is dropped (AMBER14 has no NASH/NGLH/CASH/CGLH templates), the residue is reverted to standard ASP/GLU (so the standard NASP/CASP/NGLU/CGLU RTP entry is used), and a `UserWarning` is emitted. HID/HIE/HIP have terminal templates so they work at terminals. CHARMM ASPP/GLUP work at terminals via TDB patches.

**Disulfide bonds:** Intra-chain SS bonds (SG-SG between CYS2 residues within the same chain) are added directly to the chain `.itp` `[ bonds ]` section by `build_chain()`. The SG-SG bond is not in the CYS2 RTP definition (it's an inter-residue special bond), so it's added explicitly from the detected SS pairs. The bond is added before the adjacency graph is built, so all derived angles (CB-SG-SG, SG-SG-CB), dihedrals, and 1-4 pairs are generated automatically. Inter-chain SS bonds are written to `interchain_ss.itp` with `[ intermolecular_interactions ]`. Protein-glycan bonds (ASN ND2 - NAG C1, r0=0.143 nm from CHARMM CC3162-NC2D1) also go in `interchain_ss.itp`. Auto-included in `topol.top` after `[ molecules ]` (GROMACS requires this directive after the molecules section). Warning: after `gmx solvate`/`genion`, the `#include` must be moved below SOL/ion entries to remain at the end.

**Output:** Modular set of files:
- `topol.top` — compact file with only `#include` directives, `[ system ]`, and `[ molecules ]`
- `ffparams.itp` — all FF parameters (`[ defaults ]`, `[ atomtypes ]`, `[ bondtypes ]`, `[ angletypes ]`, `[ dihedraltypes ]`, CMAP, NBFIX, glycan linkage params)
- `{chain_name}.itp` — each chain moleculetype in its own file (e.g. `Protein_chain_H.itp`, `Glycan_A_1001.itp`, `Glycolipid_ _1.itp`)
- `water.itp` — water moleculetype (rigid settles)
- `ions.itp` — ion moleculetypes
- `posre_*.itp` — position restraint files (used with `#ifdef POSRES`)
- `interchain_ss.itp` — inter-chain SS bonds + protein-glycan bonds with `[ intermolecular_interactions ]` (must stay at end of `topol.top`, after SOL/ions)
- `conf.pdb` — output PDB with FF atom names (includes ions/BUF particles from input)
FF directory is only used at build time for RTP parsing, not needed at runtime.

**Key writers:** `_write_moleculetype(f, chain_top, bonded_types)` writes a chain moleculetype section to a file. `write_top()` generates the modular output via `_read_ff_content()` (strips preprocessor directives), `_parse_defaults()` (extracts `[ defaults ]`), `_write_water_topology()` (extracts rigid settles version from water .itp), and `_dedup_atomtypes()` (removes duplicate water/ion atom type entries from #ifdef blocks, e.g. HT, OT with heavy/real mass variants).

**Key data structures:** `ChainTopology` dataclass holds atoms, bonds, pairs, angles, dihedrals, impropers, cmap per chain. `TopologyBuilder` class loads FF data, builds chains, writes output. `rtp_parser.py` provides `parse_rtp()`, `parse_r2b()`, `parse_arn()`, `parse_tdb()`, `parse_atomtypes()`.

**Atom name matching (`_match_atom_names`):** Multi-pass algorithm: (0) exact match, (0a) ARN reverse mapping (e.g. HN→H for CHARMM), (1) strip trailing digits, (2) common H renames, (3) numbered variants, (4) singleton numbered atoms (HG1→HG). Validates all RTP heavy atoms are present; warns on extra/missing atoms.

**`--acpype` mode:** Alternative to RTP-based topology. Uses `acpype_export.py` shared module: OpenMM (AMBER14+GLYCAM) → ParmEd → ACPYPE → GROMACS `topol.top`/`.gro` with `[ pairs_nb ]` for mixed 1-4 scaling (BERNARDI 2019 — AMBER fudgeLJ=0.5 vs GLYCAM fudgeLJ=1.0 reconciled via per-pair scaling). Output includes `#ifdef POSRES` / `#include "posre_{stem}.itp"` / `#endif` in the moleculetype section, and water/ion moleculetypes appended before `[ system ]`. Ignores `--ff`/`--water`/`--ignh`/`--merge` flags. Respects `--ss` for explicit disulfide bonds. Handles glycosylated proteins: auto-detects SS bonds via `detect_ss_bonds` from CONECT AND distance fallback (SG-SG within 2.5 Å, recognizes SG on CYS/CYX/CYM), reorders chains (protein first, glycan after), filters glycan TER records, captures/restores AMBER variant names across PDBFile normalization (incl. CYX/CYM not just HID/HIE/HIP/ASH/GLH/LYN), `add_glycam_bonds(positions=...)` adds intra-residue + protein-glycan peptide + sugar-sugar glycosidic bonds, adds HD21 for NLN, uses `ignoreExternalBonds=True` and `residueTemplates` for CYX disambiguation. Defensive CYS template forcing in `res_templates` loop: any CYS not yet captured gets explicit template (`CYS` if HG present, `CYX` if HG missing — assume disulfide; handles terminals NCYS/CCYS/NCYX/CCYX). **Selective H stripping** via `_GLYCAM_KEEP_H` allowlist: NLN keeps `{H, HA, HB2, HB3, HD21}`, OLS keeps `{H, HA, HB2, HB3}`, OLT keeps `{H, HA, HB, HG21/HG22/HG23}`. Only strips disallowed atoms (HD22 on NLN, HG on OLS, HG1 on OLT, CHARMM HN/HT*). This preserves the carefully-placed HD21 geometry produced by minimize's `_rigid_track_glycan_trees` through `top --acpype` (verified: CG-ND2-HD21 = 112° in output .gro, matches input; was 179° before the fix). **Terminal ASH/GLH limitation:** AMBER14 has no NASH/NGLH templates (never parameterized via RESP). Terminal ASH/GLH are converted to standard ASP/GLU with protonation H stripped; emits `UserWarning`.

## Batch mode

`top` does not support directory batch input. Generate each topology from one
explicit input structure per invocation. See the
[batch support matrix](../batch-mode.md#support-by-tool).
