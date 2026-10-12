"""Declarative metadata for every public DVBfixer command.

The CLI dispatcher, generated CLI reference, and generated GUI schema all
consume this registry so command additions cannot silently drift between them.
Keep this module dependency-free: documentation/schema generation imports it
without loading the scientific stack.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

OutputMode = Literal["file", "prefix", "directory", "stdout"]
OutputKind = Literal["artifact", "report"]


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    module: str
    description: str
    category: str
    batch_output_suffix: str | None = None
    output_extension: str = ".pdb"
    output_mode: OutputMode = "file"
    output_kind: OutputKind = "artifact"
    success_codes: tuple[int, ...] = (0,)
    specialized: bool = False
    normalize_cif: bool = True
    backend_output_modes: tuple[tuple[str, OutputMode], ...] = ()
    backend_batch_suffixes: tuple[tuple[str, str], ...] = ()

    @property
    def batch(self) -> bool:
        return self.batch_output_suffix is not None


COMMAND_REGISTRY: tuple[CommandSpec, ...] = (
    CommandSpec("split", "dvbfixer.split_chains", "Split chains empirically or extract deposited biological assemblies", "Structure preparation", batch_output_suffix="_split.pdb"),
    CommandSpec("renumber", "dvbfixer.renumber", "Renumber residues using FASTA or SEQRES alignment", "Structure preparation", batch_output_suffix="_renum.pdb"),
    CommandSpec("model", "dvbfixer.model", "Rebuild missing loops/gaps (default: Modeller)", "Structure preparation", batch_output_suffix="_model.pdb",
                backend_output_modes=(("diffusion", "directory"),), backend_batch_suffixes=(("diffusion", "_model_diffusion"),)),
    CommandSpec("pull", "dvbfixer.pull", "Pull atoms together to form a bond (geometry-only)", "Refinement", batch_output_suffix="_pulled.pdb"),
    CommandSpec("prepare", "dvbfixer.prepare", "Fix missing atoms/residues with PDBFixer", "Structure preparation", batch_output_suffix="_prepared.pdb"),
    CommandSpec("minimize", "dvbfixer.minimize", "Energy-minimize with OpenMM using selective restraints", "Refinement", batch_output_suffix="_minimized.pdb"),
    CommandSpec("protonate", "dvbfixer.protonate", "Set protonation states using PROPKA3 pKa predictions", "Refinement", batch_output_suffix="_prot.pdb"),
    CommandSpec("rename", "dvbfixer.rename", "Rename non-canonical residues (AMBER/CHARMM) to standard names", "Utilities", batch_output_suffix="_canon.pdb"),
    CommandSpec("atom-names", "dvbfixer.atom_names", "Convert PDB atom and residue names for a force field", "Utilities", normalize_cif=False),
    CommandSpec("top", "dvbfixer.top", "Generate GROMACS .itp/.top topology files from a structure", "Topology & chemistry", output_extension=".top"),
    CommandSpec("transplant", "dvbfixer.transplant", "Transplant molecules between donor and acceptor structures", "Glycoprotein preparation"),
    CommandSpec("puppet", "dvbfixer.puppet", "Strip a structure to a backbone-only polyglycine model", "Utilities", batch_output_suffix="_puppet.pdb"),
    CommandSpec("convert", "dvbfixer.glycam", "Convert between PDB/AMBER/GLYCAM and CHARMM naming (sugars + protonation variants)", "Glycoprotein preparation", batch_output_suffix="_converted.pdb"),
    CommandSpec("conect", "dvbfixer.conect", "Add inferred CONECT records (SS bonds, glycosidic links, glycosylation)", "Utilities", batch_output_suffix="_conect.pdb"),
    CommandSpec("cluster", "dvbfixer.cluster", "Cluster glycan conformations from MD trajectory", "Analysis", output_extension="", output_mode="directory"),
    CommandSpec("parametrize", "dvbfixer.parametrize", "Parametrize small molecules with GAFF2 + AM1-BCC/RESP", "Topology & chemistry", output_extension="", output_mode="directory"),
    CommandSpec("component-info", "dvbfixer.component_info", "Query authoritative CCD chemistry and compare component completeness", "Topology & chemistry", output_mode="stdout", output_kind="report", normalize_cif=False),
    CommandSpec("reconstruct-component", "dvbfixer.reconstruct_component", "Reconstruct one isolated component from pinned CCD geometry", "Topology & chemistry", output_extension="", output_mode="directory", normalize_cif=False),
    CommandSpec("homology", "dvbfixer.homology", "Multi-template homology modeling with Modeller", "Modeling & alignment", output_mode="prefix", specialized=True),
    CommandSpec("msa", "dvbfixer.msa", "Multiple protein-sequence alignment with MAFFT, MUSCLE 5, or Clustal Omega", "Modeling & alignment", output_extension=".fasta"),
    CommandSpec("salign", "dvbfixer.salign", "Structure-based multiple alignment with Modeller SALIGN", "Modeling & alignment", output_extension=".pir"),
    CommandSpec("diagnose", "dvbfixer.diagnose", "Report structure-quality issues (missing atoms, clashes, valence, ...)", "Analysis", batch_output_suffix="_diagnose.txt", output_extension=".txt", output_kind="report", success_codes=(0, 1)),
    CommandSpec("doctor", "dvbfixer.doctor", "Report installed backends, executables, and OpenMM platforms", "Utilities", output_mode="stdout", output_kind="report"),
    CommandSpec("zbs", "dvbfixer.zbs", "Full pipeline: renumber -> model -> prepare -> minimize", "Pipeline", batch_output_suffix="_zbs.pdb"),
)

COMMAND_BY_NAME = {command.name: command for command in COMMAND_REGISTRY}


def validate_command_registry() -> None:
    """Fail early when registry metadata is incomplete or contradictory."""
    if len(COMMAND_BY_NAME) != len(COMMAND_REGISTRY):
        raise RuntimeError("duplicate command name in COMMAND_REGISTRY")
    for command in COMMAND_REGISTRY:
        if re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", command.name) is None:
            raise RuntimeError(f"invalid command name: {command.name!r}")
        if not command.module.startswith("dvbfixer."):
            raise RuntimeError(f"invalid module for {command.name}: {command.module!r}")
        if not command.description or not command.category:
            raise RuntimeError(f"missing display metadata for {command.name}")
        if not command.success_codes or any(code < 0 for code in command.success_codes):
            raise RuntimeError(f"invalid success codes for {command.name}")
        if command.batch_output_suffix is not None and not command.batch_output_suffix.startswith("_"):
            raise RuntimeError(f"invalid batch suffix for {command.name}")


validate_command_registry()


def get_command(name: str) -> CommandSpec:
    """Return metadata for *name*, raising ``KeyError`` if it is not public."""
    return COMMAND_BY_NAME[name]
