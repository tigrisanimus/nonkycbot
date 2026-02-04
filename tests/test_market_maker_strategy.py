from __future__ import annotations

from decimal import Decimal

from engine.exchange_client import OpenOrder, OrderStatusView
from nonkyc_client.rest import RestError
from strategies.market_maker import LiveOrder, MarketMakerConfig, MarketMakerStrategy


class FakeExchange:
    def __init__(
        self,
        *,
        best_bid: Decimal,
        best_ask: Decimal,
        balances: dict[str, tuple[Decimal, Decimal]],
    ) -> None:
        self.best_bid = best_bid
        self.best_ask = best_ask
        self.balances = balances
        self.placed_orders: list[tuple[str, Decimal, Decimal, bool | None]] = []
        self.cancelled_orders: list[str] = []
        self._order_count = 0

    def get_mid_price(self, symbol: str) -> Decimal:
        return (self.best_bid + self.best_ask) / Decimal("2")

    def get_orderbook_top(self, symbol: str) -> tuple[Decimal, Decimal]:
        return (self.best_bid, self.best_ask)

    def place_limit(
        self,
        symbol: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        client_id: str | None = None,
        strict_validate: bool | None = None,
    ) -> str:
        self._order_count += 1
        self.placed_orders.append((side, price, quantity, strict_validate))
        return f"order-{self._order_count}"

    def place_market(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        client_id: str | None = None,
    ) -> str:
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> bool:
        self.cancelled_orders.append(order_id)
        return True

    def cancel_all(self, market_id: str, order_type: str = "all") -> bool:
        return True

    def get_order(self, order_id: str) -> OrderStatusView:
        return OrderStatusView(status="open")

    def list_open_orders(self, symbol: str) -> list[OpenOrder]:
        return []

    def get_balances(self) -> dict[str, tuple[Decimal, Decimal]]:
        return self.balances


class NotFoundCancelExchange(FakeExchange):
    def cancel_order(self, order_id: str) -> bool:
        raise RestError(
            'HTTP error 400: {"error":{"code":20002,"message":"Not found","description":"Active order not found for cancellation"}}'
        )


def build_config() -> MarketMakerConfig:
    return MarketMakerConfig(
        symbol="BTC/USDT",
        base_order_size=Decimal("1"),
        sell_quote_target=Decimal("100"),
        min_notional_quote=Decimal("1"),
        fee_rate=Decimal("0.001"),
        safety_buffer_pct=Decimal("0"),
        inside_spread_pct=Decimal("0.1"),
        inventory_target_pct=Decimal("0.5"),
        inventory_tolerance_pct=Decimal("0.05"),
        inventory_skew_pct=Decimal("0.2"),
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.01"),
        poll_interval_sec=1.0,
        max_order_age_sec=60.0,
        balance_refresh_sec=0.0,
        mode="live",
        post_only=True,
    )


def test_spread_too_small_cancels_orders(tmp_path) -> None:
    client = FakeExchange(
        best_bid=Decimal("100"),
        best_ask=Decimal("100.1"),
        balances={
            "BTC": (Decimal("1"), Decimal("0")),
            "USDT": (Decimal("100"), Decimal("0")),
        },
    )
    config = build_config()
    strategy = MarketMakerStrategy(client, config, state_path=tmp_path / "state.json")
    strategy.state.open_orders = {
        "order-1": LiveOrder(
            side="buy",
            price=Decimal("99"),
            quantity=Decimal("1"),
            client_id="client-1",
            created_at=0.0,
        )
    }

    strategy.poll_once()

    assert client.cancelled_orders == ["order-1"]
    assert not strategy.state.open_orders


def test_places_inside_spread_post_only_orders(tmp_path) -> None:
    client = FakeExchange(
        best_bid=Decimal("100"),
        best_ask=Decimal("102"),
        balances={
            "BTC": (Decimal("2"), Decimal("0")),
            "USDT": (Decimal("1000"), Decimal("0")),
        },
    )
    config = build_config()
    strategy = MarketMakerStrategy(client, config, state_path=tmp_path / "state.json")

    strategy.poll_once()

    assert len(client.placed_orders) == 2
    buy_order = next(order for order in client.placed_orders if order[0] == "buy")
    sell_order = next(order for order in client.placed_orders if order[0] == "sell")
    assert buy_order[1] > Decimal("100")
    assert sell_order[1] < Decimal("102")
    assert buy_order[3] is True
    assert sell_order[3] is True


def test_cancel_ignores_not_found_errors(tmp_path) -> None:
    client = NotFoundCancelExchange(
        best_bid=Decimal("100"),
        best_ask=Decimal("100.1"),
        balances={
            "BTC": (Decimal("1"), Decimal("0")),
            "USDT": (Decimal("100"), Decimal("0")),
        },
    )
    config = build_config()
    strategy = MarketMakerStrategy(client, config, state_path=tmp_path / "state.json")
    strategy.state.open_orders = {
        "order-1": LiveOrder(
            side="buy",
            price=Decimal("99"),
            quantity=Decimal("1"),
            client_id="client-1",
            created_at=0.0,
        )
    }

    strategy.poll_once()

    assert not strategy.state.open_orders
