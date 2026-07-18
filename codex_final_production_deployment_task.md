# Final Codex task: production hardening and deployment readiness

## Context

The functional goal is fixed and must not be expanded:

- scan all configured active perpetual markets;
- analyze both bullish and bearish D1/H4 setups;
- run once per hour;
- send a Telegram notification when a new configured event appears;
- do not implement execution, entries, stops, targets, portfolio management or live trading.

The detector logic must remain unchanged unless a failing regression test proves that a change is necessary.

This task is the final deployment-readiness pass.

---

## 1. Critical: suppress historical alert flooding during bootstrap and rebuild

The current production scanner bootstraps every symbol from historical candles and receives all historical detector events. Those events must not all be sent to Telegram.

Add an explicit bootstrap alert policy.

Recommended configuration:

```yaml
alerts:
  enabled: true
  bootstrap_policy: "suppress"
  event_types:
    - "D1_SETUP_ACTIVE"
    - "H4_REACTION_CONFIRMED"
```

Supported policies:

- `suppress` — persist historical events and checkpoints, but send no alerts during first initialization or forced/config-triggered rebuild;
- optionally `latest_active_only` — send at most the latest currently active event per symbol after bootstrap;
- never make `send_all` the default.

Requirements:

1. A first production run must build state without flooding Telegram with historical events.
2. `--rebuild` must not resend historical alerts.
3. A config-hash rebuild must not resend historical alerts merely because the dedup key contains a new config hash.
4. The next genuinely new event after bootstrap must be sent normally.
5. Add regression tests covering first bootstrap, manual rebuild and config-change rebuild.

---

## 2. Alert delivery retry lifecycle

The repository already includes both `PENDING` and `FAILED` deliveries in retry selection. Preserve this behavior and make the lifecycle bounded and observable.

Add fields/configuration as needed:

```yaml
alerts:
  maximum_delivery_attempts: 12
  retry_failed_after_minutes: 60
```

Requirements:

- retry `PENDING` and retryable `FAILED` deliveries;
- do not retry before `next_retry_at`;
- stop automatic retries after the configured maximum;
- preserve the final failure and error text for diagnostics;
- a successful retry must change status to `SENT` without creating a duplicate delivery;
- report pending, retryable failed and permanently failed counts separately;
- tests must use a fake sender and no real Telegram calls.

Do not lose an event because the checkpoint was persisted before Telegram delivery.

---

## 3. Provider factory must honor configuration

`scan-live-once` currently constructs `BinanceMarketDataProvider` directly even though configuration contains `market_data.provider`.

Create a provider factory, for example:

```python
create_market_data_provider(config.market_data) -> MarketDataProvider
```

Requirements:

- CLI and production scanner wiring must not import a specific provider directly;
- `market_data.provider: binance` creates `BinanceMarketDataProvider`;
- an unsupported provider must fail fast with a clear configuration error;
- detector and production orchestration remain provider-agnostic;
- add factory tests.

Only Binance must be implemented in this task. Do not add other exchanges.

---

## 4. Complete Python packaging

The deployable project must contain all packaging files at repository root.

Add or verify:

- `pyproject.toml`;
- package metadata;
- console entry point `htf-scanner = htf_scanner.cli:app`;
- Python requirement `>=3.12`;
- runtime dependencies;
- optional `dev` dependencies;
- README installation instructions;
- `.gitignore` for virtualenv, database, state, reports, cache and secrets.

The following must work from a fresh clone:

```bash
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e '.[dev]'
.venv/bin/htf-scanner --help
```

Do not rely on previously generated `.egg-info` files.

---

## 5. Production configuration

Add `config.production.example.yaml` with safe defaults.

It must:

- use absolute-path-friendly or clearly documented relative paths;
- enable closed candles only;
- use Binance perpetual USDT markets;
- default to all active markets;
- keep `maximum_symbols: null`;
- enable Telegram but read secrets only from environment variables;
- default alert types to:
  - `D1_SETUP_ACTIVE`;
  - `H4_REACTION_CONFIRMED`;
- default bootstrap alert policy to `suppress`;
- keep chart attachment disabled by default;
- use SQLite under a persistent `data/` directory;
- write live reports under `reports/live/`.

Never put real bot tokens or chat IDs in YAML.

---

## 6. Deployment assets

Add:

```text
deploy/systemd/htf-scanner.service
deploy/systemd/htf-scanner.timer
deploy/systemd/htf-scanner.env.example
deploy/install.sh
DEPLOYMENT.md
```

### Service requirements

The service should execute one scan and exit:

```bash
/path/to/project/.venv/bin/htf-scanner scan-live-once \
  --config /path/to/project/config.production.yaml
```

Use:

- dedicated non-root user;
- explicit `WorkingDirectory`;
- `EnvironmentFile`;
- `Type=oneshot`;
- reasonable start timeout;
- clean SIGTERM behavior;
- no automatic service restart loop because the timer schedules runs;
- hardening options that do not block required network or filesystem access.

### Timer requirements

Run shortly after each hour, not exactly at the boundary, for example:

```ini
OnCalendar=*-*-* *:05:00
Persistent=true
RandomizedDelaySec=30
```

The application-level process lock must remain enabled.

`install.sh` must not contain secrets and must be idempotent where practical.

---

## 7. Add operational CLI checks

Add a command such as:

```bash
htf-scanner doctor --config config.production.yaml
```

It must validate without running a full scan:

- config parsing;
- supported provider;
- writable database/state/cache/report paths;
- database initialization;
- exchange API connectivity and server time;
- market discovery returns at least one market;
- Telegram credentials exist when Telegram is enabled.

Optionally provide an explicit test message flag:

```bash
htf-scanner doctor --config config.production.yaml --send-telegram-test
```

Never send a Telegram test message by default.

Return non-zero exit status on failure.

---

## 8. First-run workflow

Document and support this exact sequence:

1. Install package.
2. Create production configuration.
3. Configure Telegram environment variables.
4. Run `doctor`.
5. Run the first bootstrap manually with Telegram historical alerts suppressed.
6. Inspect run status and reports.
7. Run a second manual scan and verify `NO_NEW_DATA` or only truly new closed candles.
8. Enable the systemd timer.

The first run may be long because it initializes all markets. This is acceptable, but it must not send historical alert spam.

---

## 9. Exit codes and run result

Use stable exit behavior:

- `0` — completed or partial run where at least one symbol succeeded;
- `1` — fatal run failure;
- `75` — overlapping run lock;
- configuration/doctor errors — non-zero with clear text.

A partial failure of individual symbols must be visible in reports but should not cause systemd to classify the entire service as failed when useful scanning completed.

Document the exact policy.

---

## 10. Tests and quality gates

Required regression tests:

1. bootstrap creates checkpoints but sends no historical alerts;
2. first new post-bootstrap event is sent exactly once;
3. rebuild does not resend historical events;
4. failed delivery is retried and can become sent;
5. retry maximum is enforced;
6. provider factory honors configuration;
7. unsupported provider fails clearly;
8. process lock returns exit code 75;
9. one broken symbol does not stop other symbols;
10. systemd command shown in documentation matches the actual CLI;
11. fresh editable install exposes `htf-scanner` entry point;
12. incremental state still matches full replay.

Run and report:

```bash
pytest --cov
ruff check .
mypy src
```

---

## Definition of Done

The task is complete only when:

- a fresh server can install the repository without relying on generated metadata;
- `doctor` succeeds with valid production settings;
- the initial all-market bootstrap does not send historical Telegram spam;
- hourly scans analyze all selected long and short markets incrementally;
- only configured new events are sent to Telegram;
- alerts are deduplicated and failed deliveries are retried safely;
- systemd service and timer are included and documented;
- restart and repeated runs preserve state;
- detector behavior and causal guarantees remain unchanged.

---

## Final Codex report

Include:

1. modified and added files;
2. bootstrap alert policy implementation;
3. retry lifecycle and schema changes;
4. provider factory implementation;
5. packaging verification commands;
6. systemd unit contents;
7. exact deployment commands;
8. test results;
9. first-run validation results;
10. known limitations.
