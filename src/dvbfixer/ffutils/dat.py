"""Shared schema and I/O helpers for the pipeline's ``.dat`` files.

The ``.dat`` file is the structured handoff between pipeline stages:

- ``model`` writes it with the atoms that Modeller rebuilt into gap
  residues.
- ``prepare`` writes it with the atoms PDBFixer added (missing heavy atoms
  + hydrogens), plus AMBER protonation-variant overrides (from user
  ``--mutate`` or input HIE/CYX/... names) and any residues removed by
  ``--mutate CHAIN:RESNUM:del``.
- ``prepare`` also *merges* any upstream ``.dat`` sitting next to its
  input (i.e. the one ``model`` just wrote) so downstream tools see one
  authoritative record.
- ``minimize`` reads the merged ``.dat`` to build tiered restraints:
  original heavy atoms strong, new backbone weak, new sidechain + all H
  free. It also picks up the ``variant_overrides`` map so ``addHydrogens``
  places the right protonation H even when the input PDB has been through
  OpenMM's ``PDBFile`` normalisation (which strips AMBER variant names).
- ``homology`` writes a stub ``.dat`` (all atoms modelled from templates)
  for downstream restraints.

Before this module every writer/reader used hand-rolled ``json.dump`` /
``json.load`` calls with slightly different shapes. This module codifies
the schema and gives the callers a single ``DatRecord`` dataclass with
``load`` / ``save`` / ``merge`` methods.

Schema
------
``DatRecord`` — top-level object serialised to JSON.

- ``description: str`` — free-form label, distinguishes writer (prepare vs
  model vs homology).
- ``total_added: int`` — ``len(added_atoms)``. Kept for backward
  compatibility with hand-written ``.dat`` files; auto-populated on save.
- ``added_atoms: list[AddedAtom]`` — atoms that were rebuilt by an
  upstream step. Each entry: ``{chain, resid, icode, resname, atom,
  element}``. Restraint tier lookup is by ``(chain, resid, icode, atom)``
  in ``minimize``.
- ``residue_summary: dict[str, {heavy: int, hydrogen: int}]`` — one entry
  per rebuilt residue keyed by ``"{chain}/{resname}{resid}"``. Only used
  for the human-facing "N heavy atoms, M hydrogens added to X residues"
  print in ``prepare`` and ``model``.
- ``variant_overrides: dict[str, str] | None`` — ``{f"{chain}:{resid}:{icode}":
  variant_name}`` (icode is an empty string when the residue has none — the
  key always has exactly 3 colon-separated fields, never 2, so a bare
  resid can't be confused with resid+icode concatenated together).
  Populated by ``prepare`` when the input already used AMBER variant names
  (HIE/HID/HIP/ASH/GLH/CYX/CYM/LYN) OR when the user passed ``--mutate
  CHAIN:RESNUM:VARIANT`` (icode always '' for --mutate entries — that CLI
  syntax has no icode field). Consumed by ``minimize`` so
  ``addHydrogens`` places the correct protonation H even after OpenMM's
  ``PDBFile`` normalises the names on load.
- ``removed_residues: list[dict] | None`` — records any residues removed
  by ``--mutate CHAIN:RESNUM:del`` (or substitution-cleanup where the
  parent residue changed). Each entry has ``chain, resid, icode, resname,
  removed_atoms, gap_type, gap_distance_A, prev_residue, next_residue,
  linked_glycan_residues, disulfide_partner_repaired, substituted_to``.
- ``templates: list[str] | None`` — homology only; template PDB
  basenames.
- ``target_chains: dict[str, int] | None`` — homology only; per-chain
  target sequence length.

All optional fields are dropped from the JSON when unset so existing
hand-written ``.dat`` files stay valid.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict


class AddedAtom(TypedDict):
    """One rebuilt atom entry in ``.dat``."""

    chain: str
    resid: str
    icode: str
    resname: str
    atom: str
    element: str


class ResidueSummary(TypedDict):
    heavy: int
    hydrogen: int


@dataclass
class DatRecord:
    """In-memory representation of a ``.dat`` file.

    Prefer :meth:`load` and :meth:`save` over hand-rolling ``json.load`` /
    ``json.dump`` — this keeps the schema in one place.
    """

    description: str = ""
    added_atoms: list[AddedAtom] = field(default_factory=list)
    residue_summary: dict[str, ResidueSummary] = field(default_factory=dict)
    variant_overrides: dict[str, str] | None = None
    removed_residues: list[dict[str, Any]] | None = None
    templates: list[str] | None = None
    target_chains: dict[str, int] | None = None

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> DatRecord:
        """Load a ``.dat`` file. Missing optional fields become ``None``
        / empty containers.
        """
        with open(path) as f:
            raw = json.load(f)
        return cls.from_dict(raw)

    @classmethod
    def from_json(cls, text: str) -> DatRecord:
        """Decode already digest-verified sidecar bytes without reopening a path."""
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError(".dat content must be a JSON object")
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DatRecord:
        """Canonical schema decoding shared by file and verified-byte consumers."""
        return cls(
            description=raw.get("description", ""),
            added_atoms=list(raw.get("added_atoms", [])),
            residue_summary=dict(raw.get("residue_summary", {})),
            variant_overrides=raw.get("variant_overrides"),
            removed_residues=raw.get("removed_residues"),
            templates=raw.get("templates"),
            target_chains=raw.get("target_chains"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serialisable dict. ``total_added`` is derived
        from ``added_atoms`` here so writers can't drift.
        """
        out: dict[str, Any] = {
            "description": self.description,
            "total_added": len(self.added_atoms),
            "residue_summary": self.residue_summary,
            "added_atoms": self.added_atoms,
        }
        if self.variant_overrides is not None:
            out["variant_overrides"] = self.variant_overrides
        if self.removed_residues is not None:
            out["removed_residues"] = self.removed_residues
        if self.templates is not None:
            out["templates"] = self.templates
        if self.target_chains is not None:
            out["target_chains"] = self.target_chains
        return out

    def save(self, path: str | Path, *, verbose: bool = True) -> None:
        """Write to disk. Prints a "Saved restraint data" line when
        ``verbose`` (matches the historical writer messages so log output
        is unchanged).
        """
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        if verbose:
            print(f"Saved restraint data: {path}")

    # ------------------------------------------------------------------
    # Set semantics on added_atoms
    # ------------------------------------------------------------------

    def added_keys(self) -> set[tuple[str, str, str, str]]:
        """Return ``{(chain, resid, icode, atom), ...}`` — used by
        ``minimize`` to look restraints up per topology atom.
        """
        return {
            (a["chain"], a["resid"], a["icode"].strip(), a["atom"])
            for a in self.added_atoms
        }

    def merge(self, upstream: DatRecord) -> int:
        """Merge ``upstream`` into this record (in place).

        Adds any ``upstream.added_atoms`` not already present (matched on
        ``(chain, resid, icode, atom)``) and re-tallies
        ``residue_summary``. Optional fields (``variant_overrides``,
        ``removed_residues``) are unioned dict-wise / list-wise;
        ``upstream``'s values do NOT overwrite ours on collision — the
        downstream (current) record wins because it was written by a
        later stage. Returns the number of atoms carried forward.
        """
        existing = self.added_keys()
        carried = 0
        for atom in upstream.added_atoms:
            key = (atom["chain"], atom["resid"], atom["icode"].strip(), atom["atom"])
            if key in existing:
                continue
            self.added_atoms.append(atom)
            existing.add(key)
            rkey = f"{atom['chain']}/{atom['resname']}{atom['resid']}"
            if rkey not in self.residue_summary:
                self.residue_summary[rkey] = {"heavy": 0, "hydrogen": 0}
            if atom.get("element") == "H":
                self.residue_summary[rkey]["hydrogen"] += 1
            else:
                self.residue_summary[rkey]["heavy"] += 1
            carried += 1

        if upstream.variant_overrides:
            merged_vo = dict(upstream.variant_overrides)
            merged_vo.update(self.variant_overrides or {})  # downstream wins
            self.variant_overrides = merged_vo

        if upstream.removed_residues:
            base = list(upstream.removed_residues)
            base.extend(self.removed_residues or [])
            self.removed_residues = base

        return carried


def load(path: str | Path) -> DatRecord:
    """Module-level convenience wrapper equivalent to
    :meth:`DatRecord.load`.
    """
    return DatRecord.load(path)


def load_added_keys(path: str | Path) -> set[tuple[str, str, str, str]]:
    """Load a ``.dat`` file and return the set of added-atom keys.

    Matches the shape ``minimize.load_dat`` used to return. Prints the
    ``"Loaded restraint data"`` line as a side effect so replacing the
    old writer at the call site is a byte-identical drop-in.
    """
    rec = DatRecord.load(path)
    keys = rec.added_keys()
    print(f"Loaded restraint data: {path} ({len(keys)} added atoms)")
    return keys


def save(record: DatRecord, path: str | Path, *, verbose: bool = True) -> None:
    """Module-level convenience wrapper equivalent to :meth:`DatRecord.save`."""
    record.save(path, verbose=verbose)
