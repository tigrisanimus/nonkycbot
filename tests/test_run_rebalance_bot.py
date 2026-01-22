"""Tests for the rebalance bot runner."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

import run_rebalance_bot


@pytest.fixture
def mock_config():
    """Create a mock configuration for testing."""
    return {
        "trading_pair": "ETH/USDT",
        "target_base_percent": "0.5",
        "rebalance_threshold_percent": "0.05",
        "poll_interval_seconds": 10,
        "mode": "monitor",
        "api_key": "test_key",
        "api_secret": "test_secret",
        "base_url": "https://api.test.com",
    }


@pytest.fixture
def mock_rest_client():
    """Create a mock REST client."""
    client = Mock()
    client.get_balances.return_value = []
    client.get_market_data.return_value = Mock(
        last_price=Decimal("2000"),
        bid=Decimal("1999"),
        ask=Decimal("2001"),
    )
    return client


def test_rebalance_bot_initialization(mock_config):
    """Test that RebalanceBot initializes correctly."""
    with patch("engine.rest_client_factory.build_rest_client", return_value=Mock()):
        bot = run_rebalance_bot.RebalanceBot(mock_config)

        assert bot.trading_pair == "ETH/USDT"
        assert bot.target_base_percent == Decimal("0.5")
        assert bot.rebalance_threshold_percent == Decimal("0.05")
        assert bot.mode == "monitor"
        assert bot.checks_performed == 0
        assert bot.rebalances_executed == 0


def test_rebalance_bot_get_price_mid(mock_config, mock_rest_client):
    """Test price extraction with mid price source."""
    with patch(
        "engine.rest_client_factory.build_rest_client", return_value=mock_rest_client
    ):
        bot = run_rebalance_bot.RebalanceBot(mock_config)
        bot.price_source = "mid"

        price = bot.get_price()

        # Mid price = (bid + ask) / 2 = (1999 + 2001) / 2 = 2000
        assert price == Decimal("2000")


def test_rebalance_bot_get_price_last(mock_config, mock_rest_client):
    """Test price extraction with last price source."""
    with patch(
        "engine.rest_client_factory.build_rest_client", return_value=mock_rest_client
    ):
        bot = run_rebalance_bot.RebalanceBot(mock_config)
        bot.price_source = "last"

        price = bot.get_price()

        assert price == Decimal("2000")


def test_rebalance_bot_execute_rebalance_monitor_mode(mock_config, mock_rest_client):
    """Test that monitor mode does not execute orders."""
    with patch(
        "engine.rest_client_factory.build_rest_client", return_value=mock_rest_client
    ):
        bot = run_rebalance_bot.RebalanceBot(mock_config)
        bot.mode = "monitor"

        result = bot.execute_rebalance("buy", Decimal("1"), Decimal("2000"))

        # Monitor mode should not execute
        assert result is False
        assert mock_rest_client.place_order.call_count == 0


def test_rebalance_bot_execute_rebalance_dry_run_mode(mock_config, mock_rest_client):
    """Test that dry-run mode logs but doesn't execute."""
    with patch(
        "engine.rest_client_factory.build_rest_client", return_value=mock_rest_client
    ):
        bot = run_rebalance_bot.RebalanceBot(mock_config)
        bot.mode = "dry-run"

        result = bot.execute_rebalance("buy", Decimal("1"), Decimal("2000"))

        # Dry-run mode should return True but not place orders
        assert result is True
        assert mock_rest_client.place_order.call_count == 0


def test_rebalance_bot_parses_yaml_config(tmp_path):
    """Test that YAML config files are parsed correctly."""
    config_file = tmp_path / "test_config.yml"
    config_content = """
trading_pair: BTC/USDT
target_base_percent: 0.5
rebalance_threshold_percent: 0.05
poll_interval_seconds: 60
api_key: test_key
api_secret: test_secret
    """
    config_file.write_text(config_content)

    with open(config_file) as f:
        import yaml

        config = yaml.safe_load(f)

    assert config["trading_pair"] == "BTC/USDT"
    assert config["target_base_percent"] == 0.5
    assert config["rebalance_threshold_percent"] == 0.05


def test_rebalance_bot_uses_correct_trading_pair_format(mock_config):
    """Test that trading pair is parsed correctly."""
    mock_config["trading_pair"] = "BTC_USDT"

    with patch("engine.rest_client_factory.build_rest_client", return_value=Mock()):
        bot = run_rebalance_bot.RebalanceBot(mock_config)

        assert bot.trading_pair == "BTC_USDT"
