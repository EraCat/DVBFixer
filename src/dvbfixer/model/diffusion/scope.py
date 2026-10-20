"""Fail-closed scope admission for experimental diffusion requests."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from io import StringIO
from typing import NamedTuple

from openmm.app import PDBFile

from dvbfixer.ffutils.geometry import ChiralityError, assert_all_l
from dvbfixer.model.diffusion.contract import (
    AtomIdentity,
    DiffusionContractError,
    DiffusionRequest,
    ExplicitLink,
    GapKind,
    ResidueIdentity,
)
from dvbfixer.model.diffusion.gap_capabilities import gap_capability

MINIMUM_GAP_LENGTH = 3
MAXIMUM_GAP_LENGTH = 12

_CANONICAL_ONE_TO_THREE = {
    "A": "ALA",
    "C": "CYS",
    "D": "ASP",
    "E": "GLU",
    "F": "PHE",
    "G": "GLY",
    "H": "HIS",
    "I": "ILE",
    "K": "LYS",
    "L": "LEU",
    "M": "MET",
    "N": "ASN",
    "P": "PRO",
    "Q": "GLN",
    "R": "ARG",
    "S": "SER",
    "T": "THR",
    "V": "VAL",
    "W": "TRP",
    "Y": "TYR",
}
_CANONICAL_RESIDUES = frozenset(_CANONICAL_ONE_TO_THREE.values())
CANONICAL_HEAVY_ATOMS: dict[str, tuple[str, ...]] = {
    "ALA": ("N", "CA", "CB", "C", "O"),
    "ARG": (
        "N", "CA", "CB", "CG", "CD", "NE", "CZ", "NH1", "NH2", "C", "O",
    ),
    "ASN": ("N", "CA", "CB", "CG", "OD1", "ND2", "C", "O"),
    "ASP": ("N", "CA", "CB", "CG", "OD1", "OD2", "C", "O"),
    "CYS": ("N", "CA", "CB", "SG", "C", "O"),
    "GLN": ("N", "CA", "CB", "CG", "CD", "OE1", "NE2", "C", "O"),
    "GLU": ("N", "CA", "CB", "CG", "CD", "OE1", "OE2", "C", "O"),
    "GLY": ("N", "CA", "C", "O"),
    "HIS": (
        "N", "CA", "CB", "CG", "ND1", "CE1", "NE2", "CD2", "C", "O",
    ),
    "ILE": ("N", "CA", "CB", "CG2", "CG1", "CD1", "C", "O"),
    "LEU": ("N", "CA", "CB", "CG", "CD1", "CD2", "C", "O"),
    "LYS": ("N", "CA", "CB", "CG", "CD", "CE", "NZ", "C", "O"),
    "MET": ("N", "CA", "CB", "CG", "SD", "CE", "C", "O"),
    "PHE": (
        "N", "CA", "CB", "CG", "CD1", "CE1", "CZ", "CE2", "CD2", "C", "O",
    ),
    "PRO": ("N", "CD", "CG", "CB", "CA", "C", "O"),
    "SER": ("N", "CA", "CB", "OG", "C", "O"),
    "THR": ("N", "CA", "CB", "CG2", "OG1", "C", "O"),
    "TRP": (
        "N", "CA", "CB", "CG", "CD1", "NE1", "CE2", "CZ2", "CH2", "CZ3",
        "CE3", "CD2", "C", "O",
    ),
    "TYR": (
        "N", "CA", "CB", "CG", "CD1", "CE1", "CZ", "OH", "CE2", "CD2", "C", "O",
    ),
    "VAL": ("N", "CA", "CB", "CG1", "CG2", "C", "O"),
}


def canonical_heavy_atom_identities(
    residue: ResidueIdentity,
    residue_name: str,
) -> tuple[AtomIdentity, ...]:
    """Return the complete canonical heavy-atom identity set in template order."""
    try:
        atom_names = CANONICAL_HEAVY_ATOMS[residue_name]
    except KeyError as exc:
        raise ValueError(f"unknown canonical residue name: {residue_name}") from exc
    return tuple(
        AtomIdentity(
            residue.chain,
            residue.residue_number,
            residue.insertion_code,
            atom_name,
        )
        for atom_name in atom_names
    )


class DiffusionScopeError(RuntimeError):
    """Raised when the normalized input cannot be admitted or rejected safely."""


class _CoordinateRecord(NamedTuple):
    record_name: str
    identity: AtomIdentity
    residue_name: str
    element: str


@dataclass(frozen=True, slots=True)
class ScopeAdmission:
    """Scientific scope decision made before an external runner is launched."""

    supported: bool
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.supported and self.reasons:
            raise ValueError("supported scope admission cannot contain reasons")
        if not self.supported and not self.reasons:
            raise ValueError("unsupported scope admission must contain a reason")


def assess_diffusion_scope(
    request: DiffusionRequest,
    normalized_pdb: bytes,
) -> ScopeAdmission:
    """Return whether a verified normalized PDB is inside the initial slice.

    The byte payload is checked against ``request.normalized_pdb.sha256`` before
    parsing. Malformed or unverifiable inputs raise :class:`DiffusionScopeError`;
    scientifically out-of-scope inputs return a stable unsupported decision.
    """
    digest = hashlib.sha256(normalized_pdb).hexdigest()
    if digest != request.normalized_pdb.sha256.lower():
        raise DiffusionScopeError("normalized PDB SHA-256 does not match the request")
    if request.protein_context is not None:
        from dvbfixer.model.diffusion.protein_context import (
            ProteinContextError,
            validate_context_source,
        )

        try:
            validate_context_source(request, normalized_pdb)
        except ProteinContextError as exc:
            raise DiffusionScopeError(str(exc)) from exc
    try:
        text = normalized_pdb.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DiffusionScopeError("normalized PDB is not valid UTF-8") from exc

    reasons: list[str] = []
    from dvbfixer.model.diffusion.protein_context import (
        ProteinContextError,
        is_cuda_cc89,
        validate_context_capability,
    )

    if is_cuda_cc89(request):
        try:
            validate_context_capability(request, "protpardelle")
        except ProteinContextError:
            reasons.append("cuda-cc89-profile-scope-mismatch")
    if request.protein_context is not None and request.protein_context.policy.name == "intact-native-segments-v1":
        reasons.append("intact-native-segments-research-only")
    if request.protein_context is not None and request.protein_context.policy.name == "atom37-terminal-preservation-v1" and not is_cuda_cc89(request):
        reasons.append("atom37-terminal-preservation-research-only")
    if request.protein_context is not None and request.protein_context.trajectory_queries is not None:
        reasons.append("trajectory-adaptive-context-research-only")
    requested_profile = next(
        (
            option.value
            for option in request.backend_options
            if option.name == "profile"
        ),
        "",
    )
    if any(gap.gap_kind is not GapKind.INTERNAL for gap in request.gaps) and not (
        requested_profile.startswith("protpardelle-1c")
    ):
        reasons.append("terminal-gaps-unsupported-by-profile")
    if request.heterogen_contexts and not requested_profile.startswith(
        "protpardelle-1c"
    ):
        reasons.append("heterogen-conditioning-unsupported-by-profile")
    lines = text.splitlines()
    if sum(line.startswith("MODEL ") for line in lines) > 1:
        reasons.append("multiple-models")

    sequences = {target.chain: target.sequence for target in request.target_sequences}
    if any(
        one_letter not in _CANONICAL_ONE_TO_THREE
        for sequence in sequences.values()
        for one_letter in sequence
    ):
        reasons.append("non-canonical-target-sequence")

    if "multiple-models" in reasons:
        model_start = next(
            (index for index, line in enumerate(lines) if line.startswith("MODEL ")),
            0,
        )
        model_stop = next(
            (
                index
                for index, line in enumerate(lines[model_start + 1 :], model_start + 1)
                if line.startswith("ENDMDL")
            ),
            len(lines),
        )
        coordinate_lines = lines[model_start + 1 : model_stop]
    else:
        coordinate_lines = lines
    atoms, residue_names, altloc_residues = _parse_coordinate_records(
        coordinate_lines
    )
    source_explicit_links = _parse_explicit_links(coordinate_lines, atoms)
    if any(
        gap.gap_kind is GapKind.INTERNAL
        and gap.left_anchor is not None
        and gap.right_anchor is not None
        and _has_ter_between_anchors(coordinate_lines, gap.left_anchor, gap.right_anchor)
        for gap in request.gaps
    ):
        reasons.append("terminator-between-gap-anchors")
    generated_residues = {
        residue
        for gap in request.gaps
        for residue in gap.generated_residues
    }
    context_atoms = {
        atom for context in request.heterogen_contexts for atom in context.atoms
    }
    context_residues = {context.residue for context in request.heterogen_contexts}
    movable_residues = {
        residue
        for gap in request.gaps
        for residue in gap.movable_junction_residues
    }

    if any(
        not (
            (record_name == "ATOM" and residue_name in _CANONICAL_RESIDUES)
            or (record_name == "HETATM" and identity in context_atoms)
        )
        for record_name, identity, residue_name, _element in atoms
    ):
        reasons.append("retained-heterogen-or-noncanonical-residue")
    observed_context_residues = {
        _residue(record.identity)
        for record in atoms
        if record.record_name == "HETATM" and record.identity in context_atoms
    }
    if observed_context_residues != context_residues:
        reasons.append("heterogen-context-identity-mismatch")
    if altloc_residues & movable_residues:
        reasons.append("adjacent-alternate-location-ambiguity")
    if generated_residues & set(residue_names):
        reasons.append("generated-residue-present-in-input")

    source_atoms = {record.identity for record in atoms}
    expected_fixed_atoms = {
        record.identity
        for record in atoms
        if _residue(record.identity) not in generated_residues
        and record.element != "H"
    }
    if set(request.fixed_atoms) != expected_fixed_atoms:
        reasons.append("fixed-atom-mask-mismatch")
    generated_atom_names = {
        residue: {
            identity.atom_name
            for identity in request.generated_atoms
            if _residue(identity) == residue
        }
        for residue in generated_residues
    }
    expected_generated_atom_names: dict[ResidueIdentity, set[str]] = {}
    for gap in request.gaps:
        sequence = sequences[gap.chain]
        for target_index, residue in zip(
            range(gap.target_interval.start, gap.target_interval.stop),
            gap.generated_residues,
        ):
            residue_name = _CANONICAL_ONE_TO_THREE.get(sequence[target_index])
            expected_generated_atom_names[residue] = (
                set(CANONICAL_HEAVY_ATOMS[residue_name])
                if residue_name is not None
                else set()
            )
    if (
        not request.generated_atoms
        or any(
            _residue(identity) not in generated_residues
            for identity in request.generated_atoms
        )
        or generated_atom_names != expected_generated_atom_names
    ):
        reasons.append("generated-atom-mask-mismatch")

    placement_indices: dict[ResidueIdentity, int] = {}
    placement_matches = True
    for placement in request.sequence_placements:
        sequence = sequences[placement.chain]
        source_chain_residues = {
            _residue(record.identity)
            for record in atoms
            if record.record_name == "ATOM"
            and record.identity.chain == placement.chain
        }
        if set(placement.observed_residues) != source_chain_residues:
            placement_matches = False
        for index, residue in zip(
            placement.observed_target_indices,
            placement.observed_residues,
        ):
            placement_indices[residue] = index
            residue_name = residue_names.get(residue)
            expected_name = _CANONICAL_ONE_TO_THREE.get(sequence[index])
            if residue_name is None or residue_name != expected_name:
                placement_matches = False
    if not placement_matches:
        reasons.append("observed-sequence-placement-mismatch")

    for placement in request.sequence_placements:
        generated_target_indices = {
            index
            for gap in request.gaps
            if gap.chain == placement.chain
            for index in range(
                gap.target_interval.start,
                gap.target_interval.stop,
            )
        }
        observed_target_indices = set(placement.observed_target_indices)
        if (
            observed_target_indices & generated_target_indices
            or observed_target_indices | generated_target_indices
            != set(range(placement.target_length))
        ):
            reasons.append("sequence-placement-gap-coverage-mismatch")

    for gap in request.gaps:
        gap_length = gap.target_interval.stop - gap.target_interval.start
        if not gap_capability(requested_profile, gap_length).accepted:
            reasons.append("unsupported-gap-length")
        left_matches = (
            gap.left_anchor is not None
            and placement_indices.get(gap.left_anchor)
            == gap.target_interval.start - 1
        )
        right_matches = (
            gap.right_anchor is not None
            and placement_indices.get(gap.right_anchor) == gap.target_interval.stop
        )
        anchors_match = (
            left_matches and right_matches
            if gap.gap_kind is GapKind.INTERNAL
            else right_matches
            if gap.gap_kind is GapKind.N_TERMINAL
            else left_matches
        )
        if not anchors_match:
            reasons.append("gap-anchor-placement-mismatch")

    requested_explicit_links = {
        _link_key(link)
        for link in request.retained_explicit_links
    }
    if any(
        link.atom1 not in source_atoms or link.atom2 not in source_atoms
        for link in request.retained_explicit_links
    ):
        reasons.append("retained-explicit-link-atom-missing")
    if requested_explicit_links != source_explicit_links:
        reasons.append("retained-explicit-link-mismatch")
    if any(
        _link_is_unsupported_near_gap(link, movable_residues, placement_indices)
        for link in request.retained_explicit_links
    ):
        reasons.append("external-covalent-link-near-generated-region")

    if "multiple-models" not in reasons and not any(
        reason in reasons
        for reason in (
            "retained-heterogen-or-noncanonical-residue",
            "adjacent-alternate-location-ambiguity",
        )
    ):
        try:
            pdb = PDBFile(StringIO(text))
            assert_all_l(pdb.topology, pdb.positions)
        except ChiralityError:
            reasons.append("detectable-d-ca-chirality")
        except Exception as exc:
            raise DiffusionScopeError("normalized PDB could not be parsed by OpenMM") from exc

    unique_reasons = tuple(dict.fromkeys(reasons))
    if unique_reasons:
        return ScopeAdmission(supported=False, reasons=unique_reasons)
    return ScopeAdmission(supported=True)


def _parse_coordinate_records(
    lines: list[str],
) -> tuple[
    list[_CoordinateRecord],
    dict[ResidueIdentity, str],
    set[ResidueIdentity],
]:
    atoms: list[_CoordinateRecord] = []
    residue_names: dict[ResidueIdentity, str] = {}
    altloc_residues: set[ResidueIdentity] = set()
    seen_atoms: dict[AtomIdentity, str] = {}
    for line_number, line in enumerate(lines, 1):
        record_name = line[:6].strip()
        if record_name not in {"ATOM", "HETATM"}:
            continue
        if len(line) < 54:
            raise DiffusionScopeError(
                f"truncated PDB coordinate record on line {line_number}"
            )
        residue_number = line[22:26].strip()
        try:
            int(line[6:11])
            int(residue_number)
            coordinates = (
                float(line[30:38]),
                float(line[38:46]),
                float(line[46:54]),
            )
        except ValueError as exc:
            raise DiffusionScopeError(
                f"malformed PDB coordinate record on line {line_number}"
            ) from exc
        if not all(math.isfinite(value) for value in coordinates):
            raise DiffusionScopeError(
                f"non-finite PDB coordinate on line {line_number}"
            )
        atom_name = line[12:16].strip()
        residue_name = line[17:20].strip()
        if not atom_name or not residue_name:
            raise DiffusionScopeError(
                f"missing atom or residue name on line {line_number}"
            )
        residue = ResidueIdentity(
            line[21],
            residue_number,
            line[26].strip(),
        )
        identity = AtomIdentity(
            residue.chain,
            residue.residue_number,
            residue.insertion_code,
            atom_name,
        )
        altloc = line[16].strip()
        if altloc:
            altloc_residues.add(residue)
        if identity in seen_atoms:
            if altloc or seen_atoms[identity]:
                altloc_residues.add(residue)
                continue
            raise DiffusionScopeError(
                f"duplicate atom identity on line {line_number}"
            )
        seen_atoms[identity] = altloc
        previous_name = residue_names.setdefault(residue, residue_name)
        if previous_name != residue_name:
            raise DiffusionScopeError(
                f"conflicting residue name on line {line_number}"
            )
        element = line[76:78].strip() if len(line) >= 78 else ""
        if not element:
            element = next(
                (character for character in atom_name if character.isalpha()),
                "",
            )
        atoms.append(
            _CoordinateRecord(
                record_name,
                identity,
                residue_name,
                element.upper(),
            )
        )
    if not atoms:
        raise DiffusionScopeError("normalized PDB contains no coordinate records")
    return atoms, residue_names, altloc_residues


def _parse_explicit_links(
    lines: list[str],
    atoms: list[_CoordinateRecord],
) -> set[tuple[AtomIdentity, AtomIdentity]]:
    source_atoms = {record.identity for record in atoms}
    serials: dict[int, AtomIdentity] = {}
    for line in lines:
        if line[:6].strip() not in {"ATOM", "HETATM"}:
            continue
        try:
            serials[int(line[6:11])] = AtomIdentity(
                line[21],
                line[22:26].strip(),
                line[26].strip(),
                line[12:16].strip(),
            )
        except (DiffusionContractError, ValueError):
            continue

    links: set[tuple[AtomIdentity, AtomIdentity]] = set()
    for line in lines:
        if line.startswith("CONECT"):
            serial_values: list[int] = []
            malformed = False
            remainder = line[6:]
            while len(remainder) >= 5:
                chunk = remainder[:5].strip()
                remainder = remainder[5:]
                if not chunk:
                    continue
                try:
                    serial_values.append(int(chunk))
                except ValueError:
                    malformed = True
                    break
            if (
                malformed
                or len(serial_values) < 2
                or any(serial not in serials for serial in serial_values)
            ):
                continue
            source = serials[serial_values[0]]
            for serial in serial_values[1:]:
                target = serials.get(serial)
                if target is not None and target != source:
                    first, second = sorted((source, target))
                    links.add((first, second))
        elif line.startswith("LINK") and len(line) >= 57:
            first = AtomIdentity(
                line[21],
                line[22:26].strip(),
                line[26].strip(),
                line[12:16].strip(),
            )
            second = AtomIdentity(
                line[51],
                line[52:56].strip(),
                line[56].strip(),
                line[42:46].strip(),
            )
            if first in source_atoms and second in source_atoms and first != second:
                first, second = sorted((first, second))
                links.add((first, second))
        elif line.startswith("SSBOND") and len(line) >= 36:
            first = AtomIdentity(
                line[15],
                line[17:21].strip(),
                line[21].strip(),
                "SG",
            )
            second = AtomIdentity(
                line[29],
                line[31:35].strip(),
                line[35].strip(),
                "SG",
            )
            if first in source_atoms and second in source_atoms and first != second:
                first, second = sorted((first, second))
                links.add((first, second))
    return links


def _has_ter_between_anchors(
    lines: list[str],
    left_anchor: ResidueIdentity,
    right_anchor: ResidueIdentity,
) -> bool:
    left_seen = False
    for line in lines:
        if line.startswith("TER") and left_seen:
            return True
        if line[:6].strip() not in {"ATOM", "HETATM"} or len(line) < 27:
            continue
        residue = ResidueIdentity(line[21], line[22:26].strip(), line[26].strip())
        if residue == right_anchor:
            return False
        if residue == left_anchor:
            left_seen = True
    return False


def _link_key(
    link: ExplicitLink,
) -> tuple[AtomIdentity, AtomIdentity]:
    first, second = sorted((link.atom1, link.atom2))
    return first, second


def _link_is_unsupported_near_gap(
    link: ExplicitLink,
    movable_residues: set[ResidueIdentity],
    placement_indices: dict[ResidueIdentity, int],
) -> bool:
    first_residue = _residue(link.atom1)
    second_residue = _residue(link.atom2)
    if first_residue not in movable_residues and second_residue not in movable_residues:
        return False
    if link.atom1.chain != link.atom2.chain:
        return True
    atom_names = {link.atom1.atom_name, link.atom2.atom_name}
    if atom_names != {"C", "N"}:
        return True
    first_index = placement_indices.get(first_residue)
    second_index = placement_indices.get(second_residue)
    if first_index is None or second_index is None:
        return True
    return abs(first_index - second_index) != 1


def _residue(atom: AtomIdentity) -> ResidueIdentity:
    return ResidueIdentity(atom.chain, atom.residue_number, atom.insertion_code)
