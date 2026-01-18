#!/usr/bin/env python
"""Debug script to check trading pair formats and API responses"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from nonkyc_client.rest import RestClient
from nonkyc_client.auth import ApiCredentials

# Add your credentials here
API_KEY = "your_api_key_here"
API_SECRET = "your_api_secret_here"

def check_pair(pair_name):
    """Check what data we get for a trading pair."""
    print(f"\n{'=' * 60}")
    print(f"Checking: {pair_name}")
    print('=' * 60)

    creds = ApiCredentials(api_key=API_KEY, api_secret=API_SECRET)
    client = RestClient(base_url="https://api.nonkyc.io", credentials=creds)

    try:
        ticker = client.get_market_data(pair_name)
        print(f"✓ Successfully fetched data")
        print(f"\nRaw response:")
        print(f"  raw_payload: {ticker.raw_payload}")
        print(f"\nParsed data:")
        print(f"  symbol: {ticker.symbol}")
        print(f"  last_price: '{ticker.last_price}' (type: {type(ticker.last_price)})")
        print(f"  bid: {ticker.bid}")
        print(f"  ask: {ticker.ask}")
        print(f"  volume: {ticker.volume}")

        # Try to convert to decimal
        if ticker.last_price:
            from decimal import Decimal
            try:
                price = Decimal(ticker.last_price)
                print(f"\n✓ Decimal conversion: {price}")
            except Exception as e:
                print(f"\n✗ Decimal conversion failed: {e}")
                print(f"  String value: '{ticker.last_price}'")
                print(f"  String length: {len(ticker.last_price)}")
                print(f"  String repr: {repr(ticker.last_price)}")
        else:
            print(f"\n✗ last_price is empty or None!")

    except Exception as e:
        print(f"✗ Error fetching data: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("NonKYC Trading Pair Debug Tool")
    print("=" * 60)

    if API_KEY == "your_api_key_here":
        print("\n⚠️  Please edit this file and add your API credentials!")
        sys.exit(1)

    # Test MMX-USDT with different formats
    pairs_to_test = [
        "MMX-USDT",      # Hyphen format
        "MMX/USDT",      # Slash format
        "USDT-MMX",      # Reversed with hyphen
        "USDT/MMX",      # Reversed with slash
        "MMX_USDT",      # Underscore format
        "MMXUSDT",       # No separator
    ]

    for pair in pairs_to_test:
        check_pair(pair)

    print("\n" + "=" * 60)
    print("Debug complete!")
