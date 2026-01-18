from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from engine.exchange_client import ExchangeClient, OrderStatusView
from strategies.ladder_grid import LadderGridConfig, LadderGridStrategy, LiveOrder


@dataclass
class FakeOrderStatus:
    status: str
    filled_qty: Decimal | None = None
    avg_price: Decimal | None = None


class FakeExchange(ExchangeClient):
    def __init__(self, mid_price: Decimal) -> None:
        self.mid_price = mid_price
        self.placed_orders: list[tuple[str, str, Decimal, Decimal, str | None]] = []
        self.order_statuses: dict[str, OrderStatusView] = {}
        self._next_order_id = 1
        self.cancel_all_calls: list[tuple[str, str]] = []

    def get_mid_price(self, symbol: str) -> Decimal:
        return self.mid_price

    def place_limit(
        self,
        symbol: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        client_id: str | None = None,
    ) -> str:
        order_id = f"order-{self._next_order_id}"
        self._next_order_id += 1
        self.placed_orders.append((symbol, side, price, quantity, client_id))
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        return True

    def cancel_all(self, market_id: str, order_type: str = "all") -> bool:
        self.cancel_all_calls.append((market_id, order_type))
        return True

    def get_order(self, order_id: str) -> OrderStatusView:
        return self.order_statuses.get(order_id, OrderStatusView(status="open"))

    def list_open_orders(self, symbol: str) -> list:
        return []

    def get_balances(self) -> dict[str, tuple[Decimal, Decimal]]:
        return {"MMX": (Decimal("1000"), Decimal("0")), "USDT": (Decimal("1000"), Decimal("0"))}


def _build_config(step_mode: str) -> LadderGridConfig:
    return LadderGridConfig(
        symbol="MMX/USDT",
        step_mode=step_mode,
        step_pct=Decimal("0.01") if step_mode == "pct" else None,
        step_abs=Decimal("1") if step_mode == "abs" else None,
        n_buy_levels=1,
        n_sell_levels=1,
        base_order_size=Decimal("1"),
        min_notional_quote=Decimal("1.05"),
        fee_buffer_pct=Decimal("0"),
        tick_size=Decimal("0"),
        step_size=Decimal("1"),
        poll_interval_sec=1,
        startup_cancel_all=False,
        reconcile_interval_sec=999,
        balance_refresh_sec=0,
    )


def test_min_notional_enforcement() -> None:
    client = FakeExchange(Decimal("1"))
    config = _build_config("abs")
    strategy = LadderGridStrategy(client, config)
    quantity = strategy._resolve_order_quantity(Decimal("0.035"), Decimal("1"))
    assert quantity >= Decimal("30")


def test_ladder_replacement_on_filled_buy() -> None:
    client = FakeExchange(Decimal("100"))
    config = _build_config("abs")
    strategy = LadderGridStrategy(client, config)
    strategy.state.open_orders["order-1"] = LiveOrder(
        side="buy",
        price=Decimal("100"),
        quantity=Decimal("2"),
        client_id="cid",
        created_at=0.0,
    )
    client.order_statuses["order-1"] = OrderStatusView(
        status="filled", filled_qty=Decimal("2"), avg_price=Decimal("100")
    )

    strategy.poll_once()

    assert client.placed_orders
    _, side, price, quantity, _ = client.placed_orders[0]
    assert side == "sell"
    assert price == Decimal("101")
    assert quantity == Decimal("2")


def test_strategy_does_not_call_cancel_all_without_startup() -> None:
    client = FakeExchange(Decimal("100"))
    config = _build_config("abs")
    strategy = LadderGridStrategy(client, config)
    strategy.seed_ladder()
    strategy.poll_once()

    assert client.cancel_all_calls == []
