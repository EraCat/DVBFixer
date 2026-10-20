# План A. Слияние веток и внедрение diffusion backend в CLI

## Текущий статус на 2026-10-20

Публичные opt-in CLI, runtime discovery/Doctor, batch/resume, ZBS handoff,
mosaic-first Homology и GUI routing уже реализованы. Проверенный workflow-срез
описан в [integration evidence](../research/diffusion-workflow-integration.md).
Corrected cc89 CUDA и новый `protpardelle-1c-mps-local-v1` имеют по 5/5 публичных
model/Homology кандидатов; Apple 8/8 research pilot и frozen replay описаны в
[Apple acceptance](../research/cc89-public-apple-acceptance.md). Legacy MPS identity
сохранён отдельно. Protenix profile lock и публичные GPU smokes существуют;
полный 231-case production-wrapper replay и final OCI image/GPU smoke остаются
отдельными gates. MODELLER остаётся default, расширение научной области не заявляется.

Ниже сохранён исторический этап интеграции; его старые ограничения — не текущий
перечень отсутствующего кода. Сводный статус: [индекс планов](README.md).

## Исторический статус интеграции на 2026-10-02

На ветке `feature/dvbfixer-hardening` выполнен предварительный этап:

- актуальный `main` объединён merge-коммитом `7d40ef6`;
- `origin/diffusion` объединён merge-коммитом `0762cfc`;
- diffusion-only Ramachandran и chi1/chi2 hard gates изолированы от общего
  `diagnose` в `dvbfixer.model.diffusion.quality` (`b3f3a9e`);
- `origin/diffusion-apple-silicon` объединён merge-коммитом `e84d07e`;
- MODELLER остаётся default и production-supported backend команды `model`;
  явный experimental `--backend diffusion` и отдельные production protocol
  wrappers для Protenix CUDA и Protpardelle MPS реализованы.

Аппаратно-независимая интеграция прошла полный Python 3.11 non-slow suite и GUI
suite перед последующими runner/CLI commits. Публичный Apple CLI smoke затем
прошёл на native M3 Pro с отключённым fallback, final restoration и CPU OpenMM
refinement. Portable Linux wrapper реализован, но его checkpoint-backed
NVIDIA acceptance и воспроизведение frozen scope ещё обязательны.

Архитектурное решение о narrow public CLI зафиксировано в ADR 0011. Bounded
digest-verified sampler trace связан с каждым candidate и bundle по contract/
protocol v4; additive diffusion profile report и bounded no-inference handshake
реализованы в `doctor`. Ни один из
этих статусов не означает production-default promotion, arbitrary chemistry,
batch/GUI/ZBS/Homology support или доказанную training independence Apple
engine.

## A.1. Зафиксированные границы и продуктовые решения

- Сохранить MODELLER:
  - production-supported backend;
  - backend по умолчанию для `dvbfixer model`;
  - текущий file-output контракт;
  - существующее поведение `homology`, `zbs`, batch и GUI до отдельного расширения.
- Добавить diffusion только как явный opt-in:
  - публичная точка входа: `dvbfixer model --backend diffusion`;
  - автоматический fallback на MODELLER запрещён;
  - автоматическое переключение Linux/Apple runner profiles запрещено;
  - unsupported input, preflight failure, runner failure и validation failure завершаются ошибкой без частичного output.
- Поддержать два явно выбираемых профиля:
  - `protenix-v1-cuda`:
    - Linux/NVIDIA CUDA;
    - experimental public profile;
    - confirmatory-selected только в проверенном узком scope;
    - per-step fixed-coordinate reinjection;
    - localized OpenMM boundary refinement;
  - `protpardelle-1c-mps`:
    - Apple Silicon/MPS;
    - experimental/descriptive profile;
    - unresolved training-data membership;
    - frozen evidence не использовало per-step reinjection;
    - template conditioning, финальное восстановление fixed coordinates и независимая validation;
    - OpenMM boundary refinement выполняется на CPU.
- Не называть Apple profile эквивалентом constrained Protenix sampler.
- Не добавлять diffusion options в `homology` и `zbs`.
- Не включать PyTorch, CUDA/MPS stacks, engine packages и checkpoints в core environment.
- Не скачивать checkpoints автоматически из core CLI.
- Не распространять checkpoints без отдельной проверки лицензии.
- Сохранить научные invariants:
  - residue identity: `(chain, resid, icode)`;
  - atom identity: `(chain, resid, icode, atom)`;
  - chain IDs case-sensitive;
  - insertion codes сохраняются;
  - generated residues содержат полный canonical heavy-atom set;
  - fixed heavy coordinates проверяются независимо от runner;
  - после последнего изменения heavy coordinates выполняется `assert_all_l`;
  - `.dat` создаётся только через `dvbfixer.ffutils.dat.DatRecord`;
  - CIF нормализуется только на внешней CLI boundary;
  - ни один `PDBFile.writeFile` не теряет `keepIds=True`.

## A.2. Организация интеграционной ветки

- Перед изменениями:
  - получить актуальные remote refs;
  - сохранить снимок `git status`;
  - не изменять и не включать в коммиты пользовательские untracked paths:
    - `.artifacts/`;
    - `.claude/` внутри checkout;
    - `FF/amber19sb.ff/`;
    - существующие untracked `docs/plans/*.md`;
    - `opencode.json`;
  - проверить, что имя `feature/diffusion-cli-integration` свободно.
- Создать `feature/diffusion-cli-integration` непосредственно от актуального `main`.
- Не основывать интеграцию на текущей `feature/dvbfixer-hardening` или иной локальной feature-ветке.
- Назначить одного координирующего владельца каждой exclusive-owner change group:
  - `missing-atom-rebuild-chirality`;
  - `public-command-surface`.
- Вести изменения отдельными логическими change groups:
  - merge `origin/diffusion`;
  - merge `origin/diffusion-apple-silicon`;
  - ADR/DDD reconciliation;
  - runner contract;
  - Linux production runner;
  - Apple production runner;
  - CLI orchestration;
  - output/publication contract;
  - doctor/docs/generated schemas;
  - tests/acceptance.
- Не делать commit, push, PR или release без отдельного запроса пользователя.

## A.3. Последовательное слияние веток

- Выполнить merge `origin/diffusion` в новую ветку.
- Не заменять конфликтующие файлы целиком.
- Для конфликтов сохранять более новые изменения `main`, не связанные с diffusion:
  - Amber19SB support и packaging;
  - diagnose geometry/chemistry/report hardening;
  - nonprotein reconstruction;
  - удаление mutation cluster;
  - batch artifact containment;
  - актуальную package version и metadata;
  - последующие CI/test fixes.
- Перенести additions из diffusion-ветки:
  - backend-neutral contracts;
  - masks/scope admission;
  - runner isolation;
  - validation;
  - provenance;
  - atomic bundle publication;
  - tests и research evidence.
- Особо разрешить конфликты в:
  - `.gitattributes`;
  - `AGENTS.md`;
  - `docs/agent/tasks.toml`;
  - `docs/agent/contracts.toml`;
  - `docs/agent/invariants.toml`;
  - context records;
  - `docs/installation.md`;
  - diagnose modules и tests.
- В DDD и policy docs:
  - сохранить актуальные правила `main`;
  - добавить diffusion records;
  - не повышать proposed/partial status раньше реальной реализации;
  - сообщить о любом противоречии code/tests/ADR/DDD вместо молчаливого выбора.
- После первого merge выполнить:
  - focused checks из `implement-diffusion-gap-reconstruction`;
  - focused checks затронутых main features;
  - `python scripts/check_agent_docs.py`;
  - `git diff --check`.
- Выполнить merge `origin/diffusion-apple-silicon` после стабилизации первого merge.
- Учитывать, что Apple branch является потомком diffusion branch; не переносить её как независимый набор cherry-picks.
- Сохранить Apple additions:
  - explicit CPU/CUDA/MPS device resolution;
  - fail-closed MPS checks;
  - `PYTORCH_ENABLE_MPS_FALLBACK=0`;
  - model/tensor/output device assertions;
  - synchronized timing;
  - MPS/RSS telemetry;
  - final synchronization/restoration fixed atoms;
  - Apple cohort evidence.
- Не объединять frozen Apple baseline с несовместимым callback patch.
- После второго merge повторить focused DDD checks, `check_agent_docs` и `git diff --check`.
- Сохранить два merge-коммита как provenance истории; не squash/cherry-pick исследовательские ветки без необходимости.

## A.4. Архитектурное решение до публичного CLI

- Добавить successor ADR к ADR 0010 или формально обновить ADR 0010 согласно правилам репозитория.
- Зафиксировать в ADR:
  - MODELLER остаётся default;
  - diffusion является opt-in experimental;
  - два profiles и их различающиеся capability/evidence levels;
  - отсутствие автоматического fallback;
  - поддерживаемый scientific scope;
  - Linux per-step reinjection semantics;
  - Apple final-restoration semantics без ложного per-step claim;
  - independent validation как authoritative gate;
  - directory bundle как atomic diffusion artifact;
  - training-data leakage status каждого engine;
  - separation core CLI и ML runner environments;
  - отсутствие automatic downloads;
  - условия будущего расширения scope, batch и GUI.
- Синхронизировать:
  - `docs/agent/tasks.toml`;
  - `docs/agent/contracts.toml`;
  - `docs/agent/invariants.toml`;
  - `docs/agent/contexts/structure-preparation.md`;
  - `ARCHITECTURE.md`;
  - `docs/domain-model.md`;
  - installation/known-issues docs.
- Обновлять status vocabulary только по фактически реализованным возможностям.
- Не описывать roadmap/research results как shipped behavior.

## A.5. Versioned runner contract и sampler evidence

Статус: реализовано contract/protocol v4. Старые trace-free manifests
отклоняются, trace независимо проверяется как bounded private artifact и
публикуется вместе с каждым candidate.

- Не использовать research `summary.json` как production protocol result.
- Production runner обязан:
  - читать versioned `request.json`;
  - писать обязательный `<workspace>/result.json`;
  - использовать текущую поддерживаемую protocol/schema version;
  - ссылаться только на contained regular files;
  - публиковать SHA-256 каждого artifact;
  - не создавать symlink/hardlink escape;
  - не писать вне private workspace.
- Operator-supplied runner является trusted executable code. Проверки core
  ограничивают и валидируют возвращённые artifacts, но не являются OS/filesystem
  sandbox и не могут запретить процессу записи в другие пути. Обязательство не
  писать вне workspace относится к maintained wrappers; для enforcement нужен
  внешний sandbox/container.
- Исправить gap существующего contract:
  - `SamplerTrace` уже определён, но не связан с `RunnerCandidate`/`RunnerResult`;
  - поднять schema/protocol version;
  - добавить sampler trace к каждому candidate как typed contract field или отдельный digest-verified artifact;
  - предпочесть отдельный bounded JSON artifact, чтобы trace не раздувал `result.json`.
- В trace записывать:
  - profile и sampler capability;
  - engine/source revision;
  - patch identity;
  - sampler atom order и его digest;
  - полный request fixed set, представленный sampler subset и fixed-mask digest
    именно для represented subset;
  - marker полноты sampler evidence и отдельные denoising-update/observed
    callback counts; unknown legacy evidence не кодировать нулевыми counts;
  - explicit fixed-coordinate tolerance policy (по умолчанию `0.01 Å`);
  - maximum observed post-projection/reinjection error, либо `null`, если
    projection callback не выполнялся;
  - final restoration marker;
  - refinement mode и параметры;
  - device identity;
  - fallback-disabled status;
  - bounded resource metrics.
- Для Linux требовать evidence per-step reinjection.
- Для Apple требовать честные 500 denoising updates, нулевой per-step callback
  count и final-restoration marker.
- Обновить:
  - strict serialization/parsing;
  - compatibility errors;
  - runner boundary checks;
  - provenance schema;
  - fake-runner fixtures/tests.
- Старые protocol versions отклонять stable preflight error, если отсутствует безопасная и явно протестированная compatibility path.

## A.6. Production runner для Linux/Protenix

- Не выставлять research smoke script напрямую как public runner.
- Создать protocol-compliant wrapper/executable, переиспользующий проверенную scientific логику:
  - Protenix inference;
  - per-step reinjection;
  - candidate generation;
  - localized OpenMM boundary refinement;
  - result manifest generation.
- Зафиксировать profile identity:
  - Protenix source revision;
  - patch digest;
  - environment/container identity;
  - checkpoint identity и expected SHA-256;
  - CUDA/PyTorch compatibility;
  - supported devices/dtypes;
  - sampler mode.
- Preflight должен проверять до inference:
  - runner executable;
  - protocol version;
  - image/environment identity при использовании container runner;
  - checkpoint presence/digest;
  - CUDA availability;
  - compatible GPU/device;
  - writable contained workspace;
  - required resource limits.
- Runner запускать:
  - без shell;
  - в новой process session;
  - с allowlisted environment;
  - с private `HOME`, `TMPDIR`, `XDG_CACHE_HOME`;
  - с timeout;
  - с bounded stdout/stderr/artifacts.
- Core validator после runner независимо проверяет:
  - exact identities;
  - generated atom completeness;
  - fixed-coordinate RMSD/max displacement;
  - peptide junction distances;
  - backbone breaks;
  - severe clashes;
  - connectivity;
  - final L-chirality.
- Публичный Linux profile не включать, пока production wrapper не воспроизведёт frozen confirmatory evidence в заявленном scope.

## A.7. Production runner для Apple Silicon/Protpardelle

- Создать отдельный protocol-compliant MPS wrapper, не маскируя его под Linux runner.
- Зафиксировать проверенный baseline:
  - Protpardelle-1c;
  - PyTorch 2.6.0;
  - float32 MPS;
  - `PYTORCH_ENABLE_MPS_FALLBACK=0`;
  - explicit MPS availability checks;
  - model/tensor/output device assertions;
  - synchronized timing;
  - MPS/RSS telemetry;
  - CPU OpenMM boundary refinement.
- Не применять per-step callback patch в frozen public Apple profile.
- Не заявлять constrained denoising/per-step reinjection.
- После sampling:
  - синхронизировать MPS;
  - выполнить documented final fixed-coordinate restoration;
  - записать это в sampler trace;
  - передать candidate независимому core validator.
- Завершать ошибкой при:
  - отсутствии MPS;
  - unsupported MPS operation;
  - silent CPU fallback;
  - tensor/model/output device mismatch;
  - checkpoint mismatch;
  - incompatible protocol;
  - validation failure.
- Расширить `AdapterPreflightCode` MPS-specific stable reason codes.
- Публичный Apple profile не включать, пока production wrapper не воспроизведёт descriptive cohort на подходящем Apple Silicon host.
- Training membership оставлять `unknown/unresolved`; Apple evidence не использовать для confirmatory engine selection claims.

## A.8. Backend-neutral orchestration команды `model`

- Не размазывать `if args.backend` по существующему MODELLER pipeline.
- Выделить backend-neutral orchestration boundary:
  - parse/validate options;
  - normalize input at CLI boundary;
  - common structure/sequence inspection;
  - backend-specific request construction/execution;
  - backend-specific output publication.
- Сохранить существующий MODELLER path и его порядок scientific stages.
- В `src/dvbfixer/model/cli.py` добавить:
  - `--backend {modeller,diffusion}`;
  - default `modeller`;
  - отдельную `Diffusion options` argparse group;
  - optional `--diffusion-model {protpardelle,protenix}`;
  - automatic host-compatible profile selection from installed private launchers;
  - runner, checkpoint path, and checkpoint digest remain backend-installation details and are not public model options;
  - candidate count;
  - seeds;
  - timeout;
  - work-parent;
  - bounded resource overrides только в безопасных пределах.
- Не добавлять `--device`: model/profile selection is hardware-aware and never falls back to another backend.
- До preprocessing/runner invocation:
  - отклонять MODELLER-only flags с `--backend diffusion`;
  - отклонять diffusion-only flags с `--backend modeller`;
  - resolve exactly one compatible installed profile, using `--diffusion-model` only when requested or needed to disambiguate;
  - проверять output semantics;
  - проверять batch/GUI restrictions.
- Production request builder должен:
  - использовать shared sequence placement;
  - использовать существующие masks/scope checks;
  - использовать authoritative residue-number allocator;
  - сохранять chain case и insertion codes;
  - строить exact fixed/generated atom identities;
  - включать retained explicit links только по поддерживаемой policy;
  - не дублировать force-field variant, ligand-valence, GLYCAM или CONECT policy.
- Выполнять scope admission до external process.
- Начальный scope:
  - один canonical protein target chain;
  - один внутренний two-anchor gap;
  - gap length 3–12 residues;
  - exact sequence placement;
  - отсутствие terminal gaps;
  - отсутствие adjacent altloc ambiguity;
  - отсутствие multiple MODEL;
  - отсутствие retained heterogens/noncanonical chemistry;
  - explicit `--strip-heterogens` is applied before request construction and
    scope admission without mutating the source input;
  - отсутствие unsupported covalent links;
  - входная структура проходит chirality admission.
- Unsupported scope возвращает stable reason list и не запускает runner.

### A.8.1. План поддержки генерации N/C-концов

**Implemented for the accepted Protpardelle profile (2026-10-06).** The request
contract now records `gap_kind = internal | n_terminal | c_terminal` and uses
`null` rather than a fabricated identity for the absent terminal anchor. The CLI
allocates deterministic PDB-representable terminal residue identities; the
materializer, validator, localized refinement, provenance, and scope admission
handle one-anchor regions. Protpardelle samples terminal residues as part of the
full target axis; a 500-step MPS smoke with simultaneous N-tail, internal gap,
and C-tail passed all independent gates. Profiles without accepted one-anchor
evidence remain fail closed. Broader frozen CUDA/MPS cohort acceptance remains a
promotion task.

`--no-terminal` уже является общим для MODELLER и diffusion режимом: target
обрезается снаружи первого/последнего наблюдаемого anchor, после чего
реконструируются только внутренние gaps. Полноценная terminal generation остаётся
отдельным acceptance stratum и не должна включаться снятием одной проверки.

- [x] Расширить versioned request contract так, чтобы terminal gap имел ровно один
  anchor: правый для N-конца или левый для C-конца. Не кодировать отсутствующий
  anchor фиктивным residue identity.
- [x] Добавить явный `gap_kind = internal | n_terminal | c_terminal`; внутренний gap
  сохраняет два anchor и текущие validation gates.
- [x] Расширить authoritative residue allocator для terminal generated identities:
  сохранять case-sensitive chain ID и insertion codes, детерминированно выделять
  номера до первого или после последнего наблюдаемого residue и fail closed при
  невозможности представить их в PDB.
- [x] На backend adapter уровне проверить one-anchor motif grammar для
  Protpardelle. Для каждого принятого profile зафиксировать доказательство, что
  terminal residues действительно входят в denoising state, а не дописываются
  post-hoc.
- [x] Materializer должен вставлять N-terminal atoms перед первым coordinate record
  соответствующей цепи, а C-terminal atoms перед её `TER`, сохраняя headers,
  ANISOU, explicit connectivity и все нетронутые atom serial identities.
- [x] Validator должен применять один peptide-junction gate вместо двух, проверять
  полный canonical heavy-atom set, bond lengths/angles, amide planarity,
  Ramachandran/chirality, clashes и отсутствие движения fixed atoms. Нельзя
  объявлять terminal pass только по наличию координат.
- [x] Refinement должен двигать terminal generated residues и единственный anchor
  flank, не ослабляя exact-fixed policy для остальных атомов.
- [ ] Расширить frozen fixtures beyond the implemented N-only, C-only and
  simultaneous N+C unit/MPS smoke cases: добавить несколько цепей,
  короткие/длинные tails, tight numbering, insertion codes и case-sensitive
  chain IDs. Отдельно проверить сочетание terminal и internal gaps.
- [ ] Провести frozen hardware acceptance отдельно от internal-gap cohort для MPS и
  CUDA. До прохождения gates default остаётся fail closed с подсказкой
  `--no-terminal`; никакого silent fallback на MODELLER.
- [x] Обновить scope/help/docs и provenance так, чтобы terminal
  generation была явно отличима от `--no-terminal` cropping.

### A.8.2. Локальное межцепочечное conditioning

**Implemented for Protpardelle protein partners (2026-10-06).** Каждый
gap-bearing target по-прежнему получает отдельный sampler invocation, но adapter
детерминированно выбирает contiguous crops других canonical protein chains,
heavy atoms которых находятся в пределах 12 Å от gap anchor. Crop расширяется
на два sequence neighbours, ограничивается непрерывным observed run и общим
cc89 axis budget 512 residues.

- Partner crop передаётся в `make_seq_mask_for_sampling` отдельной chain, входит
  в motif PDB и fixed motif placement; это реальный input denoiser, а не
  post-hoc clash check.
- Candidate materialization публикует только generated target coordinates;
  partner atoms восстанавливаются из source без изменений.
- `SamplerTrace.conditioning_contexts` хранит точные target/partner chain IDs и
  partner atom identities. Contract проверяет, что они присутствуют среди
  represented fixed atoms sampler axis.
- Несколько gap-bearing chains всё ещё sampling-independent. Distant,
  discontinuous, omitted и over-budget partner regions не участвуют; нельзя
  описывать режим как whole-complex joint conditioning.
- Короткий checkpoint-backed two-chain smoke подтвердил multi-chain motif grammar
  и наличие partner atoms в sampler trace. Для production promotion остаются
  frozen interface cohort и causal partner-on/off ablation.

## A.9. Output и atomic publication

- Сохранить MODELLER contract:
  - `dvbfixer model input -o result.pdb` создаёт file output;
  - существующий batch suffix `_model.pdb` не меняется.
- Для diffusion определить `-o` как новый несуществующий **directory bundle**.
- Bundle содержит:
  - selected candidate PDB;
  - corresponding `.dat`;
  - separate diffusion provenance JSON;
  - sampler trace artifact;
  - `bundle.json` с artifact digests/schema/profile identity.
- Публиковать accepted либо явно маркированный validation-failed bundle только:
  - через hidden same-parent staging directory;
  - после полного validation и manifest generation;
  - одной no-replace directory rename;
  - с Linux `renameat2(RENAME_NOREPLACE)` и macOS `renamex_np(RENAME_EXCL)` paths.
- Не публиковать loose PDB вторым действием после bundle rename.
- Не перезаписывать существующую destination.
- Scientific hard-gate failure после корректного sampling/materialization
  публикует `validation_failed` bundle с candidate PDB, полным списком gates и
  warning; он не считается success и не объявляется simulation-ready. Пользователь
  может выбрать другой seed или отдельно выполнить full-system minimization.
- Runner/protocol/digest/containment/materialization errors очищают private
  staging/workspace согласно policy и не оставляют partial public output.
- Сохранить `.dat` engine-neutral; runner metadata находится только в provenance/trace.

## A.10. Batch, command registry и GUI

- Учесть конфликт текущей модели:
  - `command_registry.py` задаёт один статический `batch_output_suffix`/file mode;
  - batch всегда передаёт file destination;
  - GUI schema имеет один static `outputMode` на command;
  - diffusion требует directory bundle.
- На первом public CLI этапе:
  - single-input CLI поддерживает diffusion;
  - generic `--batch` с diffusion отклоняется до обработки inputs с actionable error;
  - GUI не предлагает diffusion backend;
  - generator явно исключает unsupported backend option из GUI exposure либо описывает capability gate;
  - MODELLER batch/GUI остаются без изменений.
- Не позволять `gen_gui_spec.py` автоматически выставить неработающую diffusion option.
- Реализовано для первого этапа: generic directory batch отклоняет diffusion до
  создания output, а generated GUI schema не содержит `--backend` или
  `--diffusion-*` для `model`; MODELLER batch/GUI contract не изменён.
- Отдельным последующим change group, не смешанным с initial CLI promotion:
  - расширить command metadata для backend-dependent output mode;
  - определить batch directories `<stem>_model_diffusion/`;
  - обеспечить containment и collision handling;
  - научить GUI managed runner принимать directory output и архивировать/показывать bundle;
  - добавить frontend/backend schema tests.

## A.11. `doctor`, diagnostics и provenance

Статус: реализовано. Без выбора profile `doctor` сообщает только immutable
metadata обоих profiles. При явном выборе он запускает maintained runner с
`--preflight` без shell, sampling, refinement или загрузки checkpoint weights,
ограничивает время/вывод и строго разбирает sanitized JSON report. Пути,
credentials, raw environment и raw child logs в report не попадают.
Публичный diffusion model path выполняет тот же fail-closed handshake до
построения request и inference; отдельный запуск `doctor` не является условием
безопасности. Source identity отклоняет изменения tracked files вне frozen patch
и untracked Python modules. Published provenance сохраняет immutable status,
evidence и training-membership labels выбранного profile.

- [x] Добавить additive `diffusion` section в `src/dvbfixer/doctor.py`.
- [x] Обновить exact-key assertions в `tests/test_doctor.py`.
- [x] Поддержать проверку выбранной модели и автоматически разрешённого profile:
  - installed private launcher presence;
  - runner protocol/schema;
  - engine/source revision;
  - patch identity;
  - environment/container identity;
  - launcher-owned checkpoint identity and digest;
  - CUDA либо MPS availability;
  - effective device;
  - fallback-disabled status;
  - refinement platform;
  - resource prerequisites.
- [x] Выводить status labels:
  - Linux: `experimental`, `confirmatory-selected-in-frozen-scope`;
  - Apple: `experimental`, `descriptive-evidence`, `training-membership-unresolved`, `no-per-step-reinjection`.
- [x] Provenance сохраняет:
  - DVBFixer version/commit;
  - request digest;
  - input/output artifact digests;
  - profile/runner identity;
  - backend provenance;
  - diagnostics/resource metrics;
  - evidence/capability label.
- Не сохранять:
  - credentials;
  - credential-bearing URLs;
  - raw environment;
  - checkpoint content;
  - private host paths без необходимости;
  - raw stdout/stderr; сохранять только bounded byte counts/digests при необходимости.

## A.12. Документация и generated artifacts

- Обновить user documentation:
  - CLI examples для automatic selection и optional model choice;
  - installation разделы Linux CUDA и Apple MPS;
  - checkpoint provisioning без automatic download;
  - supported scope/rejection reasons;
  - output bundle layout;
  - no-fallback policy;
  - evidence and leakage limitations;
  - known issues/resource requirements.
- Явно указать:
  - MODELLER не deprecated;
  - diffusion не default;
  - Linux evidence не доказывает произвольную chemistry support;
  - Apple evidence descriptive, а не confirmatory;
  - checkpoints не входят в DVBFixer.
- После argparse/registry changes:
  - выполнить `python scripts/gen_cli_reference.py`;
  - выполнить `python scripts/gen_gui_spec.py`;
  - не редактировать `docs/reference/*.md` вручную;
  - проверить оба generator `--check` режима.

## A.13. Тестирование

- Contract tests:
  - request/result/trace round trips;
  - strict unknown/missing fields;
  - protocol mismatch;
  - stale research protocol rejection;
  - artifact digest validation.
- Fake-runner tests:
  - success;
  - nonzero exit;
  - timeout/process-group termination;
  - missing/malformed `result.json`;
  - path traversal;
  - symlink/hardlink/non-regular files;
  - digest mismatch;
  - oversized stdout/stderr/artifacts;
  - environment allowlist;
  - no partial publication.
- Request/scope tests:
  - case-sensitive chain IDs;
  - insertion codes;
  - exact identities;
  - gap length 3/12 boundaries;
  - terminal/multiple/ambiguous gaps;
  - alternate locations;
  - heterogens/noncanonical residues;
  - unsupported links;
  - input chirality.
- Portable Phase 4 additions also cover tight deposited numbering through
  insertion-code allocation, fixed-record/header/ANISOU preservation, runner
  protocol-version enforcement, non-success outcomes without refinement, bounded
  nonzero-exit diagnostics, and private-workspace cleanup after runner failure.
- Validator tests:
  - missing/extra atoms;
  - identity mismatch;
  - fixed RMSD/displacement thresholds;
  - peptide junction limits;
  - backbone breaks;
  - severe clashes;
  - connectivity;
  - final `assert_all_l`.
- Publication tests:
  - Linux no-replace path;
  - macOS no-replace path;
  - destination exists;
  - before-commit failure;
  - manifest completeness;
  - directory atomicity.
- CLI tests:
  - MODELLER remains default;
  - existing MODELLER invocations unchanged;
  - automatic compatible-profile selection and optional explicit model choice;
  - incompatible option rejection before runner;
  - no fallback;
  - unsupported input no runner invocation;
  - file versus directory output semantics;
  - batch rejection;
  - GUI schema exclusion.
- Doctor/provenance tests:
  - stable reason codes;
  - MPS/CUDA capability cases;
  - redaction;
  - capability/evidence labels;
  - raw logs absent.

## A.14. Hardware acceptance

- Не делать GPU обязательным для core pull-request CI.
- Linux self-hosted/manual lane:
  - pinned NVIDIA/CUDA runner environment;
  - production protocol wrapper smoke;
  - checkpoint digest check;
  - fallback/device assertions;
  - повтор frozen 231-case cohort;
  - сравнение hard-gate pass rate и selected geometry metrics с confirmatory baseline;
  - archive bounded manifests/evidence, но не checkpoint.
- Apple arm64 self-hosted/manual lane:
  - подходящий M3 Pro-class host или документированный эквивалент;
  - fallback disabled;
  - production protocol wrapper smoke;
  - MPS device assertions;
  - повтор 231-case cohort;
  - сравнение terminal outcomes, selected pass rates и geometry metrics с descriptive baseline;
  - подтверждение CPU-only OpenMM refinement;
  - любой silent CPU sampling считается failure.

## A.15. Обязательные repository checks

- После каждого logical change group запускать focused checks из актуальной DDD task record.
- Перед готовностью ветки запустить:
  - `pytest -m 'not slow' -q`;
  - `ruff check src/dvbfixer`;
  - `mypy src/dvbfixer/cli.py src/dvbfixer/ffutils src/dvbfixer/pdbutils src/dvbfixer/align.py` и новые typed diffusion entrypoints;
  - `python scripts/check_agent_docs.py`;
  - `python scripts/gen_cli_reference.py --check`;
  - `python scripts/gen_gui_spec.py --check`;
  - `git diff --check`;
  - из `gui/`: `npm run typecheck` и `npm test -- --run`, если затронуты registry/schema/server.
- Для development `minimize`/`zbs` iterations использовать `--no-solvent` и при отсутствии проверки heterogens — `--strip-heterogens`.

## A.16. Stop/go критерии

- **STOP:** merge теряет или меняет более новое unrelated поведение `main`.
- **STOP:** DDD/ADR/code/tests противоречат друг другу и противоречие не разрешено явно.
- **STOP Linux:** production runner не выдаёт protocol-compliant `result.json`/trace, не доказывает per-step reinjection или не воспроизводит confirmatory baseline.
- **STOP Apple:** sampler silently falls back на CPU, trace приписывает per-step reinjection или production wrapper не воспроизводит descriptive baseline.
- **STOP CLI:** MODELLER default/file output меняется либо diffusion bundle нельзя опубликовать атомарно.
- **STOP security:** credentials/private URLs/unsafe paths попадают в logs, manifest или provenance.
- **GO:** только opt-in experimental public CLI в заявленном scope.
- **GO не означает:** production-default promotion, MODELLER deprecation, arbitrary chemistry support, checkpoint redistribution, batch/GUI support или доказанную training independence Apple engine.
