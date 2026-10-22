# User documentation style

The public manual starts at [docs/README.md](../README.md). Keep instructions
task-oriented and English, matching the program's option and control labels.
Architecture, research, deployment, and agent contracts serve different readers;
link to them for advanced details rather than inserting them into a first run.

## Page structure

- One H1; command pages use ``# `dvbfixer command` ``.
- Navigation directly below the title: user guide, relevant index, reference.
- Explain purpose and when to choose another tool.
- Put a working minimal example before advanced implementation details.
- Identify required input, resulting files, dependencies, and limitations.
- Separate optional paths from the main runnable sequence.
- End with related tasks; preserve existing paths/anchors where practical.

Command guides explain decisions and common scenarios. Exact flags/defaults are
generated in `docs/reference/`; do not maintain another exhaustive option catalog.
Update generated pages through `scripts/gen_cli_reference.py`, never by hand.

## Examples and formatting

- Use fenced `bash`, `json`, `python`, or `text` blocks; no shell prompt prefixes.
- Keep explanations outside copied commands. Use explicit outputs in pipelines
  so the next command consumes a file actually produced by the preceding one.
- Label placeholders before the block. Mark JSON fragments as `text`; `json`
  fences must parse. Do not present a partial FASTA as a real complete sequence.
- Use `--no-solvent` in short minimize/ZBS examples and explain the vacuum scope.
- Avoid version-history paragraphs in user introductions and unsupported claims
  such as "arbitrary ligand", "higher quality", or "MD ready" without evidence.
- Keep tables short and decision-oriented. Escape literal pipes outside code
  spans. Leave blank lines around headings and between paragraphs and lists.
- Use short paragraphs, sentence-case section headings for new sections, and
  consistent labels. Keep legacy linked headings when renaming would break anchors.
  Do not add decorative emoji or rely on color to communicate warnings.
- Distinguish naming, protonation, reconstruction, parameterization, and relaxation.

## Validation

From the repository root:

```bash
python scripts/check_user_docs.py
pytest tests/test_user_docs.py -q
python scripts/gen_cli_reference.py --check
python scripts/gen_gui_spec.py --check
python scripts/check_agent_docs.py
```

The lightweight checker covers root entry points, the GUI README, selected shared
user guides, and every command guide. It validates local paths, heading fragments,
fences, heading spacing, table cell counts, whitespace, and JSON examples. It does
not fetch remote URLs, execute examples, or replace visual GitHub rendering review.
Generated CLI references are checked as link targets, not reformatted. Historical,
research, API, and deployment pages are outside this style migration's scope.

Before finishing, inspect rendered heading hierarchy, tables, nested lists and
code fences, including narrow windows. Smoke-test representative documented CLI
examples using tracked fixtures; do not claim all scientific recipes ran unless
they actually did.
