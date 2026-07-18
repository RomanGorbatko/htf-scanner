# Codex task: виправлення causal structure та D1 setup classification

Продовж роботу над поточною реалізацією після `codex_second_task_prompt_uk.md`.

Перед змінами:

1. Прочитай `htf_setup_scanner_implementation_plan.md`.
2. Переглянь поточні domain-моделі, detectors, persistence, CLI та tests.
3. Запусти pytest, Ruff і strict mypy.
4. Не переходь до H4 reaction, outcomes або batch universe scanning у цій ітерації.

Мета цієї ітерації — виправити концептуальні помилки в market structure, liquidity classification та `HTFSetupDetector`, не переписуючи вже працездатливий FVG vertical slice.

## 1. Виправити causal swing processing

У batch API спочатку відсортуй candles, а вже потім обчислюй ATR/features.

Неприпустимо обчислювати features для одного порядку candles, а далі ітеруватися по іншому.

Додай тест із навмисно перемішаними candles, який доводить, що batch результат ідентичний результату для хронологічно відсортованих даних.

## 2. Реалізувати справжню internal/external structure hierarchy

Поточна логіка на кшталт «external = max/min серед двох останніх swings» неприйнятна.

Потрібно формально розділити:

- internal swing;
- external swing;
- protected high/low;
- active structural leg;
- promotion internal swing до external після підтвердженого structural break.

Вимоги:

- старий major external high/low не повинен зникати лише тому, що з’явилися два нові minor swings;
- external level зберігається, доки його не буде структурно зламано або замінено за чітким causal правилом;
- internal levels використовуються для локального BOS/CHoCH/MSS;
- external levels використовуються як reference liquidity та major structure;
- усі transitions мають бути causal;
- batch та candle-by-candle результати повинні збігатися.

Опиши математичні правила internal/external structure у docstring і README.

Додай visual debug для:

- active external high/low;
- protected high/low;
- internal swing levels;
- моменти promotion;
- BOS/CHoCH/MSS.

## 3. Переробити `LiquidityContextClassifier`

Класифікатор не повинен самостійно брати «два останні same-side swings».

Він повинен отримувати явно:

- актуальний external reference swing;
- continuation-attempt swing;
- retracement/internal opposite swing між ними;
- structure state;
- opposite displacement;
- structure break після attempt.

### Failed continuation

Bearish failed continuation має вимагати послідовність:

1. Є підтверджений external structural high.
2. Після нього є достатній retracement з internal swing low.
3. Формується новий confirmed high як continuation attempt.
4. Attempt не створює accepted breakout над external high.
5. Після attempt виникає bearish displacement.
6. Цей displacement ламає релевантний internal swing low за close.

Bullish логіка симетрична.

Не класифікуй звичайні близькі highs/lows у range як failed continuation лише через ATR-distance.

Зберігай raw features:

- distance attempt до external level в ATR;
- excursion над/під external level;
- retracement size ATR;
- bars між external swing, retracement та attempt;
- closes beyond external level;
- maximum acceptance distance ATR;
- displacement metrics;
- broken internal swing ID;
- bars від attempt до displacement.

### Liquidity sweep

Sweep має бути окремою характеристикою:

- wick/excursion за external level;
- відсутність accepted breakout;
- повернення close назад за reference level;
- подальший opposite displacement/structure break.

Sweep не є обов’язковою умовою setup.

### Accepted breakout

Accepted breakout оцінюй тільки в локальному вікні від continuation attempt або першого breakout до return/displacement.

Не використовуй усі candles від старого reference swing до displacement.

Accepted breakout повинен враховувати:

- кількість closes за рівнем;
- максимальну distance за рівнем у ATR;
- кількість bars утримання;
- configurable acceptance thresholds.

## 4. Не дозволяти `UNSWEPT_EXTERNAL_LIQUIDITY` самостійно активувати setup

`UNSWEPT_EXTERNAL_LIQUIDITY` — це feature/context, а не достатній reversal trigger.

Setup може бути підтверджений за контекстами:

- `LIQUIDITY_SWEEP`;
- `FAILED_CONTINUATION`;
- `SWEEP_AND_FAILED_CONTINUATION`.

`UNSWEPT_EXTERNAL_LIQUIDITY` може бути додатковою ознакою всередині failed continuation, але не повинна сама створювати `HTFSetup`.

`ACCEPTED_BREAKOUT` і `NO_CLEAR_CONTEXT` повинні блокувати reversal setup.

## 5. Зробити structure break обов’язковим для confirmed D1 setup

Для Version 0.1 confirmed D1 setup повинен містити:

- qualified opposite displacement;
- break релевантного internal structure level за close;
- пов’язаний FVG, створений цим displacement або його безпосереднім impulse sequence;
- валідний liquidity/continuation context.

Сильна свічка та FVG всередині range без structure break не повинні ставати confirmed setup.

Можна зберігати такі випадки як `CANDIDATE`, але не як `CONFIRMED` або `ACTIVE`.

Зміни default config так, щоб `require_structure_break = true`.

## 6. Виправити зв’язування displacement, structure break і FVG

`HTFSetupDetector` повинен доводити, що всі компоненти належать одній причинно-часовій послідовності.

Вимоги:

- displacement починається після continuation attempt;
- structure break відбувається всередині displacement або не пізніше configurable кількості bars після нього;
- FVG формується всередині того самого impulse sequence;
- не можна прив’язувати старий або випадковий FVG;
- direction усіх компонентів має збігатися;
- `known_at` setup дорівнює найпізнішому causal confirmation time серед обов’язкових компонентів.

## 7. Додати централізовану state machine для `HTFSetup`

Підтримай стани:

- `CANDIDATE`;
- `CONFIRMED`;
- `ACTIVE`;
- `INVALIDATED`;
- `EXPIRED`.

Дозволені переходи мають бути централізовані та валідовані.

Мінімальна логіка:

- `CANDIDATE` — є частина компонентів, але ще немає повного structural confirmation;
- `CONFIRMED` — усі causal умови setup виконані;
- `ACTIVE` — setup підтверджений, FVG ще доступний для майбутньої H4 взаємодії;
- `INVALIDATED` — structural invalidation або invalidation FVG;
- `EXPIRED` — перевищений age limit.

Не створюй setup одразу як `ACTIVE`, якщо він ще не проходив confirmed transition.

## 8. Виправити expiry semantics

Якщо параметр називається `max_setup_age_bars`, expiry має рахуватися за кількістю оброблених D1 bars.

Альтернатива — перейменувати його на `max_setup_age_days`, але назва і реалізація повинні збігатися.

Для майбутньої timeframe-agnostic архітектури бажано використовувати bars.

Додай boundary tests.

## 9. Оновити setup scoring

Score має бути прозорим і складатися з окремих компонентів:

- structure score;
- displacement score;
- FVG score;
- liquidity sweep score;
- failed continuation score;
- freshness score.

Важливо:

- score не повинен компенсувати відсутність mandatory structure break;
- score не повинен дозволяти `UNSWEPT_EXTERNAL_LIQUIDITY` пройти як confirmed setup;
- hard validation виконується до scoring.

## 10. Додати regression та synthetic tests

Обов’язкові тести:

1. major external high залишається active після кількох internal highs;
2. internal swing promotion до external після structural break;
3. batch/incremental equivalence для structure hierarchy;
4. failed continuation без sweep;
5. liquidity sweep із reversal;
6. accepted breakout не створює reversal setup;
7. unswept liquidity без failed continuation не створює setup;
8. близькі highs у range не класифікуються як failed continuation;
9. displacement + FVG без structure break не створює confirmed setup;
10. displacement, structure break і FVG з різних impulse sequences не можуть бути об’єднані;
11. causal `known_at` setup;
12. expiry за bars;
13. bullish mirror cases;
14. shuffled candle input дає той самий результат після causal sorting.

Якщо в репозиторії є JTOUSDT cache, запусти detector на ньому та вкажи:

- чи знайдено очікуваний D1 setup;
- який external high використано;
- який continuation attempt використано;
- liquidity context;
- broken internal low;
- displacement interval;
- FVG boundaries;
- `formed_at`;
- `known_at`.

Не підганяй thresholds лише для проходження JTO case. Якщо setup не знайдено, сформуй diagnostic report із точним failed condition.

## 11. CLI та debug reports

Онови `detect-d1-setups` так, щоб reports містили:

- external reference swing ID/price/time;
- continuation attempt swing ID/price/time;
- retracement swing ID/price/time;
- broken internal swing;
- liquidity context;
- accepted breakout features;
- displacement interval;
- linked FVG;
- state transitions;
- score components;
- rejection reason для кандидатів, які не стали confirmed setup.

Додай окремий CSV для rejected candidates. Це потрібно для аналізу false negatives без зміни detector logic.

## Обмеження цієї ітерації

Не реалізовуй:

- H4 reaction engine;
- outcomes;
- universe batch scanner;
- live/WebSocket;
- LTF entry;
- ML;
- автоматичну оптимізацію thresholds.

## Перевірка якості

Після змін повинні проходити:

- усі існуючі та нові pytest tests;
- coverage не нижче поточного target;
- Ruff format і lint;
- strict mypy;
- deterministic offline replay;
- batch/incremental equivalence.

Не позначай `Second Codex task` завершеним, якщо:

- external/internal hierarchy все ще базується лише на двох останніх swings;
- failed continuation не має retracement + attempt + structure break sequence;
- unswept liquidity сама може створити confirmed setup;
- structure break не є mandatory для confirmed setup;
- setup components можуть походити з різних impulse sequences.

## Фінальний звіт

Наприкінці надай:

1. список змінених файлів;
2. точні правила external/internal structure;
3. точне правило failed continuation;
4. точне правило accepted breakout;
5. state machine `HTFSetup`;
6. результати тестів, coverage, Ruff і mypy;
7. результат JTOUSDT diagnostic;
8. відомі обмеження;
9. що залишилося перед переходом до `Third Codex task: H4 reaction, outcomes, and batch scanning`.
