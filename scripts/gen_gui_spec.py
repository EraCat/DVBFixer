#!/usr/bin/env python
"""Generate the DVBfixer GUI command schema directly from argparse parsers."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from unittest.mock import patch

from dvbfixer.command_registry import COMMAND_BY_NAME, COMMAND_REGISTRY

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "gui" / "server" / "generated-dvbfixer-spec.ts"
# Compatibility views for callers that imported these generator constants.
# They are derived from the registry and are no longer independent metadata.
MODULES = {command.name: command.module for command in COMMAND_REGISTRY}
CATEGORIES = {command.name: command.category for command in COMMAND_REGISTRY}
BATCH = {command.name for command in COMMAND_REGISTRY if command.batch}
ARTIFACT_DESTS = {
    "input", "topology", "trajectory", "acceptor", "donor", "graft", "template",
    "fasta", "alignment", "dat", "gaussian_log", "variant_overrides",
    "ccd_cif", "structure",
}
HIDDEN_DESTS = {"report_json", "cache_dir", "json_path", "output_root", "diffusion_request", "diffusion_work_parent", "diffusion_resume"}
OUTPUT_EXTENSIONS = {
    command.name: command.output_extension for command in COMMAND_REGISTRY
}
OUTPUT_MODES = {command.name: command.output_mode for command in COMMAND_REGISTRY}
FIELD_LABELS = {
    "ccd_cif": "CCD CIF",
    "ccd_sha256": "CCD SHA-256",
    "ph": "pH",
    "propka": "PROPKA",
    "protassign": "ProtAssign",
    "protassign_binary": "ProtAssign Binary",
    "extra_ff": "Extra Force Field",
}
LABEL_ACRONYMS = {
    "fasta": "FASTA",
    "ff": "FF",
    "msa": "MSA",
    "pdb": "PDB",
    "propka": "PROPKA",
    "protassign": "ProtAssign",
}


def _humanize_option(option: str) -> str:
    return " ".join(
        LABEL_ACRONYMS.get(token, token.title())
        for token in option.removeprefix("--").split("-")
    )


class _Captured(Exception):
    def __init__(self, parser: argparse.ArgumentParser):
        self.parser = parser


def _capture_parser(module_name: str) -> argparse.ArgumentParser:
    module = importlib.import_module(module_name)

    def capture(parser, args=None, namespace=None):  # noqa: ANN001, ARG001
        raise _Captured(parser)

    try:
        with patch.object(argparse.ArgumentParser, "parse_args", capture):
            module.parse_args([])
    except _Captured as captured:
        return captured.parser
    raise RuntimeError(f"could not capture parser for {module_name}")


def _plain_default(value):  # noqa: ANN001, ANN201
    if value is None or value is argparse.SUPPRESS:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)) and all(isinstance(item, (str, int, float)) for item in value):
        return list(value)
    return None


def _field(action: argparse.Action, group: str, exclusive_group: str | None = None) -> dict:
    option_strings = list(action.option_strings)
    positive = next((item for item in option_strings if item.startswith("--") and not item.startswith("--no-")), None)
    flag = positive or next((item for item in option_strings if item.startswith("--")), None)
    flag = flag or (option_strings[-1] if option_strings else action.dest)
    choices = list(action.choices) if action.choices is not None else None
    is_bool = isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction,
                                  argparse.BooleanOptionalAction))
    if is_bool:
        field_type = "bool"
    elif choices:
        field_type = "select"
    elif action.type in (int, float) or getattr(action.type, "_dvbfixer_numeric", False):
        field_type = "number"
    elif action.dest in ARTIFACT_DESTS:
        field_type = "artifact"
    else:
        field_type = "text"
    label_from_option = (
        isinstance(action, argparse._StoreFalseAction)
        or (isinstance(action, argparse._StoreTrueAction) and flag.startswith("--no-"))
    )
    label = (
        _humanize_option(flag)
        if label_from_option else FIELD_LABELS.get(action.dest, action.dest.replace("_", " ").title())
    )
    result = {
        "flag": flag,
        "dest": action.dest,
        "label": label,
        "type": field_type,
        "group": group,
        "help": action.help if action.help is not argparse.SUPPRESS else None,
        "required": bool(action.required),
        "repeatable": isinstance(action, argparse._AppendAction),
        "multi": action.nargs in ("+", "*") or (isinstance(action.nargs, int) and action.nargs > 1),
        "exclusiveGroup": exclusive_group,
    }
    default = (_plain_default(action.default) if isinstance(action, argparse.BooleanOptionalAction)
               else False if is_bool else _plain_default(action.default))
    if default is not None:
        result["default"] = default
    if choices:
        result["options"] = choices
    false_flag = (next((item for item in option_strings if item.startswith("--no-")), None)
                  if isinstance(action, argparse.BooleanOptionalAction) else None)
    if false_flag:
        result["falseFlag"] = false_flag
    return {key: value for key, value in result.items() if value is not None}


def command_schema(name: str, description: str) -> dict:
    command = COMMAND_BY_NAME[name]
    parser = _capture_parser(command.module)
    groups: list[dict] = []
    inputs: list[dict] = []
    flags: list[dict] = []
    has_output = False
    exclusive_by_action: dict[argparse.Action, str] = {}
    for index, exclusive in enumerate(parser._mutually_exclusive_groups):
        identifier = f"{name}:exclusive:{index}"
        for action in exclusive._group_actions:
            exclusive_by_action[action] = identifier
    for group in parser._action_groups:
        if group.title in {"Global logging", "Batch mode"}:
            continue
        if name not in {"model", "zbs", "homology"} and group.title in {"Diffusion options", "Backend"}:
            continue
        group_fields: list[str] = []
        for action in group._group_actions:
            if isinstance(action, argparse._HelpAction):
                continue
            if action.dest in HIDDEN_DESTS:
                continue
            if action.dest == "output" or "--output" in action.option_strings:
                has_output = True
                continue
            field = _field(action, group.title, exclusive_by_action.get(action))
            if action.option_strings:
                flags.append(field)
                group_fields.append(field["flag"])
            else:
                field["name"] = action.dest
                field["nargs"] = action.nargs
                inputs.append(field)
        if group_fields:
            groups.append({"name": group.title, "fields": group_fields})
    return {
        "name": name,
        "label": name.replace("_", " ").replace("-", " ").title(),
        "description": description,
        "category": command.category,
        "inputs": inputs,
        "flags": flags,
        "groups": groups,
        "outputExtension": command.output_extension,
        "outputMode": command.output_mode,
        **({"backendOutputModes": dict(command.backend_output_modes)} if command.backend_output_modes else {}),
        "hasOutput": has_output,
        "outputKind": command.output_kind,
        "batch": command.batch,
        "successCodes": list(command.success_codes),
        "specialized": command.specialized,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the committed schema is stale")
    args = parser.parse_args(argv)
    schema = [
        command_schema(command.name, command.description)
        for command in COMMAND_REGISTRY
    ]
    payload = json.dumps(schema, indent=2, ensure_ascii=False)
    content = (
        "// Generated by scripts/gen_gui_spec.py; do not edit by hand.\n"
        "import type { CommandDef } from './dvbfixer-spec'\n\n"
        f"export const GENERATED_COMMANDS = {payload} as CommandDef[]\n"
    )
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != content:
            raise SystemExit("GUI command schema is stale; run python scripts/gen_gui_spec.py")
        print("GUI command schema is in sync with argparse.")
        return
    OUTPUT.write_text(content)
    print(f"Wrote {OUTPUT.relative_to(ROOT)} ({len(schema)} commands)")


if __name__ == "__main__":
    main()
