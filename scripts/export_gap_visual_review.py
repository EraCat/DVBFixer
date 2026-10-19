#!/usr/bin/env python3
"""Export the exact before/masked/restored structures for manual visual review."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atoms(path):
    result = {}
    for line in path.read_text().splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            key = (line[21], line[22:26].strip(), line[26].strip(), line[12:16].strip())
            if key in result:
                raise ValueError(f"duplicate atom in {path}: {key}")
            result[key] = (line[30:54], line[17:20].strip())
    return result


def residue(record):
    return record["chain"], record["residue_number"], record["insertion_code"]


def label(record):
    return record["chain"] + ":" + record["residue_number"] + record["insertion_code"]


def collect():
    old = ROOT / ".artifacts/a100-local-relaxation-cuda12"
    new = ROOT / ".artifacts/prospective-relaxation-holdout"
    old_report = json.loads((old / "analysis.json").read_text())
    new_report = json.loads((new / "analysis.json").read_text())
    if not old_report["complete"] or not new_report["complete"]:
        raise ValueError("visual review requires completed source reports")
    cases = []
    for cohort, report, base, result_name in (
        ("development", old_report, old, "relaxed-runner-result.json"),
        ("new_holdout", new_report, new / "selected", "selected-runner-result.json"),
    ):
        for row in report["cases"]:
            if row["arm"] not in {"static-local", "full-raw"}:
                continue
            root = base / row["case_id"] / row["arm"]
            marker = json.loads((root / "complete.json").read_text())
            for relative, expected in marker["artifacts"].items():
                if sha(root / relative) != expected:
                    raise ValueError(f"archive digest changed: {root / relative}")
            request = json.loads((root / "request.json").read_text())
            result = json.loads((root / result_name).read_text())
            candidate = result["candidates"][0]["coordinate_artifact"]
            if sha(root / candidate["path"]) != candidate["sha256"]:
                raise ValueError("restored candidate digest changed")
            before, masked, restored = root / "reference.pdb", root / request["normalized_pdb"]["path"], root / candidate["path"]
            if sha(masked) != request["normalized_pdb"]["sha256"]:
                raise ValueError("masked input digest changed")
            original_atoms, masked_atoms, restored_atoms = atoms(before), atoms(masked), atoms(restored)
            generated = {(*residue(atom), atom["atom_name"]) for atom in request["generated_atoms"]}
            if set(original_atoms) - set(masked_atoms) != generated or set(masked_atoms) - set(original_atoms):
                raise ValueError("before/masked pair does not contain exactly the requested deletion")
            if set(restored_atoms) != set(original_atoms):
                raise ValueError("restored atom identities differ from the complete input")
            if any(original_atoms[key] != value or restored_atoms[key] != value for key, value in masked_atoms.items()):
                raise ValueError("unmasked atoms differ between review structures")
            gap = request["gaps"][0]
            if len(request["gaps"]) != 1:
                raise ValueError("review layout expects one gap per case")
            passed = row["relaxed_passed"] if cohort == "development" else row["selected"]["validation"]["passed"]
            gates = row["relaxed_failed_gates"] if cohort == "development" else row["selected"]["validation"]["hard_gate_failures"]
            cases.append({"protein": row["source_id"], "case_id": row["case_id"], "cohort": cohort,
                "seed": request["seeds"][0], "length": row["length"], "gap": gap,
                "deleted_residue_ids": [label(item) for item in gap["generated_residues"]],
                "deleted_sequence": next(target["sequence"] for target in request["target_sequences"] if target["chain"] == gap["chain"])[gap["target_interval"]["start"]:gap["target_interval"]["stop"]],
                "geometry_passed": passed, "failed_gates": gates,
                "source_files": {"01_before_gap.pdb": before, "02_gapped_input.pdb": masked, "03_restored_relaxed.pdb": restored}})
    return sorted(cases, key=lambda case: (case["protein"], case["length"], case["seed"]))


def export(output):
    if output.exists():
        raise ValueError(f"refusing to overwrite an existing review folder: {output}")
    cases = collect()
    if len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError("duplicate review case")
    output.mkdir()
    by_protein = defaultdict(list)
    rows = []
    for case in cases:
        directory = output / case["protein"] / f"gap_{case['length']:03d}" / f"seed_{case['seed']:03d}"
        directory.mkdir(parents=True)
        metadata = {key: value for key, value in case.items() if key != "source_files"}
        metadata["directory"] = directory.relative_to(output).as_posix()
        metadata["files"] = {}
        for name, source in case["source_files"].items():
            shutil.copyfile(source, directory / name)
            if sha(directory / name) != sha(source):
                raise ValueError("copied review file differs from archived artifact")
            metadata["files"][name] = {"source": source.relative_to(ROOT).as_posix(), "sha256": sha(source)}
        gap = case["gap"]
        left, right = label(gap["left_anchor"]), label(gap["right_anchor"])
        selection = f'chain "{gap["chain"]}" and resi ' + "+".join(item["residue_number"] + item["insertion_code"] for item in gap["generated_residues"])
        metadata["pymol_gap_selection"] = selection
        (directory / "gap.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
        (directory / "README.md").write_text(
            f"# {case['protein']} — гэп {case['length']}, seed {case['seed']}\n\n"
            f"- Цепь: `{gap['chain']}` (регистр важен).\n- Удалены: `{', '.join(case['deleted_residue_ids'])}`.\n"
            f"- Последовательность удалённого участка: `{case['deleted_sequence']}`.\n- Якоря: `{left}` и `{right}`.\n"
            f"- Серия: `{case['cohort']}`.\n- Геометрические проверки после минимизации: **{'PASS' if case['geometry_passed'] else 'FAIL'}**.\n"
            f"- Причины отказа: {', '.join(case['failed_gates']) or 'нет'}.\n\n"
            "## Структуры\n\n1. `01_before_gap.pdb` — полный фрагмент до искусственного удаления.\n"
            "2. `02_gapped_input.pdb` — фактический инпут с удалённым участком.\n"
            "3. `03_restored_relaxed.pdb` — результат Protenix после локальной минимизации с фиксированным окружением.\n\n"
            "Файлы уже в одной системе координат, дополнительное совмещение не требуется.\n\n"
            f"Выделение участка в PyMOL (для структуры до гэпа и восстановленной):\n\n```\n{selection}\n```\n",
            encoding="utf-8")
        rows.append(metadata)
        by_protein[case["protein"]].append(metadata)
    sources = {}
    for manifest, folder in (("cuda-calibration-sources.json", "cuda-calibration-sources"),
                             ("relaxation-holdout-sources-blosum62.json", "relaxation-holdout-sources-blosum62")):
        for case in json.loads((ROOT / "docs/research" / manifest).read_text())["cases"]:
            if case["pdb_id"] in by_protein:
                source = ROOT / ".artifacts" / folder / (case["pdb_id"] + ".cif")
                if sha(source) != case["source_sha256"]:
                    raise ValueError("deposited source digest changed")
                shutil.copyfile(source, output / case["pdb_id"] / "deposited_source.cif")
                sources[case["pdb_id"]] = case
    for protein, records in by_protein.items():
        lines = [f"# {protein}\n", "`deposited_source.cif` — исходная полная депонированная структура для контекста.\n",
                  f"Исходная target auth chain в CIF: `{sources[protein]['target_auth_chain']}`.\n",
                  "Модель получала выбранный белковый фрагмент/подкомплекс, не весь CIF; точные инпуты лежат ниже.\n",
                  "Подробная обрезка цепей **до создания гэпа**: [chain_coverage.md](chain_coverage.md).\n",
                 "| Случай | Цепь в PDB | Удалённые остатки | Геометрия |\n|---|---|---|---|\n"]
        for record in records:
            relative = str(Path(record["directory"]).relative_to(protein))
            lines.append(f"| [{relative}]({relative}/) | `{record['gap']['chain']}` | {', '.join(record['deleted_residue_ids'])} | {'PASS' if record['geometry_passed'] else 'FAIL'} |\n")
        (output / protein / "README.md").write_text("\n".join(lines), encoding="utf-8")
    with (output / "index.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("protein", "cohort", "length", "seed", "chain", "deleted_residues", "left_anchor", "right_anchor", "geometry", "directory"))
        for row in rows:
            writer.writerow((row["protein"], row["cohort"], row["length"], row["seed"], row["gap"]["chain"], ";".join(row["deleted_residue_ids"]),
                label(row["gap"]["left_anchor"]), label(row["gap"]["right_anchor"]), "PASS" if row["geometry_passed"] else "FAIL", row["directory"]))
    (output / "manifest.json").write_text(json.dumps({"protein_count": len(by_protein), "case_count": len(rows), "cases": rows}, indent=2, ensure_ascii=False) + "\n")
    (output / "README.md").write_text(
        f"# Структуры для визуального просмотра гэпов\n\n{len(by_protein)} белков, {len(rows)} случаев; по 3 PDB на случай.\n\n"
        "**Важно: исходники обрезались ещё ДО создания гэпа.** `01_before_gap.pdb` не содержит все наблюдаемые части депонированных цепей. "
        "Точные границы, причины и отброшенные цепи: [аудит покрытия](chain_coverage.md).\n\n"
        "```text\ngap_visual_review/\n  12NP/\n    deposited_source.cif\n    gap_005/\n      seed_007/\n        01_before_gap.pdb\n        02_gapped_input.pdb\n        03_restored_relaxed.pdb\n        gap.json\n        README.md\n```\n\n"
        "## Где искать участок\n\nОбщий список цепей, удалённых остатков, якорей и путей — в `index.csv`. "
        "В каждой папке случая есть README с точным выделением для PyMOL и JSON с происхождением файлов. "
        "Регистр цепей и insertion codes сохранены. Три PDB уже в одной системе координат.\n\n"
        "## Как выбирались дырки\n\nОкна выбраны по фиксированному хешу среди допустимых участков без CYS. "
        "**Отбор НЕ исключал альфа-спирали, бета-тяжи или смешанную вторичную структуру.** "
        "Для разных длин гэпа у одного белка могут быть разные положения — это не обязательно расширение одной петли. "
        "Seed 7 и 19 при одинаковой длине используют одно и то же удаление, но разные генерации.\n\n"
        "## Что именно лежит в файлах\n\n`01_before_gap.pdb` — полный выбранный фрагмент/подкомплекс непосредственно перед удалением, "
        "а не вся депонированная структура. Полный исходный CIF лежит рядом в папке белка. "
        "`02_gapped_input.pdb` — фактический инпут. `03_restored_relaxed.pdb` — итог жёстко фиксированной локальной релаксации. "
        "Включены и прошедшие, и отклонённые результаты; PASS обозначает геометрические проверки, не визуальную оценку.\n\n"
        "Серии: 64 случая из 7 development-структур и 15 случаев из 3 новых holdout-структур, "
        "по одному базовому контекстному режиму. Копии байт-в-байт совпадают с архивами; "
        "проверено, что удалены ровно заявленные атомы, а окружение после восстановления не изменилось.\n\n"
        "Проверка копий: `sha256sum -c CHECKSUMS.sha256` из этой папки.\n", encoding="utf-8")
    from audit_gap_chain_coverage import audit

    audit(output)
    print(json.dumps({"output": str(output), "proteins": len(by_protein), "cases": len(rows), "pdb_files": len(rows) * 3,
        "passed": sum(row["geometry_passed"] for row in rows), "failed": sum(not row["geometry_passed"] for row in rows)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "gap_visual_review")
    export(parser.parse_args().output.resolve())


if __name__ == "__main__":
    main()
