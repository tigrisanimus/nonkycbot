"""Tests for the hybrid arbitrage bot runner."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

import bots.run_hybrid_arb_bot as run_hybrid_arb_bot


@pytest.fixture
def mock_config():
    """Create a mock configuration for testing."""
    return {
        "orderbook_pairs": ["COSA/USDT", "COSA/BTC", "PIRATE/USDT", "PIRATE/BTC"],
        "pool_pair": "COSA/PIRATE",
        "base_currency": "USDT",
        "trade_amount": "100",
        "min_profit_pct": "0.5",
        "poll_interval_seconds": 2.0,
        "mode": "monitor",
        "orderbook_fee": "0.002",
        "pool_fee": "0.003",
        "api_key": "test_key",
        "api_secret": "test_secret",
        "base_url": "https://api.test.com",
    }


@pytest.fixture
def mock_rest_client():
    """Create a mock REST client."""
    client = Mock()

    # Mock market data for order book pairs
    def mock_get_market_data(pair):
        prices = {
            "COSA/USDT": Mock(bid=Decimal("0.49"), ask=Decimal("0.51")),
            "COSA/BTC": Mock(bid=Decimal("0.000012"), ask=Decimal("0.000013")),
            "PIRATE/USDT": Mock(bid=Decimal("1.00"), ask=Decimal("1.02")),
            "PIRATE/BTC": Mock(bid=Decimal("0.000024"), ask=Decimal("0.000025")),
        }
        return prices.get(pair, Mock(bid=Decimal("1"), ask=Decimal("1")))

    client.get_market_data.side_effect = mock_get_market_data

    # Mock liquidity pool data
    client.get_liquidity_pool.return_value = {
        "token_a": "COSA",
        "token_b": "PIRATE",
        "reserve_a": "10000",
        "reserve_b": "5000",
        "fee_rate": "0.003",
    }

    return client


def test_hybrid_arb_bot_initialization(mock_config):
    """Test that HybridArbBot initializes correctly."""
    with patch("bots.run_hybrid_arb_bot.build_rest_client", return_value=Mock()):
        bot = run_hybrid_arb_bot.HybridArbBot(mock_config)

        assert bot.mode == "monitor"
        assert bot.min_profit_pct == Decimal("0.5")
        assert bot.trade_amount == Decimal("100")
        assert bot.orderbook_pairs == [
            "COSA/USDT",
            "COSA/BTC",
            "PIRATE/USDT",
            "PIRATE/BTC",
        ]
        assert bot.pool_pair == "COSA/PIRATE"
        assert bot.base_currency == "USDT"
        assert bot.cycles_evaluated == 0


def test_hybrid_arb_bot_monitor_mode_setting(mock_config):
    """Test that monitor mode is properly set."""
    with patch("bots.run_hybrid_arb_bot.build_rest_client", return_value=Mock()):
        bot = run_hybrid_arb_bot.HybridArbBot(mock_config)

        assert bot.mode == "monitor"


def test_hybrid_arb_bot_orderbook_pairs_configuration(mock_config):
    """Test that orderbook pairs are correctly configured."""
    with patch("bots.run_hybrid_arb_bot.build_rest_client", return_value=Mock()):
        bot = run_hybrid_arb_bot.HybridArbBot(mock_config)

        assert len(bot.orderbook_pairs) == 4
        assert "COSA/USDT" in bot.orderbook_pairs
        assert "PIRATE/USDT" in bot.orderbook_pairs


def test_hybrid_arb_bot_fee_configuration(mock_config):
    """Test that fees are correctly configured."""
    with patch("bots.run_hybrid_arb_bot.build_rest_client", return_value=Mock()):
        bot = run_hybrid_arb_bot.HybridArbBot(mock_config)

        assert bot.orderbook_fee == Decimal("0.002")
        assert bot.pool_fee == Decimal("0.003")


def test_hybrid_arb_bot_parses_config_correctly(tmp_path):
    """Test that YAML config is parsed correctly."""
    import yaml

    config_file = tmp_path / "hybrid_arb_config.yml"
    config_content = """
orderbook_pairs:
  - COSA/USDT
  - PIRATE/USDT
pool_pair: COSA/PIRATE
base_currency: USDT
trade_amount: "50"
min_profit_pct: "1.0"
mode: monitor
    """
    config_file.write_text(config_content)

    with open(config_file) as f:
        config = yaml.safe_load(f)

    assert config["orderbook_pairs"] == ["COSA/USDT", "PIRATE/USDT"]
    assert config["pool_pair"] == "COSA/PIRATE"
    assert config["trade_amount"] == "50"
    assert config["min_profit_pct"] == "1.0"


def test_hybrid_arb_bot_dry_run_mode_configuration(mock_config):
    """Test that dry-run mode can be configured."""
    mock_config["mode"] = "dry-run"

    with patch("bots.run_hybrid_arb_bot.build_rest_client", return_value=Mock()):
        bot = run_hybrid_arb_bot.HybridArbBot(mock_config)

        assert bot.mode == "dry-run"


def test_hybrid_arb_bot_live_mode_configuration(mock_config):
    """Test that live mode can be configured."""
    mock_config["mode"] = "live"

    with patch("bots.run_hybrid_arb_bot.build_rest_client", return_value=Mock()):
        bot = run_hybrid_arb_bot.HybridArbBot(mock_config)

        assert bot.mode == "live"
