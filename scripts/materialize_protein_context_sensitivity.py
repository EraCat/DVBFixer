#!/usr/bin/env python3
"""Freeze the already-declared shell/budget policies on all base expansion cases."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-manifest", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    if args.manifest.exists():
        raise ValueError("sensitivity manifest must be new")
    parent = json.loads(args.parent_manifest.read_text())
    cases = [case for case in parent["cases"] if not case["case_id"].endswith(("-seed19", "-distant"))]
    for case in cases:
        case["arms"] = ["direct-shell", "budget-64"]
    manifest = {**parent, "cases": cases, "arms": ["direct-shell", "budget-64"],
                "scope": "descriptive-shell-budget-sensitivity-not-production-promotion",
                "parent_manifest_sha256": hashlib.sha256(args.parent_manifest.read_bytes()).hexdigest(),
                "preregistration_note": "Derived after expansion execution began, before any sensitivity-arm inference; policies and masks already frozen in parent. No thresholds changed."}
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(args.manifest)


if __name__ == "__main__":
    main()
