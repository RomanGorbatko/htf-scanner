from pathlib import Path
from typing import Any

from htf_scanner.config import AppConfig, configuration_hash
from htf_scanner.data.cache import CandleFileCache
from htf_scanner.pipeline import analyze_symbol
from htf_scanner.production.incremental import CausalIncrementalBackend


def _by_id(items: list[Any]) -> dict[str, dict[str, Any]]:
    return {str(item.id): item.model_dump(mode="json") for item in items}


def test_incremental_checkpoint_matches_full_jto_replay() -> None:
    cache = CandleFileCache(Path("tests/fixtures"))
    d1 = cache.read("JTOUSDT", "1d")
    h4 = cache.read("JTOUSDT", "4h")
    config = AppConfig()
    config_hash = configuration_hash(config)
    cutoff = d1[-10].open_time
    backend = CausalIncrementalBackend(config, config_hash)
    initial = backend.bootstrap(
        [item for item in d1 if item.open_time < cutoff],
        [item for item in h4 if item.open_time < cutoff],
    )

    assert initial.rebuilt
    restored = CausalIncrementalBackend.restore(config, config_hash, backend.export_state())
    incremental = restored.update(
        [item for item in d1 if item.open_time >= cutoff],
        [item for item in h4 if item.open_time >= cutoff],
    )
    full = analyze_symbol(d1, h4, config, config_hash)

    assert not incremental.rebuilt
    assert _by_id(incremental.d1.fvgs) == _by_id(full.d1.fvgs)
    assert _by_id(incremental.d1.swings) == _by_id(full.d1.swings)
    assert _by_id(incremental.d1.structure_breaks) == _by_id(full.d1.structure_breaks)
    assert _by_id(incremental.d1.displacements) == _by_id(full.d1.displacements)
    assert _by_id(incremental.d1.liquidity_contexts) == _by_id(full.d1.liquidity_contexts)
    assert _by_id(incremental.d1.setups) == _by_id(full.d1.setups)
    assert _by_id(incremental.h4.fvgs) == _by_id(full.h4.fvgs)
    assert _by_id(incremental.h4.swings) == _by_id(full.h4.swings)
    assert _by_id(incremental.h4.structure_breaks) == _by_id(full.h4.structure_breaks)
    assert _by_id(incremental.h4.displacements) == _by_id(full.h4.displacements)
    assert _by_id(incremental.h4.reactions) == _by_id(full.h4.reactions)
    assert _by_id(incremental.h4.transitions) == _by_id(full.h4.transitions)


def test_incremental_event_ids_are_deterministic() -> None:
    cache = CandleFileCache(Path("tests/fixtures"))
    d1 = cache.read("JTOUSDT", "1d")
    h4 = cache.read("JTOUSDT", "4h")
    config = AppConfig()
    config_hash = configuration_hash(config)
    cutoff = d1[-10].open_time

    def run() -> list[str]:
        backend = CausalIncrementalBackend(config, config_hash)
        backend.bootstrap(
            [item for item in d1 if item.open_time < cutoff],
            [item for item in h4 if item.open_time < cutoff],
        )
        update = backend.update(
            [item for item in d1 if item.open_time >= cutoff],
            [item for item in h4 if item.open_time >= cutoff],
        )
        return [str(item.id) for item in update.events]

    assert run() == run()
