"""dvbfixer — unified CLI for PDB structure preparation tools."""

from __future__ import annotations

import sys
from importlib import import_module

from dvbfixer.command_registry import COMMAND_REGISTRY, get_command

COMMANDS: dict[str, str] = {
    command.name: command.description for command in COMMAND_REGISTRY
}


def print_help() -> None:
    print("dvbfixer — PDB structure preparation tools\n")
    print("Usage: dvbfixer <command> [options]\n")
    print("Commands:")
    for cmd, desc in COMMANDS.items():
        print(f"  {cmd:<12s}  {desc}")
    print("\n  --version     Show version")
    print("  --log-file PATH  Append all output to PATH while retaining the terminal")
    print("\nBatch mode (runs a command independently on each structure;")
    print("continues after per-file failures by default):")
    print("  --input-dir DIR      Process every .pdb/.ent/.cif/.mmcif structure in DIR")
    print("  --output-dir DIR     Batch output directory")
    print("  --recursive          Include subdirectories")
    print("  --fail-fast          Stop after the first failed structure")
    print("\nRun 'dvbfixer <command> --help' for command-specific options.")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print_help()
        sys.exit(0)

    if sys.argv[1] == "--version":
        from dvbfixer import __version__
        print(f"dvbfixer {__version__}")
        sys.exit(0)

    command = sys.argv[1]
    argv = sys.argv[2:]

    from dvbfixer.batch import extract_batch_options

    batch_options, argv = extract_batch_options(argv)

    if command not in COMMANDS:
        print(f"Unknown command: {command}\n", file=sys.stderr)
        print_help()
        sys.exit(1)

    command_spec = get_command(command)
    module_name = command_spec.module
    cmd_main = import_module(module_name).main

    def normalized_main(arguments: list[str]) -> object:
        if not command_spec.normalize_cif:
            return cmd_main(arguments)
        from dvbfixer.structure_input import run_with_normalized_inputs

        return run_with_normalized_inputs(command, cmd_main, arguments)

    from dvbfixer.runtime import run_header, tee_output

    informational = any(arg in ("-h", "--help") for arg in argv)
    with tee_output(None if informational else batch_options.log_file):
        if not informational:
            print(run_header(command), file=sys.stderr)
        if batch_options.input_dir:
            from dvbfixer.batch import run_directory

            run_directory(command, normalized_main, batch_options, argv)
        else:
            if batch_options.output_dir or batch_options.recursive or batch_options.fail_fast:
                raise SystemExit("--output-dir, --recursive, and --fail-fast require --input-dir")
            normalized_main(argv)


if __name__ == "__main__":
    main()
