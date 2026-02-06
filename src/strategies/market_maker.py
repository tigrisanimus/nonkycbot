"""Market making strategy with fee-aware spread capture and inventory skew."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from pathlib import Path

from engine.exchange_client import ExchangeClient, OrderStatusView
from nonkyc_client.rest import RestError

LOGGER = logging.getLogger("nonkyc_bot.strategy.market_maker")


@dataclass(frozen=True)
class MarketMakerConfig:
    symbol: str
    base_order_size: Decimal
    sell_quote_target: Decimal
    min_notional_quote: Decimal
    fee_rate: Decimal
    safety_buffer_pct: Decimal
    inside_spread_pct: Decimal
    inventory_target_pct: Decimal
    inventory_tolerance_pct: Decimal
    inventory_skew_pct: Decimal
    tick_size: Decimal
    step_size: Decimal
    poll_interval_sec: float
    max_order_age_sec: float
    balance_refresh_sec: float = 30.0
    mode: str = "live"
    post_only: bool = True


@dataclass
class LiveOrder:
    side: str
    price: Decimal
    quantity: Decimal
    client_id: str
    created_at: float


@dataclass
class MarketMakerState:
    open_orders: dict[str, LiveOrder] = field(default_factory=dict)


class MarketMakerStrategy:
    def __init__(
        self,
        client: ExchangeClient,
        config: MarketMakerConfig,
        *,
        state_path: Path | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self.state_path = state_path
        self.state = MarketMakerState()
        self._last_balance_refresh = 0.0
        self._balances: dict[str, tuple[Decimal, Decimal]] = {}
        self._halt_placements = False
        self._halt_logged = False

    def load_state(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        open_orders = {
            order_id: LiveOrder(
                side=order["side"],
                price=Decimal(order["price"]),
                quantity=Decimal(order["quantity"]),
                client_id=order["client_id"],
                created_at=order["created_at"],
            )
            for order_id, order in payload.get("open_orders", {}).items()
        }
        self.state = MarketMakerState(open_orders=open_orders)

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
            }
        }
        self.state_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    def poll_once(self) -> None:
        now = time.time()
        self._refresh_balances(now)
        self._sync_order_statuses()

        best_bid, best_ask = self.client.get_orderbook_top(self.config.symbol)
        if best_bid <= 0 or best_ask <= 0:
            LOGGER.warning(
                "Invalid orderbook prices: bid=%s ask=%s", best_bid, best_ask
            )
            return
        if best_ask <= best_bid:
            LOGGER.warning(
                "Orderbook spread invalid (ask <= bid): bid=%s ask=%s",
                best_bid,
                best_ask,
            )
            return

        mid_price = (best_bid + best_ask) / Decimal("2")
        spread = best_ask - best_bid
        spread_pct = spread / mid_price
        min_spread_pct = (
            self.config.fee_rate * Decimal("2") + self.config.safety_buffer_pct
        )
        if spread_pct < min_spread_pct:
            LOGGER.info(
                "Spread below fee-safe minimum. spread_pct=%s min_spread_pct=%s",
                spread_pct,
                min_spread_pct,
            )
            self._cancel_all_open_orders()
            return

        buy_price, sell_price = self._derive_quotes(best_bid, best_ask, mid_price)
        if buy_price <= 0 or sell_price <= 0 or buy_price >= sell_price:
            LOGGER.info(
                "Skipping quotes due to invalid pricing. buy=%s sell=%s",
                buy_price,
                sell_price,
            )
            self._cancel_all_open_orders()
            return

        expected_profit = (
            sell_price - buy_price - (buy_price + sell_price) * self.config.fee_rate
        )
        if expected_profit <= 0:
            LOGGER.info(
                "Expected profit not positive. buy=%s sell=%s expected=%s",
                buy_price,
                sell_price,
                expected_profit,
            )
            self._cancel_all_open_orders()
            return

        buy_qty, sell_qty = self._resolve_order_sizes(buy_price, sell_price)
        desired_orders: dict[str, tuple[Decimal, Decimal]] = {}
        if buy_qty > 0:
            desired_orders["buy"] = (buy_price, buy_qty)
        if sell_qty > 0:
            desired_orders["sell"] = (sell_price, sell_qty)

        for side in ("buy", "sell"):
            desired = desired_orders.get(side)
            existing = self._find_order_by_side(side)
            if desired is None:
                if existing:
                    self._cancel_order(existing[0])
                continue
            desired_price, desired_qty = desired
            if existing is None:
                self._place_order(side, desired_price, desired_qty)
                continue
            order_id, order = existing
            if self._needs_replace(order, desired_price, desired_qty, now):
                self._cancel_order(order_id)
                self._place_order(side, desired_price, desired_qty)

        self.save_state()

    def _derive_quotes(
        self, best_bid: Decimal, best_ask: Decimal, mid_price: Decimal
    ) -> tuple[Decimal, Decimal]:
        spread = best_ask - best_bid
        epsilon = spread * self.config.inside_spread_pct
        if epsilon <= 0:
            epsilon = spread * Decimal("0.1")
        if self.config.tick_size > 0:
            epsilon = max(epsilon, self.config.tick_size)

        buy_price = best_bid + epsilon
        sell_price = best_ask - epsilon

        inventory_skew = self._calculate_inventory_skew(mid_price, spread)
        buy_price -= inventory_skew
        sell_price -= inventory_skew

        buy_price = self._quantize_price(buy_price, side="buy")
        sell_price = self._quantize_price(sell_price, side="sell")

        min_buy = best_bid + (self.config.tick_size if self.config.tick_size > 0 else 0)
        max_sell = best_ask - (
            self.config.tick_size if self.config.tick_size > 0 else 0
        )
        buy_price = max(buy_price, min_buy)
        sell_price = min(sell_price, max_sell)

        return buy_price, sell_price

    def _calculate_inventory_skew(self, mid_price: Decimal, spread: Decimal) -> Decimal:
        base_asset, quote_asset = self._split_symbol(self.config.symbol)
        base_balance = (
            self._balances.get(base_asset, (Decimal("0"), Decimal("0")))[0]
            if self._balances
            else Decimal("0")
        )
        quote_balance = (
            self._balances.get(quote_asset, (Decimal("0"), Decimal("0")))[0]
            if self._balances
            else Decimal("0")
        )
        total_value = base_balance * mid_price + quote_balance
        if total_value <= 0:
            return Decimal("0")
        base_ratio = (base_balance * mid_price) / total_value
        diff = base_ratio - self.config.inventory_target_pct
        tolerance = max(self.config.inventory_tolerance_pct, Decimal("0.0001"))
        if abs(diff) <= tolerance:
            return Decimal("0")
        skew_factor = max(min(diff / tolerance, Decimal("1")), Decimal("-1"))
        return spread * self.config.inventory_skew_pct * skew_factor

    def _resolve_order_sizes(
        self, buy_price: Decimal, sell_price: Decimal
    ) -> tuple[Decimal, Decimal]:
        base_asset, quote_asset = self._split_symbol(self.config.symbol)
        base_available = (
            self._balances.get(base_asset, (Decimal("0"), Decimal("0")))[0]
            if self._balances
            else Decimal("0")
        )
        quote_available = (
            self._balances.get(quote_asset, (Decimal("0"), Decimal("0")))[0]
            if self._balances
            else Decimal("0")
        )

        buy_qty = self._quantize_quantity(self.config.base_order_size)
        if buy_price > 0:
            max_buy_qty = quote_available / buy_price
            buy_qty = min(buy_qty, max_buy_qty)
        buy_qty = self._quantize_quantity(buy_qty)
        if buy_qty <= 0:
            buy_qty = Decimal("0")
        elif buy_price * buy_qty < self.config.min_notional_quote:
            buy_qty = Decimal("0")

        sell_qty = (
            self.config.sell_quote_target / sell_price
            if sell_price > 0
            else Decimal("0")
        )
        sell_qty = min(sell_qty, base_available)
        sell_qty = self._quantize_quantity(sell_qty)
        if sell_qty <= 0:
            sell_qty = Decimal("0")
        elif sell_price * sell_qty < self.config.min_notional_quote:
            sell_qty = Decimal("0")

        return buy_qty, sell_qty

    def _refresh_balances(self, now: float) -> None:
        if now - self._last_balance_refresh < self.config.balance_refresh_sec:
            return
        self._balances = self.client.get_balances()
        self._last_balance_refresh = now

    def _sync_order_statuses(self) -> None:
        completed = []
        for order_id, order in self.state.open_orders.items():
            status = self.client.get_order(order_id)
            if self._is_final_status(status):
                completed.append(order_id)
        for order_id in completed:
            self.state.open_orders.pop(order_id, None)

    def _is_final_status(self, status: OrderStatusView) -> bool:
        normalized = status.status.lower()
        return normalized in {
            "filled",
            "closed",
            "done",
            "cancelled",
            "canceled",
            "rejected",
            "expired",
        }

    def _find_order_by_side(self, side: str) -> tuple[str, LiveOrder] | None:
        for order_id, order in self.state.open_orders.items():
            if order.side == side:
                return order_id, order
        return None

    def _needs_replace(
        self, order: LiveOrder, desired_price: Decimal, desired_qty: Decimal, now: float
    ) -> bool:
        if now - order.created_at >= self.config.max_order_age_sec:
            return True
        if (
            self.config.tick_size > 0
            and abs(order.price - desired_price) >= self.config.tick_size
        ):
            return True
        if (
            self.config.step_size > 0
            and abs(order.quantity - desired_qty) >= self.config.step_size
        ):
            return True
        return order.price != desired_price or order.quantity != desired_qty

    def _place_order(self, side: str, price: Decimal, quantity: Decimal) -> None:
        if self._halt_placements:
            if not self._halt_logged:
                LOGGER.info(
                    "[%s] Skipping order placement; placements are halted.",
                    self.config.symbol,
                )
                self._halt_logged = True
            return
        if self.config.mode in {"monitor", "dry-run"}:
            LOGGER.info(
                "[%s] Skipping order placement in %s mode: %s %s @ %s",
                self.config.symbol,
                self.config.mode,
                side,
                quantity,
                price,
            )
            return
        client_id = f"mm-{uuid.uuid4().hex}"
        try:
            order_id = self.client.place_limit(
                self.config.symbol,
                side,
                price,
                quantity,
                client_id=client_id,
                strict_validate=self.config.post_only,
            )
        except RestError as exc:
            if self._is_insufficient_funds(exc):
                LOGGER.warning(
                    "Insufficient funds to place %s order at %s for %s.",
                    side,
                    price,
                    quantity,
                )
                self._halt_placements = True
                self._halt_logged = False
                return
            raise
        self.state.open_orders[order_id] = LiveOrder(
            side=side,
            price=price,
            quantity=quantity,
            client_id=client_id,
            created_at=time.time(),
        )
        LOGGER.info(
            "Placed %s order: %s qty=%s price=%s",
            side,
            order_id,
            quantity,
            price,
        )

    def _cancel_order(self, order_id: str) -> None:
        if self.config.mode in {"monitor", "dry-run"}:
            LOGGER.info(
                "[%s] Skipping cancel in %s mode for order %s",
                self.config.symbol,
                self.config.mode,
                order_id,
            )
            return
        try:
            self.client.cancel_order(order_id)
        except RestError as exc:
            if self._is_not_found_cancel(exc):
                LOGGER.info(
                    "Cancel skipped for %s; order not found on exchange.", order_id
                )
            else:
                raise
        self.state.open_orders.pop(order_id, None)

    def _cancel_all_open_orders(self) -> None:
        for order_id in list(self.state.open_orders.keys()):
            self._cancel_order(order_id)

    def _quantize_price(self, price: Decimal, *, side: str) -> Decimal:
        if self.config.tick_size <= 0:
            return price
        rounding = ROUND_DOWN if side == "buy" else ROUND_UP
        return (price / self.config.tick_size).to_integral_value(
            rounding=rounding
        ) * self.config.tick_size

    def _quantize_quantity(self, quantity: Decimal) -> Decimal:
        if self.config.step_size <= 0:
            return quantity
        return (quantity / self.config.step_size).to_integral_value(
            rounding=ROUND_DOWN
        ) * self.config.step_size

    @staticmethod
    def _is_not_found_cancel(exc: RestError) -> bool:
        message = str(exc).lower()
        return "not found" in message or "active order not found" in message

    @staticmethod
    def _is_insufficient_funds(exc: RestError) -> bool:
        return "insufficient funds" in str(exc).lower()

    @staticmethod
    def _split_symbol(symbol: str) -> tuple[str, str]:
        for delimiter in ("/", "-", "_"):
            if delimiter in symbol:
                base, quote = symbol.split(delimiter, maxsplit=1)
                return base, quote
        raise ValueError(f"Unsupported symbol format: {symbol}")


def describe() -> str:
    return (
        "Market making strategy that posts inside-spread quotes with fee-aware "
        "minimum spread checks and inventory-based skewing."
    )
