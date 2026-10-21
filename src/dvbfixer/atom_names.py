"""Non-destructive CLI adapter for force-field atom naming conversion."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NoReturn

from dvbfixer import __version__
from dvbfixer.domain.force_field_naming import (
    ForceFieldTarget,
    NamingConversionError,
    NamingProfile,
    ResidueIdentity,
    VariantOverride,
)
from dvbfixer.force_field_naming import (
    NamingConversionRequest,
    NamingConversionResult,
    convert_force_field_naming,
)

_INTEGER_TEXT = re.compile(r"-?\d+")
_OVERRIDE_FIELDS = frozenset({"chainId", "residueNumber", "insertionCode", "variant"})
_REQUIRED_OVERRIDE_FIELDS = frozenset({"chainId", "residueNumber", "variant"})


class AdapterError(ValueError):
    """Expected command-input failure with a stable transport code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        category: str = "validation",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.category = category
        self.details = dict(details or {})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dvbfixer atom-names",
        description="Convert PDB atom and residue names without modifying the source file.",
    )
    io = parser.add_argument_group("Input / output")
    io.add_argument("input", help="Input legacy PDB file (.pdb or .ent)")
    io.add_argument("-o", "--output", required=True, help="Output PDB file")
    io.add_argument(
        "--variant-overrides",
        metavar="JSON",
        help="JSON array of exact chain/residue/insertion-code variant overrides",
    )
    io.add_argument("--report-json", metavar="JSON", help="Write a machine-readable JSON report")
    conversion = parser.add_argument_group("Naming conversion")
    conversion.add_argument(
        "--target-ff",
        required=True,
        choices=tuple(ForceFieldTarget),
        help="Target force-field naming dialect",
    )
    conversion.add_argument(
        "--profile",
        choices=tuple(NamingProfile),
        default="gromacs",
        help="Target naming profile: gromacs for bundled GROMACS dialects; standard for native force-field names",
    )
    conversion.add_argument("--dry-run", action="store_true", help="Validate and report without writing output")
    diagnostics = parser.add_argument_group("Diagnostics")
    diagnostics.add_argument(
        "-v", "--verbose", action="store_true", help="Print conversion summary"
    )
    from dvbfixer.batch import add_runtime_help

    add_runtime_help(parser)
    return parser.parse_args(argv)


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _same_path(left: Path, right: Path) -> bool:
    if _resolved(left) == _resolved(right):
        return True
    try:
        return left.samefile(right)
    except (FileNotFoundError, OSError):
        return False


def _validate_paths(
    input_path: Path,
    output_path: Path,
    report_path: Path | None,
    overrides_path: Path | None,
) -> None:
    if input_path.suffix.lower() not in {".pdb", ".ent"}:
        raise AdapterError(
            "UNSUPPORTED_INPUT_FORMAT",
            "atom-names accepts only legacy PDB input (.pdb or .ent)",
            details={"path": str(input_path)},
        )
    if output_path.suffix.lower() != ".pdb":
        raise AdapterError(
            "UNSUPPORTED_OUTPUT_FORMAT",
            "Output path must end in .pdb",
            details={"path": str(output_path)},
        )
    if not input_path.is_file():
        raise AdapterError(
            "INPUT_NOT_FOUND", "Input file does not exist", details={"path": str(input_path)}
        )
    named_paths = [("input", input_path), ("output", output_path)]
    if report_path is not None:
        named_paths.append(("report", report_path))
    if overrides_path is not None:
        named_paths.append(("variantOverrides", overrides_path))
    for index, (left_name, left_path) in enumerate(named_paths):
        for right_name, right_path in named_paths[index + 1 :]:
            if _same_path(left_path, right_path):
                raise AdapterError(
                    "PATH_CONFLICT",
                    f"{left_name} and {right_name} paths resolve to the same file",
                )
    if output_path.exists():
        raise AdapterError(
            "OUTPUT_EXISTS", "Output destination already exists", details={"path": str(output_path)}
        )
    if report_path is not None and report_path.exists():
        raise AdapterError(
            "REPORT_EXISTS", "Report destination already exists", details={"path": str(report_path)}
        )


def _report_path_is_safe(
    report_path: Path | None,
    input_path: Path,
    output_path: Path,
    overrides_path: Path | None,
) -> bool:
    return (
        report_path is not None
        and not report_path.exists()
        and not _same_path(report_path, input_path)
        and not _same_path(report_path, output_path)
        and (overrides_path is None or not _same_path(report_path, overrides_path))
    )


def _invalid_overrides(message: str, **details: Any) -> AdapterError:
    return AdapterError(
        "INVALID_VARIANT_OVERRIDES",
        message,
        details=details,
    )


def _load_variant_overrides(path: Path | None) -> tuple[VariantOverride, ...]:
    if path is None:
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _invalid_overrides("Could not read valid variant overrides JSON", path=str(path)) from exc
    if not isinstance(payload, list):
        raise _invalid_overrides("Variant overrides must be a top-level array")

    overrides: list[VariantOverride] = []
    identities: set[ResidueIdentity] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise _invalid_overrides("Each variant override must be an object", index=index)
        fields = set(item)
        if fields - _OVERRIDE_FIELDS or not _REQUIRED_OVERRIDE_FIELDS <= fields:
            raise _invalid_overrides(
                "Variant override has unknown or missing fields",
                index=index,
                unknownFields=sorted(fields - _OVERRIDE_FIELDS),
                missingFields=sorted(_REQUIRED_OVERRIDE_FIELDS - fields),
            )
        values = {name: item.get(name, "") for name in _OVERRIDE_FIELDS}
        if any(not isinstance(value, str) for value in values.values()):
            raise _invalid_overrides("Variant override fields must be strings", index=index)
        chain = values["chainId"]
        residue_number = values["residueNumber"]
        insertion_code = values["insertionCode"]
        if len(chain) != 1 or len(insertion_code) > 1:
            raise _invalid_overrides(
                "chainId must have length 1 and insertionCode at most length 1", index=index
            )
        if _INTEGER_TEXT.fullmatch(residue_number) is None:
            raise _invalid_overrides("residueNumber must be integer-formatted", index=index)
        identity = ResidueIdentity(chain, residue_number, insertion_code)
        if identity in identities:
            raise _invalid_overrides("Duplicate variant override identity", index=index)
        identities.add(identity)
        try:
            overrides.append(VariantOverride(identity, values["variant"]))
        except NamingConversionError as exc:
            raise _invalid_overrides(str(exc), index=index, variant=values["variant"]) from exc
    return tuple(overrides)


def _serialize_override(override: VariantOverride) -> dict[str, str]:
    return {
        "chainId": override.residue.chain,
        "residueNumber": override.residue.residue_number,
        "insertionCode": override.residue.insertion_code,
        "variant": override.variant_name,
    }


def _serialize_result(result: NamingConversionResult) -> dict[str, Any]:
    return {
        "model": result.model,
        "summary": {
            "changedAtoms": result.summary.changed_atoms,
            "changedResidues": result.summary.changed_residues,
            "variantChanges": result.summary.variant_changes,
            "atomNameChanges": result.summary.atom_name_changes,
        },
        "changes": [
            {
                "model": change.model,
                "chainId": change.chain,
                "residueNumber": change.residue_number,
                "insertionCode": change.insertion_code,
                "alternateLocation": change.alternate_location,
                "atomSerial": change.atom_serial,
                "sourceResidueName": change.source_residue_name,
                "targetResidueName": change.target_residue_name,
                "sourceAtomName": change.source_atom_name,
                "targetAtomName": change.target_atom_name,
                "ruleIds": [str(rule) for rule in change.rule_ids],
            }
            for change in result.changes
        ],
        "diagnostics": [
            {
                "code": diagnostic.code,
                "message": diagnostic.message,
                "residue": (
                    {
                        "chainId": diagnostic.residue.chain,
                        "residueNumber": diagnostic.residue.residue_number,
                        "insertionCode": diagnostic.residue.insertion_code,
                    }
                    if diagnostic.residue is not None
                    else None
                ),
            }
            for diagnostic in result.diagnostics
        ],
    }


def _report_envelope(
    *,
    args: argparse.Namespace,
    overrides: tuple[VariantOverride, ...],
    output_bytes: bytes | None,
    result: NamingConversionResult | None,
    error: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "operation": "pdb-force-field-naming",
        "status": "error" if error is not None else "success",
        "tool": {"name": "dvbfixer", "version": __version__},
        "request": {
            "targetForceField": args.target_ff,
            "profile": args.profile,
            "dryRun": args.dry_run,
            "variantOverrides": [_serialize_override(item) for item in overrides],
        },
        "output": {
            "path": str(Path(args.output)),
            "written": output_bytes is not None and not args.dry_run and error is None,
            "bytes": len(output_bytes) if output_bytes is not None else None,
            "sha256": hashlib.sha256(output_bytes).hexdigest() if output_bytes is not None else None,
        },
        "result": _serialize_result(result) if result is not None else None,
        "error": error,
    }


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _stage(path: Path, content: bytes) -> Path:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path


def _publish(staged: Path, destination: Path) -> None:
    os.replace(staged, destination)


def _write_artifacts(
    *, output_path: Path | None,
    output_bytes: bytes | None,
    report_path: Path | None,
    report_bytes: bytes | None,
) -> None:
    staged_output: Path | None = None
    staged_report: Path | None = None
    report_published = False
    try:
        if output_path is not None and output_bytes is not None:
            staged_output = _stage(output_path, output_bytes)
        if report_path is not None and report_bytes is not None:
            staged_report = _stage(report_path, report_bytes)
        if staged_report is not None and report_path is not None:
            _publish(staged_report, report_path)
            staged_report = None
            report_published = True
        if staged_output is not None and output_path is not None:
            _publish(staged_output, output_path)
            staged_output = None
    except OSError:
        if report_published and report_path is not None:
            report_path.unlink(missing_ok=True)
        raise
    finally:
        if staged_output is not None:
            staged_output.unlink(missing_ok=True)
        if staged_report is not None:
            staged_report.unlink(missing_ok=True)


def _error_payload(exc: AdapterError | NamingConversionError) -> dict[str, Any]:
    if isinstance(exc, NamingConversionError):
        return {
            "code": str(exc.code),
            "category": "conversion",
            "message": str(exc),
            "details": exc.details,
        }
    return {
        "code": exc.code,
        "category": exc.category,
        "message": str(exc),
        "details": exc.details,
    }


def _exit_error(message: str, code: int) -> NoReturn:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(code)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    input_path = Path(args.input).expanduser()
    output_path = Path(args.output).expanduser()
    report_path = Path(args.report_json).expanduser() if args.report_json else None
    overrides_path = Path(args.variant_overrides).expanduser() if args.variant_overrides else None
    overrides: tuple[VariantOverride, ...] = ()

    try:
        _validate_paths(input_path, output_path, report_path, overrides_path)
        overrides = _load_variant_overrides(overrides_path)
        try:
            source_bytes = input_path.read_bytes()
        except OSError as exc:
            raise AdapterError(
                "IO_ERROR", "Could not read input file", category="io", details={"path": str(input_path)}
            ) from exc
        result = convert_force_field_naming(
            NamingConversionRequest(
                pdb_text=source_bytes.decode("latin-1"),
                target=ForceFieldTarget(args.target_ff),
                profile=NamingProfile(args.profile),
                variant_overrides=overrides,
            )
        )
        output_bytes = result.pdb_text.encode("latin-1")
        report = _report_envelope(
            args=args,
            overrides=overrides,
            output_bytes=output_bytes,
            result=result,
            error=None,
        )
        _write_artifacts(
            output_path=None if args.dry_run else output_path,
            output_bytes=None if args.dry_run else output_bytes,
            report_path=report_path,
            report_bytes=_json_bytes(report) if report_path is not None else None,
        )
    except (AdapterError, NamingConversionError) as exc:
        if _report_path_is_safe(report_path, input_path, output_path, overrides_path):
            assert report_path is not None
            report = _report_envelope(
                args=args,
                overrides=overrides,
                output_bytes=None,
                result=None,
                error=_error_payload(exc),
            )
            try:
                _write_artifacts(
                    output_path=None,
                    output_bytes=None,
                    report_path=report_path,
                    report_bytes=_json_bytes(report),
                )
            except OSError as publish_error:
                _exit_error(f"Could not publish error report: {publish_error}", 1)
        _exit_error(str(exc), 2)
    except OSError as exc:
        _exit_error(f"Could not publish output: {exc}", 1)

    if args.verbose:
        print(
            f"Converted {result.summary.changed_atoms} atom record(s) in "
            f"{result.summary.changed_residues} residue(s)."
        )
    if args.dry_run:
        print("Dry run completed; output was not written.")
    else:
        print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
