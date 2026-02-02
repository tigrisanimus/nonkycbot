"""Hybrid triangular arbitrage strategy mixing order books and liquidity pools."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import NamedTuple


class LegType(Enum):
    """Type of trading leg in arbitrage cycle."""

    ORDERBOOK = "orderbook"  # Limit order on order book
    POOL_SWAP = "pool_swap"  # Swap in liquidity pool


class TradeSide(Enum):
    """Side of trade execution."""

    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class TradeLeg:
    """Single leg of a hybrid arbitrage cycle."""

    leg_type: LegType
    symbol: str  # Trading pair or pool symbol
    side: TradeSide
    input_currency: str
    output_currency: str
    input_amount: Decimal | None = None  # Set during execution planning
    output_amount: Decimal | None = None  # Set during execution planning
    price: Decimal | None = (
        None  # For orderbook: limit price, for pool: effective price
    )
    fee_rate: Decimal = Decimal("0")
    slippage_pct: Decimal = Decimal("0")  # Price impact for pools


class ArbitrageCycle(NamedTuple):
    """Complete arbitrage cycle with 3 legs."""

    leg1: TradeLeg
    leg2: TradeLeg
    leg3: TradeLeg
    start_currency: str
    start_amount: Decimal
    expected_return: Decimal
    net_profit: Decimal
    profit_pct: Decimal
    cycle_id: str


def describe() -> str:
    """Return strategy description for CLI help."""
    return (
        "Hybrid triangular arbitrage mixing order book trades and liquidity pool swaps. "
        "Identifies profitable cycles between order book pairs (e.g., COSA/BTC, PIRATE/USDT) "
        "and AMM pools (e.g., COSA/PIRATE swap pool). Handles different pricing mechanisms "
        "and fee structures."
    )


def create_orderbook_leg(
    symbol: str,
    side: TradeSide,
    price: Decimal,
    input_currency: str,
    output_currency: str,
    fee_rate: Decimal = Decimal("0.002"),  # 0.2% default
) -> TradeLeg:
    """Create an order book trading leg."""
    return TradeLeg(
        leg_type=LegType.ORDERBOOK,
        symbol=symbol,
        side=side,
        input_currency=input_currency,
        output_currency=output_currency,
        price=price,
        fee_rate=fee_rate,
    )


def create_pool_swap_leg(
    symbol: str,
    side: TradeSide,
    effective_price: Decimal,
    input_currency: str,
    output_currency: str,
    fee_rate: Decimal = Decimal("0.003"),  # 0.3% default for AMMs
    slippage_pct: Decimal = Decimal("0"),
) -> TradeLeg:
    """Create a liquidity pool swap leg."""
    return TradeLeg(
        leg_type=LegType.POOL_SWAP,
        symbol=symbol,
        side=side,
        input_currency=input_currency,
        output_currency=output_currency,
        price=effective_price,
        fee_rate=fee_rate,
        slippage_pct=slippage_pct,
    )


def calculate_leg_output(leg: TradeLeg, input_amount: Decimal) -> Decimal:
    """
    Calculate output amount for a single leg given input amount.

    For orderbook legs: output = input * price * (1 - fee_rate)
        - BUY legs use price as base-per-quote (token per base).
        - SELL legs use price as quote-per-base (base per token).
    For pool legs: output = input * effective_price * (1 - fee_rate) * (1 - slippage)

    Args:
        leg: Trading leg configuration
        input_amount: Amount of input currency

    Returns:
        Amount of output currency received
    """
    if input_amount <= 0:
        return Decimal("0")

    if leg.price is None or leg.price <= 0:
        return Decimal("0")

    # Apply price conversion
    if leg.side == TradeSide.BUY:
        # Buying: spend input to get output
        # Example: Buy COSA with USDT at price 2 COSA/USDT (token per base)
        output = input_amount * leg.price
    else:
        # Selling: sell input to get output
        # Example: Sell COSA for USDT at price 0.5 USDT/COSA
        # output = input * price
        output = input_amount * leg.price

    # Apply fee
    output = output * (Decimal("1") - leg.fee_rate)

    # Apply slippage for pool swaps
    if leg.leg_type == LegType.POOL_SWAP:
        output = output * (Decimal("1") - leg.slippage_pct / Decimal("100"))

    return output


def evaluate_cycle(
    leg1: TradeLeg,
    leg2: TradeLeg,
    leg3: TradeLeg,
    start_amount: Decimal,
) -> ArbitrageCycle:
    """
    Evaluate profitability of a complete arbitrage cycle.

    Args:
        leg1: First trading leg
        leg2: Second trading leg
        leg3: Third trading leg
        start_amount: Starting capital amount

    Returns:
        ArbitrageCycle with all details including profit calculations
    """
    # Validate cycle connects properly
    if leg1.output_currency != leg2.input_currency:
        raise ValueError(
            f"Cycle broken: leg1 output ({leg1.output_currency}) "
            f"!= leg2 input ({leg2.input_currency})"
        )
    if leg2.output_currency != leg3.input_currency:
        raise ValueError(
            f"Cycle broken: leg2 output ({leg2.output_currency}) "
            f"!= leg3 input ({leg3.input_currency})"
        )
    if leg3.output_currency != leg1.input_currency:
        raise ValueError(
            f"Cycle broken: leg3 output ({leg3.output_currency}) "
            f"!= leg1 input ({leg1.input_currency})"
        )

    # Calculate amounts through the cycle
    amount_after_leg1 = calculate_leg_output(leg1, start_amount)
    amount_after_leg2 = calculate_leg_output(leg2, amount_after_leg1)
    final_amount = calculate_leg_output(leg3, amount_after_leg2)

    # Calculate profit
    net_profit = final_amount - start_amount
    profit_pct = (
        (net_profit / start_amount * Decimal("100"))
        if start_amount > 0
        else Decimal("0")
    )

    # Generate cycle ID
    cycle_id = f"{leg1.symbol}>{leg2.symbol}>{leg3.symbol}"

    # Create legs with populated amounts
    leg1_with_amounts = TradeLeg(
        leg_type=leg1.leg_type,
        symbol=leg1.symbol,
        side=leg1.side,
        input_currency=leg1.input_currency,
        output_currency=leg1.output_currency,
        input_amount=start_amount,
        output_amount=amount_after_leg1,
        price=leg1.price,
        fee_rate=leg1.fee_rate,
        slippage_pct=leg1.slippage_pct,
    )

    leg2_with_amounts = TradeLeg(
        leg_type=leg2.leg_type,
        symbol=leg2.symbol,
        side=leg2.side,
        input_currency=leg2.input_currency,
        output_currency=leg2.output_currency,
        input_amount=amount_after_leg1,
        output_amount=amount_after_leg2,
        price=leg2.price,
        fee_rate=leg2.fee_rate,
        slippage_pct=leg2.slippage_pct,
    )

    leg3_with_amounts = TradeLeg(
        leg_type=leg3.leg_type,
        symbol=leg3.symbol,
        side=leg3.side,
        input_currency=leg3.input_currency,
        output_currency=leg3.output_currency,
        input_amount=amount_after_leg2,
        output_amount=final_amount,
        price=leg3.price,
        fee_rate=leg3.fee_rate,
        slippage_pct=leg3.slippage_pct,
    )

    return ArbitrageCycle(
        leg1=leg1_with_amounts,
        leg2=leg2_with_amounts,
        leg3=leg3_with_amounts,
        start_currency=leg1.input_currency,
        start_amount=start_amount,
        expected_return=final_amount,
        net_profit=net_profit,
        profit_pct=profit_pct,
        cycle_id=cycle_id,
    )


def find_best_cycle(cycles: list[ArbitrageCycle]) -> ArbitrageCycle | None:
    """
    Find the most profitable cycle from a list.

    Args:
        cycles: List of evaluated arbitrage cycles

    Returns:
        Most profitable cycle, or None if list is empty
    """
    if not cycles:
        return None

    return max(cycles, key=lambda c: c.net_profit)


def is_cycle_profitable(
    cycle: ArbitrageCycle, min_profit_threshold: Decimal = Decimal("0.5")
) -> bool:
    """
    Check if a cycle meets minimum profitability threshold.

    Args:
        cycle: Arbitrage cycle to check
        min_profit_threshold: Minimum profit percentage required (default 0.5%)

    Returns:
        True if cycle is profitable above threshold
    """
    return cycle.profit_pct >= min_profit_threshold


def format_cycle_summary(cycle: ArbitrageCycle) -> str:
    """
    Format cycle information for logging/display.

    Args:
        cycle: Arbitrage cycle to format

    Returns:
        Human-readable string describing the cycle
    """
    lines = [
        f"Cycle: {cycle.cycle_id}",
        f"Start: {cycle.start_amount:.4f} {cycle.start_currency}",
        "",
        f"Leg 1 ({cycle.leg1.leg_type.value}): {cycle.leg1.symbol}",
        f"  {cycle.leg1.side.value.upper()} {cycle.leg1.input_amount:.4f} {cycle.leg1.input_currency}",
        f"  → {cycle.leg1.output_amount:.4f} {cycle.leg1.output_currency}",
        f"  Price: {cycle.leg1.price:.8f}, Fee: {cycle.leg1.fee_rate*100:.2f}%",
        "",
        f"Leg 2 ({cycle.leg2.leg_type.value}): {cycle.leg2.symbol}",
        f"  {cycle.leg2.side.value.upper()} {cycle.leg2.input_amount:.4f} {cycle.leg2.input_currency}",
        f"  → {cycle.leg2.output_amount:.4f} {cycle.leg2.output_currency}",
        f"  Price: {cycle.leg2.price:.8f}, Fee: {cycle.leg2.fee_rate*100:.2f}%",
    ]

    if cycle.leg2.leg_type == LegType.POOL_SWAP:
        lines.append(f"  Slippage: {cycle.leg2.slippage_pct:.2f}%")

    lines.extend(
        [
            "",
            f"Leg 3 ({cycle.leg3.leg_type.value}): {cycle.leg3.symbol}",
            f"  {cycle.leg3.side.value.upper()} {cycle.leg3.input_amount:.4f} {cycle.leg3.input_currency}",
            f"  → {cycle.leg3.output_amount:.4f} {cycle.leg3.output_currency}",
            f"  Price: {cycle.leg3.price:.8f}, Fee: {cycle.leg3.fee_rate*100:.2f}%",
            "",
            f"Return: {cycle.expected_return:.4f} {cycle.start_currency}",
            f"Profit: {cycle.net_profit:.4f} {cycle.start_currency} ({cycle.profit_pct:.3f}%)",
        ]
    )

    return "\n".join(lines)
