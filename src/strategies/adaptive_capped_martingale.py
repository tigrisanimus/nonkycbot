"""Adaptive capped martingale strategy for spot mean reversion."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from pathlib import Path

from engine.exchange_client import ExchangeClient, OrderStatusView
from nonkyc_client.rest import RestError, TransientApiError

LOGGER = logging.getLogger("nonkyc_bot.strategy.adaptive_capped_martingale")


@dataclass(frozen=True)
class AdaptiveCappedMartingaleConfig:
    symbol: str
    cycle_budget: Decimal
    base_order_pct: Decimal = Decimal("0.015")
    multiplier: Decimal = Decimal("1.45")
    max_adds: int = 8
    per_order_cap_pct: Decimal = Decimal("0.10")
    step_pct: Decimal = Decimal("0.012")
    slippage_buffer_pct: Decimal = Decimal("0.001")
    tp1_pct: Decimal = Decimal("0.008")
    tp2_pct: Decimal = Decimal("0.014")
    fee_rate: Decimal = Decimal("0.002")
    min_order_notional: Decimal = Decimal("2")
    min_order_qty: Decimal | None = None
    time_stop_seconds: float = 72 * 3600
    time_stop_exit_buffer_pct: Decimal = Decimal("0.001")
    poll_interval_sec: float = 5.0
    quantity_step: Decimal | None = None
    quantity_precision: int | None = None


@dataclass
class TrackedOrder:
    order_id: str
    client_id: str
    role: str
    side: str
    price: Decimal
    quantity: Decimal
    filled_qty: Decimal = Decimal("0")
    status: str = "Open"
    created_at: float = 0.0


@dataclass
class CycleState:
    cycle_id: str
    started_at: float
    base_price: Decimal | None = None
    total_btc: Decimal = Decimal("0")
    total_buy_quote: Decimal = Decimal("0")
    total_buy_fees_quote: Decimal = Decimal("0")
    last_fill_price: Decimal | None = None
    next_add_trigger: Decimal | None = None
    add_count: int = 0
    partial_exit_done: bool = False
    time_stop_triggered: bool = False
    fills: list[dict[str, str]] = field(default_factory=list)
    open_orders: dict[str, TrackedOrder] = field(default_factory=dict)


class AdaptiveCappedMartingaleStrategy:
    def __init__(
        self,
        client: ExchangeClient,
        config: AdaptiveCappedMartingaleConfig,
        *,
        state_path: Path | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self.state_path = state_path
        self.state: CycleState | None = None

    def load_state(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        orders = {}
        for order_id, payload in data.get("open_orders", {}).items():
            orders[order_id] = TrackedOrder(
                order_id=order_id,
                client_id=payload["client_id"],
                role=payload["role"],
                side=payload["side"],
                price=Decimal(payload["price"]),
                quantity=Decimal(payload["quantity"]),
                filled_qty=Decimal(payload.get("filled_qty", "0")),
                status=payload.get("status", "Open"),
                created_at=payload.get("created_at", 0.0),
            )
        cycle_id = data.get("cycle_id")
        if cycle_id is None:
            return
        self.state = CycleState(
            cycle_id=cycle_id,
            started_at=float(data["started_at"]),
            base_price=(
                Decimal(data["base_price"]) if data.get("base_price") else None
            ),
            total_btc=Decimal(str(data.get("total_btc", "0"))),
            total_buy_quote=Decimal(str(data.get("total_buy_quote", "0"))),
            total_buy_fees_quote=Decimal(str(data.get("total_buy_fees_quote", "0"))),
            last_fill_price=(
                Decimal(data["last_fill_price"])
                if data.get("last_fill_price")
                else None
            ),
            next_add_trigger=(
                Decimal(data["next_add_trigger"])
                if data.get("next_add_trigger")
                else None
            ),
            add_count=int(data.get("add_count", 0)),
            partial_exit_done=bool(data.get("partial_exit_done", False)),
            time_stop_triggered=bool(data.get("time_stop_triggered", False)),
            fills=list(data.get("fills", [])),
            open_orders=orders,
        )

    def save_state(self) -> None:
        if self.state_path is None or self.state is None:
            return
        payload = {
            "cycle_id": self.state.cycle_id,
            "started_at": self.state.started_at,
            "base_price": str(self.state.base_price) if self.state.base_price else None,
            "total_btc": str(self.state.total_btc),
            "total_buy_quote": str(self.state.total_buy_quote),
            "total_buy_fees_quote": str(self.state.total_buy_fees_quote),
            "last_fill_price": (
                str(self.state.last_fill_price) if self.state.last_fill_price else None
            ),
            "next_add_trigger": (
                str(self.state.next_add_trigger)
                if self.state.next_add_trigger is not None
                else None
            ),
            "add_count": self.state.add_count,
            "partial_exit_done": self.state.partial_exit_done,
            "time_stop_triggered": self.state.time_stop_triggered,
            "fills": list(self.state.fills),
            "remaining_budget": str(self.config.cycle_budget - self._cycle_spent()),
            "open_orders": {
                order_id: {
                    "client_id": order.client_id,
                    "role": order.role,
                    "side": order.side,
                    "price": str(order.price),
                    "quantity": str(order.quantity),
                    "filled_qty": str(order.filled_qty),
                    "status": order.status,
                    "created_at": order.created_at,
                }
                for order_id, order in self.state.open_orders.items()
            },
        }
        self.state_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    def poll_once(self, *, now: float | None = None) -> None:
        if now is None:
            now = time.time()
        self._reconcile(now)
        if self.state is None:
            self._start_cycle(now)
            self.save_state()
            return
        if self.state.total_btc == 0 and not self.state.open_orders:
            self._start_cycle(now)
            self.save_state()
            return
        self._apply_time_stop(now)
        mid_price = self.client.get_mid_price(self.config.symbol)
        desired = self._determine_next_action(mid_price)
        self._ensure_single_order(desired, mid_price, now)
        self.save_state()

    def _start_cycle(self, now: float) -> None:
        self.state = CycleState(cycle_id=uuid.uuid4().hex, started_at=now)
        self._place_base_order(now)

    def _cycle_spent(self) -> Decimal:
        if self.state is None:
            return Decimal("0")
        return self.state.total_buy_quote + self.state.total_buy_fees_quote

    def _avg_entry(self) -> Decimal | None:
        if self.state is None or self.state.total_btc <= 0:
            return None
        total_cost = self.state.total_buy_quote + self.state.total_buy_fees_quote
        if total_cost <= 0:
            return None
        return total_cost / self.state.total_btc

    def _breakeven_price(self) -> Decimal | None:
        avg_entry = self._avg_entry()
        if avg_entry is None:
            return None
        fee_buffer = Decimal("0.004") + self.config.slippage_buffer_pct
        return avg_entry * (Decimal("1") + fee_buffer)

    def _min_required_notional(self, price: Decimal) -> Decimal:
        min_notional = self.config.min_order_notional
        if self.config.min_order_qty is None:
            return min_notional
        min_qty_notional = self.config.min_order_qty * price
        return max(min_notional, min_qty_notional)

    def _base_order_notional(self, price: Decimal) -> Decimal:
        target = self.config.cycle_budget * self.config.base_order_pct
        return max(target, self._min_required_notional(price))

    def _per_order_cap(self) -> Decimal:
        return self.config.cycle_budget * self.config.per_order_cap_pct

    def _next_add_notional(self, price: Decimal) -> Decimal:
        if self.state is None:
            return Decimal("0")
        base = self._base_order_notional(price)
        raw = base * (self.config.multiplier**self.state.add_count)
        capped = min(raw, self._per_order_cap())
        return max(capped, self._min_required_notional(price))

    def _desired_budget_available(self, notional: Decimal) -> bool:
        fee = notional * self.config.fee_rate
        return self._cycle_spent() + notional + fee <= self.config.cycle_budget

    def _round_quantity(
        self, quantity: Decimal, *, rounding: str = ROUND_DOWN
    ) -> Decimal:
        if quantity <= 0:
            return Decimal("0")
        if self.config.quantity_step is not None and self.config.quantity_step > 0:
            step = self.config.quantity_step
            return (quantity / step).to_integral_value(rounding=rounding) * step
        if self.config.quantity_precision is not None:
            quantizer = Decimal("1").scaleb(-self.config.quantity_precision)
            return quantity.quantize(quantizer, rounding=rounding)
        return quantity

    def _place_limit_order(
        self,
        *,
        role: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        now: float,
        rounding: str = ROUND_DOWN,
    ) -> None:
        if self.state is None:
            return
        quantity = self._round_quantity(quantity, rounding=rounding)
        if quantity <= 0:
            return
        if (
            self.config.min_order_qty is not None
            and quantity < self.config.min_order_qty
        ):
            LOGGER.info(
                "Skipping %s order below min quantity: %s < %s",
                role,
                quantity,
                self.config.min_order_qty,
            )
            return
        if side.lower() == "sell":
            quantity = self._cap_sell_quantity_to_available(quantity)
            if quantity <= 0:
                LOGGER.info("Skipping %s order: no available balance to sell.", role)
                return
            if (
                self.config.min_order_qty is not None
                and quantity < self.config.min_order_qty
            ):
                LOGGER.info(
                    "Skipping %s order below min quantity after balance check: %s < %s",
                    role,
                    quantity,
                    self.config.min_order_qty,
                )
                return
        notional = quantity * price
        if notional < self.config.min_order_notional:
            LOGGER.info(
                "Skipping %s order below min notional: %s < %s",
                role,
                notional,
                self.config.min_order_notional,
            )
            return
        client_id = f"acm-{role}-{uuid.uuid4().hex}"
        try:
            order_id = self.client.place_limit(
                self.config.symbol, side, price, quantity, client_id
            )
        except RestError as exc:
            if self._is_insufficient_funds_error(exc):
                if not self._has_sufficient_balance_for_order(
                    side=side, price=price, quantity=quantity
                ):
                    LOGGER.warning(
                        "Insufficient funds for %s order; skipping placement at %s.",
                        role,
                        price,
                    )
                    return
            if self._is_recoverable_order_error(exc):
                LOGGER.warning(
                    "Recoverable order placement error: %s. Skipping %s order at %s.",
                    exc,
                    role,
                    price,
                )
                return
            raise
        self.state.open_orders[order_id] = TrackedOrder(
            order_id=order_id,
            client_id=client_id,
            role=role,
            side=side,
            price=price,
            quantity=quantity,
            created_at=now,
        )
        LOGGER.info(
            "Placed %s order: side=%s price=%s qty=%s id=%s",
            role,
            side,
            price,
            quantity,
            order_id,
        )

    def _place_market_order(
        self,
        *,
        role: str,
        side: str,
        price_hint: Decimal,
        fill_price: Decimal | None = None,
        quantity: Decimal,
        now: float,
        rounding: str = ROUND_DOWN,
        apply_fill: bool = False,
    ) -> None:
        if self.state is None:
            return
        quantity = self._round_quantity(quantity, rounding=rounding)
        if quantity <= 0:
            return
        if (
            self.config.min_order_qty is not None
            and quantity < self.config.min_order_qty
        ):
            LOGGER.info(
                "Skipping %s order below min quantity: %s < %s",
                role,
                quantity,
                self.config.min_order_qty,
            )
            return
        notional = quantity * price_hint
        if notional < self.config.min_order_notional:
            LOGGER.info(
                "Skipping %s order below min notional: %s < %s",
                role,
                notional,
                self.config.min_order_notional,
            )
            return
        client_id = f"acm-{role}-{uuid.uuid4().hex}"
        try:
            order_id = self.client.place_market(
                self.config.symbol, side, quantity, client_id
            )
        except NotImplementedError as exc:
            LOGGER.warning(
                "Market orders not supported; falling back to limit base order: %s",
                exc,
            )
            self._place_limit_order(
                role=role,
                side=side,
                price=price_hint,
                quantity=quantity,
                now=now,
                rounding=rounding,
            )
            return
        except RestError as exc:
            if self._is_insufficient_funds_error(exc):
                if not self._has_sufficient_balance_for_order(
                    side=side, price=price_hint, quantity=quantity
                ):
                    LOGGER.warning(
                        "Insufficient funds for %s market order; skipping placement.",
                        role,
                    )
                    return
            if self._is_recoverable_order_error(exc):
                LOGGER.warning(
                    "Recoverable order placement error: %s. Skipping %s market order.",
                    exc,
                    role,
                )
                return
            raise
        if apply_fill:
            resolved_fill = fill_price if fill_price is not None else price_hint
            if side == "buy":
                self._apply_buy_fill(quantity, resolved_fill)
                if self.state.base_price is None and role == "base":
                    self.state.base_price = resolved_fill
            else:
                self._apply_sell_fill(quantity, resolved_fill)
            LOGGER.info(
                "Placed %s market order (applied fill): side=%s qty=%s id=%s",
                role,
                side,
                quantity,
                order_id,
            )
            return
        self.state.open_orders[order_id] = TrackedOrder(
            order_id=order_id,
            client_id=client_id,
            role=role,
            side=side,
            price=price_hint,
            quantity=quantity,
            created_at=now,
        )
        LOGGER.info(
            "Placed %s market order: side=%s qty=%s id=%s",
            role,
            side,
            quantity,
            order_id,
        )

    def _place_base_order(self, now: float) -> None:
        if self.state is None:
            return
        if self._has_open_role("base"):
            return
        best_bid, _ = self.client.get_orderbook_top(self.config.symbol)
        mid_price = self.client.get_mid_price(self.config.symbol)
        notional = self._base_order_notional(best_bid)
        if not self._desired_budget_available(notional):
            LOGGER.warning("Insufficient budget for base order: %s", notional)
            return
        quantity = notional / best_bid
        quantity = self._round_quantity(quantity, rounding=ROUND_UP)
        notional = quantity * best_bid
        if not self._desired_budget_available(notional):
            LOGGER.warning(
                "Insufficient budget for base order after rounding: %s", notional
            )
            return
        self._place_market_order(
            role="base",
            side="buy",
            price_hint=best_bid,
            fill_price=mid_price,
            quantity=quantity,
            now=now,
            rounding=ROUND_UP,
            apply_fill=True,
        )

    def _place_add_order(self, now: float, price: Decimal) -> None:
        if self.state is None:
            return
        if self.state.add_count >= self.config.max_adds:
            return
        best_bid, _ = self.client.get_orderbook_top(self.config.symbol)
        target_price = price
        if self.state.next_add_trigger is not None:
            target_price = min(target_price, self.state.next_add_trigger)
        bid_price = min(best_bid, target_price)
        notional = self._next_add_notional(bid_price)
        if not self._desired_budget_available(notional):
            LOGGER.info("Skipping add: budget cap reached")
            return
        quantity = notional / bid_price
        quantity = self._round_quantity(quantity, rounding=ROUND_UP)
        notional = quantity * bid_price
        if not self._desired_budget_available(notional):
            LOGGER.info("Skipping add: budget cap reached after rounding")
            return
        role = f"add-{self.state.add_count + 1}"
        self._place_limit_order(
            role=role,
            side="buy",
            price=bid_price,
            quantity=quantity,
            now=now,
            rounding=ROUND_UP,
        )

    def _place_tp1(self, now: float, price: Decimal) -> None:
        if self.state is None:
            return
        if self.state.partial_exit_done:
            return
        quantity = self.state.total_btc * Decimal("0.5")
        quantity = self._round_quantity(quantity)
        if (
            self.config.min_order_qty is not None
            and quantity < self.config.min_order_qty
        ):
            if self.state.total_btc >= self.config.min_order_qty:
                quantity = self._round_quantity(self.state.total_btc)
            else:
                LOGGER.info("Skipping TP1: position below min quantity")
                return
        notional = quantity * price
        if notional < self.config.min_order_notional:
            total_notional = self.state.total_btc * price
            if total_notional >= self.config.min_order_notional:
                quantity = self._round_quantity(self.state.total_btc)
            else:
                LOGGER.info("Skipping TP1: position below min notional")
                return
        _, best_ask = self.client.get_orderbook_top(self.config.symbol)
        target_price = max(price, best_ask)
        self._place_limit_order(
            role="tp1",
            side="sell",
            price=target_price,
            quantity=quantity,
            now=now,
        )

    def _place_exit(self, now: float, price: Decimal) -> None:
        if self.state is None:
            return
        quantity = self._round_quantity(self.state.total_btc)
        if quantity <= 0:
            return
        if (
            self.config.min_order_qty is not None
            and quantity < self.config.min_order_qty
        ):
            LOGGER.info("Skipping exit: position below min quantity")
            return
        notional = quantity * price
        if notional < self.config.min_order_notional:
            LOGGER.info("Skipping exit: position below min notional")
            return
        _, best_ask = self.client.get_orderbook_top(self.config.symbol)
        target_price = max(price, best_ask)
        self._place_limit_order(
            role="tp2",
            side="sell",
            price=target_price,
            quantity=quantity,
            now=now,
        )

    def _has_open_role(self, role_prefix: str) -> bool:
        if self.state is None:
            return False
        return any(
            order.role.startswith(role_prefix)
            for order in self.state.open_orders.values()
        )

    def _apply_time_stop(self, now: float) -> None:
        if self.state is None or self.state.time_stop_triggered:
            return
        if now - self.state.started_at >= self.config.time_stop_seconds:
            self.state.time_stop_triggered = True
            self._cancel_roles("add")

    def _determine_next_action(self, mid_price: Decimal) -> str | None:
        if self.state is None:
            return None
        if self.state.total_btc <= 0:
            if not self.state.open_orders:
                return "base"
            return None
        avg_entry = self._avg_entry()
        if avg_entry is None:
            return None
        tp1_price = avg_entry * (Decimal("1") + self.config.tp1_pct)
        tp2_price = avg_entry * (Decimal("1") + self.config.tp2_pct)
        if self.state.time_stop_triggered:
            breakeven = self._breakeven_price()
            if breakeven is None:
                return None
            target = breakeven * (Decimal("1") + self.config.time_stop_exit_buffer_pct)
            if mid_price >= target:
                return "tp2"
            return None
        if mid_price >= tp2_price:
            return "tp2"
        if mid_price >= tp1_price and not self.state.partial_exit_done:
            return "tp1"
        if self.state.next_add_trigger is not None and (
            mid_price <= self.state.next_add_trigger or not self.state.open_orders
        ):
            if self.state.add_count < self.config.max_adds:
                return "add"
        return None

    def _ensure_single_order(
        self, desired_role: str | None, mid_price: Decimal, now: float
    ) -> None:
        if self.state is None:
            return
        if not self.state.open_orders and desired_role is None:
            return
        if desired_role is None:
            return
        desired_prefix = desired_role
        if any(
            order.role.startswith(desired_prefix)
            for order in self.state.open_orders.values()
        ):
            self._cancel_unrelated(desired_prefix)
            return
        if self.state.open_orders:
            self._cancel_all_open()
        if desired_role == "base":
            self._place_base_order(now)
        elif desired_role == "add":
            self._place_add_order(now, mid_price)
        elif desired_role == "tp1":
            self._place_tp1(now, mid_price)
        elif desired_role == "tp2":
            self._place_exit(now, mid_price)

    def _cancel_roles(self, role_prefix: str) -> None:
        if self.state is None:
            return
        to_cancel = [
            order_id
            for order_id, order in self.state.open_orders.items()
            if order.role.startswith(role_prefix)
        ]
        for order_id in to_cancel:
            self.client.cancel_order(order_id)
            self.state.open_orders.pop(order_id, None)

    def _cancel_unrelated(self, desired_prefix: str) -> None:
        if self.state is None:
            return
        to_cancel = [
            order_id
            for order_id, order in self.state.open_orders.items()
            if not order.role.startswith(desired_prefix)
        ]
        for order_id in to_cancel:
            self.client.cancel_order(order_id)
            self.state.open_orders.pop(order_id, None)

    def _cancel_all_open(self) -> None:
        if self.state is None:
            return
        for order_id in list(self.state.open_orders.keys()):
            self.client.cancel_order(order_id)
            self.state.open_orders.pop(order_id, None)

    def _reconcile(self, now: float) -> None:
        if self.state is None:
            return
        try:
            open_ids = {
                order.order_id
                for order in self.client.list_open_orders(self.config.symbol)
            }
        except Exception as exc:
            LOGGER.warning("Error fetching open orders; skipping reconcile: %s", exc)
            return
        for order_id, tracked in list(self.state.open_orders.items()):
            status_view = None
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    status_view = self.client.get_order(order_id)
                    break
                except TransientApiError as exc:
                    if attempt < max_retries - 1:
                        backoff = 1.0 * (2**attempt)
                        LOGGER.debug(
                            "Transient error fetching order %s (attempt %d/%d), "
                            "retrying in %.1fs: %s",
                            order_id,
                            attempt + 1,
                            max_retries,
                            backoff,
                            exc,
                        )
                        time.sleep(backoff)
                    else:
                        LOGGER.warning(
                            "Transient error fetching order %s after %d attempts; "
                            "skipping update: %s",
                            order_id,
                            max_retries,
                            exc,
                        )
                except RestError as exc:
                    if self._is_not_found_error(exc):
                        LOGGER.info(
                            "Order %s not found on exchange; removing from state.",
                            order_id,
                        )
                        self.state.open_orders.pop(order_id, None)
                        status_view = None
                        break
                    LOGGER.warning(
                        "Error fetching order %s; skipping update: %s", order_id, exc
                    )
                    break
                except Exception as exc:
                    LOGGER.warning(
                        "Error fetching order %s; skipping update: %s", order_id, exc
                    )
                    break
            if status_view is None:
                continue
            self._apply_order_update(tracked, status_view)
            if order_id not in open_ids:
                if status_view.status.lower() in {"filled", "closed", "done"}:
                    self._finalize_order(tracked)
                    self.state.open_orders.pop(order_id, None)
                elif status_view.status.lower() in {
                    "canceled",
                    "cancelled",
                    "rejected",
                }:
                    self.state.open_orders.pop(order_id, None)
            else:
                tracked.status = status_view.status

    @staticmethod
    def _is_not_found_error(exc: Exception) -> bool:
        return isinstance(exc, RestError) and "HTTP error 404" in str(exc)

    def _apply_order_update(
        self, tracked: TrackedOrder, status: OrderStatusView
    ) -> None:
        filled_qty = status.filled_qty or Decimal("0")
        if filled_qty <= tracked.filled_qty:
            return
        delta = filled_qty - tracked.filled_qty
        fill_price = status.avg_price or tracked.price
        tracked.filled_qty = filled_qty
        tracked.status = status.status
        if tracked.side == "buy":
            self._apply_buy_fill(delta, fill_price)
            if tracked.role == "base" and self.state and self.state.base_price is None:
                self.state.base_price = fill_price
        else:
            self._apply_sell_fill(delta, fill_price)

        if (
            tracked.side == "buy"
            and self.state
            and tracked.role.startswith("add")
            and tracked.filled_qty >= tracked.quantity
        ):
            self.state.add_count += 1

    def _apply_buy_fill(self, quantity: Decimal, price: Decimal) -> None:
        if self.state is None:
            return
        quote = quantity * price
        fee = quote * self.config.fee_rate
        self.state.total_buy_quote += quote
        self.state.total_buy_fees_quote += fee
        self.state.total_btc += quantity
        self.state.last_fill_price = price
        self.state.next_add_trigger = price * (Decimal("1") - self.config.step_pct)
        avg_entry = self._avg_entry()
        if avg_entry is not None:
            tp1_price = avg_entry * (Decimal("1") + self.config.tp1_pct)
            tp2_price = avg_entry * (Decimal("1") + self.config.tp2_pct)
            LOGGER.info(
                "Cycle levels updated: avg_entry=%s tp1=%s tp2=%s next_add_trigger=%s",
                avg_entry,
                tp1_price,
                tp2_price,
                self.state.next_add_trigger,
            )
        self.state.fills.append(
            {
                "side": "buy",
                "price": str(price),
                "quantity": str(quantity),
                "quote": str(quote),
                "fee": str(fee),
            }
        )

    def _apply_sell_fill(self, quantity: Decimal, price: Decimal) -> None:
        if self.state is None:
            return
        if self.state.total_btc <= 0:
            return
        current_total = self.state.total_btc
        ratio = quantity / current_total if current_total > 0 else Decimal("0")
        self.state.total_buy_quote -= self.state.total_buy_quote * ratio
        self.state.total_buy_fees_quote -= self.state.total_buy_fees_quote * ratio
        self.state.total_btc -= quantity
        self.state.fills.append(
            {
                "side": "sell",
                "price": str(price),
                "quantity": str(quantity),
            }
        )
        if self.state.total_btc <= 0:
            self.state.total_btc = Decimal("0")
            self.state.total_buy_quote = Decimal("0")
            self.state.total_buy_fees_quote = Decimal("0")
            self.state.last_fill_price = None
            self.state.next_add_trigger = None
            self.state.partial_exit_done = False

    def _finalize_order(self, tracked: TrackedOrder) -> None:
        if self.state is None:
            return
        if tracked.role == "tp1" and tracked.filled_qty >= tracked.quantity:
            self.state.partial_exit_done = True
        if tracked.role == "tp2" and tracked.filled_qty >= tracked.quantity:
            self.state.total_btc = Decimal("0")
            self.state.total_buy_quote = Decimal("0")
            self.state.total_buy_fees_quote = Decimal("0")
            self.state.last_fill_price = None
            self.state.next_add_trigger = None
            self.state.partial_exit_done = False

    @staticmethod
    def _is_recoverable_order_error(exc: RestError) -> bool:
        message = str(exc).lower()
        recoverable_fragments = ("bad userprovidedid",)
        if not any(fragment in message for fragment in recoverable_fragments):
            return False
        return (
            "http error 400" in message or "400" in message or "bad request" in message
        )

    @staticmethod
    def _is_insufficient_funds_error(exc: RestError) -> bool:
        return "insufficient funds" in str(exc).lower()

    def _has_sufficient_balance_for_order(
        self, *, side: str, price: Decimal, quantity: Decimal
    ) -> bool:
        try:
            balances = self.client.get_balances()
        except Exception as exc:
            LOGGER.warning("Unable to fetch balances after order error: %s", exc)
            return True
        base_asset, quote_asset = self._split_symbol(self.config.symbol)
        if side.lower() == "buy":
            available_quote = balances.get(quote_asset, (Decimal("0"), Decimal("0")))[0]
            return available_quote >= price * quantity
        available_base = balances.get(base_asset, (Decimal("0"), Decimal("0")))[0]
        return available_base >= quantity

    def _cap_sell_quantity_to_available(self, quantity: Decimal) -> Decimal:
        try:
            balances = self.client.get_balances()
        except Exception as exc:
            LOGGER.warning(
                "Unable to fetch balances before sell placement; "
                "keeping requested quantity: %s",
                exc,
            )
            return quantity
        base_asset, _ = self._split_symbol(self.config.symbol)
        if base_asset not in balances:
            return quantity
        available_base = balances[base_asset][0]
        if available_base <= 0:
            return Decimal("0")
        if available_base < quantity:
            LOGGER.warning(
                "Reducing sell quantity to available balance: %s -> %s",
                quantity,
                available_base,
            )
            return available_base
        return quantity

    @staticmethod
    def _split_symbol(symbol: str) -> tuple[str, str]:
        if "/" in symbol:
            base, quote = symbol.split("/", 1)
        elif "-" in symbol:
            base, quote = symbol.split("-", 1)
        elif "_" in symbol:
            base, quote = symbol.split("_", 1)
        else:
            raise ValueError(f"Unsupported symbol format: {symbol}")
        return base, quote


def describe() -> str:
    return (
        "Adaptive capped martingale (spot-only mean reversion) with fee-aware "
        "cycle tracking, capped geometric adds, and staged take-profit exits."
    )
