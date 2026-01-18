"""Tests for WebSocket client subscription handling."""

from __future__ import annotations

from unittest.mock import MagicMock

from nonkyc_client.auth import ApiCredentials
from nonkyc_client.ws import Subscription, WebSocketClient


def test_ws_login_payload_and_subscriptions() -> None:
    credentials = ApiCredentials(api_key="key", api_secret="secret")
    signer = MagicMock()
    signer.build_ws_login_payload.return_value = {
        "method": "login",
        "params": {"algo": "HS256", "pKey": "key", "nonce": "n", "signature": "sig"},
    }

    client = WebSocketClient(
        url="wss://ws.example", credentials=credentials, signer=signer
    )

    assert client.login_payload() == {
        "method": "login",
        "params": {"algo": "HS256", "pKey": "key", "nonce": "n", "signature": "sig"},
    }

    client.subscribe_order_book("BTC/USD", depth=10)
    client.subscribe_trades("BTC/USD")
    client.subscribe_account_updates()

    payloads = client.subscription_payloads()
    assert payloads == [
        {"method": "subscribeOrderbook", "params": {"symbol": "BTC/USD", "depth": 10}},
        {"method": "subscribeTrades", "params": {"symbol": "BTC/USD"}},
        {"method": "subscribeReports", "params": {}},
        {"method": "subscribeBalances", "params": {}},
    ]

    mocked_events = [
        {"method": "subscribeOrderbook", "data": {"symbol": "BTC/USD"}},
        {"method": "subscribeTrades", "data": {"symbol": "BTC/USD"}},
    ]
    channels = client.list_channels()
    assert all(event["method"] in channels for event in mocked_events)


def test_ws_extend_subscriptions_merges() -> None:
    client = WebSocketClient(url="wss://ws.example")
    extras = [
        Subscription(channel="subscribeOrderbook", params={"symbol": "ETH/USD"}),
        Subscription(channel="subscribeTrades", params={"symbol": "ETH/USD"}),
    ]
    client.extend_subscriptions(extras)
    assert client.subscription_payloads() == [
        {"method": "subscribeOrderbook", "params": {"symbol": "ETH/USD"}},
        {"method": "subscribeTrades", "params": {"symbol": "ETH/USD"}},
    ]
