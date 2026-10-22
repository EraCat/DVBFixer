"""Pure application service for PDB force-field naming conversion."""

from __future__ import annotations

from dataclasses import dataclass, field

from dvbfixer.domain.force_field_naming import (
    AMBER_VARIANTS,
    CHARMM_VARIANTS,
    TERMINAL_CHAIN_RESNAMES,
    ForceFieldTarget,
    NamingConversionError,
    NamingErrorCode,
    NamingProfile,
    NamingRuleId,
    ResidueIdentity,
    VariantOverride,
    atom_name_policy,
    target_residue_name,
)
from dvbfixer.domain.protonation_identity import identify_protonation


@dataclass(frozen=True, slots=True)
class NamingConversionRequest:
    pdb_text: str
    target: ForceFieldTarget
    profile: NamingProfile = NamingProfile.GROMACS
    variant_overrides: tuple[VariantOverride, ...] = field(default_factory=tuple)
    infer_protonation: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.infer_protonation, bool):
            raise TypeError("infer_protonation must be a bool")
        try:
            if not isinstance(self.target, ForceFieldTarget):
                object.__setattr__(self, "target", ForceFieldTarget(self.target))
            if not isinstance(self.profile, NamingProfile):
                object.__setattr__(self, "profile", NamingProfile(self.profile))
        except ValueError as exc:
            raise NamingConversionError(
                NamingErrorCode.UNSUPPORTED_NAMING_DIRECTION,
                "Unsupported force-field naming target or profile",
                details={"target": str(self.target), "profile": str(self.profile)},
            ) from exc
        if any(not isinstance(override, VariantOverride) for override in self.variant_overrides):
            raise TypeError("variant_overrides must contain VariantOverride values")
        identities = [override.residue for override in self.variant_overrides]
        if len(identities) != len(set(identities)):
            raise NamingConversionError(
                NamingErrorCode.AMBIGUOUS_VARIANT,
                "variant_overrides contains duplicate residue identities",
            )


@dataclass(frozen=True, slots=True)
class CoordinateNamingChange:
    model: int
    chain: str
    residue_number: str
    insertion_code: str
    alternate_location: str
    atom_serial: int
    source_residue_name: str
    target_residue_name: str
    source_atom_name: str
    target_atom_name: str
    rule_ids: tuple[NamingRuleId, ...]


@dataclass(frozen=True, slots=True)
class NamingConversionSummary:
    changed_atoms: int
    changed_residues: int
    variant_changes: int
    atom_name_changes: int


@dataclass(frozen=True, slots=True)
class NamingDiagnostic:
    code: str
    message: str
    residue: ResidueIdentity | None = None


@dataclass(frozen=True, slots=True)
class NamingConversionResult:
    pdb_text: str
    model: int
    changes: tuple[CoordinateNamingChange, ...]
    summary: NamingConversionSummary
    diagnostics: tuple[NamingDiagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class _AtomRecord:
    line_index: int
    model: int
    serial: int
    atom_name: str
    altloc: str
    residue_name: str
    identity: ResidueIdentity


def _malformed(line_index: int, record: str, reason: str) -> NamingConversionError:
    return NamingConversionError(
        NamingErrorCode.MALFORMED_PDB,
        f"Malformed {record} record on line {line_index + 1}: {reason}",
        details={"line": line_index + 1, "record": record, "reason": reason},
    )


def _parse_model_number(line: str, line_index: int) -> int:
    try:
        return int(line[10:14].strip())
    except (ValueError, IndexError) as exc:
        raise _malformed(line_index, "MODEL", "missing model number") from exc


def _residue_name(line: str) -> str:
    candidate = line[17:21].strip()
    if line[20:21].strip() and candidate in CHARMM_VARIANTS:
        return candidate
    return line[17:20].strip()


def _parse_atom_record(line: str, line_index: int, model: int) -> _AtomRecord:
    record = line[:6].strip()
    if len(line.rstrip("\r\n")) < 27:
        raise _malformed(line_index, record, "record is shorter than 27 columns")
    try:
        serial = int(line[6:11].strip())
        residue_number = line[22:26].strip()
        int(residue_number)
    except ValueError as exc:
        raise _malformed(line_index, record, "invalid atom serial or residue number") from exc
    atom_name = line[12:16].strip()
    residue_name = _residue_name(line)
    if not atom_name or not residue_name:
        raise _malformed(line_index, record, "missing atom or residue name")
    return _AtomRecord(
        line_index=line_index,
        model=model,
        serial=serial,
        atom_name=atom_name,
        altloc=line[16].strip(),
        residue_name=residue_name,
        identity=ResidueIdentity(line[21], residue_number, line[26].strip()),
    )


def _format_atom_name(name: str) -> str:
    return name[:4] if len(name) >= 4 else f" {name:<3s}"


def _rewrite_labels(
    line: str,
    source_atom: str,
    target_atom: str,
    source_residue: str,
    target_residue: str,
) -> str:
    if source_atom != target_atom:
        line = line[:12] + _format_atom_name(target_atom) + line[16:]
    if source_residue == target_residue:
        return line
    if len(target_residue) <= 3:
        return line[:17] + f"{target_residue:<3s}" + " " + line[21:]
    return line[:17] + target_residue[:4] + line[21:]


def _terminal_positions(atoms: list[_AtomRecord]) -> dict[tuple[int, ResidueIdentity], set[str]]:
    per_chain: dict[tuple[int, str], list[ResidueIdentity]] = {}
    seen: set[tuple[int, ResidueIdentity]] = set()
    for atom in atoms:
        key = (atom.model, atom.identity)
        if atom.residue_name not in TERMINAL_CHAIN_RESNAMES or key in seen:
            continue
        seen.add(key)
        per_chain.setdefault((atom.model, atom.identity.chain), []).append(atom.identity)
    result: dict[tuple[int, ResidueIdentity], set[str]] = {}
    for (model, _chain), residues in per_chain.items():
        result.setdefault((model, residues[0]), set()).add("nter")
        result.setdefault((model, residues[-1]), set()).add("cter")
    return result


def _target_for_atom(
    atom: _AtomRecord,
    request: NamingConversionRequest,
    overrides: dict[ResidueIdentity, str],
    residue_atoms: dict[tuple[int, ResidueIdentity, str], set[str]],
    terminals: dict[tuple[int, ResidueIdentity], set[str]],
    inferred: dict[ResidueIdentity, str],
) -> tuple[str, str, tuple[NamingRuleId, ...]]:
    explicit = overrides.get(atom.identity)
    observed = inferred.get(atom.identity)
    source_variant = explicit or observed or atom.residue_name
    new_residue = target_residue_name(source_variant, request.target)
    rules: list[NamingRuleId] = []
    if explicit is not None and new_residue != atom.residue_name:
        rules.append(NamingRuleId.EXPLICIT_VARIANT)
    elif observed is not None and new_residue != atom.residue_name:
        rules.append(NamingRuleId.OBSERVED_PROTONATION)
    elif explicit is None and source_variant in AMBER_VARIANTS | CHARMM_VARIANTS and new_residue != atom.residue_name:
        rules.append(NamingRuleId.SOURCE_VARIANT)

    atom_key = (atom.model, atom.identity, atom.altloc)
    atoms_here = residue_atoms[atom_key]
    if atom.identity in inferred:
        # Blank-altloc atoms belong to each conformer. In particular, a LYN
        # HZ1/HZ2 pair split between shared and alternate records is still one
        # complete pair for atom-name policy, not two incomplete singletons.
        altloc = atom.altloc or next((key[2] for key in residue_atoms if key[:2] == atom_key[:2] and key[2]), "")
        atoms_here = residue_atoms.get((atom.model, atom.identity, ""), set()) | residue_atoms.get((atom.model, atom.identity, altloc), set())
    terminal = terminals.get((atom.model, atom.identity), set())
    atom_policy = atom_name_policy(
        source_residue_name=source_variant,
        target_residue_name=new_residue,
        target=request.target,
        profile=request.profile,
        atom_names=atoms_here,
        is_n_terminal="nter" in terminal,
        is_c_terminal="cter" in terminal,
    )
    new_atom, atom_rule = atom_policy.get(atom.atom_name, (atom.atom_name, None))
    if new_atom != atom.atom_name:
        assert atom_rule is not None
        rules.append(atom_rule)
    return new_residue, new_atom, tuple(dict.fromkeys(rules))


def _identify_observed_variants(
    atoms: list[_AtomRecord], lines: list[str], overrides: dict[ResidueIdentity, str],
) -> tuple[dict[ResidueIdentity, str], list[NamingDiagnostic]]:
    grouped: dict[ResidueIdentity, list[_AtomRecord]] = {}
    for atom in atoms:
        grouped.setdefault(atom.identity, []).append(atom)
    inferred: dict[ResidueIdentity, str] = {}
    diagnostics: list[NamingDiagnostic] = []
    for identity, records in grouped.items():
        if identity in overrides:
            continue  # User-specified chemistry is authoritative.
        source_names = {atom.residue_name for atom in records}
        if len(source_names) != 1:
            diagnostics.append(NamingDiagnostic("PROTONATION_UNRESOLVED", "Mixed residue names; no H-based inference", identity))
            continue
        source = next(iter(source_names))
        conformers = {atom.altloc for atom in records if atom.altloc} or {""}
        decisions = []
        hydrogen_patterns: set[frozenset[str]] = set()
        for conformer in sorted(conformers):
            selected = [atom for atom in records if atom.altloc in {"", conformer}]
            hydrogens = set()
            for atom in selected:
                element = lines[atom.line_index][76:78].strip().upper()
                name = atom.atom_name
                if element in {"H", "D"} or (not element and name.lstrip("123").startswith(("H", "D"))):
                    if name[0].isdigit():
                        name = name[1:] + name[0]
                    if name.startswith("D"):
                        name = "H" + name[1:]
                    hydrogens.add(name)
            decision = identify_protonation(source, {atom.atom_name for atom in selected}, hydrogens)
            if decision is not None:
                decisions.append(decision)
                hydrogen_patterns.add(frozenset(hydrogens))
        if not decisions:
            continue
        if len({decision.residue_name for decision in decisions}) != 1 or len(hydrogen_patterns) > 1:
            diagnostics.append(NamingDiagnostic(
                "PROTONATION_UNRESOLVED", "Alternate conformers disagree on observed H or protonation; retaining name-derived state", identity,
            ))
            continue
        decision = decisions[0]
        for warning in sorted({item.warning for item in decisions if item.warning}):
            diagnostics.append(NamingDiagnostic(
                "PROTONATION_CONFLICT" if all(item.from_hydrogens for item in decisions) else "PROTONATION_UNRESOLVED",
                warning, identity,
            ))
        if all(item.from_hydrogens for item in decisions):
            diagnostics.append(NamingDiagnostic("PROTONATION_IDENTIFIED", f"Observed site H identify {decision.residue_name}", identity))
            if target_residue_name(source, ForceFieldTarget.AMBER) != decision.residue_name:
                inferred[identity] = decision.residue_name
    return inferred, diagnostics


def convert_force_field_naming(request: NamingConversionRequest) -> NamingConversionResult:
    """Convert PDB naming and return converted text plus a structured report."""
    lines = request.pdb_text.splitlines(keepends=True)
    model_lines = [
        (index, line) for index, line in enumerate(lines) if line[:6].strip() == "MODEL"
    ]
    if len(model_lines) > 1:
        raise NamingConversionError(
            NamingErrorCode.MULTI_MODEL_UNSUPPORTED,
            "PDB naming conversion supports at most one MODEL block",
            details={"model_count": len(model_lines)},
        )
    reported_model = _parse_model_number(model_lines[0][1], model_lines[0][0]) if model_lines else 1

    atoms: list[_AtomRecord] = []
    anisou: list[_AtomRecord] = []
    current_model = reported_model
    for index, line in enumerate(lines):
        record_name = line[:6].strip()
        if record_name == "MODEL":
            current_model = _parse_model_number(line, index)
        elif record_name in {"ATOM", "HETATM"}:
            atoms.append(_parse_atom_record(line, index, current_model))
        elif record_name == "ANISOU":
            anisou.append(_parse_atom_record(line, index, current_model))

    source_identities: dict[tuple[int, ResidueIdentity, str, str], int] = {}
    coordinate_serials: dict[tuple[int, int], int] = {}
    for atom in atoms:
        source_key = (atom.model, atom.identity, atom.altloc, atom.atom_name)
        previous_line = source_identities.setdefault(source_key, atom.line_index)
        if previous_line != atom.line_index:
            raise NamingConversionError(
                NamingErrorCode.NAMING_COLLISION,
                "Duplicate source atom identity",
                details={
                    "model": atom.model,
                    "chain": atom.identity.chain,
                    "residue_number": atom.identity.residue_number,
                    "insertion_code": atom.identity.insertion_code,
                    "alternate_location": atom.altloc,
                    "atom_name": atom.atom_name,
                    "lines": [previous_line + 1, atom.line_index + 1],
                },
            )
        serial_key = (atom.model, atom.serial)
        previous_line = coordinate_serials.setdefault(serial_key, atom.line_index)
        if previous_line != atom.line_index:
            raise _malformed(
                atom.line_index,
                "ATOM/HETATM",
                f"duplicate atom serial {atom.serial} in model {atom.model}",
            )

    anisou_serials: dict[tuple[int, int], int] = {}
    for record in anisou:
        serial_key = (record.model, record.serial)
        previous_line = anisou_serials.setdefault(serial_key, record.line_index)
        if previous_line != record.line_index:
            raise _malformed(
                record.line_index,
                "ANISOU",
                f"duplicate atom serial {record.serial} in model {record.model}",
            )

    residue_atoms: dict[tuple[int, ResidueIdentity, str], set[str]] = {}
    for atom in atoms:
        residue_atoms.setdefault((atom.model, atom.identity, atom.altloc), set()).add(atom.atom_name)
    terminals = _terminal_positions(atoms) if request.profile is NamingProfile.GROMACS else {}
    overrides = {
        override.residue: override.variant_name for override in request.variant_overrides
    }
    inferred, diagnostics = _identify_observed_variants(atoms, lines, overrides) if request.infer_protonation else ({}, [])

    for (model, identity, altloc), atom_names in residue_atoms.items():
        source_residue_name = next(
            atom.residue_name
            for atom in atoms
            if atom.model == model and atom.identity == identity and atom.altloc == altloc
        )
        source_variant = overrides.get(identity) or inferred.get(identity) or source_residue_name
        if (
            request.target is ForceFieldTarget.CHARMM
            and source_variant == "LYN"
            and {"HZ1", "HZ3"} <= atom_names
        ):
            raise NamingConversionError(
                NamingErrorCode.NAMING_COLLISION,
                "LYN contains a mixed source/target hydrogen naming set",
                details={
                    "model": model,
                    "chain": identity.chain,
                    "residue_number": identity.residue_number,
                    "insertion_code": identity.insertion_code,
                    "alternate_location": altloc,
                    "source_atom_names": sorted(atom_names & {"HZ1", "HZ2", "HZ3"}),
                },
            )

    planned: dict[int, tuple[str, str, tuple[NamingRuleId, ...]]] = {}
    collision_groups: dict[tuple[int, ResidueIdentity, str, str], set[str]] = {}
    for atom in atoms:
        target_residue, target_atom, rule_ids = _target_for_atom(
            atom, request, overrides, residue_atoms, terminals, inferred
        )
        planned[atom.line_index] = (target_residue, target_atom, rule_ids)
        collision_groups.setdefault(
            (atom.model, atom.identity, atom.altloc, target_atom), set()
        ).add(atom.atom_name)
    for (model, identity, altloc, target_atom), sources in collision_groups.items():
        if len(sources) > 1:
            raise NamingConversionError(
                NamingErrorCode.NAMING_COLLISION,
                "Different source atom names resolve to the same target atom name",
                details={
                    "model": model,
                    "chain": identity.chain,
                    "residue_number": identity.residue_number,
                    "insertion_code": identity.insertion_code,
                    "alternate_location": altloc,
                    "target_atom_name": target_atom,
                    "source_atom_names": sorted(sources),
                },
            )

    output = list(lines)
    changes: list[CoordinateNamingChange] = []
    residue_targets: dict[tuple[int, ResidueIdentity], tuple[str, str]] = {}
    serial_targets: dict[tuple[int, int], tuple[_AtomRecord, str, str]] = {}
    for atom in atoms:
        target_residue, target_atom, rule_ids = planned[atom.line_index]
        residue_targets[(atom.model, atom.identity)] = (atom.residue_name, target_residue)
        serial_targets[(atom.model, atom.serial)] = (atom, target_atom, target_residue)
        if target_residue == atom.residue_name and target_atom == atom.atom_name:
            continue
        output[atom.line_index] = _rewrite_labels(
            lines[atom.line_index], atom.atom_name, target_atom, atom.residue_name, target_residue
        )
        changes.append(
            CoordinateNamingChange(
                model=atom.model,
                chain=atom.identity.chain,
                residue_number=atom.identity.residue_number,
                insertion_code=atom.identity.insertion_code,
                alternate_location=atom.altloc,
                atom_serial=atom.serial,
                source_residue_name=atom.residue_name,
                target_residue_name=target_residue,
                source_atom_name=atom.atom_name,
                target_atom_name=target_atom,
                rule_ids=rule_ids,
            )
        )

    for record in anisou:
        target = serial_targets.get((record.model, record.serial))
        if target is None:
            continue
        source, target_atom, target_residue = target
        if (
            record.atom_name != source.atom_name
            or record.altloc != source.altloc
            or record.residue_name != source.residue_name
            or record.identity != source.identity
        ):
            raise _malformed(
                record.line_index,
                "ANISOU",
                f"labels do not match coordinate record for serial {record.serial}",
            )
        output[record.line_index] = _rewrite_labels(
            lines[record.line_index],
            source.atom_name,
            target_atom,
            source.residue_name,
            target_residue,
        )

    for index, line in enumerate(lines):
        if line[:6].strip() != "TER" or len(line.rstrip("\r\n")) < 27:
            continue
        try:
            residue_number = line[22:26].strip()
            int(residue_number)
            identity = ResidueIdentity(line[21], residue_number, line[26].strip())
        except (ValueError, IndexError):
            continue
        source_target = residue_targets.get((reported_model, identity))
        if source_target is None or source_target[0] == source_target[1]:
            continue
        source_residue, target_residue = source_target
        output[index] = _rewrite_labels(line, "", "", source_residue, target_residue)

    changed_residues = {
        (change.model, change.chain, change.residue_number, change.insertion_code)
        for change in changes
    }
    variant_residues = {
        (change.model, change.chain, change.residue_number, change.insertion_code)
        for change in changes
        if change.source_residue_name != change.target_residue_name
    }
    return NamingConversionResult(
        pdb_text="".join(output),
        model=reported_model,
        changes=tuple(changes),
        diagnostics=tuple(diagnostics),
        summary=NamingConversionSummary(
            changed_atoms=len(changes),
            changed_residues=len(changed_residues),
            variant_changes=len(variant_residues),
            atom_name_changes=sum(
                change.source_atom_name != change.target_atom_name for change in changes
            ),
        ),
    )
