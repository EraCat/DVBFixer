#!/usr/bin/env python3
"""Trace deposited-chain truncation through frozen fragment selection and export."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote

import gemmi
from materialize_cuda_fragment_calibration import complete_runs
from materialize_protein_context_expansion import source_records

from dvbfixer.model.diffusion.scope import CANONICAL_HEAVY_ATOMS

ROOT = Path(__file__).resolve().parents[1]


def residue_id(residue):
    return str(residue.seqid.num) + residue.seqid.icode.strip()


def span(residues):
    return f"{residue_id(residues[0])}…{residue_id(residues[-1])}" if residues else "—"


def breakup_events(chain):
    events, previous = [], None
    for residue in chain:
        expected = CANONICAL_HEAVY_ATOMS.get(residue.name)
        observed = {atom.name: atom for atom in residue if atom.altloc in {"\x00", " ", "A"} and not atom.element.is_hydrogen}
        if expected is None:
            if gemmi.find_tabulated_residue(residue.name).is_amino_acid():
                events.append({"residue": residue_id(residue), "name": residue.name, "reason": "noncanonical-amino-acid"})
            previous = None
        elif not set(expected) <= observed.keys():
            events.append({"residue": residue_id(residue), "name": residue.name, "reason": "incomplete-heavy-atoms", "missing": sorted(set(expected) - observed.keys())})
            previous = None
        else:
            if previous is not None:
                distance = previous["C"][0].pos.dist(observed["N"].pos)
                if not 1.0 <= distance <= 1.8:
                    events.append({"left": residue_id(previous), "right": residue_id(residue), "reason": "cn-distance-outside-screening-range", "distance_angstrom": distance})
            previous = residue
    return events


def replay_selection(structure, target_chain):
    target = max(complete_runs(structure[0][target_chain]), key=lambda run: (len(run), -run[0].seqid.num))
    selected = [(target_chain, target[:250])]
    partners = []
    for chain in structure[0]:
        if chain.name == target_chain:
            continue
        for run in complete_runs(chain):
            if len(run) < 12:
                continue
            distance, center = min((residue["CA"][0].pos.dist(other["CA"][0].pos), index)
                                   for index, residue in enumerate(run) for other in selected[0][1])
            start = max(0, min(center - 60, len(run) - 120))
            partners.append((distance, chain.name, start, run[start:start + 120]))
    if partners:
        _distance, identifier, _start, partner = min(partners, key=lambda item: item[:3])
        selected.append((identifier, partner))
    return selected


def audit(review):
    manifest = json.loads((review / "manifest.json").read_text())
    grouped = defaultdict(list)
    for case in manifest["cases"]:
        grouped[case["protein"]].append(case)
    records = []
    for protein, cases in sorted(grouped.items()):
        cohort = "cuda-fragment-calibration-cohort" if cases[0]["cohort"] == "development" else "relaxation-holdout-cohort"
        frozen = json.loads((ROOT / "docs/research" / (cohort + ".json")).read_text())
        screening = next(record for record in frozen["screening"] if record["pdb_id"] == protein)
        directory = ROOT / ".artifacts" / cohort / "screening" / protein
        if hashlib.sha256((review / protein / "deposited_source.cif").read_bytes()).hexdigest() != screening["source_sha256"]:
            raise ValueError(f"{protein}: deposited source digest changed")
        if hashlib.sha256((directory / "selected-protein-fragments.cif").read_bytes()).hexdigest() != screening["derived_source_sha256"]:
            raise ValueError(f"{protein}: selected fragment digest changed")
        source = gemmi.read_structure(str(review / protein / "deposited_source.cif"))
        derived = gemmi.read_structure(str(directory / "selected-protein-fragments.cif"))
        selection = replay_selection(source, screening["target_auth_chain"])
        predicted = {(chain, residue_id(residue), residue.name) for chain, run in selection for residue in run}
        actual = {(chain.name, residue_id(residue), residue.name) for chain in derived[0] for residue in chain}
        if predicted != actual:
            raise ValueError(f"{protein}: fragment selection cannot reproduce archived derived CIF")
        normalized = (directory / "selected-protein-fragments.pdb").read_bytes()
        _rows, lines, _points = source_records(normalized, tuple(screening["declared_chains"]))
        expected_before = ("".join(lines) + "TER\nEND\n").encode()
        for case in cases:
            if (review / case["directory"] / "01_before_gap.pdb").read_bytes() != expected_before:
                raise ValueError(f"{protein}: review does not match archived normalized selection")
        mapping = {chain: chain for chain, _run in selection}
        for line in normalized.decode().splitlines():
            prefix = "REMARK 999 DVBFIXER CIF_CHAIN_MAP "
            if line.startswith(prefix):
                new, old = line[len(prefix):].split(" ", 1)
                mapping[unquote(old.strip())] = new
            if "CIF_CHAIN_MAP_PART" in line:
                raise ValueError("chunked chain mapping needs explicit audit support")
        before_residues = {(line[21], line[22:26].strip() + line[26].strip(), line[17:20].strip()) for line in lines}
        mapped_selection = {(mapping[chain], identifier, name) for chain, identifier, name in predicted}
        if before_residues != mapped_selection:
            raise ValueError(f"{protein}: normalization/reference extraction dropped selected residues")
        selected_by_chain = dict(selection)
        chains = []
        for chain in source[0]:
            amino = [residue for residue in chain if gemmi.find_tabulated_residue(residue.name).is_amino_acid()]
            polymer = [residue for residue in chain if residue.entity_type == gemmi.EntityType.Polymer]
            if not amino and not polymer:
                continue
            runs = complete_runs(chain)
            kept = selected_by_chain.get(chain.name, [])
            kept_ids = {residue_id(residue) for residue in kept}
            omitted = [residue for residue in amino if residue_id(residue) not in kept_ids]
            chains.append({"source_chain": chain.name, "pdb_chain": mapping.get(chain.name) if kept else None,
                "role": "target" if chain.name == screening["target_auth_chain"] else ("partner" if kept else "omitted-chain"),
                "observed_amino_acid_count": len(amino), "observed_amino_acid_span": span(amino),
                "observed_polymer_residue_count": len(polymer), "retained_residue_count": len(kept), "retained_span": span(kept),
                "omitted_amino_acid_count": len(omitted), "omitted_amino_acid_ids": [residue_id(residue) for residue in omitted],
                "complete_runs": [{"count": len(run), "span": span(run)} for run in runs], "breakup_events": breakup_events(chain)})
        record = {"protein": protein, "target_auth_chain": screening["target_auth_chain"], "chains": chains,
            "selection_replay_matches_derived_cif": True, "before_gap_matches_normalized_selected_input": True,
            "normalization_preserves_all_selected_residues": True,
            "all_case_before_gap_files_verified": len(cases),
            "selection_policy": "longest complete target run capped250; one nearest complete partner run capped120; all other chains omitted before artificial gap creation"}
        records.append(record)
        text = [f"# {protein}: покрытие исходных цепей\n",
            "Это сопоставление наблюдаемых остатков в deposited_source.cif с экспериментальным фрагментом до создания гэпа.\n",
            "Обработка воспроизводит архивный выбранный CIF и все 01_before_gap.pdb без расхождений.\n",
            "| Цепь CIF | Роль | Наблюдаемые аминокислоты | Сохранено до гэпа | Убрано до гэпа |\n|---|---|---|---|---|\n"]
        for row in chains:
            text.append(f"| `{row['source_chain']}` | {row['role']} | {row['observed_amino_acid_count']} ({row['observed_amino_acid_span']}) | {row['retained_residue_count']} ({row['retained_span']}) | {row['omitted_amino_acid_count']} |\n")
        for row in chains:
            if not row["retained_residue_count"]:
                continue
            text.append(f"\n## Цепь {row['source_chain']} ({row['role']})\n\nПолные непрерывные фрагменты до ограничения длины:\n")
            text.extend(f"- {run['span']}: {run['count']} остатков.\n" for run in row["complete_runs"])
            text.append("\nПричины разделения исходной цепи:\n")
            for event in row["breakup_events"]:
                if event["reason"] == "incomplete-heavy-atoms":
                    text.append(f"- {event['residue']} {event['name']}: отсутствуют тяжёлые атомы {', '.join(event['missing'])}; остаток отбрасывался, цепь делилась.\n")
                elif event["reason"] == "noncanonical-amino-acid":
                    text.append(f"- {event['residue']} {event['name']}: неканоническая аминокислота, фрагмент прерывался.\n")
                else:
                    text.append(f"- {event['left']} → {event['right']}: C–N {event['distance_angstrom']:.3f} Å вне 1.0–1.8 Å.\n")
            if not row["breakup_events"]:
                text.append("- Нет: обрезка связана с выбором/ограничением длины фрагмента, а не неполнотой цепи.\n")
        (review / protein / "chain_coverage.md").write_text("".join(text), encoding="utf-8")
    report = {"proteins": records, "cause": "explicit-fragment-selection-before-CIF-normalization-and-before-artificial-gap", "structure_files_modified": False}
    (review / "chain_coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    text = ["# Аудит обрезки цепей до создания гэпов\n\n",
        "**01_before_gap.pdb уже содержит искусственно выбранный фрагмент/подкомплекс. Это не полные депонированные цепи.**\n\n",
        "Обрезка выполнена в materialize_cuda_fragment_calibration.py до нормализации CIF и до удаления экспериментального гэпа: выбирался самый длинный непрерывный участок с полным набором тяжёлых атомов (целевая цепь ≤250 остатков), затем один ближайший фрагмент другой цепи (≤120 остатков). Остальные цепи и остальные участки выбранных цепей исключались. Даже отсутствие бокового тяжёлого атома разрывало допустимый фрагмент.\n\n",
        "Повторный расчёт выбора точно воспроизводит архивные selected-protein-fragments.cif; нормализованный отбор точно воспроизводит все 79 файлов 01_before_gap.pdb. Следовательно, обнаруженная обрезка объясняется подготовкой выборки, а не дополнительной потерей остатков при экспорте или нормализации CIF.\n\n",
        "Сохранение окружения в предыдущих экспериментах проверялось относительно уже обрезанного входа, а не относительно полной структуры. Окружение, удалённое до создания гэпа, модель не видела. Эти эксперименты нельзя считать проверкой восстановления в полном структурном контексте.\n\n",
        "| Белок | Цепь | Роль | Аминокислот в CIF | Сохранено до гэпа | Диапазон |\n|---|---|---|---:|---:|---|\n"]
    for record in records:
        for row in record["chains"]:
            if row["retained_residue_count"]:
                text.append(f"| [{record['protein']}]({record['protein']}/chain_coverage.md) | `{row['source_chain']}` | {row['role']} | {row['observed_amino_acid_count']} | {row['retained_residue_count']} | {row['retained_span']} |\n")
    text.append("\nПолные списки удалённых до гэпа остатков, все отброшенные цепи и причины разбиения — в chain_coverage.json и в chain_coverage.md каждого белка. Нумерация и регистр цепей сохранены; считаются наблюдаемые координатные остатки, а не отсутствующие в плотности позиции SEQRES. Файлы структур и замороженные результаты не изменены.\n")
    (review / "chain_coverage.md").write_text("".join(text), encoding="utf-8")
    checksums = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(review).as_posix()}\n"
                 for path in sorted(review.rglob("*")) if path.is_file() and path.name != "CHECKSUMS.sha256"]
    (review / "CHECKSUMS.sha256").write_text("".join(checksums))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, default=ROOT / "gap_visual_review")
    report = audit(parser.parse_args().review.resolve())
    print(json.dumps({"proteins_audited": len(report["proteins"]), "selection_and_export_replayed": True}, indent=2))


if __name__ == "__main__":
    main()
