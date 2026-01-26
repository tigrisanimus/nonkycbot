from __future__ import annotations

from decimal import Decimal

from engine.exchange_client import OpenOrder, OrderStatusView
from nonkyc_client.rest import RestError
from strategies.adaptive_capped_martingale import (
    AdaptiveCappedMartingaleConfig,
    AdaptiveCappedMartingaleStrategy,
    CycleState,
    TrackedOrder,
)


class FakeExchange:
    def __init__(self) -> None:
        self.mid_price = Decimal("100")
        self.best_bid = Decimal("99")
        self.best_ask = Decimal("101")
        self.orders: dict[str, dict[str, Decimal | str]] = {}
        self._counter = 0

    def get_mid_price(self, symbol: str) -> Decimal:
        return self.mid_price

    def get_orderbook_top(self, symbol: str) -> tuple[Decimal, Decimal]:
        return self.best_bid, self.best_ask

    def place_limit(
        self,
        symbol: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        client_id: str | None = None,
    ) -> str:
        self._counter += 1
        order_id = f"order-{self._counter}"
        self.orders[order_id] = {
            "status": "Open",
            "filled_qty": Decimal("0"),
            "avg_price": price,
            "price": price,
            "quantity": quantity,
            "order_type": "limit",
        }
        return order_id

    def place_market(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        client_id: str | None = None,
    ) -> str:
        self._counter += 1
        order_id = f"market-{self._counter}"
        self.orders[order_id] = {
            "status": "Filled",
            "filled_qty": quantity,
            "avg_price": self.mid_price,
            "price": self.mid_price,
            "quantity": quantity,
            "order_type": "market",
        }
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self.orders:
            self.orders[order_id]["status"] = "Canceled"
        return True

    def cancel_all(self, market_id: str, order_type: str = "all") -> bool:
        return True

    def get_order(self, order_id: str) -> OrderStatusView:
        payload = self.orders[order_id]
        return OrderStatusView(
            status=str(payload["status"]),
            filled_qty=payload["filled_qty"],
            avg_price=payload["avg_price"],
        )

    def list_open_orders(self, symbol: str) -> list[OpenOrder]:
        open_orders = []
        for order_id, payload in self.orders.items():
            if payload["status"] in {"Open", "PartiallyFilled"}:
                open_orders.append(
                    OpenOrder(
                        order_id=order_id,
                        symbol=symbol,
                        side="buy",
                        price=payload["price"],
                        quantity=payload["quantity"],
                    )
                )
        return open_orders

    def get_balances(self) -> dict[str, tuple[Decimal, Decimal]]:
        return {}

    def fill_order(
        self, order_id: str, *, filled_qty: Decimal, avg_price: Decimal | None = None
    ) -> None:
        payload = self.orders[order_id]
        payload["filled_qty"] = filled_qty
        if avg_price is not None:
            payload["avg_price"] = avg_price
        if filled_qty >= payload["quantity"]:
            payload["status"] = "Filled"
        else:
            payload["status"] = "PartiallyFilled"


def _build_strategy(tmp_path, exchange: FakeExchange, **overrides):
    cycle_budget = overrides.pop("cycle_budget", Decimal("1000"))
    config = AdaptiveCappedMartingaleConfig(
        symbol="BTC/USDT",
        cycle_budget=cycle_budget,
        **overrides,
    )
    return AdaptiveCappedMartingaleStrategy(
        exchange, config, state_path=tmp_path / "state.json"
    )


def test_fee_aware_avg_entry_and_breakeven(tmp_path) -> None:
    exchange = FakeExchange()
    strategy = _build_strategy(tmp_path, exchange)

    strategy.poll_once(now=0.0)
    order_id = next(iter(exchange.orders))
    order = exchange.orders[order_id]

    avg_entry = strategy._avg_entry()
    assert avg_entry is not None
    expected_fee = order["price"] * order["quantity"] * Decimal("0.002")
    expected_avg = (order["price"] * order["quantity"] + expected_fee) / order[
        "quantity"
    ]
    assert avg_entry == expected_avg

    breakeven = strategy._breakeven_price()
    assert breakeven is not None
    assert breakeven == expected_avg * Decimal("1.005")


def test_min_notional_enforced_for_base_order(tmp_path) -> None:
    exchange = FakeExchange()
    strategy = _build_strategy(tmp_path, exchange, cycle_budget=Decimal("1"))

    strategy.poll_once(now=0.0)

    assert exchange.orders == {}


def test_capped_geometric_sizing(tmp_path) -> None:
    exchange = FakeExchange()
    strategy = _build_strategy(
        tmp_path,
        exchange,
        cycle_budget=Decimal("100"),
        base_order_pct=Decimal("0.10"),
        multiplier=Decimal("1.5"),
        per_order_cap_pct=Decimal("0.15"),
    )
    strategy.state = CycleState(cycle_id="cycle", started_at=0.0)

    assert strategy._next_add_notional(exchange.best_bid) == Decimal("10")
    strategy.state.add_count = 1
    assert strategy._next_add_notional(exchange.best_bid) == Decimal("15")
    strategy.state.add_count = 2
    assert strategy._next_add_notional(exchange.best_bid) == Decimal("15")


def test_min_quantity_enforced_for_base_order(tmp_path) -> None:
    exchange = FakeExchange()
    exchange.best_bid = Decimal("88000")
    strategy = _build_strategy(
        tmp_path,
        exchange,
        cycle_budget=Decimal("66.10"),
        min_order_qty=Decimal("0.000024"),
    )

    strategy.poll_once(now=0.0)

    assert len(exchange.orders) == 1
    order = next(iter(exchange.orders.values()))
    assert order["quantity"] >= Decimal("0.000024")
    assert order["order_type"] == "market"


def test_time_stop_blocks_adds_and_exits_at_breakeven(tmp_path) -> None:
    exchange = FakeExchange()
    strategy = _build_strategy(tmp_path, exchange, time_stop_seconds=0)

    strategy.poll_once(now=0.0)
    base_order_id = next(iter(exchange.orders))
    order = exchange.orders[base_order_id]
    exchange.fill_order(
        base_order_id, filled_qty=order["quantity"], avg_price=order["price"]
    )
    exchange.mid_price = Decimal("90")

    strategy.poll_once(now=1.0)

    assert not any(
        tracked.role.startswith("add")
        for tracked in strategy.state.open_orders.values()
    )
    assert strategy.state.time_stop_triggered

    exchange.mid_price = Decimal("200")
    strategy.poll_once(now=2.0)

    assert any(tracked.role == "tp2" for tracked in strategy.state.open_orders.values())


def test_partial_exit_then_full_exit(tmp_path) -> None:
    exchange = FakeExchange()
    exchange.best_bid = Decimal("100")
    strategy = _build_strategy(
        tmp_path,
        exchange,
        tp1_pct=Decimal("0.01"),
        tp2_pct=Decimal("0.02"),
    )

    strategy.poll_once(now=0.0)
    base_order_id = next(iter(exchange.orders))
    order = exchange.orders[base_order_id]
    exchange.fill_order(
        base_order_id, filled_qty=order["quantity"], avg_price=order["price"]
    )

    exchange.mid_price = Decimal("101.5")
    strategy.poll_once(now=1.0)

    tp1_order = next(iter(strategy.state.open_orders.values()))
    assert tp1_order.role == "tp1"
    assert tp1_order.quantity == order["quantity"] * Decimal("0.5")

    exchange.fill_order(tp1_order.order_id, filled_qty=tp1_order.quantity)
    exchange.mid_price = Decimal("101.5")
    strategy.poll_once(now=2.0)

    exchange.mid_price = Decimal("103")
    strategy.poll_once(now=3.0)
    tp2_order = next(iter(strategy.state.open_orders.values()))
    assert tp2_order.role == "tp2"


def test_restart_does_not_duplicate_orders(tmp_path) -> None:
    exchange = FakeExchange()
    strategy = _build_strategy(tmp_path, exchange)

    strategy.poll_once(now=0.0)
    assert len(exchange.orders) == 1
    first_order = next(iter(exchange.orders.values()))
    assert first_order["order_type"] == "market"
    strategy.save_state()

    restart_strategy = _build_strategy(tmp_path, exchange)
    restart_strategy.load_state()
    restart_strategy.poll_once(now=1.0)

    assert len(exchange.orders) == 2
    market_orders = [
        order for order in exchange.orders.values() if order["order_type"] == "market"
    ]
    assert len(market_orders) == 1


def test_add_order_seeded_after_base_buy(tmp_path) -> None:
    exchange = FakeExchange()
    strategy = _build_strategy(tmp_path, exchange)

    strategy.poll_once(now=0.0)
    strategy.poll_once(now=1.0)

    assert len(strategy.state.open_orders) == 1
    tracked = next(iter(strategy.state.open_orders.values()))
    assert tracked.role == "add-1"
    expected_trigger = exchange.mid_price * (Decimal("1") - strategy.config.step_pct)
    assert tracked.price == expected_trigger


def test_market_base_followed_by_limit_tp1(tmp_path) -> None:
    exchange = FakeExchange()
    strategy = _build_strategy(tmp_path, exchange, tp1_pct=Decimal("0.01"))

    strategy.poll_once(now=0.0)

    assert strategy.state is not None
    assert strategy.state.total_btc > 0
    assert strategy.state.open_orders == {}

    exchange.best_ask = Decimal("101.3")
    exchange.mid_price = Decimal("101.3")
    strategy.poll_once(now=1.0)

    assert len(strategy.state.open_orders) == 1
    tracked = next(iter(strategy.state.open_orders.values()))
    assert tracked.role == "tp1"
    assert exchange.orders[tracked.order_id]["order_type"] == "limit"


def test_reconcile_drops_not_found_orders_and_reseeds(tmp_path) -> None:
    class NotFoundExchange(FakeExchange):
        def get_order(self, order_id: str) -> OrderStatusView:
            raise RestError("HTTP error 404: Order not found")

        def list_open_orders(self, symbol: str) -> list[OpenOrder]:
            return []

    exchange = NotFoundExchange()
    strategy = _build_strategy(tmp_path, exchange)
    strategy.state = CycleState(cycle_id="cycle", started_at=0.0)
    strategy.state.open_orders["missing-order"] = TrackedOrder(
        order_id="missing-order",
        client_id="client-1",
        role="base",
        side="buy",
        price=Decimal("100"),
        quantity=Decimal("0.01"),
        created_at=0.0,
    )

    strategy.poll_once(now=1.0)

    assert len(exchange.orders) == 1
    assert strategy.state.open_orders == {}
