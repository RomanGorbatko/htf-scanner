# HTF Setup Scanner — Implementation Plan

## Project Progress Checklist

Last updated: 2026-07-19.

### Current milestone

- [x] First Codex task: single-symbol D1 FVG vertical slice.
- [x] Second Codex task: causal structure and D1 setup classification.
- [x] Third Codex task: H4 reaction, outcomes, and controlled offline batch scanning.
- [x] Fourth Codex task: production hourly scanner, incremental recovery, and Telegram alerts.
- [x] Final Codex task: production hardening, packaging, doctor, and deployment readiness.
- [x] Version 0.1 definition of done.

### Completed vertical slice

- [x] Create the installable Python project and `src` package structure.
- [x] Add `pyproject.toml`, runtime/dev dependencies, Ruff, mypy, pytest, and coverage configuration.
- [x] Add validated Pydantic configuration models and `config.example.yaml`.
- [x] Add typed `Candle` and `FairValueGap` domain models with UTC and boundary validation.
- [x] Add exact-Decimal SQLite candle storage with idempotent upserts.
- [x] Add Binance USDⓈ-M REST pagination, retries, chronological validation, deduplication, and missing-interval detection.
- [x] Add native D1/H4 UTC-boundary validation and closed-candle filtering.
- [x] Add exact JSONL candle caching and offline SQLite restoration.
- [x] Implement Wilder ATR and candle feature calculations.
- [x] Detect qualified raw bullish and bearish D1 FVGs.
- [x] Track FVG touch, 25%, midpoint, 75%, full-fill, invalidation, and expiry state.
- [x] Add the `htf-scanner inspect-fvg` CLI command.
- [x] Export `reports/JTOUSDT/d1_fvgs.csv`.
- [x] Generate `reports/JTOUSDT/d1_fvgs.png` with D1 candles and FVG zones.
- [x] Download and cache the available JTOUSDT history: 562 D1 and 3373 H4 closed candles;
  preserve immutable 561-D1 and 3373-H4 regression fixtures.
- [x] Verify deterministic offline output for the same candle set and configuration.

### Verification status

- [x] Unit, integration, synthetic regression, D1/H4 JTO, and production recovery tests pass:
  131 tests.
- [x] Overall test coverage exceeds the target and prior baseline: 93% branch coverage report.
- [x] Ruff formatting and lint checks pass.
- [x] Strict mypy checks pass.
- [x] Repeated offline replay produces identical FVG and D1 analysis CSV SHA-256 hashes.

### Phase 1 foundation

- [x] Add domain models for swings, structure breaks, displacements, liquidity contexts, setups, reactions, outcomes, events, and scanner runs.
- [x] Add indexed SQLite tables and idempotent persistence for all current domain records,
  including liquidity interactions/sequences, structure promotions, raw/merged setup
  candidates, setup transitions, and rejected candidates.
- [x] Add scanner-run metadata and canonical SHA-256 configuration hashes.
- [x] Complete the Phase 1 persistence surface required by later phases.

### Phase 2 core primitives

- [x] Implement causal ATR ZigZag swings with separate `formed_at` and `known_at`.
- [x] Implement persistent internal/external/protected structure with causal promotions and
  close-based BOS/CHoCH/MSS.
- [x] Verify batch and candle-by-candle swing/structure equivalence.
- [x] Extend visual debugging to show confirmed swings and structure levels.

### Phase 3 D1 context and setup detection

- [x] Implement scored single- and multi-candle displacement detection.
- [x] Enforce that displacement, internal close-break, and linked D1 FVG belong to one impulse.
- [x] Classify liquidity sweep, unswept liquidity, failed continuation, combined sweep/failure, accepted breakout, and no-clear context symmetrically.
- [x] Persist causal `TOUCHED`, `SWEPT`, `REJECTED`, `ACCEPTED_BEYOND`, `RECLAIMED`, and
  `INVALIDATED` histories independently from structural external levels.
- [x] Support prior sweep -> retracement -> later attempt -> failed continuation sequences.
- [x] Treat distance, timing, retracement quality, and freshness as soft score inputs rather
  than hard failed-continuation blockers.
- [x] Keep liquidity sweep optional for a valid setup.
- [x] Block unswept liquidity, accepted breakout, and no-clear context as standalone triggers.
- [x] Require an internal structure break before setup scoring and confirmation.
- [x] Add central `HTFSetup` detection with transparent score components and stable IDs.
- [x] Canonicalize overlapping displacement windows to one setup candidate and preserve merged
  alternatives with deterministic diagnostics.
- [x] Add validated `CANDIDATE -> CONFIRMED -> ACTIVE` transitions and bar-index expiry.
- [x] Reject accepted breakouts, no-clear contexts, weak displacement, and unlinked FVGs.
- [x] Add `detect-d1-setups`, indexed persistence, full CSV debug exports, rejected-candidate
  diagnostics, and a D1 setup PNG with hierarchy/promotion overlays.
- [x] Add a 561-candle immutable JTOUSDT D1 regression fixture.
- [x] Confirm one canonical 2026-07-09 JTOUSDT bearish setup without JTO-specific tuning;
  distance and follow-up deviations remain transparent score penalties.

### Phase 4 H4 reaction engine

- [x] Reuse causal H4 ATR swings, internal/external structure, close breaks, displacement, and FVG
  primitives with timeframe-specific typed configuration.
- [x] Ignore H4 candles closed at or before `setup.known_at` while retaining separate
  pre-activation mitigation metadata.
- [x] Classify wick/body/close/midpoint/full-fill/close-through/gap interactions and aggregate
  contiguous candles into deterministic touch phases.
- [x] Separate `ZONE_TOUCHED` from scored `EARLY_REACTION`; require directional rejection evidence.
- [x] Require a same-impulse qualified H4 displacement and linked internal close-break for
  `REACTION_CONFIRMED`.
- [x] Implement accepted-close invalidation, reclaim handling, D1 cascade invalidation, and
  bar-counted pre-touch/touch-to-confirm/total expiry.
- [x] Canonicalize overlapping H4 impulse windows and retain rejected/merged diagnostics.
- [x] Persist touch phases, reactions, candidates, merges, transitions, configuration hashes,
  scanner-run IDs, and deterministic payloads idempotently.

### Phase 5 replay, outcomes, and reporting

- [x] Use the same incremental state engine for chronological batch replay and candle-by-candle
  updates; synthetic equivalence and causality tests pass.
- [x] Add immutable 6/12/24/42-H4 outcome snapshots with directional MFE/MAE, bars/hours to
  extrema, structural labels, and no-resolution semantics.
- [x] Freeze fixed-ATR, setup impulse-origin, and causal D1 internal/external target references at
  reaction confirmation; reject future target information.
- [x] Add `detect-h4-reactions`, `evaluate-reaction-outcomes`, and controlled offline
  `scan-universe` commands with per-symbol error isolation and stable ordering.
- [x] Add indexed SQLite tables and idempotent bulk persistence for H4 artifacts, outcomes,
  targets, batch runs, and per-symbol run metadata.
- [x] Export the required single-symbol and batch CSV/JSON diagnostics plus an annotated H4 PNG.
- [x] Confirm the July JTOUSDT D1 setup without semantic changes and record a causal H4 touch,
  confirmed reaction, target snapshots, and outcome horizons without symbol-specific tuning.
- [x] Verify repeated offline JTO and batch replays produce identical report SHA-256 hashes.

### Later phases

- [x] Phase 4: H4 touch and reaction engine.
- [x] Phase 5: chronological replay, event persistence, analytics, and full reporting.
- [x] Phase 6: immutable JTOUSDT regression fixture and golden report.
- [ ] Phase 7: resumable Binance perpetual universe scan and ranking.
- [x] Phase 8: live-ready data-source abstraction and detector snapshot recovery.

### Production hourly scanner

- [x] Add exchange-neutral `MarketDataProvider` and a Binance USD-M implementation for market
  discovery, OHLCV, latest closed candle, server time, and exchange metadata.
- [x] Discover and filter active USDT perpetuals by history, quote volume, include/exclude lists,
  and persist the selected universe snapshot per run.
- [x] Persist resumable D1/H4 ATR, FVG, swing, structure, liquidity, setup, and H4 reaction state;
  full replay is restricted to bootstrap, explicit rebuild, or configuration-hash changes.
- [x] Verify full serialized D1/H4 artifact equivalence after checkpoint export/restore and
  candle-by-candle append on the immutable JTOUSDT fixture.
- [x] Add immutable deterministic D1 setup and H4 reaction transition events plus an idempotent
  Telegram delivery ledger with retries, backoff, MarkdownV2 escaping, media fallback, and dedup.
- [x] Add per-symbol production statuses, partial-failure isolation, strict closed-candle quality
  gates, run metrics, operational CSV/JSON reports, and atomic overlap prevention.
- [x] Add `scan-live-once`, explicit `--rebuild`, `--no-alerts`, and documented systemd service/timer
  deployment.
- [x] Suppress historical Telegram deliveries during first bootstrap, explicit rebuild, and
  configuration-hash rebuild while persisting historical events and checkpoints.
- [x] Add a bounded `PENDING`/`FAILED` retry lifecycle with `next_retry_at`, terminal
  `PERMANENTLY_FAILED`, additive SQLite migration, stable delivery IDs, and separate run counts.
- [x] Route production market data through a configuration-driven provider factory and reject
  unsupported providers before scanning.
- [x] Add `doctor` checks for configuration, writable paths, SQLite initialization, Binance time
  and discovery, Telegram credentials, and an explicit opt-in test message.
- [x] Add safe `config.production.example.yaml`, complete Python 3.12 packaging, clone-like editable
  install verification without generated metadata, and a verified console entry point.
- [x] Add hardened oneshot systemd service/hourly timer, environment template, idempotent installer,
  first-run deployment guide, stable exit codes, and deployment contract regressions.

> Progress rule: mark an item complete only after its implementation, automated verification, and required artifact are present. Update the date and verification counts whenever this checklist changes.

---

## 1. Goal

Build a Python application that detects historical and live higher-timeframe trading setups on Binance USDⓈ-M perpetual markets.

The first implementation phase must focus only on:

- D1 higher-timeframe context;
- D1 Fair Value Gap formation;
- structural high context;
- classification of liquidity behavior near the structural high;
- H4 return into the D1 FVG;
- H4 reaction from that zone;
- historical replay and analysis;
- validation against the known JTOUSDT case.

The first version must **not** implement LTF entries, 15m FVG entries, order execution, position sizing, Telegram alerts, or exchange trading.

The system must be designed so that the same detector logic can later be reused in live scanning.

---

## 2. Primary use cases

### 2.1 Historical discovery

The application must scan historical D1 and H4 candles and identify all candidate bullish and bearish HTF setups without using future information.

For every detected setup, it must record:

- when the setup was formed;
- when the setup became known to the algorithm;
- D1 FVG boundaries;
- structural high or low context;
- whether liquidity was swept, remained unswept, or continuation failed;
- H4 touch time;
- H4 reaction features;
- setup outcome metrics;
- invalidation or expiration reason.

### 2.2 Historical replay

The system must replay candles chronologically and operate exactly as a live detector would.

It must not:

- access candles after the current replay timestamp;
- use centered rolling windows;
- use future-confirmed pivots without respecting confirmation delay;
- label an event earlier than it could have been known in real time.

### 2.3 JTOUSDT regression case

The application must include a reproducible test that verifies whether the algorithm identifies the JTOUSDT setup discussed in July 2026.

The expected result is not necessarily one exact timestamp or exact score, but the detector should identify:

- a bearish D1 setup;
- an active bearish D1 FVG approximately in the visible zone;
- a return of H4 price into the D1 FVG;
- a bearish H4 reaction;
- subsequent downside continuation.

### 2.4 Future live scanner

The architecture must allow replacing historical REST data with live closed-candle WebSocket updates while preserving the same detector classes and state machine.

---

## 3. Technology stack

Use:

- Python 3.12+
- `pandas`
- `numpy`
- `pydantic`
- `pyyaml`
- `httpx`
- `tenacity`
- `sqlalchemy`
- SQLite for the first version
- `matplotlib`
- `pytest`
- `pytest-cov`
- `ruff`
- `mypy`

Optional:

- `typer` for CLI
- `rich` for console output
- `orjson` for JSON export

Do not use:

- TA-Lib as a hard dependency;
- machine learning in the first version;
- notebook-only implementation;
- hardcoded JTO-specific rules.

---

## 4. Project structure

```text
htf_scanner/
├── pyproject.toml
├── README.md
├── config.example.yaml
├── src/
│   └── htf_scanner/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── logging.py
│       ├── domain/
│       │   ├── enums.py
│       │   ├── candle.py
│       │   ├── fvg.py
│       │   ├── swing.py
│       │   ├── setup.py
│       │   ├── reaction.py
│       │   └── outcome.py
│       ├── data/
│       │   ├── binance_rest.py
│       │   ├── downloader.py
│       │   ├── resampler.py
│       │   ├── cache.py
│       │   └── repository.py
│       ├── indicators/
│       │   ├── atr.py
│       │   ├── candle_features.py
│       │   └── volatility.py
│       ├── structure/
│       │   ├── causal_swings.py
│       │   ├── market_structure.py
│       │   ├── liquidity_context.py
│       │   └── failed_continuation.py
│       ├── detectors/
│       │   ├── displacement.py
│       │   ├── fvg_detector.py
│       │   ├── d1_setup_detector.py
│       │   ├── h4_reaction_detector.py
│       │   └── state_machine.py
│       ├── replay/
│       │   ├── engine.py
│       │   ├── clock.py
│       │   └── event_bus.py
│       ├── analytics/
│       │   ├── outcomes.py
│       │   ├── statistics.py
│       │   ├── ranking.py
│       │   └── exports.py
│       ├── reports/
│       │   ├── charts.py
│       │   ├── html_report.py
│       │   └── markdown_report.py
│       └── storage/
│           ├── models.py
│           ├── database.py
│           └── migrations.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── regression/
│   │   └── test_jto_july_2026.py
│   └── fixtures/
└── scripts/
    ├── download_history.py
    ├── replay_symbol.py
    └── scan_universe.py
```

---

## 5. Domain model

Use typed domain models. Prefer immutable or effectively immutable Pydantic models where practical.

### 5.1 Candle

Required fields:

```python
class Candle(BaseModel):
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal | None = None
    trades: int | None = None
    is_closed: bool = True
```

Rules:

- timestamps must be timezone-aware and normalized to UTC;
- only closed candles may be used for confirmed detection;
- price values should use `Decimal` in persisted domain records;
- NumPy float arrays may be used internally for indicator calculation.

### 5.2 Swing

```python
class SwingPoint(BaseModel):
    id: UUID
    symbol: str
    timeframe: str
    side: Literal["high", "low"]
    formed_at: datetime
    known_at: datetime
    price: Decimal
    atr_at_formation: Decimal
    confirmation_move_atr: Decimal
    status: Literal["confirmed", "invalidated"]
```

Critical distinction:

- `formed_at`: candle where the extreme occurred;
- `known_at`: candle close where the algorithm had enough information to confirm it.

All downstream logic must use `known_at` for causality.

### 5.3 FVG

```python
class FairValueGap(BaseModel):
    id: UUID
    symbol: str
    timeframe: str
    side: Literal["bullish", "bearish"]
    formed_at: datetime
    known_at: datetime
    lower: Decimal
    upper: Decimal
    midpoint: Decimal
    size: Decimal
    size_atr: Decimal
    source_candle_time: datetime
    displacement_score: float
    status: Literal[
        "active",
        "partially_filled",
        "fully_filled",
        "invalidated",
        "expired",
    ]
    fill_ratio: float
```

### 5.4 D1 setup

```python
class D1Setup(BaseModel):
    id: UUID
    symbol: str
    side: Literal["long", "short"]
    formed_at: datetime
    known_at: datetime
    fvg_id: UUID
    status: Literal[
        "candidate",
        "active",
        "h4_touched",
        "h4_reacting",
        "confirmed",
        "invalidated",
        "expired",
    ]
    high_context: str | None
    context_score: float
    displacement_score: float
    structure_break: bool
    structure_break_level: Decimal | None
    external_liquidity_price: Decimal | None
    external_liquidity_remained: bool | None
    invalidation_price: Decimal
    expires_at: datetime | None
```

### 5.5 H4 reaction

```python
class H4Reaction(BaseModel):
    id: UUID
    setup_id: UUID
    touch_at: datetime
    first_reaction_at: datetime | None
    confirmed_at: datetime | None
    penetration_ratio: float
    max_penetration_ratio: float
    close_back_outside_zone: bool
    displacement_score: float
    structure_break: bool
    created_h4_fvg: bool
    reaction_score: float
    status: Literal[
        "touched",
        "early",
        "confirmed",
        "failed",
        "invalidated",
    ]
```

---

## 6. Data acquisition

### 6.1 Binance REST client

Implement official Binance USDⓈ-M perpetual kline retrieval.

Requirements:

- fetch D1 and H4 candles;
- support pagination;
- retry transient failures;
- rate-limit requests;
- validate chronological ordering;
- remove duplicate candles;
- detect missing intervals;
- persist raw candle data locally;
- allow an offline replay without calling Binance again.

CLI example:

```bash
python -m htf_scanner download \
  --symbol JTOUSDT \
  --timeframes 1d,4h \
  --start 2025-01-01 \
  --end 2026-08-01
```

### 6.2 Data storage

Use SQLite in the first version.

Tables:

- `candles`
- `swings`
- `fvgs`
- `d1_setups`
- `h4_reactions`
- `setup_events`
- `setup_outcomes`
- `scanner_runs`

Create unique indexes on:

```text
(symbol, timeframe, open_time)
```

and stable identifiers for detected objects so re-running the same interval does not create duplicates.

### 6.3 Timeframe consistency

Prefer native Binance D1 and H4 candles.

Add a validation utility that confirms H4 candles align with UTC exchange boundaries.

If resampling is ever used, document and test boundary behavior explicitly.

---

## 7. Indicator calculations

### 7.1 ATR

Implement Wilder ATR.

Default period:

```yaml
atr_period: 14
```

The detector must not emit setup candidates until enough warm-up data exists.

### 7.2 Candle features

For each candle calculate:

```text
range = high - low
body = abs(close - open)
upper_wick = high - max(open, close)
lower_wick = min(open, close) - low
body_ratio = body / range
body_atr = body / ATR
range_atr = range / ATR
close_location = (close - low) / range
```

For bearish movement, also derive:

```text
bearish_close_strength = 1 - close_location
```

Handle zero-range candles safely.

### 7.3 Multi-candle impulse features

A displacement may consist of one or several candles.

Calculate for configurable windows of 1 to 3 candles:

- net directional move / ATR;
- total body / ATR;
- directional efficiency;
- overlap ratio;
- retracement inside the impulse;
- close location of the final candle;
- whether the sequence created an FVG;
- whether it broke structure.

---

## 8. Causal swing detection

Do not use classic symmetric pivots as the primary production detector.

Implement an ATR-based causal zigzag.

### 8.1 Basic algorithm

Maintain:

- current direction;
- current candidate extreme;
- extreme timestamp;
- ATR at extreme;
- confirmation threshold.

Example bearish confirmation of a swing high:

```text
1. Track the highest high while price advances.
2. Confirm the swing high only after price declines by X × ATR from that extreme.
3. Set formed_at to the extreme candle.
4. Set known_at to the candle where the decline threshold is first satisfied.
```

Initial configuration:

```yaml
swings:
  reversal_atr: 1.0
  minimum_bars_between_swings: 2
  use_close_for_confirmation: false
```

### 8.2 Required tests

Test:

- no future candle access;
- correct formed and known timestamps;
- stable results when replayed incrementally;
- identical results between batch replay and candle-by-candle replay;
- behavior during gaps and large volatile candles.

---

## 9. Market structure model

The structure engine must expose, at each candle close:

- last confirmed swing high;
- previous confirmed swing high;
- last confirmed swing low;
- previous confirmed swing low;
- persistent external high/low;
- internal structure levels;
- protected high/low and active structural leg;
- causal internal-to-external promotion events;
- last bullish or bearish break;
- whether a structural level has been accepted beyond.

### 9.1 Break definition

Support configurable modes:

```yaml
structure:
  break_mode: close
  minimum_break_atr: 0.05
```

Possible values:

- `wick`
- `close`
- `close_plus_buffer`

Default to `close_plus_buffer` for robust testing.

### 9.2 Acceptance beyond a level

Record:

- maximum excursion beyond the level;
- number of closes beyond the level;
- total bars accepted beyond;
- whether price returned below or above within N bars.

This is needed to distinguish a liquidity raid from genuine acceptance.

---

## 10. Liquidity and structural high context

Liquidity raid must not be mandatory.

Every D1 setup candidate should be classified by context.

### 10.1 Context classes

For bearish setups:

```text
LIQUIDITY_SWEEP
FAILED_CONTINUATION_HIGH
UNSWEPT_EXTERNAL_LIQUIDITY
SWEEP_AND_FAILED_CONTINUATION
ACCEPTED_BREAKOUT
NO_CLEAR_CONTEXT
```

Bullish equivalents must be implemented symmetrically.

### 10.2 Liquidity sweep

A bearish sweep candidate exists when:

- price trades above a known structural high;
- breakout distance exceeds a configurable minimum;
- the market fails to establish acceptance above;
- price closes back below the level within a configured number of D1 candles.

Example configuration:

```yaml
liquidity:
  minimum_sweep_atr: 0.02
  maximum_sweep_atr: 1.5
  max_acceptance_closes: 1
  return_window_bars: 3
```

### 10.3 Failed continuation high

This is a first-class context type and must not be treated as an inferior fallback.

For bearish setups, detect a failed continuation high only when:

- a prior confirmed external or significant swing high exists;
- an internal swing low forms after the external high;
- a later confirmed high is the explicit continuation attempt;
- the new attempt fails to establish strong acceptance above the previous high;
- the attempt may remain below the prior high or only marginally exceed it;
- bearish displacement starts after the attempt;
- that displacement or its causal continuation breaks the explicit internal swing low by close;
- the same impulse creates a linked bearish FVG.

The configured distance and follow-up windows are soft normalization thresholds. Exceeding
either produces a bounded score penalty and is not a hard rejection when the sequence remains
structurally complete.

Record features instead of using only a binary rule:

```text
distance_to_previous_high_atr
break_above_previous_high_atr
number_of_closes_above_previous_high
maximum_acceptance_above_atr
pullback_depth_before_attempt_atr
bars_between_highs
bars_from_second_high_to_displacement
second_high_relative_strength
displacement_after_high_score
```

Initial classification suggestion:

```text
If second high remains below prior high by <= threshold
and bearish displacement follows within N bars:
    FAILED_CONTINUATION_HIGH
```

Do not overfit the thresholds to JTOUSDT.

### 10.4 Context scoring

Generate a score from independent components:

```text
structural significance
failed acceptance
proximity to external liquidity
quality of bearish displacement
internal structure break
FVG quality
```

Store both:

- total score;
- component values.

---

## 11. D1 displacement detection

Implement a configurable displacement detector.

### 11.1 Candidate features

For a bearish displacement:

- body ATR;
- range ATR;
- body-to-range ratio;
- close position near candle low;
- net move across 1–3 candles;
- directional efficiency;
- structural break;
- FVG creation;
- distance from preceding structural high;
- immediate follow-through.

### 11.2 Initial score

Example only:

```text
+1.0 body_atr >= 0.8
+1.0 range_atr >= 1.2
+1.0 body_ratio >= 0.6
+1.0 close_location <= 0.30
+1.5 breaks internal swing low
+1.0 creates D1 FVG
+0.5 next candle does not retrace more than 50%
```

The implementation must make all thresholds configurable.

Do not hardcode “displacement = one large candle”.

### 11.3 Output

```python
class DisplacementResult(BaseModel):
    side: str
    start_time: datetime
    end_time: datetime
    score: float
    body_atr: float
    range_atr: float
    efficiency: float
    structure_break: bool
    created_fvg: bool
    component_scores: dict[str, float]
```

---

## 12. D1 FVG detection

### 12.1 Three-candle definition

Bearish FVG at candle `i`:

```python
high[i] < low[i - 2]
```

Zone:

```python
lower = high[i]
upper = low[i - 2]
```

Bullish FVG:

```python
low[i] > high[i - 2]
```

Zone:

```python
lower = high[i - 2]
upper = low[i]
```

### 12.2 FVG qualification

A raw FVG becomes a qualified D1 FVG candidate based on:

- size relative to ATR;
- displacement score;
- structure break;
- location relative to recent range;
- overlap with prior FVGs;
- whether it is an origin or continuation imbalance;
- age and fill state.

Initial configuration:

```yaml
fvg:
  minimum_size_atr: 0.08
  maximum_size_atr: 5.0
  merge_overlapping: false
  expire_after_d1_bars: 90
  invalidation_mode: close_through_far_edge
```

### 12.3 Fill state

For a bearish FVG, calculate fill from the lower boundary toward the upper boundary.

Record:

- first touch;
- first 25% fill;
- midpoint fill;
- 75% fill;
- full fill;
- invalidation.

Historical events must preserve the first timestamp for each milestone.

---

## 13. D1 setup detector

A D1 setup is not every FVG.

### 13.1 Candidate creation

Confirm a bearish D1 setup only when:

- a qualified bearish D1 FVG forms;
- displacement score meets minimum threshold;
- there is a valid structural context;
- a close breaks the relevant internal structure level;
- the displacement, break, and same-direction FVG belong to one causal impulse;
- context is a liquidity sweep, failed continuation, or their combination.

`UNSWEPT_EXTERNAL_LIQUIDITY` is a feature, not a sufficient reversal trigger. Accepted breakout
and no-clear context block confirmation. Mandatory components are validated before scoring.

Example configuration:

```yaml
d1_setup:
  minimum_displacement_score: 3.0
  minimum_context_score: 1.5
  require_structure_break: true
  structure_break_max_lag_bars: 1
  max_setup_age_bars: 90
```

### 13.2 State machine

```text
CANDIDATE
  -> CONFIRMED
  -> ACTIVE

An active setup may transition to:
  -> INVALIDATED
  -> EXPIRED
```

### 13.3 Activation

A setup becomes `ACTIVE` only after the D1 candle that formed and confirmed the FVG is closed.

### 13.4 Invalidation

For bearish setups, support:

- D1 close above the far edge of the FVG;
- close above the setup origin high;
- structural invalidation level breach;
- explicit configured maximum fill;
- expiry by age.

The selected invalidation mode must be stored on the setup record.

---

## 14. H4 touch and reaction detection

### 14.1 H4 touch

For a bearish D1 FVG:

```python
touched = h4.high >= fvg.lower and h4.low <= fvg.upper
```

For each touch, calculate:

```text
entry_depth
penetration_ratio
close_location_inside_zone
close_back_below_lower_boundary
wick_rejection_ratio
time_since_d1_setup
number_of_prior_h4_touches
```

Penetration ratio for bearish FVG:

```python
penetration = (
    min(h4.high, fvg.upper) - fvg.lower
) / (fvg.upper - fvg.lower)
```

Clamp to `[0, 1]`.

### 14.2 Reaction window

After first touch, evaluate a configurable H4 reaction window.

```yaml
h4_reaction:
  evaluation_window_bars: 6
  confirmation_window_bars: 12
```

### 14.3 Reaction components

For bearish reaction:

- closes back below the lower edge of the D1 FVG;
- bearish H4 candle body ATR;
- bearish H4 range ATR;
- close near low;
- rejection wick from inside D1 FVG;
- net move away from zone;
- break of H4 internal swing low;
- creation of H4 bearish FVG;
- follow-through during the next N bars;
- absence of immediate reclaim.

### 14.4 H4 reaction score

Example scoring:

```text
+1.0 touched D1 FVG
+1.0 closed back below lower edge
+1.0 bearish body_atr >= threshold
+1.0 close near candle low
+1.5 broke H4 internal swing low
+1.0 created H4 bearish FVG
+0.5 next candle followed through
-1.0 closed above FVG midpoint
-2.0 closed above far edge
```

Classify:

```yaml
h4_reaction:
  early_score: 2.0
  confirmed_score: 4.0
```

### 14.5 Reaction failure

Mark as failed when:

- H4 closes through the far edge;
- price remains accepted inside or above the zone beyond N bars;
- no meaningful move away occurs within the reaction window;
- the D1 setup invalidates.

Do not assume every touch must produce an immediate rejection. Preserve raw features for later analysis.

---

## 15. Historical replay engine

### 15.1 Core principle

The replay engine is authoritative.

Even if vectorized feature calculations are used for speed, setup state transitions must be applied in chronological order.

### 15.2 Replay sequence

At each H4 close:

1. append the newly closed H4 candle;
2. determine whether a D1 candle has just closed;
3. if yes, update D1 indicators, swings, structure, FVGs, and D1 setups;
4. update all active D1 setups with the latest H4 candle;
5. detect touch, reaction, invalidation, or expiry events;
6. persist state changes;
7. emit deterministic event records.

### 15.3 Event log

Each event should include:

```python
class SetupEvent(BaseModel):
    event_id: UUID
    setup_id: UUID
    event_type: str
    event_time: datetime
    known_at: datetime
    payload: dict
    scanner_version: str
    config_hash: str
```

Event examples:

```text
D1_FVG_CREATED
D1_SETUP_CANDIDATE_CREATED
D1_SETUP_ACTIVATED
H4_ZONE_TOUCHED
H4_EARLY_REACTION
H4_REACTION_CONFIRMED
D1_FVG_MIDPOINT_FILLED
SETUP_INVALIDATED
SETUP_EXPIRED
OUTCOME_EVALUATED
```

### 15.4 Determinism

Given:

- same candle dataset;
- same config;
- same scanner version;

The event log must be identical across runs.

---

## 16. Outcome analysis

The detector must separate setup detection from outcome labeling.

### 16.1 Outcome anchor

Evaluate outcomes from:

- first H4 touch;
- first early reaction;
- confirmed H4 reaction.

Store all three where available.

### 16.2 Metrics

For bearish setups, compute over configurable horizons:

```text
MFE in price percent
MAE in price percent
MFE in ATR
MAE in ATR
bars to MFE
bars to MAE
whether prior swing low was broken
whether external sell-side liquidity was reached
whether D1 FVG invalidated first
maximum favorable excursion before invalidation
maximum adverse excursion before favorable threshold
```

Default horizons:

```yaml
outcomes:
  h4_horizons: [6, 12, 24, 42]
  favorable_atr_thresholds: [1.0, 2.0, 3.0]
  adverse_atr_thresholds: [0.5, 1.0, 2.0]
```

### 16.3 Labels

Create multiple labels rather than one arbitrary win/loss field:

```text
reached_1_atr_before_1_atr_adverse
reached_2_atr_before_invalidation
broke_previous_h4_low
broke_previous_d1_low
continued_for_12_h4_bars
zone_invalidated
```

---

## 17. Reporting

### 17.1 Per-setup chart

Generate a chart with:

- D1 price panel;
- D1 FVG rectangle;
- structural highs and lows;
- liquidity or failed-continuation annotations;
- D1 displacement annotation;
- H4 inset or separate H4 chart;
- H4 touch candle;
- H4 reaction candles;
- invalidation level;
- outcome path.

Chart must include timestamps and exact price boundaries.

### 17.2 Event table

Export CSV and JSON with one row per setup.

Minimum columns:

```text
symbol
side
d1_setup_formed_at
d1_setup_known_at
d1_fvg_lower
d1_fvg_upper
d1_fvg_size_atr
high_context
external_liquidity_remained
context_score
d1_displacement_score
structure_break
h4_touch_at
h4_penetration_ratio
h4_reaction_score
h4_reaction_confirmed_at
status
mfe_12h4_atr
mae_12h4_atr
invalidated
```

### 17.3 Summary report

Produce:

- setup count;
- setup count by context class;
- confirmation rate;
- median and mean H4 reaction score;
- MFE/MAE distributions;
- result by FVG penetration bucket;
- result by liquidity-context class;
- result by displacement-score bucket;
- result with and without D1 structure break;
- setup age at first touch.

---

## 18. CLI commands

Implement with Typer or argparse.

### Download

```bash
htf-scanner download \
  --symbols JTOUSDT \
  --start 2025-01-01 \
  --end 2026-08-01
```

### Replay one symbol

```bash
htf-scanner replay \
  --symbol JTOUSDT \
  --start 2025-01-01 \
  --end 2026-08-01 \
  --config config.yaml
```

### Scan universe

```bash
htf-scanner scan \
  --universe binance-usdt-perpetual \
  --minimum-history-days 500
```

### Report

```bash
htf-scanner report \
  --run-id <uuid> \
  --format html
```

### Inspect setup

```bash
htf-scanner inspect \
  --setup-id <uuid> \
  --chart
```

---

## 19. Configuration

Create `config.example.yaml`.

```yaml
scanner:
  version: "0.1.0"
  timezone: "UTC"
  confirmed_candles_only: true

atr:
  period: 14

swings:
  reversal_atr: 1.0
  minimum_bars_between_swings: 2
  use_close_for_confirmation: false

structure:
  break_mode: "close_plus_buffer"
  minimum_break_atr: 0.05

liquidity:
  minimum_sweep_atr: 0.02
  maximum_sweep_atr: 1.5
  max_acceptance_closes: 1
  return_window_bars: 3
  failed_continuation_max_distance_atr: 0.5
  failed_continuation_followup_bars: 5
  distance_penalty_max: 1.0
  timing_penalty_max: 1.0

fvg:
  minimum_size_atr: 0.08
  maximum_size_atr: 5.0
  expire_after_d1_bars: 90
  invalidation_mode: "close_through_far_edge"

 displacement:
  minimum_body_atr: 0.8
  minimum_range_atr: 1.2
  minimum_body_ratio: 0.6
  bearish_max_close_location: 0.30
  bullish_min_close_location: 0.70
  maximum_sequence_bars: 3

 d1_setup:
  minimum_displacement_score: 3.0
  minimum_context_score: 1.5
  require_structure_break: true
  structure_break_max_lag_bars: 1
  max_setup_age_bars: 90

 h4_reaction:
  evaluation_window_bars: 6
  confirmation_window_bars: 12
  early_score: 2.0
  confirmed_score: 4.0
  require_close_back_outside_zone: false

 outcomes:
  h4_horizons: [6, 12, 24, 42]
  favorable_atr_thresholds: [1.0, 2.0, 3.0]
  adverse_atr_thresholds: [0.5, 1.0, 2.0]

 storage:
  database_url: "sqlite:///data/htf_scanner.db"
  candle_cache_dir: "data/candles"

 reports:
  output_dir: "reports"
  chart_format: "png"
```

Fix YAML indentation and validate config through Pydantic settings models.

---

## 20. JTOUSDT regression test

### 20.1 Fixture data

Store an immutable candle fixture covering enough history before and after the July 2026 setup.

Use at least:

- 180 D1 candles before the setup;
- all corresponding H4 candles;
- sufficient candles after the reaction for outcome evaluation.

Do not make the regression test depend on a live API call.

### 20.2 Assertions

The test should assert robust conditions, not exact fragile values.

Example:

```python
def test_jto_july_2026_bearish_htf_setup_is_detected():
    result = run_fixture_replay("JTOUSDT", "jto_2026_07")

    setups = [
        s for s in result.setups
        if s.side == "short"
        and date(2026, 6, 1) <= s.formed_at.date() <= date(2026, 7, 31)
    ]

    assert setups, "Expected at least one bearish D1 setup"

    setup = select_best_matching_setup(setups)

    assert setup.status in {"h4_touched", "h4_reacting", "confirmed"}
    assert setup.fvg.lower < Decimal("0.68")
    assert setup.fvg.upper > Decimal("0.65")
    assert setup.displacement_score >= configured_minimum

    reaction = result.reactions_by_setup[setup.id]

    assert reaction.touch_at is not None
    assert 0.0 <= reaction.penetration_ratio <= 1.0
    assert reaction.reaction_score >= configured_early_score
    assert reaction.max_favorable_excursion_atr > 0
```

### 20.3 Expected qualitative classification

The test output should show a context similar to:

```text
SWEEP_AND_FAILED_CONTINUATION
```

or:

```text
FAILED_CONTINUATION_HIGH
```

The exact classification may evolve, but the detector must preserve the raw features needed to inspect why it classified the setup that way.

### 20.4 Golden report

Generate a chart and JSON record for the JTO case.

Commit them under:

```text
tests/golden/jto_2026_07/
```

Use tolerances for numeric comparisons.

---

## 21. Testing requirements

### 21.1 Unit tests

Cover:

- ATR;
- candle feature calculations;
- bullish and bearish FVG detection;
- FVG fill ratio;
- causal swing confirmation;
- liquidity sweep classification;
- failed continuation classification;
- displacement score;
- H4 penetration ratio;
- H4 reaction score;
- state transitions;
- invalidation and expiry.

### 21.2 Property tests

Where practical, add property tests for:

- FVG boundaries always ordered;
- fill ratio always in `[0, 1]`;
- no event timestamp before its source candle close;
- no `known_at` earlier than `formed_at`;
- no setup transitions backward;
- deterministic replay.

### 21.3 Integration tests

Cover:

- Binance pagination using mocked responses;
- persistence roundtrip;
- historical replay over a small fixture;
- report generation;
- idempotent reruns.

### 21.4 Regression tests

At minimum:

- JTOUSDT July 2026 bearish case;
- one bullish mirrored synthetic case;
- one invalidated FVG case;
- one liquidity sweep case;
- one unswept-liquidity failed continuation case;
- one no-reaction H4 touch case.

### 21.5 Coverage

Target:

```text
>= 85% overall
>= 95% for detector and state-machine modules
```

---

## 22. Logging and observability

Use structured logs.

Each detector decision should optionally expose a trace record:

```json
{
  "symbol": "JTOUSDT",
  "timeframe": "1d",
  "timestamp": "2026-07-10T00:00:00Z",
  "detector": "d1_setup",
  "decision": "candidate_created",
  "scores": {
    "context": 2.8,
    "displacement": 4.2,
    "fvg": 1.1
  },
  "reasons": [
    "failed_continuation_high",
    "bearish_fvg_created",
    "internal_low_broken"
  ]
}
```

Support:

```bash
--explain
```

This flag should produce a detailed decision trace for one symbol or setup.

---

## 23. Performance requirements

First version performance target:

- scan 500 symbols;
- approximately 2 years of D1 and H4 data;
- complete on a modern desktop within a practical offline batch window;
- no need for microsecond-level optimization.

Priorities:

1. correctness;
2. causality;
3. reproducibility;
4. explainability;
5. performance.

Use vectorized calculations where safe, but do not compromise state-machine correctness.

---

## 24. Non-repainting and causality rules

These rules are mandatory:

1. Use only closed candles.
2. Preserve `formed_at` and `known_at` separately.
3. Never reference future bars in production detection logic.
4. Never use centered rolling calculations.
5. A setup may only become active after all required source candles are closed.
6. Batch and incremental replay must produce identical events.
7. Any visual chart may show the swing at `formed_at`, but the report must also display `known_at`.
8. Outcome calculation may use future candles, but it must be a separate post-detection stage.

---

## 25. Implementation phases

### Phase 1 — Project foundation

Deliverables:

- project scaffold;
- pyproject configuration;
- linting and typing;
- config loading;
- domain models;
- SQLite setup;
- Binance downloader;
- candle caching;
- basic CLI.

Acceptance criteria:

- JTOUSDT D1 and H4 history can be downloaded and stored;
- rerun is idempotent;
- tests pass.

### Phase 2 — Core market primitives

Deliverables:

- ATR;
- candle features;
- causal swings;
- market structure;
- raw FVG detector;
- FVG fill state.

Acceptance criteria:

- no-lookahead tests pass;
- batch and incremental calculations match;
- visual debug chart correctly marks swings and FVGs.

### Phase 3 — D1 context and setup detection

Deliverables:

- liquidity sweep classifier;
- failed continuation high/low classifier;
- displacement detector;
- context scoring;
- D1 setup state creation;
- invalidation and expiry.

Acceptance criteria:

- synthetic cases are correctly classified;
- raw feature records are exported;
- detector decisions are explainable.

### Phase 4 — H4 reaction engine

Deliverables:

- D1 FVG touch detection;
- penetration measurement;
- H4 reaction score;
- H4 structure break detection;
- H4 FVG creation flag;
- reaction state transitions.

Acceptance criteria:

- no-reaction and valid-reaction fixtures are distinguished;
- reaction event log is deterministic.

### Phase 5 — Historical replay and analytics

Deliverables:

- chronological replay engine;
- event persistence;
- setup outcome calculation;
- CSV and JSON export;
- summary statistics;
- charts.

Acceptance criteria:

- one command produces a full replay report for JTOUSDT;
- outcome metrics are separated from detection.

### Phase 6 — JTO regression validation

Deliverables:

- immutable JTO fixture;
- regression test;
- golden chart;
- golden JSON report;
- explanatory markdown report.

Acceptance criteria:

- detector finds the JTO bearish HTF candidate;
- detector records H4 touch and bearish reaction;
- result is stable across reruns.

### Phase 7 — Universe scan

Deliverables:

- Binance perpetual universe loader;
- batch scan command;
- ranking report;
- aggregated statistics.

Acceptance criteria:

- scan can resume after interruption;
- failed symbols do not abort the full run;
- run metadata and configuration hash are stored.

### Phase 8 — Live-ready abstraction

Deliverables:

- data source interface;
- historical source implementation;
- placeholder WebSocket source interface;
- detector snapshot persistence;
- recovery from last processed candle.

No actual live alerting is required yet.

Acceptance criteria:

- detector logic has no dependency on REST-specific code;
- state can be serialized and restored.

---

## 26. Definition of done for version 0.1

Version 0.1 is complete when:

- historical D1 and H4 Binance perpetual data can be downloaded and cached;
- the scanner detects qualified D1 FVG-based HTF candidates;
- liquidity sweep is optional rather than mandatory;
- failed continuation highs and lows are first-class contexts;
- the detector runs causally without look-ahead;
- active D1 zones are tracked over time;
- H4 touches and reactions are scored;
- event history is persisted;
- setup outcomes are calculated separately;
- JTOUSDT regression case is detected;
- charts and machine-readable reports are generated;
- all thresholds are configurable;
- the implementation is typed, tested, and documented;
- the same detector can later be fed closed live candles.

---

## 27. Explicit non-goals for version 0.1

Do not implement:

- 15m or 5m entry logic;
- LTF MSS or FVG entry detection;
- stop-loss or take-profit recommendation;
- automatic trade execution;
- leverage or position sizing;
- order book analysis;
- open interest;
- funding rate;
- CVD;
- TWAP integration;
- Telegram alerts;
- machine learning;
- parameter optimization;
- automated strategy profitability claims.

---

## 28. Engineering rules for Codex

1. Implement the smallest complete vertical slice first.
2. Do not hide detector logic inside notebooks.
3. Keep formulas and thresholds centralized in configuration.
4. Every state transition must produce a testable event.
5. Every classification must retain raw features and component scores.
6. Avoid boolean-only black-box decisions.
7. Add type hints to all public functions.
8. Use explicit domain names rather than generic names such as `data`, `item`, or `value`.
9. Prefer pure functions for calculations.
10. Keep persistence, exchange access, detection, and reporting separated.
11. Do not silently fill missing candles.
12. Fail loudly on invalid or unordered market data.
13. Make replays deterministic.
14. Do not optimize thresholds specifically for JTOUSDT.
15. Document any interpretation choice that is not objectively defined.

---

## 29. First Codex task

Implement a vertical slice for one symbol.

Required scope:

1. Create the Python project.
2. Add configuration models.
3. Download and cache JTOUSDT D1 and H4 candles.
4. Calculate ATR and candle features.
5. Detect raw D1 bearish and bullish FVGs.
6. Track FVG fill status.
7. Generate a chart showing D1 candles and FVG zones.
8. Add unit tests.
9. Add a CLI command:

```bash
htf-scanner inspect-fvg \
  --symbol JTOUSDT \
  --start 2025-01-01 \
  --end 2026-08-01
```

10. Produce:

```text
reports/JTOUSDT/d1_fvgs.csv
reports/JTOUSDT/d1_fvgs.png
```

Do not start D1 setup classification until this vertical slice is complete and tested.

---

## 30. Second Codex task

After the first task is accepted:

1. Implement causal ATR zigzag swings.
2. Implement market structure state.
3. Implement displacement scoring.
4. Implement liquidity-sweep and failed-continuation context features.
5. Create D1 setup candidates.
6. Export an explainable setup report for JTOUSDT.
7. Add synthetic and JTO regression tests.

---

## 31. Third Codex task

After the second task is accepted:

1. Implement H4 touch tracking.
2. Implement H4 reaction scoring.
3. Extend the existing D1 setup state machine with H4 interaction states.
4. Add outcome analysis.
5. Generate the final JTO case report.
6. Add batch historical scanning.

---

## 32. Expected final JTO report format

```text
Symbol: JTOUSDT
Side: SHORT
D1 setup status: CONFIRMED
D1 FVG: 0.xxxx - 0.xxxx
D1 FVG formed at: <timestamp>
D1 setup known at: <timestamp>
Context class: FAILED_CONTINUATION_HIGH / SWEEP_AND_FAILED_CONTINUATION
External liquidity remained: true/false
D1 displacement score: <value>
D1 structure break: true/false
H4 first touch: <timestamp>
H4 penetration: <percentage>
H4 reaction score: <value>
H4 reaction confirmed at: <timestamp>
MFE after confirmation: <ATR and percent>
MAE after confirmation: <ATR and percent>
Final setup outcome: <structured labels>
```

The report must include an explanation of every score component.
