# HTF Setup Scanner

Causal historical scanner for D1 higher-timeframe setups on Binance USD-M perpetual markets.
It preserves FVGs as primitives and combines them with confirmed swings, persistent market
structure, displacement, liquidity context, and explicit setup state transitions.

## Setup

```bash
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e '.[dev]'
.venv/bin/htf-scanner --help
cp config.example.yaml config.yaml
```

## Inspect FVGs

```bash
./venv/bin/htf-scanner inspect-fvg \
  --symbol JTOUSDT \
  --start 2025-01-01 \
  --end 2026-08-01
```

The command normalizes a future end date to the current time and only accepts closed candles.
It creates `reports/JTOUSDT/d1_fvgs.csv` and `reports/JTOUSDT/d1_fvgs.png`. Add `--offline`
to analyze previously cached candles without calling Binance.

## Detect D1 setups

```bash
./venv/bin/htf-scanner detect-d1-setups --symbol JTOUSDT --offline
```

This command runs the causal ATR ZigZag, incremental close-based structure engine,
displacement scoring, liquidity-context classification, and HTF setup detector. It writes
CSV files for swings, structure breaks/promotions, liquidity interactions/sequences, raw and
canonical setup candidates, merge diagnostics, setups, state transitions, and rejected
candidates plus `d1_setups.png` under the symbol report directory. Omit `--offline` to refresh
native D1 candles from Binance first.

## Causal D1 rules

- A swing is formed at the extreme candle but becomes usable only at `known_at`, when price has
  reversed by `reversal_atr * ATR`. Batch input is sorted before ATR calculation; incremental
  and batch output are identical.
- The latest confirmed high/low are internal levels. The first confirmed level of each side
  bootstraps a persistent external boundary. Minor swings do not replace it. A close through
  an internal low promotes the latest confirmed high to external/protected high; bullish logic
  is symmetric. With-leg breaks are BOS, counter-leg internal breaks are MSS, and counter-leg
  external breaks are CHoCH.
- External liquidity interactions are separate causal events: `TOUCHED`, `SWEPT`, `REJECTED`,
  `ACCEPTED_BEYOND`, `RECLAIMED`, and `INVALIDATED`. A sweep does not replace the structural
  external reference, so a later weaker continuation attempt can reuse its sweep history.
- Bearish failed continuation hard gates require an active external high, confirmed retracement
  low, later high attempt, no active accepted breakout, qualified bearish displacement, close
  break of that exact internal low, causal promotion, and a linked bearish FVG. Bullish logic is
  symmetric. Distance, timing, retracement depth, attempt quality, and freshness are soft score
  inputs and cannot reject an otherwise complete sequence.
- Accepted breakout requires configured consecutive closes and ATR excursion beyond the level.
  A later `RECLAIMED` event clears active acceptance; a sweep requires excursion without active
  acceptance and a close back inside.
- A confirmed setup requires one causal impulse containing a qualified displacement, the
  relevant internal close-break, a same-direction FVG, and a sweep or failed-continuation
  context. `UNSWEPT_EXTERNAL_LIQUIDITY`, accepted breakout, and no-clear context cannot trigger
  a setup alone. Hard validation runs before transparent component scoring.
- Setup states follow `CANDIDATE -> CONFIRMED -> ACTIVE`; active setups can become
  `INVALIDATED` or `EXPIRED`. `max_setup_age_bars` is counted by processed D1 bar indices.
- Overlapping single/multi-candle impulses are grouped by structural IDs and linked FVG. One
  canonical candidate is selected by complete linkage, earliest confirmation, score, then the
  shortest/earliest deterministic interval; alternatives are retained as merged diagnostics.

The bundled JTOUSDT fixture confirms one canonical July 2026 bearish setup under generic default
thresholds. A June 26 sweep of the persistent external high is followed by the June 30
retracement, July 2 weaker continuation attempt, July 8-9 bearish displacement/internal break,
and July 9 FVG. Its `0.7248 ATR` distance and 7-bar timing remain visible as score penalties.

## Detect H4 reactions

```bash
./venv/bin/htf-scanner detect-h4-reactions --symbol JTOUSDT --offline
```

The H4 replay ignores candles closed at or before `setup.known_at`. It groups adjacent zone
interactions into touch phases, keeps pre-activation mitigation separate, and requires directional
rejection before `EARLY_REACTION`. Confirmation requires one qualified H4 displacement whose
linked close-based break is an H4 internal swing break in the setup direction. One wick beyond the
zone is not invalidation; acceptance uses configured close count, hold bars, buffer, excursion, and
reclaim window. Expiry is counted in H4 bars.

Use explicit candle files and output directory when the cache layout is not desired:

```bash
./venv/bin/htf-scanner detect-h4-reactions \
  --symbol JTOUSDT \
  --d1-candles data/JTOUSDT_1d.csv \
  --h4-candles data/JTOUSDT_4h.csv \
  --output reports/JTOUSDT
```

The command writes touch phases, raw/rejected/merged candidates, transitions, reactions, outcome
snapshots, target snapshots, causal diagnostics, and `h4_reactions.png`.

## Outcomes and batch scan

```bash
./venv/bin/htf-scanner evaluate-reaction-outcomes --symbol JTOUSDT --offline
./venv/bin/htf-scanner scan-universe --symbols BTCUSDT,ETHUSDT,JTOUSDT
./venv/bin/htf-scanner scan-universe --symbols-file symbols.txt --data-dir data/candles
```

Outcome analytics is downstream-only. For each configured H4 horizon it freezes confirmation close
and ATR, directional MFE/MAE, bars/hours to extrema, labels, and deterministic fixed-ATR or supplied
structural targets. A structural target is eligible only when its `known_at` does not exceed reaction
confirmation. Batch input is normalized to stable symbol order; each symbol is isolated, validated,
and reported without live/WebSocket behavior.

The H4 configuration is split into `h4_swing`, `h4_structure`, `h4_displacement`, `h4_touch`,
`h4_reaction`, and `h4_invalidation`. Analytics and batch thresholds live in
`reaction_outcomes` and `batch_scan`; every field participates in the canonical configuration hash.

## Production hourly scan

Copy `config.production.example.yaml` to `config.production.yaml`, then edit `universe`,
`telegram`, `scheduler`, and `runtime`. Relative data/report paths are resolved from the working
directory. Telegram credentials are read from environment variables and are never stored in YAML
or the database:

```bash
export HTF_TELEGRAM_BOT_TOKEN='...'
export HTF_TELEGRAM_CHAT_ID='...'
```

Validate external dependencies, run the bootstrap, inspect it, then immediately run a second scan:

```bash
.venv/bin/htf-scanner doctor --config config.production.yaml
.venv/bin/htf-scanner scan-live-once --config config.production.yaml
.venv/bin/htf-scanner scan-live-once --config config.production.yaml
```

The first run downloads closed D1/H4 history from `runtime.bootstrap_start` and creates a detector
checkpoint. With the default `alerts.bootstrap_policy: suppress`, it persists historical events
without creating Telegram deliveries. The same policy applies to `--rebuild` and configuration-hash
rebuilds. Later runs restore the checkpoint, request only candles after the last processed close,
and update the detector candle by candle. The second run should report `NO_NEW_DATA` unless a D1/H4
candle closed between runs.

Every run writes `run_manifest.json`, universe/run/symbol summaries, alert delivery ledgers, data
quality diagnostics, and runtime metrics below `reports/live/<run-id>/`. SQLite stores checkpoints,
immutable events, delivery status, universe snapshots, and run status. An atomic process lock exits
with code 75 when another scan is active.

### systemd

Production installation, doctor, first-run validation, exit codes, and recovery procedures are in
[`DEPLOYMENT.md`](DEPLOYMENT.md). The installer creates the service assets but deliberately does not
enable the timer:

```bash
sudo ./deploy/install.sh /home/rg/htf-scanner
# Complete doctor and two manual scans first.
sudo systemctl enable --now htf-scanner.timer
systemctl list-timers htf-scanner.timer
```

Put Telegram variables in `/etc/htf-scanner.env` with permissions readable only by the service
account. The service performs monitoring and notification only; it does not place orders or
calculate entries, stops, leverage, or position size.

## Quality checks

```bash
./venv/bin/pytest --cov
./venv/bin/ruff check .
./venv/bin/mypy src/htf_scanner
```
