"""Fill-driven ladder grid strategy (KuCoin-style)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Iterable

from engine.exchange_client import ExchangeClient, OrderStatusView


@dataclass(frozen=True)
class LadderGridConfig:
    symbol: str
    step_mode: str
    step_pct: Decimal | None
    step_abs: Decimal | None
    n_buy_levels: int
    n_sell_levels: int
    base_order_size: Decimal
    min_notional_quote: Decimal
    fee_buffer_pct: Decimal
    tick_size: Decimal
    step_size: Decimal
    poll_interval_sec: float
    startup_cancel_all: bool = False
    reconcile_interval_sec: float = 60.0
    balance_refresh_sec: float = 60.0


@dataclass
class LiveOrder:
    side: str
    price: Decimal
    quantity: Decimal
    client_id: str
    created_at: float


@dataclass
class LadderGridState:
    open_orders: dict[str, LiveOrder] = field(default_factory=dict)
    last_mid: Decimal | None = None
    needs_rebalance: bool = False


class LadderGridStrategy:
    def __init__(
        self,
        client: ExchangeClient,
        config: LadderGridConfig,
        *,
        state_path: Path | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self.state_path = state_path
        self.state = LadderGridState()
        self._last_reconcile = 0.0
        self._last_balance_refresh = 0.0
        self._balances: dict[str, tuple[Decimal, Decimal]] = {}

    def load_state(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        open_orders = {}
        for order_id, payload in data.get("open_orders", {}).items():
            open_orders[order_id] = LiveOrder(
                side=payload["side"],
                price=Decimal(payload["price"]),
                quantity=Decimal(payload["quantity"]),
                client_id=payload["client_id"],
                created_at=payload["created_at"],
            )
        last_mid = data.get("last_mid")
        self.state = LadderGridState(
            open_orders=open_orders,
            last_mid=Decimal(last_mid) if last_mid is not None else None,
            needs_rebalance=bool(data.get("needs_rebalance", False)),
        )

    def save_state(self) -> None:
        if self.state_path is None:
            return
        payload = {
            "open_orders": {
                order_id: {
                    "side": order.side,
                    "price": str(order.price),
                    "quantity": str(order.quantity),
                    "client_id": order.client_id,
                    "created_at": order.created_at,
                }
                for order_id, order in self.state.open_orders.items()
            },
            "last_mid": (
                str(self.state.last_mid) if self.state.last_mid is not None else None
            ),
            "needs_rebalance": self.state.needs_rebalance,
        }
        self.state_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    def seed_ladder(self) -> None:
        mid_price = self.client.get_mid_price(self.config.symbol)
        self.state.last_mid = mid_price
        buy_levels = self._build_levels(mid_price, "buy", self.config.n_buy_levels)
        sell_levels = self._build_levels(mid_price, "sell", self.config.n_sell_levels)
        for side, price in buy_levels + sell_levels:
            self._place_order(side, price, self.config.base_order_size)
        self.save_state()

    def poll_once(self) -> None:
        now = time.time()
        self._refresh_balances(now)
        for order_id in list(self.state.open_orders.keys()):
            live_order = self.state.open_orders.get(order_id)
            if live_order is None:
                continue
            status = self.client.get_order(order_id)
            normalized = status.status.lower()
            if normalized == "filled":
                self._handle_filled(order_id, live_order, status)
            elif normalized in {"cancelled", "canceled", "rejected", "expired"}:
                self.state.open_orders.pop(order_id, None)
        if now - self._last_reconcile >= self.config.reconcile_interval_sec:
            self._reconcile_missing_levels()
            self._last_reconcile = now
        self.save_state()

    def _handle_filled(
        self, order_id: str, order: LiveOrder, status: OrderStatusView
    ) -> None:
        self.state.open_orders.pop(order_id, None)
        filled_price = status.avg_price or order.price
        filled_qty = status.filled_qty or order.quantity
        if order.side.lower() == "buy":
            new_side = "sell"
            new_price = self._apply_step(filled_price, 1, upward=True)
        else:
            new_side = "buy"
            new_price = self._apply_step(filled_price, 1, upward=False)
        self._place_order(new_side, new_price, filled_qty)

    def _reconcile_missing_levels(self) -> None:
        mid_price = self.client.get_mid_price(self.config.symbol)
        self.state.last_mid = mid_price
        buys = self._count_orders("buy")
        sells = self._count_orders("sell")
        if buys < self.config.n_buy_levels:
            levels = self._build_levels(
                mid_price, "buy", self.config.n_buy_levels - buys
            )
            for side, price in levels:
                self._place_order(side, price, self.config.base_order_size)
        if sells < self.config.n_sell_levels:
            levels = self._build_levels(
                mid_price, "sell", self.config.n_sell_levels - sells
            )
            for side, price in levels:
                self._place_order(side, price, self.config.base_order_size)

    def _build_levels(
        self, mid_price: Decimal, side: str, levels: int
    ) -> list[tuple[str, Decimal]]:
        existing_prices = {
            (order.side, order.price) for order in self.state.open_orders.values()
        }
        results: list[tuple[str, Decimal]] = []
        level = 1
        while len(results) < levels:
            price = (
                self._apply_step(mid_price, level, upward=side == "sell")
                if side == "sell"
                else self._apply_step(mid_price, level, upward=False)
            )
            price = self._quantize_price(price)
            key = (side, price)
            if key not in existing_prices:
                results.append((side, price))
                existing_prices.add(key)
            level += 1
        return results

    def _apply_step(self, price: Decimal, level: int, *, upward: bool) -> Decimal:
        if self.config.step_mode == "pct":
            if self.config.step_pct is None:
                raise ValueError("step_pct is required for pct step mode.")
            delta = price * self.config.step_pct * Decimal(level)
        else:
            if self.config.step_abs is None:
                raise ValueError("step_abs is required for abs step mode.")
            delta = self.config.step_abs * Decimal(level)
        return price + delta if upward else price - delta

    def _place_order(self, side: str, price: Decimal, base_quantity: Decimal) -> None:
        price = self._quantize_price(price)
        quantity = self._resolve_order_quantity(price, base_quantity)
        if not self._has_sufficient_balance(side, price, quantity):
            self.state.needs_rebalance = True
            return
        client_id = f"ladder-{side}-{int(time.time() * 1e6)}"
        order_id = self.client.place_limit(
            self.config.symbol, side, price, quantity, client_id
        )
        self.state.open_orders[order_id] = LiveOrder(
            side=side,
            price=price,
            quantity=quantity,
            client_id=client_id,
            created_at=time.time(),
        )

    def _resolve_order_quantity(
        self, price: Decimal, base_quantity: Decimal
    ) -> Decimal:
        min_qty = self._min_qty_for_notional(price)
        quantity = max(base_quantity, min_qty)
        quantity = self._quantize_quantity(quantity)
        attempts = 0
        while price * quantity < self.config.min_notional_quote and attempts < 5:
            quantity = self._quantize_quantity(quantity * Decimal("1.05"))
            attempts += 1
        return quantity

    def _quantize_price(self, price: Decimal) -> Decimal:
        if self.config.tick_size <= 0:
            return price
        return (price / self.config.tick_size).to_integral_value(
            rounding=ROUND_DOWN
        ) * self.config.tick_size

    def _quantize_quantity(self, quantity: Decimal) -> Decimal:
        if self.config.step_size <= 0:
            return quantity
        return (quantity / self.config.step_size).to_integral_value(
            rounding=ROUND_DOWN
        ) * self.config.step_size

    def _min_qty_for_notional(self, price: Decimal) -> Decimal:
        min_with_fee = self.config.min_notional_quote * (
            Decimal("1") + self.config.fee_buffer_pct
        )
        return min_with_fee / price

    def _count_orders(self, side: str) -> int:
        return sum(
            1 for order in self.state.open_orders.values() if order.side.lower() == side
        )

    def _refresh_balances(self, now: float) -> None:
        if now - self._last_balance_refresh < self.config.balance_refresh_sec:
            return
        self._balances = self.client.get_balances()
        self._last_balance_refresh = now

    def _has_sufficient_balance(
        self, side: str, price: Decimal, quantity: Decimal
    ) -> bool:
        if not self._balances:
            return True
        base, quote = self._split_symbol(self.config.symbol)
        if side.lower() == "buy":
            available = self._balances.get(quote, (Decimal("0"), Decimal("0")))[0]
            return available >= price * quantity
        available = self._balances.get(base, (Decimal("0"), Decimal("0")))[0]
        return available >= quantity

    @staticmethod
    def _split_symbol(symbol: str) -> tuple[str, str]:
        if "/" in symbol:
            base, quote = symbol.split("/", 1)
        elif "-" in symbol:
            base, quote = symbol.split("-", 1)
        else:
            raise ValueError(f"Unsupported symbol format: {symbol}")
        return base, quote


def describe() -> str:
    return "Fill-driven ladder grid strategy with add-only reconciliation."


def derive_market_id(symbol: str) -> str:
    return symbol.replace("/", "_").replace("-", "_")


def iter_live_orders(state: LadderGridState) -> Iterable[tuple[str, LiveOrder]]:
    return tuple(state.open_orders.items())
