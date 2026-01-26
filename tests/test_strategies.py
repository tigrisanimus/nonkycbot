"""Tests for strategy helpers."""

from __future__ import annotations

from decimal import Decimal

from strategies import grid, rebalance, triangular_arb


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


def test_grid_description() -> None:
    assert "grid" in grid.describe().lower() or "Grid" in grid.describe()
