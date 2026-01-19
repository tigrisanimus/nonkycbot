"""REST client implementation for NonKYC exchange APIs."""

from __future__ import annotations

import json
import logging
import os
import random
import re
import ssl
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from nonkyc_client.auth import ApiCredentials, AuthSigner, SignedHeaders
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
    from utils.rate_limiter import RateLimiter
except ImportError:
    RateLimiter = None  # type: ignore[misc, assignment]


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
        time_synchronizer: TimeSynchronizer | None = None,
        use_server_time: bool | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        debug_auth: bool | None = None,
        sign_absolute_url: bool | None = None,
        rate_limiter: Any | None = None,  # RateLimiter instance (optional)
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

    @property
    def last_cancel_all_response(self) -> dict[str, Any] | None:
        return self._last_cancel_all_response

    def build_url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def send(self, request: RestRequest) -> dict[str, Any]:
        # Apply rate limiting if configured
        if self._rate_limiter is not None:
            self._rate_limiter.acquire()

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

        http_request = Request(
            url=url, method=request.method.upper(), headers=headers, data=data_bytes
        )
        try:
            with urlopen(
                http_request, timeout=self.timeout, context=self._ssl_context
            ) as response:
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
            raise RestError(self._build_http_error_message(exc.code, payload)) from exc
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

    def _build_http_error_message(self, status_code: int, payload: str) -> str:
        min_notional_message = self._detect_min_notional_error(payload)
        if min_notional_message:
            return (
                f"HTTP error {status_code}: {min_notional_message} "
                f"Response payload: {payload}"
            )
        if payload:
            return f"HTTP error {status_code}: {payload}"
        return f"HTTP error {status_code}"

    def _detect_min_notional_error(self, payload: str) -> str | None:
        if not payload:
            return None

        parsed_payload = None
        try:
            parsed_payload = json.loads(payload)
        except json.JSONDecodeError:
            parsed_payload = None

        if parsed_payload is not None:
            error_code = self._extract_error_code(parsed_payload)
            if error_code:
                mapped = self._min_notional_error_codes().get(error_code.lower())
                if mapped:
                    return mapped

            error_message = self._extract_error_message(parsed_payload)
            if error_message and self._mentions_min_notional(error_message.lower()):
                return self._min_notional_default_message()

        if self._mentions_min_notional(payload.lower()):
            return self._min_notional_default_message()
        return None

    def _extract_error_code(self, payload: Any) -> str | None:
        if isinstance(payload, dict):
            for key in ("code", "error_code", "errorCode"):
                if key in payload:
                    return str(payload[key])
            for key in ("error", "errors"):
                nested = payload.get(key)
                if isinstance(nested, dict):
                    for nested_key in ("code", "error_code", "errorCode"):
                        if nested_key in nested:
                            return str(nested[nested_key])
        return None

    def _extract_error_message(self, payload: Any) -> str | None:
        if isinstance(payload, dict):
            for key in ("message", "error", "detail", "details"):
                value = payload.get(key)
                if isinstance(value, str):
                    return value
                if isinstance(value, dict):
                    nested_message = value.get("message")
                    if isinstance(nested_message, str):
                        return nested_message
        return None

    def _mentions_min_notional(self, message: str) -> bool:
        keywords = ("notional", "minimum", "amount")
        if any(keyword in message for keyword in keywords):
            return True
        return re.search(r"\bmin\b", message) is not None

    def _min_notional_default_message(self) -> str:
        return "Minimum order notional requirement not met."

    def _min_notional_error_codes(self) -> dict[str, str]:
        return {
            "min_notional": self._min_notional_default_message(),
            "min_notional_not_met": self._min_notional_default_message(),
        }

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

    def cancel_order(
        self,
        order_id: str | None = None,
        *,
        user_provided_id: str | None = None,
    ) -> OrderCancelResult:
        if user_provided_id:
            body = {"userProvidedId": user_provided_id}
        elif order_id:
            body = {"id": order_id}
        else:
            raise ValueError("Either order_id or user_provided_id must be provided.")
        response = self.send(
            RestRequest(method="POST", path="/api/v2/cancelorder", body=body)
        )
        payload = self._extract_payload(response) or {}
        success = bool(payload.get("success", payload.get("status") == "Cancelled"))
        fallback_id = order_id or user_provided_id or ""
        resolved_id = str(
            payload.get(
                "id", payload.get("orderId", payload.get("userProvidedId", fallback_id))
            )
        )
        return OrderCancelResult(
            order_id=resolved_id, success=success, raw_payload=payload
        )

    def cancel_all_orders(self, symbol: str | None, side: str | None = None) -> bool:
        body: dict[str, Any] = {}
        if symbol:
            body["symbol"] = symbol
        if side is not None:
            body["side"] = side
        response = self.send(
            RestRequest(method="POST", path="/api/v2/cancelallorders", body=body)
        )
        payload = self._extract_payload(response) or {}
        if isinstance(payload, list):
            resolved_payload: dict[str, Any] = {"orders": payload}
        else:
            resolved_payload = dict(payload)
        self._last_cancel_all_response = resolved_payload
        success = bool(
            resolved_payload.get("success")
            or resolved_payload.get("status") == "Cancelled"
            or resolved_payload.get("ok") is True
        )
        return success

    def cancel_all_orders_v1(self, market: str, order_type: str) -> bool:
        if not market:
            raise ValueError("Market is required for cancel-all v1 requests.")
        if order_type not in {"all", "buy", "sell"}:
            raise ValueError("Cancel-all order_type must be one of: all, buy, sell.")
        query = {"market": market, "type": order_type}
        base_url = self.build_url("/api/v1/account/cancelallorders")
        query_str = self.signer.serialize_query(query)
        url = f"{base_url}?{query_str}"
        headers = {"Accept": "application/json"}
        signed: SignedHeaders | None = None
        if self.credentials is not None:
            nonce = self.signer.generate_nonce(multiplier=1e4)
            signed = self.signer.build_headers_for_message(
                credentials=self.credentials,
                data_to_sign=url,
                nonce=nonce,
            )
            headers.update(signed.headers)
            if self.debug_auth:
                # WARNING: Debug mode exposes sensitive authentication data
                # NEVER use NONKYC_DEBUG_AUTH=1 in production environments
                print(
                    "\n".join(
                        [
                            "*** NONKYC_DEBUG_AUTH=1 - DEVELOPMENT ONLY ***",
                            "method=GET",
                            f"url={url}",
                            f"nonce={signed.nonce}",
                            "json_str=",
                            f"data_to_sign={signed.data_to_sign}",
                            f"signature=[REDACTED - {len(signed.signature)} chars]",
                            f"api_key=[REDACTED - {len(self.credentials.api_key) if self.credentials else 0} chars]",
                            "*** DO NOT USE IN PRODUCTION ***",
                        ]
                    )
                )
        http_request = Request(url=url, method="GET", headers=headers)
        try:
            with urlopen(
                http_request, timeout=self.timeout, context=self._ssl_context
            ) as response:
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
                    self._build_unauthorized_message(
                        payload, "/api/v1/account/cancelallorders"
                    )
                ) from exc
            if exc.code in {500, 502, 503, 504}:
                raise TransientApiError(f"Transient HTTP error {exc.code}") from exc
            payload = exc.read().decode("utf8") if exc.fp else ""
            raise RestError(self._build_http_error_message(exc.code, payload)) from exc
        except URLError as exc:
            raise TransientApiError("Network error while contacting API") from exc

        response = {} if not payload else json.loads(payload)
        payload_data = self._extract_payload(response) or {}
        if isinstance(payload_data, list):
            resolved_payload: dict[str, Any] = {"orders": payload_data}
        else:
            resolved_payload = dict(payload_data)
        self._last_cancel_all_response = resolved_payload
        success = bool(
            resolved_payload.get("success")
            or resolved_payload.get("status") == "Cancelled"
            or resolved_payload.get("ok") is True
        )
        return success

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
        last_price = _resolve_last_price(payload)
        return MarketTicker(
            symbol=str(payload.get("symbol", symbol)),
            last_price=last_price,
            bid=str(payload.get("bid", "")) if "bid" in payload else None,
            ask=str(payload.get("ask", "")) if "ask" in payload else None,
            volume=str(payload.get("volume", "")) if "volume" in payload else None,
            raw_payload=payload,
        )

    def get_liquidity_pool(self, symbol: str) -> dict[str, Any]:
        """
        Get liquidity pool information including reserves and pricing.

        Args:
            symbol: Pool symbol (e.g., "COSA/PIRATE")

        Returns:
            Dictionary containing pool data with keys:
            - symbol: Pool trading pair
            - reserve_a: Reserve amount of first token
            - reserve_b: Reserve amount of second token
            - token_a: Symbol of first token
            - token_b: Symbol of second token
            - last_price: Last trade price
            - fee_rate: Pool fee rate
            - raw_payload: Full API response

        Note:
            This method attempts multiple possible API endpoints as the exact
            endpoint may vary. If one fails, it tries alternatives.
        """
        # Try different possible endpoints for liquidity pools
        endpoints = [
            f"/api/v2/pool/{symbol}",
            f"/api/v2/liquiditypool/{symbol}",
            f"/api/v2/pools/{symbol}",
            f"/api/v2/ticker/{symbol}",  # Fallback to ticker endpoint
        ]

        last_error = None
        for endpoint in endpoints:
            try:
                response = self.send(RestRequest(method="GET", path=endpoint))
                payload = self._extract_payload(response) or {}

                if payload:
                    # Normalize the response structure
                    return {
                        "symbol": str(payload.get("symbol", symbol)),
                        "reserve_a": payload.get(
                            "reserveA",
                            payload.get("reserve_a", payload.get("primaryReserve")),
                        ),
                        "reserve_b": payload.get(
                            "reserveB",
                            payload.get("reserve_b", payload.get("secondaryReserve")),
                        ),
                        "token_a": payload.get(
                            "tokenA",
                            payload.get(
                                "token_a", payload.get("primaryAsset", {}).get("ticker")
                            ),
                        ),
                        "token_b": payload.get(
                            "tokenB",
                            payload.get(
                                "token_b",
                                payload.get("secondaryAsset", {}).get("ticker"),
                            ),
                        ),
                        "last_price": payload.get(
                            "lastPrice", payload.get("last_price", payload.get("last"))
                        ),
                        "fee_rate": payload.get(
                            "feeRate",
                            payload.get("fee_rate", payload.get("tradingFee")),
                        ),
                        "raw_payload": payload,
                    }
            except (RestError, HTTPError, URLError) as e:
                last_error = e
                continue

        # If all endpoints failed, raise the last error
        if last_error:
            raise RestError(
                f"Failed to fetch liquidity pool data for {symbol}. "
                f"Pool may not exist or API endpoint may have changed. Last error: {last_error}"
            )
        return {}

    def get_pool_quote(self, symbol: str, side: str, amount: str) -> dict[str, Any]:
        """
        Get a quote for swapping tokens in a liquidity pool.

        Args:
            symbol: Pool symbol (e.g., "COSA/PIRATE")
            side: "buy" or "sell" (which token you're receiving)
            amount: Amount to swap (as string for precision)

        Returns:
            Dictionary containing:
            - amount_in: Input amount
            - amount_out: Expected output amount
            - price: Effective price
            - price_impact: Price impact percentage
            - fee: Fee amount
            - raw_payload: Full API response

        Note:
            This is a read-only operation and does not execute the swap.
        """
        body = {"symbol": symbol, "side": side, "amount": amount}

        endpoints = [
            "/api/v2/pool/quote",
            "/api/v2/swap/quote",
            "/api/v2/pool/calculate",
        ]

        last_error = None
        for endpoint in endpoints:
            try:
                response = self.send(
                    RestRequest(method="POST", path=endpoint, body=body)
                )
                payload = self._extract_payload(response) or {}

                if payload:
                    return {
                        "amount_in": payload.get(
                            "amountIn", payload.get("amount_in", amount)
                        ),
                        "amount_out": payload.get(
                            "amountOut", payload.get("amount_out")
                        ),
                        "price": payload.get("price", payload.get("effectivePrice")),
                        "price_impact": payload.get(
                            "priceImpact", payload.get("price_impact")
                        ),
                        "fee": payload.get("fee", payload.get("feeAmount")),
                        "raw_payload": payload,
                    }
            except (RestError, HTTPError, URLError) as e:
                last_error = e
                continue

        if last_error:
            raise RestError(
                f"Failed to get pool quote for {symbol}. "
                f"Pool swaps may not be supported via API. Last error: {last_error}"
            )
        return {}

    def execute_pool_swap(
        self, symbol: str, side: str, amount: str, min_received: str | None = None
    ) -> dict[str, Any]:
        """
        Execute a swap in a liquidity pool.

        Args:
            symbol: Pool symbol (e.g., "COSA/PIRATE")
            side: "buy" or "sell" (which token you're receiving)
            amount: Amount to swap
            min_received: Minimum amount to receive (slippage protection)

        Returns:
            Dictionary with swap execution result including:
            - swap_id: Unique identifier for the swap
            - amount_in: Actual input amount
            - amount_out: Actual output amount
            - status: Execution status
            - raw_payload: Full API response

        Raises:
            RestError: If swap execution fails
        """
        body: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "amount": amount,
        }

        if min_received is not None:
            body["minReceived"] = min_received

        endpoints = [
            "/api/v2/pool/swap",
            "/api/v2/swap",
            "/api/v2/pool/trade",
        ]

        last_error = None
        for endpoint in endpoints:
            try:
                response = self.send(
                    RestRequest(method="POST", path=endpoint, body=body)
                )
                payload = self._extract_payload(response) or {}

                if payload:
                    return {
                        "swap_id": payload.get(
                            "id", payload.get("swapId", payload.get("tradeId"))
                        ),
                        "amount_in": payload.get("amountIn", payload.get("amount_in")),
                        "amount_out": payload.get(
                            "amountOut", payload.get("amount_out")
                        ),
                        "status": payload.get("status"),
                        "raw_payload": payload,
                    }
            except (RestError, HTTPError, URLError) as e:
                last_error = e
                continue

        if last_error:
            raise RestError(
                f"Failed to execute pool swap for {symbol}. Last error: {last_error}"
            )
        return {}


def _resolve_last_price(payload: Mapping[str, Any]) -> str:
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
