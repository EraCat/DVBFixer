#!/usr/bin/env python3
"""Export the full provisioned core/backend package closure into private evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

SNAPSHOT_CODE = """
import importlib.metadata as metadata
import json, platform, sys
names = sorted({d.metadata['Name'] for d in metadata.distributions() if d.metadata['Name']})
print(json.dumps({
    'python': platform.python_version(), 'platform': sys.platform,
    'prefix': sys.prefix, 'base_prefix': sys.base_prefix,
    'packages': {name: metadata.version(name) for name in names},
}, sort_keys=True))
"""


def export_environment(core: Path, backend: Path, output: Path, micromamba: Path) -> dict:
    if output.exists():
        raise FileExistsError("environment export directory must be new")
    snapshots = {}
    payloads = {}
    for role, python in (("core", core), ("backend", backend)):
        snapshot = json.loads(subprocess.check_output([str(python), "-c", SNAPSHOT_CODE], text=True))
        snapshots[role] = snapshot
        payloads[f"{role}-packages.json"] = (json.dumps(snapshot, sort_keys=True, indent=2) + "\n").encode()
        payloads[f"{role}-pip-freeze.txt"] = subprocess.check_output([
            str(python), "-m", "pip", "freeze", "--all",
        ])
    payloads["core-conda-explicit.txt"] = subprocess.check_output([
        str(micromamba), "list", "--explicit", "-p", snapshots["core"]["prefix"],
    ])
    output.mkdir(parents=True)
    for name, payload in payloads.items():
        (output / name).write_bytes(payload)
    manifest = {
        "schema_version": 1,
        "scope": "private-full-package-export-not-an-OCI-image",
        "python": {role: snapshot["python"] for role, snapshot in snapshots.items()},
        "package_counts": {role: len(snapshot["packages"]) for role, snapshot in snapshots.items()},
        "backend_inherits_core": snapshots["backend"]["base_prefix"] == snapshots["core"]["prefix"],
        "artifacts": {
            name: {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
            for name, payload in sorted(payloads.items())
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-python", required=True, type=Path)
    parser.add_argument("--backend-python", required=True, type=Path)
    parser.add_argument("--micromamba", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = export_environment(args.core_python, args.backend_python, args.output, args.micromamba)
    print(json.dumps(manifest, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
