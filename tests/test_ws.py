"""Tests for WebSocket client subscription handling."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import aiohttp
import pytest

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
        {"method": "subscribeOrderbook", "params": {"symbol": "BTC/USD", "limit": 10}},
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


@pytest.mark.asyncio
async def test_ws_connect_once_sends_payloads_and_dispatches() -> None:
    credentials = ApiCredentials(api_key="key", api_secret="secret")
    signer = MagicMock()
    signer.build_ws_login_payload.return_value = {
        "method": "login",
        "params": {
            "algo": "HS256",
            "pKey": "key",
            "nonce": "n",
            "signature": "sig",
        },
    }

    received: list[dict[str, Any]] = []

    async def handler(payload: dict[str, Any]) -> None:
        received.append(payload)

    class FakeWebSocket:
        def __init__(self, messages: list[Any]) -> None:
            self.sent: list[dict[str, Any]] = []
            self._messages = messages

        async def send_json(self, payload: dict[str, Any]) -> None:
            self.sent.append(payload)

        def __aiter__(self):
            return self

        async def __anext__(self) -> Any:
            if not self._messages:
                raise StopAsyncIteration
            return self._messages.pop(0)

        async def close(self) -> None:
            return None

    class FakeWsContext:
        def __init__(self, ws: FakeWebSocket) -> None:
            self._ws = ws

        async def __aenter__(self) -> FakeWebSocket:
            return self._ws

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    class FakeSession:
        def __init__(self, ws: FakeWebSocket) -> None:
            self.ws = ws

        def ws_connect(self, *args, **kwargs) -> FakeWsContext:
            return FakeWsContext(self.ws)

    message = {
        "method": "subscribeTrades",
        "data": {"symbol": "BTC/USD"},
    }
    ws_message = MagicMock()
    ws_message.type = aiohttp.WSMsgType.TEXT
    ws_message.data = json.dumps(message)

    fake_ws = FakeWebSocket([ws_message])
    session = FakeSession(fake_ws)

    client = WebSocketClient(
        url="wss://ws.example",
        credentials=credentials,
        signer=signer,
    )
    client.subscribe_trades("BTC/USD")
    client.register_handler("subscribeTrades", handler)

    await client.connect_once(session=session)

    assert fake_ws.sent == [
        {
            "method": "login",
            "params": {
                "algo": "HS256",
                "pKey": "key",
                "nonce": "n",
                "signature": "sig",
            },
        },
        {"method": "subscribeTrades", "params": {"symbol": "BTC/USD"}},
    ]
    assert received == [message]
