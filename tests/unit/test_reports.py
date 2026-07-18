from pathlib import Path

import pytest

from htf_scanner.analytics.reaction_outcomes import evaluate_reaction_outcomes
from htf_scanner.config import AppConfig, AtrConfig, FvgConfig, ReactionOutcomesConfig
from htf_scanner.detectors.fvg_detector import detect_fvgs
from htf_scanner.detectors.h4_reaction_detector import H4ReactionEngine
from htf_scanner.domain.enums import SetupSide
from htf_scanner.reports.charts import plot_d1_fvgs, plot_h4_reaction_debug
from htf_scanner.reports.exports import export_fvgs_csv
from tests.conftest import make_candle
from tests.unit.test_h4_reaction_engine import BASE, h4, linked_impulse, setup_and_zone


def test_csv_and_chart_reports_are_written(tmp_path: Path) -> None:
    candles = [
        make_candle(0, "11", "12", "10", "11"),
        make_candle(1, "11", "11", "8", "9"),
        make_candle(2, "9", "9", "7", "8"),
    ]
    fvgs = detect_fvgs(
        candles,
        atr_period=2,
        config=FvgConfig(minimum_size_atr=0, maximum_size_atr=100),
    )

    csv_path = export_fvgs_csv(fvgs, tmp_path / "nested" / "fvgs.csv")
    chart_path = plot_d1_fvgs(candles, fvgs, tmp_path / "nested" / "fvgs.png")

    assert "formed_at" in csv_path.read_text(encoding="utf-8")
    assert chart_path.stat().st_size > 1_000


def test_chart_rejects_empty_series(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        plot_d1_fvgs([], [], tmp_path / "empty.png")


def test_h4_chart_draws_touch_confirmation_break_and_targets(tmp_path: Path) -> None:
    config = AppConfig(
        atr=AtrConfig(period=1),
        reaction_outcomes=ReactionOutcomesConfig(horizons=[1], fixed_atr_targets=[1.0]),
    )
    setup, zone = setup_and_zone(BASE, SetupSide.SHORT)
    first = h4(1, "10.5", "11", "8", "8.5")
    second = h4(2, "9", "10.5", "7", "8")
    displacement, structure_break = linked_impulse(first, SetupSide.SHORT)
    engine = H4ReactionEngine(setup, zone, config, "hash")
    engine.update(first, 1.0, [displacement], {structure_break.id: structure_break}, {})
    engine.update(second, 1.0, [], {structure_break.id: structure_break}, {})
    phases, reaction, _candidates, _rejected, _merged, _transitions = engine.result()
    assert reaction is not None
    outcomes = evaluate_reaction_outcomes(
        [reaction], [first, second], [setup], [zone], config, "hash"
    )
    path = plot_h4_reaction_debug(
        [first, second],
        [zone],
        [reaction],
        phases,
        [structure_break],
        [displacement],
        outcomes.target_outcomes,
        tmp_path / "h4.png",
    )
    assert path.stat().st_size > 1_000


def test_h4_chart_rejects_empty_series(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        plot_h4_reaction_debug([], [], [], [], [], [], [], tmp_path / "empty-h4.png")
