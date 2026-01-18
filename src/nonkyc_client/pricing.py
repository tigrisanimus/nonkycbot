"""Pricing and notional helpers."""

from decimal import ROUND_UP, Decimal


def min_quantity_for_notional(
    price: Decimal, min_notional: Decimal, fee_rate: Decimal
) -> Decimal:
    """Return minimum quantity needed to meet a notional after fees."""
    price = Decimal(str(price))
    min_notional = Decimal(str(min_notional))
    fee_rate = Decimal(str(fee_rate))
    if price <= 0:
        return Decimal("0")
    denominator = price * (Decimal("1") - fee_rate)
    if denominator <= 0:
        return Decimal("0")
    quantity = min_notional / denominator
    if effective_notional(quantity, price, fee_rate) < min_notional:
        quantity = quantity.next_plus()
    return quantity


def effective_notional(quantity: Decimal, price: Decimal, fee_rate: Decimal) -> Decimal:
    """Return notional after fees for the given quantity and price."""
    quantity = Decimal(str(quantity))
    price = Decimal(str(price))
    fee_rate = Decimal(str(fee_rate))
    return quantity * price * (Decimal("1") - fee_rate)


def round_up_to_step(quantity: Decimal, step: Decimal) -> Decimal:
    """Round quantity up to the nearest step."""
    quantity = Decimal(str(quantity))
    step = Decimal(str(step))
    if step <= 0:
        return quantity
    multiplier = (quantity / step).to_integral_value(rounding=ROUND_UP)
    return multiplier * step


def should_skip_fee_edge(
    side: str, price: Decimal, mid_price: Decimal, fee_rate: Decimal
) -> bool:
    """Return True when a grid level does not clear fees for a round trip."""
    price = Decimal(str(price))
    mid_price = Decimal(str(mid_price))
    fee_rate = Decimal(str(fee_rate))
    fee_cost = Decimal("2") * fee_rate
    offset = abs(price - mid_price)
    if offset == 0:
        print("⚠️  Skipping order with zero price offset from mid.")
        return True
    if side == "buy":
        buy_price = price
        sell_price = mid_price + offset
    else:
        sell_price = price
        buy_price = mid_price - offset
    if buy_price <= 0 or sell_price <= 0:
        print(
            "⚠️  Skipping order with invalid pricing for fee edge check: "
            f"side={side} buy_price={buy_price} sell_price={sell_price}"
        )
        return True
    gross_edge = (sell_price - buy_price) / buy_price
    if gross_edge <= fee_cost:
        print(
            "⚠️  Skipping order due to insufficient edge after fees: "
            f"side={side} buy_price={buy_price} sell_price={sell_price} "
            f"gross_edge={gross_edge} fee_cost={fee_cost}"
        )
        return True
    return False
