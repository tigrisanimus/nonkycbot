"""Rebalance strategy helpers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RebalanceOrder:
    side: str
    amount: Decimal
    price: Decimal
    target_ratio: Decimal


def _to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def calculate_rebalance_order(
    *,
    base_balance: Decimal | int | str,
    quote_balance: Decimal | int | str,
    mid_price: Decimal | int | str,
    target_base_ratio: Decimal | int | str,
    drift_threshold: Decimal | int | str,
) -> RebalanceOrder | None:
    """Calculate a rebalance order when the drift exceeds the threshold."""
    base = _to_decimal(base_balance)
    quote = _to_decimal(quote_balance)
    price = _to_decimal(mid_price)
    target_ratio = _to_decimal(target_base_ratio)
    threshold = _to_decimal(drift_threshold)

    if price <= 0:
        raise ValueError("mid_price must be positive")
    if not (Decimal("0") < target_ratio < Decimal("1")):
        raise ValueError("target_base_ratio must be between 0 and 1")
    if threshold < 0:
        raise ValueError("drift_threshold must be non-negative")

    base_value = base * price
    total_value = base_value + quote
    if total_value <= 0:
        return None

    current_ratio = base_value / total_value
    drift = current_ratio - target_ratio
    if abs(drift) <= threshold:
        return None

    target_base_value = total_value * target_ratio
    delta_base = (target_base_value - base_value) / price
    side = "buy" if delta_base > 0 else "sell"
    amount = abs(delta_base)
    if amount <= 0:
        return None
    return RebalanceOrder(
        side=side, amount=amount, price=price, target_ratio=target_ratio
    )


def describe() -> str:
    return "Rebalance strategy helpers."
