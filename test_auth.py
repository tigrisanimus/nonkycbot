#!/usr/bin/env python3
"""
Quick authentication test for nonkyc.io API
Tests both public and authenticated endpoints
"""

import hashlib
import hmac
import os
import sys
import time

import requests


def test_public_endpoint():
    """Test a public endpoint to verify API connectivity."""
    print("=" * 60)
    print("STEP 1: Testing Public API Endpoint")
    print("=" * 60)

    base_url = "https://api.nonkyc.io/api/v2"
    endpoint = "/markets"
    # Fix: Use string concatenation instead of urljoin to preserve base_url path
    url = base_url.rstrip("/") + "/" + endpoint.lstrip("/")

    print(f"URL: {url}")

    try:
        response = requests.get(url, timeout=10)
        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print(
                f"✅ SUCCESS - Received {len(data) if isinstance(data, list) else 'data'} markets"
            )
            return True
        else:
            print(f"❌ FAILED - {response.text}")
            return False
    except Exception as e:
        print(f"❌ ERROR - {e}")
        return False


def test_authenticated_endpoint(api_key: str, api_secret: str):
    """Test an authenticated endpoint to verify credentials and nonce."""
    print("\n" + "=" * 60)
    print("STEP 2: Testing Authenticated Endpoint (/balances)")
    print("=" * 60)

    base_url = "https://api.nonkyc.io/api/v2"
    endpoint = "/balances"
    # Fix: Use string concatenation instead of urljoin to preserve base_url path
    full_url = base_url.rstrip("/") + "/" + endpoint.lstrip("/")

    # Generate nonce (milliseconds since epoch)
    # CRITICAL: Using 1e3 (1000) to convert seconds to milliseconds
    nonce = str(int(time.time() * 1000))  # This should be 13 digits

    # Security: Don't log actual API credentials
    print(f"API Key: [REDACTED] ({len(api_key)} chars)")
    print(f"Nonce: {nonce} ({len(nonce)} digits)")

    if len(nonce) != 13:
        print(f"⚠️  WARNING: Nonce should be 13 digits, got {len(nonce)}")

    # Build signature
    # message = api_key + url + body + nonce
    body = ""  # GET request has no body
    message = api_key + full_url + body + nonce

    print("\nAuthentication Details:")
    print(f"  URL: {full_url}")
    print(f"  Message format: <api_key> + {full_url} + <empty_body> + {nonce}")
    print(f"  Message length: {len(message)} chars")

    # Note: HMAC-SHA256 is the CORRECT algorithm for API request signing (not password hashing)
    # This is required by the nonkyc.io API specification for request authentication
    # lgtm[py/weak-cryptographic-algorithm]  # False positive: This is HMAC for API auth, not password hashing
    signature = hmac.new(
        api_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    # Security: Don't log actual signature (derived from secret)
    print(f"  Signature: [REDACTED] ({len(signature)} chars)")

    # Make request
    headers = {
        "X-API-KEY": api_key,
        "X-API-NONCE": nonce,
        "X-API-SIGN": signature,
        "Content-Type": "application/json",
    }

    # Security: Only log non-sensitive headers explicitly
    print("\nHeaders:")
    print(f"  X-API-KEY: [REDACTED] ({len(api_key)} chars)")
    # lgtm[py/clear-text-logging-sensitive-data]  # False positive: Nonce is a public timestamp, not secret
    print(f"  X-API-NONCE: {nonce}")  # Nonce is not secret (public timestamp)
    print(f"  X-API-SIGN: [REDACTED] ({len(signature)} chars)")
    print("  Content-Type: application/json")

    try:
        # Note: We must send credentials over HTTPS to authenticate - this is intentional
        # lgtm[py/clear-text-logging-sensitive-data]  # False positive: This is an API auth request, not logging
        response = requests.get(full_url, headers=headers, timeout=10)
        print(f"\nResponse Status: {response.status_code}")

        if response.status_code == 200:
            balances = response.json()
            print("✅ SUCCESS - Authentication working!")
            print(f"\nBalances received: {len(balances)} assets")

            # Show first few balances
            for i, bal in enumerate(balances[:5]):
                asset = bal.get("asset", "N/A")
                available = bal.get("available", "0")
                print(f"  {asset}: {available}")

            if len(balances) > 5:
                print(f"  ... and {len(balances) - 5} more")

            return True
        elif response.status_code == 401:
            print("❌ AUTHENTICATION FAILED - 401 Unauthorized")
            print(f"\nResponse: {response.text}")
            print("\nPossible issues:")
            print("  1. Wrong API key or secret")
            print("  2. Nonce issue (check digit count)")
            print("  3. Signature calculation mismatch")
            return False
        else:
            print(f"❌ FAILED - {response.status_code}")
            print(f"Response: {response.text}")
            return False

    except Exception as e:
        print(f"❌ ERROR - {e}")
        return False


def main():
    print("\n" + "=" * 60)
    print("NonKYC.io API Authentication Test")
    print("=" * 60 + "\n")

    # Step 1: Test public endpoint
    if not test_public_endpoint():
        print("\n⚠️  Public API test failed. Check your internet connection.")
        return 1

    # Step 2: Get credentials
    api_key = os.getenv("NONKYC_API_KEY")
    api_secret = os.getenv("NONKYC_API_SECRET")

    if not api_key or not api_secret:
        print("\n" + "=" * 60)
        print("STEP 2: Credentials Not Found")
        print("=" * 60)
        print("\n❌ No credentials found in environment variables.")
        print("\nTo test authentication, set your credentials:")
        print("  export NONKYC_API_KEY='your_key_here'")
        print("  export NONKYC_API_SECRET='your_secret_here'")
        print("  python test_auth.py")
        print("\nAlternatively, pass them as arguments:")
        print("  python test_auth.py YOUR_API_KEY YOUR_API_SECRET")

        if len(sys.argv) == 3:
            api_key = sys.argv[1]
            api_secret = sys.argv[2]
            print("\n✓ Using credentials from command line arguments")
        else:
            return 0
    else:
        print("\n✓ Found credentials in environment variables")

    # Step 3: Test authenticated endpoint
    success = test_authenticated_endpoint(api_key, api_secret)

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    if success:
        print("✅ All tests passed!")
        print("\nYour authentication is working correctly.")
        print("The nonce fix (1e3 multiplier) is working as expected.")
        return 0
    else:
        print("❌ Authentication test failed")
        print("\nPlease verify:")
        print("  1. Your API key and secret are correct")
        print("  2. Your API key has the necessary permissions")
        print("  3. Check the nonce value (should be 13 digits)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
