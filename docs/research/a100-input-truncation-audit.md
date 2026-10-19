# A100 input-chain truncation audit

The [intact-input recheck](intact-input-recheck.md) is now complete with preserved
observed protein chains/segments and explicit unsupported-source reporting.

## Finding

Manual inspection correctly identified incomplete chains in the exported
`01_before_gap.pdb` files. **The experimental materializer deliberately removed
observed parts of chains before creating the artificial gap.** This was not an
additional chain-parsing loss at CIF normalization or visual export.

`scripts/materialize_cuda_fragment_calibration.py` calls `complete_runs()` and
then retains only:

1. The longest heavy-atom-complete, C–N-contiguous run of the target chain,
   capped at 250 residues.
2. One nearest qualifying run from one other chain, capped at 120 residues.

Every other run and every other chain is excluded. A missing **side-chain** heavy
atom or noncanonical residue can split a run even when its backbone is observed.
An unrelated native coordinate gap can therefore cause a whole otherwise
observed domain/segment to disappear. For a partner, proximity can favor a short
run over a longer run from the same chain.

This policy was introduced after complete-chain screening yielded few eligible
inputs. Although manifests documented fragment/subcomplex scope, that scope is
inadequate for evaluating preservation of the complete deposited structural
context. Describing the experiments as preserving the source environment without
emphasizing this preprocessing was too broad: the invariance checks covered
**only the already-truncated experimental input**.

## Exact cases reported during visual review

Counts below refer to observed amino-acid residues in model 1 of the deposited
CIF, not to missing-coordinate SEQRES positions. Chain IDs are case-sensitive.

| Entry / chain | Observed in deposited CIF | Retained before artificial gap | Cause |
|---|---:|---|---|
| 29HO / D | 114, 2055–2168 | 111, 2058–2168 | LYS2057 lacks CG/CD/CE/NZ; only the longer complete run was retained |
| 29HO / V | 155, 59–213 | 120, 78–197 | CAS77 splits the canonical-only run; the retained 78–213 run is then capped to 120 residues |
| 23IT / 1 | 173, 1–133 and 158–197 | 133, 1–133 | Native gap: C133–N158 is 6.699 Å; the second observed part is discarded |
| 23IT / 4 | 46, 15–39 and 64–84 | 21, 64–84 | Native gap: C39–N64 is 14.089 Å; only the nearer partner component is retained |
| 21TW / B | 139, 10–102 and 112–157 | 93, 10–102 | Native gap: C102–N112 is 15.534 Å; the second observed part is discarded |
| 21TW / D | 138, 11–101 and 111–157 | 47, 111–157 | Native gap: C101–N111 is 13.463 Å; only the nearer component is retained |
| 13EE / A | 148, 40–138 and 141–189 | 99, 40–138 | Native gap: C138–N141 is 3.930 Å; the second observed part is discarded |
| 13EE / B | 154, 40–193 | 120, 40–159 | Complete continuous chain cropped solely by the partner-length cap |

Additionally, 29HO chains B/C, 23IT chains 2/3/H/L, and 21TW chains A/C were
excluded entirely. This is distinct from the subsequently removed test gap.
The problem is not confined to the four reported entries: for example, 25II's
1,254-residue partner chain A was reduced to 120 residues.

## Verification and preserved evidence

`scripts/audit_gap_chain_coverage.py` replays the exact frozen selection for all
ten exported entries, verifies deposited/derived source digests, matches the
archived `selected-protein-fragments.cif`, checks that normalization/reference
extraction retains every selected residue, and reproduces all 79 before-gap
PDB files byte-for-byte. No structural files or frozen inference results are
rewritten.

Human-readable per-protein reports and the machine-readable coverage inventory
are in the project-root visual-review folder:

- `gap_visual_review/chain_coverage.md`
- `gap_visual_review/chain_coverage.json`
- `gap_visual_review/<protein>/chain_coverage.md`

The review README explicitly flags pre-gap truncation, and checksums include the
additional coverage reports. Future exports produce the same coverage audit.

## Consequence for the next dataset revision

The reported pass/fail numbers remain reproducible **fragment experiments**;
they do not establish full-context reconstruction quality. Omitted context may
affect closure, packing and generated conformation. This audit establishes the
omission, not its quantitative causal contribution to each failure.

A revised full-context cohort must retain all observed residues of the declared
chains/complex before deleting only the specified test gap. Native missing
coordinates and incomplete side chains must be recorded separately, handled by
an explicit preparation policy, or cause a source to be rejected. They must not
silently remove the remainder of a chain. Inputs exceeding the engine's context
budget should be excluded or explicitly designated cropped-context experiments,
rather than being presented as intact-chain tests. Existing archived PDBs must
not be patched to look like full-context runs that were never performed.
