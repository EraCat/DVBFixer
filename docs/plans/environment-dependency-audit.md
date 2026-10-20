# План B. Ревизия модулей и состава окружения

**Статус на 2026-10-20: частично подготовлен, миграция packaging не выполнена.**
Отдельные ML runner environments и `doctor` уже существуют; это не означает,
что выполнены описанные ниже optional installation profiles, полная ревизия
transitive/executable dependencies или clean-install matrix. В `pyproject.toml`
пока определён только optional extra `dev`. Исправление eager Torch import в
Protenix helper не добавляет Torch в core и не завершает весь аудит.
Сводный статус: [индекс планов](README.md).

## B.1. Цель и правила аудита

- Провести отдельную ревизию:
  - `environment.yml`;
  - обязательных dependencies в `pyproject.toml`;
  - будущих optional dependency groups;
  - внешних executable;
  - GUI/dev dependencies;
  - platform-specific diffusion environments.
- Не считать отсутствие direct import доказательством ненужности.
- Для каждого пакета проверить:
  - eager и lazy imports;
  - command entrypoints;
  - subprocess executable lookups;
  - optional backend paths;
  - tests/fixtures;
  - docs/install instructions;
  - GUI/build scripts;
  - возможную transitive/runtime роль.
- Категоризировать каждую dependency:
  - core runtime;
  - optional command/backend;
  - dev/test/build;
  - external executable;
  - platform diffusion runner;
  - transitive/redundant;
  - unused pending proof.
- Не удалять пакет до:
  - negative-evidence audit;
  - clean-environment smoke;
  - focused regression tests;
  - синхронизации packaging/docs/doctor/CI.

## B.2. Зафиксированная evidence-based классификация

- **Оставить в минимальном core:**
  - `python >=3.11,<3.14`:
    - interpreter constraint в repository policy и package metadata;
  - `numpy <2.5`:
    - базовые scientific paths и совместимость;
  - `scipy`:
    - steric diagnostics и соответствующие tests;
    - может быть вынесен только вместе с формальным переводом diagnose feature в optional extra;
  - `openmm >=8.1`:
    - preparation, minimization, topology/force-field paths;
  - `pdbfixer >=1.9`:
    - default legacy preparation backend;
  - `biopython`:
    - sequence/alignment paths;
  - `gemmi >=0.7.5`:
    - advertised mmCIF/PDBx detection/conversion на CLI boundary;
  - `pip`:
    - editable install/bootstrap flow;
  - `propka >=3.5`:
    - standalone protonation и integrated preparation variant pass.
- **Оставить в full environment, но выделить licensed modeling extra:**
  - `modeller`:
    - production-supported `model` и `homology`;
    - отдельная license setup;
    - отсутствует в обычных pip dependencies.
- **Выделить ligand/chemistry extra:**
  - `openmmforcefields`:
    - `GAFFTemplateGenerator` в ligand parameterization;
  - `openff-toolkit`:
    - direct use `Molecule` и AmberTools wrapper;
    - отсутствует в `pyproject.toml`;
  - `rdkit`:
    - glycan/heterogen hydrogen path;
    - tests уже допускают отсутствие;
  - `openbabel`/`openbabel-wheel`:
    - small-molecule CIF conversion;
    - ligand extraction;
    - heterogen hydrogen processing;
    - optional minimization utilities;
    - оставить в full environment, пока поддерживается broad-input chemistry.
- **Выделить analysis/trajectory extra:**
  - `MDAnalysis`:
    - `cluster.py`, `align.py`, trajectory/GRO workflows;
  - `plotly`:
    - optional HTML plotting;
    - код уже умеет предупреждать и пропускать plot.
- **Выделить parameterization/topology extra:**
  - `parmed`:
    - parameterization и GROMACS export;
  - `ambertools >=23`:
    - `sqm`, `antechamber`, `parmchk2`, `tleap`;
    - нужен ligand parameterization и `tleap-reduce` backend;
  - `reduce`:
    - standalone executable `reduce -build -nuclear -quiet`;
    - сохранить отдельно до platform package proof;
  - `acpype`:
    - только `top --acpype`/topology export.
- **Выделить antibody extra:**
  - `anarci`:
    - antibody numbering/CDR paths в `homology.py` и `antibody.py`;
  - `hmmer`:
    - прямой DVBFixer consumer не найден;
    - статус `unused pending proof`;
    - не удалять до проверки package metadata и isolated ANARCI runtime smoke.
- **Оставить один default MSA executable, альтернативы вынести:**
  - `mafft`:
    - `msa.py --auto` выбирает MAFFT первым;
    - docs указывают, что одного MAFFT достаточно;
  - `muscle >=5`:
    - supported explicit alternative;
    - version floor важен из-за CLI syntax;
  - `clustalo`:
    - supported explicit alternative.
- **Выделить refinement/QM extras:**
  - `xtb`:
    - только explicit `--refine xtb`;
  - `pyscf`:
    - только RESP `--qm-engine pyscf`.
- **Перенести в GUI/dev environment:**
  - `nodejs >=22`:
    - нужен GUI build/typecheck/test;
    - не нужен Python CLI runtime.
- **Хранить только в platform runner environments:**
  - PyTorch;
  - CUDA runtime/tooling;
  - MPS-compatible engine dependencies;
  - Protenix packages/patches;
  - Protpardelle packages/patches;
  - ML caches/checkpoint configuration.

## B.3. Противоречия, которые надо устранить

- `pyproject.toml` сейчас делает обязательными command-specific dependencies:
  - `MDAnalysis`;
  - `openbabel-wheel`;
  - `parmed`;
  - `acpype`;
  - `plotly`.
- `pyproject.toml` одновременно не описывает direct optional dependencies:
  - OpenFF Toolkit;
  - RDKit;
  - MODELLER;
  - ANARCI;
  - PySCF.
- Conda route использует `openbabel`, pip route — `openbabel-wheel`:
  - определить одну поддерживаемую binding route для каждого installation type;
  - не устанавливать обе реализации в одно environment без compatibility evidence;
  - добавить smoke import/feature test для выбранной route.
- `environment.yml` comment упоминает `pdb4amber`, но consumer не найден:
  - удалить/исправить комментарий;
  - не удалять AmberTools, поскольку остальные executables доказанно используются.
- `prep_backend.py` говорит, что AmberTools предоставляет Reduce, но:
  - environment отдельно устанавливает `reduce`;
  - код ищет самостоятельный executable;
  - conda package content может различаться по платформам;
  - сохранить обе записи до metadata verification на Linux и macOS.
- Три MSA engines избыточны для default install:
  - оставить MAFFT в full/default feature set;
  - MUSCLE и Clustal Omega оформить как alternatives extra/environment.
- HMMER не имеет repository-level evidence:
  - проверить выбранную ANARCI distribution metadata;
  - выполнить ANARCI smoke без HMMER и с ним;
  - только после этого принять решение remove/retain.

## B.4. Новая модель installation profiles

- Сначала определить стабильные profiles, затем менять dependencies.
- Предлагаемые profiles:
  - `core`:
    - baseline structure preparation;
    - CIF boundary support;
    - OpenMM/PDBFixer;
    - core diagnostics/protonation;
  - `full`:
    - backward-compatible conda environment со всеми production-supported non-ML features;
  - `modeling`:
    - MODELLER и license instructions;
  - `chemistry`:
    - OpenFF, openmmforcefields, RDKit, Open Babel;
  - `analysis`:
    - MDAnalysis и Plotly;
  - `parameterization`:
    - ParmEd, AmberTools, Reduce, ACPYPE;
  - `antibody`:
    - ANARCI и подтверждённые runtime requirements;
  - `msa-alternatives`:
    - MUSCLE 5 и Clustal Omega;
  - `refinement`:
    - xTB;
  - `qm`:
    - PySCF;
  - `gui-dev`:
    - Node.js/npm toolchain;
  - `diffusion-protenix-cuda`:
    - отдельный reproducible Linux runner environment;
  - `diffusion-protpardelle-mps`:
    - отдельный reproducible Apple runner environment.
- Не обязательно публиковать все extras одним релизом:
  - сначала зафиксировать matrix и user-facing feature guarantees;
  - затем мигрировать по одному coherent profile;
  - сохранять `full` как compatibility path до завершения smoke coverage.

## B.5. Изменения файлов

- `environment.yml`:
  - сохранить full/backward-compatible назначение либо переименовать/документировать его явно;
  - убрать GUI-only и alternative tools только после появления отдельных environment specs;
  - исправить misleading comments;
  - не добавлять ML dependencies.
- `pyproject.toml`:
  - оставить истинный core в `dependencies`;
  - добавить optional dependency groups там, где packages доступны через pip и поддержаны;
  - не обещать через pip packages с отдельной лицензией/conda-only route без корректных instructions;
  - согласовать naming extras с docs и `doctor`.
- Добавить отдельные environment specs/lock inputs:
  - GUI/dev;
  - Linux Protenix CUDA runner;
  - Apple Protpardelle MPS runner;
  - при необходимости conda feature profiles, если pip extras недостаточны для executables.
- `docs/installation.md`:
  - описать core/full/optional profiles;
  - указать feature-to-extra mapping;
  - дать actionable install instructions;
  - документировать MODELLER license;
  - документировать Open Babel route;
  - документировать external executable discovery.
- `docs/known-issues.md`:
  - platform/package conflicts;
  - Reduce/AmberTools differences;
  - Open Babel binding ambiguity;
  - MPS/CUDA constraints.
- `doctor.py`:
  - не объявлять optional packages общими failures;
  - проверять requirements выбранной feature/profile;
  - выдавать actionable missing-extra/missing-executable diagnostics.
- CI:
  - minimal core lane;
  - full environment lane;
  - focused optional-profile smoke lanes;
  - GUI lane;
  - diffusion runner acceptance остаётся hardware/manual/self-hosted.

## B.6. Порядок миграции dependencies

- Этап 1 — inventory freeze:
  - зафиксировать package, version constraint, consumer, install channel и category;
  - сверить `environment.yml`, `pyproject.toml`, imports, executables, docs и CI.
- Этап 2 — contract definition:
  - определить, какие команды гарантирует `core`;
  - определить, какие команды гарантирует `full`;
  - определить ошибки при отсутствии optional profile.
- Этап 3 — packaging alignment:
  - добавить optional groups/specs;
  - исправить direct/optional dependency declarations;
  - не удалять packages из `full` на этом этапе.
- Этап 4 — clean-environment proof:
  - создать чистый core environment;
  - проверить imports и advertised core commands;
  - создать каждый optional profile поверх core;
  - выполнить representative command smoke.
- Этап 5 — slim full/default при подтверждённой политике:
  - перенести Node.js в GUI/dev;
  - перенести alternative MSA engines;
  - перенести xTB/PySCF;
  - перенести analysis/parameterization/chemistry packages только если docs и feature errors готовы;
  - не удалять HMMER/Reduce до отдельных proof gates.
- Этап 6 — удалить obsolete declarations/comments:
  - только после успешных smoke lanes;
  - синхронно обновить docs, doctor и CI.

## B.7. Проверки для каждого optional profile

- `core`:
  - package import;
  - CLI startup/help;
  - PDB preparation legacy backend;
  - CIF boundary conversion;
  - protonation;
  - core diagnostics;
  - representative no-solvent minimization.
- `modeling`:
  - MODELLER import/license preflight;
  - `model` default path;
  - `homology` smoke.
- `chemistry`:
  - Open Babel import/executable path;
  - small-molecule CIF conversion;
  - OpenFF molecule creation;
  - GAFF template path;
  - RDKit heterogen/glycan H path.
- `analysis`:
  - trajectory/GRO input;
  - cluster/align;
  - Plotly present и absent behavior.
- `parameterization`:
  - discovery `antechamber`, `parmchk2`, `sqm`, `tleap`, `reduce`;
  - ParmEd import;
  - ACPYPE opt-in export;
  - `tleap-reduce` preflight.
- `antibody`:
  - ANARCI numbering/CDR smoke;
  - HMMER requirement experiment;
  - actionable failure без profile.
- `msa-alternatives`:
  - MAFFT auto/default;
  - MUSCLE 5 syntax;
  - Clustal Omega explicit selection;
  - stable missing-executable errors.
- `refinement`:
  - xTB explicit route;
  - no xTB lookup when refinement не выбран.
- `qm`:
  - PySCF RESP route;
  - no PySCF import on unrelated commands.
- `gui-dev`:
  - `npm run typecheck`;
  - `npm test -- --run`;
  - schema generation.

## B.8. Критерии удаления или переноса

- Dependency можно убрать из core/default только если:
  - нет core import/subprocess consumer;
  - optional command имеет отдельный install profile;
  - отсутствие dependency даёт раннюю actionable ошибку, а не traceback;
  - clean core smoke проходит;
  - focused feature smoke проходит после установки extra;
  - docs, doctor, CI и package metadata синхронизированы.
- Dependency нельзя удалять, если:
  - роль только кажется transitive;
  - external executable используется runtime;
  - package нужен advertised broad-input support;
  - platform distributions расходятся;
  - отсутствие покрывается лишь skipped tests;
  - нет clean-environment proof.
- Первоначальные безопасные кандидаты на перенос, но не немедленное удаление:
  - `nodejs` → GUI/dev;
  - `muscle`, `clustalo` → alternative MSA;
  - `xtb` → refinement;
  - `pyscf` → QM;
  - `plotly`, `MDAnalysis` → analysis;
  - `acpype`, `parmed` → parameterization.
- Не считать безопасными кандидатами на удаление без дополнительной проверки:
  - `hmmer`;
  - standalone `reduce`;
  - `openbabel`;
  - `ambertools`;
  - `modeller`;
  - `rdkit` при сохранении текущей broad chemistry behavior.

## B.9. Проверки репозитория после ревизии

- Запустить focused tests каждой dependency-группы.
- Запустить обязательные общие checks:
  - `pytest -m 'not slow' -q`;
  - `ruff check src/dvbfixer`;
  - `mypy src/dvbfixer/cli.py src/dvbfixer/ffutils src/dvbfixer/pdbutils src/dvbfixer/align.py`;
  - `python scripts/check_agent_docs.py`;
  - `python scripts/gen_cli_reference.py --check`;
  - `python scripts/gen_gui_spec.py --check`;
  - `git diff --check`.
- Для GUI/environment changes:
  - `npm run typecheck`;
  - `npm test -- --run`.
- Проверить установки минимум двумя независимыми путями:
  - clean core pip/venv route, если она заявлена;
  - full conda/micromamba route.
- На macOS Docker/VirtioFS не размещать micromamba root на host bind mount; использовать native container overlay согласно repository instructions.

## B.10. Результаты ревизии

- Подготовить отдельный dependency audit artifact в документации с полями:
  - dependency;
  - version/channel;
  - category;
  - concrete consumers;
  - profile;
  - keep/move/remove decision;
  - uncertainty;
  - verification command.
- Обновить installation matrix и `doctor` output.
- Не смешивать environment cleanup с diffusion scientific claims.
- Не удалять пакеты только ради уменьшения YAML.
- Итогом первого change set должны быть:
  - согласованная dependency model;
  - optional profiles/specs;
  - исправленные contradictions;
  - clean-environment evidence;
  - только затем фактическое slimming.

## B.11. Stop/go критерии

- **STOP:** dependency считается unused только по отсутствию import.
- **STOP:** pip и conda после изменения обещают разные возможности без документации.
- **STOP:** optional command падает поздним `ImportError`/`FileNotFoundError` вместо preflight diagnostic.
- **STOP:** удаление ломает advertised PDB/PDBx, preparation, MODELLER или chemistry coverage.
- **STOP:** HMMER/Reduce/Open Babel удаляются без platform/runtime proof.
- **STOP:** diffusion ML stack попадает в core environment.
- **GO:** dependency перемещена только после profile definition, clean install и focused smoke.
- **GO:** удаление означает отсутствие доказанного consumer и успешно подтверждённую работу всех заявленных profiles.
