# Amber19SB GROMACS Bundle Provenance

Retrieved and revalidated on 2026-09-30.

## Selected Release

- Upstream: official GROMACS repository, <https://github.com/gromacs/gromacs>
- Latest stable non-prerelease tag found: `v2026.3`
- Fully resolved tag commit: `121090014570a53a17ea391bcddae45e5ea05eb4`
- Commit date: 2026-06-25T13:35:24+00:00
- Source directory: `share/top/amber19sb.ff`
- Immutable source URL: <https://github.com/gromacs/gromacs/tree/121090014570a53a17ea391bcddae45e5ea05eb4/share/top/amber19sb.ff>

The tag lookup used:

```bash
git ls-remote --tags https://github.com/gromacs/gromacs.git 'v*'
```

Prerelease names containing `beta` or `rc` were excluded. The exact retrieval
and resolution commands were:

```bash
git clone --depth 1 --branch v2026.3 https://github.com/gromacs/gromacs.git .upstream-gromacs-v2026.3
git -C .upstream-gromacs-v2026.3 rev-parse HEAD
git -C .upstream-gromacs-v2026.3 show -s --format='%H%n%aI%n%s' HEAD
```

## Byte Verification

`FF/amber19sb.ff` was copied directly from the selected checkout. No upstream
parameter file was edited. Per-file SHA-256 values are recorded in
[`amber19sb-v2026.3.sha256`](amber19sb-v2026.3.sha256). The manifest file itself
has SHA-256 `7006844bb45818b495740b805c7a9cc467e22958f883d97824f753cf0567d4c9`.

Verification commands:

```bash
sha256sum .upstream-gromacs-v2026.3/share/top/amber19sb.ff/*
diff -rq FF/amber19sb.ff .upstream-gromacs-v2026.3/share/top/amber19sb.ff
sha256sum docs/provenance/amber19sb-v2026.3.sha256
```

The repository-level untracked candidate was useful for comparison but was not
staged. Against `v2026.3`, it differed in exactly three files:

- `forcefield.itp`: upstream uses the full `0.83333333333333333` Coulomb 1-4 factor.
- `spc.itp`: upstream uses the `OW_spce`/`HW_spce` atom types.
- `spce.itp`: upstream uses the `OW_spce`/`HW_spce` atom types.

All other candidate files were byte-identical. Because the complete candidate
was not byte-identical, DVBfixer ships the independently retrieved official
`v2026.3` tree instead.

## Metadata Audit

- `aminoacids.arn` is absent upstream and is represented as an optional absent
  capability; atom matching uses exact upstream names plus existing explicit PDB
  aliases.
- `aminoacids.r2b` is present. It defines standard N/C terminal blocks, AMBER
  protonation variants, `HYP` as an internal block, and `CHYP` as the supported
  C-terminal hydroxyproline block. It provides no N-terminal HYP block.
- `aminoacids.n.tdb` and `aminoacids.c.tdb` are present but empty. Amber19SB
  terminal chemistry is encoded in RTP/R2B blocks rather than TDB patches.
- `ACE` and `NME` are explicit RTP residues and supported only in their cap
  positions.
- `cmap.itp` is required by `forcefield.itp`, and `aminoacids.rtp` contains
  per-residue `[ cmap ]` records. Both parameter and molecule-term emission are
  enabled by the capability descriptor.

## Water And Ion Audit

`watermodels.dat` and the same-name upstream water/ion files establish exactly
six supported pairs. No AMBER99 ion substitution table is used:

| Water | Water topology | Ion topology |
|---|---|---|
| `opc` | `opc.itp` | `ions_opc.itp` |
| `opc3` | `opc3.itp` | `ions_opc3.itp` |
| `spc` | `spc.itp` | `ions_spc.itp` |
| `spce` | `spce.itp` | `ions_spce.itp` |
| `tip3p` | `tip3p.itp` | `ions_tip3p.itp` |
| `tip4pew` | `tip4pew.itp` | `ions_tip4pew.itp` |

Every other cross-pair is rejected before output. `tip4p` has no upstream
Amber19SB pair and is rejected.

## License And Notices

The official GROMACS README identifies the distribution as GNU Lesser General
Public License version 2.1 and states that it can be redistributed freely. The
bundle is distributed verbatim, with source identity, full hashes, attribution,
and the upstream LGPL text in
`THIRD_PARTY_NOTICES/GROMACS-LGPL-2.1.txt`. The force-field-specific
`forcefield.doc` notice and citation text remain in the bundled directory.
This satisfies the repository's redistribution policy for unmodified upstream
data; downstream distributors must preserve the notice and LGPL terms.

## External Acceptance

The initial implementation environment had no compatible `gmx`, so its six
external cases skipped. On 2026-10-20 all six cases passed with GROMACS **2026.0**
on Apple arm64 (mixed precision, CPU build):

```bash
micromamba run -n dvbfixer python -B -m pytest tests/test_top_amber19sb.py -k grompp_external_acceptance -v
```

Each case generates the self-contained `ffparams.itp`, `water.itp`, `ions.itp`,
chain ITP and topology for its selected pair. `gmx editconf` puts the peptide in
a 4 × 4 × 4 nm box; `gmx grompp -maxwarn 0` preprocesses it with `pbc=xyz`,
Verlet cutoffs and `nsteps=0`. This corrects the original test's incompatible
`pbc=no`/Verlet setup without changing force-field assets or allowing warnings.

This is peptide topology/include preprocessing acceptance for all six pair
selections, not a solvated water/ion simulation, an MD trajectory, or validation
of mixed chemistry. Full baseline-repair evidence is recorded
[separately](../research/baseline-repair-2026-10-20.md).
