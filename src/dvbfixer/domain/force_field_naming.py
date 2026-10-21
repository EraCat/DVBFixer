"""Domain vocabulary and policy data for force-field naming conversion."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ForceFieldTarget(StrEnum):
    AMBER = "amber"
    AMBER19SB = "amber19sb"
    CHARMM = "charmm"


class NamingProfile(StrEnum):
    GROMACS = "gromacs"
    STANDARD = "standard"


class NamingRuleId(StrEnum):
    EXPLICIT_VARIANT = "explicit-variant"
    SOURCE_VARIANT = "source-variant"
    AMBER_ATOM_NAME = "amber-atom-name"
    CHARMM_ATOM_NAME = "charmm-atom-name"
    TERMINAL_ATOM_NAME = "terminal-atom-name"
    NUCLEIC_ACID_ATOM_NAME = "nucleic-acid-atom-name"


class NamingErrorCode(StrEnum):
    INVALID_VARIANT = "INVALID_VARIANT"
    AMBIGUOUS_VARIANT = "AMBIGUOUS_VARIANT"
    MALFORMED_PDB = "MALFORMED_PDB"
    MULTI_MODEL_UNSUPPORTED = "MULTI_MODEL_UNSUPPORTED"
    NAMING_COLLISION = "NAMING_COLLISION"
    UNSUPPORTED_NAMING_DIRECTION = "UNSUPPORTED_NAMING_DIRECTION"


AMBER_VARIANTS = frozenset({"HID", "HIE", "HIP", "ASH", "GLH", "CYX", "CYM", "LYN"})
CHARMM_VARIANTS = frozenset({"HSD", "HSE", "HSP", "ASPP", "GLUP", "CYM", "LSN"})


@dataclass(frozen=True, slots=True)
class ResidueIdentity:
    chain: str
    residue_number: str
    insertion_code: str = ""

    def __post_init__(self) -> None:
        if len(self.chain) != 1:
            raise ValueError("chain must be exactly one character")
        if len(self.insertion_code) > 1:
            raise ValueError("insertion_code must contain at most one character")
        if not self.residue_number:
            raise ValueError("residue_number must not be empty")


@dataclass(frozen=True, slots=True)
class VariantOverride:
    residue: ResidueIdentity
    variant_name: str

    def __post_init__(self) -> None:
        if self.variant_name not in AMBER_VARIANTS:
            raise NamingConversionError(
                NamingErrorCode.INVALID_VARIANT,
                f"Unsupported explicit variant {self.variant_name!r}",
                details={
                    "chain": self.residue.chain,
                    "residue_number": self.residue.residue_number,
                    "insertion_code": self.residue.insertion_code,
                    "variant": self.variant_name,
                },
            )


class NamingConversionError(ValueError):
    """A stable, transport-safe naming conversion failure."""

    def __init__(
        self,
        code: NamingErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


PROTONATION_AMBER_TO_CHARMM: dict[str, str] = {
    "HID": "HSD",
    "HIE": "HSE",
    "HIP": "HSP",
    "ASH": "ASPP",
    "GLH": "GLUP",
    "LYN": "LSN",
    "CYX": "CYS",
}

PROTONATION_CHARMM_TO_AMBER: dict[str, str] = {
    "HSD": "HID",
    "HSE": "HIE",
    "HSP": "HIP",
    "ASPP": "ASH",
    "GLUP": "GLH",
    "LSN": "LYN",
}

PROTONATION_ATOM_RENAME_TO_CHARMM: dict[str, dict[str, str]] = {
    "LYN": {"HZ2": "HZ1", "HZ3": "HZ2"},
}
PROTONATION_ATOM_RENAME_TO_AMBER: dict[str, dict[str, str]] = {
    "LSN": {"HZ1": "HZ2", "HZ2": "HZ3"},
}

GROMACS_AMBER_ATOM_RENAMES: dict[str, dict[str, str]] = {
    "ALA": {},
    "VAL": {},
    "THR": {},
    "SER": {"HB3": "HB1"},
    "CYS": {"HB3": "HB1"},
    "CYX": {"HB3": "HB1"},
    "CYM": {"HB3": "HB1"},
    "ASN": {"HB3": "HB1"},
    "ASP": {"HB3": "HB1"},
    "ASH": {"HB3": "HB1"},
    "PHE": {"HB3": "HB1"},
    "TYR": {"HB3": "HB1"},
    "TRP": {"HB3": "HB1"},
    "HIS": {"HB3": "HB1"},
    "HID": {"HB3": "HB1"},
    "HIE": {"HB3": "HB1"},
    "HIP": {"HB3": "HB1"},
    "LEU": {"HB3": "HB1"},
    "GLU": {"HB3": "HB1", "HG3": "HG1"},
    "GLH": {"HB3": "HB1", "HG3": "HG1"},
    "GLN": {"HB3": "HB1", "HG3": "HG1"},
    "MET": {"HB3": "HB1", "HG3": "HG1"},
    "PRO": {"HB3": "HB1", "HG3": "HG1", "HD3": "HD1"},
    "HYP": {"CD": "CD2", "HB3": "HB1", "HD2": "HD21", "HD3": "HD22"},
    "ARG": {"HB3": "HB1", "HG3": "HG1", "HD3": "HD1"},
    "LYS": {"HB3": "HB1", "HG3": "HG1", "HD3": "HD1", "HE3": "HE1"},
    "LYN": {
        "HB3": "HB1",
        "HG3": "HG1",
        "HD3": "HD1",
        "HE3": "HE1",
        "HZ3": "HZ1",
    },
    "GLY": {"HA3": "HA1"},
    "ILE": {"HG13": "HG11"},
    "ACE": {"H1": "HH31", "H2": "HH32", "H3": "HH33"},
    "NME": {"H1": "HH31", "H2": "HH32", "H3": "HH33", "C": "CH3"},
}

GROMACS_AMBER19SB_ATOM_RENAMES: dict[str, dict[str, str]] = {
    **GROMACS_AMBER_ATOM_RENAMES,
    "HYP": {"HB3": "HB1", "HD2": "HD21", "HD3": "HD22"},
    "ACE": {},
    "NME": {},
}

GROMACS_AMBER_LYN_ATOM_RENAME: dict[str, dict[str, str]] = {
    "LYN": {"HZ3": "HZ1"},
}

CHARMM_UNIVERSAL_ATOM_RENAMES: dict[str, str] = {"H": "HN"}

GROMACS_CHARMM_CAP_ATOM_RENAMES: dict[str, dict[str, str]] = {
    "ACE": {"H1": "HH31", "H2": "HH32", "H3": "HH33"},
    "NME": {"H1": "HH31", "H2": "HH32", "H3": "HH33", "C": "CH3", "H": "HN"},
}

GROMACS_AMBER_NA_ATOM_RENAMES: dict[str, dict[str, str]] = {
    "DA": {"H2'": "H2'1", "H2''": "H2'2", "H5'": "H5'1", "H5''": "H5'2"},
    "DC": {"H2'": "H2'1", "H2''": "H2'2", "H5'": "H5'1", "H5''": "H5'2"},
    "DG": {"H2'": "H2'1", "H2''": "H2'2", "H5'": "H5'1", "H5''": "H5'2"},
    "DT": {"H2'": "H2'1", "H2''": "H2'2", "H5'": "H5'1", "H5''": "H5'2"},
    "A": {"H2'": "H2'1", "H2''": "H2'2", "H5'": "H5'1", "H5''": "H5'2", "HO'2": "HO2'"},
    "C": {"H2'": "H2'1", "H2''": "H2'2", "H5'": "H5'1", "H5''": "H5'2", "HO'2": "HO2'"},
    "G": {"H2'": "H2'1", "H2''": "H2'2", "H5'": "H5'1", "H5''": "H5'2", "HO'2": "HO2'"},
    "U": {"H2'": "H2'1", "H2''": "H2'2", "H5'": "H5'1", "H5''": "H5'2", "HO'2": "HO2'"},
}

PROTEIN_RESNAMES = frozenset(
    {
        "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
        "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
        "HYP", "HID", "HIE", "HIP", "ASH", "GLH", "CYX", "CYM", "LYN", "HSD",
        "HSE", "HSP", "ASPP", "GLUP", "LSN", "MSE", "SEC", "PYL", "SEP", "TPO",
        "PTR", "CSO", "CSD", "CME",
    }
)
TERMINAL_CHAIN_RESNAMES = PROTEIN_RESNAMES | {"ACE", "NME", "NHE", "NH2"}


# Native CHARMM protein aliases, checked against OpenMM charmm36.xml and
# amber14/protein.ff14SB.xml. Keep these separate from consumer-specific caps.
NATIVE_CHARMM_ATOM_RENAMES: dict[str, dict[str, str]] = {
    residue: dict(renames)
    for residue, renames in GROMACS_AMBER_ATOM_RENAMES.items()
    if residue in PROTEIN_RESNAMES and residue != "HYP"
}
for _residue in ("SER", "CYS", "CYX", "CYM"):
    NATIVE_CHARMM_ATOM_RENAMES[_residue]["HG"] = "HG1"
NATIVE_CHARMM_ATOM_RENAMES["ILE"].update(
    {"CD1": "CD", "HD11": "HD1", "HD12": "HD2", "HD13": "HD3"}
)
# HYP has overlapping atom labels: choose the complete mapping by its oxygen
# alias rather than inverting individual names and accidentally moving HD1 twice.
NATIVE_CHARMM_HYP_RENAMES = {
    "HB3": "HB1", "OD1": "OE", "HD1": "HE", "HD22": "HD1", "HD23": "HD2",
}


def _standard_atom_names(
    source: str, target_residue: str, target: ForceFieldTarget, names: set[str],
) -> dict[str, tuple[str, NamingRuleId]]:
    """Normalize recognized native/PDB and GROMACS aliases without moving atoms."""
    renames: dict[str, str] = {}
    if target is ForceFieldTarget.CHARMM:
        parent = PROTONATION_CHARMM_TO_AMBER.get(target_residue, target_residue)
        renames.update(NATIVE_CHARMM_ATOM_RENAMES.get(parent, {}))
        if source == "LYN" and not ({"HZ1", "HZ2"} <= names and "HZ3" not in names):
            renames.update(PROTONATION_ATOM_RENAME_TO_CHARMM["LYN"])
        if source in PROTEIN_RESNAMES:
            renames["H"] = "HN"
            if parent in {"PRO", "HYP"}:
                renames.update({"H2": "HN1", "H3": "HN2", "H1": "HN2"})
            else:
                renames.update({"H1": "HT1", "H2": "HT2", "H3": "HT3"})
            if "OXT" in names or "OC1" in names:
                renames.update({"O": "OT1", "OXT": "OT2", "OC2": "OT1", "OC1": "OT2"})
        renames.update(GROMACS_CHARMM_CAP_ATOM_RENAMES.get(target_residue, {}))
        if parent == "HYP" and "OD1" in names:
            renames.update(NATIVE_CHARMM_HYP_RENAMES)
            renames["CD2"] = "CD"
            if "HD21" in names:
                renames.update({"HD21": "HD1", "HD22": "HD2"})
        rule = NamingRuleId.CHARMM_ATOM_NAME
    else:
        # Both bundled AMBER dialects converge on native AMBER in this profile.
        # The aliases are disjoint except for HYP, handled as a complete set.
        aliases = dict(GROMACS_AMBER_ATOM_RENAMES.get(target_residue, {}))
        aliases.update(NATIVE_CHARMM_ATOM_RENAMES.get(target_residue, {}))
        if target_residue == "HYP":
            aliases = {}
            if "OE" in names:
                aliases = NATIVE_CHARMM_HYP_RENAMES
            else:
                renames.update({"CD2": "CD", "HB1": "HB3"})
                if "HD21" in names:
                    renames.update({"HD21": "HD22", "HD22": "HD23"})
        renames.update({destination: origin for origin, destination in aliases.items()})
        if source in PROTEIN_RESNAMES:
            renames.update({
                "HN": "H", "OC1": "OXT", "OC2": "O", "OT1": "O", "OT2": "OXT",
                "HT1": "H1", "HT2": "H2", "HT3": "H3",
            })
            if target_residue in {"PRO", "HYP"}:
                renames.update({"HN1": "H2", "HN2": "H3", "H1": "H3"})
        renames.update({
            destination: origin
            for origin, destination in GROMACS_AMBER_NA_ATOM_RENAMES.get(source, {}).items()
        })
        if source == "LSN":
            renames.update(PROTONATION_ATOM_RENAME_TO_AMBER["LSN"])
        rule = NamingRuleId.AMBER_ATOM_NAME
    return {origin: (destination, rule) for origin, destination in renames.items()}


def target_residue_name(source_name: str, target: ForceFieldTarget) -> str:
    """Map a recognized source variant without inferring canonical protonation."""
    if target is ForceFieldTarget.CHARMM:
        return PROTONATION_AMBER_TO_CHARMM.get(source_name, source_name)
    return PROTONATION_CHARMM_TO_AMBER.get(source_name, source_name)


def atom_name_policy(
    *,
    source_residue_name: str,
    target_residue_name: str,
    target: ForceFieldTarget,
    profile: NamingProfile,
    atom_names: set[str],
    is_n_terminal: bool = False,
    is_c_terminal: bool = False,
) -> dict[str, tuple[str, NamingRuleId]]:
    """Return source-to-target atom names and the rule responsible for each."""
    if profile is NamingProfile.STANDARD:
        return _standard_atom_names(source_residue_name, target_residue_name, target, atom_names)
    result: dict[str, tuple[str, NamingRuleId]] = {}
    if target is ForceFieldTarget.CHARMM:
        already_target_lyn_pair = {"HZ1", "HZ2"} <= atom_names and "HZ3" not in atom_names
        if source_residue_name == "LYN" and not already_target_lyn_pair:
            result.update(
                {
                    source: (destination, NamingRuleId.CHARMM_ATOM_NAME)
                    for source, destination in PROTONATION_ATOM_RENAME_TO_CHARMM["LYN"].items()
                }
            )
        if profile is NamingProfile.GROMACS:
            result.update(
                {
                    source: (destination, NamingRuleId.CHARMM_ATOM_NAME)
                    for source, destination in GROMACS_CHARMM_CAP_ATOM_RENAMES.get(
                        target_residue_name, {}
                    ).items()
                }
            )
            if source_residue_name in PROTEIN_RESNAMES:
                result.setdefault(
                    "H", (CHARMM_UNIVERSAL_ATOM_RENAMES["H"], NamingRuleId.CHARMM_ATOM_NAME)
                )
        return result

    amber_atom_renames = (
        GROMACS_AMBER19SB_ATOM_RENAMES
        if target is ForceFieldTarget.AMBER19SB
        else GROMACS_AMBER_ATOM_RENAMES
    )
    result.update(
        {
            source: (destination, NamingRuleId.AMBER_ATOM_NAME)
            for source, destination in amber_atom_renames.get(
                target_residue_name, {}
            ).items()
        }
    )
    if is_n_terminal and target_residue_name in PROTEIN_RESNAMES:
        if target_residue_name in {"PRO", "HYP"} and "H3" in atom_names:
            result["H3"] = ("H1", NamingRuleId.TERMINAL_ATOM_NAME)
        elif "H" in atom_names and "H1" not in atom_names:
            result["H"] = ("H1", NamingRuleId.TERMINAL_ATOM_NAME)
    if (
        target is ForceFieldTarget.AMBER
        and is_c_terminal
        and target_residue_name in PROTEIN_RESNAMES
    ):
        if "O" in atom_names and "OXT" in atom_names:
            result["O"] = ("OC2", NamingRuleId.TERMINAL_ATOM_NAME)
            result["OXT"] = ("OC1", NamingRuleId.TERMINAL_ATOM_NAME)
    for source, destination in GROMACS_AMBER_NA_ATOM_RENAMES.get(
        source_residue_name, {}
    ).items():
        result.setdefault(source, (destination, NamingRuleId.NUCLEIC_ACID_ATOM_NAME))
    return result
