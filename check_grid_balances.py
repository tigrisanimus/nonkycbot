#!/usr/bin/env python3
"""
Check if you have sufficient balance to run the grid bot
"""

import os
import sys
import yaml
from decimal import Decimal
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from nonkyc_client.auth import ApiCredentials
from nonkyc_client.rest import RestClient, AuthSigner


def load_config(config_path: str) -> dict:
    """Load YAML config"""
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    if len(sys.argv) < 2:
        print("Usage: python check_grid_balances.py <config.yml>")
        return 1

    config_path = sys.argv[1]
    config = load_config(config_path)

    # Get credentials
    api_key = os.getenv("NONKYC_API_KEY")
    api_secret = os.getenv("NONKYC_API_SECRET")

    if not api_key or not api_secret:
        print("❌ Missing credentials. Set NONKYC_API_KEY and NONKYC_API_SECRET")
        return 1

    # Create client
    credentials = ApiCredentials(api_key=api_key, api_secret=api_secret)
    signer = AuthSigner(nonce_multiplier=1e3)
    client = RestClient(
        base_url="https://api.nonkyc.io/api/v2",
        credentials=credentials,
        signer=signer,
    )

    print("\n" + "="*80)
    print("Grid Bot Balance Check")
    print("="*80)

    # Get config values
    symbol = config.get("symbol")
    step_pct = Decimal(str(config.get("step_pct", "0.01")))
    n_buy_levels = int(config.get("n_buy_levels", 10))
    n_sell_levels = int(config.get("n_sell_levels", 10))
    base_order_size = Decimal(str(config.get("base_order_size", "1")))

    print(f"\nSymbol: {symbol}")
    print(f"Step %: {step_pct * 100}%")
    print(f"Buy levels: {n_buy_levels}")
    print(f"Sell levels: {n_sell_levels}")
    print(f"Base order size: {base_order_size}")

    # Parse symbol
    if "_" in symbol:
        base, quote = symbol.split("_", 1)
    elif "/" in symbol:
        base, quote = symbol.split("/", 1)
    elif "-" in symbol:
        base, quote = symbol.split("-", 1)
    else:
        print(f"❌ Unsupported symbol format: {symbol}")
        return 1

    print(f"\nBase asset: {base}")
    print(f"Quote asset: {quote}")

    # Get mid price
    try:
        from nonkyc_client.rest_exchange import RestExchangeClient
        exchange = RestExchangeClient(client)
        mid_price = exchange.get_mid_price(symbol)
        print(f"Current mid price: {mid_price}")
    except Exception as exc:
        print(f"⚠️  Could not get mid price: {exc}")
        print("Assuming mid price = 1.0 for balance calculation")
        mid_price = Decimal("1.0")

    # Get balances
    print("\n" + "="*80)
    print("Current Balances")
    print("="*80)

    try:
        response = client.send(client.RestRequest(method="GET", path="/balances"))
        balances = {}
        for item in response:
            asset = item.get("asset")
            available = Decimal(item.get("available", "0"))
            if available > 0:
                balances[asset] = available
                if asset in [base, quote]:
                    print(f"✓ {asset}: {available}")
    except Exception as exc:
        print(f"❌ Error fetching balances: {exc}")
        return 1

    # Calculate requirements
    print("\n" + "="*80)
    print("Balance Requirements")
    print("="*80)

    # For buy orders, we need quote (USDT)
    buy_price_start = mid_price * (Decimal("1") - step_pct)
    buy_quote_per_order = buy_price_start * base_order_size
    total_buy_quote = buy_quote_per_order * n_buy_levels

    print(f"\nBUY Orders ({n_buy_levels} levels):")
    print(f"  Price per order: ~{buy_price_start:.8f} {quote}")
    print(f"  Size per order: {base_order_size} {base}")
    print(f"  Quote per order: ~{buy_quote_per_order:.8f} {quote}")
    print(f"  Total {quote} needed: ~{total_buy_quote:.8f}")

    # For sell orders, we need base (COSA)
    total_sell_base = base_order_size * n_sell_levels

    print(f"\nSELL Orders ({n_sell_levels} levels):")
    print(f"  Size per order: {base_order_size} {base}")
    print(f"  Total {base} needed: {total_sell_base}")

    # Check if sufficient
    print("\n" + "="*80)
    print("Balance Check")
    print("="*80)

    quote_balance = balances.get(quote, Decimal("0"))
    base_balance = balances.get(base, Decimal("0"))

    print(f"\n{quote}:")
    print(f"  Available: {quote_balance}")
    print(f"  Required: {total_buy_quote:.8f}")
    if quote_balance >= total_buy_quote:
        print(f"  ✅ SUFFICIENT for {n_buy_levels} buy orders")
    else:
        print(f"  ❌ INSUFFICIENT - need {total_buy_quote - quote_balance:.8f} more")

    print(f"\n{base}:")
    print(f"  Available: {base_balance}")
    print(f"  Required: {total_sell_base}")
    if base_balance >= total_sell_base:
        print(f"  ✅ SUFFICIENT for {n_sell_levels} sell orders")
    else:
        print(f"  ❌ INSUFFICIENT - need {total_sell_base - base_balance} more")

    # Overall verdict
    print("\n" + "="*80)
    if quote_balance >= total_buy_quote and base_balance >= total_sell_base:
        print("✅ READY TO RUN - You have sufficient balance for all orders!")
    elif quote_balance >= total_buy_quote or base_balance >= total_sell_base:
        print("⚠️  PARTIAL BALANCE - Bot will place some orders but not all")
        print("\nThe bot will set needs_rebalance=True and halt after first")
        print("insufficient balance check.")
    else:
        print("❌ INSUFFICIENT BALANCE - Bot will not place any orders")
        print("\nOptions:")
        print("  1. Deposit more funds to your NonKYC account")
        print("  2. Reduce base_order_size in config")
        print("  3. Reduce n_buy_levels and n_sell_levels")
        print("  4. Enable startup_rebalance: true (if you have one asset)")
    print("="*80)

    # Check state.json
    state_path = config.get("state_path", "state.json")
    if os.path.exists(state_path):
        import json
        with open(state_path) as f:
            state = json.load(f)
        needs_rebalance = state.get("needs_rebalance", False)
        if needs_rebalance:
            print("\n⚠️  state.json shows needs_rebalance=True")
            print("This means the bot previously detected insufficient balance.")
            print("Delete state.json to retry, or enable startup_rebalance.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
