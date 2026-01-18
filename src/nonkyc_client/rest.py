"""REST client implementation for NonKYC exchange APIs."""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from nonkyc_client.auth import ApiCredentials, AuthSigner
from nonkyc_client.models import (
    Balance,
    MarketTicker,
    OrderCancelResult,
    OrderRequest,
    OrderResponse,
    OrderStatus,
)


@dataclass
class RestRequest:
    method: str
    path: str
    params: Mapping[str, Any] | None = None
    body: Mapping[str, Any] | None = None


class RestError(Exception):
    """Base exception for REST client errors."""


class RateLimitError(RestError):
    """Raised when the API indicates that the rate limit has been exceeded."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TransientApiError(RestError):
    """Raised for transient REST errors that may succeed on retry."""


class RestClient:
    """Minimal REST client with retry and rate-limit handling."""

    def __init__(
        self,
        base_url: str,
        credentials: ApiCredentials | None = None,
        signer: AuthSigner | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        debug_auth: bool | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.credentials = credentials
        self.signer = signer or AuthSigner()
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        env_debug = os.getenv("NONKYC_DEBUG_AUTH")
        self.debug_auth = debug_auth if debug_auth is not None else env_debug == "1"

    def build_url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def send(self, request: RestRequest) -> dict[str, Any]:
        attempts = 0
        while True:
            try:
                return self._send_once(request)
            except RateLimitError as exc:
                attempts += 1
                if attempts > self.max_retries:
                    raise
                delay = exc.retry_after or self._compute_backoff(attempts)
                time.sleep(delay)
            except TransientApiError:
                attempts += 1
                if attempts > self.max_retries:
                    raise
                time.sleep(self._compute_backoff(attempts))

    def _send_once(self, request: RestRequest) -> dict[str, Any]:
        url = self.build_url(request.path)
        params = dict(request.params or {})
        body = dict(request.body or {})
        headers = {"Accept": "application/json"}

        if request.method.upper() == "GET" and params:
            url = f"{url}?{urlencode(params)}"

        data_bytes = None
        if request.method.upper() != "GET" and body:
            body_str = json.dumps(body, separators=(",", ":"))
            data_bytes = body_str.encode("utf8")
            headers["Content-Type"] = "application/json"

        if self.credentials is not None:
            signed = self.signer.build_rest_headers(
                credentials=self.credentials,
                method=request.method,
                url=self.build_url(request.path),
                params=params if request.method.upper() == "GET" else None,
                body=body if request.method.upper() != "GET" else None,
            )
            headers.update(signed.headers)
            if self.debug_auth:
                print(
                    "\n".join(
                        [
                            "NONKYC_DEBUG_AUTH=1",
                            f"method={request.method.upper()}",
                            f"url={url}",
                            f"nonce={signed.nonce}",
                            f"data_to_sign={signed.data_to_sign}",
                            f"signature={signed.signature}",
                            f"headers={signed.headers}",
                            f"body={body if body else ''}",
                        ]
                    )
                )

        http_request = Request(
            url=url, method=request.method.upper(), headers=headers, data=data_bytes
        )
        try:
            with urlopen(http_request, timeout=self.timeout) as response:
                payload = response.read().decode("utf8")
        except HTTPError as exc:
            if exc.code == 429:
                retry_after = self._parse_retry_after(exc.headers.get("Retry-After"))
                raise RateLimitError(
                    "Rate limit exceeded", retry_after=retry_after
                ) from exc
            if exc.code == 401:
                payload = exc.read().decode("utf8") if exc.fp else ""
                raise RestError(
                    self._build_unauthorized_message(payload, request.path)
                ) from exc
            if exc.code in {500, 502, 503, 504}:
                raise TransientApiError(f"Transient HTTP error {exc.code}") from exc
            payload = exc.read().decode("utf8") if exc.fp else ""
            raise RestError(f"HTTP error {exc.code}: {payload}") from exc
        except URLError as exc:
            raise TransientApiError("Network error while contacting API") from exc

        if not payload:
            return {}
        return json.loads(payload)

    def _compute_backoff(self, attempt: int) -> float:
        base = self.backoff_factor * (2 ** (attempt - 1))
        return base + random.uniform(0, base)

    def _parse_retry_after(self, header_value: str | None) -> float | None:
        if header_value is None:
            return None
        try:
            return float(header_value)
        except ValueError:
            return None

    def _build_unauthorized_message(self, payload: str, path: str) -> str:
        guidance = (
            "HTTP error 401: Not Authorized. Verify API key/secret, ensure the key has trading permissions, "
            "confirm any IP whitelist includes your current egress IP (VPN/static IP changes included), "
            "and check for clock skew on this machine. If balance queries succeed but order endpoints fail, "
            "double-check that the API key has trade permissions enabled for private endpoints. If the key "
            "has full access and the IP is correct, regenerate the API key/secret to rule out a stale or "
            "revoked credential."
        )
        guidance = f"{guidance} Endpoint: {path}"
        if payload:
            return f"{guidance} Response payload: {payload}"
        return guidance

    def _extract_payload(self, response: dict[str, Any]) -> Any:
        if isinstance(response, dict):
            for key in ("data", "result"):
                if key in response:
                    return response[key]
        return response

    def get_balances(self) -> list[Balance]:
        response = self.send(RestRequest(method="GET", path="/api/v2/balances"))
        payload = self._extract_payload(response) or []
        return [
            Balance(
                asset=item["asset"],
                available=str(item.get("available", "0")),
                held=str(item.get("held", "0")),
            )
            for item in payload
        ]

    def place_order(self, order: OrderRequest) -> OrderResponse:
        response = self.send(
            RestRequest(
                method="POST", path="/api/v2/createorder", body=order.to_payload()
            )
        )
        payload = self._extract_payload(response) or {}
        order_id = str(payload.get("id", payload.get("orderId", "")))
        status = str(payload.get("status", ""))
        symbol = str(payload.get("symbol", order.symbol))
        return OrderResponse(
            order_id=order_id, symbol=symbol, status=status, raw_payload=payload
        )

    def cancel_order(self, order_id: str) -> OrderCancelResult:
        response = self.send(
            RestRequest(
                method="POST", path="/api/v2/cancelorder", body={"orderId": order_id}
            )
        )
        payload = self._extract_payload(response) or {}
        success = bool(payload.get("success", payload.get("status") == "Cancelled"))
        resolved_id = str(payload.get("id", payload.get("orderId", order_id)))
        return OrderCancelResult(
            order_id=resolved_id, success=success, raw_payload=payload
        )

    def get_order_status(self, order_id: str) -> OrderStatus:
        response = self.send(
            RestRequest(method="GET", path=f"/api/v2/getorder/{order_id}")
        )
        payload = self._extract_payload(response) or {}
        status = str(payload.get("status", ""))
        symbol = str(payload.get("symbol", ""))
        filled = payload.get("filled")
        remaining = payload.get("remaining")
        return OrderStatus(
            order_id=str(payload.get("id", order_id)),
            symbol=symbol,
            status=status,
            filled_quantity=str(filled) if filled is not None else None,
            remaining_quantity=str(remaining) if remaining is not None else None,
            raw_payload=payload,
        )

    def get_market_data(self, symbol: str) -> MarketTicker:
        response = self.send(RestRequest(method="GET", path=f"/api/v2/ticker/{symbol}"))
        payload = self._extract_payload(response) or {}
        return MarketTicker(
            symbol=str(payload.get("symbol", symbol)),
            last_price=str(payload.get("last_price", payload.get("last", ""))),
            bid=str(payload.get("bid", "")) if "bid" in payload else None,
            ask=str(payload.get("ask", "")) if "ask" in payload else None,
            volume=str(payload.get("volume", "")) if "volume" in payload else None,
            raw_payload=payload,
        )
