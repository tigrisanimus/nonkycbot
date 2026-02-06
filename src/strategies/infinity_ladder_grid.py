"""Infinity ladder grid strategy - grid bot with no upper limit.

Like standard ladder grid but with unlimited upside:
- Places buy orders below current price (with lower limit)
- Places sell orders above current price (NO upper limit)
- When sell order fills, places new sell order above highest
- When buy order fills, refills at that level
- Continuously extends the sell ladder as price rises

Sizing behavior (default):
- BUY orders stay fixed in base size (legacy behavior)
- SELL orders size dynamically from a quote target, shrinking as price rises
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from engine.exchange_client import ExchangeClient
from nonkyc_client.rest import RestError, TransientApiError
from utils.profit_calculator import (
    calculate_grid_profit,
    calculate_min_profitable_step_pct,
    validate_order_profitability,
)

if TYPE_CHECKING:
    from utils.profit_store import ProfitStore

LOGGER = logging.getLogger("nonkyc_bot.strategy.infinity_ladder_grid")


@dataclass(frozen=True)
class InfinityLadderGridConfig:
    """Configuration for infinity ladder grid."""

    symbol: str
    step_mode: str  # "pct" or "abs"
    step_pct: Decimal | None
    step_abs: Decimal | None
    n_buy_levels: int  # Number of buy levels below entry
    initial_sell_levels: (
        int  # Initial sell levels above entry (more added as price rises)
    )
    base_order_size: Decimal
    min_notional_quote: Decimal
    fee_buffer_pct: Decimal
    total_fee_rate: Decimal
    tick_size: Decimal
    step_size: Decimal
    poll_interval_sec: float
    buy_sizing_mode: str = "fixed"
    sell_sizing_mode: str = "dynamic"
    fixed_base_order_qty: Decimal | None = None
    target_quote_per_order: Decimal | None = None
    min_base_order_qty: Decimal | None = None
    min_order_qty: Decimal | None = None
    fetch_backoff_sec: float = 15.0
    startup_cancel_all: bool = False
    startup_rebalance: bool = False
    rebalance_target_base_pct: Decimal = Decimal("0.5")
    rebalance_slippage_pct: Decimal = Decimal("0.002")
    rebalance_max_attempts: int = 2
    reconcile_interval_sec: float = 60.0
    balance_refresh_sec: float = 60.0
    mode: str = "live"  # "live", "dry-run", or "monitor"
    extend_buy_levels_on_restart: bool = False


@dataclass
class LiveOrder:
    """Live order on the exchange."""

    side: str
    price: Decimal
    quantity: Decimal
    client_id: str
    created_at: float
    cost_basis: Decimal | None = None


@dataclass
class InfinityLadderGridState:
    """State for infinity ladder grid."""

    entry_price: Decimal  # Initial entry price
    lowest_buy_price: Decimal  # Lowest buy level (lower limit)
    highest_sell_price: Decimal  # Highest sell level (tracks upward extension)
    open_orders: dict[str, LiveOrder] = field(default_factory=dict)
    needs_rebalance: bool = False
    last_mid: Decimal | None = None
    total_profit_quote: Decimal = Decimal("0")  # Net profit in quote currency


class InfinityLadderGridStrategy:
    """Infinity ladder grid - grid bot with unlimited upside."""

    def __init__(
        self,
        config: InfinityLadderGridConfig,
        client: ExchangeClient,
        state_path: Path,
        profit_store: ProfitStore | None = None,
    ):
        self.config = config
        self.client = client
        self.state_path = state_path
        self.profit_store = profit_store
        self.state = self._load_or_create_state()
        self._balances: dict[str, tuple[Decimal, Decimal]] = {}
        self._halted_sides: set[str] = set()
        self._last_balance_refresh = 0.0
        self._exit_triggered = False
        self._startup_reconcile_open_orders()

    def _load_or_create_state(self) -> InfinityLadderGridState:
        """Load existing state or create new."""
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    data = json.load(f)
                orders = {
                    oid: LiveOrder(
                        side=o["side"],
                        price=Decimal(o["price"]),
                        quantity=Decimal(o["quantity"]),
                        client_id=o["client_id"],
                        created_at=o["created_at"],
                        cost_basis=(
                            Decimal(o["cost_basis"])
                            if o.get("cost_basis") is not None
                            else None
                        ),
                    )
                    for oid, o in data.get("open_orders", {}).items()
                }
                return InfinityLadderGridState(
                    entry_price=Decimal(data["entry_price"]),
                    lowest_buy_price=Decimal(data["lowest_buy_price"]),
                    highest_sell_price=Decimal(data["highest_sell_price"]),
                    open_orders=orders,
                    needs_rebalance=data.get("needs_rebalance", False),
                    last_mid=(
                        Decimal(data["last_mid"]) if data.get("last_mid") else None
                    ),
                    total_profit_quote=Decimal(data.get("total_profit_quote", "0")),
                )
            except Exception as exc:
                LOGGER.warning(f"Failed to load state: {exc}, creating new state")

        # Create new state - will be initialized in seed_ladder
        mid_price = self.client.get_mid_price(self.config.symbol)
        step = self._get_step_size(mid_price)
        lowest_buy = mid_price * (Decimal("1") - step * self.config.n_buy_levels)
        highest_sell = mid_price * (
            Decimal("1") + step * self.config.initial_sell_levels
        )

        return InfinityLadderGridState(
            entry_price=mid_price,
            lowest_buy_price=lowest_buy,
            highest_sell_price=highest_sell,
        )

    def _startup_reconcile_open_orders(self) -> None:
        """Sync open orders from the exchange when the state is empty or stale."""
        if self.state.open_orders:
            return
        try:
            open_orders = self.client.list_open_orders(self.config.symbol)
        except Exception as exc:
            LOGGER.warning("Failed to fetch open orders for startup sync: %s", exc)
            return
        if not open_orders:
            return
        now = time.time()
        reconciled: dict[str, LiveOrder] = {}
        buy_prices: list[Decimal] = []
        sell_prices: list[Decimal] = []
        for order in open_orders:
            side = order.side.lower()
            if side == "buy":
                buy_prices.append(order.price)
            elif side == "sell":
                sell_prices.append(order.price)
            reconciled[order.order_id] = LiveOrder(
                side=side,
                price=order.price,
                quantity=order.quantity,
                client_id=order.order_id,
                created_at=now,
            )
        if buy_prices:
            self.state.lowest_buy_price = min(buy_prices)
        if sell_prices:
            self.state.highest_sell_price = max(sell_prices)
        self.state.entry_price = self.client.get_mid_price(self.config.symbol)
        self.state.last_mid = self.state.entry_price
        self.state.open_orders = reconciled
        self.save_state()
        LOGGER.info(
            "Synced %d open orders from exchange on startup.",
            len(self.state.open_orders),
        )

    def save_state(self) -> None:
        """Save state to disk."""
        payload = {
            "entry_price": str(self.state.entry_price),
            "lowest_buy_price": str(self.state.lowest_buy_price),
            "highest_sell_price": str(self.state.highest_sell_price),
            "open_orders": {
                oid: {
                    "side": o.side,
                    "price": str(o.price),
                    "quantity": str(o.quantity),
                    "client_id": o.client_id,
                    "created_at": o.created_at,
                    "cost_basis": (
                        str(o.cost_basis) if o.cost_basis is not None else None
                    ),
                }
                for oid, o in self.state.open_orders.items()
            },
            "needs_rebalance": self.state.needs_rebalance,
            "last_mid": str(self.state.last_mid) if self.state.last_mid else None,
            "total_profit_quote": str(self.state.total_profit_quote),
        }
        self.state_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    def _get_step_size(self, ref_price: Decimal) -> Decimal:
        """Get step size based on mode."""
        if self.config.step_mode == "pct":
            if self.config.step_pct is None:
                raise ValueError("step_pct is required when step_mode is pct")
            return self.config.step_pct
        if self.config.step_abs is None:
            raise ValueError("step_abs is required when step_mode is abs")
        return self.config.step_abs / ref_price

    def _quantize_price(self, price: Decimal) -> Decimal:
        """Round price to tick size."""
        return (price / self.config.tick_size).quantize(
            Decimal("1"), rounding=ROUND_DOWN
        ) * self.config.tick_size

    def _quantize_quantity(self, quantity: Decimal) -> Decimal:
        """Round quantity to step size."""
        return (quantity / self.config.step_size).quantize(
            Decimal("1"), rounding=ROUND_DOWN
        ) * self.config.step_size

    def _resolve_sizing_mode(self, side: str) -> str:
        """Resolve sizing mode for a given side."""
        if side.lower() == "buy":
            return self.config.buy_sizing_mode
        return self.config.sell_sizing_mode

    def _resolve_fixed_base_order_qty(self) -> Decimal:
        """Resolve fixed base quantity, preserving legacy base_order_size."""
        if self.config.fixed_base_order_qty is not None:
            return self.config.fixed_base_order_qty
        return self.config.base_order_size

    def _resolve_target_quote_per_order(self) -> Decimal:
        """Resolve quote-denominated target used for dynamic sizing."""
        if self.config.target_quote_per_order is not None:
            return self.config.target_quote_per_order
        return self._resolve_fixed_base_order_qty() * self.state.entry_price

    def _resolve_min_base_order_qty(self) -> Decimal | None:
        """Resolve minimum base quantity for hybrid sizing."""
        if self.config.min_base_order_qty is not None:
            return self.config.min_base_order_qty
        return None

    def _resolve_order_quantity(self, side: str, price: Decimal) -> Decimal | None:
        """Resolve order quantity using side-specific sizing and exchange guards."""
        sizing_mode = self._resolve_sizing_mode(side).lower()
        fixed_base_qty = self._resolve_fixed_base_order_qty()
        min_base_quantized: Decimal | None = None

        if sizing_mode == "fixed":
            quantity = fixed_base_qty
        else:
            target_quote = self._resolve_target_quote_per_order()
            if price <= 0:
                return None
            quantity = target_quote / price
            if sizing_mode == "hybrid":
                min_base = self._resolve_min_base_order_qty()
                if min_base is None:
                    raise ValueError(
                        "min_base_order_qty is required for hybrid sizing mode."
                    )
                if self.config.step_size > 0:
                    min_base_quantized = (min_base / self.config.step_size).quantize(
                        Decimal("1"), rounding=ROUND_UP
                    ) * self.config.step_size
                else:
                    min_base_quantized = min_base
                quantity = max(min_base_quantized, quantity)

        quantity = self._quantize_quantity(quantity)
        if min_base_quantized is not None:
            quantity = max(min_base_quantized, quantity)
        if quantity <= 0:
            return None
        if (
            self.config.min_order_qty is not None
            and quantity < self.config.min_order_qty
        ):
            LOGGER.warning(
                "Skipping %s order below min_qty: %s < %s",
                side.upper(),
                quantity,
                self.config.min_order_qty,
            )
            return None
        if price * quantity < self.config.min_notional_quote:
            LOGGER.warning(
                "Skipping %s order below min_notional: %s < %s",
                side.upper(),
                price * quantity,
                self.config.min_notional_quote,
            )
            return None
        return quantity

    def _refresh_balances(self, now: float) -> None:
        """Refresh balance cache."""
        if now - self._last_balance_refresh < self.config.balance_refresh_sec:
            return
        balances = self.client.get_balances()
        self._balances = balances
        self._last_balance_refresh = now
        if not self._halted_sides:
            return
        base, quote = self._split_symbol(self.config.symbol)
        base_available = self._balances.get(base, (Decimal("0"), Decimal("0")))[0]
        quote_available = self._balances.get(quote, (Decimal("0"), Decimal("0")))[0]
        if base_available > 0:
            self._halted_sides.discard("sell")
        if quote_available > 0:
            self._halted_sides.discard("buy")

    def _sync_client_order_counter(self, order_ids: list[str]) -> None:
        """Best-effort sync for fake exchange counters used in tests."""
        if not hasattr(self.client, "_order_count"):
            return
        try:
            current = int(getattr(self.client, "_order_count"))
        except (TypeError, ValueError):
            return
        max_seen = current
        for order_id in order_ids:
            for prefix in ("order-", "market-"):
                if order_id.startswith(prefix):
                    suffix = order_id[len(prefix) :]
                    if suffix.isdigit():
                        max_seen = max(max_seen, int(suffix))
                    break
        if max_seen > current:
            setattr(self.client, "_order_count", max_seen)

    def _has_sufficient_balance(
        self, side: str, price: Decimal, quantity: Decimal
    ) -> bool:
        """Check if sufficient balance for order."""
        if not self._balances:
            return True
        base, quote = self._split_symbol(self.config.symbol)
        if side.lower() == "buy":
            available = self._balances.get(quote, (Decimal("0"), Decimal("0")))[0]
            return available >= price * quantity
        available = self._balances.get(base, (Decimal("0"), Decimal("0")))[0]
        return available >= quantity

    def _place_order(
        self, side: str, price: Decimal, *, cost_basis: Decimal | None = None
    ) -> bool:
        """Place a single order."""
        if side.lower() in self._halted_sides:
            return False

        price = self._quantize_price(price)
        quantity = self._resolve_order_quantity(side, price)
        if quantity is None:
            return False

        # Check mode - skip actual placement in monitor/dry-run modes
        if self.config.mode == "monitor":
            LOGGER.info(
                "MONITOR MODE: Would place %s order at %s for %s (not executed)",
                side.upper(),
                price,
                quantity,
            )
            return False
        if self.config.mode == "dry-run":
            LOGGER.info(
                "DRY RUN: Simulating %s order at %s for %s",
                side.upper(),
                price,
                quantity,
            )
            # In dry-run, we still track the order locally but don't place it
            client_id = f"dryrun-{side}-{uuid.uuid4().hex}"
            fake_order_id = f"dryrun-{uuid.uuid4().hex}"
            self.state.open_orders[fake_order_id] = LiveOrder(
                side=side,
                price=price,
                quantity=quantity,
                client_id=client_id,
                created_at=time.time(),
                cost_basis=cost_basis,
            )
            return True

        # Check minimum balance
        if not self._has_sufficient_balance(side, price, quantity):
            base, quote = self._split_symbol(self.config.symbol)
            required_asset = quote if side.lower() == "buy" else base
            required_amount = price * quantity if side.lower() == "buy" else quantity
            available = (
                self._balances.get(required_asset, (Decimal("0"), Decimal("0")))[0]
                if self._balances
                else Decimal("0")
            )
            LOGGER.warning(
                "Insufficient balance to place %s order at %s. Required: %s %s, Available: %s %s. "
                "Setting needs_rebalance=True or deposit more funds.",
                side.upper(),
                price,
                required_amount,
                required_asset,
                available,
                required_asset,
            )
            self.state.needs_rebalance = True
            self._halted_sides.add(side.lower())
            return False

        # Calculate opposing price (one step away in the opposite direction)
        step = self._get_step_size(price)
        if side.lower() == "buy":
            # For buy orders, the opposing sell is one step up
            opposing_price = price * (Decimal("1") + step)
        else:
            # For sell orders, the opposing buy is one step down
            opposing_price = price * (Decimal("1") - step)

        # Validate order profitability
        is_valid, reason = validate_order_profitability(
            side=side,
            price=price,
            quantity=quantity,
            opposing_price=opposing_price,
            total_fee_rate=self.config.total_fee_rate,
            fee_buffer_pct=self.config.fee_buffer_pct,
            min_notional_quote=self.config.min_notional_quote,
        )

        if not is_valid:
            LOGGER.warning(
                "Skipping unprofitable order: %s. Grid spacing may be too small.",
                reason,
            )
            return False

        client_id = f"infinity-{side}-{uuid.uuid4().hex}"
        try:
            order_id = self.client.place_limit(
                self.config.symbol, side, price, quantity, client_id
            )
        except RestError as exc:
            if "Insufficient funds" in str(exc):
                self.state.needs_rebalance = True
                self._halted_sides.add(side.lower())
                return False
            if self._is_recoverable_order_error(exc):
                LOGGER.warning(
                    "Recoverable order placement error: %s. Skipping %s order at %s.",
                    exc,
                    side.upper(),
                    price,
                )
                return False
            raise

        self.state.open_orders[order_id] = LiveOrder(
            side=side,
            price=price,
            quantity=quantity,
            client_id=client_id,
            created_at=time.time(),
            cost_basis=cost_basis,
        )
        LOGGER.info(
            f"Placed {side.upper()} order: {quantity} @ {price} (order_id={order_id})"
        )
        return True

    @staticmethod
    def _is_recoverable_order_error(exc: RestError) -> bool:
        message = str(exc).lower()
        recoverable_fragments = ("bad userprovidedid",)
        if not any(fragment in message for fragment in recoverable_fragments):
            return False
        return (
            "http error 400" in message or "400" in message or "bad request" in message
        )

    def _build_buy_levels(self, mid_price: Decimal) -> list[tuple[str, Decimal]]:
        """Build buy levels below mid price down to lowest_buy_price."""
        step = self._get_step_size(mid_price)
        levels = []
        for i in range(1, self.config.n_buy_levels + 1):
            price = mid_price * (Decimal("1") - step * i)
            if price >= self.state.lowest_buy_price:
                levels.append(("buy", price))
        return levels

    def _build_initial_sell_levels(
        self, mid_price: Decimal
    ) -> list[tuple[str, Decimal]]:
        """Build initial sell levels above mid price."""
        step = self._get_step_size(mid_price)
        levels = []
        for i in range(1, self.config.initial_sell_levels + 1):
            price = mid_price * (Decimal("1") + step * i)
            levels.append(("sell", price))
        return levels

    def _validate_profitability(self, mid_price: Decimal) -> None:
        """Validate that grid spacing is sufficient for profitability."""
        min_step_pct = calculate_min_profitable_step_pct(
            self.config.total_fee_rate, self.config.fee_buffer_pct
        )

        if self.config.step_mode == "pct":
            if self.config.step_pct is None:
                raise ValueError("step_pct is required for pct step mode.")
            if self.config.step_pct < min_step_pct:
                raise ValueError(
                    f"Grid spacing too small to be profitable after fees: "
                    f"step_pct={self.config.step_pct * 100:.4f}% < "
                    f"min_profitable_step={min_step_pct * 100:.4f}% "
                    f"(fee_rate={self.config.total_fee_rate * 100:.2f}%, "
                    f"buffer={self.config.fee_buffer_pct * 100:.2f}%)"
                )
        else:
            # For absolute step mode, convert to percentage at mid price
            if self.config.step_abs is None:
                raise ValueError("step_abs is required for abs step mode.")
            step_pct_at_mid = self.config.step_abs / mid_price
            if step_pct_at_mid < min_step_pct:
                raise ValueError(
                    f"Grid spacing too small to be profitable after fees: "
                    f"step_abs={self.config.step_abs} at mid_price={mid_price} "
                    f"is {step_pct_at_mid * 100:.4f}% < "
                    f"min_profitable_step={min_step_pct * 100:.4f}%"
                )

    def seed_ladder(self) -> None:
        """Initialize the infinity grid with orders."""
        if self.state.open_orders:
            if not self.config.extend_buy_levels_on_restart:
                LOGGER.info(
                    "Open orders already tracked (%d); skipping seed.",
                    len(self.state.open_orders),
                )
                return
            self._extend_buy_levels()
            return
        self._halted_sides.clear()
        self._refresh_balances(time.time())

        mid_price = self.client.get_mid_price(self.config.symbol)
        self.state.last_mid = mid_price

        # Validate profitability before placing any orders
        self._validate_profitability(mid_price)

        # Build levels
        buy_levels = self._build_buy_levels(mid_price)
        sell_levels = self._build_initial_sell_levels(mid_price)

        base, quote = self._split_symbol(self.config.symbol)
        base_balance = (
            self._balances.get(base, (Decimal("0"), Decimal("0")))[0]
            if self._balances
            else Decimal("0")
        )
        quote_balance = (
            self._balances.get(quote, (Decimal("0"), Decimal("0")))[0]
            if self._balances
            else Decimal("0")
        )

        LOGGER.info(
            "Seeding infinity grid: entry=%s, %d buy levels (down to %s), %d initial sell levels (up to %s). "
            "Balances: %s %s, %s %s",
            mid_price,
            len(buy_levels),
            self.state.lowest_buy_price,
            len(sell_levels),
            self.state.highest_sell_price,
            base_balance,
            base,
            quote_balance,
            quote,
        )

        # Place all orders
        for side, price in buy_levels + sell_levels:
            self._place_order(side, price)

        orders_placed = len(self.state.open_orders)
        total_levels = len(buy_levels) + len(sell_levels)

        if orders_placed < total_levels:
            LOGGER.warning(
                "Only placed %d/%d orders. Insufficient balance. "
                "Deposit more funds or enable startup_rebalance.",
                orders_placed,
                total_levels,
            )
        else:
            LOGGER.info("✓ Successfully placed all %d orders", orders_placed)

        # Update highest sell price
        sell_prices = [
            o.price for o in self.state.open_orders.values() if o.side == "sell"
        ]
        if sell_prices:
            self.state.highest_sell_price = max(sell_prices)

        self.save_state()

    def _extend_buy_levels(self) -> None:
        """Extend buy ladder lower without canceling existing orders."""
        self._halted_sides.discard("buy")
        now = time.time()
        self._refresh_balances(now)

        mid_price = self.client.get_mid_price(self.config.symbol)
        self.state.last_mid = mid_price

        self._validate_profitability(mid_price)

        existing_buy_prices = {
            self._quantize_price(order.price)
            for order in self.state.open_orders.values()
            if order.side == "buy"
        }
        self._sync_client_order_counter(list(self.state.open_orders.keys()))
        step = self._get_step_size(mid_price)
        target_levels = [
            self._quantize_price(mid_price * (Decimal("1") - step * i))
            for i in range(1, self.config.n_buy_levels + 1)
            if mid_price * (Decimal("1") - step * i) < self.state.lowest_buy_price
        ]
        levels_to_add = [
            price for price in target_levels if price not in existing_buy_prices
        ]

        if not levels_to_add:
            LOGGER.info(
                "No additional buy levels needed on restart. "
                "lowest_buy=%s target_lowest=%s",
                self.state.lowest_buy_price,
                min(target_levels) if target_levels else self.state.lowest_buy_price,
            )
            return

        LOGGER.info(
            "Extending buy ladder: current_lowest=%s target_lowest=%s levels=%d",
            self.state.lowest_buy_price,
            min(levels_to_add),
            len(levels_to_add),
        )

        placed_prices: list[Decimal] = []
        for price in sorted(levels_to_add, reverse=True):
            if self._place_order("buy", price):
                placed_prices.append(self._quantize_price(price))
            if "buy" in self._halted_sides:
                break

        if placed_prices:
            self.state.lowest_buy_price = min(
                self.state.lowest_buy_price, min(placed_prices)
            )
            self.save_state()
        else:
            LOGGER.warning(
                "Failed to place additional buy levels on restart. "
                "Deposit more funds or adjust configuration."
            )

    def reconcile(self, now: float) -> None:
        """Check for filled orders and refill the grid."""
        filled = []
        for order_id, order in list(self.state.open_orders.items()):
            # Retry order fetch with exponential backoff on transient errors
            status = None
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    status = self.client.get_order(order_id)
                    break  # Success
                except TransientApiError as exc:
                    if attempt < max_retries - 1:
                        backoff = self.config.fetch_backoff_sec * (2**attempt)
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
                except Exception as exc:
                    LOGGER.warning(
                        "Error fetching order %s; skipping update: %s", order_id, exc
                    )
                    break

            if status is None:
                continue

            normalized_status = status.status.lower() if status.status else ""
            filled_statuses = {"filled", "closed", "partly filled"}
            cancelled_statuses = {"cancelled", "canceled", "rejected", "expired"}

            if normalized_status in filled_statuses or status.status in {
                "Filled",
                "Partly Filled",
            }:
                LOGGER.info(
                    "Order filled: %s %s @ %s (order_id=%s)",
                    order.side.upper(),
                    order.quantity,
                    order.price,
                    order_id,
                )
                filled.append((order_id, order))

                if order.side == "sell":
                    if order.cost_basis is not None:
                        net_profit = calculate_grid_profit(
                            order.cost_basis,
                            order.price,
                            order.quantity,
                            self.config.total_fee_rate,
                        )
                        self.state.total_profit_quote += net_profit
                        if self.profit_store is not None:
                            _, quote = self._split_symbol(self.config.symbol)
                            self.profit_store.record_profit(net_profit, quote)
                        LOGGER.info(
                            "Sell net profit: %s (cumulative: %s)",
                            net_profit,
                            self.state.total_profit_quote,
                        )
                    else:
                        LOGGER.info(
                            "Sell filled with unknown cost basis; net profit not tracked."
                        )
            elif normalized_status in cancelled_statuses or status.status in {
                "Cancelled",
                "Canceled",
            }:
                LOGGER.info(
                    "Order cancelled/expired: %s %s @ %s (order_id=%s)",
                    order.side.upper(),
                    order.quantity,
                    order.price,
                    order_id,
                )
                del self.state.open_orders[order_id]

        if not filled:
            return

        self._sync_client_order_counter(list(self.state.open_orders.keys()))

        # Remove filled orders
        for order_id, _ in filled:
            del self.state.open_orders[order_id]

        if self.profit_store is not None and self.profit_store.should_trigger_exit():
            self._handle_profit_store_exit(now)
            return

        # Refill orders
        self._refresh_balances(now)

        for order_id, order in filled:
            if order.side == "buy":
                # Buy filled - place SELL order one step above to take profit
                step = self._get_step_size(order.price)
                new_sell_price = order.price * (Decimal("1") + step)
                if self._place_order("sell", new_sell_price, cost_basis=order.price):
                    LOGGER.info(
                        "Buy filled at %s, placed sell at %s",
                        order.price,
                        new_sell_price,
                    )
            else:
                # Sell filled - TWO actions:
                # 1. Extend the ladder upward (no upper limit!)
                step = self._get_step_size(self.state.highest_sell_price)
                new_sell_price = self.state.highest_sell_price * (Decimal("1") + step)
                placed_sell = self._place_order("sell", new_sell_price)

                # Update highest sell price
                if placed_sell and new_sell_price > self.state.highest_sell_price:
                    self.state.highest_sell_price = new_sell_price
                    LOGGER.info(
                        "Extended sell ladder to %s (no upper limit!)",
                        new_sell_price,
                    )

                # 2. Place buy order below to buy back (if above lower limit)
                step = self._get_step_size(order.price)
                new_buy_price = order.price * (Decimal("1") - step)
                if new_buy_price >= self.state.lowest_buy_price:
                    if self._place_order("buy", new_buy_price):
                        LOGGER.info(
                            "Sell filled at %s, placed buy-back at %s",
                            order.price,
                            new_buy_price,
                        )
                else:
                    LOGGER.info(
                        "Sell filled at %s, but %s below lower limit %s, no buy-back placed",
                        order.price,
                        new_buy_price,
                        self.state.lowest_buy_price,
                    )

        self.save_state()
        if self.profit_store is not None:
            self.profit_store.process()

    def _handle_profit_store_exit(self, now: float) -> None:
        if self._exit_triggered:
            return
        self._exit_triggered = True
        self._halted_sides = {"buy", "sell"}
        if self.config.mode == "monitor":
            LOGGER.info("MONITOR MODE: Profit-store exit triggered; no orders placed.")
            return
        if self.config.mode == "dry-run":
            LOGGER.info("DRY RUN: Profit-store exit triggered; no orders placed.")
            return
        for order_id in list(self.state.open_orders.keys()):
            try:
                self.client.cancel_order(order_id)
            except Exception as exc:
                LOGGER.warning("Exit cancel failed for %s: %s", order_id, exc)
            self.state.open_orders.pop(order_id, None)
        self.save_state()
        self._refresh_balances(now)
        base, quote = self._split_symbol(self.config.symbol)
        base_available = self._balances.get(base, (Decimal("0"), Decimal("0")))[0]
        if base_available <= 0:
            LOGGER.info("Exit triggered but no %s balance to sell.", base)
            return
        profit_config = self.profit_store.config if self.profit_store else None
        if profit_config is None:
            return
        dump_qty = base_available * profit_config.exit_dump_pct
        if dump_qty <= 0:
            return
        try:
            best_bid, _ = self.client.get_orderbook_top(self.config.symbol)
        except Exception as exc:
            LOGGER.warning("Exit failed to read orderbook: %s", exc)
            return
        limit_price = best_bid * (Decimal("1") - profit_config.aggressive_limit_pct)
        if limit_price <= 0:
            return
        sell_qty = self._quantize_quantity(dump_qty)
        if sell_qty <= 0:
            return
        try:
            self.client.place_limit(self.config.symbol, "sell", limit_price, sell_qty)
            LOGGER.info("Exit placed SELL %s %s @ %s", sell_qty, base, limit_price)
        except Exception as exc:
            LOGGER.warning("Exit SELL placement failed: %s", exc)
            return
        quote_estimate = sell_qty * limit_price
        convert_quote = quote_estimate * profit_config.exit_convert_pct
        if convert_quote <= 0:
            return
        try:
            _, ask = self.client.get_orderbook_top(profit_config.target_symbol)
        except Exception as exc:
            LOGGER.warning(
                "Exit failed to read %s orderbook: %s",
                profit_config.target_symbol,
                exc,
            )
            return
        buy_price = ask * (Decimal("1") + profit_config.aggressive_limit_pct)
        if buy_price <= 0:
            return
        buy_qty = convert_quote / buy_price
        if buy_qty <= 0:
            return
        try:
            self.client.place_limit(
                profit_config.target_symbol, "buy", buy_price, buy_qty
            )
            LOGGER.info(
                "Exit placed %s BUY %s @ %s",
                profit_config.target_symbol,
                buy_qty,
                buy_price,
            )
        except Exception as exc:
            LOGGER.warning("Exit profit-store BUY failed: %s", exc)

    @staticmethod
    def _split_symbol(symbol: str) -> tuple[str, str]:
        """Parse symbol into base/quote."""
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
    return "Infinity ladder grid - grid bot with unlimited upside potential."
