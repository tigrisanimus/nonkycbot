#!/usr/bin/env python3
"""Quick test to find the correct symbol format for COSA/PIRATE on NonKYC."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from nonkyc_client.auth import ApiCredentials
from nonkyc_client.rest import RestClient

# Get credentials
api_key = os.getenv("NONKYC_API_KEY", "your_key")
api_secret = os.getenv("NONKYC_API_SECRET", "your_secret")

credentials = ApiCredentials(api_key=api_key, api_secret=api_secret)
client = RestClient("https://nonkyc.io", credentials=credentials)

# Different symbol formats to test
test_formats = [
    # Slash separator
    "COSA/USDT", "COSA/BTC", "PIRATE/USDT", "PIRATE/BTC",
    # Dash separator
    "COSA-USDT", "COSA-BTC", "PIRATE-USDT", "PIRATE-BTC",
    # Underscore separator
    "COSA_USDT", "COSA_BTC", "PIRATE_USDT", "PIRATE_BTC",
    # No separator
    "COSAUSDT", "COSABTC", "PIRATEUSDT", "PIRATEBTC",
    # Lowercase
    "cosa/usdt", "cosa/btc", "pirate/usdt", "pirate/btc",
    "cosa-usdt", "cosa-btc", "pirate-usdt", "pirate-btc",
]

print("=" * 80)
print("Testing Symbol Formats for COSA and PIRATE")
print("=" * 80)

working_symbols = []

for symbol in test_formats:
    try:
        ticker = client.get_market_data(symbol)
        print(f"✅ WORKS: {symbol:<20} | Last: {ticker.last_price}")
        working_symbols.append(symbol)
    except Exception as e:
        error_msg = str(e)[:50]
        print(f"❌ FAILS: {symbol:<20} | {error_msg}")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

if working_symbols:
    print(f"\n✅ Found {len(working_symbols)} working symbols:\n")
    for symbol in working_symbols:
        print(f"  • {symbol}")

    print("\n💡 Update your config file with these symbols:")
    print("\norderbook_pairs:")
    for symbol in working_symbols:
        print(f'  - "{symbol}"')
else:
    print("\n❌ No working symbol formats found!")
    print("\nPossible issues:")
    print("  1. COSA/PIRATE tokens don't exist on NonKYC")
    print("  2. Different token names (check NonKYC website)")
    print("  3. API authentication issue")
    print("  4. Different base URL needed")

print("\n" + "=" * 80)
