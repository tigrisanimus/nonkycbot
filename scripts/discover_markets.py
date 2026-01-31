#!/usr/bin/env python3
"""
Discover available markets and liquidity pools on nonkyc.io exchange.

Usage:
    python discover_markets.py

This script will:
1. List all available trading pairs (order book markets)
2. List all available liquidity pools
3. Filter for COSA and PIRATE related pairs
4. Show the correct symbol format to use in configs
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nonkyc_client.rest import RestClient

# Add src to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def discover_markets(rest_client: RestClient) -> list[dict[str, Any]]:
    """Fetch all available markets from the exchange."""
    from nonkyc_client.rest import RestRequest

    endpoints = [
        "/markets",
        "/public/markets",
        "/symbols",
        "/tickers",
    ]

    print("🔍 Searching for markets endpoint...")
    for endpoint in endpoints:
        try:
            print(f"  Trying: {endpoint}")
            response = rest_client.send(RestRequest(method="GET", path=endpoint))
            payload = rest_client._extract_payload(response)

            if payload:
                print(f"  ✅ Found markets at: {endpoint}")
                return payload if isinstance(payload, list) else [payload]
        except Exception as e:
            print(f"  ❌ Failed: {e}")
            continue

    print("  ⚠️  No markets endpoint found")
    return []


def discover_pools(rest_client: RestClient) -> list[dict[str, Any]]:
    """Fetch all available liquidity pools from the exchange."""
    from nonkyc_client.rest import RestRequest

    endpoints = [
        "/pools",
        "/liquiditypools",
        "/public/pools",
        "/swap/pools",
    ]

    print("\n🔍 Searching for pools endpoint...")
    for endpoint in endpoints:
        try:
            print(f"  Trying: {endpoint}")
            response = rest_client.send(RestRequest(method="GET", path=endpoint))
            payload = rest_client._extract_payload(response)

            if payload:
                print(f"  ✅ Found pools at: {endpoint}")
                return payload if isinstance(payload, list) else [payload]
        except Exception as e:
            print(f"  ❌ Failed: {e}")
            continue

    print("  ⚠️  No pools endpoint found")
    return []


def filter_markets_by_tokens(
    markets: list[dict[str, Any]], tokens: list[str]
) -> list[dict[str, Any]]:
    """Filter markets containing specific tokens."""
    filtered = []
    for market in markets:
        symbol = market.get("symbol", market.get("id", ""))
        for token in tokens:
            if token.upper() in symbol.upper():
                filtered.append(market)
                break
    return filtered


def print_markets(markets: list[dict[str, Any]], title: str) -> None:
    """Print markets in a readable format."""
    print(f"\n{'=' * 80}")
    print(f"{title}")
    print(f"{'=' * 80}")

    if not markets:
        print("  (none found)")
        return

    print(f"  Found {len(markets)} markets:\n")

    for market in markets:
        symbol = market.get("symbol", market.get("id", "UNKNOWN"))
        market_type = market.get("type", market.get("marketType", "spot"))
        status = market.get("status", market.get("isActive", "?"))

        print(f"  • {symbol:<20} | Type: {market_type:<15} | Status: {status}")

        # Show additional details if available
        if "baseAsset" in market and "quoteAsset" in market:
            print(f"    Base: {market['baseAsset']}, Quote: {market['quoteAsset']}")
        if "minNotional" in market:
            print(f"    Min Notional: {market['minNotional']}")
        if "tickSize" in market:
            print(f"    Tick Size: {market['tickSize']}")
        if "lastPrice" in market:
            print(f"    Last Price: {market['lastPrice']}")

        print()


def print_pools(pools: list[dict[str, Any]], title: str) -> None:
    """Print liquidity pools in a readable format."""
    print(f"\n{'=' * 80}")
    print(f"{title}")
    print(f"{'=' * 80}")

    if not pools:
        print("  (none found)")
        return

    print(f"  Found {len(pools)} pools:\n")

    for pool in pools:
        symbol = pool.get("symbol", pool.get("id", "UNKNOWN"))
        status = pool.get("status", pool.get("isActive", "?"))

        print(f"  • {symbol:<20} | Status: {status}")

        # Show pool details
        if "primaryAsset" in pool:
            print(f"    Primary Asset: {pool['primaryAsset']}")
        if "secondaryAsset" in pool:
            print(f"    Secondary Asset: {pool['secondaryAsset']}")
        if "reserveA" in pool and "reserveB" in pool:
            print(f"    Reserves: {pool['reserveA']} / {pool['reserveB']}")
        if "lastPrice" in pool:
            print(f"    Last Price: {pool['lastPrice']}")
        if "feeRate" in pool:
            print(f"    Fee Rate: {pool['feeRate']}")

        print()


def main() -> None:
    """Main discovery process."""
    from nonkyc_client.auth import ApiCredentials
    from nonkyc_client.constants import default_rest_base_url
    from nonkyc_client.rest import RestClient

    print("=" * 80)
    print("NonKYC Market & Pool Discovery Tool")
    print("=" * 80)

    # Get credentials from environment
    api_key = os.getenv("NONKYC_API_KEY")
    api_secret = os.getenv("NONKYC_API_SECRET")

    if not api_key or not api_secret:
        print("\n⚠️  WARNING: No API credentials found in environment variables!")
        print("Set NONKYC_API_KEY and NONKYC_API_SECRET to access private endpoints.")
        print("Continuing with public endpoints only...\n")
        credentials = None
    else:
        credentials = ApiCredentials(api_key=api_key, api_secret=api_secret)
        print(f"\n✅ Found API credentials (key: {api_key[:8]}...)\n")

    # Create REST client
    base_url = os.getenv("NONKYC_BASE_URL", default_rest_base_url())
    rest_client = RestClient(base_url=base_url, credentials=credentials)

    print(f"🌐 Using base URL: {base_url}\n")

    # Discover all markets
    all_markets = discover_markets(rest_client)

    # Discover all pools
    all_pools = discover_pools(rest_client)

    # Print all markets
    if all_markets:
        print_markets(all_markets, "📊 ALL AVAILABLE MARKETS")

    # Print all pools
    if all_pools:
        print_pools(all_pools, "💧 ALL AVAILABLE LIQUIDITY POOLS")

    # Filter for COSA and PIRATE
    tokens_of_interest = ["COSA", "PIRATE"]
    filtered_markets = filter_markets_by_tokens(all_markets, tokens_of_interest)
    filtered_pools = filter_markets_by_tokens(all_pools, tokens_of_interest)

    if filtered_markets:
        print_markets(filtered_markets, "🎯 COSA/PIRATE RELATED MARKETS (Order Books)")

    if filtered_pools:
        print_pools(filtered_pools, "🎯 COSA/PIRATE RELATED POOLS (AMM Swaps)")

    # Generate config suggestions
    print(f"\n{'=' * 80}")
    print("💡 CONFIG FILE SUGGESTIONS")
    print(f"{'=' * 80}\n")

    if filtered_markets or filtered_pools:
        print("Based on the discovered markets, update your config file:\n")
        print("# examples/hybrid_arb.yml")
        print("orderbook_pairs:")

        orderbook_symbols = [
            m.get("symbol", m.get("id", ""))
            for m in filtered_markets
            if m.get("type", "").lower() != "liquiditypool"
        ]
        if orderbook_symbols:
            for symbol in orderbook_symbols:
                print(f'  - "{symbol}"')
        else:
            print("  # No order book pairs found")

        print("\npool_pair:")
        pool_symbols = [p.get("symbol", p.get("id", "")) for p in filtered_pools]
        if pool_symbols:
            print(f'  "{pool_symbols[0]}"  # First pool found')
            if len(pool_symbols) > 1:
                print("\n# Alternative pools available:")
                for symbol in pool_symbols[1:]:
                    print(f'#  "{symbol}"')
        else:
            print('  "COSA/PIRATE"  # No pools found - check manually')

    else:
        print("❌ No COSA or PIRATE related markets/pools found!")
        print("\nPossible reasons:")
        print("  1. Tokens don't exist on this exchange")
        print("  2. Symbol format is different (try COSA-USDT, COSAUSDT, etc.)")
        print("  3. API endpoint has changed")
        print("  4. Need authentication to see certain markets")
        print("\nTry checking nonkyc.io exchange website directly to verify symbols.")

    print(f"\n{'=' * 80}")
    print("✅ Discovery complete!")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
