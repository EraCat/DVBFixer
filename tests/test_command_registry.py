from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from dvbfixer.batch import OUTPUT_SUFFIXES
from dvbfixer.cli import COMMANDS
from dvbfixer.command_registry import (
    COMMAND_BY_NAME,
    COMMAND_REGISTRY,
    validate_command_registry,
)


def test_command_registry_is_complete_and_unique() -> None:
    validate_command_registry()
    names = [command.name for command in COMMAND_REGISTRY]
    assert len(names) == len(set(names))
    assert COMMANDS == {
        command.name: command.description for command in COMMAND_REGISTRY
    }
    assert COMMAND_BY_NAME == {
        command.name: command for command in COMMAND_REGISTRY
    }
    assert all(command.module.startswith("dvbfixer.") for command in COMMAND_REGISTRY)
    assert all(command.category for command in COMMAND_REGISTRY)
    assert all(command.success_codes for command in COMMAND_REGISTRY)
    assert "glycam" not in COMMAND_BY_NAME
    assert COMMAND_BY_NAME["atom-names"].module == "dvbfixer.atom_names"
    assert COMMAND_BY_NAME["atom-names"].category == "Utilities"
    assert COMMAND_BY_NAME["atom-names"].normalize_cif is False
    assert COMMAND_BY_NAME["atom-names"].batch is False


def test_batch_suffixes_are_derived_from_command_registry() -> None:
    assert OUTPUT_SUFFIXES == {
        command.name: command.batch_output_suffix
        for command in COMMAND_REGISTRY
        if command.batch_output_suffix is not None
    }


def test_generators_use_the_same_registry_metadata() -> None:
    from scripts import gen_cli_reference, gen_gui_spec

    assert gen_cli_reference.COMMANDS == [
        (command.name, command.module) for command in COMMAND_REGISTRY
    ]
    assert gen_gui_spec.MODULES == {
        command.name: command.module for command in COMMAND_REGISTRY
    }
    assert gen_gui_spec.CATEGORIES == {
        command.name: command.category for command in COMMAND_REGISTRY
    }
    assert gen_gui_spec.BATCH == {
        command.name for command in COMMAND_REGISTRY if command.batch
    }
    assert gen_gui_spec.OUTPUT_EXTENSIONS == {
        command.name: command.output_extension for command in COMMAND_REGISTRY
    }
    assert gen_gui_spec.OUTPUT_MODES == {
        command.name: command.output_mode for command in COMMAND_REGISTRY
    }


def test_gui_schema_labels_negative_switches_by_actual_option() -> None:
    from scripts.gen_gui_spec import command_schema

    split = command_schema("split", COMMAND_BY_NAME["split"].description)
    labels = {field["flag"]: field["label"] for field in split["flags"]}
    assert labels["--no-renumber"] == "No Renumber"

    zbs = command_schema("zbs", COMMAND_BY_NAME["zbs"].description)
    labels = {field["flag"]: field["label"] for field in zbs["flags"]}
    assert labels["--no-propka"] == "No PROPKA"
    assert labels["--no-protassign"] == "No ProtAssign"
    assert labels["--strip-heterogens"] == "Strip Heterogens"


def test_gui_schema_excludes_doctor_diffusion_options() -> None:
    from scripts.gen_gui_spec import command_schema

    doctor = command_schema("doctor", COMMAND_BY_NAME["doctor"].description)
    flags = {field["flag"] for field in doctor["flags"]}

    assert not flags & {
        "--diffusion-model",
        "--diffusion-timeout",
    }


def test_doctor_and_diffusion_contracts_import_without_scientific_backends() -> None:
    code = '''
import importlib.abc
import sys

class BlockScientificImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"openmm", "pdbfixer", "modeller", "torch"}:
            raise AssertionError("unexpected scientific import: " + fullname)

sys.meta_path.insert(0, BlockScientificImports())
from dvbfixer.model.diffusion import DIFFUSION_SCHEMA_VERSION, RunnerLimits
from dvbfixer.model.diffusion.contract import DiffusionRequest
from dvbfixer.doctor import parse_args
from scripts.gen_gui_spec import command_schema

assert DIFFUSION_SCHEMA_VERSION > 0
assert callable(DiffusionRequest)
assert callable(RunnerLimits)
assert parse_args([]).diffusion_model is None
assert command_schema("doctor", "Installation diagnostics")["name"] == "doctor"
assert "dvbfixer.model.diffusion.pipeline" not in sys.modules
from tests.test_command_registry import test_atom_names_gui_preserves_ff_acronym_and_cli_profile_choices
test_atom_names_gui_preserves_ff_acronym_and_cli_profile_choices()
'''
    subprocess.run([sys.executable, "-B", "-c", code], check=True, timeout=30)


def test_component_commands_keep_gui_paths_workspace_scoped() -> None:
    from scripts.gen_gui_spec import command_schema

    info = command_schema("component-info", COMMAND_BY_NAME["component-info"].description)
    info_fields = {field["flag"]: field for field in info["flags"]}
    assert info_fields["--ccd-cif"]["type"] == "artifact"
    assert info_fields["--structure"]["type"] == "artifact"
    assert "--cache-dir" not in info_fields
    assert "--json" not in info_fields

    reconstruction = command_schema(
        "reconstruct-component", COMMAND_BY_NAME["reconstruct-component"].description
    )
    reconstruction_fields = {field["flag"]: field for field in reconstruction["flags"]}
    assert reconstruction_fields["--ccd-cif"]["type"] == "artifact"
    assert "--output-root" not in reconstruction_fields


def test_gui_schema_exposes_workflow_backend_but_not_private_paths() -> None:
    from scripts.gen_gui_spec import command_schema

    model = command_schema("model", COMMAND_BY_NAME["model"].description)
    flags = {field["flag"] for field in model["flags"]}

    assert {"--backend", "--diffusion-model", "--diffusion-seed"} <= flags
    assert not {"--diffusion-request", "--diffusion-work-parent", "--diffusion-resume"} & flags
    assert model["backendOutputModes"] == {"diffusion": "directory"}


def test_atom_names_gui_preserves_ff_acronym_and_cli_profile_choices() -> None:
    from scripts.gen_gui_spec import _field, command_schema

    schema = command_schema("atom-names", COMMAND_BY_NAME["atom-names"].description)
    fields = {field["flag"]: field for field in schema["flags"]}
    assert fields["--target-ff"]["label"] == "Target FF"
    assert fields["--profile"]["options"] == ["gromacs", "standard"]
    # Test the shared label builder directly. Importing every command parser
    # here would drag OpenMM into CI's intentionally dependency-light lane.
    parser = argparse.ArgumentParser(add_help=False)
    for option, expected in (
        ("--ff", "FF"), ("--ff-dir", "FF Dir"),
        ("--target-ff", "Target FF"), ("--obminimize-ff", "Obminimize FF"),
    ):
        assert _field(parser.add_argument(option), "Force field")["label"] == expected
    generated = (Path(__file__).resolve().parents[1] / "gui/server/generated-dvbfixer-spec.ts").read_text()
    assert not re.search(r'"label":\s*"[^"\n]*\bFf\b', generated)
