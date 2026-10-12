"""Shared directory-input support for single-structure commands."""

from __future__ import annotations

import argparse
import io
import re
import sys
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from dvbfixer.command_registry import COMMAND_REGISTRY, get_command

OUTPUT_SUFFIXES = {
    command.name: command.batch_output_suffix
    for command in COMMAND_REGISTRY
    if command.batch_output_suffix is not None
}


class _Mirror(io.TextIOBase):
    """Forward command output unchanged while retaining it for failure summaries."""

    def __init__(self, target: io.TextIOBase) -> None:
        self.target = target
        self.parts: list[str] = []

    def write(self, text: str) -> int:
        self.parts.append(text)
        return self.target.write(text)

    def flush(self) -> None:
        self.target.flush()

    def isatty(self) -> bool:
        return self.target.isatty()

    def fileno(self) -> int:
        return self.target.fileno()

    def captured(self) -> str:
        return "".join(self.parts)


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _last_reported_error(output: str) -> str | None:
    """Return the last useful command error, without runtime decoration."""
    candidates: list[str] = []
    for raw_line in output.splitlines():
        line = _ANSI_ESCAPE.sub("", raw_line).strip()
        line = re.sub(r"^!!!\s+ERROR\s+!!!\s*", "", line, flags=re.IGNORECASE)
        match = re.match(r"(?:Error|ERROR):\s*(.+)", line)
        if match:
            candidates.append(match.group(1).strip())
    return candidates[-1] if candidates else None


def _failure_advice(reason: str) -> str:
    """Give an actionable next step for common failures, plus a safe fallback."""
    lower = reason.lower()
    if "fasta missing sequences for chain" in lower:
        return (
            "The PDB contains a protein chain with no matching FASTA record. "
            "Rename/add the FASTA header for every listed PDB chain, or omit --fasta "
            "if sequence-guided modeling is not required. Chain IDs are case-sensitive."
        )
    if "fasta" in lower and ("invalid" in lower or "header" in lower):
        return "Correct the FASTA formatting and chain identifiers, then rerun."
    if "illegal variant for cys" in lower:
        return (
            "The selected cysteine protonation/disulfide variant is incompatible with "
            "its current bonding. Check CYS/CYX/CYM naming and disulfide connectivity."
        )
    if "no template found for residue" in lower:
        return (
            "The force field cannot match this residue's atoms or external bonds. "
            "Check residue naming, terminal state, CONECT records, and missing atoms."
        )
    if "not found" in lower or "does not exist" in lower:
        return "Check that the referenced file or directory exists and is readable."
    if "no chains found" in lower or "no recognized chains" in lower:
        return "The input has no recognized molecular chains; inspect PDB ATOM/HETATM records and chain IDs."
    return "Review this error and the detailed output above, correct the input or options, then rerun."


def extract_batch_options(argv: Sequence[str]) -> tuple[argparse.Namespace, list[str]]:
    """Remove global batch options while leaving command options untouched."""
    # Do not let this pre-parser steal command options by abbreviation:
    # ``--output`` must not be interpreted as global ``--output-dir``.
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--input-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--log-file")
    return parser.parse_known_args(list(argv))


def add_runtime_help(parser: argparse.ArgumentParser, *, batch: bool = False) -> None:
    """Expose unified-CLI options and this tool's batch status in its help."""
    runtime = parser.add_argument_group("Global logging")
    runtime.add_argument(
        "--log-file", metavar="PATH",
        help="Append all stdout/stderr (including child tools) to PATH while still printing it",
    )
    group = parser.add_argument_group(
        "Batch mode",
        (
            "Run this command independently for every supported structure in a directory. "
            "Processing continues after per-file failures by default."
            if batch else
            "This command does not support directory batch input. Run it once per input, "
            "or use a supported pipeline command."
        ),
    )
    if batch:
        group.add_argument(
            "--input-dir", metavar="DIR", help="Process every supported structure in DIR"
        )
        group.add_argument("--output-dir", metavar="DIR", help="Write batch results under DIR")
        group.add_argument("--recursive", action="store_true", help="Include input subdirectories")
        group.add_argument("--fail-fast", action="store_true", help="Stop after the first failed structure")


def run_directory(
    command: str,
    command_main: Callable[[list[str]], object],
    options: argparse.Namespace,
    command_argv: list[str],
) -> None:
    """Run a normal single-input command once for every structure in a folder."""
    if command not in OUTPUT_SUFFIXES:
        supported = ", ".join(sorted(OUTPUT_SUFFIXES))
        raise SystemExit(
            f"dvbfixer {command} does not support --input-dir. Supported commands: {supported}"
        )
    if command == "model" and any(
        token == "--backend=diffusion"
        or (token == "--backend" and index + 1 < len(command_argv)
            and command_argv[index + 1] == "diffusion")
        for index, token in enumerate(command_argv)
    ):
        _run_diffusion_directory(command_main, options, command_argv)
        return
    if "-o" in command_argv or "--output" in command_argv:
        raise SystemExit("Use --output-dir, not -o/--output, with --input-dir")

    input_dir = Path(options.input_dir).expanduser()
    if not input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist or is not a directory: {input_dir}")
    output_dir = Path(options.output_dir or f"{input_dir.name}_dvbfixer").expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    globber = input_dir.rglob if options.recursive else input_dir.glob
    extensions = {".pdb", ".ent", ".cif", ".mmcif"}
    if command == "split":
        extensions.add(".gro")
    inputs = sorted(p for p in globber("*") if p.is_file() and p.suffix.lower() in extensions)
    if not inputs:
        raise SystemExit(f"No supported structure files found in {input_dir}")

    failures: list[tuple[Path, str, str]] = []
    diagnostic_findings: list[tuple[Path, Path]] = []
    successes = 0
    policy = "stop at first failure" if options.fail_fast else "continue after failures"
    print(f"Batch mode: run '{command}' independently on {len(inputs)} structure(s)")
    print(f"Output directory: {output_dir}")
    print(f"Failure policy: {policy}")
    for index, input_path in enumerate(inputs, 1):
        relative = input_path.relative_to(input_dir)
        destination_dir = output_dir / relative.parent
        destination_dir.mkdir(parents=True, exist_ok=True)
        suffix = OUTPUT_SUFFIXES[command]
        if command == "diagnose" and "--format" in command_argv:
            pos = command_argv.index("--format")
            if pos + 1 < len(command_argv) and command_argv[pos + 1] == "json":
                suffix = "_diagnose.json"
        output_path = destination_dir / f"{input_path.stem}{suffix}"
        print(f"[{index}/{len(inputs)}] {relative}")
        stdout_capture = _Mirror(sys.stdout)
        stderr_capture = _Mirror(sys.stderr)
        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                command_main([str(input_path), *command_argv, "-o", str(output_path)])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
            if code == 0:
                successes += 1
                continue
            if command == "diagnose" and code == 1:
                diagnostic_findings.append((relative, output_path))
                print(f"  FINDINGS: {relative} has ERROR-severity findings "
                      f"(report: {output_path})")
                if options.fail_fast:
                    break
                continue
            captured = stdout_capture.captured() + "\n" + stderr_capture.captured()
            reported = _last_reported_error(captured)
            reason = reported or (
                f"command exited with status {code}" if isinstance(exc.code, int)
                else str(exc.code)
            )
            advice = _failure_advice(reason)
            failures.append((relative, reason, advice))
            print(f"  FAILED: {relative}: {reason}")
        except Exception as exc:  # isolate each structure from failures in the others
            reason = f"{type(exc).__name__}: {exc}"
            failures.append((relative, reason, _failure_advice(reason)))
            print(f"  FAILED: {relative} ({reason})")
        else:
            successes += 1
        if failures and options.fail_fast:
            break

    if failures:
        processed = successes + len(diagnostic_findings) + len(failures)
        print(f"Batch mode completed: {successes} succeeded, "
              f"{len(failures)} failed, {len(inputs) - processed} not processed.")
        print("\n" + "=" * 60)
        print("FAILED STRUCTURES - CAUSES AND NEXT STEPS")
        print("=" * 60)
        for path, reason, advice in failures:
            print(f"  {path}")
            print(f"    Cause: {reason}")
            print(f"    How to fix: {advice}")
        raise SystemExit(1)
    if diagnostic_findings:
        processed = successes + len(diagnostic_findings)
        print(f"Batch diagnose completed: {successes} clean, "
              f"{len(diagnostic_findings)} with ERROR findings, "
              f"0 execution failures, {len(inputs) - processed} not processed.")
        print("Structures with ERROR findings:")
        for path, report_path in diagnostic_findings:
            print(f"  - {path} (report: {report_path})")
        raise SystemExit(1)
    print(f"Batch mode completed: {successes} succeeded, 0 failed.")


def _run_diffusion_directory(
    command_main: Callable[[list[str]], object],
    options: argparse.Namespace,
    command_argv: list[str],
) -> None:
    """Preflight all destinations, then run contained bundle jobs sequentially."""
    import json
    import os

    from dvbfixer.model.cli import parse_args
    from dvbfixer.model.diffusion.publication import read_published_bundle

    args = parse_args(["batch-input.pdb", *command_argv])
    if args.output or args.diffusion_request:
        raise SystemExit("Diffusion batch uses --output-dir and per-input request construction")
    source = Path(options.input_dir).expanduser().resolve()
    destination = Path(options.output_dir or f"{source.name}_dvbfixer").expanduser().resolve()
    if not source.is_dir():
        raise SystemExit(f"Input directory does not exist: {source}")
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise SystemExit("Diffusion batch source and output directories must be disjoint")
    globber = source.rglob if options.recursive else source.glob
    inputs = sorted(p for p in globber("*") if p.is_file() and p.suffix.lower() in {".pdb", ".ent", ".cif", ".mmcif"})
    if not inputs or len(inputs) > 10_000:
        raise SystemExit("Diffusion batch requires 1–10000 structure inputs")
    suffix = dict(get_command("model").backend_batch_suffixes)["diffusion"]
    outputs = [destination / p.relative_to(source).parent / f"{p.stem}{suffix}" for p in inputs]
    if len(set(outputs)) != len(outputs):
        raise SystemExit("Diffusion batch has colliding output stems")
    for output in outputs:
        for parent in output.parents:
            if parent == destination:
                break
            if parent.is_symlink():
                raise SystemExit(f"Diffusion batch output parent is a symlink: {parent}")
        if output.is_symlink() or (output.exists() and not args.diffusion_resume):
            raise SystemExit(f"Diffusion batch output already exists: {output}")
        if output.exists():
            read_published_bundle(output)
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    print(f"Diffusion batch: {len(inputs)} inputs; sequential GPU execution (concurrency=1)")
    for input_path, output in zip(inputs, outputs):
        relative = input_path.relative_to(source).as_posix()
        output.parent.mkdir(parents=True, exist_ok=True)
        existed = output.exists()
        stdout_capture = _Mirror(sys.stdout)
        stderr_capture = _Mirror(sys.stderr)
        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                command_main([str(input_path), *command_argv, "-o", str(output)])
            published = read_published_bundle(output)
            status = "success" if published.status == "success" else "validation_failed"
            row = {"input": relative, "output": output.relative_to(destination).as_posix(),
                   "status": status, "resumed": existed}
        except (Exception, SystemExit) as exc:
            message = _last_reported_error(stdout_capture.captured() + "\n" + stderr_capture.captured()) or str(exc)
            status = "unsupported" if "outside the supported scope" in message else "failed"
            row = {"input": relative, "status": status, "error": message[:2000]}
        finally:
            stdout_capture.close()
            stderr_capture.close()
        rows.append(row)
        print(f"  {relative}: {row['status']}")
        if options.fail_fast and row["status"] != "success":
            break
    rows.extend({"input": p.relative_to(source).as_posix(), "status": "skipped"} for p in inputs[len(rows):])
    report = {"schema_version": 1, "command": "model", "backend": "diffusion",
              "concurrency": 1, "seeds": args.diffusion_seeds, "results": rows}
    temporary = destination / f".diffusion-batch.{os.getpid()}.json"
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination / "diffusion-batch.json")
    finally:
        temporary.unlink(missing_ok=True)
    if any(row["status"] not in {"success", "skipped"} for row in rows):
        raise SystemExit(1)
