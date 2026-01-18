from decimal import Decimal

from nonkyc_client.pricing import (
    effective_notional,
    min_quantity_for_notional,
    should_skip_fee_edge,
)


def test_min_quantity_for_notional_meets_min_after_fees():
    price = Decimal("10")
    min_notional = Decimal("1")
    fee_rate = Decimal("0.01")

    min_qty = min_quantity_for_notional(price, min_notional, fee_rate)

    assert effective_notional(min_qty, price, fee_rate) >= min_notional


def test_effective_notional_reflects_fee_discount():
    quantity = Decimal("2")
    price = Decimal("5")
    fee_rate = Decimal("0.10")

    assert effective_notional(quantity, price, fee_rate) == Decimal("9")


def test_fee_edge_check_rejects_unprofitable_level():
    fee_rate = Decimal("0.01")
    mid_price = Decimal("100")
    price = Decimal("99.5")

    assert should_skip_fee_edge("buy", price, mid_price, fee_rate) is True
