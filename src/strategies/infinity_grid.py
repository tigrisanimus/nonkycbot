"""Infinity grid strategy helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable


@dataclass(frozen=True)
class GridLevel:
    side: str
    price: Decimal
    size: Decimal


def _to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def generate_symmetric_grid(
    mid_price: Decimal | int | str,
    *,
    levels: int,
    step_pct: Decimal | int | str,
    order_size: Decimal | int | str,
) -> list[GridLevel]:
    """Generate symmetric buy/sell levels around the mid price."""
    mid = _to_decimal(mid_price)
    step = _to_decimal(step_pct)
    size = _to_decimal(order_size)
    if levels <= 0:
        raise ValueError("levels must be positive")
    if step <= 0:
        raise ValueError("step_pct must be positive")
    if size <= 0:
        raise ValueError("order_size must be positive")

    grid: list[GridLevel] = []
    for level in range(1, levels + 1):
        offset = mid * step * Decimal(level)
        grid.append(GridLevel(side="buy", price=mid - offset, size=size))
        grid.append(GridLevel(side="sell", price=mid + offset, size=size))
    return grid


def should_refresh(
    *,
    last_refresh: datetime | int | None,
    now: datetime | int,
    interval_seconds: int,
) -> bool:
    """Determine whether the grid should refresh based on elapsed time."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")

    if last_refresh is None:
        return True

    def to_timestamp(value: datetime | int) -> int:
        if isinstance(value, datetime):
            return int(value.timestamp())
        return int(value)

    last_ts = to_timestamp(last_refresh)
    now_ts = to_timestamp(now)
    return now_ts - last_ts >= interval_seconds


def describe() -> str:
    return "Infinity grid strategy helpers."


def summarize_grid(levels: Iterable[GridLevel]) -> dict[str, Decimal]:
    """Summarize grid totals for deterministic inspection."""
    totals = {"buy": Decimal("0"), "sell": Decimal("0")}
    for level in levels:
        totals[level.side] += level.size
    return totals
