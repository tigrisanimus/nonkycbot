"""Exchange client adapter for NonKYC REST APIs."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from engine.exchange_client import ExchangeClient, OpenOrder, OrderStatusView
from nonkyc_client.models import OrderRequest
from nonkyc_client.rest import RestClient


class NonkycRestExchangeClient(ExchangeClient):
    def __init__(self, rest_client: RestClient) -> None:
        self._rest = rest_client

    def get_mid_price(self, symbol: str) -> Decimal:
        ticker = self._rest.get_market_data(symbol)
        if ticker.bid is not None and ticker.ask is not None:
            return (Decimal(ticker.bid) + Decimal(ticker.ask)) / Decimal("2")
        return Decimal(ticker.last_price)

    def place_limit(
        self,
        symbol: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        client_id: str | None = None,
    ) -> str:
        order = OrderRequest(
            symbol=symbol,
            side=side,
            order_type="limit",
            price=str(price),
            quantity=str(quantity),
            user_provided_id=client_id,
        )
        response = self._rest.place_order(order)
        return response.order_id

    def cancel_order(self, order_id: str) -> bool:
        result = self._rest.cancel_order(order_id=order_id)
        return result.success

    def cancel_all(self, market_id: str, order_type: str = "all") -> bool:
        return self._rest.cancel_all_orders_v1(market_id, order_type)

    def get_order(self, order_id: str) -> OrderStatusView:
        response = self._rest.get_order_status(order_id)
        raw = response.raw_payload
        avg_price = self._extract_decimal(
            raw, ("avgPrice", "avg_price", "average", "price")
        )
        filled = self._extract_decimal(raw, ("filled", "filledQty", "filled_qty"))
        updated_at = self._extract_float(
            raw, ("updated", "updatedAt", "timestamp", "time")
        )
        return OrderStatusView(
            status=response.status,
            filled_qty=filled,
            avg_price=avg_price,
            updated_at=updated_at,
        )

    def list_open_orders(self, symbol: str) -> list[OpenOrder]:
        return []

    def get_balances(self) -> dict[str, tuple[Decimal, Decimal]]:
        balances = {}
        for balance in self._rest.get_balances():
            balances[balance.asset] = (
                Decimal(balance.available),
                Decimal(balance.held),
            )
        return balances

    @staticmethod
    def _extract_decimal(payload: Any, keys: tuple[str, ...]) -> Decimal | None:
        if isinstance(payload, dict):
            for key in keys:
                if key in payload and payload[key] is not None:
                    try:
                        return Decimal(str(payload[key]))
                    except Exception:
                        return None
        return None

    @staticmethod
    def _extract_float(payload: Any, keys: tuple[str, ...]) -> float | None:
        if isinstance(payload, dict):
            for key in keys:
                if key in payload and payload[key] is not None:
                    try:
                        return float(payload[key])
                    except Exception:
                        return None
        return None
