#!/usr/bin/env python
"""Check maintained user Markdown without importing the scientific stack.

This deliberately checks our documented Markdown subset, not arbitrary GFM:
ATX headings, fenced examples, pipe tables, inline/reference links and explicit
HTML anchors. Remote URLs are not fetched. Generated references are link targets
only; research, historical notes, API and deployment manuals are outside scope.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PAGES = (
    "README.md", "BEST_PRACTICES.md", "gui/README.md", "docs/README.md",
    "docs/quick-start.md", "docs/installation.md", "docs/pipelines.md",
    "docs/gui.md", "docs/gui-homology.md", "docs/known-issues.md",
    "docs/force-fields.md", "docs/cif-input.md", "docs/batch-mode.md",
)
HEADING = re.compile(r"^(#{1,6}) (.+?)(?: +#+)?$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
DESTINATION = r"(?:[^\s()]|\([^()]*\))+"
INLINE_LINK = re.compile(r"!?\[[^\]\n]*\]\(<?(" + DESTINATION + r")>?(?:\s+[^)]*)?\)")
REFERENCE = re.compile(r"^ {0,3}\[([^]]+)\]:\s*<?(\S+?)>?(?:\s+[\"'].*)?$")


def prose_lines(text: str) -> list[tuple[int, str]]:
    """Return non-fenced lines, retaining their source line numbers."""
    result = []
    marker = ""
    for number, line in enumerate(text.splitlines(), 1):
        fence = FENCE.match(line)
        if fence:
            token, rest = fence.groups()
            if not marker:
                marker = token
            elif token[0] == marker[0] and len(token) >= len(marker) and not rest.strip():
                marker = ""
            continue
        if not marker:
            result.append((number, line))
    return result


def heading_anchors(text: str) -> set[str]:
    anchors: set[str] = set()
    for _, line in prose_lines(text):
        for explicit in re.finditer(r'<a\s+(?:id|name)=["\']([^"\']+)["\']', line):
            anchors.add(explicit[1])
        match = HEADING.match(line)
        if not match:
            continue
        title = re.sub(r"!?\[([^]]+)\]\([^)]+\)", r"\1", match[2])
        title = re.sub(r"<[^>]*>", "", title).lower()
        slug = "".join(
            char for char in title
            if char in "-_ " or unicodedata.category(char)[0] in "LN"
        ).replace(" ", "-")
        candidate, suffix = slug, 0
        while candidate in anchors:
            suffix += 1
            candidate = f"{slug}-{suffix}"
        anchors.add(candidate)
    return anchors


def table_cells(line: str) -> list[str]:
    # GFM splits table cells before parsing inline code. Even a pipe inside
    # backticks must be escaped, otherwise a renderer silently truncates cells.
    line = line.replace(r"\|", "escaped-pipe").strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return line.split("|")


def check_page(root: Path, relative: Path) -> list[str]:
    path = root / relative
    if not path.is_file():
        return [f"{relative}: missing page"]
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []

    def error(number: int, message: str) -> None:
        errors.append(f"{relative}:{number}: {message}")

    lines = text.splitlines()
    if not text.endswith("\n"):
        error(len(lines), "missing final newline")
    prose = prose_lines(text)
    headings = [(n, HEADING.match(line)) for n, line in prose if HEADING.match(line)]
    if not lines or not lines[0].startswith("# "):
        error(1, "start with one H1 title")
    if sum(bool(match and len(match[1]) == 1) for _, match in headings) != 1:
        error(1, "expected exactly one H1 title")
    for number, match in headings:
        assert match is not None
        if number > 1 and lines[number - 2].strip():
            error(number, "blank line required before heading")
        if number < len(lines) and lines[number].strip():
            error(number, "blank line required after heading")

    previous_level = 0
    for number, match in headings:
        assert match is not None
        level = len(match[1])
        if level > previous_level + 1:
            error(number, "heading level skipped")
        previous_level = level

    marker, language, opened = "", "", 0
    block: list[str] = []
    for number, line in enumerate(lines, 1):
        if line.rstrip() != line or "\t" in line:
            error(number, "trailing whitespace or tab")
        fence = FENCE.match(line)
        if fence:
            token, rest = fence.groups()
            if not marker:
                marker, language, opened = token, rest.strip(), number
                block = []
                if not language:
                    error(number, "code fence needs a language (use text for fragments)")
            elif token[0] == marker[0] and len(token) >= len(marker) and not rest.strip():
                if language == "json":
                    try:
                        json.loads("\n".join(block))
                    except json.JSONDecodeError as exc:
                        error(opened, f"invalid JSON example: {exc.msg}; use text for fragments")
                marker = ""
            continue
        if marker:
            block.append(line)
    if marker:
        error(opened, "unclosed code fence")

    width = 0
    for number, line in prose:
        if line.startswith("|") and line.endswith("|"):
            cells = table_cells(line)
            if width and len(cells) != width:
                error(number, f"table has {len(cells)} cells; expected {width}")
            width = len(cells)
        else:
            width = 0

    references = {
        match[1].casefold(): match[2]
        for _, line in prose if (match := REFERENCE.match(line))
    }
    for number, line in prose:
        # Ignore bracket-like notation inside inline code, such as
        # `[linkage][sugar][anomer]`, when recognizing reference-style links.
        reference_line = re.sub(r"(`+).*?\1", "code", line)
        links = [match[1].removesuffix(">") for match in INLINE_LINK.finditer(reference_line)]
        definition = REFERENCE.match(line)
        if definition:
            links.append(definition[2])
        for match in re.finditer(r"\[([^]]+)\]\[([^]]*)\]", reference_line):
            key = (match[2] or match[1]).casefold()
            if key not in references:
                error(number, f"undefined reference link {key!r}")
            else:
                links.append(references[key])
        for link in links:
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                continue
            target = path.parent / unquote(parsed.path) if parsed.path else path
            if not target.exists():
                error(number, f"missing local target: {link}")
            elif parsed.fragment and target.suffix.lower() == ".md":
                anchors = heading_anchors(target.read_text(encoding="utf-8"))
                if unquote(parsed.fragment) not in anchors:
                    error(number, f"missing heading anchor: {link}")
    return errors


def main() -> int:
    pages = [Path(page) for page in PAGES]
    pages.extend(path.relative_to(ROOT) for path in sorted((ROOT / "docs/commands").glob("*.md")))
    errors = [error for page in pages for error in check_page(ROOT, page)]
    if errors:
        print("\n".join(errors))
        return 1
    print(f"User documentation checks passed ({len(pages)} pages; local links, anchors, Markdown, JSON).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
