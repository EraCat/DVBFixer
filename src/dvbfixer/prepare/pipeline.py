"""Fix missing atoms and residues in a PDB structure using PDBFixer.

Adds missing residues, missing heavy atoms, and hydrogens. Writes a .dat file
recording which atoms were added, for use by 'dvbfixer minimize' to apply
selective restraints.
"""

import sys
from pathlib import Path

from openmm.app import Modeller, PDBFile
from pdbfixer import PDBFixer

from dvbfixer.prepare.cli import parse_args
from dvbfixer.prepare.glycan import (
    _write_heterogen_conects,
    add_heterogen_h_via_openbabel,
    add_heterogen_h_via_rdkit,
    find_glycosylated_atoms_with_sugar,
    remove_extra_glycan_hydrogens,
    rename_glycosylated_protein_residues,
)
from dvbfixer.prepare.mutations import (
    apply_deletions_to_pdb_text,
    apply_mutations,
    parse_mutations,
)
from dvbfixer.prepare.smiles import (
    SmilesPreparationError,
    add_hydrogens_from_smiles,
    parse_smiles_mappings,
)

# ---------------------------------------------------------------------------
# .dat file: records what PDBFixer added
# ---------------------------------------------------------------------------

def build_dat(fixer, new_atom_indices):
    """Build a dict describing what PDBFixer added, suitable for JSON export."""
    atoms_list = list(fixer.topology.atoms())

    added_atoms = []
    added_residues_summary = {}
    for idx in sorted(new_atom_indices):
        atom = atoms_list[idx]
        res = atom.residue
        entry = {
            "chain": res.chain.id,
            "resid": res.id,
            "icode": res.insertionCode,
            "resname": res.name,
            "atom": atom.name,
            "element": atom.element.symbol,
        }
        added_atoms.append(entry)

        rkey = f"{res.chain.id}/{res.name}{res.id}"
        if rkey not in added_residues_summary:
            added_residues_summary[rkey] = {"heavy": 0, "hydrogen": 0}
        if atom.element.symbol == 'H':
            added_residues_summary[rkey]["hydrogen"] += 1
        else:
            added_residues_summary[rkey]["heavy"] += 1

    return {
        "description": "PDBFixer restraint data. Added atoms get weak/no restraints during minimization. "
                       "Edit 'added_atoms' list to change which atoms are treated as 'new'.",
        "total_added": len(added_atoms),
        "residue_summary": added_residues_summary,
        "added_atoms": added_atoms,
    }


def write_dat(dat, path):
    """Serialise a ``.dat`` dict to disk. Delegates to ``ffutils.dat`` so
    the schema (fields, total_added invariant, JSON layout) lives in one
    place.

    ``dat`` here is the dict shape returned by ``build_dat`` (plus optional
    ``variant_overrides`` / ``removed_residues`` added by the caller);
    :class:`DatRecord` accepts it via ``**dat`` decomposition.
    """
    from dvbfixer.ffutils.dat import DatRecord

    known = {
        "description", "total_added", "residue_summary", "added_atoms",
        "variant_overrides", "removed_residues", "templates", "target_chains",
    }
    kwargs = {k: v for k, v in dat.items() if k in known and k != "total_added"}
    DatRecord(**kwargs).save(path)



# ---------------------------------------------------------------------------
# PDBFixer
# ---------------------------------------------------------------------------

# Map AMBER/CHARMM protonation variant names to standard PDB names
# (PDBFixer only accepts standard 3-letter codes for mutations)
_VARIANT_TO_STANDARD = {
    'HID': 'HIS', 'HIE': 'HIS', 'HIP': 'HIS',
    'HSD': 'HIS', 'HSE': 'HIS', 'HSP': 'HIS',
    'ASH': 'ASP', 'ASPP': 'ASP',
    'GLH': 'GLU', 'GLUP': 'GLU',
    'CYX': 'CYS', 'CYM': 'CYS',
    'LYN': 'LYS',
}


def _run_propka_reduce_variants(
    pdb_path,
    ph: float,
    ss_pairs: set | None,
    his_default: str = "HIE",
    cys_ss_pka: float = 99.99,
    use_propka: bool = True,
    use_reduce: bool = True,
    verbose: bool = False,
) -> dict:
    """Run PROPKA + MolProbity Reduce on ``pdb_path`` and return a
    variant map ``{(chain, resid, icode): variant}`` for use by
    ``Modeller.addHydrogens(variants=[...])``.

    Mirrors the PROPKA-decide + Reduce-tautomer-overlay dance that
    ``prep_backend.run_prep`` uses for the tleap-reduce backend
    (fixed in 0.7.4). PROPKA drives ASP/ASH, GLU/GLH, LYS/LYN,
    CYS/CYM/CYX, and HIS/HIP; Reduce fills in HID vs HIE for the
    neutral HIS residues PROPKA said were neutral. SS pairs override
    to CYX (CONECT-detected SS wins over PROPKA's CYM).

    Returns the merged variant map (empty dict if PROPKA and Reduce
    were both skipped).
    """
    from pathlib import Path
    variant_map: dict[tuple, str] = {}

    # 1. PROPKA → variant map keyed by (chain, resnum, icode).
    n_pka = 0
    if use_propka:
        try:
            from dvbfixer.protonate import (
                decide_protonation,
                get_pka_results,
                run_propka,
            )
            pka_results = get_pka_results(run_propka(str(pdb_path)))
            n_pka = len(pka_results)
            propka_map = decide_protonation(
                pka_results, ph, his_default=his_default,
                cys_ss_pka=cys_ss_pka,
            )
            for key, variant in propka_map.items():
                variant_map[key] = variant
        except Exception as e:
            print(f"  [prep] PROPKA skipped ({e}); variants from Reduce "
                  f"+ SS only.")

    # 2. Reduce → HID/HIE tautomer per HIS residue.
    #    Run on a temp copy where all HIS variants are collapsed to HIS
    #    (Reduce -build only decides tautomer for residues named HIS).
    reduce_his: dict[tuple, str] = {}
    if use_reduce:
        import tempfile as _tf

        from dvbfixer.prep_backend import (
            _infer_his_tautomers_from_atoms,
            _rename_all_his_variants_to_his,
            _strip_hydrogens,
            run_reduce,
        )
        _wd = _tf.mkdtemp(prefix='dvbfixer_reduce_')
        try:
            _step1 = Path(_wd) / 'no_h.pdb'
            _step2 = Path(_wd) / 'his_flat.pdb'
            _step3 = Path(_wd) / 'reduced.pdb'
            _strip_hydrogens(Path(pdb_path), _step1)
            import shutil as _sh
            _sh.copy(_step1, _step2)
            _rename_all_his_variants_to_his(_step2)
            run_reduce(_step2, _step3, build=True, nuclear=True,
                       verbose=verbose)
            reduce_his = _infer_his_tautomers_from_atoms(_step3)
        except Exception as e:
            print(f"  [prep] Reduce skipped ({e}); HIS tautomers from "
                  f"input H atoms only.")
        finally:
            import shutil as _sh
            _sh.rmtree(_wd, ignore_errors=True)

    # 3. Overlay Reduce's HID/HIE choice under PROPKA's HIP decision.
    #    PROPKA HIP wins (charge state) — Reduce only fills in tautomer
    #    for neutral HIS.
    for key, tautomer in reduce_his.items():
        current = variant_map.get(key)
        if current == "HIP":
            continue  # PROPKA charged, Reduce can't override.
        if tautomer in ("HID", "HIE", "HIP"):
            variant_map[key] = tautomer

    # 4. SS-bond overlay — CONECT-detected pairs force CYX regardless
    #    of PROPKA's CYS/CYM decision.
    ss = ss_pairs or set()
    if ss:
        # Scan the PDB text to find CYS atoms and pick up their icodes.
        text = Path(pdb_path).read_text()
        seen_cys: set = set()
        for raw in text.splitlines():
            if not raw.startswith(("ATOM  ", "HETATM")) or len(raw) < 27:
                continue
            if raw[17:20].strip() not in ("CYS", "CYX", "CYM"):
                continue
            chain = raw[21]
            try:
                resseq = int(raw[22:26].strip())
            except ValueError:
                continue
            icode = raw[26].strip()
            key = (chain, resseq, icode)
            if key in seen_cys:
                continue
            seen_cys.add(key)
            if (chain, resseq) in ss:
                variant_map[key] = "CYX"

    # 5. Activity summary.
    by_kind: dict[str, int] = {}
    for name in variant_map.values():
        by_kind[name] = by_kind.get(name, 0) + 1
    by_kind_str = (", ".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
                   if by_kind else "none")
    print(f"  [prep] PROPKA + Reduce: {n_pka} titratable pKas scanned, "
          f"{len(variant_map)} residues renamed ({by_kind_str}); "
          f"{len(ss)} SS-bonded CYS.")

    return variant_map




def _warn_covalent_heterogen_bonds(pdb_path, verbose=False):
    """Scan CONECT records for bonds between an ATOM (protein) and a
    HETATM (heterogen). Emit a WARNING per covalent link so the user
    sees they're about to break a glycosylation site, ligand attachment,
    or PTM by using ``--strip-heterogens``.
    """
    # Build atom index → (record, chain, resname, resseq, atomname)
    atom_kind: dict[int, tuple[str, str, str, str, str]] = {}
    try:
        text = Path(pdb_path).read_text()
    except Exception:
        return
    for raw in text.splitlines():
        if not raw.startswith(("ATOM  ", "HETATM")) or len(raw) < 27:
            continue
        try:
            serial = int(raw[6:11].strip())
        except ValueError:
            continue
        atom_kind[serial] = (
            raw[:6].strip(), raw[21], raw[17:20].strip(),
            raw[22:26].strip(), raw[12:16].strip(),
        )
    covalent_hits: list[tuple] = []
    for raw in text.splitlines():
        if not raw.startswith("CONECT"):
            continue
        try:
            serials = [int(s) for s in raw[6:].split() if s]
        except ValueError:
            continue
        if len(serials) < 2:
            continue
        a = serials[0]
        rec_a = atom_kind.get(a)
        if rec_a is None:
            continue
        for b in serials[1:]:
            rec_b = atom_kind.get(b)
            if rec_b is None:
                continue
            if rec_a[0] == rec_b[0]:
                continue  # same class — ATOM-ATOM or HETATM-HETATM
            covalent_hits.append((rec_a, rec_b))
    if covalent_hits:
        print(f"  [strip-heterogens] WARNING: dropping {len(covalent_hits)} "
              f"covalent ATOM↔HETATM bond(s). Downstream MD will miss "
              f"these attachments. Pass --keep-heterogens to preserve.")
        if verbose:
            for a, b in covalent_hits[:10]:
                print(f"    {a[0]} {a[1]}/{a[2]}{a[3]}:{a[4]} → "
                      f"{b[0]} {b[1]}/{b[2]}{b[3]}:{b[4]}")


def _preprocess_glycoprotein_input(input_path, verbose=False):
    """Backward-compat wrapper around `ffutils.sanitize_protein_hetatm`.

    Retained for callers within this module; new callers should use
    `sanitize_protein_hetatm` from ffutils directly.
    """
    from dvbfixer.ffutils import sanitize_protein_hetatm
    return sanitize_protein_hetatm(input_path, verbose=verbose)



def _canonicalize_conect_records(input_path, verbose=False):
    """Rewrite CONECT records with fixed-width (5-char) atom serials.

    Some PDB writers emit space-separated CONECT serials (e.g. ``CONECT 5801 10293``
    where the 5-digit serial doesn't fit the standard 5-char field with a
    space separator). OpenMM's PDBFile parses such lines as 3+ atoms instead
    of 2, creating spurious bonds. Returns a temp path with corrected CONECT.
    """
    import tempfile as _tf
    needs_fix = False
    fixed_lines = []
    with open(input_path) as f:
        for line in f:
            if line.startswith('CONECT'):
                serials = line[6:].split()
                if any(len(s) > 5 for s in serials):
                    # Should not happen — PDB serials max at 99999
                    fixed_lines.append(line)
                    continue
                # Rewrite as fixed-width 5-char fields
                fixed = 'CONECT' + ''.join(f'{int(s):5d}' for s in serials) + '\n'
                if fixed != line:
                    needs_fix = True
                fixed_lines.append(fixed)
            else:
                fixed_lines.append(line)
    if not needs_fix:
        return input_path
    tmp_path = _tf.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False).name
    with open(tmp_path, 'w') as f:
        f.writelines(fixed_lines)
    if verbose:
        print(f"Canonicalized CONECT record formatting → {tmp_path}")
    return tmp_path


def run_pdbfixer(input_path, ph, keep_water, keep_heterogens, verbose,
                 mutations=None, heterogen_h=True, removed_residues_meta=None,
                 ff_xmls=None, his_default='HIE', cys_ss_pka=99.99,
                 use_propka=True, use_reduce=True):
    """Run PDBFixer to add missing atoms/residues. Returns (fixer, new_atom_indices).

    PROPKA + MolProbity Reduce (see ``_run_propka_reduce_variants``) run
    INSIDE this function, after PDBFixer's own heavy-atom repair
    (``findMissingAtoms`` + ``addMissingAtoms``) — not before. Both PROPKA
    and Reduce need a complete heavy-atom set to make any real protonation
    decision; running them on the raw (possibly heavy-atom-incomplete)
    input meant a residue with e.g. a missing imidazole ring (real
    crystallographic disorder — confirmed on a real structure) got no
    PROPKA result at all, silently deferring its HIS tautomer decision all
    the way to OpenMM's own internal auto-detect in `Modeller.addHydrogens`,
    which then raises an unrecoverable `ValueError: HIS residue (N) has
    the wrong set of atoms` — on both the whole-system attempt AND the
    protein-only fallback, since both share the same fragile logic.
    """
    # Normalise to str up front. `_preprocess_glycoprotein_input`/
    # `_canonicalize_conect_records` always return plain str (their
    # no-rewrite branches do `return str(pdb_path)` / return their own
    # str parameter unchanged) — but callers pass `input_path` as a
    # `Path` object. `some_str != some_path_object` is ALWAYS True in
    # Python regardless of whether they name the same file (`Path.__eq__`
    # requires matching types), so every `preprocess_was_rewritten`/
    # `canon_was_rewritten`/cleanup comparison below was silently wrong
    # whenever `input_path` was a `Path`: a completely no-op preprocess +
    # canonicalize pass (the common case — a clean PDB needing neither
    # fix) still evaluated `canon_path != input_path` as True and
    # unconditionally unlinked it — which, since no real rewrite
    # happened, IS the exact same file as `input_path`. Confirmed this
    # silently deleted the user's OWN INPUT FILE when `--no-infer-conect`
    # was passed on an input that didn't trigger some other temp-copy
    # step first. Keeping everything as str from here on makes the
    # comparisons mean what they say.
    input_path = str(input_path)
    # Glycoprotein-input fixes: rewrite HETATM→ATOM for protein/GLYCAM
    # glycoprotein residues (NLN/OLS/OLT) and drop spurious TER records
    # between same-chain protein residues. Both confuse OpenMM's topology
    # parser into breaking the peptide chain.
    preprocessed_path = _preprocess_glycoprotein_input(input_path, verbose)
    preprocess_was_rewritten = preprocessed_path != input_path
    # Canonicalize CONECT formatting — malformed records cause OpenMM bond
    # inference bugs (spurious bonds across distant atoms).
    canon_path = _canonicalize_conect_records(preprocessed_path, verbose)
    canon_was_rewritten = canon_path != preprocessed_path
    # If the canonicalize step produced a NEW temp file, the preprocessed
    # temp file is no longer referenced and can be cleaned up now.
    if preprocess_was_rewritten and canon_was_rewritten:
        Path(preprocessed_path).unlink(missing_ok=True)

    # Detect glycosylated atoms before PDBFixer modifies anything. Use the
    # dict-returning variant so we also know which sugar each anchor is
    # bonded to — needed to decide whether to rename ASN→NLN (only for
    # GLYCAM-named sugars).
    try:
        sugar_by_anchor = find_glycosylated_atoms_with_sugar(canon_path)
        glycosylated_atoms = set(sugar_by_anchor.keys())
        if glycosylated_atoms and verbose:
            print(f"Detected {len(glycosylated_atoms)} glycosylated atom(s)")

        with open(canon_path) as f:
            fixer = PDBFixer(pdbfile=f)
    finally:
        # Cleanup: delete any temp PDB we wrote, even if the block above
        # raised — otherwise these leak into /tmp on every failed run.
        # canon_path may be the same file as preprocessed_path (if
        # canonicalize was a no-op), so only one unlink covers both cases.
        if canon_path != input_path:
            Path(canon_path).unlink(missing_ok=True)
        if preprocess_was_rewritten and preprocessed_path != canon_path:
            Path(preprocessed_path).unlink(missing_ok=True)

    # Apply substitution mutations if requested. Deletions were already
    # applied at the raw-text level upstream (see main()).
    # variant_overrides: (chain, resnum, icode) -> variant name (HIP, ASH,
    # etc.) — icode is '' for --mutate entries (the --mutate CLI syntax has
    # no icode field) and for any residue without one.
    variant_overrides: dict[tuple[str, str, str], str] = {}
    if mutations:
        mutations_by_chain, _mutate_variant_overrides, _deletions_ignored = parse_mutations(mutations)
        variant_overrides = {
            (ch, rn, ''): var for (ch, rn), var in _mutate_variant_overrides.items()
        }
        if mutations_by_chain:
            print(f"Applying {sum(len(v) for v in mutations_by_chain.values())} mutation(s)...")
            apply_mutations(fixer, mutations_by_chain, verbose)
            if variant_overrides and verbose:
                for (ch, rn, ic), var in variant_overrides.items():
                    print(f"  Protonation override: {ch}:{rn}{ic} → {var}")

    # Capture AMBER/CHARMM protonation variant names from input PDB before
    # PDBFixer normalizes them. These are re-applied after replaceNonstandardResidues.
    #
    # Must scan the RAW PDB TEXT (`scan_variant_names`), not
    # `fixer.topology.residues()`: PDBFixer's own PDB parser normalizes
    # variant names (HIE/HID/HIP/... -> HIS, etc.) at CONSTRUCTION time —
    # by the point `fixer` exists, `res.name` is already "HIS"/"ASP"/...,
    # so a loop reading `fixer.topology` here can never actually match
    # `_VARIANT_TO_STANDARD` and was a silent no-op despite this exact
    # comment's stated intent. Scan `input_path` (still on disk and
    # untouched by residue-naming) rather than `canon_path`/
    # `preprocessed_path` — both temp files are already unlinked above by
    # this point.
    from dvbfixer.ffutils.variants import scan_variant_names as _scan_variant_names
    for (ch, rs, ic), variant_name in _scan_variant_names(input_path).items():
        key = (ch, rs, ic or '')
        if key not in variant_overrides and variant_name in _VARIANT_TO_STANDARD:
            variant_overrides[key] = variant_name

    # Strip hydrogens from protein residues (incl GLYCAM glycoprotein
    # residues NLN/OLS/OLT) before findMissingAtoms — clean template matching.
    # Heterogen H is preserved here: addHydrogens with GLYCAM FF will fill in
    # any missing H without disturbing existing ones (or rename wrong-cased H).
    _PROTEIN_AA = {
        'ALA', 'ARG', 'ASN', 'ASP', 'CYS', 'GLN', 'GLU', 'GLY', 'HIS', 'ILE',
        'LEU', 'LYS', 'MET', 'PHE', 'PRO', 'SER', 'THR', 'TRP', 'TYR', 'VAL',
        'HID', 'HIE', 'HIP', 'HSD', 'HSE', 'HSP', 'CYX', 'CYM', 'ASH', 'GLH',
        'LYN', 'MSE', 'ACE', 'NME', 'NHE',
        'NLN', 'OLS', 'OLT',  # GLYCAM glycosylated protein residues
    }
    modeller = Modeller(fixer.topology, fixer.positions)
    h_atoms = [a for a in modeller.topology.atoms()
               if a.element.symbol == 'H' and a.residue.name in _PROTEIN_AA]

    # Coincident-atom detection: if an input H is placed on top of another
    # atom in the same protein residue (e.g. HG dumped at OXT position by
    # an upstream tool — reported against test/broken_SER/SER.pdb), stripping
    # only the H isn't enough. OpenMM's `Modeller.addHydrogens` then re-
    # places that H at the OTHER atom's position again (it inherits OXT's
    # index during template matching for CSER). Fix by also stripping the
    # non-H partner — PDBFixer's `addMissingAtoms` re-adds it at the right
    # position (based on the C-terminal backbone), and `addHydrogens` places
    # H correctly without the interfering atom.
    from openmm.unit import nanometer as _nm
    _COINCIDENT_TOL_NM = 0.05  # 0.5 Å — well below any real bond
    extra_to_strip = []
    pos = modeller.positions
    for res in modeller.topology.residues():
        if res.name not in _PROTEIN_AA:
            continue
        res_atoms = list(res.atoms())
        for a in res_atoms:
            if a.element.symbol != 'H':
                continue
            pa = pos[a.index].value_in_unit(_nm)
            for b in res_atoms:
                if b.index == a.index or b.element.symbol == 'H':
                    continue
                pb = pos[b.index].value_in_unit(_nm)
                d2 = ((pa[0]-pb[0])**2 + (pa[1]-pb[1])**2 + (pa[2]-pb[2])**2)
                if d2 < _COINCIDENT_TOL_NM * _COINCIDENT_TOL_NM:
                    extra_to_strip.append(b)
                    if verbose:
                        print(f"  Coincident atom: {res.chain.id}/{res.name}{res.id}/"
                              f"{a.name} overlaps {b.name} — stripping {b.name} so "
                              f"PDBFixer re-places it correctly")
                    break

    strip_list = h_atoms + extra_to_strip
    if strip_list:
        modeller.delete(strip_list)
        if verbose:
            print(f"Stripped {len(h_atoms)} H + {len(extra_to_strip)} coincident heavy atom(s) for clean template matching (will re-add)")
        import tempfile as _tf
        with _tf.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as _tmp:
            PDBFile.writeFile(modeller.topology, modeller.positions, _tmp, keepIds=True)
            _tmp_path = _tmp.name
        try:
            with open(_tmp_path) as _f:
                fixer = PDBFixer(pdbfile=_f)
        finally:
            Path(_tmp_path).unlink()

    # Record original atoms before any modifications
    original_atoms = set()
    for atom in fixer.topology.atoms():
        original_atoms.add((atom.residue.chain.id, atom.residue.id,
                            atom.residue.insertionCode, atom.name))

    fixer.findMissingResidues()

    # Scrub missingResidues entries that correspond to user-requested
    # deletions, so PDBFixer's SEQRES-driven gap filler doesn't re-add the
    # residue we just removed. PDBFixer keys missingResidues by
    # (chain_index, residue_position_within_chain). For each deletion, find
    # the gap-position that sits between the kept neighbours and pop it.
    if removed_residues_meta:
        chains_list = list(fixer.topology.chains())
        # PDBFixer permits multiple chains to share a chain ID (e.g. when a
        # HETATM block at the end of the file gets a separate Chain object
        # with the same letter as a protein chain). Build chain_id → list
        # of chain indices, then map every deletion to all matching chains.
        chain_id_to_indices = {}
        for i, ch in enumerate(chains_list):
            chain_id_to_indices.setdefault(ch.id, []).append(i)
        chain_residues = {}
        for i, ch in enumerate(chains_list):
            chain_residues[i] = [(r.id, r.insertionCode) for r in ch.residues()]

        deletion_resseqs_by_chain = {}
        for m in removed_residues_meta:
            for ch_idx in chain_id_to_indices.get(m["chain"], []):
                deletion_resseqs_by_chain.setdefault(ch_idx, []).append(
                    (m["resid"], m.get("icode") or ' ')
                )

        scrubbed_keys = []
        for (ch_idx, pos), resnames in list(fixer.missingResidues.items()):
            if ch_idx not in deletion_resseqs_by_chain:
                continue
            # Determine the resseq range this missingResidues entry covers.
            # `pos` is the insertion index in chain_residues[ch_idx]: the
            # gap is between residue (pos-1) and residue (pos). For each
            # deletion in this chain, check whether its resseq falls between
            # the flanking residues' resseqs.
            chain_res = chain_residues[ch_idx]
            prev_resseq = None
            next_resseq = None
            if pos > 0 and pos - 1 < len(chain_res):
                try:
                    prev_resseq = int(chain_res[pos - 1][0])
                except ValueError:
                    prev_resseq = None
            if pos < len(chain_res):
                try:
                    next_resseq = int(chain_res[pos][0])
                except ValueError:
                    next_resseq = None
            # If any deletion in this chain has a resseq strictly between
            # prev and next, that's our gap — scrub it.
            for (rs_str, _ic) in deletion_resseqs_by_chain[ch_idx]:
                try:
                    rs = int(rs_str)
                except ValueError:
                    continue
                between = (
                    (prev_resseq is None or rs > prev_resseq)
                    and (next_resseq is None or rs < next_resseq)
                )
                # Also handle the "deletion is the chain terminus" case
                if between or (next_resseq is None and pos == len(chain_res)):
                    scrubbed_keys.append((ch_idx, pos))
                    break
        for k in scrubbed_keys:
            fixer.missingResidues.pop(k, None)
        if verbose and scrubbed_keys:
            print(f"  Scrubbed {len(scrubbed_keys)} missingResidues gap(s) "
                  f"for user-deleted residues")

    fixer.findNonstandardResidues()

    # Filter out GLYCAM glycoprotein residues BEFORE printing/replacing —
    # NLN/OLS/OLT look "non-standard" to PDBFixer but they're deliberate
    # (they carry the glycan attachment via sidechain N/O). Showing "NLN
    # -> LEU" misleads users; doing the replacement would destroy the
    # glycosylation site. Strip them up-front.
    _GLYCAM_PROTEIN = {'NLN', 'OLS', 'OLT'}
    fixer.nonstandardResidues = [
        (res, std) for (res, std) in fixer.nonstandardResidues
        if res.name not in _GLYCAM_PROTEIN
    ]

    if verbose:
        if fixer.missingResidues:
            print("Missing residues:")
            for (chain_idx, res_idx), resnames in sorted(fixer.missingResidues.items()):
                chain_id = list(fixer.topology.chains())[chain_idx].id
                print(f"  Chain {chain_id} position {res_idx}: {' '.join(resnames)}")
        if fixer.nonstandardResidues:
            print("Nonstandard residues:")
            for res, std in fixer.nonstandardResidues:
                print(f"  {res.chain.id}/{res.name}{res.id} -> {std}")

    # Order below matches PDBFixer's own canonical usage (findNonstandard-
    # Residues -> replaceNonstandardResidues -> removeHeterogens ->
    # findMissingAtoms -> addMissingAtoms), NOT the order this function used
    # before: both `removeHeterogens()` and `replaceNonstandardResidues()`
    # rebuild an entirely new Topology internally (via `Modeller(...).
    # delete(...)`), which silently invalidates any earlier `findMissingAtoms()`
    # dict — it's keyed by Residue OBJECT identity against the topology that
    # existed at the time, not by value. Calling `findMissingAtoms()` before
    # either rebuild meant `fixer.addMissingAtoms()` looked up stale keys
    # against a topology it no longer matched, silently adding ZERO heavy
    # atoms for every genuinely-missing sidechain (confirmed: e.g. a
    # backbone+CB-only LYS from real crystallographic disorder stayed
    # backbone+CB-only straight through `prepare`, even though PDBFixer's own
    # `findMissingAtoms()` correctly detected CG/CD/CE/NZ as missing
    # beforehand) whenever heterogens were removed or a nonstandard residue
    # was replaced — i.e. on every default run. `findMissingResidues()`
    # above is safe to call early: `missingResidues` is keyed by
    # `(chain.index, indexInChain)`, a positional pair that (for this
    # codebase's inputs) survives the later rebuilds, unlike Residue-object
    # identity.
    if not keep_heterogens:
        _warn_covalent_heterogen_bonds(input_path, verbose=verbose)

    fixer.replaceNonstandardResidues()

    if not keep_heterogens:
        # PDBFixer's built-in keep set does not include the peptide caps ACE
        # and NME, even though OpenMM classifies them as Protein in
        # pdbNames.xml.  Preserve caps explicitly under --strip-heterogens;
        # otherwise `zbs --cap-termini --strip-heterogens` adds the caps and
        # silently deletes them again in this call.
        has_caps = any(r.name in {'ACE', 'NME'} for r in fixer.topology.residues())
        if has_caps:
            from pdbfixer.pdbfixer import dnaResidues, proteinResidues, rnaResidues
            keep_resnames = set(proteinResidues).union(dnaResidues).union(rnaResidues)
            keep_resnames.update({'N', 'UNK', 'ACE', 'NME'})
            if keep_water:
                keep_resnames.add('HOH')
            to_delete = [r for r in fixer.topology.residues()
                         if r.name not in keep_resnames]
            modeller = Modeller(fixer.topology, fixer.positions)
            modeller.delete(to_delete)
            fixer.topology = modeller.topology
            fixer.positions = modeller.positions
        else:
            fixer.removeHeterogens(keepWater=keep_water)

    fixer.findMissingAtoms()

    if verbose:
        if fixer.missingAtoms:
            print("Missing atoms:")
            for res, atoms in fixer.missingAtoms.items():
                print(f"  {res.chain.id}/{res.name}{res.id}: {', '.join(a.name for a in atoms)}")
        if fixer.missingTerminals:
            print("Missing terminals:")
            for res, atoms in fixer.missingTerminals.items():
                print(f"  {res.chain.id}/{res.name}{res.id}: {', '.join(a if isinstance(a, str) else a.name for a in atoms)}")

    n_missing_res = sum(len(v) for v in fixer.missingResidues.values())
    n_missing_atoms = sum(len(v) for v in fixer.missingAtoms.items())
    print(f"PDBFixer: {n_missing_res} missing residues, {n_missing_atoms} residues with missing atoms")

    # Seeded, retried rebuild — see rebuild_missing_atoms_with_retry's
    # docstring for why PDBFixer's own unseeded addMissingAtoms() is
    # unsafe to call directly (its clash-escape fallback is genuine
    # unseeded stochastic MD).
    from dvbfixer.ffutils.geometry import rebuild_missing_atoms_with_retry as _rebuild
    _rebuild(fixer, verbose=verbose, log_prefix="[prepare] ")

    # Belt-and-braces: on branched-Cβ residues (VAL/ILE/THR) template
    # alignment can still occasionally pick the D configuration even in a
    # clash-free rebuild. Reflect any inversions back to L before H addition.
    from dvbfixer.ffutils.geometry import fix_ca_chirality as _fix_chirality
    _chir_fixed = _fix_chirality(fixer.topology, fixer.positions, verbose=verbose)
    if verbose and _chir_fixed:
        print(f"  [prepare] flipped {_chir_fixed} Cα chirality inversion(s)")

    # PROPKA + MolProbity Reduce run HERE — on `fixer`'s current,
    # heavy-atom-complete state — not on the original input. Both tools
    # need a full heavy-atom set to make a real decision (see this
    # function's docstring for the concrete failure mode this avoids).
    extra_variants: dict = {}
    if use_propka or use_reduce:
        import tempfile as _tf
        with _tf.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as _tmp:
            PDBFile.writeFile(fixer.topology, fixer.positions, _tmp, keepIds=True)
            _propka_input_path = _tmp.name
        try:
            from dvbfixer.acpype_export import detect_ss_bonds
            try:
                _ss_pairs = detect_ss_bonds(_propka_input_path)
            except Exception:
                _ss_pairs = set()
            extra_variants = _run_propka_reduce_variants(
                _propka_input_path,
                ph=ph,
                ss_pairs=_ss_pairs,
                his_default=his_default,
                cys_ss_pka=cys_ss_pka,
                use_propka=use_propka,
                use_reduce=use_reduce,
                verbose=verbose,
            )
        finally:
            Path(_propka_input_path).unlink(missing_ok=True)

    # Build explicit variants list for addHydrogens.
    # PDBFixer's addMissingHydrogens ignores our topology renames — it uses
    # its own _describeVariant which only understands standard names.
    # We call Modeller.addHydrogens directly with our variants list.
    #
    # OpenMM variant names: 'HIE', 'HID', 'HIP' for HIS; 'ASH' for ASP;
    # 'GLH' for GLU; 'CYX' for CYS (disulfide). None = auto-detect by pH.
    _OPENMM_VARIANTS = {'HIE', 'HID', 'HIP', 'ASH', 'GLH', 'CYX', 'CYM', 'LYN'}

    # Merge PROPKA + Reduce output (extra_variants, 3-tuple keys) with
    # user --mutate / raw-text-captured overrides (variant_overrides,
    # already 3-tuple `(chain, resid, icode)` keys). User entries win on
    # collision — matches .dat schema "downstream wins". Kept as one
    # single 3-tuple-keyed dict throughout (no 2-tuple collapse) so two
    # residues sharing a resSeq via insertion code (e.g. Kabat CDR-loop
    # `H:82`/`H:82A`) never overwrite each other's variant.
    merged_variants: dict[tuple[str, str, str], str] = {}
    if extra_variants:
        for (ch, rn, ic), var in extra_variants.items():
            merged_variants[(ch, str(rn), ic or '')] = var
    for (ch, rn, ic), var in variant_overrides.items():
        merged_variants[(ch, str(rn), ic or '')] = var
    variant_overrides = merged_variants

    variants = []
    for res in fixer.topology.residues():
        _ic = res.insertionCode.strip() if hasattr(res, 'insertionCode') else ''
        key3 = (res.chain.id, str(res.id), _ic)
        _var = variant_overrides.get(key3) or variant_overrides.get(
            (res.chain.id, str(res.id), ''))
        if _var and _var in _OPENMM_VARIANTS:
            from dvbfixer.ffutils.variants import openmm_hydrogen_variant
            variants.append(openmm_hydrogen_variant(_var))
            if verbose:
                print(f"  {res.name} {res.chain.id}:{res.id} → variant {_var}")
        elif res.name == 'HIS':
            # Detect from existing H atoms (if any survived stripping)
            atom_names = {a.name for a in res.atoms()}
            if 'HD1' in atom_names and 'HE2' in atom_names:
                variants.append('HIP')
            elif 'HD1' in atom_names:
                variants.append('HID')
            elif 'HE2' in atom_names:
                variants.append('HIE')
            elif ('ND1' not in atom_names or 'NE2' not in atom_names):
                # Defensive backstop: OpenMM's own auto-detect (which
                # `None` defers to) requires exactly one ND1 and one NE2
                # and raises an unrecoverable ValueError otherwise. This
                # should be unreachable now that PROPKA/Reduce run after
                # heavy-atom repair (see this function's docstring), but
                # a residue PDBFixer's template rebuild can't fully fix
                # for some other reason must never be able to crash the
                # whole pipeline when a sane default already exists.
                variants.append(his_default)
                print(f"  WARNING: {res.chain.id}/{res.name}{res.id} still "
                      f"lacks a complete ND1/NE2 ring after heavy-atom "
                      f"repair — forcing --his-default ({his_default}) "
                      f"instead of OpenMM's auto-detect (which requires "
                      f"both and would raise otherwise).")
            else:
                variants.append(None)  # let OpenMM auto-detect by pH
        else:
            variants.append(None)

    modeller = Modeller(fixer.topology, fixer.positions)
    # Rename glycosylated ASN/SER/THR → NLN/OLS/OLT — but ONLY for those
    # bonded to GLYCAM-named sugars (UYB/4YB/...). For PDB-named sugars
    # (NAG/NDG/BMA/...) we keep ASN; HD22 is still removed downstream by
    # remove_extra_glycan_hydrogens.
    if heterogen_h and glycosylated_atoms:
        new_top, new_pos, _renamed = rename_glycosylated_protein_residues(
            modeller.topology, modeller.positions, glycosylated_atoms, verbose,
            sugar_by_anchor=sugar_by_anchor,
        )
        modeller = Modeller(new_top, new_pos)
    # OpenMM's Modeller.addHydrogens looks up `res.name` in its internal
    # `_residueHydrogens` dict — which is keyed by the standard residue name
    # ("LYS", "HIS", "CYS"), not by AMBER variant names ("LYN", "HID", "HIE",
    # ...). When a topology has a residue with `res.name = "LYN"`, addHydrogens
    # SKIPS it entirely (residue.name not in _residueHydrogens) — no H atoms
    # get added — and the next createSystem call then fails with
    # "No template found for residue (LYN). The set of heavy atoms matches
    # LYN, but the residue is missing N H atoms."
    #
    # Fix: rename topology residues from AMBER variant names back to their
    # standard parents BEFORE calling addHydrogens, pass the variants list
    # so addHydrogens applies the variant rules (gates HZ3 for LYS-only,
    # skips HE2 for HID, etc.), then restore the variant names after.
    from dvbfixer.ffutils.variants import (
        fix_lyn_hz_naming as _fix_lyn_hz_naming_shared,
    )
    from dvbfixer.ffutils.variants import (
        rename_variants_to_parent_in_topology as _rename_variants_to_parent,
    )
    from dvbfixer.ffutils.variants import (
        restore_variants_post_addhydrogens as _restore_variants_post_addhydrogens,
    )

    def _fix_lyn_hz_naming(top, saved):
        renamed = _fix_lyn_hz_naming_shared(top, saved)
        if verbose and renamed:
            print(f"  Renamed HZ1→HZ3 on {renamed} LYN residue(s) to match "
                  f"AMBER ff14SB/ff19SB LYN template (HZ2 + HZ3)")

    if heterogen_h:
        # BioLuminate-style: add H to protein AND heterogens (sugars, ligands).
        # ff_xmls comes from the caller (resolved via ffutils.resolve_ff).
        # Fall back to amber14+GLYCAM if caller didn't pass one. The
        # water-model XML is included for ion templates (Ca2+, Mg2+, Zn2+,
        # Na+, Cl-, K+, etc.) which AMBER ships inside the water XML. For
        # arbitrary unknown ligands without an FF template, run `minimize
        # --parametrize-ligands` (GAFF2 + AM1-BCC) rather than relying on
        # this step (prepare only needs enough templates to place H).
        _ff_xmls = ff_xmls or ['amber14-all.xml',
                               'amber14/GLYCAM_06j-1.xml',
                               'amber14/tip3pfb.xml']
        try:
            from dvbfixer.ffutils import build_glycam_system
            ff = build_glycam_system(
                _ff_xmls, modeller.topology, modeller.positions, verbose=verbose,
            )
            _saved = _rename_variants_to_parent(modeller.topology)
            try:
                modeller.addHydrogens(ff, pH=ph, variants=variants)
                from dvbfixer.ffutils.geometry import repair_misplaced_hydrogens
                repair_misplaced_hydrogens(modeller.topology, modeller.positions, verbose=verbose)
            finally:
                _fix_lyn_hz_naming(modeller.topology, _saved)
                _restore_variants_post_addhydrogens(modeller.topology, _saved)
        except (ValueError, KeyError, Exception) as e:
            from dvbfixer.ffutils import (
                PROTEIN_RESIDUES,
                SOLVENT_IONS,
                explain_template_error,
            )
            diag = explain_template_error(e, modeller.topology, ff)
            # Classify: was the failed residue an unknown ligand (expected —
            # OpenBabel/RDKit will place its H below) or something else
            # (real problem)?
            known = PROTEIN_RESIDUES | SOLVENT_IONS
            failed_name = None
            try:
                import re as _re
                m = _re.search(r'residue\s+(\d+)\s+\(([A-Za-z0-9_]+)\)',
                               str(e))
                if m:
                    failed_name = m.group(2)
            except Exception:
                failed_name = None
            is_unknown_ligand = (failed_name is not None
                                 and failed_name not in known)

            if is_unknown_ligand:
                print(f"  INFO: {failed_name} has no FF template — its H "
                      f"atoms will be placed by OpenBabel/RDKit (universal). "
                      f"Pass `dvbfixer minimize --parametrize-ligands` for "
                      f"real GAFF2 parameters downstream.")
                if verbose and diag:
                    for line in diag.split('\n'):
                        print(f"    {line}")
            else:
                print(f"  WARNING: whole-topology addHydrogens failed "
                      f"({type(e).__name__}: {e}); falling back to "
                      f"protein-only.")
                if diag:
                    for line in diag.split('\n'):
                        print(f"    {line}")
            # Rebuild modeller since addHydrogens may have left it half-modified
            modeller = Modeller(fixer.topology, fixer.positions)
            _saved = _rename_variants_to_parent(modeller.topology)
            try:
                modeller.addHydrogens(pH=ph, variants=variants)
                from dvbfixer.ffutils.geometry import repair_misplaced_hydrogens
                repair_misplaced_hydrogens(modeller.topology, modeller.positions, verbose=verbose)
            finally:
                _fix_lyn_hz_naming(modeller.topology, _saved)
                _restore_variants_post_addhydrogens(modeller.topology, _saved)
    else:
        # Legacy: protein-only H addition
        _saved = _rename_variants_to_parent(modeller.topology)
        try:
            modeller.addHydrogens(pH=ph, variants=variants)
            from dvbfixer.ffutils.geometry import repair_misplaced_hydrogens
            repair_misplaced_hydrogens(modeller.topology, modeller.positions, verbose=verbose)
        finally:
            _fix_lyn_hz_naming(modeller.topology, _saved)
            _restore_variants_post_addhydrogens(modeller.topology, _saved)
    fixer.topology = modeller.topology
    fixer.positions = modeller.positions

    # Polish step: use OpenBabel to add H atoms to any heterogens (sugars,
    # ligands) that the AMBER/GLYCAM addHydrogens pass couldn't handle.
    # OpenBabel uses valence rules + connectivity and works for arbitrary
    # organic molecules without needing templates or SMILES.
    # Heterogen H is now added by add_heterogen_h_via_rdkit in main(), after
    # the PDB is written with CONECTs. RDKit sees the full molecular graph
    # (CONECT + distance perception) and places H atoms with proper geometry.

    # Remove extra hydrogens from glycosylated residues
    if glycosylated_atoms:
        remove_extra_glycan_hydrogens(fixer, glycosylated_atoms, verbose)

    # Identify which atoms in the new topology are newly added
    new_atom_indices = set()
    added_residue_ids = set()
    for atom in fixer.topology.atoms():
        key = (atom.residue.chain.id, atom.residue.id,
               atom.residue.insertionCode, atom.name)
        if key not in original_atoms:
            new_atom_indices.add(atom.index)
            added_residue_ids.add((atom.residue.chain.id, atom.residue.id))

    if verbose:
        n_new_heavy = sum(1 for idx in new_atom_indices
                          for atom in [list(fixer.topology.atoms())[idx]]
                          if atom.element.symbol != 'H')
        print(f"Added {len(new_atom_indices)} atoms ({n_new_heavy} heavy), "
              f"across {len(added_residue_ids)} residues")

    return fixer, new_atom_indices, variant_overrides


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _main_tleap_reduce_backend(args, input_path, output_path, dat_path):
    """Deterministic prep pipeline via `dvbfixer.prep_backend.run_prep`
    (tleap + reduce + PROPKA-driven variant renames).

    Handles the simple case: protein + standard AAs + no heterogens.
    If the input has non-canonical residues tleap rejects, raises
    ``TleapError`` with the offending residue in the message; user
    should retry with ``--backend legacy`` or supply the missing
    leaprc via a future ``--extra-leaprc`` flag.
    """
    from dvbfixer.acpype_export import detect_ss_bonds
    from dvbfixer.ffutils.dat import DatRecord
    from dvbfixer.ffutils.geometry import find_d_residues
    from dvbfixer.prep_backend import TleapError, apply_output_naming, run_prep

    # SS bond detection from CONECT (drives CYX assignment).
    try:
        ss_res = detect_ss_bonds(str(input_path))
    except Exception:
        ss_res = set()

    if args.mutate:
        print("ERROR: --mutate is not yet supported by the tleap-reduce "
              "backend. Rerun with --backend legacy for mutations.",
              file=sys.stderr)
        sys.exit(2)

    original_input_path = input_path
    if getattr(args, "cap_termini", False):
        from dvbfixer.terminal_caps import add_terminal_caps_to_pdb
        try:
            input_path = add_terminal_caps_to_pdb(
                input_path,
                chain_ids=args.cap_chain or None,
                verbose=args.verbose,
            )
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc

    print(f"=== prep (tleap + reduce): {input_path} ===")
    try:
        result = run_prep(
            input_path, output_path,
            ph=args.ph, ff="leaprc.protein.ff19SB",
            assign_variants=True, ss_pairs=ss_res,
            verbose=args.verbose,
        )
    except TleapError as e:
        print(f"\nERROR: tleap failed on {input_path}. This usually means "
              f"a non-canonical residue (GLYCAM sugar, phosphorylated AA, "
              f"exotic ligand) that ff14SB doesn't know. Rerun with "
              f"--backend legacy for the PDBFixer+Modeller path which "
              f"handles more edge cases.\n{e}", file=sys.stderr)
        sys.exit(1)

    # Chirality check — WARN only, don't raise. Modeller upstream can
    # produce a D-Cα that tleap preserves; downstream minimize catches
    # + reflects. Raising here would abort the zbs pipeline before
    # minimize has a chance.
    from openmm.app import PDBFile
    _pdb = PDBFile(str(output_path))
    _d = find_d_residues(_pdb.topology, _pdb.positions)
    if _d:
        print(f"  WARNING: {len(_d)} D-Cα residue(s) after prepare "
              f"(minimize should catch): "
              + ", ".join(f"{c}/{n}{r}" for c, r, n, _ in _d[:5]))

    # tleap itself requires native AMBER names. Apply the requested public
    # output convention only after tleap, Reduce, and the chirality check.
    apply_output_naming(
        output_path,
        result["renames"],
        atom_naming=getattr(args, "atom_naming", "gromacs"),
        verbose=args.verbose,
    )

    # Emit .dat file. tleap adds heavy atoms deterministically, but we
    # don't have a per-atom "was this added" flag from tleap. Simplest
    # correct approach: consider ALL H atoms + any heavy atoms not
    # present in the original input as "added" (weak restraint in
    # minimize). Match by (chain, resseq, icode, atom name).
    orig_keys: set[tuple[str, str, str, str]] = set()
    for raw in original_input_path.read_text().splitlines():
        if not raw.startswith(("ATOM  ", "HETATM")) or len(raw) < 27:
            continue
        orig_keys.add((raw[21], raw[22:26].strip(),
                       raw[26].strip(), raw[12:16].strip()))
    added_atoms = []
    residue_summary: dict[str, dict[str, int]] = {}
    for raw in output_path.read_text().splitlines():
        if not raw.startswith(("ATOM  ", "HETATM")) or len(raw) < 27:
            continue
        chain = raw[21]
        resseq = raw[22:26].strip()
        icode = raw[26].strip()
        atom_name = raw[12:16].strip()
        resname = raw[17:20].strip()
        elem = raw[76:78].strip() if len(raw) >= 78 else ""
        key = (chain, resseq, icode, atom_name)
        # Hydrogens are always "added" (input was pre-existing, tleap
        # re-placed all H); heavy atoms only added if not in input.
        is_h = elem == "H" or (not elem and atom_name and atom_name[0] == "H")
        if is_h or key not in orig_keys:
            added_atoms.append({
                "chain": chain, "resid": resseq, "icode": icode,
                "resname": resname, "atom": atom_name,
                "element": elem or ("H" if is_h else atom_name[0]),
            })
            rkey = f"{chain}/{resname}{resseq}"
            bucket = residue_summary.setdefault(
                rkey, {"heavy": 0, "hydrogen": 0}
            )
            if is_h:
                bucket["hydrogen"] += 1
            else:
                bucket["heavy"] += 1

    dat = DatRecord(
        description="Deterministic prep via tleap+reduce. Hydrogens and "
                    "any tleap-added heavy atoms (OXT, missing sidechain) "
                    "get weak restraints in minimize; original heavy "
                    "atoms get strong restraints.",
        added_atoms=added_atoms,
        residue_summary=residue_summary,
        # "chain:resid:icode" — same unambiguous 3-field format the legacy
        # backend uses (icode empty when none); NOT "chain:resid" + icode
        # concatenated onto resid, which can't be told apart from a longer
        # plain resid on read-back.
        variant_overrides={f"{c}:{r}:{i}": v
                            for (c, r, i), v in result["renames"].items()},
    )
    upstream_dat = original_input_path.with_suffix('.dat')
    if upstream_dat.exists():
        dat.merge(DatRecord.load(upstream_dat))
    dat.save(dat_path)
    print(f"Saved prepared structure: {output_path}")
    print(f"Saved restraint data: {dat_path} "
          f"({len(added_atoms)} added atoms)")


def main(argv=None):
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    try:
        smiles_by_resname = parse_smiles_mappings(getattr(args, "smiles", []))
    except SmilesPreparationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if smiles_by_resname:
        incompatible = []
        if getattr(args, "backend", "legacy") != "legacy":
            incompatible.append("--backend tleap-reduce")
        if not args.keep_heterogens:
            incompatible.append("--strip-heterogens")
        if not args.heterogen_h:
            incompatible.append("--no-heterogen-h")
        if incompatible:
            print("Error: --smiles is incompatible with " + ", ".join(incompatible),
                  file=sys.stderr)
            raise SystemExit(2)
    if args.cap_chain and not args.cap_termini:
        print("Error: --cap-chain requires --cap-termini", file=sys.stderr)
        raise SystemExit(2)

    output_path = Path(args.output) if args.output else input_path.with_stem(input_path.stem + "_prepared")
    dat_path = Path(args.dat) if args.dat else output_path.with_suffix(".dat")

    # Deterministic backend: tleap (heavy atoms) + reduce (H). This is the
    # default. Skips the entire legacy PDBFixer.addMissingAtoms +
    # Modeller.addHydrogens code path — both had upstream bugs (stochastic
    # D-Cα from PDBFixer, coincident H atoms from Modeller) that we
    # exhausted several rounds of workarounds on. See prep_backend.py
    # docstring for the diagnosis. Legacy backend is still selectable via
    # --backend legacy for GLYCAM glycoproteins / exotic heterogens tleap
    # rejects.
    if getattr(args, "backend", "legacy") == "tleap-reduce":
        return _main_tleap_reduce_backend(args, input_path, output_path,
                                           dat_path)

    # Auto-infer CONECT records into a temp PDB copy so downstream flows
    # (glycosylation detection, mutation glycan walk, SS detection) work on
    # inputs that lack explicit CONECT.
    if not args.no_infer_conect:
        from dvbfixer.pdbutils import _materialise_inferred_pdb
        input_path = Path(_materialise_inferred_pdb(
            input_path, verbose=args.verbose))

    # Resolve --ff for the heterogen-H step. Only prints when heterogen-H
    # actually runs; auto-detects from residue names.
    from dvbfixer.ffutils import (
        has_pdb_standard_sugars,
        print_ff_selection,
        resolve_ff,
    )
    _ff_xmls, _ff_alias, _ff_reason = resolve_ff(
        args.ff, input_path, verbose=args.verbose)

    # Two coordinated auto-transforms driven by the resolved FF alias:
    # (a) amber+glycam on a PDB-named glycoprotein → convert PDB sugar
    #     names to GLYCAM canonical naming so the FF templates match.
    # (b) charmm on a PDB-named glycoprotein → process the run under
    #     amber+glycam (which has sugar templates), then rewrite the
    #     final output to CHARMM sugar names post-hoc. Record the
    #     original request so the post-run rewrite can find it.
    _charmm_output_requested = False
    if _ff_alias == 'charmm' and has_pdb_standard_sugars(input_path):
        print("  [ff] charmm requested but input has PDB-standard "
              "sugars charmm36.xml can't parametrise; processing "
              "with amber+glycam and rewriting output residue names "
              "to CHARMM convention.")
        _charmm_output_requested = True
        from dvbfixer.ffutils import FF_ALIASES
        _ff_alias = 'amber+glycam'
        _ff_xmls = FF_ALIASES['amber+glycam']
        _ff_reason = (
            'auto-switched from charmm (PDB sugars need GLYCAM); '
            'output residue names will be rewritten back to CHARMM'
        )

    if _ff_alias == 'amber+glycam' and has_pdb_standard_sugars(input_path):
        from dvbfixer.glycam import convert_to_glycam
        from dvbfixer.tempfiles import make_temp_path
        _conv_out = make_temp_path(suffix='.pdb', prefix='dvbfixer_glycam_')
        try:
            convert_to_glycam(str(input_path), str(_conv_out),
                              add_roh=True, verbose=args.verbose)
            print("  [ff] auto-converted PDB-standard sugar names → "
                  "GLYCAM canonical for amber+glycam FF matching.")
            input_path = Path(_conv_out)
        except Exception as e:
            print(f"  [ff] convert_to_glycam failed ({e}); continuing "
                  f"with original names — createSystem may fail on "
                  f"unrecognised sugar residues.")

    if args.heterogen_h:
        print_ff_selection(_ff_alias, _ff_reason, _ff_xmls)

    if args.rename:
        from dvbfixer.rename import canonicalize_pdb
        from dvbfixer.tempfiles import make_temp_path
        _tmp = make_temp_path(suffix='.pdb')
        n = canonicalize_pdb(input_path, _tmp, args.verbose)
        if n > 0:
            print(f"Canonicalized {n} non-canonical residue(s)")
            input_path = _tmp
        elif _tmp.exists():
            _tmp.unlink()

    # Apply --mutate ...:del deletions AND substitution-cleanup at the raw-
    # text level BEFORE PDBFixer. Substitution cleanup removes dependent
    # atoms/records (attached glycan tree, SS partner repair, LINK records)
    # for substitution mutations where the new AA can't carry the old AA's
    # sidechain-mediated bonds — e.g. --mutate H:297:ALA on a glycosylated
    # ASN removes the entire NAG-NAG-BMA-... tree along with the substitution.
    removed_residues_meta = []
    deletion_path = input_path
    if args.mutate:
        subs_by_chain, _vars, deletions = parse_mutations(args.mutate)
        # Build substitution-cleanup list: read old residue name from raw PDB
        # so we can decide whether the cleanup is needed (skip CYS→CYX style
        # protonation-variant renames where the parent residue is unchanged).
        substitution_cleanups = []
        if subs_by_chain:
            old_resname = {}  # (chain, int(resseq)) → resname
            with open(input_path) as _f:
                for _line in _f:
                    if not _line.startswith(('ATOM  ', 'HETATM')):
                        continue
                    try:
                        _rs = int(_line[22:26].strip())
                    except ValueError:
                        continue
                    _ch = _line[21]
                    _rn = _line[17:20].strip()
                    old_resname.setdefault((_ch, _rs), _rn)
            for ch, muts in subs_by_chain.items():
                for (resnum_str, new_aa) in muts:
                    try:
                        rs = int(resnum_str)
                    except ValueError:
                        continue
                    orn = old_resname.get((ch, rs))
                    if orn is None:
                        continue
                    substitution_cleanups.append((ch, rs, ' ', orn, new_aa))
        if deletions or substitution_cleanups:
            if deletions:
                print(f"Applying {len(deletions)} deletion mutation(s)...")
            deletion_path, removed_residues_meta = apply_deletions_to_pdb_text(
                input_path, deletions, verbose=args.verbose,
                substitution_cleanups=substitution_cleanups,
            )
            input_path = deletion_path

    precap_atom_keys: set[tuple[str, str, str, str]] = set()
    if args.cap_termini:
        for raw in Path(input_path).read_text().splitlines():
            if raw.startswith(("ATOM  ", "HETATM")) and len(raw) >= 27:
                precap_atom_keys.add((raw[21], raw[22:26].strip(),
                                      raw[26].strip(), raw[12:16].strip()))
        from dvbfixer.terminal_caps import add_terminal_caps_to_pdb
        try:
            input_path = add_terminal_caps_to_pdb(
                input_path,
                chain_ids=args.cap_chain or None,
                verbose=args.verbose,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc

    # PROPKA + Reduce now run INSIDE run_pdbfixer, after PDBFixer's own
    # heavy-atom repair (findMissingAtoms/addMissingAtoms) — not before.
    # See run_pdbfixer's docstring: running them on the raw input let a
    # heavy-atom-incomplete residue (e.g. a missing imidazole ring) get
    # no PROPKA result at all, deferring its variant decision all the
    # way to OpenMM's own fragile auto-detect logic in addHydrogens,
    # which then crashes with an unrecoverable ValueError.
    print(f"=== PDBFixer: {input_path} ===")
    fixer, new_atom_indices, variant_overrides = run_pdbfixer(
        input_path, args.ph, args.keep_water, args.keep_heterogens, args.verbose,
        mutations=args.mutate, heterogen_h=args.heterogen_h,
        removed_residues_meta=removed_residues_meta,
        ff_xmls=_ff_xmls,
        his_default=getattr(args, 'his_default', 'HIE'),
        cys_ss_pka=getattr(args, 'cys_ss_pka', 99.99),
        use_propka=getattr(args, 'propka', True),
        use_reduce=getattr(args, 'protassign', True),
    )

    # Heavy cap atoms were inserted before PDBFixer, so run_pdbfixer's
    # ordinary before/after comparison sees them as pre-existing.  Restore
    # their real provenance for the .dat restraint policy while leaving
    # genuinely pre-capped input atoms classified as original.
    if args.cap_termini:
        for atom in fixer.topology.atoms():
            if atom.residue.name not in {'ACE', 'NME'}:
                continue
            key = (atom.residue.chain.id, atom.residue.id,
                   atom.residue.insertionCode.strip(), atom.name)
            if key not in precap_atom_keys:
                new_atom_indices.add(atom.index)

    # Write PDB with standard names first (OpenMM writes HETATM for non-standard)
    with open(output_path, 'w') as f:
        PDBFile.writeFile(fixer.topology, fixer.positions, f, keepIds=True)

    # Build var_lookup for variant name restoration (applied after each PDB
    # write). Split into an icode-specific map and an any-icode fallback map
    # (same pattern as ffutils.ff_names.apply_variants_to_pdb_text) so two
    # residues sharing a resSeq via insertion code (Kabat CDR loops) each
    # keep their own variant instead of the last one in iteration order
    # silently winning for both.
    var_lookup_by_icode: dict[tuple[str, str, str], str] = {}
    var_lookup_any_icode: dict[tuple[str, str], str] = {}
    for (ch, rn, ic), var_name in variant_overrides.items():
        if ic:
            var_lookup_by_icode[(ch, rn, ic)] = var_name
        else:
            var_lookup_any_icode[(ch, rn)] = var_name

    def _restore_variants(path):
        if not var_lookup_by_icode and not var_lookup_any_icode:
            return
        with open(path) as f:
            pdb_lines = f.readlines()
        with open(path, 'w') as f:
            for line in pdb_lines:
                if line.startswith(('ATOM  ', 'HETATM', 'TER   ')) and len(line) > 26:
                    ch = line[21]
                    rs = line[22:26].strip()
                    ic = line[26].strip()
                    var = var_lookup_by_icode.get((ch, rs, ic))
                    if var is None:
                        var = var_lookup_any_icode.get((ch, rs))
                    if var:
                        # Preserve the original record type (ATOM/HETATM/TER)
                        # — hardcoding "ATOM  " here used to corrupt TER
                        # lines (which have no atom-name or coordinate
                        # fields) into malformed, coordinate-less ATOM
                        # records whenever the terminal residue itself had
                        # a variant override (e.g. a C-terminal CYX).
                        line = f"{line[:17]}{var:>3s}{line[20:]}"
                f.write(line)

    _restore_variants(output_path)

    # Emit CONECT records for inter/intra heterogen bonds. OpenMM's
    # PDBFile.writeFile doesn't write CONECTs by default, so PyMOL/VMD can't
    # show the protein-glycan and sugar-sugar bonds. minimize.py also needs
    # them to reconstruct topology bonds.
    _write_heterogen_conects(output_path, fixer.topology)

    if smiles_by_resname:
        old_atoms = list(fixer.topology.atoms())
        previous_new_keys = {
            (old_atoms[index].residue.chain.id, old_atoms[index].residue.id,
             old_atoms[index].residue.insertionCode, old_atoms[index].name)
            for index in new_atom_indices
        }
        old_atom_keys = {
            (a.residue.chain.id, a.residue.id, a.residue.insertionCode, a.name)
            for a in old_atoms
        }
        try:
            fixer.topology, fixer.positions = add_hydrogens_from_smiles(
                fixer.topology, fixer.positions, smiles_by_resname, args.verbose,
            )
        except SmilesPreparationError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        with open(output_path, 'w') as f:
            PDBFile.writeFile(fixer.topology, fixer.positions, f, keepIds=True)
        _restore_variants(output_path)
        _write_heterogen_conects(output_path, fixer.topology)
        new_atom_indices = set()
        for atom in fixer.topology.atoms():
            key = (atom.residue.chain.id, atom.residue.id,
                   atom.residue.insertionCode, atom.name)
            if key in previous_new_keys or key not in old_atom_keys:
                new_atom_indices.add(atom.index)

    # BioLuminate-style polish: pipe through RDKit so it sees the full
    # molecular graph (CONECT-derived bonds + distance perception) and adds H
    # to any heterogens that still need them, with proper 3D geometry.
    # RDKit honors all bonds (protein-glycan, sugar-sugar, intra-sugar) so it
    # won't add spurious H at linkage positions.
    # Skip the RDKit/OpenBabel polish passes when every heterogen is already
    # GLYCAM-named (UYB/4YB/VMB/NLN/...) — the AMBER14+GLYCAM addHydrogens
    # step inside run_pdbfixer already placed all H atoms correctly using
    # the GLYCAM templates + glycam-hydrogens.xml definitions. Running the
    # polish on top would strip and re-add H via valence rules, breaking
    # GLYCAM atom names (C2N/O2N/CME/etc.) that OpenBabel doesn't recognize.
    from dvbfixer.ffutils import PROTEIN_RESIDUES as _PR
    from dvbfixer.ffutils import SOLVENT_IONS as _SI
    from dvbfixer.ffutils import is_glycam_residue
    _known = _PR | _SI
    needs_polish = any(
        not is_glycam_residue(r.name) and r.name not in _known
        and r.name not in smiles_by_resname
        for r in fixer.topology.residues()
    )
    if args.heterogen_h and not needs_polish and args.verbose:
        print("No unmapped non-GLYCAM heterogens need RDKit/OpenBabel polish")

    if args.heterogen_h and needs_polish:
        # Two-pass heterogen H addition:
        #   1. RDKit AddHs(addCoords=True) — full-graph, fast for fully-perceived
        #      sugars. Often miscounts H on ring carbons when proximityBonding
        #      adds spurious cross-residue bonds (over-coordinated → no H).
        #   2. OpenBabel per-residue fallback — strips stale H from residues
        #      that came out under-protonated, regenerates from valence rules.
        for h_pass in (add_heterogen_h_via_rdkit, add_heterogen_h_via_openbabel):
            if h_pass is add_heterogen_h_via_rdkit:
                new_top, new_pos = h_pass(
                    fixer.topology, fixer.positions, output_path, args.verbose,
                    excluded_resnames=smiles_by_resname,
                )
            else:
                new_top, new_pos = h_pass(
                    fixer.topology, fixer.positions, args.verbose,
                    excluded_resnames=smiles_by_resname,
                )
            if new_top is not fixer.topology:
                old_atom_keys = {
                    (a.residue.chain.id, a.residue.id, a.residue.insertionCode, a.name)
                    for a in fixer.topology.atoms()
                }
                fixer.topology = new_top
                fixer.positions = new_pos
                with open(output_path, 'w') as f:
                    PDBFile.writeFile(fixer.topology, fixer.positions, f, keepIds=True)
                _restore_variants(output_path)
                _write_heterogen_conects(output_path, fixer.topology)
                for atom in fixer.topology.atoms():
                    key = (atom.residue.chain.id, atom.residue.id,
                           atom.residue.insertionCode, atom.name)
                    if key not in old_atom_keys:
                        new_atom_indices.add(atom.index)

    # Rewrite HETATM→ATOM for AMBER protonation variants and GLYCAM
    # glycoprotein residues (NLN/OLS/OLT). PDBFile.writeFile defaults these
    # to HETATM. _restore_variants already covers user-mutated variants;
    # this catches any residue that slipped through (e.g. NLN coming in
    # from the input file).
    from dvbfixer.ffutils import fix_atom_hetatm_records as _fix_records
    _fix_records(output_path)
    # Restore AMBER variant residue names + GROMACS LYN atom names.
    # OpenMM's PDBFile.writeFile canonicalised them; recover from
    # user-mutated variants (`variant_overrides`) plus any variants
    # already in the raw input text (`scan_variant_names` output).
    from dvbfixer.ffutils.ff_names import (
        AMBER_VARIANTS,
        apply_variants_to_pdb_text,
    )
    from dvbfixer.ffutils.variants import scan_variant_names
    _ff_target = 'charmm' if 'charmm' in (_ff_alias or '').lower() else 'amber'
    _merged_variants = {}
    try:
        _input_scan = scan_variant_names(str(args.input))
        for (ch, resid, icode), v in _input_scan.items():
            if v in AMBER_VARIANTS:
                _merged_variants[(ch, resid, icode)] = v
    except Exception:
        pass
    for (ch, rn, ic), var_name in variant_overrides.items():
        _merged_variants[(ch, str(rn), ic)] = var_name
    _n_var = apply_variants_to_pdb_text(
        output_path, _merged_variants,
        target_ff=_ff_target, verbose=args.verbose,
        include_gromacs_shifts=(getattr(args, 'atom_naming', 'gromacs')
                                 == 'gromacs'),
    )
    if _n_var and args.verbose:
        print(f"  Applied {_n_var} variant name/atom rewrites to output")

    # CHARMM output was requested but the pipeline ran under
    # amber+glycam (because the input had PDB-standard sugars).
    # Rewrite sugar residue names GLYCAM → CHARMM so the output
    # matches what the user asked for at the CLI. Coordinates and
    # topology unchanged; only sugar residue names are affected.
    if _charmm_output_requested:
        from dvbfixer.glycam import convert_to_charmm
        from dvbfixer.tempfiles import make_temp_path
        _tmp = make_temp_path(suffix='.pdb', prefix='dvbfixer_charmm_out_')
        try:
            convert_to_charmm(str(output_path), str(_tmp), verbose=args.verbose)
            import shutil as _sh
            _sh.move(str(_tmp), str(output_path))
            print("  [ff] rewrote sugar residue names GLYCAM → CHARMM "
                  "for output (user asked for --ff charmm).")
        except Exception as e:
            print(f"  [ff] convert_to_charmm on output failed ({e}); "
                  f"output has GLYCAM sugar names — run "
                  f"`dvbfixer convert --to-charmm` manually.")

    print(f"Saved prepared structure: {output_path}")

    dat = build_dat(fixer, new_atom_indices)

    # Save variant overrides in .dat so minimize can restore them. Key
    # format is always "chain:resid:icode" (icode empty when none) — an
    # unambiguous 3-field split, unlike concatenating resid+icode with no
    # separator (which can't be told apart from a longer plain resid).
    if variant_overrides:
        dat['variant_overrides'] = {
            f"{ch}:{rn}:{ic}": var for (ch, rn, ic), var in variant_overrides.items()
        }

    # Record any --mutate ...:del removals so downstream minimize / model
    # tools know which residues are intentionally absent.
    if removed_residues_meta:
        dat['removed_residues'] = removed_residues_meta

    # Merge with upstream .dat (e.g. from model step) if it exists.
    # Delegate to ffutils.dat's merge logic so the "downstream wins on
    # optional-field collision" semantics stay in one place.
    # Preprocessing may replace input_path with an inferred/capped/converted
    # temporary PDB. The model restraint sidecar belongs to the user's input.
    upstream_dat = Path(args.input).with_suffix('.dat')
    if upstream_dat.exists():
        from dvbfixer.ffutils.dat import DatRecord

        known = {
            "description", "residue_summary", "added_atoms",
            "variant_overrides", "removed_residues", "templates", "target_chains",
        }
        downstream = DatRecord(**{k: v for k, v in dat.items() if k in known})
        upstream = DatRecord.load(upstream_dat)
        carried = downstream.merge(upstream)
        dat = downstream.to_dict()
        if carried > 0:
            print(f"Merged {carried} atoms from upstream {upstream_dat.name}")

    write_dat(dat, dat_path)

    # AMBER protein XMLs do not provide combined N/C-terminal templates for
    # protonated ASH/GLH or neutral LYN/CYM.  Preserve those states when the
    # end is explicitly ACE/NME-capped; otherwise revert to the supported
    # parent residue and keep the PDB and restraint sidecar consistent.
    if _ff_target == "amber":
        from dvbfixer.ffutils.artificial_terminals import (
            normalize_fasta_truncated_terminal_variants,
        )

        changed = normalize_fasta_truncated_terminal_variants(
            output_path, dat_path=dat_path, force_field=_ff_target,
        )
        for chain, resid, old, parent in changed:
            print(
                f"  WARNING: AMBER has no uncapped terminal {old} template; "
                f"changed {chain}:{resid} to {parent}. Use --cap-termini to "
                "preserve terminal protonation."
            )

    # Clean up the deletion-cleaned temp file (if one was created)
    if deletion_path != Path(args.input).resolve() and deletion_path != Path(args.input):
        try:
            Path(deletion_path).unlink(missing_ok=True)
        except (OSError, TypeError):
            pass
