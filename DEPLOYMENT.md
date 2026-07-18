# Production Deployment

The service polls closed Binance USD-M D1/H4 candles once per hour and sends configured Telegram
events. It does not place orders or calculate entries, stops, leverage, or position sizes.

## 1. Install

On a supported Linux server with Python 3.12+, systemd, and an existing `rg` login user:

```bash
id rg
sudo -H -u rg git clone git@github.com:RomanGorbatko/htf-scanner.git /home/rg/htf-scanner
cd /home/rg/htf-scanner
sudo ./deploy/install.sh /home/rg/htf-scanner
```

The installer requires `/home/rg/htf-scanner` to be writable by `rg`. It creates the virtual
environment and installs the package as `rg`, while only the systemd units and environment file are
managed as root. It automatically tries `python3.12` and then `python3`, verifies Python 3.12+, and
passes the resolved absolute path through `runuser`. To select another executable explicitly:

```bash
sudo PYTHON_BIN=/usr/local/bin/python3.12 ./deploy/install.sh /home/rg/htf-scanner
```

It does not enable the timer automatically.

`config.production.yaml` is owned by `rg` with mode `0640`, so `rg` can maintain it without `sudo`.
The Telegram environment file remains root-owned because it contains secrets.

For a manual installation:

```bash
cd /home/rg/htf-scanner
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .
cp config.production.example.yaml config.production.yaml
```

All relative paths in the example configuration are resolved from the service
`WorkingDirectory=/home/rg/htf-scanner`. Absolute paths are also accepted when data is mounted
separately.

If installation reports that Python is missing or too old, inspect the server before retrying:

```bash
command -v python3.12 || command -v python3
python3 --version
python3 -m venv --help
```

Install Python 3.12 and its `venv` module through the server's package manager when these checks
fail.

## 2. Configure Telegram

Keep these literal environment variable names in `config.production.yaml`; do not replace them with
the token or chat ID:

```yaml
telegram:
  enabled: true
  bot_token_env: "HTF_TELEGRAM_BOT_TOKEN"
  chat_id_env: "HTF_TELEGRAM_CHAT_ID"
```

Put the actual credentials only in `/etc/htf-scanner.env`:

```bash
HTF_TELEGRAM_BOT_TOKEN=123456:replace_with_real_token
HTF_TELEGRAM_CHAT_ID=replace_with_real_chat_id
```

Then restrict access:

```bash
sudo chown root:rg /etc/htf-scanner.env
sudo chmod 0640 /etc/htf-scanner.env
```

## 3. Validate

```bash
cd /home/rg/htf-scanner
sudo -H -u rg /bin/bash -c '
  set -a
  source /etc/htf-scanner.env
  set +a
  exec /home/rg/htf-scanner/.venv/bin/htf-scanner doctor \
    --config /home/rg/htf-scanner/config.production.yaml
'
```

Doctor does not send Telegram messages by default. An explicit connectivity message is available:

```bash
sudo -H -u rg /bin/bash -c '
  set -a
  source /etc/htf-scanner.env
  set +a
  exec /home/rg/htf-scanner/.venv/bin/htf-scanner doctor \
    --config /home/rg/htf-scanner/config.production.yaml --send-telegram-test
'
```

## 4. Bootstrap Manually

`alerts.bootstrap_policy: suppress` persists historical events and checkpoints without creating
Telegram deliveries. It applies to first initialization, `--rebuild`, and configuration-hash
rebuilds.

The installed oneshot service executes exactly:

```bash
/home/rg/htf-scanner/.venv/bin/htf-scanner scan-live-once --config /home/rg/htf-scanner/config.production.yaml
```

```bash
sudo systemctl start htf-scanner.service
sudo systemctl status htf-scanner.service
journalctl -u htf-scanner.service -n 100 --no-pager
```

The first all-market run can take a long time. Inspect `reports/live/<run-id>/run_manifest.json`,
`symbol_summary.csv`, `alerts_pending.csv`, and `runtime_metrics.csv`.

Run it manually a second time. Symbols should normally report `NO_NEW_DATA`, unless another D1/H4
candle closed in the meantime:

```bash
sudo systemctl start htf-scanner.service
journalctl -u htf-scanner.service -n 100 --no-pager
```

## 5. Enable Hourly Timer

```bash
sudo systemctl enable --now htf-scanner.timer
systemctl list-timers htf-scanner.timer
```

The timer runs shortly after each hour (`*:05:00` plus up to 30 seconds randomized delay). The
application lock remains authoritative; overlap exits with code 75.

The service runs as `rg`. `ProtectHome=read-only` keeps the rest of `/home` non-writable, while
`ReadWritePaths` permits writes only below `/home/rg/htf-scanner/data` and
`/home/rg/htf-scanner/reports`.

## Exit Policy

- `0`: completed scan, or partial scan with at least one successful/`NO_NEW_DATA` symbol;
- `1`: fatal scan failure or doctor failure;
- `75`: another scanner process holds the application lock.

Per-symbol failures remain visible in reports. A partial run with useful results exits zero so
systemd does not mark the whole hourly service failed.

## Operations

```bash
systemctl status htf-scanner.timer htf-scanner.service
journalctl -u htf-scanner.service --since today
sudo systemctl stop htf-scanner.timer
```

Back up `/home/rg/htf-scanner/data/htf_scanner.db` and
`/home/rg/htf-scanner/data/candles/`. Do not run `--rebuild` routinely. Failed alert deliveries
respect `next_retry_at`, stop at `alerts.maximum_delivery_attempts`, and remain in reports as
`PERMANENTLY_FAILED` with the final error text.
