#!/usr/bin/env python3
"""
USDT/ETH/BTC Triangular Arbitrage Bot - Order book only (no liquidity pools)

Monitors order books to find profitable arbitrage opportunities using market orders.

Usage:
    # Monitor mode (no execution, just logging)
    python run_arb_bot.py config.yml --monitor-only

    # Live trading mode
    python run_arb_bot.py config.yml

    # Dry run mode (simulated execution)
    python run_arb_bot.py config.yml --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from datetime import datetime
from decimal import ROUND_UP, Decimal
from pathlib import Path
from typing import Any

import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from nonkyc_client.auth import AuthSigner
from nonkyc_client.models import OrderRequest
from nonkyc_client.pricing import (
    effective_notional,
    min_quantity_for_notional,
    round_up_to_step,
)
from nonkyc_client.rest import RestClient
from utils.credentials import DEFAULT_SERVICE_NAME, load_api_credentials
from utils.logging_config import setup_logging
from utils.notional import resolve_quantity_rounding

logger = logging.getLogger(__name__)

REQUIRED_FEE_RATE = Decimal("0.002")


def load_config(config_file):
    """Load configuration from YAML file."""
    with open(config_file, "r") as f:
        return yaml.safe_load(f)


def _round_quantity(value, step_size, precision):
    if step_size is not None:
        return round_up_to_step(value, Decimal(str(step_size)))
    if precision is None:
        return value
    quantizer = Decimal("1").scaleb(-precision)
    return value.quantize(quantizer, rounding=ROUND_UP)


def _min_quantities_for_cycle(config, prices, step_size, precision):
    min_notional = Decimal(str(config.get("min_notional_usd", "1.0")))
    fee_rate = _resolve_fee_rate(config)
    min_quantities = {}
    for pair in (config["pair_ab"], config["pair_bc"], config["pair_ac"]):
        min_qty = min_quantity_for_notional(
            price=prices[pair],
            min_notional=min_notional,
            fee_rate=fee_rate,
        )
        min_quantities[pair] = _round_quantity(min_qty, step_size, precision)
    return min_quantities


def _simulate_fee_adjusted_cycle(config, prices, start_amount, min_quantities):
    fee_rate = _resolve_fee_rate(config)
    pair_ab = config["pair_ab"]
    pair_bc = config["pair_bc"]
    pair_ac = config["pair_ac"]

    min_eth = max(min_quantities[pair_ab], min_quantities[pair_bc])
    min_start_usdt = min_eth * prices[pair_ab]
    adjusted_start = max(start_amount, min_start_usdt)

    eth_amount = adjusted_start / prices[pair_ab]
    eth_amount = max(eth_amount, min_eth)
    eth_amount = eth_amount * (Decimal("1") - fee_rate)

    btc_amount = eth_amount * prices[pair_bc]
    btc_amount = max(btc_amount, min_quantities[pair_ac])
    btc_amount = btc_amount * (Decimal("1") - fee_rate)

    final_usdt = btc_amount * prices[pair_ac]
    final_usdt = final_usdt * (Decimal("1") - fee_rate)

    profit = final_usdt - adjusted_start
    profit_ratio = profit / adjusted_start
    return adjusted_start, final_usdt, profit_ratio


def _should_skip_notional(config, symbol, side, quantity, price, order_type):
    min_notional = Decimal(str(config.get("min_notional_usd", "1.0")))
    fee_rate = _resolve_fee_rate(config)
    notional = effective_notional(quantity, price, fee_rate)
    if notional < min_notional:
        print(
            "⚠️  Skipping order below min notional: "
            f"symbol={symbol} side={side} order_type={order_type} "
            f"price={price} quantity={quantity} notional={notional}"
        )
        return True
    return False


def _resolve_signing_enabled(config):
    if "enable_signing" in config:
        return config["enable_signing"]
    if "use_signing" in config:
        return config["use_signing"]
    if "sign_requests" in config:
        return config["sign_requests"]
    return True


def _resolve_fee_rate(config):
    configured = config.get("fee_rate")
    if configured is None:
        config["fee_rate"] = str(REQUIRED_FEE_RATE)
        return REQUIRED_FEE_RATE
    parsed = Decimal(str(configured))
    if parsed != REQUIRED_FEE_RATE:
        print(
            "⚠️  Fee rate mismatch detected. "
            f"Configured fee_rate={parsed} but exchange fee is {REQUIRED_FEE_RATE}. "
            "Using the exchange fee."
        )
        config["fee_rate"] = str(REQUIRED_FEE_RATE)
        return REQUIRED_FEE_RATE
    return parsed


def build_rest_client(config):
    """Create a REST client with optional signer configuration overrides."""
    signing_enabled = _resolve_signing_enabled(config)
    creds = (
        load_api_credentials(DEFAULT_SERVICE_NAME, config) if signing_enabled else None
    )
    sign_absolute_url = config.get("sign_absolute_url")
    signer = (
        AuthSigner(
            nonce_multiplier=config.get("nonce_multiplier", 1e3),
            sort_params=config.get("sort_params", False),
            sort_body=config.get("sort_body", False),
        )
        if signing_enabled
        else None
    )
    return RestClient(
        base_url="https://api.nonkyc.io/api/v2",
        credentials=creds,
        signer=signer,
        use_server_time=config.get("use_server_time"),
        sign_absolute_url=sign_absolute_url,
    )


_NUMERIC_RE = re.compile(r"^[+-]?\d+(\.\d+)?([eE][+-]?\d+)?$")


def _coerce_price_value(value):
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
    else:
        candidate = str(value).strip()
    if not candidate:
        return None
    if not _NUMERIC_RE.match(candidate):
        return None
    return Decimal(candidate)


def _fallback_price_from_ticker(ticker):
    payload = getattr(ticker, "raw_payload", None) or {}
    for key in ("last", "price", "lastPrice"):
        candidate = payload.get(key)
        price = _coerce_price_value(candidate)
        if price is not None:
            return price, f"raw_payload.{key}"
    bid = _coerce_price_value(getattr(ticker, "bid", None))
    ask = _coerce_price_value(getattr(ticker, "ask", None))
    if bid is not None and ask is not None:
        return (bid + ask) / Decimal("2"), "ticker.bid_ask_mid"
    bid = _coerce_price_value(payload.get("bid"))
    ask = _coerce_price_value(payload.get("ask"))
    if bid is not None and ask is not None:
        return (bid + ask) / Decimal("2"), "raw_payload.bid_ask_mid"
    return None


def _get_orderbook_mid_price(client, pair):
    """Fetch mid-price from orderbook as final fallback."""
    try:
        from nonkyc_client.rest import RestRequest

        response = client.send(
            RestRequest(method="GET", path=f"/api/v2/orderbook/{pair}")
        )
        payload = response.get("data", response.get("result", response))
        if not isinstance(payload, dict):
            return None

        bids = payload.get("bids", [])
        asks = payload.get("asks", [])

        if not bids or not asks:
            return None

        # Extract best bid and ask prices
        # Orderbook format can be [[price, size], ...] or [{"price": price, "size": size}, ...]
        def extract_price(item):
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                return _coerce_price_value(item[0])
            elif isinstance(item, dict):
                return _coerce_price_value(item.get("price"))
            return None

        best_bid = extract_price(bids[0])
        best_ask = extract_price(asks[0])

        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) / Decimal("2")

        return None
    except Exception as e:
        print(f"    DEBUG: orderbook fallback failed: {e}")
        return None


def get_price(client, pair):
    """Fetch current market price for a trading pair."""
    try:
        ticker = client.get_market_data(pair)
        price = _coerce_price_value(ticker.last_price)
        if price is None:
            fallback_result = _fallback_price_from_ticker(ticker)
            if fallback_result is None:
                # Try orderbook as final fallback
                logger.debug(
                    f"Invalid last_price for {pair}: {ticker.last_price!r}, "
                    "trying orderbook..."
                )
                orderbook_price = _get_orderbook_mid_price(client, pair)
                if orderbook_price is not None:
                    logger.debug(f"{pair}: {orderbook_price} (from orderbook)")
                    return orderbook_price
                logger.warning(f"No price data available for {pair}")
                return None
            fallback_price, fallback_source = fallback_result
            logger.debug(
                f"Invalid last_price for {pair}: {ticker.last_price!r}, "
                f"using fallback {fallback_price} from {fallback_source}"
            )
            price = fallback_price
        logger.debug(f"{pair}: {price}")
        return price
    except Exception as e:
        logger.error(f"Failed to fetch price for {pair}: {e}")
        return None


def calculate_conversion_rates(config, prices):
    """Calculate conversion rates for the triangular cycle."""
    # USDT → ETH → BTC → USDT
    pair_ab = config["pair_ab"]  # ETH-USDT
    pair_bc = config["pair_bc"]  # ETH-BTC
    pair_ac = config["pair_ac"]  # BTC-USDT

    # For each step, calculate how much we get
    # Step 1: USDT → ETH (buy ETH with USDT)
    # ETH-USDT means price in USDT (how much USDT for 1 ETH), so we invert for ETH per USDT
    eth_usdt_price = prices[pair_ab]  # USDT per ETH
    usdt_eth_rate = Decimal("1") / eth_usdt_price  # ETH per USDT

    # Step 2: ETH → BTC (sell ETH for BTC)
    # ETH-BTC means price in BTC (how much BTC for 1 ETH), so BTC per ETH
    eth_btc_rate = prices[pair_bc]  # BTC per ETH

    # Step 3: BTC → USDT (sell BTC for USDT)
    # BTC-USDT means price in USDT (how much USDT for 1 BTC), so USDT per BTC
    btc_usdt_rate = prices[pair_ac]  # USDT per BTC

    return {
        "step1": usdt_eth_rate,  # USDT → ETH
        "step2": eth_btc_rate,  # ETH → BTC
        "step3": btc_usdt_rate,  # BTC → USDT
    }


def execute_arbitrage(client, config, prices, start_amount, mode="live"):
    """Execute the arbitrage cycle.

    Args:
        client: REST client
        config: Configuration dictionary
        prices: Price dictionary
        start_amount: Starting USDT amount for the cycle
        mode: Execution mode (monitor, dry-run, or live)

    Returns:
        Decimal: Final USDT amount if successful, None if failed
    """
    if mode == "monitor":
        logger.info("MONITOR MODE: Would execute cycle but skipping")
        return None

    user_provided_id = config.get("userProvidedId") or config.get("user_provided_id")
    strict_validate = (
        config["strictValidate"]
        if "strictValidate" in config
        else config.get("strict_validate")
    )
    fee_rate = _resolve_fee_rate(config)
    step_size, precision = resolve_quantity_rounding(config)
    min_quantities = _min_quantities_for_cycle(
        config,
        prices,
        step_size,
        precision,
    )
    min_eth = max(min_quantities[config["pair_ab"]], min_quantities[config["pair_bc"]])
    min_start_usdt = min_eth * prices[config["pair_ab"]]
    start_amount = max(start_amount, min_start_usdt)

    logger.info("\n🔄 EXECUTING ARBITRAGE CYCLE")
    logger.info(f"Starting amount: {start_amount} {config['asset_a']}")

    try:
        order_type = config.get("order_type", "market")
        # Step 1: Buy ETH with USDT
        logger.info(f"\nStep 1: Buying {config['asset_b']} with {config['asset_a']}...")
        eth_amount = start_amount / prices[config["pair_ab"]]
        eth_amount = max(eth_amount, min_eth)
        if _should_skip_notional(
            config,
            config["pair_ab"],
            "buy",
            eth_amount,
            prices[config["pair_ab"]],
            order_type,
        ):
            return None

        if mode == "dry-run":
            logger.info(f"DRY RUN: Would buy {eth_amount} {config['asset_b']}")
        else:
            order1 = OrderRequest(
                symbol=config["pair_ab"],
                side="buy",
                order_type=order_type,
                quantity=str(eth_amount),
                user_provided_id=user_provided_id,
                strict_validate=strict_validate,
            )
            response1 = client.place_order(order1)
            logger.info(f"  Order ID: {response1.order_id}, Status: {response1.status}")

        # TODO: Wait for order to fill and get actual ETH amount received
        # For now, estimate based on price
        eth_amount = eth_amount * (Decimal("1") - fee_rate)
        logger.info(f"  Received: ~{eth_amount} {config['asset_b']}")

        if mode != "dry-run":
            time.sleep(2)  # Brief pause between orders

        # Step 2: Sell ETH for BTC
        logger.info(f"\nStep 2: Selling {config['asset_b']} for {config['asset_c']}...")
        eth_amount = max(eth_amount, min_quantities[config["pair_bc"]])
        if _should_skip_notional(
            config,
            config["pair_bc"],
            "sell",
            eth_amount,
            prices[config["pair_bc"]],
            order_type,
        ):
            return None

        if mode == "dry-run":
            logger.info(f"DRY RUN: Would sell {eth_amount} {config['asset_b']}")
        else:
            order2 = OrderRequest(
                symbol=config["pair_bc"],
                side="sell",
                order_type=order_type,
                quantity=str(eth_amount),
                user_provided_id=user_provided_id,
                strict_validate=strict_validate,
            )
            response2 = client.place_order(order2)
            logger.info(f"  Order ID: {response2.order_id}, Status: {response2.status}")

        btc_amount = eth_amount * prices[config["pair_bc"]]
        btc_amount = btc_amount * (Decimal("1") - fee_rate)
        logger.info(f"  Received: ~{btc_amount} {config['asset_c']}")

        if mode != "dry-run":
            time.sleep(2)

        # Step 3: Sell BTC for USDT
        logger.info(f"\nStep 3: Selling {config['asset_c']} for {config['asset_a']}...")
        btc_amount = max(btc_amount, min_quantities[config["pair_ac"]])
        if _should_skip_notional(
            config,
            config["pair_ac"],
            "sell",
            btc_amount,
            prices[config["pair_ac"]],
            order_type,
        ):
            return None

        if mode == "dry-run":
            logger.info(f"DRY RUN: Would sell {btc_amount} {config['asset_c']}")
        else:
            order3 = OrderRequest(
                symbol=config["pair_ac"],
                side="sell",
                order_type=order_type,
                quantity=str(btc_amount),
                user_provided_id=user_provided_id,
                strict_validate=strict_validate,
            )
            response3 = client.place_order(order3)
            logger.info(f"  Order ID: {response3.order_id}, Status: {response3.status}")

        final_usdt = btc_amount * prices[config["pair_ac"]]
        final_usdt = final_usdt * (Decimal("1") - fee_rate)
        logger.info(f"  Received: ~{final_usdt} {config['asset_a']}")

        profit = final_usdt - start_amount
        profit_pct = (profit / start_amount) * 100

        logger.info("\n✅ CYCLE COMPLETE!")
        logger.info(f"Started with: {start_amount} {config['asset_a']}")
        logger.info(f"Ended with: {final_usdt} {config['asset_a']}")
        logger.info(f"Profit: {profit} {config['asset_a']} ({profit_pct:.2f}%)")

        return final_usdt

    except Exception as e:
        logger.error(f"\n❌ ERROR during execution: {e}", exc_info=True)
        return None


def evaluate_profitability_and_execute(client, config, prices, current_balance, mode="live"):
    """Evaluate profit and execute arbitrage when thresholds are met.

    Args:
        client: REST client
        config: Configuration dictionary
        prices: Price dictionary
        current_balance: Current USDT balance to trade with
        mode: Execution mode (monitor, dry-run, or live)

    Returns:
        Decimal: New balance if successful profitable trade, None otherwise
    """
    # Calculate conversion rates
    rates = calculate_conversion_rates(config, prices)

    # Calculate expected profit
    start_amount = current_balance
    fee_rate = _resolve_fee_rate(config)
    step_size, precision = resolve_quantity_rounding(config)

    # Simulate the cycle
    amount = start_amount
    amount = amount * rates["step1"]  # USDT → ETH
    amount = amount * (Decimal("1") - fee_rate)  # Fee

    amount = amount * rates["step2"]  # ETH → BTC
    amount = amount * (Decimal("1") - fee_rate)  # Fee

    amount = amount * rates["step3"]  # BTC → USDT
    amount = amount * (Decimal("1") - fee_rate)  # Fee

    profit = amount - start_amount
    profit_ratio = profit / start_amount
    profit_pct = profit_ratio * 100

    logger.info("\n💰 Profit Analysis:")
    logger.info(f"  Start: {start_amount} {config['asset_a']}")
    logger.info(f"  End: {amount:.8f} {config['asset_a']}")
    logger.info(f"  Profit: {profit:.8f} {config['asset_a']} ({profit_pct:.4f}%)")
    logger.info(f"  Threshold: {float(config['min_profitability'])*100}%")

    # Check if profitable
    min_profit = Decimal(str(config["min_profitability"]))

    if profit_ratio >= min_profit:
        logger.info(f"\n🚀 OPPORTUNITY FOUND! Profit: {profit_pct:.4f}%")
        min_quantities = _min_quantities_for_cycle(
            config,
            prices,
            step_size,
            precision,
        )
        (
            adjusted_start,
            adjusted_final,
            adjusted_profit_ratio,
        ) = _simulate_fee_adjusted_cycle(
            config,
            prices,
            start_amount,
            min_quantities,
        )
        adjusted_profit_pct = adjusted_profit_ratio * 100
        logger.info("\n🔎 Fee-Adjusted Cycle Check:")
        logger.info(f"  Start (adjusted): {adjusted_start} {config['asset_a']}")
        logger.info(f"  End (adjusted): {adjusted_final:.8f} {config['asset_a']}")
        logger.info(
            "  Profit (adjusted): "
            f"{adjusted_final - adjusted_start:.8f} {config['asset_a']} "
            f"({adjusted_profit_pct:.4f}%)"
        )

        if adjusted_profit_ratio < min_profit:
            logger.info("\n⏸️  Fee-adjusted profit below threshold. Skipping execution.")
            logger.info(f"  Threshold: {float(config['min_profitability'])*100}%")
            return None

        final_balance = execute_arbitrage(client, config, prices, start_amount, mode)
        return final_balance

    logger.info(f"\n⏸️  No opportunity - profit {profit_pct:.4f}% below threshold")
    return None


def run_arbitrage_bot(config: dict[str, Any]) -> None:
    """Main bot loop."""
    mode = config.get("mode", "monitor")

    logger.info("=" * 80)
    logger.info("USDT/ETH/BTC Triangular Arbitrage Bot")
    logger.info("=" * 80)
    logger.info(f"Running in {mode.upper()} mode")

    logger.info("\n📋 Configuration:")
    logger.info(
        f"  Triangle: {config['asset_a']} → {config['asset_b']} → {config['asset_c']} → {config['asset_a']}"
    )
    logger.info(f"  Trade amount: {config['trade_amount_a']} {config['asset_a']}")
    logger.info(f"  Min profitability: {float(config['min_profitability'])*100}%")
    fee_rate = _resolve_fee_rate(config)
    logger.info(f"  Fee rate: {float(fee_rate)*100}%")
    poll_interval = config.get("poll_interval_seconds", config.get("refresh_time", 2))
    logger.info(f"  Poll interval: {poll_interval}s")

    # Setup client
    client = build_rest_client(config)

    logger.info("\n✅ Connected to NonKYC API")

    # Initialize current balance (will be updated after successful profitable trades)
    current_balance = Decimal(str(config["trade_amount_a"]))
    initial_balance = current_balance
    logger.info(f"\n💰 Starting balance: {current_balance} {config['asset_a']}")

    cycle_count = 0
    successful_profit_cycles = 0
    opportunities_found = 0

    try:
        while True:
            cycle_count += 1
            logger.info(f"\n{'=' * 80}")
            logger.info(
                f"Cycle #{cycle_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            logger.info(f"{'=' * 80}")
            logger.debug(f"💼 Current balance: {current_balance} {config['asset_a']}")

            # Fetch current prices
            logger.debug("\n📊 Fetching prices...")
            prices = {}

            for pair in [config["pair_ab"], config["pair_bc"], config["pair_ac"]]:
                price = get_price(client, pair)
                if price is None:
                    logger.warning(f"⚠️  Skipping cycle - failed to fetch price for {pair}")
                    time.sleep(poll_interval)
                    continue
                prices[pair] = price

            if len(prices) != 3:
                continue

            new_balance = evaluate_profitability_and_execute(
                client, config, prices, current_balance, mode
            )

            # Update balance if the cycle was successful and profitable
            if new_balance is not None:
                opportunities_found += 1
                if mode == "live" and new_balance > current_balance:
                    previous_balance = current_balance
                    current_balance = new_balance
                    successful_profit_cycles += 1
                    profit = current_balance - previous_balance
                    total_profit = current_balance - initial_balance
                    profit_pct = (
                        (current_balance - previous_balance) / previous_balance
                    ) * 100
                    total_profit_pct = (
                        (current_balance - initial_balance) / initial_balance
                    ) * 100
                    logger.info("\n🎉 PROFIT REINVESTED!")
                    logger.info(f"  Previous balance: {previous_balance} {config['asset_a']}")
                    logger.info(f"  New balance: {current_balance} {config['asset_a']}")
                    logger.info(
                        f"  Cycle profit: {profit} {config['asset_a']} ({profit_pct:.2f}%)"
                    )
                    logger.info(
                        f"  Total profit: {total_profit} {config['asset_a']} ({total_profit_pct:.2f}%)"
                    )
                    logger.info(f"  Successful profit cycles: {successful_profit_cycles}")

            # Log statistics periodically
            if cycle_count % 100 == 0:
                logger.info(
                    f"Stats: {cycle_count} cycles evaluated, "
                    f"{opportunities_found} opportunities found"
                )

            # Wait before next cycle
            logger.debug(f"\n⏰ Waiting {poll_interval} seconds...")
            time.sleep(poll_interval)

    except KeyboardInterrupt:
        logger.info("\n\n🛑 Bot stopped by user")
        logger.info(f"Total cycles run: {cycle_count}")
        logger.info(f"Opportunities found: {opportunities_found}")
        logger.info(f"Successful profit cycles: {successful_profit_cycles}")
        logger.info("\n📊 Final Statistics:")
        logger.info(f"  Initial balance: {initial_balance} {config['asset_a']}")
        logger.info(f"  Final balance: {current_balance} {config['asset_a']}")
        total_profit = current_balance - initial_balance
        if initial_balance > 0:
            total_profit_pct = (total_profit / initial_balance) * 100
            logger.info(
                f"  Total profit: {total_profit} {config['asset_a']} ({total_profit_pct:.2f}%)"
            )
    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}", exc_info=True)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="USDT/ETH/BTC triangular arbitrage bot")
    parser.add_argument("config", help="Path to configuration file")
    parser.add_argument(
        "--monitor-only",
        action="store_true",
        help="Monitor mode only (no execution)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode (simulated execution)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(level=args.log_level)

    # Load config
    config = load_config(args.config)

    # Set mode
    if args.monitor_only:
        config["mode"] = "monitor"
    elif args.dry_run:
        config["mode"] = "dry-run"
    else:
        config["mode"] = config.get("mode", "live")

    # Run bot
    run_arbitrage_bot(config)


if __name__ == "__main__":
    main()
