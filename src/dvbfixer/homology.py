"""Multi-template homology modeling with Modeller.

Takes a target FASTA (multi-chain) and one or more template PDB files.
Auto-aligns target to templates, builds a composite model using Modeller's
automodel/LoopModel with multiple knowns, then optionally runs prepare+minimize.

Antibody mode (--antibody): uses ANARCI for numbering/CDR detection.
"""

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

from dvbfixer.cli_types import positive_int
from dvbfixer.model import (
    AA3TO1,
    WATER_RESNAMES,
    parse_pir_sequence,
    remove_water_lines,
)

# ---------------------------------------------------------------------------
# FASTA parsing
# ---------------------------------------------------------------------------

def parse_fasta_chains(fasta_path, *, logical_ids=False):
    """Parse multi-chain FASTA. Returns list of (chain_id, sequence) tuples.

    Chain ID is extracted from the header: >ChainName or >Protein_X
    The last character of the header ID is used as chain ID if it's a single letter.
    """
    chains = []
    current_id = None
    current_seq = []
    with open(fasta_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith('>'):
                if current_id is not None:
                    chains.append((current_id, ''.join(current_seq)))
                header = line[1:].split()[0]
                # Extract chain ID: last char after underscore, or last char
                if logical_ids:
                    chain_id = header
                elif '_' in header:
                    chain_id = header.split('_')[-1]
                    if len(chain_id) == 1:
                        pass  # single letter chain ID
                    else:
                        chain_id = header[-1]
                else:
                    if header in ('VH', 'VL'):
                        chain_id = header[-1]
                    else:
                        chain_id = header[-1] if len(header) == 1 else header[0]
                current_id = chain_id
                current_seq = []
            elif current_id is not None:
                current_seq.append(line)
    if current_id is not None:
        chains.append((current_id, ''.join(current_seq)))
    return chains


# ---------------------------------------------------------------------------
# Template analysis
# ---------------------------------------------------------------------------

def get_template_chains(pdb_path):
    """Extract chain sequences from a PDB template file.

    Returns dict: chain_id -> one-letter sequence.
    """
    chains = {}
    current_chain = None
    current_resseq = None
    with open(pdb_path) as f:
        for line in f:
            if not line.startswith(('ATOM  ', 'HETATM')):
                continue
            chain = line[21]
            resname = line[17:20].strip()
            resseq = line[22:27].strip()  # includes icode
            if resname in WATER_RESNAMES:
                continue
            aa = AA3TO1.get(resname)
            if aa is None:
                continue
            key = (chain, resseq)
            if key != current_resseq:
                current_resseq = key
                if chain != current_chain:
                    current_chain = chain
                    chains.setdefault(chain, [])
                chains[chain].append(aa)
    return {k: ''.join(v) for k, v in chains.items()}


def sequence_identity(seq1, seq2):
    """Compute approximate sequence identity using k-mer overlap.

    Fast heuristic — counts shared 3-mers normalized by sequence length.
    Sufficient for template selection (not alignment).
    """
    k = 3
    if len(seq1) < k or len(seq2) < k:
        # Fallback for very short sequences
        matches = sum(1 for a, b in zip(seq1, seq2) if a == b)
        return matches / max(len(seq1), len(seq2)) if max(len(seq1), len(seq2)) > 0 else 0.0

    kmers1 = set(seq1[i:i+k] for i in range(len(seq1) - k + 1))
    kmers2 = set(seq2[i:i+k] for i in range(len(seq2) - k + 1))
    shared = len(kmers1 & kmers2)
    total = max(len(kmers1), len(kmers2))
    return shared / total if total > 0 else 0.0


def map_target_to_templates(target_chains, template_infos, verbose=False):
    """Map each target chain to the best-matching template chain.

    target_chains: [(chain_id, sequence), ...]
    template_infos: [(template_name, {chain_id: sequence}), ...]

    Returns: dict target_chain_id -> (template_name, template_chain_id, identity)
    """
    mapping = {}
    for tgt_id, tgt_seq in target_chains:
        best_match = None
        best_score = -1
        for tpl_name, tpl_chains in template_infos:
            for tpl_chain_id, tpl_seq in tpl_chains.items():
                score = sequence_identity(tgt_seq, tpl_seq)
                if score > best_score:
                    best_score = score
                    best_match = (tpl_name, tpl_chain_id, score)
        if best_match:
            mapping[tgt_id] = best_match
            if verbose:
                print(f"  Target chain {tgt_id} → {best_match[0]}:{best_match[1]} "
                      f"({best_match[2]*100:.1f}% identity)")
    return mapping


# ---------------------------------------------------------------------------
# Antibody mode (ANARCI)
# ---------------------------------------------------------------------------

def run_antibody_analysis(target_chains, verbose=False):
    """Run ANARCI on target chains for antibody numbering and CDR detection.

    Returns dict with domain info per chain.
    """
    try:
        from anarci import anarci
    except ImportError:
        print("ERROR: ANARCI not installed. Install with: pip install anarci",
              file=sys.stderr)
        sys.exit(1)

    results = {}
    sequences = [(ch_id, seq) for ch_id, seq in target_chains]

    for chain_id, seq in sequences:
        numbered, alignment_details, hit_tables = anarci(
            [("query", seq)], scheme="kabat", output=False)

        if numbered[0] is None:
            if verbose:
                print(f"  Chain {chain_id}: not an antibody chain")
            results[chain_id] = {'type': 'non-antibody'}
            continue

        # Extract domain info
        # numbered[0][0] = (numbering_list, start_index, end_index)
        # chain type is in alignment_details
        numbering, start_idx, end_idx = numbered[0][0]
        domain_type = alignment_details[0][0]['chain_type']  # H, K, L

        # Determine CDR boundaries (Kabat definition)
        cdr_ranges = {}
        if domain_type == 'H':
            cdr_ranges = {
                'CDR-H1': (26, 35),
                'CDR-H2': (50, 65),
                'CDR-H3': (95, 102),
            }
            domain_label = 'VH'
        elif domain_type in ('K', 'L'):
            cdr_ranges = {
                'CDR-L1': (24, 34),
                'CDR-L2': (50, 56),
                'CDR-L3': (89, 97),
            }
            domain_label = 'VL'
        else:
            domain_label = domain_type

        results[chain_id] = {
            'type': domain_label,
            'chain_type': domain_type,
            'numbering': numbering,
            'cdrs': cdr_ranges,
        }

        if verbose:
            print(f"  Chain {chain_id}: {domain_label} ({domain_type})")
            for cdr_name, (start, end) in cdr_ranges.items():
                cdr_seq = ''.join(
                    aa for (pos, icode), aa in numbering
                    if start <= pos <= end and aa != '-'
                )
                print(f"    {cdr_name}: {cdr_seq}")

    return results


# ---------------------------------------------------------------------------
# Per-chain alignment
# ---------------------------------------------------------------------------

def _extract_chain_pdb(pdb_path, chain_id, output_path):
    """Extract a single chain from a PDB file."""
    with open(pdb_path) as f:
        lines = f.readlines()
    with open(output_path, 'w') as f:
        for line in lines:
            if line.startswith(('ATOM  ', 'HETATM', 'TER   ')):
                if line[21] == chain_id:
                    f.write(line)
            elif line.startswith(('HEADER', 'CRYST1', 'REMARK', 'END')):
                f.write(line)


def _build_per_chain_alignment(env, target_chains, template_names,
                               chain_mapping, workdir, use_salign=False,
                               verbose=False):
    """Build multi-chain alignment by aligning each target chain to its best
    template chain independently, then combining into a single PIR file.

    The key insight: Modeller's PIR format for multi-template requires each
    template entry to have the SAME number of chain breaks (/) as the target.
    For templates that don't cover a target chain, that chain position gets
    all-gap characters. The structureX header must specify FIRST:LAST residue
    and chain so Modeller reads the correct atoms from the PDB.

    Returns path to the combined alignment PIR file.
    """
    from modeller import Alignment, Model

    # Step 1: Get template chain sequences as Modeller sees them
    # (important: Modeller may read atoms differently than our parser)
    tpl_modeller_seqs = {}  # tpl_name -> {chain_id: sequence}
    for tpl_name in template_names:
        mdl = Model(env, file=f'{tpl_name}.pdb')
        aln_tmp = Alignment(env)
        aln_tmp.append_model(mdl, align_codes=tpl_name,
                             atom_files=f'{tpl_name}.pdb')
        tmp_pir = os.path.join(workdir, f'_tpl_{tpl_name}.pir')
        aln_tmp.write(file=tmp_pir, alignment_format='PIR')
        full_seq = parse_pir_sequence(tmp_pir, tpl_name)
        # Split by chain breaks
        chain_seqs = full_seq.split('/')
        # Get chain IDs from PDB
        chain_ids = []
        seen = set()
        with open(os.path.join(workdir, f'{tpl_name}.pdb')) as pf:
            for line in pf:
                if line.startswith(('ATOM  ', 'HETATM')):
                    ch = line[21]
                    if ch not in seen:
                        seen.add(ch)
                        chain_ids.append(ch)
        tpl_modeller_seqs[tpl_name] = {}
        for i, ch_id in enumerate(chain_ids):
            if i < len(chain_seqs):
                tpl_modeller_seqs[tpl_name][ch_id] = chain_seqs[i]

    # Step 2: Pairwise alignment for each target chain
    per_chain = {}
    for tgt_chain_id, tgt_seq in target_chains:
        tpl_name, tpl_chain_id, _ = chain_mapping[tgt_chain_id]

        # Get template chain sequence as Modeller sees it
        tpl_chain_seq = tpl_modeller_seqs[tpl_name].get(tpl_chain_id, '')
        if not tpl_chain_seq:
            print(f"WARNING: template {tpl_name} chain {tpl_chain_id} not found",
                  file=sys.stderr)
            # Use target as-is (all modeled)
            per_chain[tgt_chain_id] = {
                'tpl_name': tpl_name,
                'tpl_chain': tpl_chain_id,
                'tpl_aligned': '-' * len(tgt_seq),
                'tgt_aligned': tgt_seq,
            }
            continue

        # Extract single chain from template PDB
        chain_pdb = os.path.join(workdir, f'_chain_{tpl_name}_{tpl_chain_id}.pdb')
        _extract_chain_pdb(
            os.path.join(workdir, f'{tpl_name}.pdb'),
            tpl_chain_id, chain_pdb)

        chain_code = f'{tpl_name}_{tpl_chain_id}'

        # Write single-chain target PIR
        chain_target_pir = os.path.join(workdir, f'_target_{tgt_chain_id}.pir')
        with open(chain_target_pir, 'w') as cf:
            cf.write(f">P1;target_{tgt_chain_id}\n")
            cf.write(f"sequence:target_{tgt_chain_id}::::::::\n")
            seq_with_star = tgt_seq if tgt_seq.endswith('*') else tgt_seq + '*'
            for i in range(0, len(seq_with_star), 75):
                cf.write(seq_with_star[i:i+75] + '\n')

        # Align single chain pair
        aln = Alignment(env)
        mdl = Model(env, file=chain_pdb)
        aln.append_model(mdl, align_codes=chain_code, atom_files=chain_pdb)
        aln.append(file=chain_target_pir, align_codes=f'target_{tgt_chain_id}')

        if use_salign:
            aln.salign(auto_overhang=True, gap_penalties_1d=(-450, -50),
                       alignment_type='tree', output='')
        else:
            aln.align2d(max_gap_length=50)

        pair_aln_path = os.path.join(workdir, f'_aln_{tgt_chain_id}.pir')
        aln.write(file=pair_aln_path, alignment_format='PIR')

        tpl_aln_seq = parse_pir_sequence(pair_aln_path, chain_code)
        tgt_aln_seq = parse_pir_sequence(pair_aln_path, f'target_{tgt_chain_id}')

        per_chain[tgt_chain_id] = {
            'tpl_name': tpl_name,
            'tpl_chain': tpl_chain_id,
            'tpl_aligned': tpl_aln_seq,
            'tgt_aligned': tgt_aln_seq,
        }

        if verbose:
            print(f"  Aligned chain {tgt_chain_id} → {tpl_name}:{tpl_chain_id} "
                  f"({len(tpl_aln_seq)} aligned positions)")

    # Step 3: Build combined multi-chain PIR
    # Each template entry must have the same number of '/' as the target.
    # Use Modeller's structureX header with FIRST and LAST residue/chain
    # so Modeller reads the correct PDB atoms.
    aln_path = os.path.join(workdir, 'alignment.pir')

    with open(aln_path, 'w') as f:
        for tpl_name in template_names:
            chain_seqs = []
            for tgt_chain_id, _ in target_chains:
                info = per_chain[tgt_chain_id]
                if info['tpl_name'] == tpl_name:
                    chain_seqs.append(info['tpl_aligned'])
                else:
                    gap_len = len(per_chain[tgt_chain_id]['tgt_aligned'])
                    chain_seqs.append('-' * gap_len)

            combined_seq = '/'.join(chain_seqs)

            # structureX header: FIRST and LAST specify the range Modeller
            # should read from the PDB. Use empty fields to let Modeller
            # auto-detect from the PDB file.
            f.write(f">P1;{tpl_name}\n")
            f.write(f"structureX:{tpl_name}.pdb:FIRST:@:LAST:@::::\n")
            for i in range(0, len(combined_seq), 75):
                f.write(combined_seq[i:i+75] + '\n')
            f.write('*\n\n')

        # Target entry
        chain_seqs = [per_chain[ch]['tgt_aligned'] for ch, _ in target_chains]
        combined_target = '/'.join(chain_seqs)
        f.write(">P1;target\n")
        f.write("sequence:target::::::::\n")
        for i in range(0, len(combined_target), 75):
            f.write(combined_target[i:i+75] + '\n')
        f.write('*\n')

    return aln_path


# ---------------------------------------------------------------------------
# Modeller multi-template modeling
# ---------------------------------------------------------------------------

def _make_model_with_loop_fallback(env, automodel_cls, loopmodel_cls,
                                   alnfile, knowns, sequence, num_models,
                                   no_loop_refine, md_level):
    """Build with LoopModel, retrying with automodel when no loops exist."""
    use_loops = not no_loop_refine
    model_cls = loopmodel_cls if use_loops else automodel_cls

    def configured(cls, configure_loops):
        model = cls(env, alnfile=alnfile, knowns=knowns, sequence=sequence)
        model.starting_model = 1
        model.ending_model = num_models
        if configure_loops:
            model.loop.starting_model = 1
            model.loop.ending_model = num_models
            model.loop.md_level = md_level
        return model

    model = configured(model_cls, use_loops)
    try:
        model.make()
    except Exception as exc:
        if not use_loops or "No loops detected for refinement" not in str(exc):
            raise
        print("INFO: alignment contains no modelable loops; retrying with automodel")
        model = configured(automodel_cls, False)
        model.make()
        use_loops = False
    return model, use_loops

def run_homology_modeller(target_chains, template_paths, chain_mapping,
                          args, workdir='.'):
    """Run Modeller multi-template homology modeling.

    Returns path to best model PDB.
    """
    from modeller import Alignment, Environ, Model, log
    from modeller import automodel as am
    from modeller.automodel import LoopModel, automodel

    if args.verbose:
        log.verbose()
    else:
        log.none()

    env = Environ()
    env.io.atom_files_directory = [workdir, '.']
    env.io.hetatm = True

    # Copy template PDBs to workdir with clean names
    template_names = []
    for i, tpl_path in enumerate(template_paths):
        tpl_name = Path(tpl_path).stem
        dst = os.path.join(workdir, f'{tpl_name}.pdb')
        if not os.path.exists(dst):
            shutil.copy2(tpl_path, dst)
        template_names.append(tpl_name)

    md_levels = {
        "none": None,
        "fast": am.refine.fast,
        "slow": am.refine.slow,
        "very_slow": am.refine.very_slow,
        "slow_large": am.refine.slow_large,
    }

    if args.alignment:
        # User-provided alignment — single Modeller run
        aln_path = str(Path(args.alignment).resolve())
        shutil.copy2(aln_path, os.path.join(workdir, 'alignment.pir'))
        aln_path = os.path.join(workdir, 'alignment.pir')

        a, used_loops = _make_model_with_loop_fallback(
            env, automodel, LoopModel, aln_path, tuple(template_names),
            'target', args.num_models, args.no_loop_refine,
            md_levels[args.md_level],
        )
        models = _get_best_models(a, not used_loops)
        best = min(models, key=lambda x: x['molpdf'])
        print(f"Best model: {best['name']} (molpdf={best['molpdf']:.1f})")
        return os.path.join(workdir, best['name']), aln_path

    # Per-chain modeling: model each target chain independently with its
    # best template, then assemble into a full multi-chain PDB.
    # This is necessary because templates have different chain structures
    # (e.g. Fab=2 chains vs IgG=4 chains) and Modeller requires matching
    # chain break counts between alignment entries.
    chain_models = {}  # tgt_chain_id -> model PDB path

    for tgt_chain_id, tgt_seq in target_chains:
        tpl_name, tpl_chain_id, _ = chain_mapping[tgt_chain_id]
        print(f"\n  Modeling chain {tgt_chain_id} "
              f"(template {tpl_name}:{tpl_chain_id})...")

        # Extract single chain from template
        chain_pdb = os.path.join(workdir, f'_chain_{tpl_name}_{tpl_chain_id}.pdb')
        _extract_chain_pdb(
            os.path.join(workdir, f'{tpl_name}.pdb'),
            tpl_chain_id, chain_pdb)

        chain_code = f'{tpl_name}_{tpl_chain_id}'

        # Write target PIR for this chain
        chain_target_pir = os.path.join(workdir, f'_target_{tgt_chain_id}.pir')
        with open(chain_target_pir, 'w') as cf:
            cf.write(f">P1;target_{tgt_chain_id}\n")
            cf.write(f"sequence:target_{tgt_chain_id}::::::::\n")
            seq_star = tgt_seq + '*' if not tgt_seq.endswith('*') else tgt_seq
            for i in range(0, len(seq_star), 75):
                cf.write(seq_star[i:i+75] + '\n')

        # Align
        aln = Alignment(env)
        mdl = Model(env, file=chain_pdb)
        aln.append_model(mdl, align_codes=chain_code, atom_files=chain_pdb)
        aln.append(file=chain_target_pir, align_codes=f'target_{tgt_chain_id}')

        if args.salign:
            aln.salign(auto_overhang=True, gap_penalties_1d=(-450, -50),
                       alignment_type='tree', output='')
        else:
            aln.align2d(max_gap_length=50)

        chain_aln_path = os.path.join(workdir, f'_aln_{tgt_chain_id}.pir')
        aln.write(file=chain_aln_path, alignment_format='PIR')

        if args.verbose:
            with open(chain_aln_path) as af:
                print(af.read()[:300])

        # Model this chain
        a, used_loops = _make_model_with_loop_fallback(
            env, automodel, LoopModel, chain_aln_path, chain_code,
            f'target_{tgt_chain_id}', args.num_models,
            args.no_loop_refine, md_levels[args.md_level],
        )
        models = _get_best_models(a, not used_loops)
        best = min(models, key=lambda x: x['molpdf'])
        print(f"    Best: {best['name']} (molpdf={best['molpdf']:.1f})")
        chain_models[tgt_chain_id] = os.path.join(workdir, best['name'])

    # Assemble per-chain models into a single multi-chain PDB
    assembled_path = os.path.join(workdir, 'assembled.pdb')
    _assemble_chains(chain_models, target_chains, assembled_path)
    print(f"\nAssembled {len(chain_models)} chains into {assembled_path}")

    return assembled_path, None


def _get_best_models(automodel_obj, no_loop_refine):
    """Extract successful models from automodel output."""
    if not no_loop_refine:
        models = [x for x in automodel_obj.loop.outputs if x['failure'] is None]
        if not models:
            models = [x for x in automodel_obj.outputs if x['failure'] is None]
            if models:
                print("WARNING: loop refinement failed, using initial model")
    else:
        models = [x for x in automodel_obj.outputs if x['failure'] is None]
    if not models:
        print("ERROR: all models failed", file=sys.stderr)
        sys.exit(1)
    return models


def _assemble_chains(chain_models, target_chains, output_path):
    """Assemble per-chain model PDBs into a single multi-chain PDB."""
    serial = 0
    with open(output_path, 'w') as f:
        f.write("REMARK    Assembled by dvbfixer homology\n")
        for tgt_chain_id, _ in target_chains:
            model_path = chain_models[tgt_chain_id]
            with open(model_path) as mf:
                for line in mf:
                    if line.startswith(('ATOM  ', 'HETATM')):
                        serial += 1
                        # Set chain ID and renumber serial
                        line = (f"{line[:6]}{serial % 100000:5d}"
                                f"{line[11:21]}{tgt_chain_id}"
                                f"{line[22:]}")
                        f.write(line)
            # TER between chains
            serial += 1
            f.write(f"TER   {serial % 100000:5d}\n")
        f.write("END\n")


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def restore_chain_ids(model_path, target_chains):
    """Restore chain IDs from Modeller's A,B,C,... to target chain IDs."""
    chain_ids = [ch_id for ch_id, _ in target_chains]
    with open(model_path) as f:
        lines = f.readlines()

    # Modeller assigns chains as A, B, C, ... in order
    modeller_chains = []
    seen = set()
    for line in lines:
        if line.startswith(('ATOM  ', 'HETATM')):
            ch = line[21]
            if ch not in seen:
                seen.add(ch)
                modeller_chains.append(ch)

    # Build mapping: modeller chain -> target chain
    chain_map = {}
    for i, mod_ch in enumerate(modeller_chains):
        if i < len(chain_ids):
            chain_map[mod_ch] = chain_ids[i]
        else:
            chain_map[mod_ch] = mod_ch

    # Apply mapping
    result = []
    for line in lines:
        if line.startswith(('ATOM  ', 'HETATM', 'TER   ')):
            old_ch = line[21]
            new_ch = chain_map.get(old_ch, old_ch)
            line = line[:21] + new_ch + line[22:]
        result.append(line)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog='dvbfixer homology',
        description='Multi-template homology modeling with Modeller or explicit '
                    'experimental mosaic diffusion.',
    )
    io = p.add_argument_group('Input / output')
    io.add_argument('fasta',
                    help='Target sequence FASTA (multi-chain, one >header per chain)')
    io.add_argument('--template', action='append', default=[],
                    help='Template PDB or PDBx/mmCIF file (repeatable, at least 1)')
    io.add_argument('--template-plan',
                    help='JSON template-chain selection plan; fits and merges selected parts into one known')
    io.add_argument('-o', '--output', default=None,
                    help='Output prefix (default: FASTA stem)')

    backend = p.add_argument_group('Backend')
    backend.add_argument('--backend', choices=['modeller', 'diffusion'],
                         default='modeller',
                         help='Modeling backend (default: modeller; diffusion is experimental)')
    backend.add_argument('--diffusion-model', choices=['protpardelle', 'protenix'],
                         default=None,
                         help='Installed diffusion model for mosaic completion (default: host-compatible auto selection)')
    backend.add_argument('--diffusion-seed', action='append', type=int,
                         dest='diffusion_seeds',
                         help='Candidate seed; repeat for multiple candidates (default: 7)')
    backend.add_argument('--diffusion-timeout', type=float, default=900.0,
                         help='Runner timeout in seconds (default: 900)')
    backend.add_argument('--diffusion-work-parent', default=None,
                         help='Parent directory for the private runner workspace')
    backend.add_argument('--diffusion-resume', action='store_true',
                         help='Reuse a verified bundle matching the current mosaic request')
    backend.add_argument('--diffusion-context', choices=['auto', 'none', 'local', 'full'], default='auto',
                         help='Protein context: auto uses local for corrected Protpardelle CUDA/MPS; legacy profiles retain their prior path (default: auto)')
    backend.add_argument('--diffusion-regenerate-covered', action='store_true',
                         help='Opt in to bounded regeneration of covered substitutions and short uncovered windows')
    backend.add_argument('--diffusion-edit-flanks', type=int, choices=range(1, 6), default=1,
                         help='Covered-edit sequence flanks per side, requires --diffusion-regenerate-covered (default: 1)')

    alignment = p.add_argument_group('Alignment')
    alignment.add_argument('--alignment', default=None,
                           help='Pre-built PIR alignment file (skip auto-alignment)')
    alignment.add_argument('--salign', action='store_true',
                           help='Use structure-based alignment instead of align2d')

    modelling = p.add_argument_group('Modelling parameters')
    modelling.add_argument('-n', '--num-models', type=positive_int, default=5,
                           help='Number of models to generate (default: 5)')
    modelling.add_argument('--md-level',
                           choices=['none', 'fast', 'slow', 'very_slow', 'slow_large'],
                           default='fast',
                           help='MD refinement level (default: fast)')
    modelling.add_argument('--no-loop-refine', action='store_true',
                           help='Use automodel instead of LoopModel (faster, no loop refinement)')
    modelling.add_argument('--antibody', action='store_true',
                           help='Antibody-aware mode: ANARCI numbering, CDR detection')

    pipeline = p.add_argument_group('Post-processing pipeline')
    pipeline.add_argument('--prepare', action='store_true',
                          help='Run dvbfixer prepare on output')
    pipeline.add_argument('--minimize', action='store_true',
                          help='Run dvbfixer prepare + minimize on output')
    pipeline.add_argument('--ph', type=float, default=7.0,
                          help='pH for hydrogen addition (default: 7.0)')
    pipeline.add_argument('--no-solvent', action='store_true',
                          help='Use vacuum for optional downstream minimization')

    diag = p.add_argument_group('Diagnostics')
    diag.add_argument('--keep-workdir', action='store_true',
                      help='Keep homology working directory')
    diag.add_argument('-v', '--verbose', action='store_true',
                      help='Verbose output')

    from dvbfixer.batch import add_runtime_help
    add_runtime_help(p)
    args = p.parse_args(argv)
    raw_args = list(sys.argv[1:] if argv is None else argv)
    provided = {token.split('=', 1)[0] for token in raw_args if token.startswith('-')}
    diffusion_flags = {
        '--diffusion-model', '--diffusion-seed', '--diffusion-timeout',
        '--diffusion-work-parent', '--diffusion-resume', '--diffusion-context', '--diffusion-regenerate-covered', '--diffusion-edit-flanks',
    }
    modeller_flags = {'--num-models', '-n', '--md-level', '--no-loop-refine', '--salign'}
    invalid = (
        provided & diffusion_flags
        if args.backend == 'modeller'
        else provided & modeller_flags
    )
    if invalid:
        required = '--backend diffusion' if args.backend == 'modeller' else '--backend modeller'
        p.error(f"{', '.join(sorted(invalid))} require {required}")
    if '--diffusion-edit-flanks' in provided and not args.diffusion_regenerate_covered:
        p.error('--diffusion-edit-flanks requires --diffusion-regenerate-covered')
    return args


def main(argv=None):
    args = parse_args(argv)
    fasta_path = Path(args.fasta).resolve()
    output_prefix = args.output or fasta_path.stem

    if not fasta_path.exists():
        print(f"Error: {fasta_path} not found", file=sys.stderr)
        sys.exit(1)

    if not args.template and not args.template_plan:
        raise SystemExit('ERROR: provide --template at least once or use --template-plan')
    if args.template_plan and (args.template or args.alignment):
        raise SystemExit('ERROR: --template-plan cannot be combined with --template or --alignment')
    if args.backend == 'diffusion' and not args.template_plan:
        raise SystemExit('ERROR: homology diffusion requires --template-plan')
    if args.backend == 'diffusion' and args.antibody:
        raise SystemExit('ERROR: --antibody is not supported by homology diffusion')
    if not math.isfinite(args.diffusion_timeout) or args.diffusion_timeout <= 0:
        raise SystemExit('ERROR: --diffusion-timeout must be positive')
    args.diffusion_seeds = args.diffusion_seeds or [7]
    if any(seed < 0 for seed in args.diffusion_seeds) or len(set(args.diffusion_seeds)) != len(args.diffusion_seeds):
        raise SystemExit('ERROR: --diffusion-seed must be unique and non-negative')
    for tpl in args.template:
        if not Path(tpl).exists():
            print(f"Error: template {tpl} not found", file=sys.stderr)
            sys.exit(1)

    # 1. Parse target FASTA
    target_chains = parse_fasta_chains(fasta_path)
    if args.backend == 'diffusion':
        with open(args.template_plan) as stream:
            declared = {group['chainId'] for group in json.load(stream)['alignmentGroups']}
        logical = parse_fasta_chains(fasta_path, logical_ids=True)
        target_chains = [
            (logical_id if logical_id in declared else mapped_id, sequence)
            for (logical_id, sequence), (mapped_id, _) in zip(logical, target_chains)
        ]
    print(f"Target: {len(target_chains)} chain(s)")
    for ch_id, seq in target_chains:
        print(f"  Chain {ch_id}: {len(seq)} residues")

    workdir = tempfile.mkdtemp(prefix='dvbfixer_homology_',
                              dir=args.diffusion_work_parent if args.backend == 'diffusion' else None)
    try:
        if args.template_plan:
            from dvbfixer.homology_plan import materialize_template_plan
            template_paths, args.alignment = materialize_template_plan(
                Path(args.template_plan).resolve(), Path(workdir), verbose=args.verbose)
        else:
            template_paths = [str(Path(t).resolve()) for t in args.template]
    except Exception:
        if args.keep_workdir:
            print(f"Homology mosaic workdir: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)
        raise

    if args.backend == 'diffusion':
        from dvbfixer.homology_plan import build_mosaic_diffusion_request
        from dvbfixer.model.diffusion.runtime import (
            DiffusionRuntimeError,
            resolve_diffusion_runtime,
        )
        from dvbfixer.model.diffusion_cli import DiffusionCliError, run_diffusion_model

        mosaic = Path(template_paths[0])
        coverage = mosaic.with_name('selected_template_mosaic.coverage.json')
        try:
            runtime = resolve_diffusion_runtime(args.diffusion_model)
            mosaic_input, mosaic_request = build_mosaic_diffusion_request(
                coverage,
                target_chains,
                Path(workdir),
                seeds=tuple(args.diffusion_seeds),
                regenerate_covered=args.diffusion_regenerate_covered,
                profile=runtime.profile,
                edit_flanks=args.diffusion_edit_flanks,
                context_mode=args.diffusion_context,
            )
            output_bundle = f"{output_prefix}_homology_diffusion"
            run_diffusion_model(argparse.Namespace(
                input=str(mosaic_input),
                output=output_bundle,
                fasta=None,
                diffusion_request=str(mosaic_request),
                diffusion_model=runtime.model,
                diffusion_seeds=args.diffusion_seeds,
                diffusion_timeout=args.diffusion_timeout,
                diffusion_work_parent=args.diffusion_work_parent,
                diffusion_heterogen_smiles=[],
                diffusion_resume=args.diffusion_resume,
                diffusion_context=args.diffusion_context,
                keep_heterogens=True,
                no_terminal=False,
                verbose=args.verbose,
            ))
            if args.prepare or args.minimize:
                from dvbfixer.model.diffusion.publication import copy_selected_candidate

                selected = copy_selected_candidate(
                    Path(output_bundle), Path(f"{output_prefix}_homology.pdb"), resume=args.diffusion_resume,
                )
                _postprocess_model(str(selected), args)
        except (DiffusionCliError, DiffusionRuntimeError, ValueError) as exc:
            raise SystemExit(f'ERROR: homology diffusion failed: {exc}') from exc
        finally:
            if args.keep_workdir:
                print(f"Homology mosaic workdir: {workdir}")
            else:
                shutil.rmtree(workdir, ignore_errors=True)
        return

    # 2. Analyze templates
    template_infos = []
    for tpl_path in template_paths:
        tpl_name = Path(tpl_path).stem
        tpl_chains = get_template_chains(tpl_path)
        template_infos.append((tpl_name, tpl_chains))
        if args.verbose:
            print(f"Template {tpl_name}: {len(tpl_chains)} chain(s)")
            for ch, seq in tpl_chains.items():
                print(f"  Chain {ch}: {len(seq)} residues")

    # 3. Map target chains to best template chains
    print("\nChain mapping (target → template):")
    chain_mapping = map_target_to_templates(
        target_chains, template_infos, verbose=True)

    # 4. Antibody analysis (optional)
    if args.antibody:
        print("\nAntibody analysis (ANARCI):")
        ab_info = run_antibody_analysis(target_chains, verbose=args.verbose)

    # 5. Run Modeller
    orig_dir = os.getcwd()

    try:
        os.chdir(workdir)
        print(f"\nRunning Modeller ({args.num_models} models, "
              f"md_level={args.md_level})...")

        best_model_path, aln_path = run_homology_modeller(
            target_chains, template_paths, chain_mapping, args, workdir)

        # 6. Post-process
        # Modeller outputs correct chain IDs from the PIR alignment,
        # so restore_chain_ids is only needed if they don't match.
        with open(best_model_path) as f:
            result_lines = f.readlines()

        # Check if chain IDs need fixing
        expected_chains = [ch for ch, _ in target_chains]
        actual_chains = []
        seen = set()
        for line in result_lines:
            if line.startswith(('ATOM  ', 'HETATM')):
                ch = line[21]
                if ch not in seen:
                    seen.add(ch)
                    actual_chains.append(ch)

        if actual_chains != expected_chains:
            print("Restoring chain IDs...")
            result_lines = restore_chain_ids(best_model_path, target_chains)

        # Remove water if present
        result_lines = remove_water_lines(result_lines)

        # 7. Write output
        os.chdir(orig_dir)
        output_pdb = f"{output_prefix}_homology.pdb"
        with open(output_pdb, 'w') as f:
            f.writelines(result_lines)
        print(f"Wrote {output_pdb}")

        # 8. Write .dat file (record modeled regions)
        # For homology modeling, all atoms are "new" since the entire structure
        # is built. But we mark template-covered regions as "original" and
        # gap regions as "new" for restraint purposes.
        from dvbfixer.ffutils.dat import DatRecord

        dat_path = f"{output_prefix}_homology.dat"
        DatRecord(
            description="Homology model built by dvbfixer homology",
            templates=[Path(t).name for t in template_paths],
            target_chains={ch: len(seq) for ch, seq in target_chains},
        ).save(dat_path, verbose=False)
        print(f"Wrote {dat_path}")

    finally:
        os.chdir(orig_dir)
        if args.keep_workdir:
            print(f"Modeller workdir: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)

    _postprocess_model(output_pdb, args)


def _postprocess_model(output_pdb, args):
    """Shared PDB/.dat post-processing after either model backend."""
    if args.prepare or args.minimize:
        print("\nRunning prepare...")
        from dvbfixer.prepare import main as prepare_main
        prepare_args = [output_pdb, '--ph', str(args.ph)]
        if args.verbose:
            prepare_args.append('-v')
        prepare_main(prepare_args)

        prepared_pdb = output_pdb.replace('.pdb', '_prepared.pdb')
        from dvbfixer.ffutils.dat import DatRecord

        upstream_dat = Path(output_pdb).with_suffix('.dat')
        downstream_dat = Path(prepared_pdb).with_suffix('.dat')
        if upstream_dat.exists() and Path(prepared_pdb).exists():
            downstream = DatRecord.load(downstream_dat) if downstream_dat.exists() else DatRecord()
            downstream.merge(DatRecord.load(upstream_dat))
            downstream.save(downstream_dat, verbose=False)
        if args.minimize and Path(prepared_pdb).exists():
            print("\nRunning minimize...")
            from dvbfixer.minimize import main as minimize_main
            minimize_args = [prepared_pdb, '--ph', str(args.ph)]
            if args.no_solvent:
                minimize_args.append('--no-solvent')
            if args.verbose:
                minimize_args.append('-v')
            minimize_main(minimize_args)


if __name__ == "__main__":
    main()
