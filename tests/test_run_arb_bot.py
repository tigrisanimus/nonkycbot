"""Tests for run_arb_bot helpers."""

from __future__ import annotations

from decimal import Decimal

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


def test_get_price_uses_last_price_from_raw_payload() -> None:
    client = _StubClient(
        MarketTicker(
            symbol="ETH-USDT",
            last_price="",
            raw_payload={"lastPrice": "125.5"},
        )
    )
    assert get_price(client, "ETH-USDT") == Decimal("125.5")


def test_get_price_uses_bid_ask_mid_from_raw_payload() -> None:
    client = _StubClient(
        MarketTicker(
            symbol="ETH-USDT",
            last_price=None,
            raw_payload={"bid": "100", "ask": "102"},
        )
    )
    assert get_price(client, "ETH-USDT") == Decimal("101")


def test_get_price_uses_orderbook_fallback() -> None:
    from nonkyc_client.rest import RestRequest, RestResponse

    class _OrderbookStubClient:
        def __init__(self) -> None:
            pass

        def get_market_data(self, symbol: str) -> MarketTicker:
            return MarketTicker(symbol=symbol, last_price="", raw_payload={})

        def send(self, request: RestRequest) -> RestResponse:
            # Simulate orderbook response
            return {
                "data": {
                    "bids": [["3000.50", "1.5"], ["3000.00", "2.0"]],
                    "asks": [["3001.50", "1.0"], ["3002.00", "0.5"]],
                }
            }

    client = _OrderbookStubClient()
    # Mid-price should be (3000.50 + 3001.50) / 2 = 3001.00
    result = get_price(client, "ETH-USDT")
    assert result == Decimal("3001.00")
