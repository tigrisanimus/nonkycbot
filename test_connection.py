#!/usr/bin/env python
"""Test script to verify NonKYC API connection and authentication."""

import sys
import os

# Add src to path so we can import the modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from nonkyc_client.rest import RestClient
from nonkyc_client.auth import ApiCredentials

# Replace with your actual API credentials
API_KEY = "your_api_key_here"
API_SECRET = "your_api_secret_here"

def test_connection():
    """Test the NonKYC API connection."""
    print("=" * 60)
    print("NonKYC Bot - Connection Test")
    print("=" * 60)

    # Create credentials
    creds = ApiCredentials(api_key=API_KEY, api_secret=API_SECRET)

    # Create REST client
    client = RestClient(
        base_url="https://api.nonkyc.io",
        credentials=creds,
        timeout=10.0
    )

    print(f"\n✓ Client initialized")
    print(f"  Base URL: {client.base_url}")
    print(f"  Timeout: {client.timeout}s")
    print(f"  Max retries: {client.max_retries}")

    # Test 1: Get balances
    print("\n" + "-" * 60)
    print("Test 1: Fetching account balances...")
    print("-" * 60)

    try:
        balances = client.get_balances()
        print(f"✓ Success! Retrieved {len(balances)} balance(s)")
        for balance in balances:
            print(f"  {balance.asset}: Available={balance.available}, Held={balance.held}")
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")

    # Test 2: Get market data (example with BTC/USDT)
    print("\n" + "-" * 60)
    print("Test 2: Fetching market data (BTC/USDT)...")
    print("-" * 60)

    try:
        ticker = client.get_market_data("BTC/USDT")
        print(f"✓ Success! Market data retrieved")
        print(f"  Symbol: {ticker.symbol}")
        print(f"  Last Price: {ticker.last_price}")
        if ticker.bid:
            print(f"  Bid: {ticker.bid}")
        if ticker.ask:
            print(f"  Ask: {ticker.ask}")
        if ticker.volume:
            print(f"  Volume: {ticker.volume}")
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")

    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)

if __name__ == "__main__":
    if API_KEY == "your_api_key_here" or API_SECRET == "your_api_secret_here":
        print("\n⚠️  WARNING: Please edit this file and add your API credentials!")
        print("   Edit test_connection.py and replace:")
        print("   - API_KEY = 'your_api_key_here'")
        print("   - API_SECRET = 'your_api_secret_here'")
        print("\n   Then run: python test_connection.py")
        sys.exit(1)

    test_connection()
