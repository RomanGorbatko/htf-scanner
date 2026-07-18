# Codex task: multi-stage liquidity context, failed continuation scoring та дедуплікація setup candidates

Продовж роботу над поточною реалізацією після останньої ітерації.

Перед змінами:

1. Прочитай `htf_setup_scanner_implementation_plan.md`.
2. Переглянь поточні detectors, domain models, reports, persistence і tests.
3. Запусти pytest, Ruff і strict mypy.
4. Не переходь до H4 reaction, outcomes або universe scanning у цій ітерації.

Мета цієї ітерації — завершити `Second Codex task`, виправивши multi-stage liquidity context, failed continuation classification і дублювання setup candidates.

## 1. Додати історію взаємодій із external liquidity levels

Для кожного активного external high/low зберігай causal історію подій:

- `TOUCHED`;
- `SWEPT`;
- `REJECTED`;
- `ACCEPTED_BEYOND`;
- `RECLAIMED`;
- `INVALIDATED`.

Кожна подія повинна містити:

- external level ID;
- reference swing ID;
- direction;
- event type;
- formed_at;
- known_at;
- candle ID/time;
- excursion beyond level у price та ATR;
- close position відносно level;
- number of closes beyond level;
- maximum acceptance distance ATR.

Structural external level і liquidity interaction — це різні сутності. Sweep не повинен автоматично замінювати structural reference level.

Додай persistence та CSV/debug output для liquidity interaction events.

## 2. Підтримати multi-stage liquidity sequence

Класифікатор повинен розуміти послідовність:

```text
external level
→ sweep/raid
→ retracement
→ later continuation attempt
→ failed continuation
→ opposite displacement
→ internal structure break
```

Якщо sweep стався раніше, а останній continuation attempt уже не торкався external level, контекст усе одно може бути:

```text
SWEEP_AND_FAILED_CONTINUATION
```

Не обмежуй sweep аналіз лише останнім attempt swing.

Для setup зберігай:

- external reference swing;
- усі релевантні liquidity interactions;
- sweep event, якщо він був;
- retracement swing;
- continuation attempt swing;
- broken internal swing;
- displacement;
- linked FVG.

## 3. Переробити failed continuation: hard gates + soft score

Не визначай failed continuation лише двома жорсткими умовами:

- maximum distance до external level;
- maximum bars до displacement.

### Hard requirements

Bearish failed continuation має вимагати:

1. Існує active external high.
2. Після нього є confirmed retracement low.
3. Після retracement є confirmed continuation-attempt high.
4. Немає accepted breakout над external high.
5. Після attempt виникає qualified bearish displacement.
6. Displacement або його causal continuation ламає релевантний internal low за close.
7. Є пов’язаний bearish FVG у тому самому impulse sequence.

Bullish логіка симетрична.

### Soft features

Наступні параметри мають впливати на score, але не повинні автоматично відхиляти setup:

- distance attempt до external level в ATR;
- bars від attempt до displacement;
- retracement size ATR;
- bars між reference, retracement і attempt;
- quality continuation attempt;
- prior sweep history;
- displacement quality;
- FVG quality;
- freshness.

Збережи configurable soft thresholds, але використовуй їх для нормалізованого score/penalty.

Наприклад, `0.69 ATR` замість `0.5 ATR` або 6 bars замість 5 не повинні самі по собі знищувати structurally valid setup.

## 4. Розділити hard rejection і score penalties

Hard rejection дозволений лише для причин на кшталт:

- відсутній reference/retracement/attempt;
- accepted breakout;
- немає opposite displacement;
- немає internal structure break;
- немає linked FVG;
- компоненти належать різним causal sequences;
- direction mismatch;
- setup already invalidated.

Distance, timing і freshness мають бути score penalties, а не hard rejection, якщо структура валідна.

У rejected report окремо показуй:

- `hard_rejection_reasons`;
- `score_penalties`;
- `failed_hard_gates`;
- `soft_feature_values`.

## 5. Дедуплікувати overlapping displacement candidates

Зараз одна structural sequence може створювати кілька candidates через overlapping single/multi-candle displacement windows.

Реалізуй canonicalization:

```text
одна structural sequence
→ один canonical setup candidate
```

Ключ sequence повинен враховувати щонайменше:

- symbol;
- side;
- external reference swing ID;
- retracement swing ID;
- continuation attempt swing ID;
- broken internal swing ID;
- linked FVG ID або impulse sequence ID.

Правило вибору canonical displacement:

1. displacement, який causal пов’язаний із потрібним structure break;
2. має linked FVG;
3. першим підтвердив повний setup;
4. при рівності — має найвищий transparent score;
5. при подальшій рівності — найкоротший/найраніший deterministic interval.

Не створюй окремі setup candidates для кожного overlapping window одного імпульсу.

Збережи rejected/merged displacement candidates у diagnostics із причиною:

```text
MERGED_INTO_CANONICAL_CANDIDATE
```

## 6. Виправити liquidity context classification для JTO-like sequence

Очікувана логіка для відомого JTO кейсу:

```text
external high
→ later sweep/raid above it
→ retracement
→ weaker continuation high
→ bearish displacement
→ internal MSS/BOS
→ bearish FVG
```

Такий setup повинен мати контекст:

```text
SWEEP_AND_FAILED_CONTINUATION
```

або, якщо sweep event не проходить configurable quality threshold:

```text
FAILED_CONTINUATION
```

Він не повинен залишатися лише:

```text
UNSWEPT_EXTERNAL_LIQUIDITY
```

Не hardcode конкретні JTO timestamps або prices.

## 7. Оновити setup scoring

Transparent score повинен містити:

- structure component;
- displacement component;
- FVG component;
- failed continuation component;
- sweep-history component;
- freshness component;
- distance penalty;
- timing penalty.

Hard gates перевіряються до scoring.

Додай у reports усі score components і total score.

## 8. Оновити domain models та persistence

За потреби додай:

- `LiquidityInteraction`;
- `LiquidityInteractionType`;
- `LiquiditySequence`;
- `ImpulseSequence`;
- canonical candidate/merge metadata.

Усі timestamps повинні бути UTC, а `formed_at` і `known_at` — causal.

Додай SQLite tables/indexes та idempotent upserts.

Не ламай існуючу candle/FVG/setup persistence.

## 9. Оновити CLI та debug reports

Команда `detect-d1-setups` повинна додатково експортувати:

- `d1_liquidity_interactions.csv`;
- `d1_liquidity_sequences.csv`;
- `d1_setup_candidates.csv`;
- `d1_rejected_candidates.csv`;
- `d1_merged_candidates.csv`.

Для кожного setup/candidate показуй:

- external reference;
- sweep history;
- retracement;
- continuation attempt;
- broken internal level;
- canonical displacement;
- linked FVG;
- liquidity context;
- hard gates;
- soft penalties;
- score components;
- state transitions.

PNG повинен візуально показувати sweep event і пізніший failed continuation attempt як окремі події.

## 10. Додати тести

Обов’язкові synthetic tests:

1. sweep → retracement → later failed continuation → setup;
2. failed continuation без sweep → setup;
3. prior sweep history з later weak high класифікується як `SWEEP_AND_FAILED_CONTINUATION`;
4. accepted breakout блокує reversal setup;
5. unswept liquidity без failed continuation не створює setup;
6. distance трохи вище soft threshold з валідною структурою не викликає hard rejection;
7. timing трохи вище soft threshold з валідною структурою не викликає hard rejection;
8. overlapping displacement windows створюють один canonical setup;
9. canonical selection deterministic;
10. merged candidates мають diagnostic reason;
11. liquidity interactions causal `formed_at`/`known_at`;
12. batch/incremental equivalence;
13. bullish mirror cases.

## 11. JTOUSDT regression/diagnostic

Якщо локальний JTO cache є в репозиторії, запусти offline detector.

У фінальному звіті покажи:

- external reference high;
- sweep event high/time;
- retracement low/time;
- continuation attempt high/time;
- broken internal low;
- displacement interval;
- linked FVG boundaries;
- liquidity context;
- total score та components;
- setup `formed_at`;
- setup `known_at`;
- чи створено один canonical candidate;
- чи setup став `CONFIRMED/ACTIVE`.

Не підганяй окремі thresholds під JTO. Якщо setup не знайдено, надай точний diagnostic із hard gate, який не пройдено.

## Обмеження цієї ітерації

Не реалізовуй:

- H4 reaction engine;
- outcomes;
- universe scanning;
- live/WebSocket;
- M15/LTF entry;
- ML;
- automated parameter optimization.

## Definition of Done для цієї ітерації

Ітерація завершена лише якщо:

- liquidity interactions з external levels зберігаються causal;
- prior sweep history доступна classifier;
- multi-stage sweep + failed continuation підтримується;
- failed continuation використовує hard gates + soft score;
- distance/timing не є автоматичними hard blockers;
- overlapping displacement candidates дедупліковані;
- один structural sequence створює один canonical setup;
- JTO-like synthetic fixture проходить;
- JTOUSDT regression або проходить, або має точний non-tuned diagnostic;
- pytest, coverage, Ruff і strict mypy проходять;
- deterministic offline replay збережений;
- checklist оновлений лише для фактично завершених пунктів.

## Фінальний звіт

Наприкінці надай:

1. список змінених файлів;
2. модель liquidity interaction history;
3. точне правило multi-stage liquidity sequence;
4. hard gates та soft features failed continuation;
5. canonicalization/deduplication rule;
6. результати tests, coverage, Ruff і mypy;
7. JTOUSDT result;
8. відомі обмеження;
9. чи готовий проєкт перейти до `Third Codex task: H4 reaction, outcomes, and batch scanning`.
