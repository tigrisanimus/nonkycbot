"""Tests for REST client signing and request formation."""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import socket
from typing import Any, Literal
from unittest.mock import patch
from urllib.error import URLError

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

    def __exit__(self, exc_type, exc, tb) -> Literal[False]:
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

    def fake_urlopen(request, timeout=10.0, context=None):
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
    data_to_sign = "https://api.example/balances?limit=1"
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

    def fake_urlopen(request, timeout=10.0, context=None):
        captured["request"] = request
        return FakeResponse(
            {"data": {"id": "order-1", "status": "open", "symbol": "BTC/USD"}}
        )

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        response = client.place_order(order)

    request = captured["request"]
    assert request.full_url == "https://api.example/createorder"
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
    data_to_sign = "https://api.example/createorder" + json.dumps(
        body, separators=(",", ":")
    )
    message = f"{credentials.api_key}{data_to_sign}{nonce}"
    expected_signature = _expected_signature(message, credentials.api_secret)

    assert request.headers["X-api-key"] == credentials.api_key
    assert request.headers["X-api-nonce"] == nonce
    assert request.headers["X-api-sign"] == expected_signature
    assert response.order_id == "order-1"


def test_rest_createorder_signature_string_matches_known_good_format() -> None:
    credentials = ApiCredentials(api_key="sig-key", api_secret="sig-secret")
    signer = AuthSigner(time_provider=lambda: 1700000150.0)
    client = RestClient(
        base_url="https://api.example", credentials=credentials, signer=signer
    )

    order = OrderRequest(
        symbol="ETH/USD",
        side="sell",
        order_type="limit",
        quantity="1.0",
        price="2500",
        user_provided_id="client-2",
    )

    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout=10.0, context=None):
        captured["request"] = request
        return FakeResponse({"data": {"id": "order-2", "status": "open"}})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        client.place_order(order)

    request = captured["request"]
    body = order.to_payload()
    json_str = json.dumps(body, separators=(",", ":"))
    data_to_sign = "https://api.example/createorder" + json_str
    nonce = str(int(1700000150.0 * 1e4))
    message = f"{credentials.api_key}{data_to_sign}{nonce}"
    expected_signature = _expected_signature(message, credentials.api_secret)

    assert request.headers["X-api-sign"] == expected_signature
    assert data_to_sign == "https://api.example/createorder" + json_str


def test_rest_createorder_signature_matches_request_payload() -> None:
    credentials = ApiCredentials(api_key="payload-key", api_secret="payload-secret")
    signer = AuthSigner(time_provider=lambda: 1700000250.0)
    client = RestClient(
        base_url="https://api.example", credentials=credentials, signer=signer
    )

    order = OrderRequest(
        symbol="SOL/USD",
        side="buy",
        order_type="limit",
        quantity="2.5",
        price="95",
    )

    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout=10.0, context=None):
        captured["request"] = request
        return FakeResponse({"data": {"id": "order-3", "status": "open"}})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        client.place_order(order)

    request = captured["request"]
    request_payload = request.data.decode("utf8")
    expected_payload = json.dumps(order.to_payload(), separators=(",", ":"))

    assert request_payload == expected_payload

    nonce = str(int(1700000250.0 * 1e4))
    data_to_sign = f"https://api.example/createorder{request_payload}"
    message = f"{credentials.api_key}{data_to_sign}{nonce}"
    expected_signature = _expected_signature(message, credentials.api_secret)

    assert request.headers["X-api-sign"] == expected_signature


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

    def fake_urlopen(request, timeout=10.0, context=None):
        return FakeResponse({"data": {"id": "order-2", "status": "open"}})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        client.place_order(order)

    captured = capsys.readouterr().out
    body = order.to_payload()
    expected_json_str = json.dumps(body, separators=(",", ":"))

    assert "NONKYC_DEBUG_AUTH=1" in captured
    assert f"json_str={expected_json_str}" in captured
    # signed_message is now redacted for security, check for redaction instead
    assert "signature=[REDACTED" in captured
    assert "api_key=[REDACTED" in captured
    assert "DO NOT USE IN PRODUCTION" in captured


@pytest.mark.parametrize("value", ["", None])
def test_rest_parse_retry_after_returns_none(value: str | None) -> None:
    client = RestClient(base_url="https://api.example")
    assert client._parse_retry_after(value) is None


def test_rest_send_honors_configured_timeout() -> None:
    client = RestClient(base_url="https://api.example", timeout=2.5)
    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout=10.0, context=None):
        captured["timeout"] = timeout
        return FakeResponse({"data": {"ok": True}})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        response = client.send(RestRequest(method="GET", path="/ping"))

    assert response["data"]["ok"] is True
    assert captured["timeout"] == 2.5


def test_rest_send_retries_on_transient_url_error() -> None:
    client = RestClient(
        base_url="https://api.example", timeout=1.0, max_retries=2, backoff_factor=0.5
    )
    call_count = {"count": 0}
    sleep_calls: list[float] = []

    def fake_urlopen(request, timeout=10.0, context=None):
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise URLError("temporary failure")
        return FakeResponse({"data": {"ok": True}})

    def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    with (
        patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen),
        patch("nonkyc_client.rest.time.sleep", side_effect=fake_sleep),
        patch("nonkyc_client.rest.random.uniform", return_value=0.0),
    ):
        response = client.send(RestRequest(method="GET", path="/ping"))

    assert response["data"]["ok"] is True
    assert call_count["count"] == 2
    assert sleep_calls == [0.5]


def test_rest_send_retries_on_timeout_error() -> None:
    client = RestClient(
        base_url="https://api.example", timeout=1.0, max_retries=2, backoff_factor=0.5
    )
    call_count = {"count": 0}
    sleep_calls: list[float] = []

    def fake_urlopen(request, timeout=10.0, context=None):
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise socket.timeout("read timed out")
        return FakeResponse({"data": {"ok": True}})

    def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    with (
        patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen),
        patch("nonkyc_client.rest.time.sleep", side_effect=fake_sleep),
        patch("nonkyc_client.rest.random.uniform", return_value=0.0),
    ):
        response = client.send(RestRequest(method="GET", path="/ping"))

    assert response["data"]["ok"] is True
    assert call_count["count"] == 2
    assert sleep_calls == [0.5]


def test_rest_send_retries_on_remote_disconnected() -> None:
    client = RestClient(
        base_url="https://api.example", timeout=1.0, max_retries=2, backoff_factor=0.5
    )
    call_count = {"count": 0}
    sleep_calls: list[float] = []

    def fake_urlopen(request, timeout=10.0, context=None):
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise http.client.RemoteDisconnected(
                "Remote end closed connection without response"
            )
        return FakeResponse({"data": {"ok": True}})

    def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)

    with (
        patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen),
        patch("nonkyc_client.rest.time.sleep", side_effect=fake_sleep),
        patch("nonkyc_client.rest.random.uniform", return_value=0.0),
    ):
        response = client.send(RestRequest(method="GET", path="/ping"))

    assert response["data"]["ok"] is True
    assert call_count["count"] == 2
    assert sleep_calls == [0.5]


def test_rest_signing_defaults_to_absolute_url() -> None:
    credentials = ApiCredentials(api_key="full-url-key", api_secret="full-url-secret")
    signer = AuthSigner(time_provider=lambda: 1700000200.0)
    client = RestClient(
        base_url="https://api.example", credentials=credentials, signer=signer
    )

    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout=10.0, context=None):
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


def test_rest_signing_can_opt_out_of_absolute_url() -> None:
    credentials = ApiCredentials(api_key="path-key", api_secret="path-secret")
    signer = AuthSigner(time_provider=lambda: 1700000300.0)
    client = RestClient(
        base_url="https://api.example",
        credentials=credentials,
        signer=signer,
        sign_absolute_url=False,
    )

    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout=10.0, context=None):
        captured["request"] = request
        return FakeResponse({"data": [{"asset": "USD", "available": "5", "held": "1"}]})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        response = client.send(
            RestRequest(method="GET", path="/balances", params={"limit": 1})
        )

    request = captured["request"]
    assert request.full_url == "https://api.example/balances?limit=1"
    assert request.data is None

    nonce = str(int(1700000300.0 * 1e4))
    data_to_sign = "/balances?limit=1"
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

    def fake_urlopen(request, timeout=10.0, context=None):
        return FakeResponse({"data": {"success": True, "status": "Cancelled"}})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        success = client.cancel_all_orders("BTC_USDT")

    assert success is True
    assert client.last_cancel_all_response == {"success": True, "status": "Cancelled"}


def test_cancel_all_orders_includes_symbol_in_body() -> None:
    credentials = ApiCredentials(
        api_key="cancel-body-key", api_secret="cancel-body-secret"
    )
    signer = AuthSigner(time_provider=lambda: 1700000350.0)
    client = RestClient(
        base_url="https://api.example", credentials=credentials, signer=signer
    )

    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout=10.0, context=None):
        captured["request"] = request
        return FakeResponse({"data": {"success": True}})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        client.cancel_all_orders("BTC_USDT", "buy")

    request = captured["request"]
    body = json.loads(request.data.decode("utf8"))
    assert body == {"symbol": "BTC_USDT", "side": "buy"}


def test_cancel_all_orders_omits_side_when_none() -> None:
    credentials = ApiCredentials(
        api_key="cancel-none-key", api_secret="cancel-none-secret"
    )
    signer = AuthSigner(time_provider=lambda: 1700000375.0)
    client = RestClient(
        base_url="https://api.example", credentials=credentials, signer=signer
    )

    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout=10.0, context=None):
        captured["request"] = request
        return FakeResponse({"data": {"success": True}})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        client.cancel_all_orders("BTC_USDT")

    request = captured["request"]
    body = json.loads(request.data.decode("utf8"))
    assert body == {"symbol": "BTC_USDT"}


def test_cancel_all_orders_v1_signs_full_url_with_query() -> None:
    credentials = ApiCredentials(api_key="v1-key", api_secret="v1-secret")
    signer = AuthSigner(time_provider=lambda: 1700000500.0)
    client = RestClient(
        base_url="https://api.example", credentials=credentials, signer=signer
    )

    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout=10.0, context=None):
        captured["request"] = request
        return FakeResponse({"data": {"success": True}})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        client.cancel_all_orders_v1("MMX_USDT", "all")

    request = captured["request"]
    expected_url = (
        "https://api.example/api/v1/account/cancelallorders?market=MMX_USDT&type=all"
    )
    assert request.full_url == expected_url

    nonce = str(int(1700000500.0 * 1e4))  # Correct multiplier for NonKYC nonce
    message = f"{credentials.api_key}{expected_url}{nonce}"
    expected_signature = _expected_signature(message, credentials.api_secret)

    assert request.headers["X-api-key"] == credentials.api_key
    assert request.headers["X-api-nonce"] == nonce
    assert request.headers["X-api-sign"] == expected_signature


def test_cancel_all_orders_allows_missing_symbol() -> None:
    credentials = ApiCredentials(
        api_key="cancel-missing-key", api_secret="cancel-missing-secret"
    )
    signer = AuthSigner(time_provider=lambda: 1700000390.0)
    client = RestClient(
        base_url="https://api.example", credentials=credentials, signer=signer
    )

    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout=10.0, context=None):
        captured["request"] = request
        return FakeResponse({"data": {"success": True}})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        client.cancel_all_orders(None, "sell")

    request = captured["request"]
    body = json.loads(request.data.decode("utf8"))
    assert body == {"side": "sell"}


def test_cancel_all_orders_failure_sets_last_response() -> None:
    credentials = ApiCredentials(api_key="cancel-key", api_secret="cancel-secret")
    signer = AuthSigner(time_provider=lambda: 1700000400.0)
    client = RestClient(
        base_url="https://api.example", credentials=credentials, signer=signer
    )

    def fake_urlopen(request, timeout=10.0, context=None):
        return FakeResponse({"data": {"success": False, "error": "Denied"}})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        success = client.cancel_all_orders("BTC_USDT")

    assert success is False
    assert client.last_cancel_all_response == {"success": False, "error": "Denied"}


def test_rest_market_data_accepts_last_price_variants() -> None:
    client = RestClient(base_url="https://api.example")

    def fake_urlopen(request, timeout=10.0, context=None):
        return FakeResponse({"data": {"symbol": "BTC/USD", "lastPrice": "123.45"}})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        ticker = client.get_market_data("BTC/USD")

    assert ticker.last_price == "123.45"


def test_rest_market_data_uses_bid_ask_mid_when_last_missing() -> None:
    client = RestClient(base_url="https://api.example")

    def fake_urlopen(request, timeout=10.0, context=None):
        return FakeResponse({"data": {"symbol": "BTC/USD", "bid": "100", "ask": "110"}})

    with patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen):
        ticker = client.get_market_data("BTC/USD")

    assert ticker.last_price == "105"


class TestCloudflareErrorDetection:
    """Tests for Cloudflare transient error detection."""

    CLOUDFLARE_1018_ERROR_PAGE = """<!DOCTYPE html>
<html class="no-js" lang="en-US">
<head>
<title>Could not find host | api.nonkyc.io | Cloudflare</title>
</head>
<body>
<h1><span>Error</span><span>1018</span></h1>
<h2>Could not find host</h2>
<p>Cloudflare is currently unable to resolve your requested domain (api.nonkyc.io).</p>
</body>
</html>"""

    CLOUDFLARE_522_ERROR_PAGE = """<!DOCTYPE html>
<html class="no-js" lang="en-US">
<head>
<title>Connection timed out | Cloudflare</title>
</head>
<body>
<h1><span>Error</span><span>522</span></h1>
<h2>Connection timed out</h2>
<p>The initial connection between Cloudflare and the origin web server timed out.</p>
</body>
</html>"""

    def test_detects_cloudflare_1018_error(self) -> None:
        client = RestClient(base_url="https://api.example")
        assert client._is_cloudflare_transient_error(self.CLOUDFLARE_1018_ERROR_PAGE)

    def test_detects_cloudflare_522_error(self) -> None:
        client = RestClient(base_url="https://api.example")
        assert client._is_cloudflare_transient_error(self.CLOUDFLARE_522_ERROR_PAGE)

    def test_does_not_detect_non_cloudflare_error(self) -> None:
        client = RestClient(base_url="https://api.example")
        regular_error = '{"error": "Invalid order", "code": "INVALID_ORDER"}'
        assert not client._is_cloudflare_transient_error(regular_error)

    def test_does_not_detect_empty_payload(self) -> None:
        client = RestClient(base_url="https://api.example")
        assert not client._is_cloudflare_transient_error("")

    def test_does_not_detect_cloudflare_without_error_code(self) -> None:
        client = RestClient(base_url="https://api.example")
        # Has Cloudflare but no known error code
        payload = "<html><title>Cloudflare</title><body>Success</body></html>"
        assert not client._is_cloudflare_transient_error(payload)

    def test_cloudflare_error_raises_transient_error_on_http_409(self) -> None:
        import io
        from urllib.error import HTTPError

        from nonkyc_client.rest import TransientApiError

        client = RestClient(
            base_url="https://api.example",
            max_retries=0,  # Don't retry for this test
        )

        def fake_urlopen(request, timeout=10.0, context=None):
            # Create an HTTPError with Cloudflare error page body
            error = HTTPError(
                "https://api.example/getorder/123",
                409,
                "Conflict",
                {},
                io.BytesIO(self.CLOUDFLARE_1018_ERROR_PAGE.encode("utf8")),
            )
            raise error

        with (
            patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen),
            pytest.raises(TransientApiError) as exc_info,
        ):
            client.send(RestRequest(method="GET", path="/getorder/123"))

        assert "Cloudflare transient error" in str(exc_info.value)
        assert "HTTP 409" in str(exc_info.value)

    def test_regular_http_409_raises_rest_error(self) -> None:
        import io
        from urllib.error import HTTPError

        from nonkyc_client.rest import RestError, TransientApiError

        client = RestClient(
            base_url="https://api.example",
            max_retries=0,
        )

        def fake_urlopen(request, timeout=10.0, context=None):
            error = HTTPError(
                "https://api.example/getorder/123",
                409,
                "Conflict",
                {},
                io.BytesIO(b'{"error": "Order already cancelled"}'),
            )
            raise error

        with (
            patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen),
            pytest.raises(RestError) as exc_info,
        ):
            client.send(RestRequest(method="GET", path="/getorder/123"))

        # Should be a RestError, not TransientApiError
        assert not isinstance(exc_info.value, TransientApiError)
        assert "Order already cancelled" in str(exc_info.value)

    def test_cloudflare_error_is_retried(self) -> None:
        import io
        from urllib.error import HTTPError

        client = RestClient(
            base_url="https://api.example",
            max_retries=2,
            backoff_factor=0.1,
        )

        call_count = {"count": 0}
        sleep_calls: list[float] = []

        def fake_urlopen(request, timeout=10.0, context=None):
            call_count["count"] += 1
            if call_count["count"] == 1:
                error = HTTPError(
                    "https://api.example/getorder/123",
                    409,
                    "Conflict",
                    {},
                    io.BytesIO(TestCloudflareErrorDetection.CLOUDFLARE_1018_ERROR_PAGE.encode("utf8")),
                )
                raise error
            return FakeResponse({"data": {"id": "123", "status": "Filled"}})

        def fake_sleep(duration: float) -> None:
            sleep_calls.append(duration)

        with (
            patch("nonkyc_client.rest.urlopen", side_effect=fake_urlopen),
            patch("nonkyc_client.rest.time.sleep", side_effect=fake_sleep),
            patch("nonkyc_client.rest.random.uniform", return_value=0.0),
        ):
            response = client.send(RestRequest(method="GET", path="/getorder/123"))

        assert response["data"]["status"] == "Filled"
        assert call_count["count"] == 2
        assert len(sleep_calls) == 1  # One retry sleep
