"""Lightweight regression checks for user documentation validation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_user_docs", ROOT / "scripts/check_user_docs.py")
assert SPEC is not None and SPEC.loader is not None
docs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(docs)


def test_anchors_ignore_fences_and_handle_duplicate_unicode_headings() -> None:
    assert docs.heading_anchors(
        "# Title\n\n## `--ff` choices: Cα → Å\n\n## Repeat\n\n## Repeat\n\n"
        "```text\n## Not a heading\n```\n\n<a id=\"old-anchor\"></a>\n"
    ) == {"title", "--ff-choices-cα--å", "repeat", "repeat-1", "old-anchor"}


def test_links_fragments_and_json(tmp_path: Path) -> None:
    (tmp_path / "other page.md").write_text("# Other\n\n## `--ff`\n", encoding="utf-8")
    (tmp_path / "page.md").write_text(
        '# Page\n\n[link](other%20page.md#--ff)\n\n```json\n{"ok": true}\n```\n',
        encoding="utf-8",
    )
    assert docs.check_page(tmp_path, Path("page.md")) == []
    (tmp_path / "page.md").write_text(
        '# Page\n\n[link](other%20page.md#absent)\n\n```json\n{...}\n```\n',
        encoding="utf-8",
    )
    errors = docs.check_page(tmp_path, Path("page.md"))
    assert any("missing heading anchor" in error for error in errors)
    assert any("invalid JSON" in error for error in errors)


def test_fences_tables_and_missing_reference(tmp_path: Path) -> None:
    (tmp_path / "page.md").write_text(
        "# Page\n\n| Option | Use |\n|---|---|\n| `a\\|b` | x |\n"
        "| a | b | c |\n\n[missing][ref]\n\n```text\n# not H1\n",
        encoding="utf-8",
    )
    errors = docs.check_page(tmp_path, Path("page.md"))
    assert any("unclosed code fence" in error for error in errors)
    assert any("table has 3 cells" in error for error in errors)
    assert any("undefined reference" in error for error in errors)
    assert not any("H1" in error for error in errors)


def test_reference_links_and_duplicate_anchor_collisions(tmp_path: Path) -> None:
    assert docs.heading_anchors("# Foo\n\n## Foo\n\n## Foo-1\n") == {"foo", "foo-1", "foo-1-1"}
    (tmp_path / "page.md").write_text(
        "# Page\n\n[Go][local]\n\n[local]: #page\n\n[remote](https://example.com/a_(b))\n",
        encoding="utf-8",
    )
    assert docs.check_page(tmp_path, Path("page.md")) == []


def test_table_pipes_inside_code_still_need_escaping() -> None:
    assert len(docs.table_cells('| `a|b` | x |')) == 3
    assert len(docs.table_cells(r'| `a\|b` | x |')) == 2
    assert len(docs.table_cells('| a ||')) == 2


def test_inline_code_is_not_a_link_and_heading_levels_are_checked(tmp_path: Path) -> None:
    (tmp_path / "page.md").write_text(
        "# Page\n\n`[not a link](missing.md)` and `[linkage][sugar]`.\n\n### Skipped\n",
        encoding="utf-8",
    )
    errors = docs.check_page(tmp_path, Path("page.md"))
    assert len(errors) == 1
    assert "heading level skipped" in errors[0]


def test_maintained_user_documentation() -> None:
    assert docs.main() == 0


def test_every_registered_command_has_a_consistent_user_entry() -> None:
    # Import metadata only, never the scientific command parsers in this lane.
    from dvbfixer.command_registry import COMMAND_REGISTRY

    index = (ROOT / "docs/commands/index.md").read_text()
    for command in COMMAND_REGISTRY:
        path = ROOT / f"docs/commands/{command.name}.md"
        text = path.read_text()
        assert text.startswith(f"# `dvbfixer {command.name}`\n"), path
        assert "[User guide](../README.md)" in text, path
        assert f"[CLI reference](../reference/{command.name}.md)" in text, path
        assert "## Quick start" in "\n".join(text.splitlines()[:40]), path
        assert f"]({command.name}.md)" in index, path
