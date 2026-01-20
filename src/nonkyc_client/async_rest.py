"""Async REST client implementation for nonkyc.io exchange APIs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import ssl
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

import aiohttp

from nonkyc_client.auth import ApiCredentials, AuthSigner
from nonkyc_client.models import (
    Balance,
    MarketTicker,
    OrderCancelResult,
    OrderRequest,
    OrderResponse,
    OrderStatus,
)
from nonkyc_client.time_sync import TimeSynchronizer

# Import rate limiter if available (optional dependency)
try:
    from utils.rate_limiter import AsyncRateLimiter
except ImportError:
    AsyncRateLimiter = None  # type: ignore[misc, assignment]


@dataclass
class AsyncRestRequest:
    method: str
    path: str
    params: Mapping[str, Any] | None = None
    body: Mapping[str, Any] | None = None


class AsyncRestError(Exception):
    """Base exception for async REST client errors."""


class AsyncRateLimitError(AsyncRestError):
    """Raised when the API indicates that the rate limit has been exceeded."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AsyncTransientApiError(AsyncRestError):
    """Raised for transient REST errors that may succeed on retry."""


class AsyncRestClient:
    """Async REST client with retry and rate-limit handling."""

    def __init__(
        self,
        base_url: str,
        credentials: ApiCredentials | None = None,
        signer: AuthSigner | None = None,
        time_synchronizer: TimeSynchronizer | None = None,
        use_server_time: bool | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        debug_auth: bool | None = None,
        sign_absolute_url: bool | None = None,
        session: aiohttp.ClientSession | None = None,
        rate_limiter: Any | None = None,  # AsyncRateLimiter instance (optional)
        verify_ssl: bool = True,  # Enable SSL certificate verification
        ssl_context: ssl.SSLContext | None = None,  # Custom SSL context
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.credentials = credentials
        self._rate_limiter = rate_limiter
        self._ssl_context = ssl_context
        if ssl_context is None and verify_ssl:
            # Create default SSL context with certificate verification
            self._ssl_context = ssl.create_default_context()
        elif ssl_context is None and not verify_ssl:
            # Disable certificate verification (NOT recommended for production)
            self._ssl_context = ssl._create_unverified_context()
            logging.warning(
                "SSL certificate verification is DISABLED. "
                "This should NEVER be used in production environments. "
                "Man-in-the-middle attacks are possible."
            )
        env_use_server_time = os.getenv("NONKYC_USE_SERVER_TIME")
        if use_server_time is None:
            use_server_time = env_use_server_time == "1"
        self._time_synchronizer = (
            time_synchronizer
            if time_synchronizer is not None
            else (TimeSynchronizer() if use_server_time else None)
        )
        resolved_time_provider = (
            self._time_synchronizer.time if self._time_synchronizer else None
        )
        if signer is None:
            self.signer = AuthSigner(time_provider=resolved_time_provider)
        else:
            self.signer = signer
            if (
                resolved_time_provider is not None
                and self.signer.uses_default_time_provider()
            ):
                self.signer.set_time_provider(resolved_time_provider)
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        env_debug = os.getenv("NONKYC_DEBUG_AUTH")
        self.debug_auth = debug_auth if debug_auth is not None else env_debug == "1"
        env_sign_full_url = os.getenv("NONKYC_SIGN_FULL_URL")
        if sign_absolute_url is None:
            self.sign_absolute_url = (
                True if env_sign_full_url is None else env_sign_full_url == "1"
            )
        else:
            self.sign_absolute_url = sign_absolute_url
        self._last_cancel_all_response: dict[str, Any] | None = None
        self._session = session
        self._owns_session = session is None

    @property
    def last_cancel_all_response(self) -> dict[str, Any] | None:
        return self._last_cancel_all_response

    def build_url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    async def send(self, request: AsyncRestRequest) -> dict[str, Any]:
        # Apply rate limiting if configured
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire()

        attempts = 0
        while True:
            try:
                return await self._send_once(request)
            except AsyncRateLimitError as exc:
                attempts += 1
                if attempts > self.max_retries:
                    raise
                delay = exc.retry_after or self._compute_backoff(attempts)
                await asyncio.sleep(delay)
            except AsyncTransientApiError:
                attempts += 1
                if attempts > self.max_retries:
                    raise
                await asyncio.sleep(self._compute_backoff(attempts))

    async def _send_once(self, request: AsyncRestRequest) -> dict[str, Any]:
        base_url = self.build_url(request.path)
        url = base_url
        params = dict(request.params or {})
        body = dict(request.body or {})
        headers = {"Accept": "application/json"}

        if request.method.upper() == "GET" and params:
            url = f"{url}?{self.signer.serialize_query(params)}"

        data_bytes = None
        if request.method.upper() != "GET" and body:
            body_str = self.signer.serialize_body(body)
            data_bytes = body_str.encode("utf8")
            headers["Content-Type"] = "application/json"

        if self.credentials is not None:
            url_to_sign = base_url if self.sign_absolute_url else request.path
            signed = self.signer.build_rest_headers(
                credentials=self.credentials,
                method=request.method,
                url=url_to_sign,
                params=params if request.method.upper() == "GET" else None,
                body=(body if request.method.upper() != "GET" and body else None),
            )
            headers.update(signed.headers)
            if self.debug_auth:
                # WARNING: Debug mode exposes sensitive authentication data
                # NEVER use NONKYC_DEBUG_AUTH=1 in production environments
                print(
                    "\n".join(
                        [
                            "*** NONKYC_DEBUG_AUTH=1 - DEVELOPMENT ONLY ***",
                            f"method={request.method.upper()}",
                            f"url={url}",
                            f"nonce={signed.nonce}",
                            f"json_str={signed.json_str or ''}",
                            f"data_to_sign={signed.data_to_sign}",
                            f"signature=[REDACTED - {len(signed.signature)} chars]",
                            f"api_key=[REDACTED - {len(self.credentials.api_key) if self.credentials else 0} chars]",
                            "*** DO NOT USE IN PRODUCTION ***",
                        ]
                    )
                )

        session = await self._ensure_session()
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        try:
            async with session.request(
                request.method.upper(),
                url,
                headers=headers,
                data=data_bytes,
                timeout=timeout,
            ) as response:
                payload = await response.text()
                if response.status == 429:
                    retry_after = self._parse_retry_after(
                        response.headers.get("Retry-After")
                    )
                    raise AsyncRateLimitError(
                        "Rate limit exceeded", retry_after=retry_after
                    )
                if response.status == 401:
                    raise AsyncRestError(
                        self._build_unauthorized_message(payload, request.path)
                    )
                if response.status in {500, 502, 503, 504}:
                    raise AsyncTransientApiError(
                        f"Transient HTTP error {response.status}"
                    )
                if response.status >= 400:
                    raise AsyncRestError(
                        self._build_http_error_message(response.status, payload)
                    )
        except aiohttp.ClientError as exc:
            raise AsyncTransientApiError("Network error while contacting API") from exc

        if not payload:
            return {}
        return json.loads(payload)

    async def close(self) -> None:
        if self._session is not None and self._owns_session:
            await self._session.close()
            self._session = None
            self._owns_session = False

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            # Create TCP connector with SSL context
            connector = aiohttp.TCPConnector(ssl=self._ssl_context)
            self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return self._session

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
        if not payload:
            return guidance
        return f"{guidance} Response: {payload}"

    def _build_http_error_message(self, status_code: int, payload: str) -> str:
        if payload:
            return f"HTTP error {status_code}: {payload}"
        return f"HTTP error {status_code}"

    def _detect_min_notional_error(self, payload: str) -> str | None:
        if not payload:
            return None
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
        error_code = self._extract_error_code(data)
        if error_code is None:
            return None
        resolved = self._min_notional_error_codes().get(error_code)
        if resolved:
            return resolved
        error_message = self._extract_error_message(data)
        if error_message and self._mentions_min_notional(error_message):
            return self._min_notional_default_message()
        return None

    def _extract_error_code(self, payload: Any) -> str | None:
        if isinstance(payload, dict):
            for key in ("code", "error_code", "errorCode"):
                if key in payload and payload[key] is not None:
                    return str(payload[key])
        return None

    def _extract_error_message(self, payload: Any) -> str | None:
        if isinstance(payload, dict):
            for key in ("message", "error", "errorMessage"):
                if key in payload and payload[key] is not None:
                    return str(payload[key])
        return None

    def _mentions_min_notional(self, message: str) -> bool:
        return "notional" in message.lower()

    def _min_notional_default_message(self) -> str:
        return (
            "Order rejected: minimum notional requirement not met. "
            "Increase order size or adjust configuration."
        )

    def _min_notional_error_codes(self) -> dict[str, str]:
        return {"-1013": self._min_notional_default_message()}

    def _extract_payload(self, response: dict[str, Any]) -> Any:
        return response.get("data", response.get("result", response))

    async def get_balances(self) -> list[Balance]:
        response = await self.send(AsyncRestRequest(method="GET", path="/balances"))
        payload = self._extract_payload(response) or []
        balances: list[Balance] = []
        for item in payload:
            balances.append(
                Balance(
                    asset=str(item.get("asset", "")),
                    available=str(item.get("available", "0")),
                    held=str(item.get("held", "0")),
                )
            )
        return balances

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        payload = order.to_payload()
        response = await self.send(
            AsyncRestRequest(method="POST", path="/api/v2/createorder", body=payload)
        )
        data = self._extract_payload(response) or {}
        status = str(data.get("status", ""))
        symbol = str(data.get("symbol", order.symbol))
        return OrderResponse(
            order_id=str(data.get("id", "")),
            symbol=symbol,
            status=status,
            raw_payload=data,
        )

    async def cancel_order(
        self, order_id: str, symbol: str | None = None
    ) -> OrderCancelResult:
        body = {"order_id": order_id}
        if symbol:
            body["symbol"] = symbol
        response = await self.send(
            AsyncRestRequest(method="POST", path="/api/v2/cancelorder", body=body)
        )
        payload = self._extract_payload(response) or {}
        success = bool(payload.get("success") or payload.get("status") == "Cancelled")
        return OrderCancelResult(
            order_id=order_id, success=success, raw_payload=payload
        )

    async def cancel_all_orders(
        self, symbol: str | None, side: str | None = None
    ) -> bool:
        body: dict[str, Any] = {}
        if symbol:
            body["symbol"] = symbol
        if side:
            body["side"] = side
        response = await self.send(
            AsyncRestRequest(method="POST", path="/api/v2/cancelallorders", body=body)
        )
        payload = self._extract_payload(response) or {}
        if isinstance(payload, list):
            resolved_payload: dict[str, Any] = {"orders": payload}
        else:
            resolved_payload = dict(payload)
        self._last_cancel_all_response = resolved_payload
        return bool(
            resolved_payload.get("success")
            or resolved_payload.get("status") == "Cancelled"
            or resolved_payload.get("ok") is True
        )

    async def get_order_status(self, order_id: str) -> OrderStatus:
        response = await self.send(
            AsyncRestRequest(method="GET", path=f"/api/v2/getorder/{order_id}")
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

    async def get_market_data(self, symbol: str) -> MarketTicker:
        response = await self.send(
            AsyncRestRequest(method="GET", path=f"/api/v2/ticker/{symbol}")
        )
        payload = self._extract_payload(response) or {}
        last_price = _resolve_last_price(payload, symbol)
        return MarketTicker(
            symbol=str(payload.get("symbol", symbol)),
            last_price=last_price,
            bid=str(payload.get("bid", "")) if "bid" in payload else None,
            ask=str(payload.get("ask", "")) if "ask" in payload else None,
            volume=str(payload.get("volume", "")) if "volume" in payload else None,
            raw_payload=payload,
        )


def _resolve_last_price(payload: Mapping[str, Any], symbol: str) -> str:
    for key in ("last_price", "last", "lastPrice", "price"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    bid = _parse_decimal(payload.get("bid"))
    ask = _parse_decimal(payload.get("ask"))
    if bid is not None and ask is not None:
        return str((bid + ask) / Decimal("2"))
    return ""


def _parse_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
