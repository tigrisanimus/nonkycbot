"""Tests for async REST client signing and request formation."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any

import pytest

from nonkyc_client.async_rest import (
    AsyncRateLimitError,
    AsyncRestClient,
    AsyncRestRequest,
)
from nonkyc_client.auth import ApiCredentials, AuthSigner
from nonkyc_client.models import OrderRequest


class FakeResponse:
    def __init__(
        self,
        status: int,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self._payload = payload
        self.headers = headers or {}

    async def text(self) -> str:
        return json.dumps(self._payload)

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        timeout: Any | None = None,
    ) -> FakeResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "data": data,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)

    async def close(self) -> None:
        return None


def _expected_signature(message: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf8"), message.encode("utf8"), hashlib.sha256
    ).hexdigest()


@pytest.mark.asyncio
async def test_async_rest_get_signing_and_request_formation() -> None:
    credentials = ApiCredentials(api_key="test-key", api_secret="test-secret")
    signer = AuthSigner(time_provider=lambda: 1700000000.0)
    session = FakeSession([FakeResponse(200, {"data": []})])
    client = AsyncRestClient(
        base_url="https://api.example",
        credentials=credentials,
        signer=signer,
        session=session,
    )

    response = await client.send(
        AsyncRestRequest(method="GET", path="/balances", params={"limit": 1})
    )

    assert response["data"] == []
    request = session.requests[0]
    assert request["url"] == "https://api.example/balances?limit=1"

    nonce = str(int(1700000000.0 * 1e4))
    data_to_sign = "https://api.example/balances?limit=1"
    message = f"{credentials.api_key}{data_to_sign}{nonce}"
    expected_signature = _expected_signature(message, credentials.api_secret)

    headers = {key.lower(): value for key, value in request["headers"].items()}
    assert headers["x-api-key"] == credentials.api_key
    assert headers["x-api-nonce"] == nonce
    assert headers["x-api-sign"] == expected_signature


@pytest.mark.asyncio
async def test_async_rest_post_signing_and_body_payload() -> None:
    credentials = ApiCredentials(api_key="post-key", api_secret="post-secret")
    signer = AuthSigner(time_provider=lambda: 1700000100.0)
    session = FakeSession([FakeResponse(200, {"data": {"id": "order-1"}})])
    client = AsyncRestClient(
        base_url="https://api.example",
        credentials=credentials,
        signer=signer,
        session=session,
    )

    order = OrderRequest(
        symbol="BTC/USD",
        side="buy",
        order_type="limit",
        quantity="0.5",
        price="30000",
        user_provided_id="client-1",
    )

    response = await client.place_order(order)

    assert response.order_id == "order-1"
    request = session.requests[0]
    body = json.loads(request["data"].decode("utf8"))
    assert body["symbol"] == "BTC/USD"

    nonce = str(int(1700000100.0 * 1e4))
    expected_payload = json.dumps(body, separators=(",", ":"))
    # URL should match base_url + path (no extra /api/v2 since base_url is just "https://api.example")
    data_to_sign = "https://api.example/createorder" + expected_payload
    message = f"{credentials.api_key}{data_to_sign}{nonce}"
    expected_signature = _expected_signature(message, credentials.api_secret)

    headers = {key.lower(): value for key, value in request["headers"].items()}
    assert headers["x-api-sign"] == expected_signature


@pytest.mark.asyncio
async def test_async_rest_rate_limit_raises_retry_after() -> None:
    session = FakeSession(
        [FakeResponse(429, {"error": "rate"}, headers={"Retry-After": "1.5"})]
    )
    client = AsyncRestClient(
        base_url="https://api.example", session=session, max_retries=0
    )

    with pytest.raises(AsyncRateLimitError) as excinfo:
        await client.send(AsyncRestRequest(method="GET", path="/ping"))

    assert excinfo.value.retry_after == 1.5


@pytest.mark.asyncio
async def test_async_rest_retries_on_timeout() -> None:
    credentials = ApiCredentials(api_key="timeout-key", api_secret="timeout-secret")
    signer = AuthSigner(time_provider=lambda: 1700000000.0)
    call_count = {"count": 0}

    class TimeoutSession:
        def __init__(self) -> None:
            self.requests: list[dict[str, Any]] = []

        def request(
            self,
            method: str,
            url: str,
            headers: dict[str, str] | None = None,
            data: bytes | None = None,
            timeout: Any | None = None,
        ) -> FakeResponse:
            self.requests.append(
                {
                    "method": method,
                    "url": url,
                    "headers": headers or {},
                    "data": data,
                    "timeout": timeout,
                }
            )
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise asyncio.TimeoutError()
            return FakeResponse(200, {"data": {"ok": True}})

        async def close(self) -> None:
            return None

    session = TimeoutSession()
    client = AsyncRestClient(
        base_url="https://api.example",
        credentials=credentials,
        signer=signer,
        session=session,
        max_retries=1,
        backoff_factor=0.0,
    )

    response = await client.send(AsyncRestRequest(method="GET", path="/ping"))

    assert response["data"]["ok"] is True
    assert call_count["count"] == 2


@pytest.mark.asyncio
async def test_async_rest_market_data_uses_bid_ask_mid_when_last_missing() -> None:
    session = FakeSession(
        [FakeResponse(200, {"data": {"symbol": "ETH/USD", "bid": "200", "ask": "210"}})]
    )
    client = AsyncRestClient(base_url="https://api.example", session=session)

    ticker = await client.get_market_data("ETH/USD")

    assert ticker.last_price == "205"
