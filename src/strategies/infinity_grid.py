"""Infinity grid strategy for trending markets with no upper limit.

Infinity Grid maintains a constant value in the base asset while profiting from uptrends.
Unlike standard grid trading which has upper/lower bounds, infinity grid only has a lower
limit and allows unlimited upside.

IMPORTANT: This is a TWO-SIDED grid. You need BOTH base and quote assets:
- Base asset (BTC): For selling as price rises
- Quote asset (USDT): For buying as price drops below entry

Example (BTC_USDT):
- Entry: BTC = $50,000, you hold 1 BTC + $10,000 USDT
- Constant value: $50,000 (maintained in BTC)
- Lower limit: Calculated from USDT allocation (~$40,000 with $10k USDT)

Price rises to $50,500 (+1%): Sell 0.0099 BTC to maintain $50,000 value, profit = $500
Price rises to $51,005 (+1%): Sell more BTC to maintain $50,000 value, profit = $500
Price drops to $49,500 (-1%): Buy BTC using allocated USDT to restore $50,000 value
Price drops to $49,000 (-1%): Buy more BTC using allocated USDT

This strategy is optimal for bull markets with consistent uptrends.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class InfinityGridOrder:
    """Represents a rebalance order for infinity grid."""

    side: str  # "buy" or "sell"
    amount: Decimal  # Amount of base asset to trade
    price: Decimal  # Current market price
    reason: str  # Why this order was generated


@dataclass(frozen=True)
class InfinityGridState:
    """State for infinity grid strategy."""

    constant_value_quote: Decimal  # Target value to maintain in quote currency
    last_rebalance_price: Decimal  # Price at last rebalance
    step_pct: Decimal  # Grid spacing as percentage (e.g., 0.01 = 1%)
    lower_limit: Decimal  # Lower price limit based on quote allocation
    allocated_quote: Decimal  # Quote currency allocated for buying dips
    total_profit_quote: Decimal = Decimal("0")  # Accumulated profit in quote


def _to_decimal(value: Decimal | int | str) -> Decimal:
    """Convert various numeric types to Decimal."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def calculate_lower_limit(
    *,
    entry_price: Decimal,
    step_pct: Decimal,
    quote_balance: Decimal,
    constant_value: Decimal,
) -> tuple[Decimal, int]:
    """Calculate lower price limit based on available quote currency.

    The lower limit is determined by how many grid levels down the quote
    balance can support while maintaining the constant value.

    Args:
        entry_price: Entry price (current market price)
        step_pct: Grid step percentage
        quote_balance: Available quote currency (USDT) for buying
        constant_value: Constant value being maintained

    Returns:
        Tuple of (lower_limit_price, num_levels_supported)
    """
    if quote_balance <= 0:
        return entry_price, 0

    # Simulate stepping down to find how far we can go
    current_price = entry_price
    remaining_quote = quote_balance
    levels = 0

    while remaining_quote > 0:
        # Calculate next lower price level
        next_price = current_price * (Decimal("1") - step_pct)

        # Calculate how much base we'd need to buy at this level
        target_base_at_next = constant_value / next_price
        current_base_at_next = constant_value / current_price
        buy_amount = target_base_at_next - current_base_at_next

        # Cost to buy this amount
        cost = buy_amount * next_price

        if cost > remaining_quote:
            # Can't afford a full level, this is our limit
            break

        remaining_quote -= cost
        current_price = next_price
        levels += 1

        # Safety limit: don't go below 50% of entry price
        if current_price < entry_price * Decimal("0.5"):
            break

    return current_price, levels


def initialize_infinity_grid(
    *,
    base_balance: Decimal | int | str,
    quote_balance: Decimal | int | str,
    current_price: Decimal | int | str,
    step_pct: Decimal | int | str,
) -> InfinityGridState:
    """Initialize infinity grid state.

    Args:
        base_balance: Current balance of base asset (e.g., BTC)
        quote_balance: Current balance of quote asset (e.g., USDT) allocated for buying dips
        current_price: Current market price
        step_pct: Grid spacing percentage (e.g., 0.01 for 1%)

    Returns:
        Initial infinity grid state
    """
    base = _to_decimal(base_balance)
    quote = _to_decimal(quote_balance)
    price = _to_decimal(current_price)
    step = _to_decimal(step_pct)

    if base <= 0:
        raise ValueError("base_balance must be positive")
    if quote < 0:
        raise ValueError("quote_balance cannot be negative")
    if price <= 0:
        raise ValueError("current_price must be positive")
    if step <= 0:
        raise ValueError("step_pct must be positive")

    # Calculate constant value in quote currency
    constant_value = base * price

    # Calculate lower limit based on quote allocation
    lower_limit, levels_supported = calculate_lower_limit(
        entry_price=price,
        step_pct=step,
        quote_balance=quote,
        constant_value=constant_value,
    )

    return InfinityGridState(
        constant_value_quote=constant_value,
        last_rebalance_price=price,
        step_pct=step,
        lower_limit=lower_limit,
        allocated_quote=quote,
        total_profit_quote=Decimal("0"),
    )


def calculate_infinity_grid_order(
    *,
    base_balance: Decimal | int | str,
    quote_balance: Decimal | int | str,
    current_price: Decimal | int | str,
    grid_state: InfinityGridState,
) -> InfinityGridOrder | None:
    """Calculate rebalance order for infinity grid.

    The infinity grid maintains a constant value in the base asset:
    - When price rises by step_pct: Sell base to maintain constant value
    - When price drops by step_pct: Buy base using allocated quote to restore constant value
    - No action if price hasn't moved enough

    Args:
        base_balance: Current balance of base asset
        quote_balance: Current balance of quote asset
        current_price: Current market price
        grid_state: Current infinity grid state

    Returns:
        Order to execute, or None if no rebalance needed
    """
    base = _to_decimal(base_balance)
    quote = _to_decimal(quote_balance)
    price = _to_decimal(current_price)

    if base < 0:
        raise ValueError("base_balance cannot be negative")
    if quote < 0:
        raise ValueError("quote_balance cannot be negative")
    if price <= 0:
        raise ValueError("current_price must be positive")

    # Check if price is below lower limit
    if price < grid_state.lower_limit:
        # Price below lower limit - out of quote to buy more
        return None

    # Calculate price change percentage from last rebalance
    price_change_pct = (
        price - grid_state.last_rebalance_price
    ) / grid_state.last_rebalance_price

    # Determine if we need to rebalance
    # Sell trigger: price rose by at least step_pct
    # Buy trigger: price dropped by at least step_pct
    if abs(price_change_pct) < grid_state.step_pct:
        return None  # Not enough movement

    # Calculate target base amount to maintain constant value
    target_base = grid_state.constant_value_quote / price

    # Calculate how much to trade
    trade_amount = base - target_base

    if trade_amount > 0:
        # Need to sell (price went up)
        return InfinityGridOrder(
            side="sell",
            amount=trade_amount,
            price=price,
            reason=f"Price rose {price_change_pct * 100:.2f}%, selling to maintain constant value",
        )
    elif trade_amount < 0:
        # Need to buy (price went down)
        buy_amount = abs(trade_amount)
        cost = buy_amount * price

        # Check if we have enough quote to buy
        if cost > quote:
            # Not enough quote - adjust buy amount
            buy_amount = quote / price
            if buy_amount <= 0:
                return None

        return InfinityGridOrder(
            side="buy",
            amount=buy_amount,
            price=price,
            reason=f"Price dropped {price_change_pct * 100:.2f}%, buying to restore constant value",
        )

    return None  # No rebalance needed


def update_infinity_grid_state(
    *,
    current_state: InfinityGridState,
    new_rebalance_price: Decimal | int | str,
    profit_realized: Decimal | int | str = Decimal("0"),
) -> InfinityGridState:
    """Update infinity grid state after a rebalance.

    Args:
        current_state: Current grid state
        new_rebalance_price: Price at which rebalance occurred
        profit_realized: Profit realized from this rebalance (in quote currency)

    Returns:
        Updated grid state
    """
    new_price = _to_decimal(new_rebalance_price)
    profit = _to_decimal(profit_realized)

    return InfinityGridState(
        constant_value_quote=current_state.constant_value_quote,
        last_rebalance_price=new_price,
        step_pct=current_state.step_pct,
        lower_limit=current_state.lower_limit,
        allocated_quote=current_state.allocated_quote,
        total_profit_quote=current_state.total_profit_quote + profit,
    )


def describe() -> str:
    """Return strategy description."""
    return "Infinity grid: maintains constant base asset value with no upper limit, optimal for trending bull markets"
