# Intact deposited-input reconstruction recheck

## Change prompted by visual inspection

This repeats the original mask locations after the
[input-truncation audit](a100-input-truncation-audit.md). No source chain or
observed protein segment may be cropped to make the experiment runnable.
Distance selection controls **engine conditioning**, not which observed
coordinates remain in the scientific input/output.

The frozen cohort contains the **47 original structural masks**, one seed (7)
each, from all ten reviewed sources. It is a development recheck, not a new
independent validation cohort. No new gap locations are chosen after looking at
results. Existing cropped archives are preserved separately.

## Full input and supported scope

Every case has an exact deposited `01_before_gap.cif` and a complete-complex
`02_gapped_input.cif` in the project-root `gap_visual_review_intact/` folder.
The independent input audit verifies every outside atom identity/coordinate and
that only the original declared target residues are removed, including for
unsupported cases. Unsupported chemistry is not removed from these CIF pairs.

For supported pure-protein cases, PDB preparation is explicitly solvent-free and
heavy-only, choosing blank/A conformers. Every observed protein residue and chain
must remain; a failed count check rejects the source. Canonical protein HETATM
records use the existing sanitizer. Atom/residue/chain identity and coordinates
are preserved at PDB precision. Incomplete or ambiguous conditioning is rejected,
not hidden by deleting a segment.

| Source | Complete observed protein residues | Engine-axis residues per case | Cases |
|---|---:|---:|---:|
| 12NP | 889, eight chains | 119–134 | 5 |
| 13EE | 302, two chains | 79–147 | 5 |
| 21TW | 638, four chains | 80–173 | 5 |
| 23IT | 884, six chains | 69–164 | 5 |
| 24BT | 357, three chains | 84–132 | 5 |

Thus 25 cases are admitted for inference. The 512-residue limit applies to the
explicit engine axis, not to preserved source coordinates. Every other observed
protein atom remains in the input/output and in the whole-source force-field
working system, even when not used as a learned-conditioning feature.

The other **22 original masks** are explicitly unsupported by the current
protein-only Protenix/refinement protocol, with no replacement:

| Source | Cases | Retained incompatibility |
|---|---:|---|
| 21CH | 2 | DNA and Zn |
| 22VH | 5 | CYC heterogens |
| 25II | 5 | HYP/DPN, glycans, ligands/lipids/ions; incomplete side chains also recorded |
| 25VF | 5 | SF4 cofactors |
| 29HO | 5 | CAS89/CAS77 and CAC/PEG/A1J2L; incomplete LYS2057 also recorded |

In particular, 29HO's full chain V remains in both CIF files; it is not shortened
to make the source protein-only. No legacy/backend fallback is used.

## Native breaks and local context

Local context considers every retained source chain, using minimum heavy-atom
distance to the gap's observed anchor atoms, 6/10 Å shells, sequence padding two,
and target flanks eight. There is no nearest-single-partner preselection and no
120-residue partner cap. Required contacts exceeding the engine budget cause an
explicit rejection rather than dropping contacts.

Native coordinate gaps remain native gaps. PDB `TER` records mark them without
renaming or deleting either observed segment. The research-only
`intact-native-segments-v1` context policy represents selected discontinuous
segments as separate engine entities with exact inverse source identities.
Generated indices distinguish the artificial test gap, which is not split into
two entities. Explicit TER boundaries are respected even at short C–N distances.
Production/default context policies and public capability limits are unchanged.

Before inference, template preflight verifies that every entity contains exactly
its declared observed residues; no extra native segment can disappear during
template construction. The complete input audit covers all 47 CIF pairs and all
25 PDB/request/template mappings.

Unobserved native residues outside the test gap are **not rebuilt**. Temporary
force-field topology treats those observed segments as separate termini; that
is an approximation to a molecule with unresolved connecting residues. This run
preserves the full observed environment, not a completed biochemical molecule.

## Frozen execution protocol

- Protenix on the A100, pinned checkpoint/source/profile, seed 7, one cycle,
  200 denoising updates with per-step exact reinjection.
- Existing rigid v6 local OpenMM CUDA refinement: only the generated residues
  move, all observed background atoms fixed, no solvent and no dynamics.
- Unchanged geometry, chirality, atom-identity and fixed-coordinate gates.
  No reference RMSD ranking, tuning or acceptance criterion.
- Every admitted case is attempted once; execution/refinement failures remain
  archived and counted. All input-scope exclusions remain separately visible.
- Raw/restored results are copied into the matching intact visual-review folders.
  Full original background atom records must match the intact pre-gap source
  exactly, not merely the selected engine context.

Frozen input manifest: `intact-recheck-cohort.json`, SHA-256
`d0d68ac0630710f70bd4fb22d0201a1ed131d9331b002e020cc95af03c5d5707`.
Execution protocol, environment and code hashes:
`intact-recheck-run-protocol.json`.

Inputs and input-audit evidence: `.artifacts/intact-recheck-cohort/`.
Results: `.artifacts/intact-recheck-results/`.
Progress log: `.artifacts/intact-recheck.log`.
Visual review: `gap_visual_review_intact/`.

## Completed results and independent audit

All 25 admitted cases were attempted. Generation succeeded in every case;
24 returned a refined candidate. One refinement was stopped by its final
chirality safety assertion: `23IT`, length 25, ALA93, signed volume
−0.00055 nm³. No refined structure was published for that case. Its raw candidate
was independently checked and remains available with the failure log; the case
stays in the denominator.

Geometry acceptance is **3/25 raw and 13/25 after local refinement**. Ten
raw-failing cases are rescued, all three raw-passing cases remain passing.
Eleven returned refined candidates fail geometry and one additional case fails
the chirality safeguard before a refined artifact is returned.

| Gap length | Attempted | Raw accepted | Refined accepted | Safety failures without refined output |
|---|---:|---:|---:|---:|
| 5 | 5 | 2 | 5 | 0 |
| 13 | 5 | 1 | 5 | 0 |
| 25 | 5 | 0 | 2 | 1 |
| 26 | 5 | 0 | 1 | 0 |
| 50 | 5 | 0 | 0 | 0 |

| Source | Raw accepted | Refined accepted | Additional safety failures |
|---|---:|---:|---:|
| 12NP | 1/5 | 4/5 | 0 |
| 13EE | 1/5 | 2/5 | 0 |
| 21TW | 1/5 | 3/5 | 0 |
| 23IT | 0/5 | 2/5 | 1 |
| 24BT | 0/5 | 2/5 | 0 |

Among the 24 returned refined candidates, hard-gate failures overlap: severe
steric overlap in ten cases, junction length in eight, gross bond lengths in
five, bond angles in five, amide planarity in five, Ramachandran in three and
internal backbone breaks in two. The additional chirality safety failure is
reported separately, not misclassified as a missing or unsupported input.

The independent final audit revalidates both runner results and their traces,
confirms 200 exact per-step reinjections, and compares every original background
atom record against the intact pre-gap reference. Preservation holds for all
25 raw candidates and all 24 returned refined candidates. Every returned
refined candidate has zero fixed-heavy coordinate displacement and zero
detectable D-Cα. The failed chirality case returns no refined PDB.

For each of the eleven returned geometry failures, diagnostic findings were
also compared with the intact source before test-gap deletion. No finding was
exactly identical to a corresponding source finding. This exact-record check
does not prove that every source imperfection is absent; the comparison is
diagnostic and never changes a gate.

The corresponding 25 cropped cases previously passed 21/25 after refinement;
the intact protocol passes 13/25. **Do not attribute this entire difference to
one omitted partner:** this is a whole-protocol change (intact source, explicit
native segmentation and local conditioning for every length), not an isolated
causal ablation. In particular, the old long-gap engine policy included full
preselected fragments, whereas this recheck uses local anchor-shell features.
What is established is that the earlier cropped acceptance numbers cannot stand
in for the intact-input experiment. Public capabilities and gates are unchanged.

### Review files and evidence

`gap_visual_review_intact/` now contains all 47 input pairs, an `index.csv`, a
`RESULTS.md` summary, per-case `RESULT.md`, and:

- `01_before_gap.cif`, `02_gapped_input.cif`: full deposited complex, including
  retained unsupported chemistry; only the declared test gap is removed.
- Eligible cases additionally have intact prepared PDB input pairs.
- `03_restored_relaxed.pdb`: 24 returned refined candidates, including the
  rejected geometry candidates, clearly labeled PASS/FAIL in metadata.
- `04_restored_raw.pdb`: all 25 generated candidates.
- The chirality-rejected case has `failure.log` and no `03` PDB.
- Rejected refined cases have `physical_findings.json`, including source
  comparison. Unsupported cases retain full inputs and explicit reasons.

Final independently audited report:
`.artifacts/intact-recheck-results/analysis.json`, SHA-256
`f8c4c05a88b70375e949d978bd2f1b7c88b2c4ac1747c96bdbe9e9680e81bb67`.
Frozen execution protocol SHA-256:
`5d80eaca3ec5a810dd58cf0cafd02f360fd6f5201196032c4fa9a345f241228d`.
The visual-copy verification is logged in
`.artifacts/intact-recheck-visual-audit.log`; `CHECKSUMS.sha256` covers the review
folder. Reference RMSD was not used for ranking, selection or acceptance.
