"""Tests for strategy helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from strategies import (
    infinity_grid,
    profit_reinvest,
    rebalance,
    standard_grid,
    triangular_arb,
)


def test_infinity_grid_generation_and_refresh() -> None:
    grid = infinity_grid.generate_symmetric_grid(
        mid_price=Decimal("100"),
        levels=2,
        step_pct=Decimal("0.01"),
        order_size=Decimal("1.5"),
    )
    assert [level.price for level in grid] == [
        Decimal("99.00"),
        Decimal("101.00"),
        Decimal("98.00"),
        Decimal("102.00"),
    ]
    totals = infinity_grid.summarize_grid(grid)
    assert totals["buy"] == Decimal("3.0")
    assert totals["sell"] == Decimal("3.0")

    now = datetime(2024, 1, 1)
    assert infinity_grid.should_refresh(last_refresh=None, now=now, interval_seconds=60)
    assert not infinity_grid.should_refresh(
        last_refresh=now,
        now=now + timedelta(seconds=30),
        interval_seconds=60,
    )


def test_infinity_grid_requires_positive_inputs() -> None:
    with pytest.raises(ValueError):
        infinity_grid.generate_symmetric_grid(
            mid_price=100, levels=0, step_pct=0.1, order_size=1
        )

    with pytest.raises(ValueError):
        infinity_grid.should_refresh(last_refresh=None, now=0, interval_seconds=0)


def test_rebalance_order_when_drift_exceeds_threshold() -> None:
    order = rebalance.calculate_rebalance_order(
        base_balance=Decimal("1"),
        quote_balance=Decimal("150"),
        mid_price=Decimal("100"),
        target_base_ratio=Decimal("0.6"),
        drift_threshold=Decimal("0.05"),
    )
    assert order is not None
    assert order.side == "buy"
    assert order.amount == Decimal("0.5")


def test_rebalance_no_order_within_threshold() -> None:
    order = rebalance.calculate_rebalance_order(
        base_balance=Decimal("1"),
        quote_balance=Decimal("100"),
        mid_price=Decimal("100"),
        target_base_ratio=Decimal("0.5"),
        drift_threshold=Decimal("0.2"),
    )
    assert order is None


def test_triangular_arb_cycle_profitability() -> None:
    rates = {
        "A/B": Decimal("2"),
        "B/C": Decimal("3"),
        "C/A": Decimal("0.2"),
    }
    plan = triangular_arb.find_profitable_cycle(
        cycles=[("A/B", "B/C", "C/A")],
        rates=rates,
        start_amount=Decimal("1"),
        fee_rate=Decimal("0"),
        profit_threshold=Decimal("0.1"),
    )
    assert plan is not None
    assert plan.profit_ratio == Decimal("0.2")
    assert plan.final_amount == Decimal("1.2")


def test_triangular_arb_rejects_unprofitable_cycle_with_fees() -> None:
    rates = {"A/B": Decimal("1"), "B/C": Decimal("1"), "C/A": Decimal("1")}
    plan = triangular_arb.find_profitable_cycle(
        cycles=[("A/B", "B/C", "C/A")],
        rates=rates,
        start_amount=Decimal("1"),
        fee_rate=Decimal("0.01"),
        profit_threshold=Decimal("0"),
    )
    assert plan is None


def test_profit_reinvest_allocation() -> None:
    allocation = profit_reinvest.allocate_profit(
        balance=Decimal("130"),
        principal=Decimal("100"),
        reserve_ratio=Decimal("0.5"),
        reinvest_ratio=Decimal("0.5"),
    )
    assert allocation.reserve_amount == Decimal("15")
    assert allocation.reinvest_amount == Decimal("7.5")
    assert allocation.remaining_profit == Decimal("7.5")


def test_profit_reinvest_returns_zero_without_profit() -> None:
    allocation = profit_reinvest.allocate_profit(
        balance=Decimal("99"),
        principal=Decimal("100"),
        reserve_ratio=Decimal("0.2"),
    )
    assert allocation.reserve_amount == Decimal("0")
    assert allocation.reinvest_amount == Decimal("0")
    assert allocation.remaining_profit == Decimal("0")


def test_standard_grid_description() -> None:
    assert standard_grid.describe() == "Standard grid strategy scaffold."
