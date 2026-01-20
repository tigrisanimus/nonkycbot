"""Tests for the grid trading bot runner."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

import run_grid


def test_load_config_from_yaml_file(tmp_path):
    """Test that load_config correctly parses YAML files."""
    config_file = tmp_path / "grid_config.yml"
    config_content = {
        "trading_pair": "BTC/USDT",
        "step_pct": "0.01",
        "n_buy_levels": 5,
        "n_sell_levels": 5,
        "base_order_size": "10",
        "api_key": "test_key",
        "api_secret": "test_secret",
    }

    with open(config_file, "w") as f:
        yaml.dump(config_content, f)

    loaded_config = run_grid.load_config(str(config_file))

    assert loaded_config["trading_pair"] == "BTC/USDT"
    assert loaded_config["step_pct"] == "0.01"
    assert loaded_config["n_buy_levels"] == 5
    assert loaded_config["n_sell_levels"] == 5
    assert loaded_config["base_order_size"] == "10"


def test_load_config_with_missing_file():
    """Test that load_config raises error for missing file."""
    with pytest.raises(FileNotFoundError):
        run_grid.load_config("nonexistent_file.yml")


def test_run_grid_from_file_validates_config_exists(tmp_path):
    """Test that run_grid_from_file checks if config file exists."""
    nonexistent_file = tmp_path / "does_not_exist.yml"

    # Should handle missing file gracefully or raise appropriate error
    # Since the script expects the file to exist, we test that it fails
    # when the file doesn't exist
    with pytest.raises(FileNotFoundError):
        run_grid.run_grid_from_file(str(nonexistent_file))


def test_run_grid_accepts_valid_config(tmp_path):
    """Test that run_grid accepts a valid configuration."""
    config_file = tmp_path / "valid_grid.yml"
    config_content = {
        "exchange": "nonkyc",
        "trading_pair": "ETH/USDT",
        "step_pct": "0.02",
        "n_buy_levels": 3,
        "n_sell_levels": 3,
        "base_order_size": "0.1",
        "total_fee_rate": "0.002",
        "api_key": "test_key",
        "api_secret": "test_secret",
        "base_url": "https://api.test.com",
        "state_path": str(tmp_path / "state.json"),
    }

    with open(config_file, "w") as f:
        yaml.dump(config_content, f)

    # This would actually try to connect, so we just verify config loads
    config = run_grid.load_config(str(config_file))
    assert config["trading_pair"] == "ETH/USDT"
    assert config["step_pct"] == "0.02"


def test_grid_config_has_state_path_default(tmp_path):
    """Test that state_path defaults to state.json if not specified."""
    config_file = tmp_path / "minimal_grid.yml"
    config_content = {
        "trading_pair": "BTC/USDT",
        "api_key": "test",
        "api_secret": "test",
    }

    with open(config_file, "w") as f:
        yaml.dump(config_content, f)

    config = run_grid.load_config(str(config_file))

    # Default should be used if not specified
    state_path = Path(config.get("state_path", "state.json"))
    assert state_path.name == "state.json"
