"""Shared data models for NonKYC clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class TradingPair:
    base: str
    quote: str

    @property
    def symbol(self) -> str:
        return f"{self.base}/{self.quote}"


@dataclass(frozen=True)
class Balance:
    asset: str
    available: str
    held: str


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: str
    order_type: str
    quantity: str
    price: str | None = None
    user_provided_id: str | None = None
    strict_validate: bool | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "side": self.side,
            "type": self.order_type,
            "quantity": self.quantity,
        }
        if self.price is not None:
            payload["price"] = self.price
        if self.user_provided_id is not None:
            payload["userProvidedId"] = self.user_provided_id
        if self.strict_validate is not None:
            payload["strictValidate"] = self.strict_validate
        return payload


@dataclass(frozen=True)
class OrderResponse:
    order_id: str
    symbol: str
    status: str
    raw_payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderStatus:
    order_id: str
    symbol: str
    status: str
    filled_quantity: str | None = None
    remaining_quantity: str | None = None
    raw_payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderCancelResult:
    order_id: str
    success: bool
    raw_payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketTicker:
    symbol: str
    last_price: str
    bid: str | None = None
    ask: str | None = None
    volume: str | None = None
    raw_payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderBookLevel:
    price: str
    quantity: str


@dataclass(frozen=True)
class OrderBookSnapshot:
    symbol: str
    bids: Sequence[OrderBookLevel]
    asks: Sequence[OrderBookLevel]
    timestamp: float | None = None
    raw_payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Trade:
    trade_id: str
    symbol: str
    price: str
    quantity: str
    side: str | None = None
    timestamp: float | None = None
    raw_payload: Mapping[str, Any] = field(default_factory=dict)
