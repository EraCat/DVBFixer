"""Narrow public orchestration for ``model --backend diffusion``."""

from __future__ import annotations

import argparse
import hashlib
import tempfile
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

from dvbfixer.model.cli import AA3TO1
from dvbfixer.model.diffusion.contract import (
    DIFFUSION_SCHEMA_VERSION,
    ArtifactReference,
    BackendOption,
    DiffusionContractError,
    DiffusionRequest,
    ExplicitLink,
    GapKind,
    GapRegion,
    ResidueIdentity,
    SequencePlacement,
    TargetInterval,
    TargetSequence,
    TemplateOwnership,
)
from dvbfixer.model.diffusion.heterogen_context import (
    HeterogenContextError,
    build_smiles_heterogen_contexts,
)
from dvbfixer.model.diffusion.masks import (
    DiffusionMaskError,
    ObservedResidue,
    build_sequence_placement,
)
from dvbfixer.model.diffusion.pipeline import run_diffusion_pipeline
from dvbfixer.model.diffusion.preflight import invoke_runner_preflight
from dvbfixer.model.diffusion.runner import RunnerLimits
from dvbfixer.model.diffusion.runtime import (
    DiffusionRuntimeError,
    resolve_diffusion_runtime,
)
from dvbfixer.model.diffusion.scope import (
    MAXIMUM_GAP_LENGTH,
    MINIMUM_GAP_LENGTH,
    DiffusionScopeError,
    _parse_coordinate_records,
    _parse_explicit_links,
    assess_diffusion_scope,
    canonical_heavy_atom_identities,
)
from dvbfixer.prepare.smiles import SmilesPreparationError, parse_smiles_mappings


class DiffusionCliError(ValueError):
    """Raised when a CLI input cannot form the initial diffusion request."""


def build_cli_diffusion_request(
    input_path: Path,
    target_sequences: dict[str, str],
    *,
    seeds: tuple[int, ...],
    profile: str,
    no_terminal: bool = False,
    heterogen_smiles: dict[str, str] | None = None,
    template_ownership: tuple[TemplateOwnership, ...] = (),
) -> DiffusionRequest:
    """Build a canonical-protein request with internal gaps on one or more chains."""
    source = input_path.read_bytes()
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DiffusionCliError("normalized PDB is not valid UTF-8") from exc
    lines = text.splitlines()
    atoms, residue_names, _altlocs = _parse_coordinate_records(lines)

    protein_residues: list[ObservedResidue] = []
    seen: set[ResidueIdentity] = set()
    atom_names: dict[ResidueIdentity, list[str]] = {}
    for record in atoms:
        if record.record_name != "ATOM":
            continue
        residue = ResidueIdentity(
            record.identity.chain,
            record.identity.residue_number,
            record.identity.insertion_code,
        )
        atom_names.setdefault(residue, []).append(record.identity.atom_name)
        if residue in seen:
            continue
        seen.add(residue)
        one_letter = AA3TO1.get(record.residue_name)
        if one_letter is None:
            raise DiffusionCliError(
                f"non-canonical protein residue is unsupported: "
                f"{residue.chain}/{record.residue_name}{residue.residue_number}{residue.insertion_code}"
            )
        protein_residues.append(ObservedResidue(residue, one_letter, ("CA",)))

    chains = tuple(dict.fromkeys(residue.identity.chain for residue in protein_residues))
    if not chains:
        raise DiffusionCliError("diffusion input contains no protein chains")
    targets: list[TargetSequence] = []
    placements = []
    gap_regions: list[GapRegion] = []
    target_by_chain: dict[str, str] = {}
    for chain in chains:
        observed = tuple(
            ObservedResidue(
                residue.identity,
                residue.one_letter_code,
                tuple(dict.fromkeys(atom_names[residue.identity])),
            )
            for residue in protein_residues
            if residue.identity.chain == chain
        )
        target = target_sequences.get(
            chain,
            "".join(residue.one_letter_code for residue in observed),
        ).upper()
        try:
            placement = build_sequence_placement(chain, observed, target)
        except DiffusionMaskError as exc:
            raise DiffusionCliError(str(exc)) from exc
        if no_terminal and (
            placement.observed_target_indices[0] != 0
            or placement.observed_target_indices[-1] != len(target) - 1
        ):
            first = placement.observed_target_indices[0]
            last = placement.observed_target_indices[-1]
            target = target[first : last + 1]
            placement = SequencePlacement(
                chain=chain,
                target_length=len(target),
                observed_target_indices=tuple(
                    index - first for index in placement.observed_target_indices
                ),
                observed_residues=placement.observed_residues,
            )
        targets.append(TargetSequence(chain, target))
        placements.append(placement)
        target_by_chain[chain] = target
        occupied = set(placement.observed_residues)
        by_target = dict(zip(
            placement.observed_target_indices,
            placement.observed_residues,
        ))
        intervals: list[tuple[int, int, GapKind]] = []
        first_observed = placement.observed_target_indices[0]
        last_observed = placement.observed_target_indices[-1]
        if first_observed > 0:
            intervals.append((0, first_observed, GapKind.N_TERMINAL))
        intervals.extend(
            (left + 1, right, GapKind.INTERNAL)
            for left, right in zip(
                placement.observed_target_indices,
                placement.observed_target_indices[1:],
            )
            if right > left + 1
        )
        if last_observed < len(target) - 1:
            intervals.append((last_observed + 1, len(target), GapKind.C_TERMINAL))
        for start, stop, gap_kind in intervals:
            gap_length = stop - start
            if not MINIMUM_GAP_LENGTH <= gap_length <= MAXIMUM_GAP_LENGTH:
                region = {
                    GapKind.INTERNAL: "internal gap",
                    GapKind.N_TERMINAL: "N-terminal missing region",
                    GapKind.C_TERMINAL: "C-terminal missing region",
                }[gap_kind]
                remedy = (
                    "; pass --no-terminal to crop unobserved tails"
                    if gap_kind is not GapKind.INTERNAL
                    else ""
                )
                raise DiffusionCliError(
                    f"{region} length {gap_length} on chain {chain} is outside "
                    f"the accepted range {MINIMUM_GAP_LENGTH}-{MAXIMUM_GAP_LENGTH}"
                    f"{remedy}"
                )
            left_anchor = by_target[start - 1] if start > 0 else None
            right_anchor = by_target[stop] if stop < len(target) else None
            try:
                for anchor in (left_anchor, right_anchor):
                    if anchor is not None:
                        int(anchor.residue_number)
            except ValueError as exc:
                raise DiffusionCliError(
                    "diffusion requires integer PDB residue numbers"
                ) from exc
            if gap_kind is GapKind.INTERNAL:
                assert left_anchor is not None and right_anchor is not None
                generated_residues = _allocate_generated_residues(
                    chain,
                    left_anchor,
                    right_anchor,
                    gap_length,
                    occupied,
                )
            else:
                terminal_anchor = right_anchor if left_anchor is None else left_anchor
                assert terminal_anchor is not None
                generated_residues = _allocate_terminal_generated_residues(
                    chain,
                    terminal_anchor,
                    gap_length,
                    occupied,
                    n_terminal=gap_kind is GapKind.N_TERMINAL,
                )
            occupied.update(generated_residues)
            gap_regions.append(GapRegion(
                chain=chain,
                target_interval=TargetInterval(start, stop),
                left_anchor=left_anchor,
                right_anchor=right_anchor,
                generated_residues=generated_residues,
                movable_junction_residues=(
                    *((left_anchor,) if left_anchor is not None else ()),
                    *generated_residues,
                    *((right_anchor,) if right_anchor is not None else ()),
                ),
                gap_kind=gap_kind,
            ))
    if not gap_regions:
        raise DiffusionCliError("diffusion requires at least one missing target region")

    fixed_atoms = tuple(
        record.identity for record in atoms if record.element.upper() != "H"
    )
    generated_atoms = tuple(
        atom
        for gap in gap_regions
        for target_index, residue in zip(
            range(gap.target_interval.start, gap.target_interval.stop),
            gap.generated_residues,
        )
        for atom in canonical_heavy_atom_identities(residue, _one_to_three(
            target_by_chain[gap.chain][target_index]
        ))
    )
    links = tuple(
        ExplicitLink(first, second, "PDB")
        for first, second in sorted(_parse_explicit_links(lines, atoms))
    )
    try:
        heterogen_contexts = build_smiles_heterogen_contexts(
            text,
            heterogen_smiles or {},
        )
    except HeterogenContextError as exc:
        raise DiffusionCliError(str(exc)) from exc
    return DiffusionRequest(
        schema_version=DIFFUSION_SCHEMA_VERSION,
        normalized_pdb=ArtifactReference(input_path.name, hashlib.sha256(source).hexdigest()),
        target_sequences=tuple(targets),
        sequence_placements=tuple(placements),
        gaps=tuple(gap_regions),
        fixed_atoms=fixed_atoms,
        generated_atoms=generated_atoms,
        retained_explicit_links=links,
        candidate_count=len(seeds),
        seeds=seeds,
        backend_options=(BackendOption("profile", profile),),
        heterogen_contexts=heterogen_contexts,
        template_ownership=template_ownership,
    )


def _allocate_generated_residues(
    chain: str,
    left_anchor: ResidueIdentity,
    right_anchor: ResidueIdentity,
    gap_length: int,
    occupied: set[ResidueIdentity],
) -> tuple[ResidueIdentity, ...]:
    """Allocate gap identities without changing any observed residue identity."""
    left_number = int(left_anchor.residue_number)
    right_number = int(right_anchor.residue_number)
    numeric = tuple(
        ResidueIdentity(chain, str(left_number + offset))
        for offset in range(1, gap_length + 1)
    )
    if left_number + gap_length < right_number and not set(numeric) & occupied:
        return numeric

    insertion_codes = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if left_anchor.insertion_code:
        try:
            first_code = insertion_codes.index(left_anchor.insertion_code) + 1
        except ValueError as exc:
            raise DiffusionCliError(
                "diffusion cannot allocate generated residues after this insertion code"
            ) from exc
    else:
        first_code = 0
    last_code = first_code + gap_length
    if last_code > len(insertion_codes):
        raise DiffusionCliError("diffusion cannot allocate insertion codes for the gap")
    if right_number < left_number:
        raise DiffusionCliError("diffusion requires increasing PDB residue numbering")
    if right_number == left_number:
        try:
            right_code = insertion_codes.index(right_anchor.insertion_code)
        except ValueError as exc:
            raise DiffusionCliError(
                "diffusion cannot allocate generated residues before the right anchor"
            ) from exc
        if last_code > right_code:
            raise DiffusionCliError(
                "input numbering does not leave enough insertion codes for the gap"
            )
    generated = tuple(
        ResidueIdentity(chain, left_anchor.residue_number, code)
        for code in insertion_codes[first_code:last_code]
    )
    if set(generated) & occupied:
        raise DiffusionCliError("generated residue numbering collides with observed residues")
    return generated


def _allocate_terminal_generated_residues(
    chain: str,
    anchor: ResidueIdentity,
    gap_length: int,
    occupied: set[ResidueIdentity],
    *,
    n_terminal: bool,
) -> tuple[ResidueIdentity, ...]:
    """Allocate ordered one-anchor terminal identities in the PDB resSeq range."""
    anchor_number = int(anchor.residue_number)
    numbers = (
        range(anchor_number - gap_length, anchor_number)
        if n_terminal
        else range(anchor_number + 1, anchor_number + gap_length + 1)
    )
    generated = tuple(ResidueIdentity(chain, str(number)) for number in numbers)
    if any(not -999 <= int(residue.residue_number) <= 9999 for residue in generated):
        raise DiffusionCliError(
            "terminal residue numbering exceeds the PDB resSeq field"
        )
    if set(generated) & occupied:
        raise DiffusionCliError("terminal residue numbering collides with observed residues")
    return generated


def run_diffusion_model(args: argparse.Namespace) -> None:
    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        raise DiffusionCliError(f"input file does not exist: {input_path}")
    output_value = args.output
    output_path = (
        Path(output_value).resolve()
        if output_value
        else input_path.with_name(input_path.stem + "_model_diffusion")
    )
    resume = getattr(args, "diffusion_resume", False)
    if (output_path.exists() or output_path.is_symlink()) and not resume:
        raise DiffusionCliError(f"diffusion output directory already exists: {output_path}")

    work_parent_value = args.diffusion_work_parent
    work_parent = (
        Path(work_parent_value).expanduser().resolve()
        if work_parent_value
        else output_path.parent
    )
    if not work_parent.is_dir():
        raise DiffusionCliError(f"diffusion work parent is not a directory: {work_parent}")

    request_value = getattr(args, "diffusion_request", None)
    frozen_request: DiffusionRequest | None = None
    source_root = input_path.parent
    if request_value:
        request_path = Path(request_value).expanduser().resolve()
        if not request_path.is_file():
            raise DiffusionCliError(f"diffusion request does not exist: {request_path}")
        limits = RunnerLimits(timeout_seconds=args.diffusion_timeout)
        if request_path.stat().st_size > limits.max_manifest_bytes:
            raise DiffusionCliError("diffusion request exceeds the manifest size limit")
        try:
            with request_path.open("rb") as stream:
                request_bytes = stream.read(limits.max_manifest_bytes + 1)
            if len(request_bytes) > limits.max_manifest_bytes:
                raise DiffusionCliError("diffusion request exceeds the manifest size limit")
            frozen_request = DiffusionRequest.from_json(request_bytes.decode("utf-8"))
        except (DiffusionContractError, OSError, UnicodeDecodeError) as exc:
            raise DiffusionCliError(f"invalid diffusion request: {exc}") from exc
        source_root = request_path.parent
        referenced_input = (source_root / frozen_request.normalized_pdb.path).resolve()
        if referenced_input != input_path:
            raise DiffusionCliError(
                "input must be the normalized PDB referenced by --diffusion-request"
            )

    try:
        runtime = resolve_diffusion_runtime(args.diffusion_model)
    except DiffusionRuntimeError as exc:
        raise DiffusionCliError(str(exc)) from exc
    if frozen_request is not None:
        requested_profile = next(
            (
                option.value
                for option in frozen_request.backend_options
                if option.name == "profile"
            ),
            "",
        )
        if requested_profile and requested_profile != runtime.profile:
            raise DiffusionCliError(
                "diffusion request profile does not match the selected runtime"
            )
        if not requested_profile:
            if args.diffusion_model is None:
                raise DiffusionCliError(
                    "legacy diffusion request without a profile requires "
                    "--diffusion-model"
                )
            frozen_request = replace(
                frozen_request,
                backend_options=(
                    *frozen_request.backend_options,
                    BackendOption("profile", runtime.profile),
                ),
            )

    with ExitStack() as resources:
        model_input = input_path
        if frozen_request is None and not args.keep_heterogens:
            from dvbfixer.model.pipeline import _strip_hetatm_lines

            prep_root = Path(resources.enter_context(tempfile.TemporaryDirectory(
                prefix=".dvbfixer-diffusion-input.",
                dir=work_parent,
            )))
            model_input = prep_root / input_path.name
            lines = input_path.read_text(encoding="utf-8").splitlines(keepends=True)
            model_input.write_text(
                "".join(_strip_hetatm_lines(lines, keep_water=False, verbose=args.verbose)),
                encoding="utf-8",
            )
        if frozen_request is None:
            source_root = model_input.parent

        if frozen_request is None:
            target_sequences = _target_sequences(model_input, args.fasta)
            try:
                heterogen_smiles = parse_smiles_mappings(
                    getattr(args, "diffusion_heterogen_smiles", ())
                )
            except SmilesPreparationError as exc:
                raise DiffusionCliError(str(exc)) from exc
            request = build_cli_diffusion_request(
                model_input,
                target_sequences,
                seeds=tuple(args.diffusion_seeds),
                profile=runtime.profile,
                no_terminal=getattr(args, "no_terminal", False),
                heterogen_smiles=heterogen_smiles,
                template_ownership=getattr(args, "diffusion_template_ownership", ()),
            )
        else:
            request = frozen_request
        context_mode = getattr(args, "diffusion_context", "none")
        if context_mode != "none":
            if runtime.model != "protenix":
                raise DiffusionCliError("explicit protein context-v1 is currently supported by Protenix only")
            from dvbfixer.model.diffusion.contract import ProteinContextPolicy
            from dvbfixer.model.diffusion.protein_context import (
                ProteinContextError,
                select_protein_context,
            )

            policy = (ProteinContextPolicy(target_flanks=8, same_chain_spatial=True) if context_mode == "local"
                      else ProteinContextPolicy(partner_mode="full"))
            try:
                request = select_protein_context(request, model_input.read_bytes(), policy)
            except ProteinContextError as exc:
                raise DiffusionCliError(f"unsupported protein context: {exc}") from exc
        try:
            admission = assess_diffusion_scope(request, model_input.read_bytes())
        except DiffusionScopeError as exc:
            raise DiffusionCliError(str(exc)) from exc
        if not admission.supported:
            raise DiffusionCliError(
                "diffusion input is outside the supported scope: "
                + ", ".join(admission.reasons)
            )
        if resume and output_path.exists():
            from dvbfixer.model.diffusion.publication import read_published_bundle

            published = read_published_bundle(
                output_path, request=request, source_root=source_root, work_parent=work_parent,
            )
            print(f"Reused verified diffusion bundle {output_path} ({published.status})")
            return
        if runtime.model == "protpardelle" and len(request.target_sequences) > 1:
            sampled_chains = tuple(dict.fromkeys(gap.chain for gap in request.gaps))
            print(
                "WARNING: Protpardelle will reconstruct gaps using "
                f"{len(sampled_chains)} independent chain-level sampler "
                "invocation(s), then DVBFixer will merge the generated regions "
                "and restore fixed atoms exactly. Each invocation may include a "
                "bounded crop of nearby fixed partner-chain residues as local "
                "denoiser context; the gap-bearing chains are not jointly sampled, "
                "and distant or omitted partner regions do not condition it."
            )

        preflight = invoke_runner_preflight(
            profile=runtime.profile,
            runner=runtime.runner,
            timeout_seconds=args.diffusion_timeout,
        )
        if not preflight.passed:
            reasons = "; ".join(
                f"{issue.code.value}: {issue.message}" for issue in preflight.issues
            )
            raise DiffusionCliError(f"diffusion runner preflight failed: {reasons}")
        command = (
            runtime.runner,
            "--profile",
            runtime.profile,
        )
        outcome = run_diffusion_pipeline(
            request,
            command,
            source_root=source_root,
            work_parent=work_parent,
            destination_bundle=output_path,
            limits=RunnerLimits(timeout_seconds=args.diffusion_timeout),
        )
        if outcome.published_bundle is None:
            raise DiffusionCliError(
                outcome.message or f"diffusion ended with {outcome.status.value}"
            )
    if outcome.status.value == "failed":
        failures = tuple(dict.fromkeys(
            failure
            for summary in (outcome.result.validation_summaries if outcome.result else ())
            for failure in summary.hard_gate_failures
        ))
        print(
            "WARNING: Diffusion candidate was published but failed independent "
            "DVBFixer validation. Inspect it before use; consider another seed "
            "or a full-system minimization. Failed gates: "
            + (", ".join(failures) if failures else "unspecified")
        )
        print(f"Wrote rejected diffusion bundle {outcome.published_bundle}")
    else:
        print(f"Wrote diffusion bundle {outcome.published_bundle}")


def _target_sequences(input_path: Path, fasta_path: str | None) -> dict[str, str]:
    from dvbfixer.model.pipeline import parse_fasta, parse_seqres

    if fasta_path:
        return {chain: sequence.upper() for chain, sequence in parse_fasta(fasta_path).items()}
    seqres = parse_seqres(input_path.read_text(encoding="utf-8").splitlines())
    if not seqres:
        raise DiffusionCliError("diffusion requires SEQRES records or --fasta")
    return {
        chain: "".join(AA3TO1.get(residue, "X") for residue in residues)
        for chain, residues in seqres.items()
    }


def _one_to_three(one_letter: str) -> str:
    matches = [name for name, letter in AA3TO1.items() if letter == one_letter and name in {
        "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
        "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
    }]
    if not matches:
        raise DiffusionCliError(f"non-canonical target residue is unsupported: {one_letter}")
    return matches[0]
