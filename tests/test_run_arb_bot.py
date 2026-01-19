"""Tests for run_arb_bot helpers."""

from __future__ import annotations

from nonkyc_client.models import MarketTicker
from run_arb_bot import get_price


class _StubClient:
    def __init__(self, ticker: MarketTicker) -> None:
        self._ticker = ticker

    def get_market_data(self, symbol: str) -> MarketTicker:
        return self._ticker


def test_get_price_returns_none_for_empty_last_price() -> None:
    client = _StubClient(MarketTicker(symbol="ETH-USDT", last_price="", raw_payload={}))
    assert get_price(client, "ETH-USDT") is None
