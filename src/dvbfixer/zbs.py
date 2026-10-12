"""Full pipeline: renumber → model → prepare (PROPKA + Reduce) → minimize.

Runs the complete PDB preparation workflow in sequence, passing output
of each step as input to the next.

As of 0.7.7, PROPKA + MolProbity Reduce run **inside** the prepare
step: PROPKA drives pKa-dependent variant renames (ASH/GLH/HIP/LYN/
CYM/CYX) and Reduce picks the HIS tautomer (HID/HIE) + flags ASN/GLN
amide flips. There is no separate `protonate` step in the pipeline
anymore. Standalone `dvbfixer protonate` still exists as a post-hoc
re-protonation tool if the user wants to re-run PROPKA/Reduce on an
already-prepared PDB (e.g. to switch pH).

minimize.py preserves AMBER variant names on output via its
`_input_variants` capture-restore path, so no final "re-apply names"
step is needed after minimize.
"""

import argparse
import math
import sys
from pathlib import Path

from dvbfixer.cli_types import nonnegative_float, nonnegative_int, positive_int


class PostflightError(RuntimeError):
    """The final structure could not pass or complete validation."""


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="dvbfixer zbs",
        description="Run the full preparation pipeline: "
        "renumber -> model -> prepare -> minimize. PROPKA + MolProbity "
        "Reduce run inside the prepare step (0.7.7+); there is no "
        "separate protonate stage.",
    )
    io = p.add_argument_group("Input / output")
    io.add_argument("input", help="Input PDB or PDBx/mmCIF file (use --fasta when polymer sequence metadata is absent or incomplete)")
    io.add_argument("-o", "--output", help="Final output PDB file (default: <input>_zbs.pdb)")

    ff = p.add_argument_group("Force field")
    ff.add_argument("--ph", type=float, default=7.0,
                    help="pH for protonation and hydrogen addition (default: 7.0)")
    ff.add_argument("--ff", nargs='+', default=['auto'],
                    help="Force field selection forwarded to prepare / "
                         "minimize. Accepts a short name (auto, "
                         "amber, amber+glycam, charmm, ...) or an explicit "
                         "list of OpenMM XML paths. Default: 'auto'. "
                         "See docs/force-fields.md.")
    ff.add_argument("--atom-naming", choices=["gromacs", "standard"],
                    default="gromacs",
                    help="Atom-naming convention for the final output PDB. "
                         "'gromacs' (default): rewrite atom names to "
                         "GROMACS amber99sb-ildn conventions (HB3→HB1, "
                         "HZ3→HZ1 on LYN, O→OC2, OXT→OC1). 'standard': "
                         "keep IUPAC/AMBER-native names. Propagated to "
                         "prepare + minimize.")
    ff.add_argument("--parametrize-ligands", action="store_true",
                    help="Forward --parametrize-ligands to the minimize "
                         "step (GAFF2 + AM1-BCC for unknown ligands via "
                         "antechamber). See docs/force-fields.md.")
    ff.add_argument(
        "--extra-ff", action="append", default=[], metavar="FILE",
        help="Additional OpenMM XML template/force-field file; repeatable and "
             "forwarded to minimize after --ff.",
    )

    skip = p.add_argument_group("Pipeline skip flags")
    skip.add_argument("--skip-renumber", action="store_true",
                      help="Skip the renumber step")
    skip.add_argument("--skip-model", action="store_true",
                      help="Skip the model step")
    skip.add_argument("--skip-prepare", action="store_true",
                      help="Skip the prepare step")
    skip.add_argument("--skip-minimize", action="store_true",
                      help="Skip the minimize step")

    model_grp = p.add_argument_group("Model step")
    model_grp.add_argument("--model-backend", choices=["modeller", "diffusion"], default="modeller",
                           help="Modeling backend; independent of the prepare --backend (default: modeller)")
    model_grp.add_argument("--diffusion-model", choices=["protenix", "protpardelle"],
                           help="Installed diffusion model (default: host-compatible auto selection)")
    model_grp.add_argument("--diffusion-seed", action="append", type=int, dest="diffusion_seeds",
                           help="Candidate seed; repeat for multiple candidates (default: 7)")
    model_grp.add_argument("--diffusion-timeout", type=float, default=900.0,
                           help="Diffusion runner timeout in seconds (default: 900)")
    model_grp.add_argument("--diffusion-work-parent", help="Existing parent for private diffusion workspaces")
    model_grp.add_argument("--diffusion-resume", action="store_true",
                           help="Reuse a verified model bundle matching the current scientific request")
    model_grp.add_argument("--fasta", help="FASTA file with complete sequence(s) for model step")
    model_grp.add_argument("--no-terminal", action="store_true",
                           help="Do not model missing N/C terminal residues; "
                                "rebuild only gaps between observed anchors")
    model_grp.add_argument("--num-loops", type=positive_int, default=2,
                           help="Number of loop models (default: 2)")
    model_grp.add_argument("--md-level", choices=["none", "fast", "slow", "very_slow", "slow_large"],
                           default="fast", help="Modeller MD refinement level (default: fast)")
    model_grp.add_argument("--num-output", type=positive_int, default=1, dest="num_output",
                           help="Save top-N candidate models from Modeller (default: 1). "
                                "With N>1, the model step writes <stem>_model_1.pdb, "
                                "..._2.pdb, ... zbs picks _1 (best) for downstream.")
    model_grp.add_argument("--pin-input", dest="pin_input",
                           action=argparse.BooleanOptionalAction, default=True,
                           help="During Modeller's loop refinement MD, allow only "
                                "the gap residues to move (no ±flank margin). "
                                "Default ON — pass --no-pin-input to restore the "
                                "legacy LoopModel behaviour (gap ±~3 residue flank "
                                "mobile).")

    prep = p.add_argument_group("Prepare step")
    prep.add_argument("--strip-heterogens", dest="keep_heterogens",
                      action="store_false", default=True,
                      help="Strip heterogens before processing (protein-only pipeline). "
                           "Default: keep heterogens through prepare and minimize the whole system.")
    prep.add_argument("--backend", choices=["tleap-reduce", "legacy"],
                      default="legacy",
                      help="Prep backend, forwarded to prepare. 'legacy' "
                           "(default): PDBFixer + Modeller.addHydrogens; "
                           "handles glycans, ligands, heterogens and "
                           "covalent-HETATM links. 'tleap-reduce': opt-in "
                           "deterministic AmberTools + MolProbity pipeline "
                           "(tleap for heavy atoms, reduce for H). "
                           "Pure-protein only — rejects non-canonical "
                           "residues and is incompatible with --mutate.")
    prep.add_argument("--no-heterogen-h", dest="heterogen_h",
                      action="store_false", default=True,
                      help="Skip hydrogen addition for heterogens in prepare "
                           "(default: add H to heterogens BioLuminate-style).")
    prep.add_argument(
        "--smiles", action="append", default=[], metavar="RESNAME=SMILES",
        help="Optional SMILES chemistry for an isolated ligand residue; "
             "repeatable and forwarded to prepare. Unmapped ligands keep "
             "the existing automatic preparation path.",
    )
    prep.add_argument("--mutate", action="append", default=[],
                      metavar="CHAIN:RESNUM:NEW_AA",
                      help="Mutate a residue during prepare step (can be used multiple times)")
    prep.add_argument("--rename", action="store_true",
                      help="Canonicalise non-standard residue names before prepare/minimize.")
    prep.add_argument("--cap-termini", action="store_true",
                      help="Add neutral ACE/NME caps during prepare. Applies to "
                           "all protein chains unless --cap-chain is supplied.")
    prep.add_argument("--cap-chain", action="append", default=[], metavar="CHAIN",
                      help="Protein chain to cap (repeatable; '_' means blank chain).")

    minz = p.add_argument_group("Minimize step (OpenMM)")
    minz.add_argument("--no-solvent", action="store_true",
                      help="Minimize in vacuum (no solvent box)")
    minz.add_argument("--rebuild-h", action="store_true",
                      help="Force --rebuild-h on the minimize step (default: off; "
                           "prepare already produced correct H via PROPKA/Reduce)")
    minz.add_argument("--restraint-k", type=nonnegative_float, default=100.0,
                      help="Restraint force constant for original atoms (default: 100)")
    minz.add_argument("--max-iter", type=nonnegative_int, default=1000,
                      help="Max minimization iterations per phase (default: 1000)")
    minz.add_argument("--refine", choices=["none", "xtb", "obminimize"], default="none",
                      help="Post-minimize refinement pass in the minimize step "
                           "(default: none). 'xtb' uses GFN-FF, 'obminimize' uses "
                           "OpenBabel UFF.")
    minz.add_argument("--refine-heterogens-only", action="store_true",
                      help="Restrict --refine pass to heterogen residues "
                           "(protein backbone frozen). Only meaningful with "
                           "--refine != none.")

    prot = p.add_argument_group("Protonation (PROPKA + Reduce, inside prepare)")
    prot.add_argument("--no-propka", dest="propka",
                      action="store_false", default=True,
                      help="Skip PROPKA3 during prepare. Reduce "
                           "(--protassign) becomes the only source of HIS "
                           "tautomer picks and ASN/GLN flip detection. "
                           "Combining --no-propka with --no-protassign "
                           "leaves variants=[--mutate only] — no pKa-driven "
                           "ASH/GLH/HIP/LYN/CYM in output.")
    prot.add_argument("--no-protassign", dest="protassign",
                      action="store_false", default=True,
                      help="Skip MolProbity Reduce (HIS tautomer / ASN-GLN flip "
                           "detection) during prepare. Default: run Reduce.")
    prot.add_argument("--his-default", choices=["HIE", "HID"], default="HIE",
                      help="Default HIS tautomer when PROPKA says neutral "
                           "AND Reduce didn't place either HD1 or HE2. "
                           "Default: HIE.")
    prot.add_argument("--cys-ss-pka", type=float, default=99.99,
                      help="PROPKA disulfide-sentinel cutoff for CYS -> CYX "
                           "(default: 99.99). This does not override predicted "
                           "pKa: pKa below --ph still gives thiolate CYM. Explicit "
                           "CONECT-detected SS pairs override PROPKA regardless.")

    general = p.add_argument_group("Pipeline behaviour")
    general.add_argument("--keep-water", action="store_true",
                         help="Keep water molecules in output (default: remove)")
    general.add_argument("--no-infer-conect", dest="no_infer_conect",
                         action="store_true",
                         help="Skip automatic CONECT inference in model/prepare/"
                              "minimize. Default: infer missing CONECT bonds "
                              "(SS/glycosidic/glycosylation) from coordinates.")
    general.add_argument("--keep-interim", action="store_true",
                         help="Keep all intermediate files (default: only final output)")
    general.add_argument("--dry-run", action="store_true",
                         help="Print the planned pipeline steps + output "
                              "filenames without running anything. Useful "
                              "when many skip flags are in play.")
    general.add_argument("--number-from-1", action="store_true",
                         help="Shift each final output chain so its first retained protein residue is 1")
    general.add_argument("--no-postflight", action="store_true",
                         help="Skip the final diagnose quality gate. By default, "
                              "zbs writes <output>.diagnose.json and warns if "
                              "diagnose reports an ERROR.")
    general.add_argument("--postflight-report",
                         help="Path for the final diagnose JSON report "
                              "(default: <output>.diagnose.json).")
    general.add_argument("--strict-postflight", action="store_true",
                         help="Fail the pipeline when postflight diagnose reports "
                              "ERROR findings. Default: write the report and warn.")
    general.add_argument("--align-to-input", dest="align_to_input",
                         action=argparse.BooleanOptionalAction, default=True,
                         help="After every pipeline step, Kabsch-align the output "
                              "back to the ORIGINAL input on protein backbone "
                              "atoms. Prevents accumulated rigid-body drift so "
                              "residue-by-residue comparisons in a viewer line up. "
                              "Default ON — pass --no-align-to-input for the "
                              "legacy behaviour (each step's output in its own "
                              "frame).")

    runtime = p.add_argument_group("Runtime")
    runtime.add_argument("--platform", choices=["CPU", "CUDA", "OpenCL", "Reference"],
                         help="OpenMM platform (default: auto)")
    runtime.add_argument("-v", "--verbose", action="store_true",
                         help="Print detailed progress for all steps")

    from dvbfixer.batch import add_runtime_help
    add_runtime_help(p, batch=True)
    args = p.parse_args(argv)
    provided = {token.split("=", 1)[0] for token in (sys.argv[1:] if argv is None else argv) if token.startswith("-")}
    diffusion_flags = {"--diffusion-model", "--diffusion-seed", "--diffusion-timeout", "--diffusion-work-parent", "--diffusion-resume"}
    if args.model_backend == "modeller" and provided & diffusion_flags:
        p.error("diffusion options require --model-backend diffusion")
    if args.model_backend == "diffusion":
        if args.skip_model:
            p.error("--model-backend diffusion cannot be combined with --skip-model")
        if provided & {"--num-loops", "--md-level", "--num-output", "--pin-input", "--no-pin-input"}:
            p.error("Modeller modeling options are incompatible with --model-backend diffusion")
        seeds = args.diffusion_seeds or [7]
        if any(seed < 0 for seed in seeds) or len(seeds) != len(set(seeds)):
            p.error("diffusion seeds must be unique non-negative integers")
        if not math.isfinite(args.diffusion_timeout) or args.diffusion_timeout <= 0:
            p.error("diffusion timeout must be positive and finite")
        args.diffusion_seeds = seeds

    if args.backend == "tleap-reduce" and args.mutate:
        p.error("--mutate is not supported by the tleap-reduce backend; "
                "rerun with --backend legacy for mutations.")
    if args.cap_chain and not args.cap_termini:
        p.error("--cap-chain requires --cap-termini")
    if args.cap_termini and args.skip_prepare:
        p.error("--cap-termini cannot be used with --skip-prepare")
    if args.smiles:
        if args.skip_prepare:
            p.error("--smiles cannot be used with --skip-prepare")
        if args.backend != "legacy":
            p.error("--smiles requires --backend legacy")
        if not args.keep_heterogens:
            p.error("--smiles cannot be used with --strip-heterogens")
        if not args.heterogen_h:
            p.error("--smiles cannot be used with --no-heterogen-h")

    return args


def main(argv=None):
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"File not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    try:
        _run_pipeline(args, input_path)
    except PostflightError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(3)
    except _lazy_import_chirality_error() as e:
        print(f"\nERROR: chirality guard tripped in the zbs pipeline.\n"
              f"{e}\n"
              f"Downstream MD would produce nonsense on a D-Cα residue; "
              f"fix the upstream model / prepare / minimize step or "
              f"rebuild the affected residue by hand.",
              file=sys.stderr)
        sys.exit(2)
    except _lazy_import_publication_error() as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)


def _lazy_import_publication_error():
    from dvbfixer.model.diffusion.publication import PublicationError
    return PublicationError


def _lazy_import_chirality_error():
    """Deferred import — keeps ``dvbfixer zbs --help`` free of the
    ffutils import chain (which pulls OpenMM)."""
    from dvbfixer.ffutils.geometry import ChiralityError
    return ChiralityError


def _print_dry_run(args, input_path, final_output):
    """Print the planned pipeline steps + outputs without running anything."""
    print("Planned zbs pipeline:")
    step = 1

    def _line(name, out_suffix, notes=""):
        nonlocal step
        out = str((final_output.parent / f"{input_path.stem}{out_suffix}")
                  .with_suffix(input_path.suffix))
        line = f"  {step}. {name:12s} → {Path(out).name}"
        if notes:
            line += f"   ({notes})"
        print(line)
        step += 1

    if not args.skip_renumber:
        _line("renumber", "_renum",
              "FASTA/SEQRES-based residue renumbering"
              + (", keep water" if args.keep_water else ""))
    if not args.skip_model:
        notes = ("diffusion bundle; first independently validated ranked candidate"
                 if args.model_backend == "diffusion" else f"Modeller LoopModel, --md-level {args.md_level}")
        if args.fasta:
            notes += f", --fasta {args.fasta}"
        if not args.pin_input:
            notes += ", --no-pin-input"
        if args.model_backend == "diffusion":
            print(f"  {step}. model        → {input_path.stem}_model_diffusion/   ({notes})")
            step += 1
        else:
            _line("model", "_model", notes)
    if not args.skip_prepare:
        notes = (f"backend: {args.backend} (PDBFixer + Modeller.addHydrogens)"
                  if args.backend == "legacy" else
                  f"backend: {args.backend} (AmberTools tleap + MolProbity reduce)")
        if not args.keep_heterogens:
            notes += ", --strip-heterogens"
        if args.mutate:
            notes += f", {len(args.mutate)} mutation(s)"
        _line("prepare", "_prepared", notes)
    if not args.skip_minimize:
        notes = "OpenMM ff14SB"
        if args.no_solvent:
            notes += ", --no-solvent"
        if args.rebuild_h:
            notes += ", --rebuild-h"
        if args.refine != "none":
            notes += f", --refine {args.refine}"
        _line("minimize", "_minimized", notes)

    print(f"  final       → {final_output.name}")
    if not args.no_postflight:
        report = args.postflight_report or f"{final_output}.diagnose.json"
        policy = "strict ERROR gate" if args.strict_postflight else "report + warning"
        print(f"  postflight  → {Path(report).name}   ({policy})")
    if args.verbose:
        interim_kept = "keep" if args.keep_interim else "delete"
        print(f"  (interim files: {interim_kept})")


def _run_pipeline(args, input_path):
    if args.output:
        final_output = Path(args.output)
    else:
        final_output = input_path.with_stem(input_path.stem + "_zbs")

    if getattr(args, "dry_run", False):
        _print_dry_run(args, input_path, final_output)
        return

    # Derive every named intermediate beside the final output.  This is
    # especially important in --input-dir mode: the source tree must remain
    # read-only while all run artifacts live below --output-dir.
    artifact_base = final_output.parent / input_path.stem
    current = str(input_path)
    step_num = 0
    interim_files = []  # files to clean up unless --keep-interim

    def step_output(name):
        path = str(artifact_base.with_name(artifact_base.name + f"_{name}")
                   .with_suffix(input_path.suffix))
        interim_files.append(path)
        # Also track .dat files that steps may produce
        interim_files.append(str(Path(path).with_suffix('.dat')))
        return path

    def _maybe_align(path):
        """Kabsch-superpose `path` onto the original input in-place.
        No-op if --no-align-to-input, or the file didn't get written,
        or the align helper couldn't match enough atoms."""
        if not args.align_to_input:
            return
        if not Path(path).exists():
            return
        try:
            from dvbfixer.align import kabsch_align_pdb
            kabsch_align_pdb(path, str(input_path), path,
                             selection='backbone', verbose=args.verbose)
        except Exception as e:
            print(f"  WARNING: align-to-input failed on {path} ({e}); "
                  f"leaving unaligned")

    # 1. Renumber
    if not args.skip_renumber:
        step_num += 1
        print(f"\n{'='*60}")
        print(f"Step {step_num}: RENUMBER")
        print(f"{'='*60}")
        from dvbfixer.renumber import main as renumber_main
        out = step_output("renum")
        renumber_argv = [current, "-o", out]
        if args.fasta:
            renumber_argv.extend(["--fasta", args.fasta])
        if args.keep_water:
            renumber_argv.append("--keep-water")
        if args.verbose:
            renumber_argv.append("-v")
        renumber_main(renumber_argv)
        _maybe_align(out)
        current = out

    # 2. Model
    if not args.skip_model:
        step_num += 1
        print(f"\n{'='*60}")
        print(f"Step {step_num}: MODEL")
        print(f"{'='*60}")
        from dvbfixer.model import main as model_main
        out = step_output("model")
        if args.model_backend == "diffusion":
            bundle = artifact_base.with_name(artifact_base.name + "_model_diffusion")
            model_argv = [current, "-o", str(bundle), "--backend", "diffusion",
                          "--diffusion-timeout", str(args.diffusion_timeout)]
            if args.diffusion_model:
                model_argv.extend(["--diffusion-model", args.diffusion_model])
            for seed in args.diffusion_seeds:
                model_argv.extend(["--diffusion-seed", str(seed)])
            if args.diffusion_work_parent:
                model_argv.extend(["--diffusion-work-parent", args.diffusion_work_parent])
            if args.diffusion_resume:
                model_argv.append("--diffusion-resume")
        else:
            model_argv = [current, "-o", out,
                          "--num-loops", str(args.num_loops),
                          "--md-level", args.md_level,
                          "--num-output", str(args.num_output)]
        if args.no_terminal:
            model_argv.append("--no-terminal")
        if args.fasta:
            model_argv.extend(["--fasta", args.fasta])
        if not args.pin_input:
            model_argv.append("--no-pin-input")
        # Propagate the same heterogen policy zbs was invoked with, so
        # Modeller doesn't refine a loop against ligand/glycan context
        # the user has explicitly asked to strip downstream.
        if not args.keep_heterogens:
            model_argv.append("--strip-heterogens")
        if args.keep_water and args.model_backend == "modeller":
            model_argv.append("--keep-water")
        if args.no_infer_conect and args.model_backend == "modeller":
            model_argv.append("--no-infer-conect")
        if args.verbose:
            model_argv.append("-v")
        model_main(model_argv)
        if args.model_backend == "diffusion":
            from dvbfixer.model.diffusion.publication import copy_selected_candidate

            copy_selected_candidate(bundle, Path(out), resume=args.diffusion_resume)
        # With --num-output > 1, model writes _model_1.pdb, _model_2.pdb, ...
        # zbs picks the best (_1) for the downstream pipeline; other candidates
        # remain on disk for the user to inspect.
        if args.num_output > 1:
            multi_out = str(artifact_base.with_name(artifact_base.name + "_model_1")
                            .with_suffix(input_path.suffix))
            if Path(multi_out).exists():
                interim_files.append(multi_out)
                interim_files.append(str(Path(multi_out).with_suffix('.dat')))
                out = multi_out
        if args.model_backend == "modeller":
            _maybe_align(out)
        current = out

    # 3. Prepare
    if not args.skip_prepare:
        step_num += 1
        print(f"\n{'='*60}")
        print(f"Step {step_num}: PREPARE")
        print(f"{'='*60}")
        from dvbfixer.prepare import main as prepare_main
        out = step_output("prepared")
        prepare_argv = [current, "-o", out, "--ph", str(args.ph),
                        "--ff"] + args.ff
        prepare_argv.extend(["--atom-naming", args.atom_naming])
        prepare_argv.extend(["--backend", args.backend])
        # Propagate PROPKA + Reduce flags into prepare (0.7.7+: legacy
        # prepare now runs PROPKA + Reduce internally so the pipeline
        # emits pKa-driven ASH/GLH/HIP/LYN/CYM variants and per-residue
        # HIS tautomers).
        if not args.propka:
            prepare_argv.append("--no-propka")
        if not args.protassign:
            prepare_argv.append("--no-protassign")
        prepare_argv.extend(["--his-default", args.his_default])
        prepare_argv.extend(["--cys-ss-pka", str(args.cys_ss_pka)])
        if not args.keep_heterogens:
            prepare_argv.append("--strip-heterogens")
        if args.keep_water:
            prepare_argv.append("--keep-water")
        if not args.heterogen_h:
            prepare_argv.append("--no-heterogen-h")
        for mapping in args.smiles:
            prepare_argv.extend(["--smiles", mapping])
        for mut in args.mutate:
            prepare_argv.extend(["--mutate", mut])
        if args.rename:
            prepare_argv.append("--rename")
        if args.cap_termini:
            prepare_argv.append("--cap-termini")
            for chain in args.cap_chain:
                prepare_argv.extend(["--cap-chain", chain])
        if args.no_infer_conect:
            prepare_argv.append("--no-infer-conect")
        if args.verbose:
            prepare_argv.append("-v")
        prepare_main(prepare_argv)
        if args.model_backend == "diffusion":
            from dvbfixer.ffutils.dat import DatRecord

            upstream_dat = Path(current).with_suffix(".dat")
            downstream_dat = Path(out).with_suffix(".dat")
            if upstream_dat.exists():
                downstream = DatRecord.load(downstream_dat) if downstream_dat.exists() else DatRecord()
                carried = downstream.merge(DatRecord.load(upstream_dat))
                downstream.save(downstream_dat, verbose=False)
                if carried:
                    print(f"Carried {carried} modeled atoms into prepare restraint data")
        _maybe_align(out)
        current = out

    # 4. Minimize — single pass. Propagate the SAME FF alias that
    # prepare used, so both steps agree on force field selection. If
    # the user passed --ff auto, resolve it once here against the
    # pipeline input and pass the resolved short alias
    # (e.g. 'amber+glycam') to both prepare and minimize; propagating
    # the alias rather than expanded XML paths preserves each tool's
    # ability to run its own upgrade logic if a downstream step
    # transforms the residue set.
    _minimize_ff = list(args.ff)
    if not args.skip_minimize:
        step_num += 1
        print(f"\n{'='*60}")
        print(f"Step {step_num}: MINIMIZE")
        print(f"{'='*60}")
        from dvbfixer.minimize import main as minimize_main
        out = step_output("minimized")
        minimize_argv = [current, "-o", out,
                         "--ph", str(args.ph),
                         "--ff"] + _minimize_ff + [
                         "--restraint-k", str(args.restraint_k),
                         "--max-iter", str(args.max_iter),
                         "--atom-naming", args.atom_naming]
        if args.no_solvent:
            minimize_argv.append("--no-solvent")
        if args.keep_water:
            minimize_argv.append("--keep-water")
        if args.rebuild_h:
            minimize_argv.append("--rebuild-h")
        if not args.keep_heterogens:
            minimize_argv.append("--strip-heterogens")
        if args.rename:
            minimize_argv.append("--rename")
        if args.no_infer_conect:
            minimize_argv.append("--no-infer-conect")
        if args.parametrize_ligands:
            minimize_argv.append("--parametrize-ligands")
        for extra_ff in args.extra_ff:
            minimize_argv.extend(["--extra-ff", extra_ff])
        if args.refine == "xtb":
            minimize_argv.append("--xtb-refine")
        elif args.refine == "obminimize":
            minimize_argv.append("--obminimize-refine")
        if args.refine != "none" and args.refine_heterogens_only:
            minimize_argv.append("--refine-heterogens-only")
        if args.platform:
            minimize_argv.extend(["--platform", args.platform])
        if args.verbose:
            minimize_argv.append("-v")
        minimize_main(minimize_argv)
        _maybe_align(out)
        current = out

    # Copy last output to final destination
    if str(current) != str(final_output):
        import shutil
        shutil.copy2(current, final_output)

    if args.number_from_1:
        from dvbfixer.renumber import normalize_numbering_from_one

        deltas = normalize_numbering_from_one(final_output)
        shifted = ", ".join(f"{chain}:{delta:+d}" for chain, delta in deltas.items())
        print(f"Normalized final residue numbering ({shifted or 'no coordinate chains'})")

    if not args.no_postflight:
        report_path = Path(args.postflight_report or f"{final_output}.diagnose.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"\nRunning postflight structure diagnostics → {report_path}")
        from dvbfixer.diagnose import main as diagnose_main

        try:
            diagnose_main([
                str(final_output), "--format", "json", "--severity", "ERROR",
                "-o", str(report_path),
            ])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            if code == 1 and not args.strict_postflight:
                print(f"  WARNING: postflight diagnose reported ERROR findings; "
                      f"inspect {report_path}", file=sys.stderr)
            elif code != 0:
                raise PostflightError(
                    f"postflight diagnose failed with exit {code}; inspect {report_path}"
                ) from exc

    # Clean up interim files
    if not args.keep_interim:
        removed = 0
        for f in interim_files:
            p = Path(f)
            if p.exists() and p.resolve() != final_output.resolve():
                p.unlink()
                removed += 1
        if removed and args.verbose:
            print(f"Cleaned up {removed} interim file(s)")

    print(f"\n{'='*60}")
    print(f"Pipeline complete: {final_output}")
    print(f"{'='*60}")
