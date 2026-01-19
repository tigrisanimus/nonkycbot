"""Balance checking utilities for order placement."""

from __future__ import annotations

from decimal import Decimal

from nonkyc_client.models import Balance, OrderRequest


class InsufficientBalanceError(Exception):
    """Raised when there is insufficient balance for an order."""

    def __init__(
        self,
        message: str,
        asset: str,
        required: Decimal,
        available: Decimal,
    ) -> None:
        super().__init__(message)
        self.asset = asset
        self.required = required
        self.available = available


def parse_symbol(symbol: str) -> tuple[str, str]:
    """
    Parse a trading symbol into base and quote assets.

    Examples:
        BTC/USDT -> ("BTC", "USDT")
        ETH-USD -> ("ETH", "USD")

    Args:
        symbol: Trading symbol (e.g., "BTC/USDT" or "BTC-USDT")

    Returns:
        Tuple of (base_asset, quote_asset)

    Raises:
        ValueError: If symbol format is invalid
    """
    for separator in ["/", "-"]:
        if separator in symbol:
            parts = symbol.split(separator)
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip()

    raise ValueError(
        f"Invalid symbol format: {symbol}. Expected format like BTC/USDT or BTC-USDT"
    )


def get_balance_for_asset(balances: list[Balance], asset: str) -> Decimal:
    """
    Get available balance for a specific asset.

    Args:
        balances: List of Balance objects
        asset: Asset symbol (e.g., "BTC", "USDT")

    Returns:
        Available balance as Decimal (0 if asset not found)
    """
    for balance in balances:
        if balance.asset.upper() == asset.upper():
            return Decimal(str(balance.available))
    return Decimal("0")


def calculate_required_balance(
    order: OrderRequest, fee_rate: Decimal = Decimal("0")
) -> tuple[str, Decimal]:
    """
    Calculate required balance for an order.

    Args:
        order: Order request
        fee_rate: Trading fee rate (e.g., 0.002 for 0.2%)

    Returns:
        Tuple of (asset, required_amount)

    For buy orders: Requires quote asset (price * amount * (1 + fee_rate))
    For sell orders: Requires base asset (amount * (1 + fee_rate))
    """
    base_asset, quote_asset = parse_symbol(order.symbol)
    amount = Decimal(str(order.amount))
    price = Decimal(str(order.price))

    if order.side.lower() == "buy":
        # For buy orders, need quote asset
        required = price * amount * (Decimal("1") + fee_rate)
        return quote_asset, required
    else:
        # For sell orders, need base asset
        # Add fee buffer for conservative check
        required = amount * (Decimal("1") + fee_rate)
        return base_asset, required


def check_sufficient_balance(
    order: OrderRequest,
    balances: list[Balance],
    fee_rate: Decimal = Decimal("0"),
    *,
    safety_margin: Decimal = Decimal("0.01"),  # 1% safety margin
) -> None:
    """
    Check if there is sufficient balance for an order.

    Args:
        order: Order request to validate
        balances: List of current balances
        fee_rate: Trading fee rate (e.g., 0.002 for 0.2%)
        safety_margin: Additional safety margin as decimal (default 1%)

    Raises:
        InsufficientBalanceError: If balance is insufficient
        ValueError: If order or balance data is invalid
    """
    if not order.symbol:
        raise ValueError("Order symbol is required")
    if not order.amount or Decimal(str(order.amount)) <= 0:
        raise ValueError("Order amount must be positive")
    if not order.price or Decimal(str(order.price)) <= 0:
        raise ValueError("Order price must be positive")
    if not order.side or order.side.lower() not in {"buy", "sell"}:
        raise ValueError("Order side must be 'buy' or 'sell'")

    asset, required = calculate_required_balance(order, fee_rate)

    # Apply safety margin
    required_with_margin = required * (Decimal("1") + safety_margin)

    available = get_balance_for_asset(balances, asset)

    if available < required_with_margin:
        raise InsufficientBalanceError(
            f"Insufficient {asset} balance. Required: {required_with_margin:.8f} "
            f"(including {float(safety_margin * 100):.1f}% safety margin), "
            f"Available: {available:.8f}",
            asset=asset,
            required=required_with_margin,
            available=available,
        )


def check_sufficient_balances_for_orders(
    orders: list[OrderRequest],
    balances: list[Balance],
    fee_rate: Decimal = Decimal("0"),
    *,
    safety_margin: Decimal = Decimal("0.01"),
) -> None:
    """
    Check if there are sufficient balances for multiple orders.

    This function aggregates requirements across multiple orders and checks
    if total requirements can be met.

    Args:
        orders: List of order requests to validate
        balances: List of current balances
        fee_rate: Trading fee rate (e.g., 0.002 for 0.2%)
        safety_margin: Additional safety margin as decimal (default 1%)

    Raises:
        InsufficientBalanceError: If balance is insufficient for any asset
        ValueError: If order or balance data is invalid
    """
    # Aggregate required balances by asset
    required_by_asset: dict[str, Decimal] = {}

    for order in orders:
        asset, required = calculate_required_balance(order, fee_rate)
        required_by_asset[asset] = required_by_asset.get(asset, Decimal("0")) + required

    # Check each asset
    for asset, required in required_by_asset.items():
        required_with_margin = required * (Decimal("1") + safety_margin)
        available = get_balance_for_asset(balances, asset)

        if available < required_with_margin:
            raise InsufficientBalanceError(
                f"Insufficient {asset} balance for {len(orders)} orders. "
                f"Required: {required_with_margin:.8f} "
                f"(including {float(safety_margin * 100):.1f}% safety margin), "
                f"Available: {available:.8f}",
                asset=asset,
                required=required_with_margin,
                available=available,
            )


def get_max_order_size(
    symbol: str,
    side: str,
    price: Decimal | str,
    balances: list[Balance],
    fee_rate: Decimal = Decimal("0"),
    *,
    safety_margin: Decimal = Decimal("0.01"),
) -> Decimal:
    """
    Calculate maximum order size based on available balance.

    Args:
        symbol: Trading symbol (e.g., "BTC/USDT")
        side: Order side ("buy" or "sell")
        price: Order price
        balances: List of current balances
        fee_rate: Trading fee rate (e.g., 0.002 for 0.2%)
        safety_margin: Additional safety margin as decimal (default 1%)

    Returns:
        Maximum order amount in base asset

    Raises:
        ValueError: If inputs are invalid
    """
    if side.lower() not in {"buy", "sell"}:
        raise ValueError("Side must be 'buy' or 'sell'")

    price_decimal = Decimal(str(price))
    if price_decimal <= 0:
        raise ValueError("Price must be positive")

    base_asset, quote_asset = parse_symbol(symbol)

    if side.lower() == "buy":
        # For buy orders, limited by quote asset
        available = get_balance_for_asset(balances, quote_asset)
        # account for fees and safety margin
        usable = available / (Decimal("1") + safety_margin)
        max_notional = usable / (Decimal("1") + fee_rate)
        max_amount = max_notional / price_decimal
    else:
        # For sell orders, limited by base asset
        available = get_balance_for_asset(balances, base_asset)
        # account for fees and safety margin
        usable = available / (Decimal("1") + safety_margin)
        max_amount = usable / (Decimal("1") + fee_rate)

    return max(Decimal("0"), max_amount)
