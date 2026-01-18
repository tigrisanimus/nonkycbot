#!/usr/bin/env python
"""MMX-USDT Grid Trading Bot with Sell-Only Mode Support"""

import os
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
    should_skip_fee_edge,
)
from nonkyc_client.rest import RestClient
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


def _should_skip_notional(config, symbol, side, quantity, price, order_type):
    min_notional = Decimal(str(config.get("min_notional_usd", "1.0")))
    fee_rate = Decimal(str(config.get("fee_rate", "0.001")))
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


def _looks_like_auth_error_message(message: str) -> bool:
    lowered = message.lower()
    return "401" in lowered and (
        "not authorized" in lowered or "unauthorized" in lowered
    )


def _is_auth_failure_response(response: dict | None) -> bool:
    if not response:
        return False
    for key in ("status", "code", "errorcode", "error_code", "http_status"):
        value = response.get(key)
        if value is None:
            continue
        if str(value) == "401":
            return True
        if isinstance(value, str) and _looks_like_auth_error_message(value):
            return True
    for value in response.values():
        if isinstance(value, str) and _looks_like_auth_error_message(value):
            return True
    for key in ("error", "message", "errormsg", "detail", "msg"):
        value = response.get(key)
        if isinstance(value, str) and _looks_like_auth_error_message(value):
            return True
    return False


def _format_cancel_symbol(symbol: str, symbol_format: str) -> str:
    if symbol_format == "dash":
        return symbol.replace("/", "-")
    if symbol_format == "slash":
        return symbol
    if symbol_format == "underscore":
        return symbol.replace("/", "_")
    return symbol


def _next_cancel_symbol_format(current_format: str) -> str:
    formats = ["dash", "slash", "underscore"]
    if current_format not in formats:
        return "dash"
    return formats[(formats.index(current_format) + 1) % len(formats)]


def _missing_required_input_response(response: dict | str | None) -> bool:
    if not response:
        return False
    return "missing required input" in str(response).lower()


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
    fee_rate = Decimal(str(config.get("fee_rate", "0.001")))
    min_notional = Decimal(str(config.get("min_notional_usd", "1.0")))
    step_size, precision = resolve_quantity_rounding(config)

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
    order_type = config.get("order_type", "limit")
    for order_data in grid:
        try:
            min_qty = min_quantity_for_notional(
                price=mid_price,
                min_notional=min_notional,
                fee_rate=fee_rate,
            )
            min_qty = _round_quantity(min_qty, step_size, precision)
            quantity = max(order_data["amount"], min_qty)
            print(
                f"\n  Placing {order_data['side']} order: {quantity} MMX @ {order_data['price']:.8f} USDT"
            )

            if should_skip_fee_edge(
                order_data["side"], order_data["price"], mid_price, fee_rate
            ):
                continue

            price_for_notional = (
                order_data["price"] if order_type == "limit" else mid_price
            )
            if _should_skip_notional(
                config,
                config["trading_pair"],
                order_data["side"],
                quantity,
                price_for_notional,
                order_type,
            ):
                continue

            order = OrderRequest(
                symbol=config["trading_pair"],
                side=order_data["side"],
                order_type=order_type,
                quantity=str(quantity),
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
        symbol_format = config.get("cancel_symbol_format", "slash")
        cancel_side = config.get("cancel_side", "all")
        side_arg = None if cancel_side == "all" else cancel_side
        symbol_base = config["trading_pair"]
        known_formats = ["dash", "slash", "underscore"]
        if symbol_format in known_formats:
            start_index = known_formats.index(symbol_format)
            attempt_formats = (
                known_formats[start_index:] + known_formats[:start_index]
            )
        else:
            attempt_formats = [symbol_format] + [
                fmt for fmt in known_formats if fmt != symbol_format
            ]
        missing_required = False
        for attempt_index, attempt_format in enumerate(attempt_formats, start=1):
            symbol = _format_cancel_symbol(symbol_base, attempt_format)
            print(
                f"  ℹ️ Cancel attempt {attempt_index}: "
                f"format={attempt_format} symbol={symbol}"
            )
            success = client.cancel_all_orders(symbol, side_arg)
            if success:
                print("  ✓ Cancelled all orders")
                return True, False
            response = client.last_cancel_all_response
            if _is_auth_failure_response(response):
                print(
                    "  🛑 Cancel all orders failed due to auth error (401 / Not Authorized). "
                    "Stopping cycle to avoid placing orders."
                )
                return False, True
            if _missing_required_input_response(response):
                missing_required = True
                if attempt_index < len(attempt_formats):
                    fallback_format = attempt_formats[attempt_index]
                    print(
                        "  ⚠️ Cancel all orders failed with missing required input. "
                        f"Retrying with format={fallback_format}."
                    )
                    continue
            print(f"  ✗ Cancel all orders failed. Response: {response}")
            return False, False
        if missing_required:
            print(
                "  ⚠️ Cancel all orders failed with missing required input across "
                "symbol formats. Retrying without a symbol."
            )
            success = client.cancel_all_orders(None, side_arg)
            if success:
                print("  ✓ Cancelled all orders without symbol")
                return True, False
            response = client.last_cancel_all_response
            if _is_auth_failure_response(response):
                print(
                    "  🛑 Cancel all orders failed due to auth error (401 / Not Authorized). "
                    "Stopping cycle to avoid placing orders."
                )
                return False, True
            print(f"  ✗ Cancel all orders failed. Response: {response}")
            return False, False
        return False, False
    except Exception as e:
        if _looks_like_auth_error_message(str(e)):
            print(
                "  🛑 Cancel all orders failed due to auth error (401 / Not Authorized). "
                f"Stopping cycle to avoid placing orders. Error: {e}"
            )
            return False, True
        print(f"  ✗ Error cancelling orders: {e}")
        return False, False


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
    max_refresh_seconds = int(config.get("max_refresh_seconds", 1800))
    refresh_seconds = int(config["refresh_time"])
    effective_refresh_seconds = min(refresh_seconds, max_refresh_seconds)
    print(f"  Refresh Time: {refresh_seconds}s")
    print(f"  Max Refresh Time: {max_refresh_seconds}s")

    if grid_type == "sell_only":
        print(f"\n⚠️  SELL-ONLY MODE:")
        print(f"  - Only sell orders will be placed")
        print(f"  - You will accumulate USDT as price rises")
        print(f"  - Switch to balanced grid once you have USDT")

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
            _, auth_failed = cancel_all_orders(client, config)
            if auth_failed:
                print(
                    "🛑 Authorization failure detected during cancel-all. "
                    "Check API credentials/permissions and restart after fixing."
                )
                break
            time.sleep(2)

            # Create new grid
            orders = place_grid_orders(client, config, mid_price)

            print(f"\n✅ Grid active with {len(orders)} orders")
            print(f"⏰ Waiting {effective_refresh_seconds} seconds before refresh...")

            time.sleep(effective_refresh_seconds)

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
