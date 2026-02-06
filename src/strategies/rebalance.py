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


@dataclass(frozen=True)
class MultiAssetRebalanceOrder:
    asset: str
    side: str
    amount: Decimal
    price: Decimal
    target_ratio: Decimal
    current_ratio: Decimal


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


def calculate_multi_asset_rebalance(
    *,
    balances: dict[str, Decimal | int | str],
    prices: dict[str, Decimal | int | str],
    target_ratios: dict[str, Decimal | int | str],
    quote_asset: str,
    drift_threshold: Decimal | int | str,
) -> MultiAssetRebalanceOrder | None:
    """Calculate a rebalance order across multiple assets using a quote asset."""
    if quote_asset not in target_ratios:
        raise ValueError("quote_asset must be included in target_ratios")

    threshold = _to_decimal(drift_threshold)
    if threshold < 0:
        raise ValueError("drift_threshold must be non-negative")

    normalized_prices = {asset: _to_decimal(price) for asset, price in prices.items()}
    for asset, price in normalized_prices.items():
        if price <= 0:
            raise ValueError(f"price must be positive for {asset}")

    normalized_targets = {
        asset: _to_decimal(ratio) for asset, ratio in target_ratios.items()
    }
    normalized_balances = {
        asset: _to_decimal(balance) for asset, balance in balances.items()
    }

    total_value = Decimal("0")
    for asset, ratio in normalized_targets.items():
        asset_price = normalized_prices.get(asset)
        if asset_price is None:
            raise ValueError(f"Missing price for asset: {asset}")
        total_value += normalized_balances.get(asset, Decimal("0")) * asset_price

    if total_value <= 0:
        return None

    drifts: dict[str, Decimal] = {}
    current_ratios: dict[str, Decimal] = {}
    for asset, target_ratio in normalized_targets.items():
        price = normalized_prices[asset]
        current_value = normalized_balances.get(asset, Decimal("0")) * price
        current_ratio = current_value / total_value
        current_ratios[asset] = current_ratio
        drifts[asset] = current_ratio - target_ratio

    candidate_assets = [
        asset
        for asset, drift in drifts.items()
        if asset != quote_asset and abs(drift) > threshold
    ]
    if not candidate_assets:
        return None

    asset = max(candidate_assets, key=lambda item: abs(drifts[item]))
    target_ratio = normalized_targets[asset]
    current_ratio = current_ratios[asset]
    price = normalized_prices[asset]
    current_value = normalized_balances.get(asset, Decimal("0")) * price
    target_value = total_value * target_ratio
    delta_value = target_value - current_value
    side = "buy" if delta_value > 0 else "sell"
    amount = abs(delta_value) / price
    if amount <= 0:
        return None

    return MultiAssetRebalanceOrder(
        asset=asset,
        side=side,
        amount=amount,
        price=price,
        target_ratio=target_ratio,
        current_ratio=current_ratio,
    )


def describe() -> str:
    return "Rebalance strategy helpers."
