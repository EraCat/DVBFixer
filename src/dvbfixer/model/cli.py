"""CLI parsing + shared constants for ``dvbfixer model``.

Split out of the flat ``model.py`` in Phase 2.2 of the revision plan.
Argparse only — no OpenMM / Modeller imports at module scope. Shared
tables (``AA3TO1``, ``WATER_RESNAMES``) live here so both the numbering
helpers and the pipeline can import them without a circular dep.
"""

from __future__ import annotations

import argparse
import math
import sys

from dvbfixer.cli_types import positive_int

AA3TO1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    # Nonstandard / protonation variants
    "MSE": "M", "HSD": "H", "HSE": "H", "HSP": "H",
    "HID": "H", "HIE": "H", "HIP": "H",
    "CYX": "C", "CYM": "C", "ASH": "D", "GLH": "E", "LYN": "K",
}

WATER_RESNAMES = {"HOH", "WAT", "TIP3", "TIP", "SOL", "T3P", "T4P", "T5P"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="dvbfixer model",
        description="Rebuild missing loops and gaps in a PDB structure. "
        "Identifies gaps from SEQRES vs ATOM records (or a provided FASTA), "
        "then uses MODELLER by default or an explicit experimental diffusion runner."
    )
    io = p.add_argument_group("Input / output")
    io.add_argument("input", help="Input PDB or PDBx/mmCIF file (must contain polymer sequence metadata or use --fasta)")
    io.add_argument(
        "-o",
        "--output",
        help="MODELLER output PDB, or a new directory bundle for diffusion "
        "(defaults: <input>_model.pdb or <input>_model_diffusion)",
    )
    io.add_argument(
        "--fasta", help="FASTA file with complete sequence(s). Headers must encode "
        "chain IDs: '>chain_X', '>PDBID_X', or '>X'. Mapping is by chain ID, "
        "not file order. Use instead of SEQRES."
    )

    backend = p.add_argument_group("Backend")
    backend.add_argument(
        "--backend",
        choices=("modeller", "diffusion"),
        default="modeller",
        help="Modeling backend (default: modeller; diffusion is experimental)",
    )

    diffusion = p.add_argument_group("Diffusion options")
    diffusion.add_argument(
        "--diffusion-model",
        choices=("protpardelle", "protenix"),
        help="Diffusion model (default: select an installed model for this machine)",
    )
    diffusion.add_argument(
        "--diffusion-request",
        help="Use an existing schema-4 diffusion request instead of reconstructing "
        "sequence placement and masks from FASTA/SEQRES",
    )
    diffusion.add_argument(
        "--diffusion-seed",
        action="append",
        type=int,
        dest="diffusion_seeds",
        help="Candidate seed; repeat for multiple candidates (default: 7)",
    )
    diffusion.add_argument(
        "--diffusion-timeout",
        type=float,
        default=900.0,
        help="Runner timeout in seconds (default: 900; covers multi-chain sampling/refinement)",
    )
    diffusion.add_argument(
        "--diffusion-work-parent",
        help="Parent directory for the private runner workspace",
    )
    diffusion.add_argument(
        "--diffusion-resume", action="store_true",
        help="Reuse an existing digest-verified bundle only when its scientific request matches",
    )
    diffusion.add_argument(
        "--diffusion-context", choices=("auto", "none", "local", "full"), default="auto",
        help="Protein context: auto uses local for Protpardelle CUDA and the legacy path for other profiles (default: auto)",
    )
    diffusion.add_argument(
        "--diffusion-heterogen-smiles",
        action="append",
        default=[],
        metavar="RESNAME=SMILES",
        help="Authoritative SMILES for a retained isolated HETATM residue; repeat "
        "for multiple residue names (Protpardelle fixed geometric context only)",
    )

    modelling = p.add_argument_group("Modelling parameters")
    modelling.add_argument(
        "-n", "--num-models", type=positive_int, default=1,
        help="Number of initial models to generate (default: 1)"
    )
    modelling.add_argument(
        "--num-loops", type=positive_int, default=2,
        help="Number of loop refinement models per initial model (default: 2)"
    )
    modelling.add_argument(
        "--num-output", type=positive_int, default=1, dest="num_output",
        help="Number of top-ranked candidate models to save (default: 1; "
             "ceiling: num_models × num_loops). Output PDBs are sorted "
             "ascending by Modeller's molpdf score (best first). With "
             "--num-output > 1, output filenames get a _N suffix: "
             "<stem>_model_1.pdb, _model_2.pdb, ... (and matching .dat). "
             "With --num-output 1 the filename is unchanged from today."
    )
    modelling.add_argument(
        "--md-level", choices=["none", "fast", "slow", "very_slow", "slow_large"],
        default="fast",
        help="MD refinement level for loop modeling (default: fast)"
    )
    modelling.add_argument(
        "--pin-input", dest="pin_input",
        action=argparse.BooleanOptionalAction, default=True,
        help="During Modeller's loop refinement MD, allow only the "
             "newly-modeled gap residues to move — no ±flank margin. "
             "Default ON: prevents flanking-residue drift; the initial "
             "automodel CG still runs on all atoms so any input close "
             "contacts get relaxed normally. Pass --no-pin-input for the "
             "legacy LoopModel behaviour (gap ±~3 residue flank mobile)."
    )
    modelling.add_argument(
        "--no-terminal", action="store_true",
        help="Do not model missing N/C terminal residues. Align to the complete "
             "reference first, trim outside the first/last observed anchors, "
             "and rebuild only gaps between those anchors. Supported by both "
             "MODELLER and diffusion backends."
    )
    modelling.add_argument(
        "--number-from-1", action="store_true",
        help="Shift each completed output chain so its first retained protein residue is 1; "
             "applies even when missing N-terminal residues were not modeled",
    )
    content = p.add_argument_group("Content selection")
    content.add_argument(
        "--keep-water", action="store_true",
        help="Keep water molecules (HOH, WAT, TIP3, SOL) in output (default: remove)"
    )
    content.add_argument(
        "--strip-heterogens", dest="keep_heterogens",
        action="store_false", default=True,
        help="Remove all HETATM records (ligands, sugars, ions, cofactors) "
             "before modeling. Waters are also removed unless "
             "--keep-water is passed (MODELLER only). Off by default — MODELLER usually "
             "benefits from heterogen context for loop refinement, but "
             "in some cases (bad ligand geometry, ambiguous CONECT) they "
             "cause artifacts.",
    )
    content.add_argument(
        "--no-infer-conect", dest="no_infer_conect", action="store_true",
        help="Skip automatic CONECT inference before Modeller runs. "
             "Default: infer missing CONECT bonds (SS/glycosidic/"
             "glycosylation) from coordinates first, so an under-"
             "annotated glycosylation site (real bond, but no CONECT/LINK "
             "in the deposited PDB) doesn't get repositioned arbitrarily "
             "far from its anchor during modeling — Modeller has no way "
             "to know two chains are covalently linked unless a bond is "
             "already documented before it runs.",
    )

    diag = p.add_argument_group("Diagnostics")
    diag.add_argument(
        "--keep-workdir", action="store_true",
        help="Keep the Modeller working directory (for debugging)"
    )
    diag.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print Modeller progress"
    )

    from dvbfixer.batch import add_runtime_help
    add_runtime_help(p, batch=True)
    args = p.parse_args(argv)
    _validate_backend_options(p, args, list(sys.argv[1:] if argv is None else argv))
    return args


def _validate_backend_options(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    argv: list[str],
) -> None:
    diffusion_options = {
        "--diffusion-model",
        "--diffusion-request",
        "--diffusion-seed",
        "--diffusion-timeout",
        "--diffusion-work-parent",
        "--diffusion-resume",
        "--diffusion-context",
        "--diffusion-heterogen-smiles",
    }
    provided = {token.split("=", 1)[0] for token in argv if token.startswith("-")}
    if args.backend == "modeller":
        invalid = sorted(provided & diffusion_options)
        if invalid:
            parser.error(
                f"{', '.join(invalid)} require --backend diffusion"
            )
        return

    if not math.isfinite(args.diffusion_timeout) or args.diffusion_timeout <= 0:
        parser.error("--diffusion-timeout must be a positive finite number")
    seeds = args.diffusion_seeds or [7]
    if any(seed < 0 for seed in seeds) or len(seeds) != len(set(seeds)):
        parser.error("--diffusion-seed values must be unique non-negative integers")
    args.diffusion_seeds = seeds

    if args.diffusion_request:
        construction_options = {
            "--fasta",
            "--diffusion-seed",
            "--diffusion-heterogen-smiles",
            "--no-terminal",
            "--strip-heterogens",
            "--diffusion-context",
        }
        invalid = sorted(provided & construction_options)
        if invalid:
            parser.error(
                f"{', '.join(invalid)} cannot be combined with --diffusion-request"
            )

    modeller_only = {
        "-n", "--num-models", "--num-loops", "--num-output", "--md-level",
        "--pin-input", "--no-pin-input", "--number-from-1",
        "--keep-water", "--no-infer-conect", "--keep-workdir",
    }
    invalid = sorted(provided & modeller_only)
    if invalid:
        parser.error(
            f"{', '.join(invalid)} are not supported with --backend diffusion"
        )
