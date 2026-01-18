#!/usr/bin/env python
"""PIRATE/USDT/BTC Triangular Arbitrage Bot - Starting with PIRATE (order book pairs only)"""

import os
import sys
import time
from datetime import datetime
from decimal import Decimal, ROUND_UP

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
    fee_rate = Decimal(str(config.get("fee_rate", "0")))
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
    fee_rate = Decimal(str(config.get("fee_rate", "0")))
    pair_ab = config["pair_ab"]
    pair_bc = config["pair_bc"]
    pair_ac = config["pair_ac"]

    adjusted_start = max(start_amount, min_quantities[pair_ab])

    usdt_amount = adjusted_start * prices[pair_ab]
    usdt_amount = usdt_amount * (Decimal("1") - fee_rate)

    btc_amount = usdt_amount / prices[pair_bc]
    btc_amount = max(btc_amount, min_quantities[pair_bc])
    btc_amount = btc_amount * (Decimal("1") - fee_rate)

    final_pirate = btc_amount / prices[pair_ac]
    final_pirate = max(final_pirate, min_quantities[pair_ac])
    final_pirate = final_pirate * (Decimal("1") - fee_rate)

    profit = final_pirate - adjusted_start
    profit_ratio = profit / adjusted_start
    return adjusted_start, final_pirate, profit_ratio


def _should_skip_notional(config, symbol, side, quantity, price, order_type):
    min_notional = Decimal(str(config.get("min_notional_usd", "1.0")))
    fee_rate = Decimal(str(config.get("fee_rate", "0")))
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


def get_price(client, pair):
    """Fetch current market price for a trading pair."""
    try:
        ticker = client.get_market_data(pair)
        price = Decimal(ticker.last_price)
        print(f"  {pair}: {price}")
        return price
    except Exception as e:
        print(f"  ERROR fetching {pair}: {e}")
        return None


def calculate_conversion_rates(config, prices):
    """Calculate conversion rates for the triangular cycle."""
    # PIRATE → USDT → BTC → PIRATE
    pair_ab = config["pair_ab"]  # PIRATE-USDT
    pair_bc = config["pair_bc"]  # BTC-USDT
    pair_ac = config["pair_ac"]  # PIRATE-BTC

    # For each step, calculate how much we get
    # Step 1: PIRATE → USDT (sell PIRATE for USDT)
    # PIRATE-USDT means price in USDT, so that's USDT per PIRATE
    pirate_usdt_rate = prices[pair_ab]  # How much USDT per PIRATE

    # Step 2: USDT → BTC (buy BTC with USDT)
    # BTC-USDT means price in USDT (how much USDT for 1 BTC), so we need to invert
    btc_usdt_price = prices[pair_bc]  # USDT per BTC
    usdt_btc_rate = Decimal("1") / btc_usdt_price  # BTC per USDT

    # Step 3: BTC → PIRATE (buy PIRATE with BTC)
    # PIRATE-BTC means price in BTC (how much BTC for 1 PIRATE), so we need to invert
    pirate_btc_price = prices[pair_ac]  # BTC per PIRATE
    btc_pirate_rate = Decimal("1") / pirate_btc_price  # PIRATE per BTC

    return {
        "step1": pirate_usdt_rate,  # PIRATE → USDT
        "step2": usdt_btc_rate,  # USDT → BTC
        "step3": btc_pirate_rate,  # BTC → PIRATE
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
    fee_rate = Decimal(str(config.get("fee_rate", "0")))
    step_size, precision = resolve_quantity_rounding(config)
    min_quantities = _min_quantities_for_cycle(
        config,
        prices,
        step_size,
        precision,
    )

    print(f"\n🔄 EXECUTING ARBITRAGE CYCLE")
    print(f"Starting amount: {start_amount} PIRATE")

    try:
        order_type = config.get("order_type", "limit")
        # Step 1: Sell PIRATE for USDT
        print(f"\nStep 1: Selling PIRATE for USDT...")
        start_amount = max(start_amount, min_quantities[config["pair_ab"]])
        if _should_skip_notional(
            config,
            config["pair_ab"],
            "sell",
            start_amount,
            prices[config["pair_ab"]],
            order_type,
        ):
            return False
        order1 = OrderRequest(
            symbol=config["pair_ab"],
            side="sell",
            order_type=order_type,
            quantity=str(start_amount),
            user_provided_id=user_provided_id,
            strict_validate=strict_validate,
        )
        response1 = client.place_order(order1)
        print(f"  Order ID: {response1.order_id}, Status: {response1.status}")

        # TODO: Wait for order to fill and get actual USDT amount received
        # For now, estimate based on price
        usdt_amount = start_amount * prices[config["pair_ab"]]
        usdt_amount = usdt_amount * (Decimal("1") - fee_rate)
        print(f"  Received: ~{usdt_amount} USDT")

        time.sleep(2)  # Brief pause between orders

        # Step 2: Buy BTC with USDT
        print(f"\nStep 2: Buying BTC with USDT...")
        btc_amount = usdt_amount / prices[config["pair_bc"]]
        btc_amount = max(btc_amount, min_quantities[config["pair_bc"]])
        if _should_skip_notional(
            config,
            config["pair_bc"],
            "buy",
            btc_amount,
            prices[config["pair_bc"]],
            order_type,
        ):
            return False
        order2 = OrderRequest(
            symbol=config["pair_bc"],
            side="buy",
            order_type=order_type,
            quantity=str(btc_amount),
            user_provided_id=user_provided_id,
            strict_validate=strict_validate,
        )
        response2 = client.place_order(order2)
        print(f"  Order ID: {response2.order_id}, Status: {response2.status}")

        btc_amount = btc_amount * (Decimal("1") - fee_rate)
        print(f"  Received: ~{btc_amount} BTC")

        time.sleep(2)

        # Step 3: Buy PIRATE with BTC
        print(f"\nStep 3: Buying PIRATE with BTC...")
        final_pirate = btc_amount / prices[config["pair_ac"]]
        final_pirate = max(final_pirate, min_quantities[config["pair_ac"]])
        if _should_skip_notional(
            config,
            config["pair_ac"],
            "buy",
            final_pirate,
            prices[config["pair_ac"]],
            order_type,
        ):
            return False
        order3 = OrderRequest(
            symbol=config["pair_ac"],
            side="buy",
            order_type=order_type,
            quantity=str(final_pirate),
            user_provided_id=user_provided_id,
            strict_validate=strict_validate,
        )
        response3 = client.place_order(order3)
        print(f"  Order ID: {response3.order_id}, Status: {response3.status}")

        final_pirate = final_pirate * (Decimal("1") - fee_rate)
        print(f"  Received: ~{final_pirate} PIRATE")

        profit = final_pirate - start_amount
        profit_pct = (profit / start_amount) * 100

        print(f"\n✅ CYCLE COMPLETE!")
        print(f"Started with: {start_amount} PIRATE")
        print(f"Ended with: {final_pirate} PIRATE")
        print(f"Profit: {profit} PIRATE ({profit_pct:.2f}%)")

        return True

    except Exception as e:
        print(f"\n❌ ERROR during execution: {e}")
        return False


def cancel_all_orders(client, config):
    """Cancel all open orders for configured trading pairs."""
    print(f"\n🗑️  Cancelling all open orders...")
    symbol_format = config.get("cancel_symbol_format", "underscore")
    symbols = [config["pair_ab"], config["pair_bc"], config["pair_ac"]]
    success = True
    for symbol in symbols:
        formatted_symbol = symbol
        if symbol_format == "underscore":
            formatted_symbol = symbol.replace("/", "_")
        try:
            canceled = client.cancel_all_orders(formatted_symbol)
        except Exception as exc:
            print(f"  ✗ Error cancelling orders for {symbol}: {exc}")
            success = False
            continue
        if canceled:
            print(f"  ✓ Cancelled all orders for {symbol}")
        else:
            print(
                f"  ✗ Cancel all orders failed for {symbol}. Response: {client.last_cancel_all_response}"
            )
            success = False
    return success


def run_arbitrage_bot(config_file):
    """Main bot loop."""
    print("=" * 80)
    print("PIRATE/USDT/BTC Triangular Arbitrage Bot")
    print("=" * 80)

    # Load config
    config = load_config(config_file)
    print(f"\n📋 Configuration:")
    print(
        f"  Triangle: {config['asset_a']} → {config['asset_b']} → {config['asset_c']} → {config['asset_a']}"
    )
    print(f"  Trade amount: {config['trade_amount_a']} {config['asset_a']}")
    print(f"  Min profitability: {float(config['min_profitability'])*100}%")
    print(f"  Fee rate: {float(config['fee_rate'])*100}%")
    max_refresh_seconds = int(config.get("max_refresh_seconds", 1800))
    refresh_seconds = int(config["refresh_time"])
    effective_refresh_seconds = min(refresh_seconds, max_refresh_seconds)
    print(f"  Refresh time: {refresh_seconds}s")
    print(f"  Max refresh time: {max_refresh_seconds}s")

    # Setup client
    client = build_rest_client(config)

    print("\n✅ Connected to NonKYC API")

    cycle_count = 0

    last_cancel_timestamp = time.time()
    try:
        while True:
            cycle_count += 1
            current_time = time.time()
            if current_time - last_cancel_timestamp >= max_refresh_seconds:
                cancel_all_orders(client, config)
                last_cancel_timestamp = current_time
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

            # Calculate conversion rates
            rates = calculate_conversion_rates(config, prices)

            # Calculate expected profit
            start_amount = Decimal(str(config["trade_amount_a"]))
            fee_rate = Decimal(str(config["fee_rate"]))
            step_size, precision = resolve_quantity_rounding(config)

            # Simulate the cycle
            amount = start_amount
            amount = amount * rates["step1"]  # PIRATE → USDT
            amount = amount * (Decimal("1") - fee_rate)  # Fee

            amount = amount * rates["step2"]  # USDT → BTC
            amount = amount * (Decimal("1") - fee_rate)  # Fee

            amount = amount * rates["step3"]  # BTC → PIRATE
            amount = amount * (Decimal("1") - fee_rate)  # Fee

            profit = amount - start_amount
            profit_ratio = profit / start_amount
            profit_pct = profit_ratio * 100

            print(f"\n💰 Profit Analysis:")
            print(f"  Start: {start_amount} PIRATE")
            print(f"  End: {amount:.8f} PIRATE")
            print(f"  Profit: {profit:.8f} PIRATE ({profit_pct:.4f}%)")
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
                print(f"  Start (adjusted): {adjusted_start} PIRATE")
                print(f"  End (adjusted): {adjusted_final:.8f} PIRATE")
                print(
                    "  Profit (adjusted): "
                    f"{adjusted_final - adjusted_start:.8f} PIRATE "
                    f"({adjusted_profit_pct:.4f}%)"
                )

                if adjusted_profit_ratio < min_profit:
                    print(
                        "\n⏸️  Fee-adjusted profit below threshold. "
                        "Skipping execution."
                    )
                    print(f"  Threshold: {float(config['min_profitability'])*100}%")
                    continue

                # Ask for confirmation
                response = input("\nExecute arbitrage? (yes/no): ")
                if response.lower() in ["yes", "y"]:
                    execute_arbitrage(client, config, prices)
                else:
                    print("Skipped by user.")
            else:
                print(f"\n⏸️  No opportunity - profit {profit_pct:.4f}% below threshold")

            # Wait before next cycle
            print(f"\n⏰ Waiting {effective_refresh_seconds} seconds...")
            time.sleep(effective_refresh_seconds)

    except KeyboardInterrupt:
        print("\n\n🛑 Bot stopped by user")
        print(f"Total cycles run: {cycle_count}")
        cancel_all_orders(client, config)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_cosa_arb.py <config_file>")
        print("Example: python run_cosa_arb.py pirate_arb_config.yml")
        sys.exit(1)

    config_file = sys.argv[1]

    if not os.path.exists(config_file):
        print(f"Error: Config file '{config_file}' not found!")
        sys.exit(1)

    run_arbitrage_bot(config_file)
