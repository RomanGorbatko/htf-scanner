# Завдання для Codex: causal structure та D1 setup classification

Продовж реалізацію існуючого проєкту відповідно до `htf_setup_scanner_implementation_plan.md`.

Не переписуй уже завершену D1 FVG vertical slice. Перед початком переглянь код, тести та секцію `Current milestone` у плані.

У цій ітерації виконай **Second Codex task: causal structure and D1 setup classification**.

## Завдання

1. Заверши Phase 1 foundation:
   - додай domain-моделі для swings, structure breaks, displacements, liquidity context, HTF setups, reactions, outcomes, events і scanner runs;
   - додай відповідні SQLite-таблиці, індекси та idempotent persistence;
   - додай scanner-run metadata і стабільний configuration hash.

2. Реалізуй causal ATR ZigZag swing detector:
   - без використання майбутніх даних;
   - окремі `formed_at` і `known_at`;
   - configurable ATR reversal threshold;
   - однаковий результат у batch та candle-by-candle режимах.

3. Реалізуй incremental market structure:
   - confirmed swing highs/lows;
   - internal та external structure levels;
   - BOS/CHoCH або еквівалентну формалізовану класифікацію;
   - structure break за закриттям свічки;
   - batch та incremental результати мають збігатися.

4. Реалізуй окремий `DisplacementDetector`:
   - range/body/net move відносно ATR;
   - body efficiency;
   - close location;
   - single- та multi-candle impulse;
   - зв’язок зі structure break і FVG.

5. Реалізуй класифікацію D1-контексту:
   - liquidity sweep;
   - unswept external liquidity;
   - failed continuation high/low;
   - sweep + failed continuation;
   - accepted breakout;
   - no clear context.

   Liquidity sweep **не є обов’язковою умовою setup**. Валідний bearish setup може виникати, коли попередня верхня ліквідність залишилася, наступний high не зміг продовжити bullish structure, а потім виник bearish displacement зі зламом структури. Bullish логіка має бути симетричною.

6. Реалізуй центральну модель і детектор `HTFSetup`.

   `FairValueGap` має залишатися примітивом, а не головним об’єктом системи.

   D1 setup повинен об’єднувати:
   - structural context;
   - liquidity classification;
   - displacement;
   - structure break;
   - пов’язаний D1 FVG;
   - `formed_at` і `known_at`;
   - transparent quality score та його компоненти.

7. Додай CLI-команду для історичного пошуку D1 setup, наприклад:

   ```bash
   htf-scanner detect-d1-setups --symbol JTOUSDT --offline
   ```

8. Додай debug-звіти:
   - CSV зі swings, structure breaks, displacements і setups;
   - PNG з D1-свічками, swing-рівнями, structure breaks, displacement, liquidity context та setup FVG.

9. Додай тести:
   - batch/incremental equivalence;
   - causal `formed_at`/`known_at`;
   - setup із liquidity sweep;
   - setup із failed continuation без sweep;
   - accepted breakout, який не повинен класифікуватися як reversal setup;
   - FVG без displacement, який не повинен ставати HTF setup;
   - bullish mirror cases.

## Обмеження

У цій ітерації не реалізовуй:

- H4 reaction engine;
- outcomes;
- batch universe scanning;
- live/WebSocket режим;
- M15/LTF entry;
- ML або оптимізацію параметрів під JTO.

## Якість

Збережи сумісність із поточною реалізацією та командою `inspect-fvg`.

Після змін повинні проходити:

- pytest;
- coverage не нижче встановленого target;
- Ruff format/lint;
- strict mypy;
- deterministic offline replay.

Онови checklist у `htf_setup_scanner_implementation_plan.md` лише для фактично завершених пунктів.

Наприкінці надай:

1. список змінених файлів;
2. короткий опис математичних правил swing, structure break, displacement, failed continuation та HTF setup;
3. результати тестів, coverage, Ruff і mypy;
4. що залишилося до Third Codex task;
5. чи знаходить поточний алгоритм JTOUSDT setup, а якщо ні — точну причину без підгонки параметрів під один кейс.
