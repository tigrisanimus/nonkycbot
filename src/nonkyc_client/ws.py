"""WebSocket client scaffolding for NonKYC exchange streams."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from nonkyc_client.auth import ApiCredentials, AuthSigner


@dataclass(frozen=True)
class Subscription:
    channel: str
    params: Mapping[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {"method": self.channel, "params": dict(self.params)}


class WebSocketClient:
    """Minimal WebSocket client for building NonKYC subscriptions."""

    def __init__(
        self,
        url: str,
        credentials: ApiCredentials | None = None,
        signer: AuthSigner | None = None,
    ) -> None:
        self.url = url
        self.credentials = credentials
        self.signer = signer or AuthSigner()
        self.subscriptions: list[Subscription] = []

    def login_payload(self) -> dict[str, Any] | None:
        if self.credentials is None:
            return None
        return self.signer.build_ws_login_payload(self.credentials)

    def subscribe_order_book(
        self, symbol: str, depth: int | None = None
    ) -> Subscription:
        params: dict[str, Any] = {"symbol": symbol}
        if depth is not None:
            params["depth"] = depth
        subscription = Subscription(channel="subscribeOrderbook", params=params)
        self.subscriptions.append(subscription)
        return subscription

    def subscribe_trades(self, symbol: str) -> Subscription:
        subscription = Subscription(
            channel="subscribeTrades", params={"symbol": symbol}
        )
        self.subscriptions.append(subscription)
        return subscription

    def subscribe_account_updates(self) -> list[Subscription]:
        orders_subscription = Subscription(channel="subscribeReports", params={})
        balances_subscription = Subscription(channel="subscribeBalances", params={})
        self.subscriptions.extend([orders_subscription, balances_subscription])
        return [orders_subscription, balances_subscription]

    def list_channels(self) -> list[str]:
        return [sub.channel for sub in self.subscriptions]

    def subscription_payloads(self) -> list[dict[str, Any]]:
        return [subscription.as_payload() for subscription in self.subscriptions]

    def extend_subscriptions(self, subscriptions: Iterable[Subscription]) -> None:
        self.subscriptions.extend(subscriptions)
