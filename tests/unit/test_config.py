import pytest
from pydantic import ValidationError

from htf_scanner.config import AppConfig, load_config


def test_load_config_uses_defaults_and_yaml_overrides(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert load_config().atr.period == 14
    path = tmp_path / "config.yaml"
    path.write_text("atr:\n  period: 21\n", encoding="utf-8")

    config = load_config(path)

    assert config.atr.period == 21
    assert config.scanner.version == "0.1.0"


def test_config_forbids_unknown_keys() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        AppConfig.model_validate({"unknown": True})
