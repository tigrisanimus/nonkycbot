#!/usr/bin/env python
"""Grid Trading Bot for COSA/PIRATE or any trading pair"""

import os
import sys
import time
from datetime import datetime
from decimal import Decimal

import yaml

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from nonkyc_client.auth import ApiCredentials, AuthSigner
from nonkyc_client.models import OrderRequest
from nonkyc_client.rest import RestClient, RestRequest
from strategies.infinity_grid import generate_symmetric_grid, summarize_grid
from utils.notional import (
    min_quantity_from_notional,
    resolve_quantity_rounding,
    should_skip_notional,
)


def load_config(config_file):
    """Load configuration from YAML file."""
    with open(config_file, "r") as f:
        return yaml.safe_load(f)


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


def get_current_price(client, pair):
    """Fetch current market price."""
    try:
        ticker = client.get_market_data(pair)
        price = Decimal(ticker.last_price)
        return price
    except Exception as e:
        print(f"ERROR fetching price for {pair}: {e}")
        return None


def create_grid_orders(client, config, mid_price):
    """Create grid orders based on configuration."""
    print(f"\n📊 Creating Grid Orders")
    print(f"Mid Price: {mid_price}")

    levels = int(config["grid_levels"])
    spread = Decimal(str(config["grid_spread"]))
    order_size = Decimal(str(config["order_amount"]))
    fee_rate = Decimal(str(config.get("fee_rate", "0")))
    min_notional = Decimal(str(config.get("min_notional_usd", "1.0")))
    step_size, precision = resolve_quantity_rounding(config)

    # Generate grid levels
    grid = generate_symmetric_grid(
        mid_price=mid_price, levels=levels, step_pct=spread, order_size=order_size
    )

    print(f"\nGrid Summary:")
    summary = summarize_grid(grid)
    print(f"  Total buy orders: {len([g for g in grid if g.side == 'buy'])}")
    print(f"  Total sell orders: {len([g for g in grid if g.side == 'sell'])}")
    print(f"  Total buy amount: {summary['buy']}")
    print(f"  Total sell amount: {summary['sell']}")

    # Place orders
    placed_orders = []
    user_provided_id = config.get("userProvidedId") or config.get("user_provided_id")
    strict_validate = (
        config["strictValidate"]
        if "strictValidate" in config
        else config.get("strict_validate")
    )
    order_type = config.get("order_type", "limit")
    for level in grid:
        try:
            min_qty = min_quantity_from_notional(
                price=mid_price,
                min_notional=min_notional,
                fee_rate=fee_rate,
                step_size=step_size,
                precision=precision,
            )
            quantity = max(level.amount, min_qty)
            print(f"\n  Placing {level.side} order: {quantity} @ {level.price}")

            price_for_notional = level.price if order_type == "limit" else mid_price
            if should_skip_notional(
                config=config,
                symbol=config["trading_pair"],
                side=level.side,
                quantity=quantity,
                price=price_for_notional,
                order_type=order_type,
            ):
                continue

            order = OrderRequest(
                symbol=config["trading_pair"],
                side=level.side,
                order_type=order_type,
                quantity=str(quantity),
                price=str(level.price),
                user_provided_id=user_provided_id,
                strict_validate=strict_validate,
            )

            response = client.place_order(order)
            print(f"    ✓ Order ID: {response.order_id}, Status: {response.status}")
            placed_orders.append(
                {
                    "id": response.order_id,
                    "side": level.side,
                    "price": level.price,
                    "amount": quantity,
                }
            )

            time.sleep(0.5)  # Brief pause between orders

        except Exception as e:
            print(f"    ✗ Error placing order: {e}")

    return placed_orders


def cancel_all_orders(client, config):
    """Cancel all open orders for the trading pair."""
    print(f"\n🗑️  Cancelling all open orders...")
    try:
        # This uses the cancelallorders endpoint
        response = client.send(
            RestRequest(
                method="POST",
                path="/api/v2/cancelallorders",
                body={"symbol": config["trading_pair"]},
            )
        )
        print(f"  ✓ Cancelled all orders")
        return True
    except Exception as e:
        print(f"  ✗ Error cancelling orders: {e}")
        return False


def run_grid_bot(config_file):
    """Main grid bot loop."""
    print("=" * 80)
    print("Grid Trading Bot")
    print("=" * 80)

    # Load config
    config = load_config(config_file)
    print(f"\n📋 Configuration:")
    print(f"  Trading Pair: {config['trading_pair']}")
    print(f"  Grid Levels: {config['grid_levels']}")
    print(f"  Grid Spread: {float(config['grid_spread'])*100}%")
    print(f"  Order Amount: {config['order_amount']}")
    print(f"  Refresh Time: {config['refresh_time']}s")

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

            # Get current price
            print(f"\n📈 Fetching current price for {config['trading_pair']}...")
            mid_price = get_current_price(client, config["trading_pair"])

            if mid_price is None:
                print("⚠️  Failed to fetch price, skipping cycle")
                time.sleep(config["refresh_time"])
                continue

            # Cancel existing orders
            cancel_all_orders(client, config)
            time.sleep(2)

            # Create new grid
            orders = create_grid_orders(client, config, mid_price)

            print(f"\n✅ Grid active with {len(orders)} orders")
            print(f"⏰ Waiting {config['refresh_time']} seconds before refresh...")

            time.sleep(config["refresh_time"])

    except KeyboardInterrupt:
        print("\n\n🛑 Bot stopped by user")
        print(f"Total cycles run: {cycle_count}")

        # Cancel all orders before exiting
        print("\nCleaning up...")
        cancel_all_orders(client, config)

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_grid_bot.py <config_file>")
        print("Example: python run_grid_bot.py cosa_pirate_grid.yml")
        sys.exit(1)

    config_file = sys.argv[1]

    if not os.path.exists(config_file):
        print(f"Error: Config file '{config_file}' not found!")
        sys.exit(1)

    run_grid_bot(config_file)
