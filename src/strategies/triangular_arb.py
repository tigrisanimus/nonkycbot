"""Triangular arbitrage strategy helpers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


@dataclass(frozen=True)
class CycleOrder:
    pair: str
    side: str
    amount: Decimal
    rate: Decimal


@dataclass(frozen=True)
class CyclePlan:
    cycle: tuple[str, str, str]
    orders: tuple[CycleOrder, CycleOrder, CycleOrder]
    profit_ratio: Decimal
    final_amount: Decimal


def _to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _apply_fee(amount: Decimal, fee_rate: Decimal) -> Decimal:
    if fee_rate < 0:
        raise ValueError("fee_rate must be non-negative")
    return amount * (Decimal("1") - fee_rate)


def evaluate_cycle(
    *,
    start_amount: Decimal | int | str,
    rates: dict[str, Decimal | int | str],
    cycle: tuple[str, str, str],
    fee_rate: Decimal | int | str = Decimal("0"),
) -> Decimal:
    """Evaluate the final amount after executing a triangular cycle."""
    amount = _to_decimal(start_amount)
    fee = _to_decimal(fee_rate)
    if amount <= 0:
        raise ValueError("start_amount must be positive")

    first, second, third = cycle
    for pair in (first, second, third):
        rate = _to_decimal(rates[pair])
        if rate <= 0:
            raise ValueError("rates must be positive")
        amount = _apply_fee(amount * rate, fee)
    return amount


def find_profitable_cycle(
    *,
    cycles: Iterable[tuple[str, str, str]],
    rates: dict[str, Decimal | int | str],
    start_amount: Decimal | int | str,
    fee_rate: Decimal | int | str,
    profit_threshold: Decimal | int | str,
) -> CyclePlan | None:
    """Find a profitable cycle and return the order sequence."""
    threshold = _to_decimal(profit_threshold)
    if threshold < 0:
        raise ValueError("profit_threshold must be non-negative")

    best_plan: CyclePlan | None = None
    start = _to_decimal(start_amount)
    fee = _to_decimal(fee_rate)

    for cycle in cycles:
        final_amount = evaluate_cycle(
            start_amount=start,
            rates=rates,
            cycle=cycle,
            fee_rate=fee,
        )
        profit_ratio = (final_amount - start) / start
        if profit_ratio < threshold:
            continue

        orders = []
        amount = start
        for pair in cycle:
            rate = _to_decimal(rates[pair])
            orders.append(CycleOrder(pair=pair, side="sell", amount=amount, rate=rate))
            amount = _apply_fee(amount * rate, fee)
        plan = CyclePlan(
            cycle=cycle,
            orders=tuple(orders),  # type: ignore[arg-type]
            profit_ratio=profit_ratio,
            final_amount=amount,
        )
        if best_plan is None or plan.profit_ratio > best_plan.profit_ratio:
            best_plan = plan

    return best_plan


def describe() -> str:
    return "Triangular arbitrage strategy helpers."
