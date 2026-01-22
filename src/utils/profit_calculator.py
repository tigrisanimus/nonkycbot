"""Profit calculation utilities for grid trading strategies."""

from decimal import Decimal


def calculate_min_profitable_sell_price(
    buy_price: Decimal,
    total_fee_rate: Decimal,
    fee_buffer_pct: Decimal = Decimal("0"),
) -> Decimal:
    """Calculate minimum sell price that results in profit after fees.

    Args:
        buy_price: Price at which asset was bought
        total_fee_rate: Total fee rate (maker + taker), e.g., 0.002 for 0.2%
        fee_buffer_pct: Additional safety buffer, e.g., 0.0001 for 0.01%

    Returns:
        Minimum sell price to break even after fees

    Example:
        buy_price = 100
        total_fee_rate = 0.002 (0.2%)
        fee_buffer_pct = 0.0001 (0.01%)

        Cost basis = 100 * (1 + 0.002) = 100.20 (buy price + buy fee)
        Min sell price = 100.20 / (1 - 0.002 - 0.0001) = 100.421

        This ensures: sell_revenue - buy_cost > 0
    """
    # Buy cost including fee
    buy_cost_per_unit = buy_price * (Decimal("1") + total_fee_rate)

    # Sell price must be high enough to cover buy cost + sell fee + buffer
    # sell_price * (1 - fee_rate - buffer) >= buy_cost
    # sell_price >= buy_cost / (1 - fee_rate - buffer)
    min_sell_price = buy_cost_per_unit / (
        Decimal("1") - total_fee_rate - fee_buffer_pct
    )

    return min_sell_price


def calculate_grid_profit(
    buy_price: Decimal,
    sell_price: Decimal,
    quantity: Decimal,
    total_fee_rate: Decimal,
) -> Decimal:
    """Calculate profit from a complete grid cycle (buy + sell).

    Args:
        buy_price: Buy order price
        sell_price: Sell order price
        quantity: Order quantity
        total_fee_rate: Total fee rate (maker + taker)

    Returns:
        Net profit in quote currency after all fees

    Example:
        buy_price = 100, sell_price = 101, quantity = 1, fee = 0.002

        Buy cost = 100 * 1 * (1 + 0.002) = 100.20
        Sell revenue = 101 * 1 * (1 - 0.002) = 100.798
        Profit = 100.798 - 100.20 = 0.598
    """
    # Cost to buy (including fee)
    buy_cost = buy_price * quantity * (Decimal("1") + total_fee_rate)

    # Revenue from sell (after fee)
    sell_revenue = sell_price * quantity * (Decimal("1") - total_fee_rate)

    # Net profit
    profit = sell_revenue - buy_cost

    return profit


def is_profitable_grid_level(
    buy_price: Decimal,
    sell_price: Decimal,
    total_fee_rate: Decimal,
    fee_buffer_pct: Decimal = Decimal("0"),
) -> bool:
    """Check if a grid level pair (buy/sell) will be profitable after fees.

    Args:
        buy_price: Buy order price
        sell_price: Sell order price
        total_fee_rate: Total fee rate (maker + taker)
        fee_buffer_pct: Additional safety buffer

    Returns:
        True if the grid level will be profitable, False otherwise
    """
    min_profitable_sell = calculate_min_profitable_sell_price(
        buy_price, total_fee_rate, fee_buffer_pct
    )
    return sell_price >= min_profitable_sell


def calculate_min_profitable_step_pct(
    total_fee_rate: Decimal,
    fee_buffer_pct: Decimal = Decimal("0"),
) -> Decimal:
    """Calculate minimum grid step percentage to be profitable.

    Args:
        total_fee_rate: Total fee rate (maker + taker)
        fee_buffer_pct: Additional safety buffer

    Returns:
        Minimum step percentage as decimal (e.g., 0.005 for 0.5%)

    Example:
        total_fee_rate = 0.002 (0.2%)
        fee_buffer_pct = 0.0001 (0.01%)

        min_step_pct ≈ 0.0042 (0.42%)

        This means grid levels must be at least 0.42% apart to profit.
    """
    # Using the formula from calculate_min_profitable_sell_price
    # min_sell / buy = (1 + fee) / (1 - fee - buffer)
    # min_step_pct = (min_sell / buy) - 1

    numerator = Decimal("1") + total_fee_rate
    denominator = Decimal("1") - total_fee_rate - fee_buffer_pct

    min_step_pct = (numerator / denominator) - Decimal("1")

    return min_step_pct


def meets_min_notional(
    price: Decimal,
    quantity: Decimal,
    min_notional_quote: Decimal,
) -> bool:
    """Check if order meets minimum notional value requirement.

    Args:
        price: Order price
        quantity: Order quantity
        min_notional_quote: Minimum order value in quote currency

    Returns:
        True if order meets minimum notional, False otherwise
    """
    notional_value = price * quantity
    return notional_value >= min_notional_quote


def validate_order_profitability(
    side: str,
    price: Decimal,
    quantity: Decimal,
    opposing_price: Decimal | None,
    total_fee_rate: Decimal,
    fee_buffer_pct: Decimal,
    min_notional_quote: Decimal,
) -> tuple[bool, str]:
    """Validate if an order will be profitable and meets requirements.

    Args:
        side: "buy" or "sell"
        price: Order price
        quantity: Order quantity
        opposing_price: Price of opposing order (sell price if buying, buy price if selling)
        total_fee_rate: Total fee rate
        fee_buffer_pct: Safety buffer
        min_notional_quote: Minimum notional value

    Returns:
        Tuple of (is_valid, reason)
        - is_valid: True if order is valid, False otherwise
        - reason: Human-readable reason if invalid, empty string if valid
    """
    # Check minimum notional
    if not meets_min_notional(price, quantity, min_notional_quote):
        notional = price * quantity
        return False, (
            f"Order below minimum notional: {notional} < {min_notional_quote}"
        )

    # Check profitability if we have opposing price
    if opposing_price is not None:
        if side.lower() == "buy":
            # We're buying, so opposing_price is where we'll sell
            if not is_profitable_grid_level(
                price, opposing_price, total_fee_rate, fee_buffer_pct
            ):
                min_sell = calculate_min_profitable_sell_price(
                    price, total_fee_rate, fee_buffer_pct
                )
                return False, (
                    f"Buy at {price} with sell at {opposing_price} would lose money after fees. "
                    f"Min profitable sell: {min_sell}"
                )
        else:  # sell
            # We're selling, so opposing_price is where we bought
            if not is_profitable_grid_level(
                opposing_price, price, total_fee_rate, fee_buffer_pct
            ):
                min_sell = calculate_min_profitable_sell_price(
                    opposing_price, total_fee_rate, fee_buffer_pct
                )
                return False, (
                    f"Sell at {price} after buying at {opposing_price} would lose money after fees. "
                    f"Min profitable sell: {min_sell}"
                )

    return True, ""
