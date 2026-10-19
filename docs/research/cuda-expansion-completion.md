# CUDA expansion completion audit — 2026-10-19

Scope: long-gap strata, surrounding-protein context, and mosaic-first Homology.
Apple MPS follow-up is deferred until CUDA implementation is complete; it is not
a gate for this CUDA work. MODELLER remains the default. Scientific publication
gates are unchanged.

## Delivered software

- CLI request construction, authoritative mosaic construction, and scope admission
  now use one profile-specific gap capability policy. The accepted-range registry
  is immutable and an expansion for one profile cannot leak to another. The
  public baseline remains 3–12; research capacity is 13–25 and 26–50.
- Adaptive expansion revalidates the previous source-derived context before
  constructing a successor. Sampled query extraction rejects invalid encoding,
  truncated identities, multiple models, altlocs, wrong target residue names,
  duplicates, missing backbone atoms, and non-finite coordinates. Contact-gated
  routing does not claim expansion when the declared policy permits no new atoms.
- Homology validates the complete request before writing its normalized input.
  Invalid seeds, merged unsupported windows, and invalid edit-flank values fail
  without leaving a candidate input PDB. Regression coverage exercises deletion
  flanks 1–5, exact generated intervals, and preservation of every outside-mosaic
  atom. The explicit flank choice is retained; there is no outcome-guided retry.

Existing implementations, retained and verified here, include Protenix joint
sampling, private cc89 joint/discontiguous engine views with inverse source
mapping, between-round adaptive expansion, multiple Homology spans/templates,
bounded covered substitutions/deletions, and CLI/GUI edit-flank forwarding.

## Full-input long-gap accuracy audit

`scripts/audit_clean_reconstruction_accuracy.py` reopens every immutable archive
of the 50-case/11-source clean full-input cohort, checks protocol/inventory
digests, independently reruns validation, and measures withheld-reference
accuracy for both raw and refined candidates. No sampling or candidate selection
uses the reference. Rejections remain in accuracy summaries; missing results have
their own denominator. Multiple masks of one source are not counted as
independent structures.

| Length | Refined geometry PASS | Median backbone RMSD, all candidates (Å) | Maximum RMSD, geometry-passing candidates (Å) |
|---|---:|---:|---:|
| 5 | 11/11 | 0.21887 | 0.69637 |
| 13 | 9/10 | 0.37236 | 1.68741 |
| 25 | 10/10 | 1.53254 | 3.34304 |
| 26 | 10/10 | 0.56343 | 0.73280 |
| 50 | 9/9 | 0.82568 | 8.69575 |

All 50 raw and 50 refined results are available. Five native-quality exclusions
remain in the original 55-mask source-screening record. Geometry acceptance is
26/50 raw and 49/50 refined, but `9m9n-gap50-seed7` passes geometry at 8.69575 Å
backbone RMSD. Of the 49 accepted refined candidates, 38 are at most 1 Å, eight
are in (1,2] Å, two in (2,4] Å, and one exceeds 4 Å. These bins are descriptive,
not new acceptance thresholds.

Report: [`clean-protein-expanded-accuracy.json`](clean-protein-expanded-accuracy.json).
SHA-256: `f338ee08b87d5819e88bdb89c3664d563daa4d574a43eaa1bf6389fa84b6a77a`.
This is a **post-hoc** accuracy audit, not a prospective noninferiority study.
The results do not close long-gap scientific promotion; a prospective paired
MODELLER comparison and independent review remain outstanding.

## Rich cc89 CUDA refinement

The six previously frozen joint/discontiguous/insertion-code native/projection
outputs were all subjected to the unchanged generated-only rigid v6 CUDA
refinement. Raw inference was not repeated. The protocol was frozen before this
refinement and all failures were retained.

| Case | Native 500 | Projection 500 |
|---|---|---|
| Joint 1EMV | rejected | rejected |
| Discontiguous 1EMV | guarded chirality exception, no refined output | rejected |
| Insertion-coded 7K8S | guarded chirality exception, no refined output | rejected |

Result: **0/6 accepted**, four evaluated failures and two worker errors caused by
the final `assert_all_l` guard. For the four evaluated outputs, failed gates
include peptide closure, backbone continuity, bond/angle/amide geometry, and
severe clashes. The two exceptional paths preserve raw artifacts and diagnostics
and emit no refined coordinate artifact. Successful atom mapping, causal
conditioning, and fixed-coordinate projection do not imply acceptable generation.
Local minimization does not rescue this rich cc89 configuration.

Producer: `scripts/refine_cuda_context_frontiers.py`.
Frozen protocol: [`cc89-rich-cuda-refinement-protocol.json`](cc89-rich-cuda-refinement-protocol.json),
SHA-256 `3fa308817a30cfa56c0d5c7ca36e8fb08d666c327ca234bd627e5475377e6bfb`.
Archive: `.artifacts/cc89-rich-cuda-refinement/`.
Analysis SHA-256: `e2d6c0bf44d67400b0e0f00b6e7b5dcf1f4965128e4ac71ac3628a722a7f8758`.
The producer's `run_a100_relaxation` import was wrapped onto multiple lines for
lint after execution; the frozen protocol retains the original producer hash.
No scientific code or captured outcome was revised by that formatting change.

## Homology acceptance boundary

The previous real CUDA deletion-window study already passed flanks 3, 4, and 5
(windows 7, 9, and 11); flanks 1 and 2 failed. Its independent public CLI run with
three flanks is archived as described in
[`reconstruction-frontiers.md`](reconstruction-frontiers.md#4-deletion-edit-windows).
This resolves the earlier single narrow-window demonstration, not all deletion
classes. The existing five-plan study also covers joint logical VH/VL mapping,
multiple spans, covered substitution, and fitted multiple templates.

Broad antibody H/L/CDR and interface acceptance, leakage control, prospective
bounded-edit validation, and independent scientific review remain open. The
engineering VH/VL test on 1EMV is not an antibody benchmark. The preceding
software fixes and negative cc89 results are not a basis to mark those gates done.

## Reproduction

Use the repository source on `PYTHONPATH`; the host's editable installation may
refer to an older worktree. Put the scientific environment's `bin` on `PATH` for
tests which spawn `dvbfixer`.

```bash
python scripts/audit_clean_reconstruction_accuracy.py \
  --manifest docs/research/clean-protein-expanded-cohort-v2.json \
  --protocol docs/research/clean-protein-expanded-run-protocol-v2.json \
  --outcomes .artifacts/clean-protein-expanded-results-v2 \
  --output NEW_accuracy_audit.json
```

For a new cc89 refinement replay, freeze a **new** protocol and output namespace
in the isolated CUDA-12.2 OpenMM environment using
`scripts/refine_cuda_context_frontiers.py freeze` / `run`. Existing outcomes must
not be replaced or silently attached to another producer/environment.

## Software verification

- Full non-slow Python suite: **1,149 passed, 7 skipped**, 31 slow tests
  deselected. Skips are the optional Biotite check and six GROMACS executable
  acceptance cases.
- GUI: typecheck passed; **243 tests passed**.
- Ruff passed for `src/dvbfixer`, the two new audit/refinement scripts, and
  their new standalone test modules.
- Strict core plus changed diffusion/Homology mypy targets passed (17 files).
- Agent maps, version synchronization, generated GUI spec, and `git diff --check`
  passed. CLI reference validation passed with Python 3.12; Python 3.13 changes
  argparse formatting and reports unrelated help-format drift.

The first broad pytest invocation omitted the environment's `bin` from `PATH`;
six executable-spawning tests failed with `dvbfixer` not found. They passed after
correcting `PATH`, followed by the complete successful suite above. No scientific
threshold or implementation was changed to address that environment error.
