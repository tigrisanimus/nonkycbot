from decimal import Decimal

from engine.exchange_client import OrderStatusView
from utils.profit_store import ProfitStore, ProfitStoreConfig


class FakeExchange:
    def __init__(self) -> None:
        self.orders: list[tuple[str, str, Decimal, Decimal]] = []
        self.status = "open"

    def get_orderbook_top(self, symbol: str) -> tuple[Decimal, Decimal]:
        return Decimal("99"), Decimal("100")

    def place_limit(
        self,
        symbol: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        client_id: str | None = None,
    ) -> str:
        self.orders.append((symbol, side, price, quantity))
        return "order-1"

    def get_order(self, order_id: str) -> OrderStatusView:
        return OrderStatusView(status=self.status)


def test_profit_store_places_order_above_best_ask() -> None:
    exchange = FakeExchange()
    config = ProfitStoreConfig(
        enabled=True,
        target_symbol="PAXG_USDT",
        quote_asset="USDT",
        min_profit_quote=Decimal("1"),
        aggressive_limit_pct=Decimal("0.003"),
    )
    store = ProfitStore(exchange, config, mode="live")

    store.record_profit(Decimal("2"), "USDT")

    assert store.open_order_id == "order-1"
    assert store.pending_profit == Decimal("0")
    assert store.reserved_profit == Decimal("2")
    assert exchange.orders
    symbol, side, price, _ = exchange.orders[0]
    assert symbol == "PAXG_USDT"
    assert side == "buy"
    assert price == Decimal("100.3")


def test_profit_store_waits_for_min_notional() -> None:
    exchange = FakeExchange()
    config = ProfitStoreConfig(
        enabled=True,
        min_profit_quote=Decimal("1"),
    )
    store = ProfitStore(exchange, config, mode="live")

    store.record_profit(Decimal("0.5"), "USDT")

    assert store.open_order_id is None
    assert store.pending_profit == Decimal("0.5")
    assert not exchange.orders


def test_profit_store_requeues_on_cancel() -> None:
    exchange = FakeExchange()
    config = ProfitStoreConfig(enabled=True, min_profit_quote=Decimal("1"))
    store = ProfitStore(exchange, config, mode="live")

    store.record_profit(Decimal("2"), "USDT")
    exchange.status = "canceled"
    store.process()

    assert store.open_order_id is None
    assert store.reserved_profit == Decimal("0")
    assert store.pending_profit == Decimal("2")


def test_profit_store_ignores_wrong_asset() -> None:
    exchange = FakeExchange()
    config = ProfitStoreConfig(enabled=True, quote_asset="USDT")
    store = ProfitStore(exchange, config, mode="live")

    store.record_profit(Decimal("2"), "BTC")

    assert store.pending_profit == Decimal("0")
    assert not exchange.orders


def test_profit_store_exit_trigger_on_principal() -> None:
    exchange = FakeExchange()
    config = ProfitStoreConfig(
        enabled=True,
        min_profit_quote=Decimal("1"),
        principal_investment_quote=Decimal("2"),
    )
    store = ProfitStore(exchange, config, mode="live")
    store.open_order_id = "order-1"
    store.reserved_profit = Decimal("2")
    exchange.status = "filled"

    store.process()

    assert store.should_trigger_exit() is True
