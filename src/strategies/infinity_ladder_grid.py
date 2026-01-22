"""Infinity ladder grid strategy - grid bot with no upper limit.

Like standard ladder grid but with unlimited upside:
- Places buy orders below current price (with lower limit)
- Places sell orders above current price (NO upper limit)
- When sell order fills, places new sell order above highest
- When buy order fills, refills at that level
- Continuously extends the sell ladder as price rises
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

from engine.exchange_client import ExchangeClient
from nonkyc_client.rest import RestError
from utils.profit_calculator import (
    calculate_min_profitable_step_pct,
    validate_order_profitability,
)

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
    fetch_backoff_sec: float = 15.0
    startup_cancel_all: bool = False
    startup_rebalance: bool = False
    rebalance_target_base_pct: Decimal = Decimal("0.5")
    rebalance_slippage_pct: Decimal = Decimal("0.002")
    rebalance_max_attempts: int = 2
    reconcile_interval_sec: float = 60.0
    balance_refresh_sec: float = 60.0


@dataclass
class LiveOrder:
    """Live order on the exchange."""

    side: str
    price: Decimal
    quantity: Decimal
    client_id: str
    created_at: float


@dataclass
class InfinityLadderGridState:
    """State for infinity ladder grid."""

    entry_price: Decimal  # Initial entry price
    lowest_buy_price: Decimal  # Lowest buy level (lower limit)
    highest_sell_price: Decimal  # Highest sell level (tracks upward extension)
    open_orders: dict[str, LiveOrder] = field(default_factory=dict)
    needs_rebalance: bool = False
    last_mid: Decimal | None = None
    total_profit_quote: Decimal = Decimal("0")  # Accumulated profit from sells


class InfinityLadderGridStrategy:
    """Infinity ladder grid - grid bot with unlimited upside."""

    def __init__(
        self,
        config: InfinityLadderGridConfig,
        client: ExchangeClient,
        state_path: Path,
    ):
        self.config = config
        self.client = client
        self.state_path = state_path
        self.state = self._load_or_create_state()
        self._balances: dict[str, tuple[Decimal, Decimal]] = {}
        self._halt_placements = False
        self._last_balance_refresh = 0.0

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
            return self.config.step_pct
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

    def _refresh_balances(self, now: float) -> None:
        """Refresh balance cache."""
        if now - self._last_balance_refresh < self.config.balance_refresh_sec:
            return
        balances = self.client.get_balances()
        self._balances = balances
        self._last_balance_refresh = now

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

    def _place_order(self, side: str, price: Decimal, base_quantity: Decimal) -> None:
        """Place a single order."""
        if self._halt_placements:
            return

        price = self._quantize_price(price)
        quantity = self._quantize_quantity(base_quantity)

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
            self._halt_placements = True
            return

        # Calculate opposing price (one step away in the opposite direction)
        step = (
            self.config.step_pct
            if self.config.step_mode == "pct"
            else self.config.step_abs / price
        )
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
            return

        client_id = f"infinity-{side}-{int(time.time() * 1e6)}"
        try:
            order_id = self.client.place_limit(
                self.config.symbol, side, price, quantity, client_id
            )
        except RestError as exc:
            if "Insufficient funds" in str(exc):
                self.state.needs_rebalance = True
                self._halt_placements = True
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
            f"Placed {side.upper()} order: {quantity} @ {price} (order_id={order_id})"
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
        self._halt_placements = False
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
            self._place_order(side, price, self.config.base_order_size)

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

    def reconcile(self, now: float) -> None:
        """Check for filled orders and refill the grid."""
        filled = []
        for order_id, order in list(self.state.open_orders.items()):
            status = self.client.get_order(order_id)
            if status.status in ["filled", "closed"]:
                LOGGER.info(
                    "Order filled: %s %s @ %s (order_id=%s)",
                    order.side.upper(),
                    order.quantity,
                    order.price,
                    order_id,
                )
                filled.append((order_id, order))

                # Track profit from sells
                if order.side == "sell":
                    profit = order.quantity * order.price
                    self.state.total_profit_quote += profit
                    LOGGER.info(
                        f"Profit from sell: {profit} (total: {self.state.total_profit_quote})"
                    )

        # Remove filled orders
        for order_id, _ in filled:
            del self.state.open_orders[order_id]

        if not filled:
            return

        # Refill orders
        self._refresh_balances(now)
        mid_price = self.client.get_mid_price(self.config.symbol)
        step = self._get_step_size(mid_price)

        for order_id, order in filled:
            if order.side == "buy":
                # Buy filled - place SELL order one step above to take profit
                new_sell_price = order.price * (Decimal("1") + step)
                self._place_order("sell", new_sell_price, order.quantity)
                LOGGER.info(
                    f"Buy filled at {order.price}, placed sell at {new_sell_price}"
                )
            else:
                # Sell filled - TWO actions:
                # 1. Extend the ladder upward (no upper limit!)
                new_sell_price = self.state.highest_sell_price * (Decimal("1") + step)
                self._place_order("sell", new_sell_price, self.config.base_order_size)

                # Update highest sell price
                if new_sell_price > self.state.highest_sell_price:
                    self.state.highest_sell_price = new_sell_price
                    LOGGER.info(
                        f"Extended sell ladder to {new_sell_price} (no upper limit!)"
                    )

                # 2. Place buy order below to buy back (if above lower limit)
                new_buy_price = order.price * (Decimal("1") - step)
                if new_buy_price >= self.state.lowest_buy_price:
                    self._place_order("buy", new_buy_price, order.quantity)
                    LOGGER.info(
                        f"Sell filled at {order.price}, placed buy-back at {new_buy_price}"
                    )
                else:
                    LOGGER.info(
                        f"Sell filled at {order.price}, but {new_buy_price} below lower limit {self.state.lowest_buy_price}, no buy-back placed"
                    )

        self.save_state()

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
