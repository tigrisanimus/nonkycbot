#!/usr/bin/env python
"""MMX-USDT Grid Trading Bot with Sell-Only Mode Support"""

import os
import sys
import time
from datetime import datetime
from decimal import Decimal

import yaml

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from nonkyc_client.auth import ApiCredentials
from nonkyc_client.models import OrderRequest
from nonkyc_client.rest import RestClient, RestRequest


def load_config(config_file):
    """Load configuration from YAML file."""
    with open(config_file, "r") as f:
        return yaml.safe_load(f)


def get_current_price(client, pair):
    """Fetch current market price."""
    try:
        ticker = client.get_market_data(pair)
        price = Decimal(ticker.last_price)
        return price
    except Exception as e:
        print(f"ERROR fetching price for {pair}: {e}")
        return None


def create_balanced_grid(mid_price, levels, spread, order_amount):
    """Create balanced grid with buy and sell orders."""
    grid = []
    spread_decimal = Decimal(str(spread))
    amount = Decimal(str(order_amount))

    for i in range(1, levels + 1):
        # Sell orders above mid price
        sell_price = mid_price * (Decimal("1") + spread_decimal * i)
        grid.append({"side": "sell", "price": sell_price, "amount": amount})

        # Buy orders below mid price
        buy_price = mid_price * (Decimal("1") - spread_decimal * i)
        grid.append({"side": "buy", "price": buy_price, "amount": amount})

    return grid


def create_sell_only_grid(mid_price, levels, spread, order_amount):
    """Create sell-only grid (only orders above current price)."""
    grid = []
    spread_decimal = Decimal(str(spread))
    amount = Decimal(str(order_amount))

    for i in range(1, levels + 1):
        # Only sell orders above mid price
        sell_price = mid_price * (Decimal("1") + spread_decimal * i)
        grid.append({"side": "sell", "price": sell_price, "amount": amount})

    return grid


def place_grid_orders(client, config, mid_price):
    """Create and place grid orders."""
    print(f"\n📊 Creating Grid Orders")
    print(f"Mid Price: {mid_price}")

    levels = int(config["grid_levels"])
    spread = Decimal(str(config["grid_spread"]))
    order_amount = Decimal(str(config["order_amount_mmx"]))
    grid_type = config.get("grid_type", "balanced")

    # Generate grid
    if grid_type == "sell_only":
        print(f"Grid Type: SELL-ONLY (accumulate USDT)")
        grid = create_sell_only_grid(mid_price, levels, spread, order_amount)
    else:
        print(f"Grid Type: BALANCED (buy & sell)")
        grid = create_balanced_grid(mid_price, levels, spread, order_amount)

    print(f"\nGrid Summary:")
    buy_count = len([g for g in grid if g["side"] == "buy"])
    sell_count = len([g for g in grid if g["side"] == "sell"])
    print(f"  Buy orders: {buy_count}")
    print(f"  Sell orders: {sell_count}")
    print(f"  Total orders: {len(grid)}")

    # Place orders
    placed_orders = []
    user_provided_id = config.get("userProvidedId") or config.get("user_provided_id")
    strict_validate = (
        config["strictValidate"]
        if "strictValidate" in config
        else config.get("strict_validate")
    )
    for order_data in grid:
        try:
            print(
                f"\n  Placing {order_data['side']} order: {order_data['amount']} MMX @ {order_data['price']:.8f} USDT"
            )

            order = OrderRequest(
                symbol=config["trading_pair"],
                side=order_data["side"],
                order_type=config.get("order_type", "limit"),
                quantity=str(order_data["amount"]),
                price=str(order_data["price"]),
                user_provided_id=user_provided_id,
                strict_validate=strict_validate,
            )

            response = client.place_order(order)
            print(f"    ✓ Order ID: {response.order_id}, Status: {response.status}")
            placed_orders.append(
                {
                    "id": response.order_id,
                    "side": order_data["side"],
                    "price": order_data["price"],
                    "amount": order_data["amount"],
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


def run_mmx_grid_bot(config_file):
    """Main grid bot loop."""
    print("=" * 80)
    print("MMX-USDT Grid Trading Bot")
    print("=" * 80)

    # Load config
    config = load_config(config_file)
    grid_type = config.get("grid_type", "balanced")

    print(f"\n📋 Configuration:")
    print(f"  Trading Pair: {config['trading_pair']}")
    print(f"  Grid Type: {grid_type.upper()}")
    print(f"  Grid Levels: {config['grid_levels']}")
    print(f"  Grid Spread: {float(config['grid_spread'])*100}%")
    print(f"  Order Amount: {config['order_amount_mmx']} MMX")
    print(f"  Refresh Time: {config['refresh_time']}s")

    if grid_type == "sell_only":
        print(f"\n⚠️  SELL-ONLY MODE:")
        print(f"  - Only sell orders will be placed")
        print(f"  - You will accumulate USDT as price rises")
        print(f"  - Switch to balanced grid once you have USDT")

    # Setup client
    creds = ApiCredentials(api_key=config["api_key"], api_secret=config["api_secret"])
    client = RestClient(base_url="https://api.nonkyc.io", credentials=creds)

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
            orders = place_grid_orders(client, config, mid_price)

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
        print("Usage: python run_mmx_grid.py <config_file>")
        print("\nExamples:")
        print("  Sell-only grid:  python run_mmx_grid.py mmx_usdt_sell_grid.yml")
        print("  Balanced grid:   python run_mmx_grid.py mmx_usdt_grid.yml")
        sys.exit(1)

    config_file = sys.argv[1]

    if not os.path.exists(config_file):
        print(f"Error: Config file '{config_file}' not found!")
        sys.exit(1)

    run_mmx_grid_bot(config_file)
