"""Tests for the market maker bot runner."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import bots.run_market_maker as run_market_maker


def test_load_config_from_yaml_file(tmp_path):
    """Test that load_config correctly parses YAML files."""
    config_file = tmp_path / "mm_config.yml"
    config_content = {
        "symbol": "BTC/USDT",
        "base_order_size": "1",
        "sell_quote_target": "100",
        "fee_rate": "0.001",
        "api_key": "test_key",
        "api_secret": "test_secret",
    }

    with open(config_file, "w") as f:
        yaml.dump(config_content, f)

    loaded_config = run_market_maker.load_config(str(config_file))

    assert loaded_config["symbol"] == "BTC/USDT"
    assert loaded_config["base_order_size"] == "1"
    assert loaded_config["sell_quote_target"] == "100"


def test_load_config_with_missing_file():
    """Test that load_config raises error for missing file."""
    with pytest.raises(FileNotFoundError):
        run_market_maker.load_config("nonexistent_file.yml")


def test_run_market_maker_from_file_validates_config_exists(tmp_path):
    """Test that run_market_maker_from_file checks if config file exists."""
    nonexistent_file = tmp_path / "does_not_exist.yml"

    with pytest.raises(FileNotFoundError):
        run_market_maker.run_market_maker_from_file(str(nonexistent_file))


def test_market_maker_config_has_state_path_default(tmp_path):
    """Test that state_path defaults to state/market_maker_state.json if not specified."""
    config_file = tmp_path / "minimal_mm.yml"
    config_content = {
        "symbol": "BTC/USDT",
        "base_order_size": "1",
        "sell_quote_target": "100",
        "fee_rate": "0.001",
    }

    with open(config_file, "w") as f:
        yaml.dump(config_content, f)

    config = run_market_maker.load_config(str(config_file))

    state_path = Path(config.get("state_path", "state/market_maker_state.json"))
    assert state_path.as_posix().endswith("state/market_maker_state.json")
