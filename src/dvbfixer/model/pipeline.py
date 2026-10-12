"""Rebuild missing loops/gaps in a PDB structure using Modeller.

Uses the SEQRES section (or a user-provided FASTA) as the complete sequence,
aligns it to the existing ATOM records, and runs Modeller's LoopModel to
rebuild only the missing regions while keeping the rest of the structure fixed.

Non-protein chains (glycans, ligands) are included in the Modeller pipeline
via env.io.hetatm=True. The target sequence includes '.' (BLK residue) entries
for non-protein chains so Modeller preserves them through loop modeling.
The '.' counts are derived from Modeller's own template reading to avoid
any mismatch.
"""

import os
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from dvbfixer.model.cli import AA3TO1, WATER_RESNAMES, parse_args
from dvbfixer.model.modeller_run import (
    _reorder_chains_for_modeller,
    parse_alignment,
    run_modeller,
)
from dvbfixer.model.renumber import build_resnum_mapping


def parse_seqres(lines):
    """Return dict: chain_id -> [resname, ...] from SEQRES records."""
    seqres = {}
    for line in lines:
        if not line.startswith("SEQRES"):
            continue
        chain = line[11]
        seqres.setdefault(chain, []).extend(line[19:].split())
    return seqres


_CHAIN_PATTERNS = [
    re.compile(r'^chain[_\s]*([A-Za-z0-9])$', re.IGNORECASE),
    re.compile(r'_([A-Za-z0-9])$'),
    re.compile(r'^([A-Za-z0-9])$'),
]

# Multi-chain suffix: `>1abc_A_B` or `>1abc_A_B_C` → chains A, B, C share seq.
_MULTI_CHAIN_SUFFIX = re.compile(r'_([A-Za-z0-9](?:_[A-Za-z0-9])+)$')
# RCSB pipe: `>8A67_2|Chains B, C, F, G|Polyubiquitin-B|Homo sapiens`.
_RCSB_CHAINS = re.compile(r'\|\s*Chains?\s+([^|]+?)\s*\|', re.IGNORECASE)


def _chain_ids_from_header(header, description=None):
    """Return list of chain IDs from a FASTA header.

    Tries in order: RCSB `|Chains X, Y, Z|` (on the full description),
    multi-chain suffix `>PDBID_A_B`, then the three single-chain
    patterns. Empty list on no match.
    """
    if description:
        m = _RCSB_CHAINS.search(description)
        if m:
            chains = re.split(r'[,\s]+', m.group(1).strip())
            return [c for c in chains if c]
    h = header.strip()
    m = _MULTI_CHAIN_SUFFIX.search(h)
    if m:
        return [c for c in m.group(1).split('_') if c]
    for pat in _CHAIN_PATTERNS:
        m = pat.search(h)
        if m:
            return [m.group(1)]
    return []


def _chain_id_from_header(header):
    """Compatibility wrapper — returns the first chain ID or None."""
    ids = _chain_ids_from_header(header)
    return ids[0] if ids else None


def parse_fasta(fasta_path):
    """Parse a FASTA file, return dict {chain_id: sequence}.

    Header formats supported (priority order):
      * ``>8A67_2|Chains B, C, F, G|Polyubiquitin-B|Homo sapiens (9606)``
        (RCSB pipe-delimited) — assigns the sequence to every chain in
        the ``Chains`` field.
      * ``>PDBID_A_B`` (multi-chain suffix) — assigns the sequence to
        chains A and B.
      * ``>chain_X`` / ``>chainX`` / ``>PDBID_X`` / ``>X`` — single chain.

    When the same chain letter appears in multiple records with
    IDENTICAL sequences, the second occurrence is silently ignored.
    Only differing sequences on the same chain raise ValueError.
    """
    from Bio import SeqIO
    records = list(SeqIO.parse(fasta_path, "fasta"))
    result: dict[str, str] = {}
    for r in records:
        chain_ids = _chain_ids_from_header(r.id, description=r.description)
        if not chain_ids:
            raise ValueError(
                f"Could not extract chain ID from FASTA header '{r.description}'. "
                "Supported formats: '>chain_X', '>PDBID_X', '>PDBID_A_B', "
                "'>X', or RCSB-style '>PDBID_N|Chains A, B, C|Name|Organism'."
            )
        seq = str(r.seq)
        for ch in chain_ids:
            if ch in result:
                if result[ch] == seq:
                    continue   # idempotent
                raise ValueError(
                    f"Chain '{ch}' has two different sequences in FASTA."
                )
            result[ch] = seq
    return result



def _strip_hetatm_lines(lines, keep_water=False, verbose=False):
    """Drop HETATM records from ``lines``. Waters (HOH/WAT/TIP3/TIP4/
    TIP5/SOL/T3P/T4P/T5P) are kept when ``keep_water=True``. CONECT
    records that reference dropped atom serials are also removed so
    downstream serial renumbering doesn't emit orphan bonds.

    Returns the filtered line list. Pure text pass — safe to run
    before any structural parsing.
    """
    n_before = len(lines)
    kept_water_set = WATER_RESNAMES if keep_water else frozenset()
    dropped_serials = set()
    dropped_residues = set()
    for ln in lines:
        if ln.startswith("HETATM") and len(ln) >= 20:
            resname = ln[17:20].strip()
            if resname in kept_water_set:
                continue
            try:
                dropped_serials.add(int(ln[6:11]))
            except ValueError:
                pass
            if len(ln) >= 27:
                dropped_residues.add((ln[17:20].strip(), ln[21], ln[22:26].strip(), ln[26].strip()))

    kept = []
    for ln in lines:
        if ln.startswith("HETATM") and len(ln) >= 20:
            resname = ln[17:20].strip()
            if resname not in kept_water_set:
                continue
        if ln.startswith("ANISOU"):
            try:
                if int(ln[6:11]) in dropped_serials:
                    continue
            except ValueError:
                pass
        if ln.startswith("LINK") and len(ln) >= 57:
            first = (ln[17:20].strip(), ln[21], ln[22:26].strip(), ln[26].strip())
            second = (ln[47:50].strip(), ln[51], ln[52:56].strip(), ln[56].strip())
            if first in dropped_residues or second in dropped_residues:
                continue
        if ln.startswith("CONECT") and dropped_serials:
            try:
                # CONECT record columns: 7-11, 12-16, 17-21, 22-26, 27-31
                # (each is a 5-char right-justified serial). Grab them.
                parts = [ln[i:i + 5].strip() for i in range(6, min(len(ln), 31), 5)]
                serials = [int(p) for p in parts if p]
                if any(s in dropped_serials for s in serials):
                    continue
            except ValueError:
                pass
        kept.append(ln)
    if verbose and len(kept) != n_before:
        print(f"  [model] --strip-heterogens: dropped "
              f"{n_before - len(kept)} HETATM/CONECT line(s)")
    return kept


def get_chain_order(lines, seqres_only=None):
    """Get chain IDs from ATOM/HETATM records in order of appearance.

    If seqres_only is a set of chain IDs, only return chains in that set.
    """
    chains = []
    seen = set()
    for line in lines:
        if line.startswith(("ATOM  ", "HETATM")):
            c = line[21]
            if c not in seen:
                seen.add(c)
                if seqres_only is None or c in seqres_only:
                    chains.append(c)
    return chains


def get_atom_sequence(lines, chain_id):
    """Get the one-letter amino acid sequence from ATOM records for a chain."""
    residues = []
    seen = set()
    for line in lines:
        if not line.startswith("ATOM  "):
            continue
        ch = line[21]
        if ch != chain_id:
            continue
        resname = line[17:20].strip()
        resnum = line[22:26].strip()
        icode = line[26]
        key = (resnum, icode)
        if key not in seen:
            seen.add(key)
            aa = AA3TO1.get(resname)
            if aa:
                residues.append(aa)
    return ''.join(residues)


def trim_terminal_gaps(protein_seq_map, pdb_lines, verbose=False):
    """Trim N/C terminal residues from target sequences that aren't in the structure.

    Semi-globally aligns each ATOM-derived sequence to its complete target, then
    trims target residues before the first observed anchor and after the last.
    Reference gaps between those anchors remain modelable internal loops.
    """
    trimmed = {}
    for chain, target_seq in protein_seq_map.items():
        atom_seq = get_atom_sequence(pdb_lines, chain)
        if not atom_seq:
            trimmed[chain] = target_seq
            continue

        from dvbfixer.sequence_alignment import (
            align_observed_to_reference,
            format_alignment_diagnostic,
        )

        alignment = align_observed_to_reference(atom_seq, target_seq)
        if alignment is None:
            # Alignment failed, keep original target rather than guessing.
            trimmed[chain] = target_seq
            continue

        diagnostic = format_alignment_diagnostic(chain, alignment)
        if alignment.ambiguous:
            print(f"  [alignment] WARNING: {diagnostic}; using deterministic "
                  "leftmost best alignment")
        elif verbose:
            print(f"  [alignment] {diagnostic}")

        first_pos = alignment.start
        last_pos = alignment.end - 1
        new_seq = target_seq[alignment.start:alignment.end]

        n_trimmed_n = first_pos
        n_trimmed_c = len(target_seq) - last_pos - 1
        if verbose and (n_trimmed_n > 0 or n_trimmed_c > 0):
            print(f"  Chain {chain}: trimmed {n_trimmed_n} N-terminal, "
                  f"{n_trimmed_c} C-terminal residues")

        trimmed[chain] = new_seq
    return trimmed





# ---------------------------------------------------------------------------
# Post-processing: restore chain IDs and residue numbering
# ---------------------------------------------------------------------------

def _set_resid(line, resseq, icode=' '):
    """Set residue sequence number (cols 22-25) and insertion code (col 26)."""
    return line[:22] + f"{resseq:4d}" + icode + line[27:]


def get_template_mask(aln_path):
    """Parse alignment and return per-chain boolean masks.

    True = template position (present in original), False = gap (rebuilt).
    """
    template_seq = parse_alignment(aln_path)
    per_chain = []
    for chain_seq in template_seq.split('/'):
        per_chain.append([ch != '-' for ch in chain_seq])
    flat = []
    for cm in per_chain:
        flat.extend(cm)
    return flat, per_chain



def restore_chain_ids_and_read(model_pdb_path, all_chains):
    """Read Modeller output PDB, remap chain IDs back to original.

    Modeller assigns A, B, C, ... to all chains (protein + non-protein).
    """
    modeller_chains = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    chain_map = {}
    for i, orig_chain in enumerate(all_chains):
        if i < len(modeller_chains):
            chain_map[modeller_chains[i]] = orig_chain

    output_lines = []
    with open(model_pdb_path) as f:
        content = f.read()

    # Modeller can write TER records without trailing newline,
    # causing them to be joined with the next line. Split on known
    # record boundaries to handle this. Also split on CONECT so that a
    # joined "TER...CONECT..." line gets disentangled and the CONECT
    # part can be dropped explicitly below.
    lines = content.split('\n')
    expanded = []
    for line in lines:
        while True:
            found = False
            for prefix in ("ATOM  ", "HETATM", "CONECT"):
                idx = line.find(prefix, 1)  # skip pos 0
                if idx > 0 and line[:idx].startswith("TER"):
                    expanded.append(line[:idx])
                    line = line[idx:]
                    found = True
                    break
            if not found:
                break
        if line:
            expanded.append(line)

    for line in expanded:
        if not line.endswith('\n'):
            line = line + '\n'
        if line.startswith(("ATOM  ", "HETATM", "ANISOU")):
            if len(line) > 21:
                mod_chain = line[21]
                if mod_chain in chain_map:
                    line = line[:21] + chain_map[mod_chain] + line[22:]
            output_lines.append(line)
        elif line.startswith("TER"):
            if len(line) > 21:
                mod_chain = line[21]
                if mod_chain in chain_map:
                    line = line[:21] + chain_map[mod_chain] + line[22:]
            output_lines.append(line)
        elif line.startswith("END"):
            output_lines.append(line)
        elif line.startswith("CONECT"):
            # Explicitly drop Modeller-emitted CONECT records. Bonds are
            # restored separately by restore_conect_records using the
            # ORIGINAL PDB's CONECT entries, remapped by atom identity.
            continue
        # Any other line (REMARK, HEADER, SEQRES, SSBOND, etc.) is dropped.

    return output_lines


def renumber_model_output(result_lines, resnum_mapping):
    """Apply residue renumbering to Modeller output lines.

    resnum_mapping values are (resSeq, iCode) tuples.
    Only renumbers residues that appear in the mapping (protein chains).
    Non-protein chains are left with their numbering.
    """
    output = []
    for line in result_lines:
        if line.startswith(("ATOM  ", "HETATM", "ANISOU")):
            chain = line[21]
            resseq = int(line[22:26].strip())
            key = (chain, resseq)
            if key in resnum_mapping and resnum_mapping[key] is not None:
                new_resseq, new_icode = resnum_mapping[key]
                line = _set_resid(line, new_resseq, new_icode)
            output.append(line)
        elif line.startswith("TER"):
            if len(line) > 26:
                chain = line[21]
                seq_str = line[22:26].strip()
                if seq_str and seq_str.isdigit():
                    key = (chain, int(seq_str))
                    if key in resnum_mapping and resnum_mapping[key] is not None:
                        new_resseq, new_icode = resnum_mapping[key]
                        line = _set_resid(line, new_resseq, new_icode)
            output.append(line)
        else:
            output.append(line)
    return output


def _renumber_atom_serials(lines):
    """Assign sequential unique serials (1..N) to every ATOM/HETATM line.

    Used after `patch_missing_hetatm`, which inserts atoms from the input
    PDB keeping their original serials — those collide with Modeller's
    renumbered serials in the result. Without re-serialization, the final
    PDB has duplicate serials, and CONECT records resolve to whichever
    atom the viewer happens to pick first → spurious bonds.

    Returns a new list of lines with cols 7-11 (atom serial) rewritten.
    Non-atom lines pass through unchanged.
    """
    out = []
    serial = 0
    for line in lines:
        if line.startswith(("ATOM  ", "HETATM")):
            serial += 1
            new_serial = serial if serial < 100000 else (serial % 100000)
            out.append(line[:6] + f"{new_serial:5d}" + line[11:])
        else:
            out.append(line)
    return out


def patch_missing_hetatm(result_lines, original_lines, all_chains, protein_chains, verbose=False):
    """Patch back HETATM atoms that Modeller dropped (e.g. linkage atoms).

    Modeller's BLK residue handling can drop atoms at protein-glycan linkage
    points (e.g. NAG C1 that forms the N-glycosidic bond to ASN). This function
    compares output vs original non-protein residues and inserts any missing
    atoms from the original PDB.

    Matching is done by (chain, resname, position-in-chain) since Modeller
    renumbers residues.
    """
    protein_set = set(protein_chains)

    def get_nonprotein_residues(lines, chain_set=None):
        """Get ordered list of (chain, resnum, resname) and atoms per residue."""
        residues = {}  # (chain, resnum) -> {resname, atoms: [lines]}
        order = []     # ordered unique (chain, resnum)
        for line in lines:
            if not line.startswith("HETATM"):
                continue
            ch = line[21]
            if chain_set and ch not in chain_set:
                continue
            resnum = line[22:26].strip()
            resname = line[17:20].strip()
            key = (ch, resnum)
            if key not in residues:
                residues[key] = {"resname": resname, "atoms": {}, "lines": {}}
                order.append(key)
            atomname = line[12:16].strip()
            residues[key]["atoms"][atomname] = line
            residues[key]["lines"][atomname] = line
        return residues, order

    nonprotein_set = set(all_chains) - protein_set
    orig_res, orig_order = get_nonprotein_residues(original_lines, nonprotein_set)
    out_res, out_order = get_nonprotein_residues(result_lines, nonprotein_set)

    # Build position-based mapping: (chain, resname, nth_occurrence) -> residue key
    def build_pos_map(order, residues):
        pos_map = {}
        counter = {}
        for key in order:
            ch, _ = key
            resname = residues[key]["resname"]
            ck = (ch, resname)
            counter.setdefault(ck, 0)
            counter[ck] += 1
            pos_map[(ch, resname, counter[ck])] = key
        return pos_map

    orig_pos = build_pos_map(orig_order, orig_res)
    out_pos = build_pos_map(out_order, out_res)

    # Find missing atoms and build patches
    patches = {}  # out_resnum_key -> list of original lines to insert
    n_patched = 0
    for pos_key, orig_key in orig_pos.items():
        if pos_key not in out_pos:
            continue
        out_key = out_pos[pos_key]
        orig_atoms = set(orig_res[orig_key]["atoms"].keys())
        out_atoms = set(out_res[out_key]["atoms"].keys())
        missing = orig_atoms - out_atoms
        if missing:
            out_chain, out_resnum = out_key
            for atomname in sorted(missing):
                orig_line = orig_res[orig_key]["atoms"][atomname]
                # Update chain and residue number to match output
                patched = orig_line[:21] + out_chain + f"{int(out_resnum):4d}" + " " + orig_line[27:]
                patches.setdefault(out_key, []).append(patched)
                n_patched += 1

    if n_patched == 0:
        return result_lines

    if verbose:
        print(f"Patched {n_patched} missing HETATM atom(s) from original")

    # Insert patched atoms after the last atom of each residue
    output = []
    for line in result_lines:
        output.append(line)
        if line.startswith("HETATM"):
            ch = line[21]
            resnum = line[22:26].strip()
            key = (ch, resnum)
            if key in patches:
                # Check if next line is same residue; if not, insert here
                pass  # We'll handle insertion differently

    # Simpler approach: collect all lines per residue, insert patches
    output = []
    prev_key = None
    for line in result_lines:
        if line.startswith("HETATM"):
            ch = line[21]
            resnum = line[22:26].strip()
            cur_key = (ch, resnum)
            # If we moved to a new residue, insert patches for the previous one
            if prev_key and prev_key != cur_key and prev_key in patches:
                output.extend(patches.pop(prev_key))
            prev_key = cur_key
        else:
            # Non-HETATM line — flush patches for previous residue
            if prev_key and prev_key in patches:
                output.extend(patches.pop(prev_key))
            prev_key = None
        output.append(line)

    # Flush any remaining patches
    if prev_key and prev_key in patches:
        # Insert before END if present
        if output and output[-1].startswith("END"):
            end_line = output.pop()
            output.extend(patches.pop(prev_key))
            output.append(end_line)
        else:
            output.extend(patches.pop(prev_key))

    return output


def restore_conect_records(result_lines, original_lines, verbose=False,
                            per_chain_masks=None, all_chains=None):
    """Restore CONECT records from original PDB with remapped atom serials.

    Modeller strips all CONECT records. This function rebuilds them by:
    1. Walking residues in chain order in BOTH the input and the model
       output to build a position-based residue index per chain.
    2. For each input residue, map its INPUT position N to its MODEL
       output position via `per_chain_masks` (True=template, False=gap).
       The Nth template-position in the mask is the Nth input residue;
       its model output position is the mask index where that True sits.
    3. Within each aligned residue, atom-name matching links input
       atoms to model output atoms regardless of serial renumbering.

    Without `per_chain_masks` (e.g. when called without alignment info),
    falls back to naive position-by-position alignment which is correct
    only when no gaps were filled.

    Note: `original_lines` should already have any CONECT gaps
    supplemented (see `main()`'s CONECT-inference pre-processing,
    applied to the input BEFORE Modeller ever runs) — restoring
    whatever CONECT text is present here happens too late to prevent
    an under-annotated glycan chain from being repositioned during
    modeling; the fix has to happen before, not after.
    """
    def _build_residue_index(lines):
        """Walk all ATOM/HETATM lines and return:
          - by_chain_pos: dict {chain: [(record_type, resname, resnum, icode), ...]}
            (entries in file order, one per unique residue per chain)
          - serial_to_pos: dict serial -> (chain, position_index, atomname)
        """
        by_chain_pos = {}
        seen_per_chain = {}
        serial_to_pos = {}
        for line in lines:
            if not line.startswith(("ATOM  ", "HETATM")):
                continue
            chain = line[21]
            resname = line[17:20].strip()
            resnum = line[22:26].strip()
            icode = line[26] if len(line) > 26 else ' '
            atomname = line[12:16].strip()
            try:
                serial = int(line[6:11].strip())
            except ValueError:
                continue
            res_key = (resnum, icode)
            seen = seen_per_chain.setdefault(chain, {})
            if res_key not in seen:
                idx = len(by_chain_pos.setdefault(chain, []))
                seen[res_key] = idx
                by_chain_pos[chain].append(
                    ('het' if line.startswith('HETATM') else 'atom',
                     resname, resnum, icode))
            pos = seen[res_key]
            serial_to_pos[serial] = (chain, pos, atomname)
        return by_chain_pos, serial_to_pos

    orig_by_chain, orig_serial_to_pos = _build_residue_index(original_lines)
    model_by_chain, _ = _build_residue_index(result_lines)

    # Build (chain, model_pos) -> serial map by re-walking result_lines
    model_atom_serial = {}
    seen_per_chain = {}
    for line in result_lines:
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        chain = line[21]
        resnum = line[22:26].strip()
        icode = line[26] if len(line) > 26 else ' '
        atomname = line[12:16].strip()
        try:
            serial = int(line[6:11].strip())
        except ValueError:
            continue
        res_key = (resnum, icode)
        seen = seen_per_chain.setdefault(chain, {})
        if res_key not in seen:
            seen[res_key] = len(seen)
        pos = seen[res_key]
        model_atom_serial[(chain, pos, atomname)] = serial

    # Build per-chain map: input_position → model_output_position.
    # When per_chain_masks is provided, use it: the Nth template-True
    # in the mask is the Nth input residue, located at the model
    # position corresponding to that mask index. When per_chain_masks
    # is missing, fall back to naive identity (works only when no gaps).
    chain_input_to_model_pos = {}  # {chain: {input_pos: model_pos}}
    if per_chain_masks is not None and all_chains is not None:
        for ci, chain in enumerate(all_chains):
            if ci >= len(per_chain_masks):
                continue
            mask = per_chain_masks[ci]
            input_pos = 0
            mapping = {}
            for model_pos, is_template in enumerate(mask):
                if is_template:
                    mapping[input_pos] = model_pos
                    input_pos += 1
            chain_input_to_model_pos[chain] = mapping

    # Sanity: warn if input vs model chain lengths don't match the mask
    # expectation. Non-protein chains aren't in the mask but should still
    # align position-by-position (Modeller doesn't reorder them).
    if verbose:
        for chain, orig_residues in orig_by_chain.items():
            model_residues = model_by_chain.get(chain, [])
            if chain in chain_input_to_model_pos:
                expected_input_n = sum(1 for v in chain_input_to_model_pos[chain].values())
                if expected_input_n != len(orig_residues):
                    print(f"  WARN: chain {chain}: mask says {expected_input_n} "
                          f"input residues but PDB has {len(orig_residues)} "
                          f"— bond restoration may miss some atoms")
            elif len(orig_residues) != len(model_residues):
                print(f"  WARN: chain {chain}: input has {len(orig_residues)} "
                      f"residues, model has {len(model_residues)} — bonds may "
                      f"be partially restored")

    # Helper: resolve an input serial to the corresponding model output serial
    def _remap(serial):
        pos_info = orig_serial_to_pos.get(serial)
        if pos_info is None:
            return None
        chain, orig_pos, atomname = pos_info
        # Translate input_pos → model_pos via the mask (or identity).
        pos_map = chain_input_to_model_pos.get(chain)
        if pos_map is not None:
            model_pos = pos_map.get(orig_pos)
        else:
            model_pos = orig_pos  # non-protein chain: position-by-position
        if model_pos is None:
            return None
        # Check resname consistency to avoid misrouting if mask is wrong
        model_residues = model_by_chain.get(chain, [])
        orig_residues = orig_by_chain.get(chain, [])
        if model_pos >= len(model_residues) or orig_pos >= len(orig_residues):
            return None
        if orig_residues[orig_pos][1] != model_residues[model_pos][1]:
            # resname mismatch — drop the bond rather than misroute it.
            return None
        return model_atom_serial.get((chain, model_pos, atomname))

    # Build a per-input-serial → per-model-serial map used below
    orig_serial_to_model_serial = {}
    for serial in orig_serial_to_pos:
        new_serial = _remap(serial)
        if new_serial is not None:
            orig_serial_to_model_serial[serial] = new_serial

    # Direct input-serial → model-serial mapping used for CONECT remap.
    orig_to_model_serial = orig_serial_to_model_serial

    # Parse CONECT records from original
    conect_records = []
    for line in original_lines:
        if not line.startswith("CONECT"):
            continue
        serials = []
        text = line.rstrip()
        for i in range(6, len(text), 5):
            field = text[i:i + 5].strip()
            if field and field.isdigit():
                serials.append(int(field))
        if len(serials) >= 2:
            conect_records.append(serials)

    if not conect_records:
        return result_lines

    # Remap serials
    new_conect_lines = []
    n_dropped = 0
    for serials in conect_records:
        new_serials = []
        skip = False
        for s in serials:
            new_s = orig_to_model_serial.get(s)
            if new_s is None:
                skip = True
                break
            new_serials.append(new_s)
        if skip:
            n_dropped += 1
            continue
        line = "CONECT"
        for ns in new_serials:
            line += f"{ns:5d}"
        line = line.ljust(80) + "\n"
        new_conect_lines.append(line)

    if verbose:
        print(f"Restored {len(new_conect_lines)} CONECT records"
              + (f" ({n_dropped} dropped — atoms not found)" if n_dropped else ""))

    if not new_conect_lines:
        return result_lines

    # Insert CONECT before END line
    output = []
    end_line = None
    for line in result_lines:
        if line.startswith("END"):
            end_line = line
        else:
            output.append(line)
    output.extend(new_conect_lines)
    if end_line:
        output.append(end_line)
    else:
        output.append("END\n")

    return output


def build_model_dat(result_lines, per_chain_masks, all_chains, protein_chains, resnum_mapping):
    """Build .dat file recording gap-filled (rebuilt) atoms.

    Uses per_chain_masks (True=template, False=gap) and resnum_mapping
    to identify which residues were rebuilt by Modeller. All atoms in
    rebuilt residues are recorded as "added".
    """
    protein_set = set(protein_chains)

    # Collect (chain, resSeq, iCode) for gap-filled positions
    gap_resids = set()
    for ci, chain in enumerate(all_chains):
        if chain not in protein_set:
            continue
        if ci >= len(per_chain_masks):
            continue
        mask = per_chain_masks[ci]
        offset = sum(len(per_chain_masks[j]) for j in range(ci))
        for pos, is_template in enumerate(mask):
            if not is_template:
                model_resnum = offset + pos + 1
                resid = resnum_mapping.get((chain, model_resnum))
                if resid is not None:
                    gap_resids.add((chain, resid[0], resid[1].strip()))

    # Scan output PDB lines for atoms in gap residues
    added_atoms = []
    residue_summary = {}
    for line in result_lines:
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        chain = line[21]
        seq_str = line[22:26].strip()
        if not seq_str or not seq_str.lstrip('-').isdigit():
            continue
        resnum = int(seq_str)
        icode = line[26].strip() if len(line) > 26 else ''
        if (chain, resnum, icode) in gap_resids:
            resname = line[17:20].strip()
            atom_name = line[12:16].strip()
            element = line[76:78].strip() if len(line) > 77 else ''
            resid_str = str(resnum)
            added_atoms.append({
                "chain": chain,
                "resid": resid_str,
                "icode": icode,
                "resname": resname,
                "atom": atom_name,
                "element": element,
            })
            rkey = f"{chain}/{resname}{resid_str}"
            if rkey not in residue_summary:
                residue_summary[rkey] = {"heavy": 0, "hydrogen": 0}
            if element == 'H':
                residue_summary[rkey]["hydrogen"] += 1
            else:
                residue_summary[rkey]["heavy"] += 1

    return {
        "description": "Modeller gap-fill data. Rebuilt residue atoms get weak/no restraints "
                       "during minimization.",
        "total_added": len(added_atoms),
        "residue_summary": residue_summary,
        "added_atoms": added_atoms,
    }


def remove_water_lines(lines):
    """Remove water molecules from PDB lines."""
    output = []
    for line in lines:
        if line.startswith(("ATOM  ", "HETATM", "ANISOU")):
            resname = line[17:20].strip()
            if resname in WATER_RESNAMES:
                continue
        elif line.startswith("TER") and len(line) > 20:
            resname = line[17:20].strip()
            if resname in WATER_RESNAMES:
                continue
        output.append(line)
    return output


def main(
    argv=None,
    *,
    observed_target_indices_by_chain: Mapping[str, tuple[int, ...]] | None = None,
):
    args = parse_args(argv)
    if args.backend == "diffusion":
        from dvbfixer.model.diffusion.pipeline import DiffusionPipelineError
        from dvbfixer.model.diffusion.publication import PublicationError
        from dvbfixer.model.diffusion.runner import DiffusionRunnerError
        from dvbfixer.model.diffusion.validate import DiffusionValidationError
        from dvbfixer.model.diffusion_cli import DiffusionCliError, run_diffusion_model

        try:
            run_diffusion_model(args)
        except (
            DiffusionCliError,
            DiffusionPipelineError,
            DiffusionRunnerError,
            DiffusionValidationError,
            PublicationError,
        ) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return
    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Validate --num-output BEFORE running Modeller so bad input fails fast.
    if args.num_output < 1:
        print(f"ERROR: --num-output must be >= 1 (got {args.num_output})",
              file=sys.stderr)
        sys.exit(1)
    pool_size = args.num_models * args.num_loops
    if args.num_output > pool_size:
        print(f"WARNING: --num-output {args.num_output} exceeds the candidate "
              f"pool (num-models {args.num_models} × num-loops "
              f"{args.num_loops} = {pool_size}); at most {pool_size} models "
              f"can be saved.", file=sys.stderr)

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = input_path.with_stem(input_path.stem + "_model")

    # Infer missing CONECT bonds (SS/glycosidic/glycosylation) from
    # coordinates BEFORE Modeller ever runs — not after. A real
    # deposited PDB can have incomplete CONECT/LINK annotation for a
    # genuine glycosylation site; without an explicit bond documented
    # up front, Modeller has no way to know an under-annotated glycan
    # chain is covalently anchored to the protein, and can reposition
    # it arbitrarily far away during structure-building. No downstream
    # distance-based bond detection (e.g. `convert_to_glycam`) can
    # recover the connection once the geometry itself has drifted
    # apart — the same information restore_conect_records applies
    # AFTER modeling is already too late for this specific failure mode.
    if not args.no_infer_conect:
        from dvbfixer.pdbutils import _materialise_inferred_pdb
        input_path = Path(_materialise_inferred_pdb(
            input_path, verbose=args.verbose))

    with open(input_path) as f:
        lines = f.readlines()

    # --strip-heterogens: remove HETATM records before Modeller sees
    # the input. In some cases (bad ligand geometry, ambiguous CONECT
    # references) heterogens cause artifacts in the loop refinement.
    # Waters are also removed unless --keep-water is passed. CONECT
    # records referencing dropped serials are removed too so the
    # downstream serial renumberer doesn't emit orphan bonds.
    if not args.keep_heterogens:
        lines = _strip_hetatm_lines(
            lines, keep_water=args.keep_water, verbose=args.verbose,
        )

    # Determine protein chains (those with SEQRES)
    seqres = parse_seqres(lines)
    if args.fasta:
        try:
            fasta_map = parse_fasta(args.fasta)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        protein_chains = (
            get_chain_order(lines, seqres_only=set(seqres.keys()))
            if seqres else get_chain_order(lines)
        )
        missing = [c for c in protein_chains if c not in fasta_map]
        if missing:
            print(
                f"Error: FASTA missing sequences for chain(s): {', '.join(missing)}. "
                f"FASTA has: {', '.join(sorted(fasta_map.keys()))}. "
                f"PDB has: {', '.join(protein_chains)}.",
                file=sys.stderr,
            )
            sys.exit(1)
        # FASTA chains not in the input PDB — skip them (don't try to
        # model a chain we have no ATOM records to align to). Always
        # warn (not just verbose) so users don't silently miss a chain.
        extra = [c for c in fasta_map if c not in protein_chains]
        if extra:
            print(f"  [fasta] WARNING: chain(s) {', '.join(extra)} in "
                  f"FASTA but not in input PDB; skipping (no ATOM records "
                  f"to align to). Pass --force-fasta-chains to attempt "
                  f"modeling from scratch (not implemented in 0.7.2).")
        # SEQRES vs FASTA consistency check — WARN on divergence, but
        # use FASTA (SEQRES is often incomplete on legacy PDBs).
        if seqres:
            for ch in protein_chains:
                if ch not in seqres:
                    continue
                seqres_letters = ''.join(
                    AA3TO1.get(r, 'X') for r in seqres[ch]
                )
                fasta_letters = fasta_map[ch]
                if seqres_letters != fasta_letters:
                    # Find first divergence position.
                    diff_i = next(
                        (i for i, (a, b) in enumerate(
                            zip(seqres_letters, fasta_letters))
                         if a != b),
                        min(len(seqres_letters), len(fasta_letters)),
                    )
                    print(f"  [fasta] WARNING: chain {ch} SEQRES differs "
                          f"from FASTA at position {diff_i + 1} "
                          f"(SEQRES len={len(seqres_letters)}, FASTA len="
                          f"{len(fasta_letters)}); using FASTA.")
        protein_seq_map = {ch: fasta_map[ch] for ch in protein_chains}
    else:
        if not seqres:
            print("No SEQRES records found — no gaps to model, copying input")
            import shutil as _sh
            _sh.copy2(str(input_path), str(output_path))
            print(f"Wrote {output_path}")
            return
        protein_chains = get_chain_order(lines, seqres_only=set(seqres.keys()))
        protein_seq_map = {}
        for ch in protein_chains:
            protein_seq_map[ch] = ''.join(AA3TO1.get(r, 'X') for r in seqres[ch])

    if not protein_chains:
        print("No modelable chains found.", file=sys.stderr)
        sys.exit(1)

    if observed_target_indices_by_chain is not None:
        placement_chains = set(observed_target_indices_by_chain)
        protein_chain_set = set(protein_chains)
        if placement_chains != protein_chain_set:
            missing = sorted(protein_chain_set - placement_chains)
            extra = sorted(placement_chains - protein_chain_set)
            details = []
            if missing:
                details.append(f"missing chain(s): {', '.join(missing)}")
            if extra:
                details.append(f"unknown chain(s): {', '.join(extra)}")
            raise ValueError(
                "locked observed-to-target placements must cover exactly the "
                f"modelled protein chains ({'; '.join(details)})"
            )
        if args.no_terminal:
            raise ValueError(
                "locked observed-to-target placements are incompatible with --no-terminal"
            )

    # ALL chains in order of appearance (protein + non-protein)
    all_chains = get_chain_order(lines)
    nonprotein = [c for c in all_chains if c not in set(protein_chains)]

    if args.verbose:
        print(f"Protein chains: {', '.join(protein_chains)}")
        if nonprotein:
            print(f"Non-protein chains (included via hetatm): {', '.join(nonprotein)}")

    if args.no_terminal:
        print("Trimming N/C terminal residues (--no-terminal)")
        protein_seq_map = trim_terminal_gaps(protein_seq_map, lines, args.verbose)

    n_protein_res = sum(len(protein_seq_map[ch]) for ch in protein_chains)
    print(f"Target sequence: {n_protein_res} protein residues across {len(protein_chains)} chain(s)")

    # Work in temp directory
    workdir = tempfile.mkdtemp(prefix='dvbfixer_model_')
    orig_dir = os.getcwd()

    try:
        os.chdir(workdir)

        # Write FULL PDB (all chains) for Modeller.
        # Rename non-standard protonation variants to standard names so Modeller
        # can read them (Modeller only knows HIS, not HIE/HID/HIP/ASH/GLH etc.)
        # Save the original names to restore in the output.
        _VARIANT_TO_STD = {
            'HIE': 'HIS', 'HID': 'HIS', 'HIP': 'HIS',
            'HSE': 'HIS', 'HSD': 'HIS', 'HSP': 'HIS',
            'ASH': 'ASP', 'ASPP': 'ASP',
            'GLH': 'GLU', 'GLUP': 'GLU',
            'CYX': 'CYS', 'CYM': 'CYS',
            'LYN': 'LYS',
            # GLYCAM glycoprotein residues — Modeller doesn't know NLN/
            # OLS/OLT; pre-rename to the standard parent residue so the
            # protein chain is recognized correctly. Restored on output
            # via _input_variants downstream.
            'NLN': 'ASN', 'OLS': 'SER', 'OLT': 'THR',
        }
        # Capture: (chain, resseq) -> original variant name
        _input_variants = {}
        for line in lines:
            if line.startswith(('ATOM  ', 'HETATM')):
                resname = line[17:20].strip()
                if resname in _VARIANT_TO_STD:
                    ch = line[21]
                    rs = line[22:26].strip()
                    _input_variants[(ch, rs)] = resname

        # Apply variant rename, then reorder chains so each chain ID forms
        # one contiguous block in the temp file Modeller reads. Without
        # reordering, Modeller emits one PIR segment per file-order chain
        # block — if a chain ID appears in two file positions (e.g. protein
        # ATOMs early, glycan HETATMs later), the template ends up with
        # one more segment than `all_chains` knows about, and align2d either
        # silently drops a segment (3ry6: chain C's NAG is lost) or aborts
        # with 'No aligned template residues for BLK residue' (FcgRI).
        renamed_lines = []
        for line in lines:
            if line.startswith(('ATOM  ', 'HETATM')):
                resname = line[17:20].strip()
                std = _VARIANT_TO_STD.get(resname)
                if std:
                    line = line[:17] + f"{std:>3s}" + line[20:]
            renamed_lines.append(line)
        reordered_lines = _reorder_chains_for_modeller(renamed_lines)

        input_pdb = workdir + '/' + input_path.name
        with open(input_pdb, 'w') as f:
            f.writelines(reordered_lines)

        # Fast pre-check: if every protein chain's ATOM sequence already
        # matches SEQRES exactly, there are NO gaps → skip Modeller
        # entirely. Modeller's align2d step is O(N^2) DP and can take
        # minutes on multi-chain complexes (2BNQ: 5 chains × 829 residues
        # → ~2 min just to conclude "no gaps"). Comparing sequences in
        # Python takes microseconds.
        _no_gaps_fast = all(
            get_atom_sequence(reordered_lines, ch) == protein_seq_map[ch]
            for ch in protein_chains
        )
        if _no_gaps_fast:
            print("No gaps found (fast pre-check: ATOM sequences match "
                  "SEQRES exactly on every chain) — skipping Modeller, "
                  "copying input verbatim.")
            candidates = [(str(Path(input_pdb)), 0.0)]
            aln_path = ''  # not used on the shortcut path
        else:
            # Run Modeller — target is built inside using Modeller's own
            # template reading, so non-protein '.' counts are guaranteed
            # to match. Returns a list of (model_path, molpdf) sorted
            # ascending — best first.
            candidates, aln_path = run_modeller(
                Path(input_pdb), protein_chains, protein_seq_map,
                all_chains, args,
                observed_target_indices_by_chain=observed_target_indices_by_chain,
            )

        # Clamp --num-output to the number of successfully completed
        # candidates (some Modeller loops can fail individually).
        n_save = min(args.num_output, len(candidates))
        if args.num_output > len(candidates):
            print(f"WARNING: requested {args.num_output} outputs but only "
                  f"{len(candidates)} candidate model(s) succeeded; "
                  f"saving {n_save}.", file=sys.stderr)

        # First candidate (best) — if there's just one, we may be on the
        # no-gap shortcut where run_modeller returned the input path unchanged.
        first_path, _ = candidates[0]
        no_gap_shortcut = (first_path == str(Path(input_pdb)))
        if no_gap_shortcut and args.num_output > 1:
            print(f"INFO: --num-output={args.num_output} requested but no "
                  f"gaps detected; only 1 output is meaningful.", file=sys.stderr)
            n_save = 1

        # If no gaps were found, run_modeller returns the input path unchanged.
        # Just copy input to output with variant restoration and skip post-processing.
        if no_gap_shortcut:
            best_model = first_path
            result_lines = lines[:]
            # Restore variant names
            if _input_variants:
                restored = []
                for line in result_lines:
                    if line.startswith(('ATOM  ', 'HETATM')):
                        ch = line[21]
                        rs = line[22:26].strip()
                        orig = _input_variants.get((ch, rs))
                        if orig:
                            line = line[:17] + f"{orig:>3s}" + line[20:]
                    restored.append(line)
                result_lines = restored
            if not args.keep_water:
                result_lines = remove_water_lines(result_lines)
            with open(output_path, 'w') as f:
                f.writelines(result_lines)
            print(f"Wrote {output_path}")
            # Write empty .dat (no gaps filled)
            from dvbfixer.ffutils.dat import DatRecord
            record = DatRecord(description="No gaps — input copied unchanged")
            if _input_variants:
                record.variant_overrides = {
                    f"{ch}:{rs}": var for (ch, rs), var in _input_variants.items()
                }
            dat_path = output_path.with_suffix('.dat')
            record.save(dat_path, verbose=False)
            print(f"Wrote {dat_path}")
            return

        # Per-candidate post-processing loop. Each Modeller candidate gets the
        # same chain-ID / numbering / variant restoration, then writes its own
        # _N-suffixed PDB and .dat file (no suffix when --num-output == 1).
        _, per_chain_masks = get_template_mask(aln_path)
        resnum_mapping = build_resnum_mapping(
            per_chain_masks, all_chains, protein_chains, lines,
            protein_seq_map=protein_seq_map,
            renumber_from_1=getattr(args, "renumber_from_1", False),
        )
        n_gaps = sum(
            not m for ci, chain in enumerate(all_chains)
            if chain in set(protein_chains) and ci < len(per_chain_masks)
            for m in per_chain_masks[ci]
        )

        for idx, (candidate_path, molpdf) in enumerate(candidates[:n_save]):
            if n_save == 1:
                this_output = output_path
            else:
                this_output = output_path.with_stem(
                    output_path.stem + f"_{idx + 1}")

            # Restore original chain IDs (Modeller reassigns A,B,C,... to all chains)
            result_lines = restore_chain_ids_and_read(
                candidate_path, all_chains)

            # Restore residue numbering for protein chains only
            result_lines = renumber_model_output(result_lines, resnum_mapping)

            # Patch back any HETATM atoms Modeller dropped (e.g. NAG C1 linkage atom)
            result_lines = patch_missing_hetatm(
                result_lines, lines, all_chains, protein_chains, args.verbose
            )

            # Re-serialize ALL atoms after patching so serials stay unique.
            # patch_missing_hetatm copies orig_line[:21] + new_chain + new_resnum
            # + orig_line[27:] — which keeps the ORIGINAL input serial in cols
            # 7-11. That serial collides with Modeller's renumbered atoms,
            # producing two atoms with the same serial in the output. CONECT
            # records (added next by restore_conect_records) then resolve to
            # whichever duplicate the viewer picks first, creating spurious
            # bonds between unrelated atoms ("strange bonds inside glycans").
            result_lines = _renumber_atom_serials(result_lines)

            # Restore CONECT records from original PDB with remapped atom serials
            result_lines = restore_conect_records(
                result_lines, lines, args.verbose,
                per_chain_masks=per_chain_masks, all_chains=all_chains,
            )

            if args.verbose and idx == 0:
                n_gaps_filled = sum(
                    not m for ci, cm in enumerate(per_chain_masks)
                    for m in cm
                    if ci < len(all_chains) and all_chains[ci] in set(protein_chains)
                )
                print(f"Restored numbering ({n_gaps_filled} gap positions assigned)")

            if not args.keep_water:
                result_lines = remove_water_lines(result_lines)

            # Restore original protonation variant names (HIE, ASH, etc.)
            if _input_variants:
                restored = []
                for line in result_lines:
                    if line.startswith(('ATOM  ', 'HETATM')):
                        ch = line[21]
                        rs = line[22:26].strip()
                        orig = _input_variants.get((ch, rs))
                        if orig:
                            line = line[:17] + f"{orig:>3s}" + line[20:]
                    restored.append(line)
                result_lines = restored

            # Final pass: split any remaining concatenated TER+ATOM/HETATM lines
            # that may have survived post-processing, and ensure all lines end with \n
            sanitized = []
            for line in result_lines:
                while True:
                    found = False
                    for prefix in ("ATOM  ", "HETATM"):
                        sub_idx = line.find(prefix, 1)
                        if sub_idx > 0 and line[:sub_idx].rstrip().startswith("TER"):
                            ter = line[:sub_idx].rstrip() + "\n"
                            sanitized.append(ter)
                            line = line[sub_idx:]
                            found = True
                            break
                    if not found:
                        break
                if not line.endswith("\n"):
                    line = line + "\n"
                sanitized.append(line)
            result_lines = sanitized

            with open(str(this_output), 'w') as f:
                f.writelines(result_lines)
            print(f"Wrote {this_output} (molpdf={molpdf:.1f})")

            # Post-sanitize Cα chirality sweep. modeller_run already
            # ran fix_ca_chirality on each raw candidate; the sanitize
            # step above rebuilds the file textually (TER handling,
            # chain reordering) which does not touch coordinates but
            # is a good place for the final assert-L invariant. Fails
            # loudly via ChiralityError → zbs prints the offender and
            # exits non-zero.
            import numpy as _np
            from openmm.app import PDBFile as _PDBFile
            from openmm.unit import Quantity as _Quantity
            from openmm.unit import nanometer as _nm

            from dvbfixer.ffutils.geometry import (
                assert_all_l,
                fix_ca_chirality,
            )
            _mdl = _PDBFile(str(this_output))
            # Numpy-backed Quantity so PDBFile.writeFile's np.isnan
            # guard passes on older OpenMM builds too (list-backed
            # Quantities from PDBFile trip np.isnan on some versions).
            _pos_arr = _np.array(
                [list(_mdl.positions[i].value_in_unit(_nm))
                 for i in range(len(_mdl.positions))],
                dtype=float,
            )
            _pos = _Quantity(_pos_arr, _nm)
            _n = fix_ca_chirality(_mdl.topology, _pos, verbose=args.verbose)
            if _n:
                with open(str(this_output), 'w') as _f:
                    _PDBFile.writeFile(_mdl.topology, _pos, _f,
                                        keepIds=True)
                print(f"  [model] repaired {_n} D-Cα in "
                      f"{this_output.name}")
            assert_all_l(_mdl.topology, _pos)

            # Write .dat file only if there were actual gaps
            dat_path = None
            if n_gaps > 0:
                from dvbfixer.ffutils.dat import DatRecord
                dat = build_model_dat(
                    result_lines, per_chain_masks, all_chains, protein_chains, resnum_mapping
                )
                dat_path = this_output.with_suffix('.dat')
                DatRecord(
                    description=dat["description"],
                    added_atoms=dat["added_atoms"],
                    residue_summary=dat["residue_summary"],
                ).save(dat_path, verbose=False)
                print(f"  Saved restraint data: {dat_path} ({dat['total_added']} atoms in rebuilt regions)")

            if getattr(args, "number_from_1", False):
                from dvbfixer.renumber import normalize_numbering_from_one

                deltas = normalize_numbering_from_one(this_output)
                if dat_path is not None and dat_path.exists():
                    record = DatRecord.load(dat_path)
                    for atom in record.added_atoms:
                        delta = deltas.get(atom["chain"], 0)
                        atom["resid"] = str(int(atom["resid"]) + delta)
                    summary = {}
                    for atom in record.added_atoms:
                        key = f"{atom['chain']}/{atom['resname']}{atom['resid']}"
                        bucket = summary.setdefault(key, {"heavy": 0, "hydrogen": 0})
                        bucket["hydrogen" if atom.get("element") == "H" else "heavy"] += 1
                    record.residue_summary = summary
                    record.save(dat_path, verbose=False)
                if args.verbose:
                    shifted = ", ".join(f"{chain}:{delta:+d}" for chain, delta in deltas.items())
                    print(f"  [model] normalized final residue numbering ({shifted})")

    finally:
        os.chdir(orig_dir)
        if args.keep_workdir:
            print(f"Workdir kept: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)
