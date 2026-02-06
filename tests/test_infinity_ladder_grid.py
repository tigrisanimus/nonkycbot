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
        self.placed_orders: list[tuple[str, Decimal, Decimal]] = []

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
        self.placed_orders.append((side, price, quantity))
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

    strategy._place_order("buy", Decimal("100"))

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
    assert not strategy._halted_sides
    assert any(
        "Bad userProvidedId" in record.message for record in caplog.records
    ), "Expected warning for recoverable order error"


def test_sell_insufficient_balance_does_not_block_buy_back(tmp_path) -> None:
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

    class BaseLimitedExchange(FakeExchange):
        def get_balances(self) -> dict[str, tuple[Decimal, Decimal]]:
            return {
                "BTC": (Decimal("0"), Decimal("0")),
                "USDT": (Decimal("1000"), Decimal("0")),
            }

    client = BaseLimitedExchange()
    strategy = InfinityLadderGridStrategy(config, client, tmp_path / "state.json")
    strategy.state.highest_sell_price = Decimal("101")
    strategy.state.lowest_buy_price = Decimal("50")
    strategy.state.open_orders = {
        "order-1": LiveOrder(
            side="sell",
            price=Decimal("101"),
            quantity=Decimal("1"),
            client_id="client-1",
            created_at=0.0,
        )
    }

    strategy.reconcile(now=100.0)

    assert any(
        order[0] == "buy" and order[1] == Decimal("99.99")
        for order in client.placed_orders
    )


def test_seed_ladder_extends_buy_levels_on_restart(tmp_path) -> None:
    class LowerMidExchange(FakeExchange):
        def get_mid_price(self, symbol: str) -> Decimal:
            return Decimal("80")

    config = InfinityLadderGridConfig(
        symbol="BTC/USDT",
        step_mode="pct",
        step_pct=Decimal("0.02"),
        step_abs=None,
        n_buy_levels=5,
        initial_sell_levels=1,
        base_order_size=Decimal("1"),
        min_notional_quote=Decimal("1"),
        fee_buffer_pct=Decimal("0"),
        total_fee_rate=Decimal("0"),
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.001"),
        poll_interval_sec=1.0,
        extend_buy_levels_on_restart=True,
    )
    client = LowerMidExchange()
    strategy = InfinityLadderGridStrategy(config, client, tmp_path / "state.json")
    strategy.state.open_orders = {
        "order-1": LiveOrder(
            side="buy",
            price=Decimal("90"),
            quantity=Decimal("1"),
            client_id="client-1",
            created_at=0.0,
        ),
        "order-2": LiveOrder(
            side="sell",
            price=Decimal("110"),
            quantity=Decimal("1"),
            client_id="client-2",
            created_at=0.0,
        ),
    }
    strategy.state.lowest_buy_price = Decimal("90")

    strategy.seed_ladder()

    buy_prices = sorted(
        order.price
        for order in strategy.state.open_orders.values()
        if order.side == "buy"
    )
    assert buy_prices[0] == Decimal("72.00")
    assert len(buy_prices) == 6


def test_default_sizing_modes_buy_fixed_sell_dynamic(tmp_path) -> None:
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

    strategy.seed_ladder()

    buy_orders = [o for o in strategy.state.open_orders.values() if o.side == "buy"]
    sell_orders = [o for o in strategy.state.open_orders.values() if o.side == "sell"]
    assert buy_orders
    assert sell_orders
    assert buy_orders[0].quantity == Decimal("1")
    assert sell_orders[0].quantity < buy_orders[0].quantity
    assert sell_orders[0].quantity == Decimal("0.990")


def test_fixed_mode_reproduces_legacy_behavior(tmp_path) -> None:
    config = InfinityLadderGridConfig(
        symbol="BTC/USDT",
        step_mode="pct",
        step_pct=Decimal("0.01"),
        step_abs=None,
        n_buy_levels=1,
        initial_sell_levels=1,
        base_order_size=Decimal("1"),
        buy_sizing_mode="fixed",
        sell_sizing_mode="fixed",
        min_notional_quote=Decimal("1"),
        fee_buffer_pct=Decimal("0"),
        total_fee_rate=Decimal("0"),
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.001"),
        poll_interval_sec=1.0,
    )
    client = FakeExchange()
    strategy = InfinityLadderGridStrategy(config, client, tmp_path / "state.json")

    strategy._place_order("sell", Decimal("101"))

    placed_order = next(iter(strategy.state.open_orders.values()))
    assert placed_order.quantity == Decimal("1")


def test_hybrid_mode_clamps_to_min_base_qty(tmp_path) -> None:
    config = InfinityLadderGridConfig(
        symbol="BTC/USDT",
        step_mode="pct",
        step_pct=Decimal("0.01"),
        step_abs=None,
        n_buy_levels=1,
        initial_sell_levels=1,
        base_order_size=Decimal("1"),
        sell_sizing_mode="hybrid",
        target_quote_per_order=Decimal("10"),
        min_base_order_qty=Decimal("0.5"),
        min_notional_quote=Decimal("1"),
        fee_buffer_pct=Decimal("0"),
        total_fee_rate=Decimal("0"),
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.01"),
        poll_interval_sec=1.0,
    )
    client = FakeExchange()
    strategy = InfinityLadderGridStrategy(config, client, tmp_path / "state.json")

    strategy._place_order("sell", Decimal("100"))

    placed_order = next(iter(strategy.state.open_orders.values()))
    assert placed_order.quantity == Decimal("0.5")


def test_hybrid_mode_preserves_min_base_after_quantize(tmp_path) -> None:
    config = InfinityLadderGridConfig(
        symbol="BTC/USDT",
        step_mode="pct",
        step_pct=Decimal("0.01"),
        step_abs=None,
        n_buy_levels=1,
        initial_sell_levels=1,
        base_order_size=Decimal("1"),
        sell_sizing_mode="hybrid",
        target_quote_per_order=Decimal("0.002"),
        min_base_order_qty=Decimal("0.000053"),
        min_notional_quote=Decimal("0.001"),
        fee_buffer_pct=Decimal("0"),
        total_fee_rate=Decimal("0"),
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.00001"),
        poll_interval_sec=1.0,
    )
    strategy = InfinityLadderGridStrategy(
        config, FakeExchange(), tmp_path / "state.json"
    )

    quantity = strategy._resolve_order_quantity("sell", Decimal("100"))

    assert quantity == Decimal("0.00006")


def test_min_constraints_skip_orders(tmp_path) -> None:
    config = InfinityLadderGridConfig(
        symbol="BTC/USDT",
        step_mode="pct",
        step_pct=Decimal("0.01"),
        step_abs=None,
        n_buy_levels=1,
        initial_sell_levels=1,
        base_order_size=Decimal("1"),
        min_order_qty=Decimal("2"),
        min_notional_quote=Decimal("1"),
        fee_buffer_pct=Decimal("0"),
        total_fee_rate=Decimal("0"),
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.001"),
        poll_interval_sec=1.0,
    )
    client = FakeExchange()
    strategy = InfinityLadderGridStrategy(config, client, tmp_path / "state.json")

    strategy._place_order("buy", Decimal("100"))

    assert not strategy.state.open_orders


def test_min_notional_skip_is_deterministic(tmp_path) -> None:
    config = InfinityLadderGridConfig(
        symbol="BTC/USDT",
        step_mode="pct",
        step_pct=Decimal("0.01"),
        step_abs=None,
        n_buy_levels=1,
        initial_sell_levels=1,
        base_order_size=Decimal("1"),
        min_notional_quote=Decimal("500"),
        fee_buffer_pct=Decimal("0"),
        total_fee_rate=Decimal("0"),
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.001"),
        poll_interval_sec=1.0,
    )
    client = FakeExchange()
    strategy = InfinityLadderGridStrategy(config, client, tmp_path / "state.json")

    strategy._place_order("sell", Decimal("100"))

    assert not strategy.state.open_orders


def test_dynamic_sell_qty_decreases_with_price(tmp_path) -> None:
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
    strategy = InfinityLadderGridStrategy(
        config, FakeExchange(), tmp_path / "state.json"
    )

    qty_low = strategy._resolve_order_quantity("sell", Decimal("100"))
    qty_high = strategy._resolve_order_quantity("sell", Decimal("120"))

    assert qty_low is not None
    assert qty_high is not None
    assert qty_high < qty_low


def test_profit_accounting_uses_variable_sell_sizes(tmp_path) -> None:
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
            side="sell",
            price=Decimal("100"),
            quantity=Decimal("0.5"),
            client_id="client-1",
            created_at=0.0,
            cost_basis=Decimal("90"),
        ),
        "order-2": LiveOrder(
            side="sell",
            price=Decimal("105"),
            quantity=Decimal("0.25"),
            client_id="client-2",
            created_at=0.0,
            cost_basis=Decimal("100"),
        ),
    }

    strategy.reconcile(now=0.0)

    assert strategy.state.total_profit_quote == Decimal("6.25")


def test_reconcile_uses_absolute_step_for_sell_and_buy_back(tmp_path) -> None:
    config = InfinityLadderGridConfig(
        symbol="BTC/USDT",
        step_mode="abs",
        step_pct=None,
        step_abs=Decimal("10"),
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
    strategy.state.highest_sell_price = Decimal("130")
    strategy.state.lowest_buy_price = Decimal("50")
    strategy.state.open_orders = {
        "order-1": LiveOrder(
            side="sell",
            price=Decimal("130"),
            quantity=Decimal("1"),
            client_id="client-1",
            created_at=0.0,
        )
    }

    strategy.reconcile(now=0.0)

    assert any(
        order[0] == "sell" and order[1] == Decimal("140.00")
        for order in client.placed_orders
    )
    assert any(
        order[0] == "buy" and order[1] == Decimal("120.00")
        for order in client.placed_orders
    )


def test_reconcile_uses_absolute_step_for_buy_fill(tmp_path) -> None:
    config = InfinityLadderGridConfig(
        symbol="BTC/USDT",
        step_mode="abs",
        step_pct=None,
        step_abs=Decimal("10"),
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
            price=Decimal("80"),
            quantity=Decimal("1"),
            client_id="client-1",
            created_at=0.0,
        )
    }

    strategy.reconcile(now=0.0)

    assert any(
        order[0] == "sell" and order[1] == Decimal("90.00")
        for order in client.placed_orders
    )


def test_dynamic_sell_reduces_inventory_depletion(tmp_path) -> None:
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
    prices = [
        Decimal("100"),
        Decimal("105"),
        Decimal("103"),
        Decimal("110"),
        Decimal("108"),
        Decimal("115"),
    ]

    dynamic_strategy = InfinityLadderGridStrategy(
        config, FakeExchange(), tmp_path / "a.json"
    )
    fixed_config = InfinityLadderGridConfig(
        **{**config.__dict__, "sell_sizing_mode": "fixed"}
    )
    fixed_strategy = InfinityLadderGridStrategy(
        fixed_config, FakeExchange(), tmp_path / "b.json"
    )

    starting_base = Decimal("3")
    remaining_dynamic = starting_base
    remaining_fixed = starting_base
    dynamic_fills = 0
    fixed_fills = 0

    for price in prices:
        buy_qty = dynamic_strategy._resolve_order_quantity("buy", price)
        assert buy_qty == Decimal("1")

        dynamic_qty = dynamic_strategy._resolve_order_quantity("sell", price)
        if dynamic_qty is not None and remaining_dynamic >= dynamic_qty:
            remaining_dynamic -= dynamic_qty
            dynamic_fills += 1

        fixed_qty = fixed_strategy._resolve_order_quantity("sell", price)
        if fixed_qty is not None and remaining_fixed >= fixed_qty:
            remaining_fixed -= fixed_qty
            fixed_fills += 1

    assert dynamic_fills >= fixed_fills
    assert remaining_dynamic >= remaining_fixed
