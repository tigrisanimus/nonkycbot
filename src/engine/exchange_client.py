"""Exchange client interface for strategy integrations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class OrderStatusView:
    status: str
    filled_qty: Decimal | None = None
    avg_price: Decimal | None = None
    updated_at: float | None = None


@dataclass(frozen=True)
class OpenOrder:
    order_id: str
    symbol: str
    side: str
    price: Decimal
    quantity: Decimal


class ExchangeClient(Protocol):
    def get_mid_price(self, symbol: str) -> Decimal:
        """Return the current mid price for a symbol."""

    def place_limit(
        self,
        symbol: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        client_id: str | None = None,
    ) -> str:
        """Place a limit order and return the order id."""

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a single order by id."""

    def cancel_all(self, market_id: str, order_type: str = "all") -> bool:
        """Cancel all orders for a market id."""

    def get_order(self, order_id: str) -> OrderStatusView:
        """Fetch the order status."""

    def list_open_orders(self, symbol: str) -> list[OpenOrder]:
        """Return a list of open orders, or an empty list if unsupported."""

    def get_balances(self) -> dict[str, tuple[Decimal, Decimal]]:
        """Return balances as mapping asset -> (available, held)."""
