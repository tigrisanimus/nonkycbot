import logging
import re
from decimal import Decimal

from engine.exchange_client import OpenOrder, OrderStatusView
from nonkyc_client.rest import RestError
from strategies.infinity_ladder_grid import (
    InfinityLadderGridConfig,
    InfinityLadderGridStrategy,
    LiveOrder,
)


class FakeExchange:
    def __init__(self) -> None:
        self._order_count = 0
        self.last_client_id: str | None = None

    def get_mid_price(self, symbol: str) -> Decimal:
        return Decimal("100")

    def get_order(self, order_id: str) -> OrderStatusView:
        return OrderStatusView(status="Filled")

    def place_limit(
        self,
        symbol: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        client_id: str | None = None,
    ) -> str:
        self._order_count += 1
        self.last_client_id = client_id
        return f"order-{self._order_count}"

    def place_market(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        client_id: str | None = None,
    ) -> str:
        self._order_count += 1
        return f"market-{self._order_count}"

    def cancel_order(self, order_id: str) -> bool:
        return True

    def cancel_all(self, market_id: str, order_type: str = "all") -> bool:
        return True

    def get_balances(self) -> dict[str, tuple[Decimal, Decimal]]:
        return {}

    def get_orderbook_top(self, symbol: str) -> tuple[Decimal, Decimal]:
        return (Decimal("99"), Decimal("101"))

    def list_open_orders(self, symbol: str) -> list[OpenOrder]:
        return []


def test_reconcile_accepts_capitalized_filled_status(tmp_path) -> None:
    config = InfinityLadderGridConfig(
        symbol="BTC/USDT",
        step_mode="pct",
        step_pct=Decimal("0.01"),
        step_abs=None,
        n_buy_levels=1,
        initial_sell_levels=1,
        base_order_size=Decimal("1"),
        min_notional_quote=Decimal("1"),
        fee_buffer_pct=Decimal("0"),
        total_fee_rate=Decimal("0"),
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.001"),
        poll_interval_sec=1.0,
    )
    client = FakeExchange()
    strategy = InfinityLadderGridStrategy(config, client, tmp_path / "state.json")
    strategy.state.open_orders = {
        "order-1": LiveOrder(
            side="buy",
            price=Decimal("100"),
            quantity=Decimal("1"),
            client_id="client-1",
            created_at=0.0,
        )
    }

    strategy.reconcile(now=0.0)

    assert "order-1" not in strategy.state.open_orders
    assert any(order.side == "sell" for order in strategy.state.open_orders.values())


def test_place_order_uses_uuid_client_id(tmp_path) -> None:
    config = InfinityLadderGridConfig(
        symbol="BTC/USDT",
        step_mode="pct",
        step_pct=Decimal("0.01"),
        step_abs=None,
        n_buy_levels=1,
        initial_sell_levels=1,
        base_order_size=Decimal("1"),
        min_notional_quote=Decimal("1"),
        fee_buffer_pct=Decimal("0"),
        total_fee_rate=Decimal("0"),
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.001"),
        poll_interval_sec=1.0,
    )
    client = FakeExchange()
    strategy = InfinityLadderGridStrategy(config, client, tmp_path / "state.json")

    strategy._place_order("buy", Decimal("100"), Decimal("1"))

    assert client.last_client_id is not None
    assert re.match(r"^infinity-buy-[0-9a-f]{32}$", client.last_client_id)


def test_reconcile_logs_only_when_refill_order_is_placed(tmp_path, caplog) -> None:
    config = InfinityLadderGridConfig(
        symbol="BTC/USDT",
        step_mode="pct",
        step_pct=Decimal("0.01"),
        step_abs=None,
        n_buy_levels=1,
        initial_sell_levels=1,
        base_order_size=Decimal("1"),
        min_notional_quote=Decimal("1"),
        fee_buffer_pct=Decimal("0"),
        total_fee_rate=Decimal("0"),
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.001"),
        poll_interval_sec=1.0,
    )

    class BalanceLimitedExchange(FakeExchange):
        def get_balances(self) -> dict[str, tuple[Decimal, Decimal]]:
            return {
                "BTC": (Decimal("0"), Decimal("0")),
                "USDT": (Decimal("0"), Decimal("0")),
            }

    client = BalanceLimitedExchange()
    strategy = InfinityLadderGridStrategy(config, client, tmp_path / "state.json")
    strategy.state.open_orders = {
        "order-1": LiveOrder(
            side="buy",
            price=Decimal("100"),
            quantity=Decimal("1"),
            client_id="client-1",
            created_at=0.0,
        )
    }

    with caplog.at_level(logging.INFO):
        strategy.reconcile(now=100.0)

    assert "order-1" not in strategy.state.open_orders
    assert not any(
        "placed sell" in record.message for record in caplog.records
    ), "Expected no placement log when balance is insufficient"


def test_seed_ladder_skips_recoverable_rest_error(tmp_path, caplog) -> None:
    config = InfinityLadderGridConfig(
        symbol="BTC/USDT",
        step_mode="pct",
        step_pct=Decimal("0.01"),
        step_abs=None,
        n_buy_levels=1,
        initial_sell_levels=1,
        base_order_size=Decimal("1"),
        min_notional_quote=Decimal("1"),
        fee_buffer_pct=Decimal("0"),
        total_fee_rate=Decimal("0"),
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.001"),
        poll_interval_sec=1.0,
    )

    class RecoverableErrorExchange(FakeExchange):
        def __init__(self) -> None:
            super().__init__()
            self._fail_once = True

        def place_limit(
            self,
            symbol: str,
            side: str,
            price: Decimal,
            quantity: Decimal,
            client_id: str | None = None,
        ) -> str:
            if self._fail_once:
                self._fail_once = False
                raise RestError("HTTP error 400: Bad userProvidedId")
            return super().place_limit(symbol, side, price, quantity, client_id)

    client = RecoverableErrorExchange()
    strategy = InfinityLadderGridStrategy(config, client, tmp_path / "state.json")

    with caplog.at_level(logging.WARNING):
        strategy.seed_ladder()

    assert len(strategy.state.open_orders) == 1
    assert not strategy._halt_placements
    assert any(
        "Bad userProvidedId" in record.message for record in caplog.records
    ), "Expected warning for recoverable order error"
