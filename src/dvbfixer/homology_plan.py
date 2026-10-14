"""Materialize GUI/CLI template-part plans for comparative modeling."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from dvbfixer.domain.structure_identity import allocate_chain_ids
from dvbfixer.homology import AA3TO1
from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    ArtifactReference,
    AtomIdentity,
    BackendOption,
    DiffusionRequest,
    GapKind,
    GapRegion,
    ResidueIdentity,
    SequencePlacement,
    TargetInterval,
    TargetSequence,
    TemplateOwnership,
)
from dvbfixer.model.diffusion.scope import (
    _CANONICAL_ONE_TO_THREE,
    MAXIMUM_GAP_LENGTH,
    MINIMUM_GAP_LENGTH,
    canonical_heavy_atom_identities,
)
from dvbfixer.salign import run_biopython_superposition


def _residues(pdb: Path, chain: str) -> list[dict]:
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in pdb.read_text().splitlines():
        if not line.startswith(("ATOM  ", "HETATM")) or line[21].strip() != chain:
            continue
        aa = AA3TO1.get(line[17:20].strip().upper())
        if not aa:
            continue
        key = line[22:27]
        if current is None or current["key"] != key:
            current = {"key": key, "aa": aa, "lines": []}
            records.append(current)
        current["lines"].append(line)
    if not records:
        raise ValueError(f"no protein residues found for chain {chain} in {pdb}")
    return records


def materialize_template_plan(plan_path: Path, workdir: Path,
                              msa_engine: str = "auto",
                              verbose: bool = False) -> tuple[list[str], str]:
    """Fit selected templates and create one coordinate-preserving known.

    The JSON plan contains ``templates`` and ``alignmentGroups`` using the
    documented Homology workspace schema. Alignment ranges are zero-based,
    half-open column intervals. Earlier template rows win overlap columns.
    """
    plan = json.loads(plan_path.read_text())
    workdir.mkdir(parents=True, exist_ok=True)
    templates = [dict(item) for item in plan.get("templates", [])]
    groups = plan.get("alignmentGroups", [])
    if not templates or not groups:
        raise ValueError("template plan requires templates and alignmentGroups")
    labels = [str(group["chainId"]) for group in groups]
    if any(not label for label in labels) or len(set(labels)) != len(labels):
        raise ValueError("template plan target chain IDs must be non-empty and unique")
    by_id = {item["id"]: item for item in templates}
    if len(by_id) != len(templates):
        raise ValueError("template plan template IDs must be unique")
    global_reference = Path(templates[0]["path"]).resolve()
    fitted_by_id: dict[str, Path] = {}

    for group in groups:
        members = [item for item in templates if item["targetChain"] == group["chainId"]]
        reference = next((item for item in members
                          if Path(item["path"]).resolve() == global_reference), None)
        if len(groups) > 1 and reference is None:
            raise ValueError(
                f"target chain {group['chainId']} has no chain from common "
                f"reference structure {global_reference}"
            )
        if reference:
            members = [reference] + [item for item in members if item["id"] != reference["id"]]
        if len(members) == 1:
            fitted_by_id[members[0]["id"]] = Path(members[0]["path"]).resolve()
            continue
        fit_dir = workdir / "fitted" / str(group["chainId"])
        specs = [f"{Path(item['path']).resolve()}:{item['chain']}" for item in members]
        fitted = run_biopython_superposition(
            specs, workdir / f"structural_alignment_{group['chainId']}.pir",
            fit_dir, msa_engine=msa_engine, verbose=verbose,
        )
        for item, fitted_path in zip(members, fitted):
            fitted_by_id[item["id"]] = fitted_path

    blocks: list[str] = []
    coverage_groups: list[dict[str, Any]] = []
    pdb_lines: list[str] = []
    serial = 1
    first = last = None
    used_chains: set[str] = set()
    group_chains: dict[str, str] = {}
    alphabet = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
    declared_pdb_chains = {label for label in labels if len(label) == 1}
    for group in groups:
        label = str(group["chainId"])
        preferred = label.upper()[-1] if label.upper() in {"VH", "VL"} else (label if len(label) == 1 else label[0])
        if len(preferred) != 1 or preferred in used_chains or len(label) > 1 and preferred in declared_pdb_chains:
            preferred = allocate_chain_ids(1, alphabet=alphabet, reserved=used_chains | declared_pdb_chains)[0]
        used_chains.add(preferred)
        group_chains[label] = preferred

    for group in groups:
        rows = group.get("rows", [])
        target = next((row for row in rows if row.get("kind") == "target"), None)
        if target is None:
            raise ValueError(f"target row missing for chain {group['chainId']}")
        length = len(target["sequence"])
        if any(len(row["sequence"]) != length for row in rows):
            raise ValueError(f"alignment rows for target chain {group['chainId']} differ in length")
        chosen: list[tuple[dict[str, Any], str] | None] = [None] * length
        deleted: list[tuple[dict[str, Any], str] | None] = [None] * length
        for row in (row for row in rows if row.get("kind") == "template"):
            template_id = row.get("templateId", row["id"])
            template = by_id.get(template_id)
            if template is None:
                raise ValueError(f"template metadata missing for {row['id']}")
            residues = _residues(fitted_by_id.get(template_id, Path(template["path"])), template["chain"])
            if row["sequence"].replace("-", "") != "".join(item["aa"] for item in residues):
                raise ValueError(f"alignment row {row['id']} does not match {template['path']}:{template['chain']}")
            by_column = []
            index = 0
            for character in row["sequence"]:
                by_column.append(None if character == "-" else residues[index])
                if character != "-":
                    index += 1
            mode = group.get("maskModes", {}).get(row["id"],
                    "ranges" if group.get("masks", {}).get(row["id"]) else "all")
            spans = [] if mode == "none" else group.get("masks", {}).get(row["id"], []) \
                if mode == "ranges" else [{"start": 0, "end": length}]
            for span in spans:
                for column in range(max(0, span["start"]), min(length, span["end"])):
                    if target["sequence"][column] == "-" and deleted[column] is None:
                        residue = by_column[column]
                        if residue is not None:
                            deleted[column] = (residue, template_id)
                    elif target["sequence"][column] != "-" and chosen[column] is None:
                        residue = by_column[column]
                        if residue is not None:
                            chosen[column] = (residue, template_id)

        ordinal = 0
        block = []
        coverage: list[dict[str, Any]] = []
        deletions: list[dict[str, Any]] = []
        chain = group_chains[str(group["chainId"])]
        for column, target_aa in enumerate(target["sequence"]):
            removed_selection = deleted[column]
            if target_aa == "-" and removed_selection is not None:
                removed, removed_owner = removed_selection
                deletions.append({"alignmentColumn": column, "boundaryTargetIndex": ordinal,
                                  "templateId": removed_owner, "templateResidue": removed["aa"]})
            if target_aa != "-":
                ordinal += 1
                if ordinal > 9999:
                    raise ValueError("mosaic target residue numbering exceeds the fixed-column PDB limit")
            selected = chosen[column]
            residue = selected[0] if selected is not None else None
            owner = selected[1] if selected is not None else None
            block.append(residue["aa"] if residue else "-")
            if target_aa != "-":
                coverage.append({
                    "targetIndex": ordinal - 1,
                    "alignmentColumn": column,
                    "targetResidue": target_aa,
                    "covered": residue is not None,
                    "templateId": owner,
                    "templateResidue": residue["aa"] if residue else None,
                    "pdbResidue": {
                        "chain": chain,
                        "residueNumber": str(ordinal),
                        "insertionCode": "",
                    },
                })
            if residue is None:
                continue
            first = first or (ordinal, chain)
            last = (ordinal, chain)
            for raw in residue["lines"]:
                if serial > 99999:
                    raise ValueError("mosaic atom serial numbering exceeds the fixed-column PDB limit")
                line = raw.ljust(80)
                pdb_lines.append(
                    f"ATOM  {serial:5d}{line[11:21]}{chain}{ordinal:4d} {line[27:]}\n"
                )
                serial += 1
        blocks.append("".join(block))
        coverage_groups.append({
            "targetChain": str(group["chainId"]),
            "pdbChain": chain,
            "targetSequence": target["sequence"].replace("-", ""),
            "coverage": coverage,
            **({"deletions": deletions} if deletions else {}),
        })
        pdb_lines.append("TER\n")

    if first is None or last is None:
        raise ValueError("template plan selects no target-aligned residues")
    code = "selected_template_mosaic"
    pdb = workdir / f"{code}.pdb"
    pdb.write_text("".join(pdb_lines) + "END\n")
    coverage_path = workdir / "selected_template_mosaic.coverage.json"
    coverage_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "sourcePlan": str(plan_path.resolve()),
                "mosaic": pdb.name,
                "maskConvention": "zero-based-half-open",
                "overlapPolicy": "earlier-template-wins",
                "groups": coverage_groups,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    target_blocks = [next(row for row in group["rows"] if row.get("kind") == "target")["sequence"]
                     for group in groups]
    pir = workdir / "selected_template_mosaic.pir"
    pir.write_text(
        f">P1;{code}\nstructureX:{code}:{first[0]}:{first[1]}:{last[0]}:{last[1]}::::\n"
        f"{'/'.join(blocks)}*\n>P1;target\nsequence:target::::::::\n{'/'.join(target_blocks)}*\n"
    )
    return [str(pdb)], str(pir)


def prepare_mosaic_diffusion_inputs(
    coverage_path: Path,
    target_chains: list[tuple[str, str]],
    workdir: Path,
    *,
    regenerate_covered: bool = False,
) -> tuple[Path, tuple[TemplateOwnership, ...]]:
    """Validate template ownership and write a PDB-chain-keyed target FASTA."""
    raw = json.loads(coverage_path.read_text(encoding="utf-8"))
    if raw.get("schemaVersion") != 1:
        raise ValueError("unsupported mosaic coverage schema")
    targets = dict(target_chains)
    groups = raw.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("mosaic coverage contains no target groups")

    fasta_lines: list[str] = []
    ownership: list[TemplateOwnership] = []
    seen_pdb_chains: set[str] = set()
    uncovered = 0
    for group in groups:
        if group.get("deletions") and not regenerate_covered:
            raise ValueError("mosaic diffusion deletions require opt-in covered regeneration")
        logical_chain = str(group.get("targetChain", ""))
        pdb_chain = str(group.get("pdbChain", ""))
        expected_sequence = str(group.get("targetSequence", ""))
        if logical_chain not in targets:
            raise ValueError(
                f"mosaic target chain {logical_chain!r} is absent from target FASTA"
            )
        if targets[logical_chain] != expected_sequence:
            raise ValueError(
                f"mosaic target sequence for chain {logical_chain!r} does not match FASTA"
            )
        if len(pdb_chain) != 1 or pdb_chain in seen_pdb_chains:
            raise ValueError("mosaic PDB chain mapping must be unique and one character")
        seen_pdb_chains.add(pdb_chain)
        coverage = group.get("coverage")
        if not isinstance(coverage, list) or len(coverage) != len(expected_sequence):
            raise ValueError("mosaic coverage length does not match its target sequence")
        for expected_index, item in enumerate(coverage):
            if item.get("targetIndex") != expected_index:
                raise ValueError("mosaic coverage target indices must be contiguous")
            if item.get("targetResidue") != expected_sequence[expected_index]:
                raise ValueError("mosaic coverage residue does not match the target sequence")
            residue = item.get("pdbResidue", {})
            if residue.get("chain") != pdb_chain:
                raise ValueError("mosaic coverage residue chain mapping is inconsistent")
            if not item.get("covered"):
                uncovered += 1
                continue
            if item.get("templateResidue") != item.get("targetResidue") and not regenerate_covered:
                raise ValueError(
                    "mosaic diffusion does not yet support template-covered substitutions"
                )
            ownership.append(TemplateOwnership(
                chain=pdb_chain,
                target_index=expected_index,
                residue=ResidueIdentity(
                    pdb_chain,
                    str(residue.get("residueNumber", "")),
                    str(residue.get("insertionCode", "")),
                ),
                template_id=str(item.get("templateId", "")),
            ))
        fasta_lines.extend((f">{pdb_chain}", expected_sequence))

    extra_targets = set(targets) - {
        str(group.get("targetChain", "")) for group in groups
    }
    if extra_targets:
        raise ValueError(
            "target FASTA contains chains absent from mosaic plan: "
            + ", ".join(sorted(extra_targets))
        )
    if not uncovered and not regenerate_covered:
        raise ValueError("mosaic diffusion requires at least one uncovered target residue")
    fasta_path = workdir / "selected_template_mosaic.target.fasta"
    fasta_text = "\n".join(fasta_lines) + "\n"
    if fasta_path.exists():
        if fasta_path.is_symlink() or fasta_path.read_text() != fasta_text:
            raise ValueError("mosaic target FASTA destination already contains different data")
    else:
        with fasta_path.open("x", encoding="utf-8") as stream:
            stream.write(fasta_text)
    return fasta_path, tuple(ownership)


def build_mosaic_diffusion_request(
    coverage_path: Path,
    target_chains: list[tuple[str, str]],
    workdir: Path,
    *,
    seeds: tuple[int, ...],
    regenerate_covered: bool = False,
    profile: str = "",
) -> tuple[Path, Path]:
    """Use authoritative coverage positions, never sequence re-alignment.

    Opt-in substitutions regenerate a bounded window with observed anchors.
    Short uncovered runs may expand only under the same explicit opt-in.
    Covered atoms outside those windows remain byte-identical and template-owned.
    """
    input_path = workdir / "mosaic_diffusion_input.pdb"
    request_path = workdir / "mosaic_diffusion_request.json"
    if any(path.exists() or path.is_symlink() for path in (input_path, request_path)):
        raise ValueError("mosaic diffusion input or request destination already exists")
    _fasta, ownership = prepare_mosaic_diffusion_inputs(
        coverage_path, target_chains, workdir, regenerate_covered=regenerate_covered,
    )
    raw = json.loads(coverage_path.read_text())
    source = coverage_path.parent / raw["mosaic"]
    text = source.read_text()
    canonical_names = set(_CANONICAL_ONE_TO_THREE.values())
    if any(line.startswith(("ATOM  ", "HETATM")) and line[17:20].strip() not in canonical_names
           for line in text.splitlines()):
        raise ValueError("mosaic diffusion requires canonical protein template residues before regeneration")
    targets = []
    placements = []
    gaps = []
    generated_atoms: list[AtomIdentity] = []
    mutable_residues: set[ResidueIdentity] = set()
    for group in raw["groups"]:
        chain = group["pdbChain"]
        sequence = group["targetSequence"]
        if any(letter not in _CANONICAL_ONE_TO_THREE for letter in sequence):
            raise ValueError("mosaic diffusion requires canonical target sequences")
        coverage = group["coverage"]
        mutable = {index for index, item in enumerate(coverage) if not item["covered"]}
        mismatches = {index for index, item in enumerate(coverage)
                      if item["covered"] and item["templateResidue"] != item["targetResidue"]}
        if regenerate_covered:
            for index in sorted(mismatches):
                mutable.update(range(max(0, index - 1), min(len(sequence), index + 2)))
            for deletion in group.get("deletions", []):
                boundary = int(deletion["boundaryTargetIndex"])
                if not 0 <= boundary <= len(sequence):
                    raise ValueError("mosaic deletion boundary is outside the target sequence")
                mutable.update(range(max(0, boundary - 1), min(len(sequence), boundary + 2)))
        # Expand short runs in a fixed left-then-right order. Recompute runs
        # after each expansion because adjacent mutable windows can merge.
        while True:
            runs = _index_runs(mutable)
            short = next(((start, stop) for start, stop in runs if stop - start < MINIMUM_GAP_LENGTH), None)
            if short is None or not regenerate_covered:
                break
            start, stop = short
            if start > 1:
                mutable.add(start - 1)
            elif stop < len(sequence) - 1:
                mutable.add(stop)
            else:
                raise ValueError("mosaic regeneration cannot retain observed anchors around a short window")
        residues = tuple(ResidueIdentity(chain, str(item["pdbResidue"]["residueNumber"]),
                                         str(item["pdbResidue"].get("insertionCode", ""))) for item in coverage)
        targets.append(TargetSequence(chain, sequence))
        observed = tuple(index for index, item in enumerate(coverage) if item["covered"] and index not in mutable)
        placements.append(SequencePlacement(chain, len(sequence), observed, tuple(residues[index] for index in observed)))
        for start, stop in _index_runs(mutable):
            if not MINIMUM_GAP_LENGTH <= stop - start <= MAXIMUM_GAP_LENGTH:
                raise ValueError(f"mosaic regeneration window {chain}:{start}-{stop} is outside the accepted 3-12 range")
            left = residues[start - 1] if start else None
            right = residues[stop] if stop < len(sequence) else None
            generated = residues[start:stop]
            gaps.append(GapRegion(chain, TargetInterval(start, stop), left, right, generated,
                                  tuple(residue for residue in (left, *generated, right) if residue is not None),
                                  GapKind.N_TERMINAL if left is None else GapKind.C_TERMINAL if right is None else GapKind.INTERNAL))
            mutable_residues.update(generated)
            generated_atoms.extend(atom for index in range(start, stop)
                                   for atom in canonical_heavy_atom_identities(residues[index],
                                       _CANONICAL_ONE_TO_THREE[sequence[index]]))
    if not gaps:
        raise ValueError("mosaic diffusion requires uncovered residues or opt-in covered substitutions")
    if regenerate_covered:
        from openmm.app import PDBFile

        original_topology = PDBFile(str(source)).topology
        for first_atom, second_atom in original_topology.bonds():
            if first_atom.name == second_atom.name == "SG":
                linked = {ResidueIdentity(atom.residue.chain.id, atom.residue.id,
                                          atom.residue.insertionCode.strip()) for atom in (first_atom, second_atom)}
                if linked & mutable_residues:
                    raise ValueError("mosaic regeneration would alter a disulfide-linked residue; unsupported edit chemistry")
    normalized_lines = []
    fixed = []
    for line in text.splitlines(keepends=True):
        if line.startswith(("ATOM  ", "HETATM")):
            residue = ResidueIdentity(line[21], line[22:26].strip(), line[26].strip())
            if residue in mutable_residues:
                continue
            if line[76:78].strip().upper() not in {"H", "D"}:
                fixed.append(AtomIdentity(residue.chain, residue.residue_number, residue.insertion_code, line[12:16].strip()))
        normalized_lines.append(line)
    with input_path.open("x") as stream:
        stream.write("".join(normalized_lines))
    request = DiffusionRequest(
        schema_version=DIFFUSION_SCHEMA_VERSION,
        normalized_pdb=ArtifactReference(input_path.name, hashlib.sha256(input_path.read_bytes()).hexdigest()),
        target_sequences=tuple(targets), sequence_placements=tuple(placements), gaps=tuple(gaps),
        fixed_atoms=tuple(fixed), generated_atoms=tuple(generated_atoms), retained_explicit_links=(),
        candidate_count=len(seeds), seeds=seeds,
        backend_options=(BackendOption("mosaic_source_sha256", hashlib.sha256(source.read_bytes()).hexdigest()),
                         BackendOption("mosaic_coverage_sha256", hashlib.sha256(coverage_path.read_bytes()).hexdigest()),
                         *((BackendOption("profile", profile),) if profile else ())),
        template_ownership=tuple(owner for owner in ownership if owner.residue not in mutable_residues),
        regenerated_template_ownership=(tuple(owner for owner in ownership if owner.residue in mutable_residues)
                                       if regenerate_covered else None),
    )
    with request_path.open("x") as stream:
        stream.write(request.to_json())
    return input_path, request_path


def _index_runs(indices: set[int]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for index in sorted(indices):
        if runs and runs[-1][1] == index:
            runs[-1] = (runs[-1][0], index + 1)
        else:
            runs.append((index, index + 1))
    return runs
