"""WebSocket client for NonKYC exchange streams."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Mapping

import aiohttp

from nonkyc_client.auth import ApiCredentials, AuthSigner


@dataclass(frozen=True)
class Subscription:
    channel: str
    params: Mapping[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {"method": self.channel, "params": dict(self.params)}


MessageHandler = Callable[[dict[str, Any]], Awaitable[None] | None]


class WebSocketClient:
    """WebSocket client for NonKYC subscriptions with reconnect handling."""

    def __init__(
        self,
        url: str,
        credentials: ApiCredentials | None = None,
        signer: AuthSigner | None = None,
        *,
        reconnect: bool = True,
        reconnect_backoff: float = 1.0,
        max_reconnect_backoff: float = 30.0,
        ping_interval: float | None = 20.0,
    ) -> None:
        self.url = url
        self.credentials = credentials
        self.signer = signer or AuthSigner()
        self.subscriptions: list[Subscription] = []
        self._handlers: dict[str, MessageHandler] = {}
        self._default_handler: MessageHandler | None = None
        self._error_handler: MessageHandler | None = None
        self._running = False
        self._session: aiohttp.ClientSession | None = None
        self._owns_session = False
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reconnect = reconnect
        self._reconnect_backoff = reconnect_backoff
        self._max_reconnect_backoff = max_reconnect_backoff
        self._ping_interval = ping_interval

    def login_payload(self) -> dict[str, Any] | None:
        if self.credentials is None:
            return None
        return self.signer.build_ws_login_payload(self.credentials)

    def subscribe_order_book(
        self, symbol: str, depth: int | None = None
    ) -> Subscription:
        params: dict[str, Any] = {"symbol": symbol}
        if depth is not None:
            params["limit"] = depth
        subscription = Subscription(channel="subscribeOrderbook", params=params)
        self.subscriptions.append(subscription)
        return subscription

    def subscribe_trades(self, symbol: str) -> Subscription:
        subscription = Subscription(
            channel="subscribeTrades", params={"symbol": symbol}
        )
        self.subscriptions.append(subscription)
        return subscription

    def subscribe_account_updates(
        self, *, include_balances: bool = True
    ) -> list[Subscription]:
        orders_subscription = Subscription(channel="subscribeReports", params={})
        self.subscriptions.append(orders_subscription)
        subscriptions = [orders_subscription]
        if include_balances:
            balances_subscription = Subscription(channel="subscribeBalances", params={})
            self.subscriptions.append(balances_subscription)
            subscriptions.append(balances_subscription)
        return subscriptions

    def list_channels(self) -> list[str]:
        return [sub.channel for sub in self.subscriptions]

    def subscription_payloads(self) -> list[dict[str, Any]]:
        return [subscription.as_payload() for subscription in self.subscriptions]

    def extend_subscriptions(self, subscriptions: Iterable[Subscription]) -> None:
        self.subscriptions.extend(subscriptions)

    def register_handler(self, method: str, handler: MessageHandler) -> None:
        self._handlers[method] = handler

    def remove_handler(self, method: str) -> None:
        self._handlers.pop(method, None)

    def set_default_handler(self, handler: MessageHandler | None) -> None:
        self._default_handler = handler

    def set_error_handler(self, handler: MessageHandler | None) -> None:
        self._error_handler = handler

    async def connect_once(self, session: aiohttp.ClientSession | None = None) -> None:
        resolved_session = session
        if resolved_session is None:
            timeout = aiohttp.ClientTimeout(total=None)
            resolved_session = aiohttp.ClientSession(timeout=timeout)
            self._owns_session = True
        self._session = resolved_session
        async with resolved_session.ws_connect(
            self.url, heartbeat=self._ping_interval
        ) as ws:
            self._ws = ws
            login = self.login_payload()
            if login is not None:
                await ws.send_json(login)
            for payload in self.subscription_payloads():
                await ws.send_json(payload)
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    await self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    raise RuntimeError("WebSocket connection error")
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE):
                    break
        self._ws = None
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None
            self._owns_session = False

    async def run_forever(self, session: aiohttp.ClientSession | None = None) -> None:
        self._running = True
        backoff = self._reconnect_backoff
        while self._running:
            try:
                await self.connect_once(session=session)
                backoff = self._reconnect_backoff
                if not self._reconnect:
                    break
            except Exception as exc:  # pragma: no cover - defensive
                await self._dispatch_error(exc)
                if not self._running or not self._reconnect:
                    break
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._max_reconnect_backoff)

    async def close(self) -> None:
        self._running = False
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        if self._session is not None and self._owns_session:
            await self._session.close()
            self._session = None
            self._owns_session = False

    async def _handle_message(self, data: str | bytes) -> None:
        if isinstance(data, bytes):
            text = data.decode("utf8")
        else:
            text = data
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            await self._dispatch_error({"error": "invalid_json", "payload": text})
            return
        await self._dispatch(payload)

    async def _dispatch(self, payload: dict[str, Any]) -> None:
        method = payload.get("method") or payload.get("channel")
        handler = self._handlers.get(method) if method else None
        target = handler or self._default_handler
        if target is None:
            return
        result = target(payload)
        if asyncio.iscoroutine(result):
            await result

    async def _dispatch_error(self, payload: Any) -> None:
        if self._error_handler is None:
            return
        result = self._error_handler(
            {"method": "error", "data": payload}
            if not isinstance(payload, dict)
            else payload
        )
        if asyncio.iscoroutine(result):
            await result
