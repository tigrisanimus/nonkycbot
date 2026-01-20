"""Tests for strategy helpers."""

from __future__ import annotations

from decimal import Decimal

from strategies import (
    grid,
    infinity_grid,
    rebalance,
    triangular_arb,
)


def test_infinity_grid_initialization() -> None:
    """Test infinity grid state initialization."""
    state = infinity_grid.initialize_infinity_grid(
        base_balance=Decimal("1.0"),
        quote_balance=Decimal("10000"),  # $10k USDT for buying dips
        current_price=Decimal("50000"),
        step_pct=Decimal("0.01"),
    )
    assert state.constant_value_quote == Decimal("50000")
    assert state.last_rebalance_price == Decimal("50000")
    assert state.step_pct == Decimal("0.01")
    assert state.allocated_quote == Decimal("10000")
    # Lower limit should be calculated automatically and be below entry
    assert state.lower_limit < Decimal("50000")
    assert state.total_profit_quote == Decimal("0")


def test_infinity_grid_sell_on_price_rise() -> None:
    """Test that infinity grid generates sell order when price rises."""
    state = infinity_grid.initialize_infinity_grid(
        base_balance=Decimal("1.0"),
        quote_balance=Decimal("10000"),
        current_price=Decimal("50000"),
        step_pct=Decimal("0.01"),
    )

    # Price rises by 1%
    order = infinity_grid.calculate_infinity_grid_order(
        base_balance=Decimal("1.0"),
        quote_balance=Decimal("10000"),
        current_price=Decimal("50500"),
        grid_state=state,
    )

    assert order is not None
    assert order.side == "sell"
    # Should sell ~0.0099 BTC to bring value back to 50000
    assert abs(order.amount - Decimal("0.009901")) < Decimal("0.0001")
    assert order.price == Decimal("50500")


def test_infinity_grid_buy_on_price_drop() -> None:
    """Test that infinity grid generates buy order when price drops."""
    state = infinity_grid.initialize_infinity_grid(
        base_balance=Decimal("1.0"),
        quote_balance=Decimal("10000"),
        current_price=Decimal("50000"),
        step_pct=Decimal("0.01"),
    )

    # Price drops by 1%
    order = infinity_grid.calculate_infinity_grid_order(
        base_balance=Decimal("1.0"),
        quote_balance=Decimal("10000"),
        current_price=Decimal("49500"),
        grid_state=state,
    )

    assert order is not None
    assert order.side == "buy"
    # Should buy ~0.0101 BTC to restore value to 50000
    assert abs(order.amount - Decimal("0.010101")) < Decimal("0.0001")
    assert order.price == Decimal("49500")


def test_infinity_grid_no_action_within_step() -> None:
    """Test that infinity grid doesn't trade if price hasn't moved enough."""
    state = infinity_grid.initialize_infinity_grid(
        base_balance=Decimal("1.0"),
        quote_balance=Decimal("10000"),
        current_price=Decimal("50000"),
        step_pct=Decimal("0.01"),
    )

    # Price only moved 0.5% (less than 1% step)
    order = infinity_grid.calculate_infinity_grid_order(
        base_balance=Decimal("1.0"),
        quote_balance=Decimal("10000"),
        current_price=Decimal("50250"),
        grid_state=state,
    )

    assert order is None


def test_infinity_grid_respects_lower_limit() -> None:
    """Test that infinity grid stops trading below lower limit."""
    state = infinity_grid.initialize_infinity_grid(
        base_balance=Decimal("1.0"),
        quote_balance=Decimal("5000"),  # Limited USDT means lower limit will be calculated
        current_price=Decimal("50000"),
        step_pct=Decimal("0.01"),
    )

    # Price well below calculated lower limit - grid should stop buying
    order = infinity_grid.calculate_infinity_grid_order(
        base_balance=Decimal("1.0"),
        quote_balance=Decimal("5000"),
        current_price=Decimal("30000"),  # Far below entry
        grid_state=state,
    )

    assert order is None


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
