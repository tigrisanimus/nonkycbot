"""Tests for REST client signing and request formation."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import patch

import pytest

from nonkyc_client.auth import ApiCredentials, AuthSigner
from nonkyc_client.models import OrderRequest
from nonkyc_client.rest import RestClient, RestRequest


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _expected_signature(message: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf8"), message.encode("utf8"), hashlib.sha256
    ).hexdigest()


def test_rest_get_signing_and_request_formation() -> None:
    credentials = ApiCredentials(api_key="test-key", api_secret="test-secret")
    signer = AuthSigner(time_provider=lambda: 1700000000.0)
    client = RestClient(
        base_url="https://api.example", credentials=credentials, signer=signer
    )

    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout=10.0):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse({"data": [{"asset": "USD", "available": "5", "held": "1"}]})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        response = client.send(
            RestRequest(method="GET", path="/balances", params={"limit": 1})
        )

    request = captured["request"]
    assert request.full_url == "https://api.example/balances?limit=1"
    assert request.data is None

    nonce = str(int(1700000000.0 * 1e4))
    data_to_sign = "/balances?limit=1"
    message = f"{credentials.api_key}{data_to_sign}{nonce}"
    expected_signature = _expected_signature(message, credentials.api_secret)

    assert request.headers["X-api-key"] == credentials.api_key
    assert request.headers["X-api-nonce"] == nonce
    assert request.headers["X-api-sign"] == expected_signature
    assert response["data"][0]["asset"] == "USD"


def test_rest_post_signing_and_body_payload() -> None:
    credentials = ApiCredentials(api_key="post-key", api_secret="post-secret")
    signer = AuthSigner(time_provider=lambda: 1700000100.0)
    client = RestClient(
        base_url="https://api.example", credentials=credentials, signer=signer
    )

    order = OrderRequest(
        symbol="BTC/USD",
        side="buy",
        order_type="limit",
        quantity="0.5",
        price="30000",
        user_provided_id="client-1",
        strict_validate=True,
    )

    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout=10.0):
        captured["request"] = request
        return FakeResponse(
            {"data": {"id": "order-1", "status": "open", "symbol": "BTC/USD"}}
        )

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        response = client.place_order(order)

    request = captured["request"]
    assert request.full_url == "https://api.example/api/v2/createorder"
    assert request.headers["Content-type"] == "application/json"

    body = json.loads(request.data.decode("utf8"))
    assert body == {
        "symbol": "BTC/USD",
        "side": "buy",
        "type": "limit",
        "quantity": "0.5",
        "price": "30000",
        "userProvidedId": "client-1",
        "strictValidate": True,
    }

    nonce = str(int(1700000100.0 * 1e4))
    data_to_sign = "/api/v2/createorder" + json.dumps(body, separators=(",", ":"))
    message = f"{credentials.api_key}{data_to_sign}{nonce}"
    expected_signature = _expected_signature(message, credentials.api_secret)

    assert request.headers["X-api-key"] == credentials.api_key
    assert request.headers["X-api-nonce"] == nonce
    assert request.headers["X-api-sign"] == expected_signature
    assert response.order_id == "order-1"


def test_rest_debug_auth_includes_json_str(capsys, monkeypatch) -> None:
    monkeypatch.setenv("NONKYC_DEBUG_AUTH", "1")
    credentials = ApiCredentials(api_key="post-key", api_secret="post-secret")
    signer = AuthSigner(time_provider=lambda: 1700000100.0)
    client = RestClient(
        base_url="https://api.example", credentials=credentials, signer=signer
    )

    order = OrderRequest(
        symbol="ETH/USD",
        side="sell",
        order_type="limit",
        quantity="1.2",
        price="2500",
    )

    def fake_urlopen(request, timeout=10.0):
        return FakeResponse({"data": {"id": "order-2", "status": "open"}})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        client.place_order(order)

    captured = capsys.readouterr().out
    body = order.to_payload()
    expected_json_str = json.dumps(body, separators=(",", ":"))

    assert "NONKYC_DEBUG_AUTH=1" in captured
    assert f"json_str={expected_json_str}" in captured


@pytest.mark.parametrize("value", ["", None])
def test_rest_parse_retry_after_returns_none(value: str | None) -> None:
    client = RestClient(base_url="https://api.example")
    assert client._parse_retry_after(value) is None


def test_rest_signing_can_use_absolute_url() -> None:
    credentials = ApiCredentials(api_key="full-url-key", api_secret="full-url-secret")
    signer = AuthSigner(time_provider=lambda: 1700000200.0)
    client = RestClient(
        base_url="https://api.example",
        credentials=credentials,
        signer=signer,
        sign_absolute_url=True,
    )

    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout=10.0):
        captured["request"] = request
        return FakeResponse({"data": [{"asset": "USD", "available": "5", "held": "1"}]})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        response = client.send(
            RestRequest(method="GET", path="/balances", params={"limit": 1})
        )

    request = captured["request"]
    assert request.full_url == "https://api.example/balances?limit=1"
    assert request.data is None

    nonce = str(int(1700000200.0 * 1e4))
    data_to_sign = "https://api.example/balances?limit=1"
    message = f"{credentials.api_key}{data_to_sign}{nonce}"
    expected_signature = _expected_signature(message, credentials.api_secret)

    assert request.headers["X-api-key"] == credentials.api_key
    assert request.headers["X-api-nonce"] == nonce
    assert request.headers["X-api-sign"] == expected_signature
    assert response["data"][0]["asset"] == "USD"


def test_cancel_all_orders_success_sets_last_response() -> None:
    credentials = ApiCredentials(api_key="cancel-key", api_secret="cancel-secret")
    signer = AuthSigner(time_provider=lambda: 1700000300.0)
    client = RestClient(
        base_url="https://api.example", credentials=credentials, signer=signer
    )

    def fake_urlopen(request, timeout=10.0):
        return FakeResponse({"data": {"success": True, "status": "Cancelled"}})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        success = client.cancel_all_orders("BTC_USDT")

    assert success is True
    assert client.last_cancel_all_response == {"success": True, "status": "Cancelled"}


def test_cancel_all_orders_failure_sets_last_response() -> None:
    credentials = ApiCredentials(api_key="cancel-key", api_secret="cancel-secret")
    signer = AuthSigner(time_provider=lambda: 1700000400.0)
    client = RestClient(
        base_url="https://api.example", credentials=credentials, signer=signer
    )

    def fake_urlopen(request, timeout=10.0):
        return FakeResponse({"data": {"success": False, "error": "Denied"}})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        success = client.cancel_all_orders("BTC_USDT")

    assert success is False
    assert client.last_cancel_all_response == {"success": False, "error": "Denied"}
