# Third Codex task: H4 reaction engine, outcome analytics та controlled batch scanning

Продовж роботу над поточною реалізацією після завершення:

- `codex_second_task_prompt_uk.md`;
- `codex_structure_setup_fix_task_uk.md`;
- `codex_liquidity_context_dedup_task_uk.md`.

Поточний D1 pipeline вважається базовим контрактом. Не спрощуй і не переписуй його без необхідності.

Перед змінами:

1. Прочитай `htf_setup_scanner_implementation_plan.md`.
2. Переглянь поточні domain models, state machines, detectors, persistence, reports, CLI та tests.
3. Запусти повний набір quality checks.
4. Зафіксуй baseline:
   - кількість тестів;
   - coverage;
   - Ruff;
   - strict mypy;
   - hashes deterministic replay;
   - JTOUSDT D1 regression result.
5. Після реалізації переконайся, що існуючий D1 результат JTO не змінився.

## Мета ітерації

Реалізувати наступний causal pipeline:

```text
D1 HTF setup ACTIVE
        ↓
H4 FVG interaction
        ↓
H4 early reaction
        ↓
H4 reaction confirmation
        ↓
reaction outcome analytics
        ↓
controlled multi-symbol offline scan
```

Ця ітерація не повинна створювати LTF entry signal або торговий backtest. Її задача — визначити, чи відреагувала H4-структура на активну D1 зону, наскільки якісною була ця реакція і що відбулося після неї.

---

# 1. Базові causal правила multi-timeframe replay

## 1.1. Заборона використання незакритих свічок

Усі рішення приймаються лише після закриття відповідної свічки.

Для D1 setup:

```text
setup.known_at
```

є найранішим моментом, з якого H4 engine може використовувати setup.

H4-свічки з `close_time <= setup.known_at` не можуть створювати reaction events.

## 1.2. Timeframe alignment

Реалізуй явне вирівнювання D1 і H4:

- timestamps зберігаються в UTC;
- H4 candle повинна мати deterministic `open_time` і `close_time`;
- не роби припущення, що біржові D1/H4 межі збігаються з локальним timezone;
- перевір пропущені, дубльовані та неупорядковані candles;
- H4 data починає аналізуватися лише після `setup.known_at`.

## 1.3. Replay modes

Підтримай:

- batch replay;
- candle-by-candle incremental replay.

Результати обох режимів мають бути ідентичними за:

- reaction events;
- reaction state transitions;
- scores;
- outcomes;
- timestamps;
- canonical IDs.

---

# 2. Domain model H4 reaction

Додай окрему domain-модель `H4Reaction`.

Мінімальні поля:

- `id`;
- `setup_id`;
- `symbol`;
- `side`;
- `status`;
- `zone_id` або `fvg_id`;
- `touch_type`;
- `touch_open_time`;
- `touch_close_time`;
- `formed_at`;
- `known_at`;
- `confirmed_at`;
- `invalidated_at`;
- `expired_at`;
- `entry_price_reference`;
- `reaction_extreme_price`;
- `reaction_score`;
- `score_components`;
- `invalidation_reason`;
- `config_hash`;
- `created_at`;
- `updated_at`.

## 2.1. H4 reaction states

Реалізуй централізовану state machine:

```text
WAITING_FOR_TOUCH
→ ZONE_TOUCHED
→ EARLY_REACTION
→ REACTION_CONFIRMED
→ INVALIDATED
→ EXPIRED
```

Дозволені переходи мають бути централізовані та валідовані.

### `WAITING_FOR_TOUCH`

D1 setup активний, але жодна H4-свічка ще не взаємодіяла із зоною.

### `ZONE_TOUCHED`

H4 candle вперше торкнулася D1 FVG або увійшла в нього.

### `EARLY_REACTION`

Після touch є мінімальна evidence реакції, але ще немає достатнього structural confirmation.

### `REACTION_CONFIRMED`

Є qualified rejection/displacement і H4 structure confirmation у напрямку D1 setup.

### `INVALIDATED`

Реакція або D1 setup втратили валідність.

### `EXPIRED`

Перевищений configurable reaction age без confirmation.

Не створюй окрему незалежну reaction для кожної H4-свічки. Один D1 setup повинен мати одну canonical H4 reaction sequence, якщо інше не передбачено явно.

---

# 3. Формалізувати H4 zone interaction

Для bearish D1 setup із bearish FVG `[lower, upper]` визнач:

- first touch;
- partial penetration;
- midpoint penetration;
- deep penetration;
- full fill;
- close inside;
- close back below;
- close above invalidation boundary.

Bullish логіка симетрична.

## 3.1. Touch types

Додай enum на кшталт:

- `WICK_TOUCH`;
- `BODY_ENTRY`;
- `CLOSE_INSIDE`;
- `MIDPOINT_REACHED`;
- `FULL_FILL`;
- `CLOSE_THROUGH`;
- `GAP_OVER_ZONE`.

Не всі типи мусять бути mutually exclusive. За потреби використовуй primary type + feature flags.

## 3.2. Zone metrics

Зберігай:

- penetration depth у price;
- penetration depth як частку FVG width;
- penetration depth у H4 ATR;
- maximum adverse excursion всередині/за зоною;
- close location відносно zone;
- bars від setup activation до touch;
- кількість H4 candles у зоні;
- duration у годинах;
- first touch та deepest touch;
- чи була зона вже частково mitigated до `setup.known_at`.

## 3.3. Pre-existing mitigation

Якщо частина D1 FVG була проторгована до того, як setup став `known_at`, це не можна рахувати як causal H4 reaction.

Збережи:

- `pre_activation_mitigation_fraction`;
- `post_activation_touch_fraction`.

Reaction engine має працювати лише з інформацією, доступною після setup activation.

---

# 4. H4 early reaction

`EARLY_REACTION` не повинна означати простий touch.

Для bearish setup early reaction може включати одну або кілька ознак:

- close back below D1 FVG;
- bearish rejection candle;
- lower close після touch;
- bearish H4 displacement candidate;
- локальний H4 FVG;
- failed auction у верхній частині D1 zone;
- sweep локальної H4 liquidity;
- скорочення penetration після deepest touch.

Bullish логіка симетрична.

## 4.1. Hard minimum

Для переходу `ZONE_TOUCHED → EARLY_REACTION` вимагай щонайменше:

- touch відбувся після `setup.known_at`;
- немає hard invalidation;
- є directional rejection evidence;
- reaction evidence стало відомим на закритті H4 candle.

Сам touch без rejection evidence не є early reaction.

## 4.2. Early reaction score

Зроби transparent score із компонентів:

- touch quality;
- close-back quality;
- rejection candle quality;
- local liquidity event;
- H4 displacement candidate;
- H4 FVG;
- freshness;
- zone depth penalty;
- dwell-time penalty.

Score не повинен компенсувати hard invalidation.

---

# 5. H4 reaction confirmation

Для `REACTION_CONFIRMED` використовуй causal structural evidence.

Bearish confirmation повинна вимагати:

1. D1 bearish setup ще active.
2. H4 zone touch уже відбувся.
3. Після touch є qualified bearish displacement.
4. Displacement ламає релевантний H4 internal swing low за close.
5. Structure break causal пов’язаний із touch/reaction impulse.
6. Немає accepted H4 close through D1 invalidation boundary.
7. Усі компоненти directionally узгоджені.

Bullish логіка симетрична.

## 5.1. H4 swings і structure

Не використовуй D1 swings для H4 confirmation.

Або:

- повторно використай generic causal swing/structure engine із timeframe-specific config;
- або створюй H4 wrapper над існуючим generic engine.

Не дублюй логіку без потреби.

## 5.2. H4 displacement

Повторно використай generic displacement detector, але додай H4 config:

- ATR period;
- minimum body ATR;
- range ATR;
- net move ATR;
- efficiency;
- close location;
- allowed impulse length;
- mandatory structure break.

## 5.3. Confirmation `known_at`

`reaction.known_at` або `confirmed_at` дорівнює найпізнішому `known_at` серед:

- zone touch;
- H4 displacement;
- H4 structure break;
- linked H4 FVG, якщо він mandatory;
- інших mandatory confirmation components.

---

# 6. Invalidation та expiry

## 6.1. Hard invalidation

Додай configurable правила.

Для bearish D1 setup можливі:

- H4 close вище D1 FVG upper boundary + buffer;
- accepted breakout над D1 structural invalidation level;
- D1 setup перейшов у `INVALIDATED`;
- FVG повністю пройдений і acceptance підтверджено;
- протилежний H4 structure break до reaction confirmation.

Bullish логіка симетрична.

## 6.2. Acceptance beyond zone

Не інвалідуй reaction через один wick.

Використай configurable acceptance logic:

- minimum closes beyond;
- maximum excursion ATR;
- hold bars;
- optional reclaim window.

## 6.3. Expiry

Підтримай:

- maximum H4 bars до first touch;
- maximum H4 bars від touch до confirmation;
- maximum total H4 reaction age.

Expiry має рахуватися за bars, а не випадково за calendar days.

---

# 7. Canonical H4 reaction sequence

Один D1 setup може мати кілька touches та кілька overlapping H4 displacement windows.

Реалізуй canonicalization.

## 7.1. Touch phase

Групуй contiguous або близькі interactions із зоною в одну `TouchPhase`.

Поля:

- phase ID;
- setup ID;
- first touch;
- last touch;
- deepest penetration;
- bars in zone;
- primary touch type;
- invalidation status.

Не створюй нову reaction sequence на кожну candle всередині тієї самої touch phase.

## 7.2. Canonical reaction candidate

Ключ має враховувати:

- setup ID;
- touch phase ID;
- side;
- broken H4 internal swing ID;
- linked H4 FVG/impulse ID.

Пріоритет:

1. повні hard gates;
2. causal structure break;
3. linked H4 displacement;
4. linked H4 FVG;
5. earliest full confirmation;
6. highest score;
7. shortest deterministic impulse interval.

Merged candidates зберігай з diagnostic reason:

```text
MERGED_INTO_CANONICAL_H4_REACTION
```

---

# 8. Outcome analytics

Outcome analytics не повинна змінювати detection logic.

Вона запускається після того, як reaction стала `REACTION_CONFIRMED`, `INVALIDATED` або `EXPIRED`.

## 8.1. Reference prices

Зберігай кілька reference prices:

- first touch price;
- D1 FVG midpoint;
- deepest penetration price;
- reaction confirmation close;
- optional theoretical entry reference.

Не називай це реальною торговою entry без окремої entry model.

## 8.2. MFE/MAE

Для кожної confirmed reaction обчислюй:

- MFE у price;
- MFE у ATR;
- MAE у price;
- MAE у ATR;
- bars/time до MFE;
- bars/time до MAE.

Рахуй у configurable horizons:

- 6 H4 bars;
- 12 H4 bars;
- 24 H4 bars;
- 42 H4 bars;
- або configurable список.

## 8.3. Structural outcomes

Додай labels:

- `REACTION_CONTINUED`;
- `REACTION_FAILED`;
- `ZONE_RETESTED`;
- `D1_TARGET_REACHED`;
- `OPPOSITE_LIQUIDITY_REACHED`;
- `INVALIDATION_REACHED`;
- `NO_RESOLUTION_WITHIN_HORIZON`.

## 8.4. Target model

Не hardcode один target.

Підтримай deterministic target references:

- nearest opposing D1 internal liquidity;
- nearest opposing D1 external liquidity;
- setup impulse origin;
- configurable fixed ATR multiples;
- optional FVG-to-liquidity target.

Для кожного target зберігай:

- target type;
- target price;
- known_at;
- reached_at;
- bars to target;
- adverse excursion before target.

Уникай lookahead: target повинен бути відомий на момент reaction confirmation.

## 8.5. Outcome snapshots

Створи immutable outcome snapshots для кожного horizon, щоб повторний replay був deterministic та idempotent.

---

# 9. JTOUSDT regression

Використай поточний JTO D1 setup без зміни його D1 semantics.

Очікувана перевірка:

1. D1 setup залишається знайденим із тим самим:
   - external high;
   - sweep;
   - retracement;
   - attempt;
   - displacement;
   - D1 FVG;
   - context.
2. H4 engine визначає:
   - перший causal touch D1 FVG;
   - touch phase;
   - penetration metrics;
   - early reaction або причину її відсутності;
   - H4 displacement;
   - H4 internal structure break;
   - reaction status;
   - reaction score;
   - outcome metrics.

Не hardcode JTO timestamps, prices або expected IDs.

Якщо H4 reaction не підтверджується, сформуй precise diagnostic:

- failed hard gate;
- missing structural component;
- invalidation event;
- insufficient H4 data;
- threshold/score details.

Не підганяй thresholds лише для проходження JTO.

---

# 10. Controlled batch scanning

Після завершення single-symbol H4 pipeline додай offline batch scan.

## 10.1. Scope

Підтримай список символів із config або CLI:

```bash
scan-universe --symbols BTCUSDT,ETHUSDT,JTOUSDT
```

або файл зі списком.

Не реалізовуй live scanning.

## 10.2. Data validation

Для кожного symbol/timeframe перевір:

- duplicate candles;
- missing intervals;
- unordered candles;
- invalid OHLC;
- non-UTC timestamps;
- insufficient warm-up;
- incomplete final candle.

Data-quality errors не повинні тихо пропускатися.

## 10.3. Isolation

Помилка одного symbol не повинна ламати весь batch.

Зберігай per-symbol:

- run status;
- error;
- candle counts;
- setup counts;
- reaction counts;
- outcome counts;
- timings.

## 10.4. Determinism

Один і той самий offline input + config повинен давати однакові:

- IDs;
- CSV;
- SQLite rows;
- ordering;
- hashes.

## 10.5. Performance

Не оптимізуй передчасно, але:

- не перераховуй ATR/swings для одного timeframe багато разів без потреби;
- кешуй immutable features у межах run;
- використовуй bulk persistence;
- вимірюй runtime per symbol.

---

# 11. Persistence

Додай таблиці/моделі за потреби:

- `h4_touch_phases`;
- `h4_reactions`;
- `h4_reaction_candidates`;
- `h4_merged_candidates`;
- `h4_reaction_transitions`;
- `reaction_outcomes`;
- `reaction_target_outcomes`;
- `batch_runs`;
- `batch_symbol_runs`.

Вимоги:

- idempotent upserts;
- foreign keys;
- useful indexes;
- UTC timestamps;
- config hash;
- run ID;
- deterministic IDs;
- не ламати існуючі D1 tables.

---

# 12. CLI

Додай команди або розшир поточні.

## 12.1. Single-symbol H4 analysis

Приклад:

```bash
detect-h4-reactions   --symbol JTOUSDT   --d1-candles data/JTOUSDT_1d.csv   --h4-candles data/JTOUSDT_4h.csv   --config config.yaml   --output reports/JTOUSDT
```

## 12.2. Outcomes

Приклад:

```bash
evaluate-reaction-outcomes   --symbol JTOUSDT   --h4-candles data/JTOUSDT_4h.csv   --output reports/JTOUSDT
```

## 12.3. Batch

Приклад:

```bash
scan-universe   --symbols-file symbols.txt   --data-dir data   --config config.yaml   --output reports/universe
```

Команди повинні повертати non-zero exit code при validation/config/runtime errors.

---

# 13. Reports

Для single-symbol scan експортуй щонайменше:

- `h4_touch_phases.csv`;
- `h4_reactions.csv`;
- `h4_reaction_candidates.csv`;
- `h4_rejected_candidates.csv`;
- `h4_merged_candidates.csv`;
- `h4_reaction_transitions.csv`;
- `reaction_outcomes.csv`;
- `reaction_target_outcomes.csv`;
- `h4_diagnostics.json`;
- PNG chart.

PNG повинен показувати:

- D1 FVG;
- D1 setup activation;
- first H4 touch;
- touch phase;
- deepest penetration;
- early reaction;
- H4 displacement;
- H4 structure break;
- reaction confirmation;
- invalidation/expiry;
- targets та realized outcome.

Для batch scan додай:

- `universe_summary.csv`;
- `symbol_run_summary.csv`;
- `active_d1_setups.csv`;
- `confirmed_h4_reactions.csv`;
- `reaction_outcome_summary.csv`;
- `data_quality_errors.csv`;
- `run_manifest.json`.

---

# 14. Testing

Обов’язкові synthetic tests.

## 14.1. Multi-timeframe causality

1. H4 touch до `D1 setup.known_at` ігнорується.
2. H4 touch після activation створює `ZONE_TOUCHED`.
3. Незакрита H4 candle не створює event.
4. Batch та incremental replay ідентичні.
5. Shuffled candles після sorting дають той самий результат.
6. Missing H4 candles створюють data-quality diagnostic.

## 14.2. Touch logic

7. Wick touch.
8. Body entry.
9. Close inside.
10. Midpoint reached.
11. Full fill.
12. Gap through zone.
13. Pre-activation mitigation не рахується як reaction.
14. Кілька candles у зоні агрегуються в одну touch phase.

## 14.3. Early reaction

15. Touch без rejection не створює `EARLY_REACTION`.
16. Close back outside створює early reaction.
17. Rejection candle score deterministic.
18. Dwell-time penalty застосовується.
19. Deep penetration penalty застосовується.

## 14.4. Confirmation

20. Displacement без structure break не підтверджує reaction.
21. Structure break без causal displacement не підтверджує reaction.
22. Правильний displacement + internal break підтверджує reaction.
23. Components із різних impulse sequences не об’єднуються.
24. Bullish mirror case.
25. `confirmed_at` causal.

## 14.5. Invalidation/expiry

26. Wick beyond zone не інвалідує reaction автоматично.
27. Accepted closes through zone інвалідують.
28. Reclaim у дозволеному window скасовує premature acceptance.
29. Expiry до touch.
30. Expiry після touch без confirmation.
31. D1 setup invalidation каскадно інвалідує H4 reaction.

## 14.6. Canonicalization

32. Overlapping H4 displacement windows → одна canonical reaction.
33. Merged candidates мають diagnostic reason.
34. Canonical selection deterministic.
35. Повторний replay не дублює rows.

## 14.7. Outcomes

36. MFE/MAE правильні для bearish case.
37. MFE/MAE правильні для bullish case.
38. Target відомий на reaction confirmation.
39. Target, створений майбутньою структурою, не використовується.
40. Horizon snapshots deterministic.
41. Target reached timestamp правильний.
42. No-resolution label після завершення horizon.

## 14.8. Batch

43. Помилка одного symbol не зупиняє інші.
44. Stable ordering незалежно від input symbol order.
45. Run manifest deterministic.
46. Per-symbol counts збігаються із single-symbol scan.

## 14.9. Regression

47. Усі D1 tests залишаються green.
48. JTO D1 setup не змінюється.
49. JTO H4 diagnostic генерується.
50. Offline replay hashes стабільні.

---

# 15. Configuration

Додай окремі секції:

```yaml
h4_swing:
h4_structure:
h4_displacement:
h4_touch:
h4_reaction:
h4_invalidation:
reaction_outcomes:
batch_scan:
```

Усі thresholds повинні:

- мати typed config;
- мати validation;
- входити в config hash;
- бути присутніми в `config.example.yaml`;
- бути описані в README.

Не використовуй magic numbers у detectors.

---

# 16. Quality requirements

Після змін повинні проходити:

- усі старі й нові pytest tests;
- coverage не нижче поточного baseline, бажано ≥ 90%;
- Ruff format;
- Ruff lint;
- strict mypy;
- deterministic batch та incremental replay;
- idempotent SQLite persistence;
- stable CSV hashes;
- JTO D1 regression unchanged.

Не позначай Third task завершеним, якщо:

- touch до `setup.known_at` може впливати на reaction;
- touch без rejection автоматично стає early reaction;
- reaction підтверджується без H4 structure break;
- overlapping windows створюють дублікати;
- outcomes використовують future target information;
- batch result залежить від порядку symbols;
- D1 JTO regression змінився.

---

# 17. Обмеження цієї ітерації

Не реалізовуй:

- M15/LTF entry engine;
- реальні order/position models;
- fees, slippage або PnL backtest;
- live/WebSocket scanning;
- Telegram alerts;
- ML;
- parameter optimization;
- автоматичну зміну thresholds;
- portfolio/risk management.

---

# Definition of Done

Ітерація завершена лише якщо:

1. H4 candles causal прив’язані до active D1 setup.
2. Реалізовано canonical touch phase.
3. `ZONE_TOUCHED` відрізняється від `EARLY_REACTION`.
4. `REACTION_CONFIRMED` вимагає H4 displacement + internal structure break.
5. Invalidation та expiry працюють за bars.
6. Overlapping H4 candidates дедупліковані.
7. Outcome analytics не використовує lookahead.
8. MFE/MAE та targets зберігаються deterministic.
9. Single-symbol JTO diagnostic сформований.
10. Controlled offline batch scanning працює.
11. Усі quality checks проходять.
12. Існуючий D1 JTO setup не змінився.

---

# Фінальний звіт Codex

Наприкінці надай:

1. список змінених файлів;
2. точне правило H4 zone touch;
3. точне правило `EARLY_REACTION`;
4. точне правило `REACTION_CONFIRMED`;
5. invalidation та expiry semantics;
6. canonicalization rule;
7. outcome formulas та horizons;
8. persistence schema;
9. CLI examples;
10. результати pytest, coverage, Ruff і strict mypy;
11. deterministic replay/hash results;
12. JTO D1 regression result;
13. JTO H4 reaction diagnostic;
14. batch scan summary;
15. відомі обмеження;
16. оцінку готовності до наступного етапу: `LTF entry model and strategy backtesting`.
