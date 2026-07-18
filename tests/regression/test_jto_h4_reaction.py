from datetime import UTC, datetime
from pathlib import Path

from htf_scanner.config import AppConfig, configuration_hash
from htf_scanner.data.cache import CandleFileCache
from htf_scanner.domain.enums import H4ReactionStatus
from htf_scanner.pipeline import analyze_symbol


def test_jto_july_setup_has_causal_confirmed_h4_reaction() -> None:
    fixture_root = Path(__file__).parents[1] / "fixtures"
    cache = CandleFileCache(fixture_root)
    d1 = cache.read("JTOUSDT", "1d")
    h4 = cache.read("JTOUSDT", "4h")
    config = AppConfig()
    result = analyze_symbol(d1, h4, config, configuration_hash(config), strict_data=True)
    setup = next(
        item
        for item in result.d1.setups
        if item.known_at == datetime(2026, 7, 9, 23, 59, 59, 999000, tzinfo=UTC)
    )
    assert str(setup.id) == "d27da152-ebb2-5f0e-8a60-b74996a747ad"
    assert str(setup.fvg_id) == "14fb3120-b063-559c-b462-651d21ca96aa"
    assert setup.quality_score == 11.985936134298132
    reaction = next(item for item in result.h4.reactions if item.setup_id == setup.id)
    assert reaction.status == H4ReactionStatus.REACTION_CONFIRMED
    assert reaction.touch_close_time == datetime(2026, 7, 10, 3, 59, 59, 999000, tzinfo=UTC)
    assert reaction.confirmed_at == datetime(2026, 7, 10, 15, 59, 59, 999000, tzinfo=UTC)
    assert reaction.touch_close_time > setup.known_at
    assert reaction.displacement_id is not None
    assert reaction.structure_break_id is not None
    assert reaction.reaction_score == 12.988888888888889
    snapshots = [item for item in result.outcomes.outcomes if item.reaction_id == reaction.id]
    assert [item.horizon_bars for item in snapshots] == [6, 12, 24, 42]
    assert snapshots[1].mfe_atr == 1.8558688569856974
    assert result.h4.diagnostics == []
