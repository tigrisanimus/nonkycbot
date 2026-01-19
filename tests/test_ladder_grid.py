from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from engine import ladder_runner
from engine.exchange_client import ExchangeClient, OrderStatusView
from nonkyc_client.rest import RestError, TransientApiError
from strategies.ladder_grid import (LadderGridConfig, LadderGridState,
                                    LadderGridStrategy, LiveOrder)


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
        self.market_orders: list[tuple[str, str, Decimal, str | None]] = []

    def get_mid_price(self, symbol: str) -> Decimal:
        return self.mid_price

    def get_orderbook_top(self, symbol: str) -> tuple[Decimal, Decimal]:
        return self.mid_price, self.mid_price

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

    def place_market(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        client_id: str | None = None,
    ) -> str:
        order_id = f"market-{self._next_order_id}"
        self._next_order_id += 1
        self.market_orders.append((symbol, side, quantity, client_id))
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
        return {
            "MMX": (Decimal("1000"), Decimal("0")),
            "USDT": (Decimal("1000"), Decimal("0")),
        }


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
        total_fee_rate=Decimal("0"),
        tick_size=Decimal("0"),
        step_size=Decimal("1"),
        poll_interval_sec=1,
        startup_cancel_all=False,
        startup_rebalance=False,
        rebalance_target_base_pct=Decimal("0.5"),
        rebalance_slippage_pct=Decimal("0.01"),
        rebalance_max_attempts=1,
        reconcile_interval_sec=999,
        balance_refresh_sec=0,
    )


def test_min_notional_enforcement() -> None:
    client = FakeExchange(Decimal("1"))
    config = _build_config("abs")
    strategy = LadderGridStrategy(client, config)
    quantity = strategy._resolve_order_quantity(Decimal("0.035"), Decimal("1"))
    assert quantity >= Decimal("30")


def test_step_pct_must_exceed_fee_rate() -> None:
    client = FakeExchange(Decimal("100"))
    base_config = _build_config("pct")
    config = LadderGridConfig(
        **{
            **base_config.__dict__,
            "step_pct": Decimal("0.001"),
            "total_fee_rate": Decimal("0.002"),
        }
    )
    strategy = LadderGridStrategy(client, config)

    with pytest.raises(ValueError, match="spacing_pct"):
        strategy.seed_ladder()


def test_step_pct_accepts_profitable_spacing() -> None:
    client = FakeExchange(Decimal("100"))
    base_config = _build_config("pct")
    config = LadderGridConfig(
        **{
            **base_config.__dict__,
            "step_pct": Decimal("0.003"),
            "total_fee_rate": Decimal("0.002"),
        }
    )
    strategy = LadderGridStrategy(client, config)

    strategy.seed_ladder()

    assert len(client.placed_orders) == 2


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


def test_insufficient_funds_marks_rebalance_and_halts_cycle() -> None:
    class InsufficientFundsExchange(FakeExchange):
        def __init__(self, mid_price: Decimal) -> None:
            super().__init__(mid_price)
            self.place_limit_calls = 0

        def place_limit(
            self,
            symbol: str,
            side: str,
            price: Decimal,
            quantity: Decimal,
            client_id: str | None = None,
        ) -> str:
            self.place_limit_calls += 1
            raise RestError("Insufficient funds for order creation")

    client = InsufficientFundsExchange(Decimal("100"))
    config = _build_config("abs")
    strategy = LadderGridStrategy(client, config)

    strategy.seed_ladder()

    assert strategy.state.needs_rebalance is True
    assert strategy.state.open_orders == {}
    assert client.place_limit_calls == 1


def test_poll_once_skips_transient_get_order_error() -> None:
    class TransientOrderExchange(FakeExchange):
        def get_order(self, order_id: str) -> OrderStatusView:
            raise TransientApiError("Timeout fetching order")

    client = TransientOrderExchange(Decimal("100"))
    config = _build_config("abs")
    strategy = LadderGridStrategy(client, config)
    strategy.state.open_orders["order-1"] = LiveOrder(
        side="buy",
        price=Decimal("100"),
        quantity=Decimal("2"),
        client_id="cid",
        created_at=0.0,
    )

    strategy.poll_once()

    assert "order-1" in strategy.state.open_orders


def test_rebalance_market_success() -> None:
    class MarketSuccessExchange(FakeExchange):
        def __init__(self) -> None:
            super().__init__(Decimal("10"))
            self.balances = {
                "MMX": (Decimal("0"), Decimal("0")),
                "USDT": (Decimal("100"), Decimal("0")),
            }

        def get_balances(self) -> dict[str, tuple[Decimal, Decimal]]:
            return self.balances

        def place_market(
            self,
            symbol: str,
            side: str,
            quantity: Decimal,
            client_id: str | None = None,
        ) -> str:
            order_id = super().place_market(symbol, side, quantity, client_id)
            if side == "buy":
                self.balances["MMX"] = (
                    self.balances["MMX"][0] + quantity,
                    Decimal("0"),
                )
                self.balances["USDT"] = (
                    self.balances["USDT"][0] - quantity * self.mid_price,
                    Decimal("0"),
                )
            return order_id

    client = MarketSuccessExchange()
    config = _build_config("abs")
    strategy = LadderGridStrategy(client, config)

    strategy.rebalance_startup()

    assert client.market_orders
    assert client.placed_orders == []


def test_rebalance_market_fallback_limit_success() -> None:
    class MarketFallbackExchange(FakeExchange):
        def __init__(self) -> None:
            super().__init__(Decimal("10"))
            self.balances = {
                "MMX": (Decimal("0"), Decimal("0")),
                "USDT": (Decimal("100"), Decimal("0")),
            }
            self.orderbook_top = (Decimal("9"), Decimal("11"))

        def get_balances(self) -> dict[str, tuple[Decimal, Decimal]]:
            return self.balances

        def get_orderbook_top(self, symbol: str) -> tuple[Decimal, Decimal]:
            return self.orderbook_top

        def place_market(
            self,
            symbol: str,
            side: str,
            quantity: Decimal,
            client_id: str | None = None,
        ) -> str:
            raise RestError("Market orders not supported")

        def place_limit(
            self,
            symbol: str,
            side: str,
            price: Decimal,
            quantity: Decimal,
            client_id: str | None = None,
        ) -> str:
            order_id = super().place_limit(symbol, side, price, quantity, client_id)
            self.order_statuses[order_id] = OrderStatusView(status="filled")
            self.balances["MMX"] = (
                self.balances["MMX"][0] + quantity,
                Decimal("0"),
            )
            self.balances["USDT"] = (
                self.balances["USDT"][0] - quantity * self.mid_price,
                Decimal("0"),
            )
            return order_id

    client = MarketFallbackExchange()
    config = _build_config("abs")
    config = LadderGridConfig(
        **{**config.__dict__, "poll_interval_sec": 0, "rebalance_max_attempts": 1}
    )
    strategy = LadderGridStrategy(client, config)

    strategy.rebalance_startup()

    assert client.market_orders == []
    assert client.placed_orders
    _, _, price, _, _ = client.placed_orders[0]
    assert price == Decimal("11.11")


def test_rebalance_failure_requires_manual_guidance() -> None:
    class FailureExchange(FakeExchange):
        def __init__(self) -> None:
            super().__init__(Decimal("10"))
            self.balances = {
                "MMX": (Decimal("20"), Decimal("0")),
                "USDT": (Decimal("0"), Decimal("0")),
            }
            self.orderbook_top = (Decimal("9"), Decimal("11"))

        def get_balances(self) -> dict[str, tuple[Decimal, Decimal]]:
            return self.balances

        def get_orderbook_top(self, symbol: str) -> tuple[Decimal, Decimal]:
            return self.orderbook_top

        def place_market(
            self,
            symbol: str,
            side: str,
            quantity: Decimal,
            client_id: str | None = None,
        ) -> str:
            raise RestError("Market orders not supported")

        def place_limit(
            self,
            symbol: str,
            side: str,
            price: Decimal,
            quantity: Decimal,
            client_id: str | None = None,
        ) -> str:
            return super().place_limit(symbol, side, price, quantity, client_id)

    client = FailureExchange()
    config = _build_config("abs")
    config = LadderGridConfig(
        **{**config.__dict__, "poll_interval_sec": 0, "rebalance_max_attempts": 1}
    )
    strategy = LadderGridStrategy(client, config)

    try:
        strategy.rebalance_startup()
        assert False, "Expected rebalance_startup to raise"
    except RuntimeError as exc:
        message = str(exc)
        assert "required sell 10" in message
        assert "MMX available=20" in message
        assert "Manual action: sell 10 MMX for USDT" in message


def test_failed_rebalance_prevents_seeding(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    class StubStrategy:
        def __init__(self, config: LadderGridConfig) -> None:
            self.config = config
            self.state = LadderGridState()
            self.seeded = False

        def load_state(self) -> None:
            return None

        def rebalance_startup(self) -> None:
            raise RuntimeError("Manual action: sell 1 MMX for USDT.")

        def seed_ladder(self) -> None:
            self.seeded = True
            self.state.open_orders["order-1"] = LiveOrder(
                side="buy",
                price=Decimal("1"),
                quantity=Decimal("1"),
                client_id="cid",
                created_at=0.0,
            )

    config = _build_config("abs")
    config = LadderGridConfig(
        **{**config.__dict__, "startup_rebalance": True, "poll_interval_sec": 0}
    )
    strategy = StubStrategy(config)
    monkeypatch.setattr(ladder_runner, "build_strategy", lambda *_: strategy)

    with pytest.raises(RuntimeError):
        ladder_runner.run_ladder_grid({}, tmp_path / "state.json")

    assert strategy.seeded is False
    assert strategy.state.open_orders == {}
