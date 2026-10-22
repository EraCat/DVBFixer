# `dvbfixer convert`

[User guide](../README.md) · [Command index](index.md) · [CLI reference](../reference/convert.md)

Converts glycan naming conventions and protein protonation-variant labels.
For ordinary protein atom-label conversion, use [atom-names](atom-names.md).
This command does not predict pKa or parameterize a structure.

## Quick start

```bash
dvbfixer convert crystal.pdb -o glycam.pdb
```

**Result:** a structure using GLYCAM/AMBER conventions for supported components.
Inspect glycan identities and links before following the
[glycoprotein recipe](../pipelines.md#glycoprotein-preparation-with-glycam).

## Conversion behavior

**Default direction (`--to-amber`)** — converts PDB / CHARMM-named input to AMBER-friendly naming:
- Sugars: PDB codes (NAG, BMA, MAN, GAL, FUC, SIA, …) → GLYCAM 3-char codes `[linkage][sugar][anomer]` (UYB, VMB, 0MA, 6LB, 0fA, 0SA, …)
- Glycoprotein residues: `ASN→NLN`, `SER→OLS`, `THR→OLT` when sidechain-bonded to a sugar
- Protonation variants: CHARMM `HSD→HID`, `HSE→HIE`, `HSP→HIP`, `ASPP→ASH`, `GLUP→GLH`, `LSN→LYN` (and LSN's `HZ1→HZ2`, `HZ2→HZ3` to match the AMBER LYN template)
- Atom names: hydroxyl `HO3→H3O`, N-acetyl `C7→C2N`, `O7→O2N`, `C8→CME`, methyl `HT1→H1M`, etc.
- Sialic acid (`SIA→0SA`): stereo-specific atom renames including `H3/H32→H3A/H3E`, `H9/H92→H9R/H9S`, `HN5→H5N`, methyl `H11/H112/H113→H1M/H2M/H3M`; the spurious `HO1B` (PDBFixer-added) is dropped
- ROH cap added at the reducing end (suppress with `--no-roh`)

Output is consumable by `prepare`, `minimize`, `protonate`, `top --acpype`.

**Reverse direction (`--to-charmm`)** — converts AMBER/GLYCAM-named input to CHARMM-friendly naming:
- Sugars: GLYCAM codes → standard 3-char PDB / CHARMM-GUI 4-char codes (NAG/NDG/BMA/MAN/GAL/FUL/SIA/… or BGLCNA/BMAN/AMAN/ANE5AC/… where `top --ff charmm` maps via `PDB_TO_CARB`)
- Glycoprotein residues: `NLN/OLS/OLT → ASN/SER/THR`; ROH/OME caps dropped
- Protonation variants: AMBER `HID→HSD`, `HIE→HSE`, `HIP→HSP`, `ASH→ASPP`, `GLH→GLUP`, `LYN→LSN` (and LYN's `HZ2→HZ1`, `HZ3→HZ2` to match the CHARMM LSN convention); `CYX→CYS` (CHARMM uses DISU patch via SSBOND)
- CYM stays as CYM (CHARMM36 has a `[ CYM ]` residue)
- Linkage information preserved via CONECT records, not in the residue name

Output is consumable by `top --ff charmm`.

**Accidental wrong-FF naming** is handled automatically: if the input has the wrong FF's convention (e.g. AMBER LYN in a structure being converted with `--to-charmm`), it's renamed to the target convention. If the input is already in the target convention (e.g. CHARMM LSN + `--to-charmm`), nothing changes.

Text-based — no OpenMM dependency. Handles input from PDB, CHARMM-GUI, or `dvbfixer prepare`.

**Header records are preserved** (since 0.7.9): SEQRES, HELIX, SHEET,
CRYST1, and other non-ATOM/HETATM/CONECT records pass through
unchanged from input to output. This matters if you pipe `convert`'s
output straight into `model`/`zbs` — `model` needs SEQRES to know the
full sequence including missing residues.

**Glycosidic-bond detection combines CONECT and distance** (since
0.7.9): if the input's CONECT/LINK records document some but not all
of its glycosylation sites (a real gap in many deposited PDBs — not
every site was carefully annotated), the distance-based detector now
fills in whichever sites CONECT doesn't already cover, instead of
trusting CONECT exclusively the moment any CONECT record is present.

**Stale-H cleanup**: when an input labels a residue with an AMBER variant name but still carries H atoms the AMBER template doesn't have (e.g. a user manually renamed `LYS→LYN` without dropping `HZ1`), `convert` drops the extra H atoms during its rename pass:

| Variant | Atoms dropped | Why |
|---------|---------------|-----|
| `LYN` | `HZ1`, `1HZ` | AMBER LYN keeps HZ2 + HZ3 only |
| `CYX` | `HG`, `HG1` | Disulfide-bonded SG has no H |
| `CYM` | `HG`, `HG1` | Deprotonated SG has no H |
| `HID` | `HE2` | HD1-only tautomer |
| `HIE` | `HD1` | HE2-only tautomer |

`HIP`, `ASH`, `GLH` are not in the table — they ADD an H rather than miss one. Vanilla `LYS`/`CYS`/`HIS` are untouched.

## Usage

```bash
# Default direction: PDB/CHARMM → GLYCAM + AMBER (writes input_amber.pdb)
dvbfixer convert input.pdb -v

# Explicit (same as default)
dvbfixer convert input.pdb --to-amber -v

# Reverse: GLYCAM/AMBER → CHARMM (writes input_charmm.pdb)
dvbfixer convert input.pdb --to-charmm -v

# Without ROH cap at reducing end (default direction only)
dvbfixer convert glycan.pdb --no-roh

# Custom output
dvbfixer convert input.pdb -o output.pdb -v
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `-o`, `--output` | `<input>_amber.pdb` (or `_charmm.pdb` with `--to-charmm`) | Output file path |
| `--to-amber` | (default) | PDB/CHARMM → GLYCAM (sugars) + AMBER (protonation variants). Mutually exclusive with `--to-charmm`. |
| `--to-charmm` | off | Reverse direction: GLYCAM/AMBER → CHARMM. |
| `--no-roh` | off | Do not add ROH cap at the reducing end (default direction only) |
| `--no-infer-conect` | off | Skip automatic CONECT inference (default: infer missing glycosidic/glycosylation bonds so linkage detection works on CONECT-less inputs) |
| `-v`, `--verbose` | off | Print conversion details |

## GLYCAM Naming Convention

Each sugar residue gets a 3-character name: `[linkage][sugar][anomer]`

**Linkage code** (1st character): `0`=terminal, `2`-`9`=single position, `V`=O3+O6, `W`=O3+O4, `U`=O4+O6, `Z`=O2+O3, `X`=O2+O6, `Y`=O2+O4 (multi-linkage for branching sugars).

**Sugar code** (2nd character): `G`=glucose, `L`=galactose, `M`=mannose, `Y`=GlcNAc, `V`=GalNAc, `f`=fucose (lowercase=L-sugar), `S`=Neu5Ac, `X`=xylose, `R`=ribose, etc.

**Anomer code** (3rd character): `A`=alpha, `B`=beta.

## Protonation-variant mapping table

| State | AMBER (`--to-amber`) | CHARMM (`--to-charmm`) | Glycam-stage atom changes |
|---|---|---|---|
| Protonated K (cationic) | LYS | LYS | none |
| Neutral K | LYN | LSN | `--to-charmm`: HZ2→HZ1, HZ3→HZ2 (and reverse) |
| HIS, ND1 only | HID | HSD | none |
| HIS, NE2 only | HIE | HSE | none |
| HIS, doubly protonated | HIP | HSP | none |
| Protonated D | ASH | ASPP | none |
| Protonated E | GLH | GLUP | none |
| Disulfide C | CYX | CYS (+ DISU patch) | none |
| Deprotonated C | CYM | CYM | none |

Methylene H renames (HB2/HB3 ↔ HB1/HB2 etc.) and backbone H ↔ HN are NOT applied here — `top.py`'s ARN + methylene-shift passes handle them during topology generation.

## Example

```text
BGC(res1, child at O4)     -> 4GB
GAL(res2, children at O3+O4) -> WLB
SIA(res6, terminal)        -> 0SA
NGA(res3, child at O3)     -> 3VB
GAL(res4, child at O2)     -> 2LB
FUC(res5, terminal)        -> 0fA
+ ROH cap at reducing end
```

## See also

- [`transplant`](transplant.md) — pair with `convert` for the GLYCAM-Web glycoprotein workflow
- [`top`](top.md) — `--acpype` consumes default `convert` output; `--ff charmm` consumes the `--to-charmm` output
- [`prepare`](prepare.md) / [`minimize`](minimize.md) / [`protonate`](protonate.md) — all consume the default (AMBER) direction
- [BEST_PRACTICES.md](../../BEST_PRACTICES.md) — full GLYCAM glycoprotein recipe

## How it works

Bidirectional converter for BOTH sugar nomenclature AND protein protonation variants between PDB/AMBER/GLYCAM and CHARMM conventions. Two modes selected by a mutually-exclusive flag pair, default is `--to-amber`:

**Default (`--to-amber`)**: PDB/CHARMM → GLYCAM + AMBER. Renames sugars from standard PDB codes (BGC/GAL/NAG/...) to GLYCAM 3-character `[linkage][sugar][anomer]` codes (UYB/4YB/VMB/0SA/...). Linkage detected from CONECT records (or C1-O distance < 2.0 Å fallback). Single linkage: `0`=terminal, `2`-`9`=position. Multi-linkage: `V`=O3+O6, `W`=O3+O4, `U`=O4+O6, etc. Sugar codes: `G`=Glc, `L`=Gal, `M`=Man, `Y`=GlcNAc, `V`=GalNAc, `f`=Fuc (lowercase=L-sugar), `S`=Neu5Ac. Anomer: `A`=alpha, `B`=beta. Handles sialic acid (anomeric C2 not C1), ROH cap at reducing end, and protein-linked glycans (ASN→NLN, SER→OLS, THR→OLT). Also renames CHARMM protonation variants to AMBER (HSD→HID, HSE→HIE, HSP→HIP, ASPP→ASH, GLUP→GLH, LSN→LYN with HZ1→HZ2, HZ2→HZ3 atom rename via `PROTONATION_CHARMM_TO_AMBER` + `PROTONATION_ATOM_RENAME_TO_AMBER`). Text-based, no OpenMM dependency. H addition handled downstream by `transplant --relax` or `prepare`. Default output suffix: `_amber`.

**Reverse (`--to-charmm`)**: GLYCAM/AMBER → CHARMM. Strips the GLYCAM linkage character, inverts atom-name maps, drops ROH/OME caps, reverts NLN/OLS/OLT→ASN/SER/THR. Output uses 3-char PDB sugar codes (NAG/NDG/BMA/MAN/GAL/FUL/SIA/...) accepted natively by CHARMM-GUI and by `dvbfixer top --ff charmm` (which maps them to CHARMM RTP names via `PDB_TO_CARB`). Linkage info preserved via CONECT records. Also renames AMBER protonation variants to CHARMM (HID→HSD, HIE→HSE, HIP→HSP, ASH→ASPP, GLH→GLUP, LYN→LSN with HZ2→HZ1, HZ3→HZ2 atom rename; CYX→CYS for disulfide-bonded; CYM stays as CYM since CHARMM36 has a `[ CYM ]` residue). Default output suffix: `_charmm`.

**Idempotent both ways**: input already in the target convention is left unchanged. Input with the "wrong" FF naming (e.g. AMBER LYN in a structure being converted with `--to-charmm`) is correctly renamed to the target.

**4-char CHARMM resname I/O** (`_parse_pdb` + `_format_atom_line`): CHARMM-GUI 4-char names (ASPP/GLUP/BGLC/AGLC/BMAN/AMAN/BGAL/AGAL/BFUC/AFUC/BGLCNA/AGLCNA/BGALNA/AGALNA/ANE5/ANE5AC/CER1/CER160/...) extend into PDB col 21 (the standard chain-ID col). The parser detects them via the `_CHARMM_4CHAR_RESNAMES` set and reads chain from col 21 in that case (vs col 22 for 3-char). The writer's `_format_atom_line` builds `f" {resname[:4]:<4s}"` for 4-char resnames (altLoc space + 4-char without gap) or `f" {resname:>3s} "` for 3-char (altLoc + 3-char + gap), then appends chain at col 21 in both cases.

**Stale-H cleanup for AMBER protonation variants** (`PROTEIN_VARIANT_ATOM_DROP`): when the input PDB labels a residue with an AMBER variant name (LYN/CYX/CYM/HID/HIE) but still carries H atoms that the variant template doesn't have — common when a user manually renamed LYS→LYN to mark deprotonation but didn't strip HZ1 — convert drops the extra H atoms during its rename pass so the output matches the AMBER template. Drops: LYN→drop HZ1/1HZ; CYX/CYM→drop HG/HG1; HID→drop HE2; HIE→drop HD1. HIP/ASH/GLH have no drops (they ADD an H rather than missing one). NLN/OLS/OLT HD22/HG/HG1 drops are still handled by the protein-link path. Vanilla LYS/CYS/HIS are untouched.

**Atom renaming (forward):** Multiple rename maps applied in order: (1) residue-specific `GLYCAM_ATOM_MAP` (C7→C2N, O7→O2N, C8→CME for N-acetyl sugars; for SIA: C10→C5N, C11→CME, O10→O5N plus stereo-specific H3→H3A, H32→H3E, H9→H9R, H92→H9S, HN5→H5N, H11/H112/H113→H1M/H2M/H3M), (2) universal hydroxyl H rename (`_HYDROXYL_H_RENAME`: HOn → HnO), (3) PDB-style N-acetyl rename (`_NACETYL_RENAME_PDB`: C7→C2N, O7→O2N for inputs already partially renamed), (4) CHARMM-GUI style N-acetyl rename (`_NACETYL_RENAME_CHARMM`: N→N2, HN→H2N, C→C2N, O→O2N, CT→CME, HT1→H1M etc. — only for N-acetyl sugars). Plus `GLYCAM_ATOM_DROP['SIA'] = {HO1A, HO1B}` strips the spurious H that PDBFixer mis-adds to the sialic carboxylate (GLYCAM template has no slot there). This ensures correct atom names regardless of whether the input comes from PDB, CHARMM-GUI, or `dvbfixer prepare`.

**Atom renaming (reverse, `--to-charmm`):** Inverse atom maps `_REV_HYDROXYL_H`, `_REV_NACETYL_PDB`, `_REV_GLYCAM_ATOM_MAP['SIA']` are built by dict-inverting the forward maps. NAG/NDG/NGA/A2G atoms revert to standard PDB names (C7/C8/N2/HN2/H81/H82/H83/HO3/HO4/HO6). SIA atoms revert to PDB sialic naming (C10/C11/O10/H111/H112/H113/HN5/H31/H32/H91/H92).

**ATOM vs HETATM:** `_format_atom_line()` writes `ATOM` records for standard amino acids (including AMBER protonation variants HIE/HID/HIP/ASH/GLH/CYX/CYM/LYN and GLYCAM protein residues NLN/OLS/OLT) and `HETATM` for sugar residues. This is critical for downstream tools that expect protein residues as ATOM records.

**Pipeline:** Forward output feeds `dvbfixer top --acpype` (AMBER14+GLYCAM). Reverse (`--to-charmm`) output feeds `dvbfixer top --ff charmm` (CHARMM36). The same source structure can drive both FFs.

## Batch mode

`convert` supports independent directory conversion in either direction:
`dvbfixer convert --input-dir structures --output-dir glycam --to-amber`.
See [Batch mode](../batch-mode.md) for shared keys.
