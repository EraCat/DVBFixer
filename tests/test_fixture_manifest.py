"""Integrity checks for the tracked structural fixture set."""

from __future__ import annotations

import hashlib
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parent.parent
# Source-selection/provenance metadata is part of the portable input inventory,
# unlike generated JSON reports. Keep this allowlist explicit.
FIXTURE_METADATA = {FIXTURES / "cc89_apple_handoff" / "manifest.json"}


def test_fixture_manifest_is_complete_and_matches_checksums() -> None:
    manifest = FIXTURES / "MANIFEST.sha256"
    entries = []
    for line in manifest.read_text().splitlines():
        expected, relative = line.split("  ", 1)
        path = REPO_ROOT / relative
        assert path.is_file(), f"tracked fixture missing: {relative}"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected, f"fixture checksum mismatch: {relative}"
        entries.append(path.resolve())

    fixture_inputs = {
        path.resolve() for path in FIXTURES.rglob("*")
        if path.is_file() and path.suffix.lower() in {".pdb", ".fasta"}
    }
    assert len(entries) == len(set(entries)), "fixture manifest repeats an input"
    expected_inputs = fixture_inputs | {path.resolve() for path in FIXTURE_METADATA}
    assert set(entries) == expected_inputs, "fixture manifest has missing or stale entries"
