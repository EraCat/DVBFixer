# User documentation refresh

## Scope

Reorganize the existing English user manual around tasks, without changing
scientific behavior or hand-editing generated CLI references. Keep existing
page paths and useful heading anchors wherever possible.

## Work plan

- [x] Add `docs/README.md`, `docs/quick-start.md`, and `docs/gui.md`.
- [x] Simplify the root README and installation entry path.
- [x] Make pipelines the canonical recipe collection; reduce BEST_PRACTICES to navigation.
- [x] Normalize command introductions, navigation, examples, and reference links.
- [x] Separate user troubleshooting from development/research details.
- [x] Add a documentation style guide and automated Markdown/link checks.
- [x] Validate rendered structure, examples, generated references, and agent maps.

Additional files: `docs/known-issues-history.md` preserves the old investigation
notes; `docs/maintenance/documentation-style.md` documents the maintenance policy.
The checker and its regression tests are `scripts/check_user_docs.py` and
`tests/test_user_docs.py`; the lightweight CI lane runs both.

## Link tracking

All planned pages exist. The link checker validates local paths and Markdown
heading anchors across maintained user documentation. There are no pending local
links. Existing technical/research documents are preserved, not rewritten as
part of this pass. Existing inbound links to changed user-page anchors were
also checked across tracked Markdown files; no missing anchors were found.

## Acceptance

- Installation and first-run instructions do not require architecture/research reading.
- Recipes use connected filenames and identify optional steps separately.
- Command pages start with purpose and a usable example before advanced details.
- User documentation has consistent navigation and passes automated checks.
- CLI references remain generated and synchronized with argparse.

## Verification results

- User Markdown/link/anchor/JSON checks: 38 pages passed.
- Focused documentation, agent-map, and environment tests: 13 passed.
- Ruff on production Python plus the new checker/tests: passed.
- CLI reference and GUI schema `--check`: passed; generated files unchanged.
- Long-option spellings in 220 documented shell invocations checked against the
  generated CLI references: passed (static verification, not execution).
- Release metadata and agent maps: passed.
- CommonMark + GFM-table rendering: 38 pages, 62 tables, 139 fenced blocks;
  HTML previews generated in private temporary storage. This is a parser/render
  check, not a browser screenshot or narrow-window visual acceptance.
- Scientific example smoke on tracked ubiquitin `1UBQ.pdb`: prepare → minimize
  with matching `.dat` and `--no-solvent` → diagnose → native AMBER naming all
  returned 0 and produced their expected artifacts. No fixture inputs changed.
- Complete recipe coverage is not claimed: glycoprotein, topology export,
  external-builder, and experimental runner recipes were not all executed.
- Fast Python suite: 1,342 passed, 2 optional skips, 31 slow tests deselected.
  The final documentation contract test was also included in the subsequent
  focused run reported above.

## Quality report

The user entry path is now installation → quick start → task recipes/GUI.
All 24 command guides have a consistent title, navigation, reference link, and
quick-start section near the top, enforced by a metadata-only regression test.
The recipes distinguish optional re-protonation from required preparation,
use explicit connected filenames, and explain vacuum-minimization scope.
Known issues are symptom-based; resolved implementation investigations are
archived separately. Shared batch/logging/numbering behavior has one guide.
No scientific behavior, dependencies, generated references, or release version
were changed.
