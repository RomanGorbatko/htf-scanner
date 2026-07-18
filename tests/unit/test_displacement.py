from htf_scanner.config import DisplacementConfig, FvgConfig
from htf_scanner.detectors.displacement import DisplacementDetector
from htf_scanner.detectors.fvg_detector import detect_fvgs
from htf_scanner.domain.enums import Direction
from tests.conftest import make_candle


def test_multi_candle_displacement_links_fvg_created_on_final_bar() -> None:
    candles = [
        make_candle(0, "11", "12", "10", "11"),
        make_candle(1, "11", "11", "8", "9"),
        make_candle(2, "9", "9", "7", "7.2"),
        make_candle(3, "7.3", "8", "6.5", "6.8"),
    ]
    fvgs = detect_fvgs(
        candles,
        2,
        FvgConfig(minimum_size_atr=0, maximum_size_atr=100),
    )

    displacements = DisplacementDetector(
        DisplacementConfig(minimum_score=3, maximum_sequence_bars=3), 2
    ).detect(candles, [], fvgs)

    linked = [item for item in displacements if item.created_fvg]
    assert len(linked) > 1
    assert all(item.direction == Direction.BEARISH for item in linked)
    assert {item.sequence_bars for item in linked} >= {1, 2}
    assert all(item.fvg_id == fvgs[0].id for item in linked)
    assert all(item.score == sum(item.component_scores.values()) for item in linked)


def test_fvg_without_minimum_displacement_score_is_not_linked() -> None:
    candles = [
        make_candle(0, "10", "10.2", "9.8", "10"),
        make_candle(1, "10", "10.1", "9.9", "10"),
        make_candle(2, "10.3", "10.4", "10.3", "10.35"),
    ]
    fvgs = detect_fvgs(
        candles,
        1,
        FvgConfig(minimum_size_atr=0, maximum_size_atr=100),
    )

    displacements = DisplacementDetector(DisplacementConfig(minimum_score=7.0), 1).detect(
        candles, [], fvgs
    )

    assert fvgs
    assert displacements == []
