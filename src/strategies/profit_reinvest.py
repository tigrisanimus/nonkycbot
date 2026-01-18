"""Profit reinvest strategy helpers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ProfitAllocation:
    reserve_amount: Decimal
    reinvest_amount: Decimal
    remaining_profit: Decimal


def _to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def allocate_profit(
    *,
    balance: Decimal | int | str,
    principal: Decimal | int | str,
    reserve_ratio: Decimal | int | str,
    reinvest_ratio: Decimal | int | str | None = None,
) -> ProfitAllocation:
    """Allocate profit into reserve and optional reinvest buckets."""
    total_balance = _to_decimal(balance)
    principal_value = _to_decimal(principal)
    reserve = _to_decimal(reserve_ratio)
    reinvest = _to_decimal(reinvest_ratio) if reinvest_ratio is not None else None

    if reserve < 0 or reserve > 1:
        raise ValueError("reserve_ratio must be between 0 and 1")
    if reinvest is not None and (reinvest < 0 or reinvest > 1):
        raise ValueError("reinvest_ratio must be between 0 and 1")

    profit = total_balance - principal_value
    if profit <= 0:
        return ProfitAllocation(
            reserve_amount=Decimal("0"),
            reinvest_amount=Decimal("0"),
            remaining_profit=Decimal("0"),
        )

    reserve_amount = profit * reserve
    remaining = profit - reserve_amount
    reinvest_amount = remaining * reinvest if reinvest is not None else Decimal("0")
    remaining_profit = remaining - reinvest_amount
    return ProfitAllocation(
        reserve_amount=reserve_amount,
        reinvest_amount=reinvest_amount,
        remaining_profit=remaining_profit,
    )


def describe() -> str:
    return "Profit reinvest strategy helpers."
