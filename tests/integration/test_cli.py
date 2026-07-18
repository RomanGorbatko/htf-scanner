from datetime import timedelta
from pathlib import Path

from typer.testing import CliRunner

from htf_scanner.cli import app
from htf_scanner.storage.database import create_database_engine
from htf_scanner.storage.repository import CandleRepository
from tests.conftest import make_candle
from tests.unit.test_h4_reaction_engine import h4


def test_inspect_fvg_offline_generates_outputs(tmp_path: Path) -> None:
    database_path = tmp_path / "scanner.db"
    reports_path = tmp_path / "reports"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "atr:",
                "  period: 2",
                "fvg:",
                "  minimum_size_atr: 0",
                "  maximum_size_atr: 100",
                f"storage:\n  database_url: 'sqlite:///{database_path}'",
                f"reports:\n  output_dir: '{reports_path}'",
            ]
        ),
        encoding="utf-8",
    )
    candles = [
        make_candle(0, "11", "12", "10", "11"),
        make_candle(1, "11", "11", "8", "9"),
        make_candle(2, "9", "9", "7", "8"),
    ]
    engine = create_database_engine(f"sqlite:///{database_path}")
    repository = CandleRepository(engine)
    repository.upsert_many(candles)
    engine.dispose()
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "inspect-fvg",
            "--symbol",
            "TESTUSDT",
            "--start",
            "2026-01-01",
            "--end",
            (candles[-1].open_time + timedelta(days=1)).date().isoformat(),
            "--config",
            str(config_path),
            "--offline",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Detected" in result.output
    assert (reports_path / "TESTUSDT" / "d1_fvgs.csv").exists()
    assert (reports_path / "TESTUSDT" / "d1_fvgs.png").exists()


def test_detect_d1_setups_offline_generates_debug_outputs(tmp_path: Path) -> None:
    database_path = tmp_path / "scanner.db"
    reports_path = tmp_path / "reports"
    cache_path = tmp_path / "cache"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "atr:\n  period: 2",
                "swings:\n  reversal_atr: 0.5\n  minimum_bars_between_swings: 1",
                "structure:\n  break_mode: close\n  minimum_break_atr: 0",
                "fvg:\n  minimum_size_atr: 0\n  maximum_size_atr: 100",
                f"storage:\n  database_url: 'sqlite:///{database_path}'",
                f"  candle_cache_dir: '{cache_path}'",
                f"reports:\n  output_dir: '{reports_path}'",
            ]
        ),
        encoding="utf-8",
    )
    candles = [
        make_candle(0, "9.5", "10", "9", "9.5"),
        make_candle(1, "10", "12", "10", "11.5"),
        make_candle(2, "11", "11", "9", "9.5"),
        make_candle(3, "9", "9.5", "7", "8"),
        make_candle(4, "8", "10", "8", "9.5"),
        make_candle(5, "10", "13", "10", "12.5"),
        make_candle(6, "12", "12", "9", "9.5"),
        make_candle(7, "9", "9", "6", "6.5"),
    ]
    engine = create_database_engine(f"sqlite:///{database_path}")
    CandleRepository(engine).upsert_many(candles)
    engine.dispose()

    result = CliRunner().invoke(
        app,
        [
            "detect-d1-setups",
            "--symbol",
            "TESTUSDT",
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-09",
            "--config",
            str(config_path),
            "--offline",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "D1 analysis:" in result.output
    for filename in [
        "d1_swings.csv",
        "d1_structure_breaks.csv",
        "d1_displacements.csv",
        "d1_liquidity_contexts.csv",
        "d1_setups.csv",
        "d1_setups.png",
    ]:
        assert (reports_path / "TESTUSDT" / filename).exists()


def test_detect_h4_reactions_offline_generates_full_report_set(tmp_path: Path) -> None:
    database_path = tmp_path / "scanner.db"
    reports_path = tmp_path / "reports"
    cache_path = tmp_path / "cache"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "atr:\n  period: 2",
                f"storage:\n  database_url: 'sqlite:///{database_path}'",
                f"  candle_cache_dir: '{cache_path}'",
                f"reports:\n  output_dir: '{reports_path}'",
            ]
        ),
        encoding="utf-8",
    )
    from htf_scanner.data.cache import CandleFileCache

    cache = CandleFileCache(cache_path)
    cache.write(
        "TESTUSDT",
        "1d",
        [make_candle(index, "10", "11", "9", "10") for index in range(5)],
    )
    cache.write("TESTUSDT", "4h", [h4(index, "10", "11", "9", "10") for index in range(8)])
    result = CliRunner().invoke(
        app,
        [
            "detect-h4-reactions",
            "--symbol",
            "TESTUSDT",
            "--config",
            str(config_path),
            "--offline",
        ],
    )
    assert result.exit_code == 0, result.output
    report_dir = reports_path / "TESTUSDT"
    expected = {
        "h4_touch_phases.csv",
        "h4_reactions.csv",
        "h4_reaction_candidates.csv",
        "h4_rejected_candidates.csv",
        "h4_merged_candidates.csv",
        "h4_reaction_transitions.csv",
        "reaction_outcomes.csv",
        "reaction_target_outcomes.csv",
        "h4_diagnostics.json",
        "h4_reactions.png",
    }
    assert expected <= {item.name for item in report_dir.iterdir()}


def test_outcome_and_batch_cli_commands_write_deterministic_reports(tmp_path: Path) -> None:
    database_path = tmp_path / "scanner.db"
    reports_path = tmp_path / "reports"
    cache_path = tmp_path / "cache"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "atr:\n  period: 2",
                "batch_scan:\n  minimum_d1_candles: 3\n  minimum_h4_candles: 3",
                f"storage:\n  database_url: 'sqlite:///{database_path}'",
                f"  candle_cache_dir: '{cache_path}'",
                f"reports:\n  output_dir: '{reports_path}'",
            ]
        ),
        encoding="utf-8",
    )
    from htf_scanner.data.cache import CandleFileCache

    cache = CandleFileCache(cache_path)
    cache.write(
        "TESTUSDT",
        "1d",
        [make_candle(index, "10", "11", "9", "10") for index in range(5)],
    )
    cache.write("TESTUSDT", "4h", [h4(index, "10", "11", "9", "10") for index in range(8)])
    runner = CliRunner()
    outcome = runner.invoke(
        app,
        [
            "evaluate-reaction-outcomes",
            "--symbol",
            "TESTUSDT",
            "--config",
            str(config_path),
        ],
    )
    assert outcome.exit_code == 0, outcome.output
    assert "Outcome snapshots:" in outcome.output
    batch_output = tmp_path / "universe"
    batch = runner.invoke(
        app,
        [
            "scan-universe",
            "--symbols",
            "MISSINGUSDT,TESTUSDT",
            "--data-dir",
            str(cache_path),
            "--config",
            str(config_path),
            "--output",
            str(batch_output),
        ],
    )
    assert batch.exit_code == 0, batch.output
    assert "Manifest hash:" in batch.output
    expected = {
        "universe_summary.csv",
        "symbol_run_summary.csv",
        "active_d1_setups.csv",
        "confirmed_h4_reactions.csv",
        "reaction_outcome_summary.csv",
        "data_quality_errors.csv",
        "run_manifest.json",
    }
    assert expected == {item.name for item in batch_output.iterdir()}
