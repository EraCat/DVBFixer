"""Digest-verified bundle consumption shared by batch and preparation workflows."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dvbfixer.ffutils.dat import DatRecord
from dvbfixer.model.diffusion.contract import (
    MAX_TRACE_BYTES,
    ArtifactReference,
    BackendProvenance,
    DiffusionRequest,
    RunnerResult,
    SamplerTrace,
)
from dvbfixer.model.diffusion.pipeline import DiffusionPipelineError, _read_contained_artifact
from dvbfixer.model.diffusion.runner import DiffusionRunnerError, _open_regular_file
from dvbfixer.model.diffusion.trace import validate_sampler_trace_context


class PublicationError(ValueError):
    """A published bundle is incomplete, incompatible, or not validated."""


@dataclass(frozen=True)
class PublishedCandidate:
    candidate_id: str
    seed: int
    pdb: Path
    dat: Path
    pdb_bytes: bytes
    dat_record: DatRecord


@dataclass(frozen=True)
class PublishedBundle:
    status: str
    candidates: tuple[PublishedCandidate, ...]

    def selected(self) -> PublishedCandidate:
        if self.status != "success":
            raise PublicationError("diffusion bundle has no independently validated candidate")
        return self.candidates[0]


def read_published_bundle(
    bundle: Path, *, request: DiffusionRequest | None = None,
    source_root: Path | None = None, work_parent: Path | None = None,
) -> PublishedBundle:
    """Verify every linked artifact and optionally the exact request for resume."""
    try:
        return _read_published_bundle(bundle, request=request, source_root=source_root, work_parent=work_parent)
    except (ValueError, KeyError, TypeError, OSError, DiffusionPipelineError, DiffusionRunnerError) as exc:
        raise PublicationError(f"invalid diffusion publication: {exc}") from exc


def _read_published_bundle(
    bundle: Path, *, request: DiffusionRequest | None,
    source_root: Path | None, work_parent: Path | None,
) -> PublishedBundle:
    if bundle.is_symlink() or not bundle.is_dir():
        raise PublicationError("diffusion bundle must be a directory, not a symlink")
    root = bundle.resolve()
    descriptor = _open_regular_file(root / "bundle.json", label="bundle index", max_bytes=10_000_000)
    with os.fdopen(descriptor, "rb") as stream:
        index = json.loads(stream.read(10_000_001))
    if not isinstance(index, dict) or index.get("schema_version") != 2 or index.get("status") not in {"success", "validation_failed"}:
        raise PublicationError("unsupported diffusion bundle index")
    rows = index.get("candidates")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise PublicationError("diffusion bundle must contain bounded candidates")
    expected_digest = hashlib.sha256(request.to_json().encode()).hexdigest() if request else None
    candidates = []
    identifiers = set()
    seeds = set()
    artifact_paths = set()
    for row in rows:
        if not isinstance(row, dict):
            raise PublicationError("diffusion candidate must be an object")
        identity, seed = row["candidate_id"], row["seed"]
        if not isinstance(identity, str) or not identity or not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            raise PublicationError("invalid diffusion candidate identity or seed")
        if identity in identifiers or seed in seeds:
            raise PublicationError("diffusion bundle repeats candidate identities or seeds")
        identifiers.add(identity)
        seeds.add(seed)
        payloads = {}
        for label in ("pdb", "dat", "provenance", "sampler_trace"):
            reference = ArtifactReference(**row[label])
            if reference.path in artifact_paths:
                raise PublicationError("diffusion bundle repeats artifact paths")
            artifact_paths.add(reference.path)
            maximum = MAX_TRACE_BYTES if label == "sampler_trace" else 1_000_000_000
            payloads[label] = _read_contained_artifact(root, reference, max_bytes=maximum)
        provenance = json.loads(payloads["provenance"])
        summary = provenance["validation_summary"]
        passed = index["status"] == "success"
        if (
            row["validation_passed"] is not passed or summary["passed"] is not passed
            or row["hard_gate_failures"] != summary["hard_gate_failures"]
            or bool(row["hard_gate_failures"]) == passed
            or provenance["candidate"]["candidate_id"] != identity
            or provenance["candidate"]["seed"] != seed
            or provenance["candidate"]["coordinate_artifact"] != row["pdb"]
            or provenance["candidate"]["sampler_trace_artifact"] != row["sampler_trace"]
        ):
            raise PublicationError("diffusion bundle validation evidence is inconsistent")
        if expected_digest and provenance["request_sha256"] != expected_digest:
            raise PublicationError("existing diffusion bundle does not match the current request")
        trace = SamplerTrace.from_json(payloads["sampler_trace"].decode())
        if request:
            validate_sampler_trace_context(trace, request, BackendProvenance(**provenance["backend_provenance"]))
        dat_path = root / row["dat"]["path"]
        record = DatRecord.from_json(payloads["dat"].decode())
        expected_added = {
            (atom["chain"], atom["residue_number"], atom["insertion_code"], atom["atom_name"])
            for atom in provenance["candidate"]["generated_atoms"]
        }
        if record.added_keys() != expected_added or len(record.added_atoms) != len(expected_added):
            raise PublicationError("diffusion .dat does not match the generated atom identities")
        if request and source_root:
            from dvbfixer.model.diffusion.validate import build_validated_result

            result = RunnerResult.from_dict({
                "schema_version": request.schema_version, "status": "success",
                "candidates": [provenance["candidate"]],
                "backend_provenance": provenance["backend_provenance"],
                "runner_diagnostics": {"exit_code": 0, "timed_out": False},
            })
            with tempfile.TemporaryDirectory(prefix=".diffusion-resume.", dir=work_parent) as temporary:
                workspace = Path(temporary)
                source_path = workspace / request.normalized_pdb.path
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_bytes(_read_contained_artifact(source_root, request.normalized_pdb, max_bytes=1_000_000_000))
                for label in ("pdb", "sampler_trace"):
                    destination = workspace / row[label]["path"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(payloads[label])
                revalidated = build_validated_result(request, result, workspace=workspace).validation_summaries[0]
            if revalidated.passed != passed or list(revalidated.hard_gate_failures) != row["hard_gate_failures"]:
                raise PublicationError("existing diffusion bundle no longer passes the current validation policy")
        candidates.append(PublishedCandidate(
            identity, seed, root / row["pdb"]["path"], dat_path, payloads["pdb"], record,
        ))
    return PublishedBundle(index["status"], tuple(candidates))


def copy_selected_candidate(bundle: Path, destination: Path, *, resume: bool = False) -> Path:
    """Keep the bundle immutable and create a PDB/.dat handoff for downstream tools."""
    selected = read_published_bundle(bundle).selected()
    if destination.resolve().is_relative_to(bundle.resolve()):
        raise PublicationError("workflow output must not modify the diffusion bundle")
    if destination.is_symlink() or destination.with_suffix(".dat").is_symlink():
        raise PublicationError("selected candidate handoff must not use symlinks")
    if destination.exists() or destination.with_suffix(".dat").exists():
        if (
            resume and destination.is_file() and destination.with_suffix(".dat").is_file()
            and destination.read_bytes() == selected.pdb_bytes
            and DatRecord.load(destination.with_suffix(".dat")).to_dict() == selected.dat_record.to_dict()
        ):
            return destination
        raise PublicationError("selected candidate handoff already exists")
    destination.write_bytes(selected.pdb_bytes)
    selected.dat_record.save(destination.with_suffix(".dat"), verbose=False)
    return destination
