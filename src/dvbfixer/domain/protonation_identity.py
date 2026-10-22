"""Identify supported residue states from names and explicitly observed H atoms.

This is not a pKa predictor or a hydrogen-completion service. Missing atoms are
not evidence of a different charge state, especially for cysteine/disulfides.
"""

from __future__ import annotations

from dataclasses import dataclass

from dvbfixer.domain.force_field_naming import ForceFieldTarget, target_residue_name

_FAMILIES = {
    "HIS": {"HIS", "HID", "HIE", "HIP"},
    "ASP": {"ASP", "ASH"},
    "GLU": {"GLU", "GLH"},
    "LYS": {"LYS", "LYN"},
    "CYS": {"CYS", "CYM", "CYX"},
}
_PARENTS = {
    "HIS": {"ND1", "NE2"}, "ASP": {"OD1", "OD2"},
    "GLU": {"OE1", "OE2"}, "LYS": {"NZ"}, "CYS": {"SG"},
}


@dataclass(frozen=True)
class ProtonationIdentification:
    residue_name: str
    from_hydrogens: bool = False
    warning: str | None = None


def identify_protonation(
    residue_name: str, atom_names: set[str], hydrogen_names: set[str],
) -> ProtonationIdentification | None:
    """Recognize the name first, then refine it using supported site-H patterns.

    Return None for families without a supported alternative naming vocabulary.
    Output residue labels use AMBER spelling; atom labels are never changed.
    """
    named = target_residue_name(residue_name, ForceFieldTarget.AMBER)
    family = next((parent for parent, variants in _FAMILIES.items() if named in variants), None)
    if family is None:
        return None

    def unresolved(reason: str) -> ProtonationIdentification:
        return ProtonationIdentification(named, warning=f"{reason}; retaining name-derived {named}")

    if not _PARENTS[family] <= atom_names:
        return unresolved("Incomplete ionizable-group heavy atoms")

    inferred: str | None = None
    if family == "HIS":
        ring = hydrogen_names & {"HD1", "HE2"}
        inferred = {frozenset({"HD1"}): "HID", frozenset({"HE2"}): "HIE",
                    frozenset({"HD1", "HE2"}): "HIP"}.get(frozenset(ring))
    elif family in {"ASP", "GLU"}:
        site = hydrogen_names & ({"HD1", "HD2"} if family == "ASP" else {"HE1", "HE2"})
        if len(site) > 1:
            return unresolved("Multiple carboxyl hydrogens are outside supported states")
        if site:
            inferred = "ASH" if family == "ASP" else "GLH"
    elif family == "LYS":
        site = hydrogen_names & {"HZ", "HZ1", "HZ2", "HZ3"}
        if len(site) == 3 and "HZ" not in site:
            inferred = "LYS"
        elif site in ({"HZ1", "HZ2"}, {"HZ2", "HZ3"}):
            inferred = "LYN"
        elif site:
            return unresolved("Incomplete or unsupported NZ hydrogen pattern")
    else:
        site = hydrogen_names & {"HG", "HG1"}
        if len(site) > 1:
            return unresolved("Multiple sulfur hydrogens are outside supported states")
        if site:
            if named == "CYX":
                return unresolved("CYX disulfide identity conflicts with an observed sulfur hydrogen")
            inferred = "CYS"
        else:
            return unresolved("No sulfur hydrogen: thiolate, disulfide and missing H cannot be distinguished")

    if inferred is None:
        return unresolved("No diagnostic site hydrogens; absent H is not proof of deprotonation")
    warning = None
    if inferred != named and named != family:
        warning = f"Name-derived {named} conflicts with observed site H; using {inferred}"
    elif inferred != named and family in {"ASP", "GLU", "LYS"}:
        warning = f"Name-derived {named} differs from observed site H; using {inferred}"
    return ProtonationIdentification(inferred, from_hydrogens=True, warning=warning)
