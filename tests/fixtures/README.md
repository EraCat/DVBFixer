# Tracked test fixtures

These are the input structures and companion sequences read by the pytest
suite. They were copied from the historical, mostly untracked `test/` working
tree so CI and fresh clones exercise the same structural regressions. Generated
outputs (`*_zbs`, prepared/minimized files, GRO files, and topology trees) are
deliberately excluded.

Run `sha256sum -c tests/fixtures/MANIFEST.sha256` from the repository root to
verify that none of the source fixtures changed accidentally.

## Fixture inventory

| Tracked fixture | Historical source | Purpose |
|---|---|---|
| `ASN.pdb` | `test/ASN.pdb` | Minimal two-residue ASN input |
| `assemblies/8XJ0.pdb`, `assemblies/8XJ0_chain_A_observed.fasta` | `test/homology_modelling/8XJ0.pdb`; FASTA derived from its observed chain A | Four Fab biological assemblies declared by REMARK 350/BIOMT; post-2023 temporal-holdout diffusion pilot |
| `hinge_CH3_glycosylated.pdb` | `test/default.pdb` | GLYCAM hinge/CH3, CYX, rename/convert/CONECT tests |
| `multistate.pdb`, `multistate.fasta` | `test/multistate/test_multistate.pdb`, `test/multistate/test.fasta` | Eleven-model split input and companion sequence |
| `8cz8/*` | `test/8cz8/*` | Pure-protein renumbering and truncated-LYS deterministic rebuild; companion FASTA |
| `lipid/*` | `test/lipid/*` | 7X35 protein/PLM residue-number collision; companion FASTA |
| `regressions/1DQJ.pdb` | `test/shit/1DQJ_original.pdb` | Disulfide-rich antibody |
| `regressions/{1EMV,1FR2,2VLN,2VLQ}.pdb` | Corresponding `test/shit/*_original.pdb` | Historical coincident-H/chirality/NaN failures |
| `trastuzumab.pdb` | `test/shit/trastuzumab.pdb` | PDB-named glycoprotein stress case |
| `1VCU.pdb` | `test/protein_ligand/1VCU.pdb` | Protein with DAN and two EPE ligands |
| `3ry6.pdb` | `test/3ry6/3ry6.pdb` | Under-annotated four-site glycoprotein |
| `glycosilated_mAb_CHARMM.pdb` | `test/glycosilated_mAb_Charmm-GUI/conf.pdb` | CHARMM-GUI glycoprotein topology input |
| `numbering/*` | `test/numbering_problem/*` | 8B01 bound/unbound structures and reference FASTA |
| `c_glh/*` | `test/C_GLH/{8cde_t_u.pdb,8cde_renamed.fasta}` | Terminal GLH/capping preparation regression input and companion FASTA |
| `warnings/*` | `test/warnings/{8ct6_t_b.pdb,8ct6_renamed.fasta}` | Real addHydrogens/connectivity-warning input and companion FASTA |
| `overlap/8dis_t_u.pdb` | `test/overlap/8dis_t_u.pdb` | Coordinate-identical chains `d`/`D` caused by missing MODEL/ENDMDL separators |
| `insertion_codes/{7K8S.pdb,7K8S.fasta}` | RCSB PDB entry 7K8S coordinate and FASTA downloads | Antibody heavy-chain insertion-code diffusion benchmark (`H/82A`-`H/82C`) |
| `protein_context/{1UBQ,1TIM,1A3N}.pdb` | Unmodified RCSB PDB downloads on 2026-10-14 from `https://files.rcsb.org/download/<ID>.pdb` | Frozen protein-context expansion: ubiquitin nonlocal-contact strata, triosephosphate-isomerase dimer, and hemoglobin protein interface |

The protein-context materializer derives protein-only, heavy-atom inputs from
these deposited sources. Heterogens (including 1A3N hemes) are excluded explicitly;
this is a protein-context mechanism study, not acceptance for complete hemoglobin
chemistry. Low/high contact counts are structural proxies, not measured solvent
accessibility. Derived masks, controls, and outcomes live in ignored evidence
archives; only deposited source inputs and frozen manifests are tracked.

## 8UCD molecule retention and connectivity

`rename_mols/structure.pdb` is the user-provided 8UCD preparation input copied
unchanged from `test/rename_mols/structure.pdb`. Split regression tests verify
that all 807 heterogen atoms (nine LBN/FAD/HEM residues) survive retention and
unique-chain assignment with unchanged coordinates and serials.

## 1VCU ligand chemistry

The optional-SMILES regression uses RCSB Chemical Component Dictionary
connectivity and DAN stereochemistry. The selected forms represent the
dominant DAN carboxylate and a representative HEPES/EPE zwitterion near
physiological pH, so the expected acidic oxygens remain unprotonated:

- DAN: `CC(=O)N[C@@H]1[C@H](C=C(O[C@H]1[C@@H]([C@@H](CO)O)O)C(=O)[O-])O`
- EPE: `C1CN(CC[NH+]1CCO)CCS(=O)(=O)[O-]`

Sources: [RCSB DAN](https://www.rcsb.org/ligand/DAN),
[RCSB EPE](https://www.rcsb.org/ligand/EPE), and
[PubChem HEPES (CID 23831)](https://pubchem.ncbi.nlm.nih.gov/compound/Hepes).
At pH 7.4, HEPES is close to its approximately 7.55 buffer pKa, so protonated
zwitterionic and deprotonated anionic microspecies coexist; the test chooses
the slightly more populated zwitterion. A protein binding site can shift this
balance, so users should supply the microspecies appropriate to their system.
