#!/usr/bin/env python
"""USDT/ETH/BTC Triangular Arbitrage Bot - Starting with USDT (order book pairs only)"""

import os
import re
import sys
import time
from datetime import datetime
from decimal import ROUND_UP, Decimal

import yaml

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from nonkyc_client.auth import ApiCredentials, AuthSigner
from nonkyc_client.models import OrderRequest
from nonkyc_client.pricing import (
    effective_notional,
    min_quantity_for_notional,
    round_up_to_step,
)
from nonkyc_client.rest import RestClient
from strategies.triangular_arb import evaluate_cycle, find_profitable_cycle
from utils.notional import resolve_quantity_rounding


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
        ApiCredentials(api_key=config["api_key"], api_secret=config["api_secret"])
        if signing_enabled
        else None
    )
    sign_absolute_url = config.get("sign_absolute_url")
    signer = (
        AuthSigner(
            nonce_multiplier=config.get("nonce_multiplier", 1e4),
            sort_params=config.get("sort_params", False),
            sort_body=config.get("sort_body", False),
        )
        if signing_enabled
        else None
    )
    return RestClient(
        base_url="https://api.nonkyc.io",
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
    for key in ("last", "price"):
        candidate = payload.get(key)
        price = _coerce_price_value(candidate)
        if price is not None:
            return price
    return None


def get_price(client, pair):
    """Fetch current market price for a trading pair."""
    try:
        ticker = client.get_market_data(pair)
        price = _coerce_price_value(ticker.last_price)
        if price is None:
            fallback_price = _fallback_price_from_ticker(ticker)
            if fallback_price is None:
                print(
                    "  WARNING: invalid last_price for "
                    f"{pair}: {ticker.last_price!r}"
                )
                return None
            print(
                "  WARNING: invalid last_price for "
                f"{pair}: {ticker.last_price!r} "
                f"using fallback {fallback_price}"
            )
            price = fallback_price
        print(f"  {pair}: {price}")
        return price
    except Exception as e:
        print(f"  ERROR fetching {pair}: {e}")
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


def execute_arbitrage(client, config, prices):
    """Execute the arbitrage cycle."""
    start_amount = Decimal(str(config["trade_amount_a"]))
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

    print(f"\n🔄 EXECUTING ARBITRAGE CYCLE")
    print(f"Starting amount: {start_amount} {config['asset_a']}")

    try:
        order_type = "market"
        # Step 1: Buy ETH with USDT
        print(f"\nStep 1: Buying {config['asset_b']} with {config['asset_a']}...")
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
            return False
        order1 = OrderRequest(
            symbol=config["pair_ab"],
            side="buy",
            order_type=order_type,
            quantity=str(eth_amount),
            user_provided_id=user_provided_id,
            strict_validate=strict_validate,
        )
        response1 = client.place_order(order1)
        print(f"  Order ID: {response1.order_id}, Status: {response1.status}")

        # TODO: Wait for order to fill and get actual ETH amount received
        # For now, estimate based on price
        eth_amount = eth_amount * (Decimal("1") - fee_rate)
        print(f"  Received: ~{eth_amount} {config['asset_b']}")

        time.sleep(2)  # Brief pause between orders

        # Step 2: Sell ETH for BTC
        print(f"\nStep 2: Selling {config['asset_b']} for {config['asset_c']}...")
        eth_amount = max(eth_amount, min_quantities[config["pair_bc"]])
        if _should_skip_notional(
            config,
            config["pair_bc"],
            "sell",
            eth_amount,
            prices[config["pair_bc"]],
            order_type,
        ):
            return False
        order2 = OrderRequest(
            symbol=config["pair_bc"],
            side="sell",
            order_type=order_type,
            quantity=str(eth_amount),
            user_provided_id=user_provided_id,
            strict_validate=strict_validate,
        )
        response2 = client.place_order(order2)
        print(f"  Order ID: {response2.order_id}, Status: {response2.status}")

        btc_amount = eth_amount * prices[config["pair_bc"]]
        btc_amount = btc_amount * (Decimal("1") - fee_rate)
        print(f"  Received: ~{btc_amount} {config['asset_c']}")

        time.sleep(2)

        # Step 3: Sell BTC for USDT
        print(f"\nStep 3: Selling {config['asset_c']} for {config['asset_a']}...")
        btc_amount = max(btc_amount, min_quantities[config["pair_ac"]])
        if _should_skip_notional(
            config,
            config["pair_ac"],
            "sell",
            btc_amount,
            prices[config["pair_ac"]],
            order_type,
        ):
            return False
        order3 = OrderRequest(
            symbol=config["pair_ac"],
            side="sell",
            order_type=order_type,
            quantity=str(btc_amount),
            user_provided_id=user_provided_id,
            strict_validate=strict_validate,
        )
        response3 = client.place_order(order3)
        print(f"  Order ID: {response3.order_id}, Status: {response3.status}")

        final_usdt = btc_amount * prices[config["pair_ac"]]
        final_usdt = final_usdt * (Decimal("1") - fee_rate)
        print(f"  Received: ~{final_usdt} {config['asset_a']}")

        profit = final_usdt - start_amount
        profit_pct = (profit / start_amount) * 100

        print(f"\n✅ CYCLE COMPLETE!")
        print(f"Started with: {start_amount} {config['asset_a']}")
        print(f"Ended with: {final_usdt} {config['asset_a']}")
        print(f"Profit: {profit} {config['asset_a']} ({profit_pct:.2f}%)")

        return True

    except Exception as e:
        print(f"\n❌ ERROR during execution: {e}")
        return False


def evaluate_profitability_and_execute(client, config, prices) -> bool:
    """Evaluate profit and execute arbitrage when thresholds are met."""
    # Calculate conversion rates
    rates = calculate_conversion_rates(config, prices)

    # Calculate expected profit
    start_amount = Decimal(str(config["trade_amount_a"]))
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

    print(f"\n💰 Profit Analysis:")
    print(f"  Start: {start_amount} {config['asset_a']}")
    print(f"  End: {amount:.8f} {config['asset_a']}")
    print(f"  Profit: {profit:.8f} {config['asset_a']} ({profit_pct:.4f}%)")
    print(f"  Threshold: {float(config['min_profitability'])*100}%")

    # Check if profitable
    min_profit = Decimal(str(config["min_profitability"]))

    if profit_ratio >= min_profit:
        print(f"\n🚀 OPPORTUNITY FOUND! Profit: {profit_pct:.4f}%")
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
        print("\n🔎 Fee-Adjusted Cycle Check:")
        print(f"  Start (adjusted): {adjusted_start} {config['asset_a']}")
        print(f"  End (adjusted): {adjusted_final:.8f} {config['asset_a']}")
        print(
            "  Profit (adjusted): "
            f"{adjusted_final - adjusted_start:.8f} {config['asset_a']} "
            f"({adjusted_profit_pct:.4f}%)"
        )

        if adjusted_profit_ratio < min_profit:
            print("\n⏸️  Fee-adjusted profit below threshold. " "Skipping execution.")
            print(f"  Threshold: {float(config['min_profitability'])*100}%")
            return False

        execute_arbitrage(client, config, prices)
        return True

    print(f"\n⏸️  No opportunity - profit {profit_pct:.4f}% below threshold")
    return False


def run_arbitrage_bot(config_file):
    """Main bot loop."""
    print("=" * 80)
    print("USDT/ETH/BTC Triangular Arbitrage Bot")
    print("=" * 80)

    # Load config
    config = load_config(config_file)
    print(f"\n📋 Configuration:")
    print(
        f"  Triangle: {config['asset_a']} → {config['asset_b']} → {config['asset_c']} → {config['asset_a']}"
    )
    print(f"  Trade amount: {config['trade_amount_a']} {config['asset_a']}")
    print(f"  Min profitability: {float(config['min_profitability'])*100}%")
    fee_rate = _resolve_fee_rate(config)
    print(f"  Fee rate: {float(fee_rate)*100}%")
    refresh_seconds = int(config["refresh_time"])
    print(f"  Refresh time: {refresh_seconds}s")

    # Setup client
    client = build_rest_client(config)

    print("\n✅ Connected to NonKYC API")

    cycle_count = 0

    try:
        while True:
            cycle_count += 1
            print(f"\n{'=' * 80}")
            print(
                f"Cycle #{cycle_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            print(f"{'=' * 80}")

            # Fetch current prices
            print("\n📊 Fetching prices...")
            prices = {}

            for pair in [config["pair_ab"], config["pair_bc"], config["pair_ac"]]:
                price = get_price(client, pair)
                if price is None:
                    print(f"⚠️  Skipping cycle - failed to fetch price for {pair}")
                    time.sleep(config["refresh_time"])
                    continue
                prices[pair] = price

            if len(prices) != 3:
                continue

            evaluate_profitability_and_execute(client, config, prices)

            # Wait before next cycle
            print(f"\n⏰ Waiting {refresh_seconds} seconds...")
            time.sleep(refresh_seconds)

    except KeyboardInterrupt:
        print("\n\n🛑 Bot stopped by user")
        print(f"Total cycles run: {cycle_count}")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_arb_bot.py <config_file>")
        print("Example: python run_arb_bot.py arb_config.yml")
        sys.exit(1)

    config_file = sys.argv[1]

    if not os.path.exists(config_file):
        print(f"Error: Config file '{config_file}' not found!")
        sys.exit(1)

    run_arbitrage_bot(config_file)
