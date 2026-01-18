"""Helpers for checking minimum order notional."""

from decimal import ROUND_UP, Decimal


def _round_up_to_step(value, step):
    if step <= 0:
        return value
    multiplier = (value / step).to_integral_value(rounding=ROUND_UP)
    return multiplier * step


def _round_up_to_precision(value, precision):
    if precision is None:
        return value
    quantizer = Decimal("1").scaleb(-precision)
    return value.quantize(quantizer, rounding=ROUND_UP)


def resolve_quantity_rounding(config):
    """Resolve configured quantity rounding settings."""
    step_size = (
        config.get("quantity_step")
        or config.get("qty_step")
        or config.get("step_size")
        or config.get("quantity_step_size")
    )
    precision = config.get("quantity_precision") or config.get("qty_precision")
    if precision is not None:
        precision = int(precision)
    return step_size, precision


def min_quantity_from_notional(
    *,
    price,
    min_notional,
    fee_rate,
    step_size=None,
    precision=None,
):
    """Compute min quantity from notional, factoring in fees and rounding up."""
    price = Decimal(str(price))
    min_notional = Decimal(str(min_notional))
    fee_rate = Decimal(str(fee_rate))
    if price <= 0:
        return Decimal("0")
    denominator = price * (Decimal("1") - fee_rate)
    if denominator <= 0:
        return Decimal("0")
    min_qty = min_notional / denominator
    if step_size is not None:
        min_qty = _round_up_to_step(min_qty, Decimal(str(step_size)))
    else:
        min_qty = _round_up_to_precision(min_qty, precision)
    return min_qty


def should_skip_notional(config, symbol, side, quantity, price, order_type="limit"):
    """Return True if the order notional is below configured minimum."""
    min_notional = Decimal(str(config.get("min_notional_usd", "1.0")))
    notional = Decimal(str(quantity)) * Decimal(str(price))
    if notional < min_notional:
        print(
            "⚠️  Skipping order below min notional: "
            f"symbol={symbol} side={side} order_type={order_type} "
            f"price={price} quantity={quantity} notional={notional}"
        )
        return True
    return False
