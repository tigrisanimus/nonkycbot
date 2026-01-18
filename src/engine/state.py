"""State tracking scaffolding for the trading engine."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from engine.order_manager import Order


@dataclass
class EngineState:
    is_running: bool = False
    last_error: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    open_orders: list[Order] = field(default_factory=list)

    def mark_running(self) -> None:
        self.is_running = True
        self.last_error = None

    def mark_error(self, message: str) -> None:
        self.is_running = False
        self.last_error = message

    def update_open_orders(self, orders: Iterable[Order]) -> None:
        self.open_orders = list(orders)

    def to_payload(self) -> dict[str, Any]:
        return {
            "is_running": self.is_running,
            "last_error": self.last_error,
            "config": dict(self.config),
            "open_orders": [self._order_to_dict(order) for order in self.open_orders],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "EngineState":
        orders = [cls._order_from_dict(item) for item in payload.get("open_orders", [])]
        return cls(
            is_running=payload.get("is_running", False),
            last_error=payload.get("last_error"),
            config=dict(payload.get("config", {})),
            open_orders=orders,
        )

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_payload()
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> "EngineState":
        target = Path(path)
        if not target.exists():
            return cls()
        payload = json.loads(target.read_text(encoding="utf-8"))
        return cls.from_payload(payload)

    @staticmethod
    def _order_to_dict(order: Order) -> dict[str, Any]:
        return {
            "order_id": order.order_id,
            "trading_pair": order.trading_pair,
            "side": order.side,
            "price": order.price,
            "amount": order.amount,
        }

    @staticmethod
    def _order_from_dict(payload: dict[str, Any]) -> Order:
        return Order(
            order_id=payload["order_id"],
            trading_pair=payload["trading_pair"],
            side=payload["side"],
            price=payload["price"],
            amount=payload["amount"],
        )
