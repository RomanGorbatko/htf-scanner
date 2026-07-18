# Fourth Codex task: Production Hourly Scanner, Incremental State, Telegram Alerts

## Goal

Do NOT work on execution, entries, stop-losses, backtesting or trading.

Transform the existing D1/H4 detector into a production monitoring service.

Pipeline:

Scheduler
→ Universe discovery
→ Fetch newly closed candles
→ Data validation
→ Incremental D1/H4 update
→ Detect new events
→ Deduplicate alerts
→ Telegram notification
→ Persist state
→ Diagnostics

## 1. Incremental processing

- Never replay full history every hour.
- Restore detector state from persistence.
- Download only missing closed candles.
- Process only newly closed candles.
- Persist updated state.
- Full replay only for initialization, rebuild or config changes.
- Incremental and full replay must produce identical results.



## Architecture requirement: MarketDataProvider abstraction

Do NOT couple the scanner directly to a specific exchange (Binance, Hyperliquid, Bybit, etc.).

Introduce an abstract `MarketDataProvider` interface that encapsulates all market-data access.

The detector, scanner, scheduler and alerting system must depend only on this abstraction.

The interface should expose operations similar to:

- discover_markets()
- fetch_ohlcv()
- fetch_latest_closed_candle()
- server_time()
- exchange_metadata()

Implement the current exchange as one concrete provider (for example `BinanceMarketDataProvider`), but design the architecture so another provider (Hyperliquid, OKX, Bybit, offline CSV, etc.) can be added without changing detector logic.

The detector must never contain exchange-specific code.

Universe discovery, candle downloading, timestamp normalization and exchange-specific quirks belong exclusively inside the provider implementation.

The long-term goal is that replacing the data source requires only changing configuration:

```yaml
market_data:
  provider: binance
```

instead of modifying detector code.

This abstraction is a mandatory architectural requirement of this iteration.


## 2. Universe discovery

Automatically discover perpetual USDT markets.

Support:
- active only
- minimum history
- minimum volume
- include/exclude lists

Persist universe snapshot for every run.

## 3. Candle validation

Reject unfinished candles.

Validate:
- duplicates
- missing intervals
- unordered timestamps
- invalid OHLC
- UTC alignment

Generate diagnostics instead of silently skipping.

## 4. Persistent state

Persist:
- processed candle positions
- active D1 structures
- liquidity interactions
- setups
- H4 reactions
- transitions
- config hash
- last successful run

Restart must resume processing without rebuilding history.

## 5. Event model

Immutable events:

- D1_SETUP_ACTIVE
- D1_SETUP_INVALIDATED
- H4_ZONE_TOUCHED
- H4_EARLY_REACTION
- H4_REACTION_CONFIRMED
- H4_REACTION_INVALIDATED
- H4_REACTION_EXPIRED

Each event must have deterministic ID.

## 6. Alert deduplication

Never send the same alert twice.

Deduplication key:
- event type
- entity ID
- transition
- config hash

Store delivery status.

## 7. Telegram

Implement:
- retries
- exponential backoff
- timeout handling
- Markdown escaping
- optional chart attachment
- fallback to text
- delivery logging

Alert should include:
- symbol
- side
- D1 context
- score
- FVG
- invalidation
- timestamps
- chart

## 8. Scheduler

Detector must remain scheduler agnostic.

Provide:

scan-live-once

Target deployment:

- systemd service
- systemd timer

Prevent overlapping runs.

## 9. Batch isolation

One broken symbol must not stop the scan.

Per-symbol statuses:
- SUCCESS
- NO_NEW_DATA
- FETCH_ERROR
- DATA_ERROR
- DETECTOR_ERROR
- ALERT_ERROR

## 10. Reports

Generate:
- run_manifest.json
- universe_snapshot.csv
- run_summary.csv
- symbol_summary.csv
- alerts_sent.csv
- alerts_pending.csv
- data_quality.csv
- runtime_metrics.csv

## 11. Metrics

Track:
- symbols scanned
- new D1 setups
- new H4 reactions
- alerts sent
- alerts failed
- fetch time
- detection time
- persistence time
- total runtime

## 12. Tests

Cover:
- incremental == full replay
- restart recovery
- duplicate alert prevention
- scheduler overlap protection
- universe changes
- partial fetch failures
- Telegram retry
- deterministic IDs
- batch isolation

## 13. Configuration

Add sections:
- scheduler
- exchange
- universe
- telegram
- alerts
- retry
- runtime

All values must participate in config hash.

## Definition of Done

Complete only if:

- hourly incremental scan works
- no duplicated alerts
- restart resumes state
- deterministic replay preserved
- D1/H4 detection unchanged
- Telegram delivery reliable
- systemd deployment documented

## Final report

Include:
1. modified files
2. architecture changes
3. persistence schema
4. incremental algorithm
5. alert model
6. Telegram implementation
7. scheduler deployment
8. test results
9. replay verification
10. known limitations
