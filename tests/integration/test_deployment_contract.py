import subprocess
import sys
import tomllib
from datetime import timedelta
from pathlib import Path

from typer.testing import CliRunner

from htf_scanner.cli import app
from htf_scanner.config import load_config
from htf_scanner.production.lock import ProcessLock

PROJECT_ROOT = Path(__file__).parents[2]


def test_scan_live_once_returns_75_when_process_lock_is_held(tmp_path: Path) -> None:
    lock_path = tmp_path / "scanner.lock"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "scheduler:",
                f"  lock_path: '{lock_path}'",
                "  stale_after_minutes: 180",
            ]
        ),
        encoding="utf-8",
    )

    with ProcessLock(lock_path, timedelta(minutes=180)):
        result = CliRunner().invoke(
            app,
            ["scan-live-once", "--config", str(config_path)],
        )

    assert result.exit_code == 75
    assert "lock already exists" in result.output


def test_scan_live_once_reports_configuration_errors(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text("unsupported_root_key: true\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["scan-live-once", "--config", str(config_path)],
    )

    assert result.exit_code == 2
    assert "Configuration failed:" in result.output


def test_editable_install_exposes_console_entry_point() -> None:
    metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["requires-python"] == ">=3.12"
    assert metadata["project"]["scripts"]["htf-scanner"] == "htf_scanner.cli:app"

    executable = Path(sys.executable).with_name("htf-scanner")
    result = subprocess.run(
        [executable, "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "scan-live-once" in result.stdout
    assert "doctor" in result.stdout


def test_documented_systemd_command_matches_service_and_cli() -> None:
    service = (PROJECT_ROOT / "deploy/systemd/htf-scanner.service").read_text(encoding="utf-8")
    deployment = (PROJECT_ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    installer = (PROJECT_ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    exec_start = next(line for line in service.splitlines() if line.startswith("ExecStart="))
    command = exec_start.removeprefix("ExecStart=")

    assert command in deployment
    assert " scan-live-once --config " in command
    assert "User=rg" in service
    assert "WorkingDirectory=/home/rg/htf-scanner" in service
    assert "ProtectHome=read-only" in service
    assert "ReadWritePaths=/home/rg/htf-scanner/data /home/rg/htf-scanner/reports" in service
    assert 'PROJECT_DIR="${1:-/home/rg/htf-scanner}"' in installer
    assert 'SERVICE_USER="${HTF_SCANNER_USER:-rg}"' in installer
    assert "/opt/htf-scanner" not in "\n".join([service, deployment, readme, installer])
    assert "OnCalendar=*-*-* *:05:00" in (
        PROJECT_ROOT / "deploy/systemd/htf-scanner.timer"
    ).read_text(encoding="utf-8")


def test_production_example_has_safe_alert_and_universe_defaults() -> None:
    config = load_config(PROJECT_ROOT / "config.production.example.yaml")

    assert config.scanner.confirmed_candles_only
    assert config.market_data.provider == "binance"
    assert config.exchange.quote_asset == "USDT"
    assert config.exchange.contract_type == "PERPETUAL"
    assert config.universe.active_only
    assert config.universe.maximum_symbols is None
    assert config.telegram.enabled
    assert config.alerts.bootstrap_policy == "suppress"
    assert config.alerts.event_types == ["D1_SETUP_ACTIVE", "H4_REACTION_CONFIRMED"]
    assert not config.alerts.attach_chart
    assert config.storage.database_url == "sqlite:///data/htf_scanner.db"
    assert config.runtime.report_dir == Path("reports/live")
