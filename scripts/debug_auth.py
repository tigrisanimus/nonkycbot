#!/usr/bin/env python3
"""
Debug authentication by testing different signing variations
"""

import hashlib
import hmac
import os
import sys
import time


def sign(api_secret: str, message: str) -> str:
    """Generate HMAC-SHA256 signature"""
    return hmac.new(
        api_secret.encode("utf8"),
        message.encode("utf8"),
        hashlib.sha256,
    ).hexdigest()


def test_signature_variant(
    api_key: str, api_secret: str, variant_name: str, url_part: str, nonce: int
):
    """Test a specific signature variant"""
    print(f"\n{'='*80}")
    print(f"Variant: {variant_name}")
    print(f"{'='*80}")

    # Build the message to sign
    message = f"{api_key}{url_part}{nonce}"

    print(f"URL part: {url_part}")
    print(f"Nonce: {nonce} ({len(str(nonce))} digits)")
    print(f"Message format: <api_key> + {url_part} + {nonce}")
    print(f"Message length: {len(message)} chars")

    # Generate signature
    signature = sign(api_secret, message)
    print(f"Signature: {signature[:16]}... (showing first 16 chars)")

    # Build headers
    headers = {
        "X-API-KEY": api_key,
        "X-API-NONCE": str(nonce),
        "X-API-SIGN": signature,
    }

    # Try the request
    try:
        import urllib.request

        full_url = "https://api.nonkyc.io/api/v2/balances"
        req = urllib.request.Request(full_url, headers=headers)

        print(f"\nTesting request to: {full_url}")
        with urllib.request.urlopen(req, timeout=10) as response:
            data = response.read().decode("utf8")
            print(f"✅ SUCCESS! Status: {response.status}")
            print(f"Response: {data[:200]}...")
            return True
    except urllib.error.HTTPError as e:
        print(f"❌ FAILED: HTTP {e.code} - {e.reason}")
        if e.code == 401:
            body = e.read().decode("utf8") if e.fp else ""
            print(f"Response: {body}")
    except Exception as e:
        print(f"❌ ERROR: {e}")

    return False


def main():
    print("\n" + "=" * 80)
    print("NonKYC Authentication Debug Tool")
    print("=" * 80)

    # Get credentials
    api_key = os.getenv("NONKYC_API_KEY")
    api_secret = os.getenv("NONKYC_API_SECRET")

    if not api_key or not api_secret:
        print("\n❌ Missing credentials. Set NONKYC_API_KEY and NONKYC_API_SECRET")
        if len(sys.argv) == 3:
            api_key = sys.argv[1]
            api_secret = sys.argv[2]
            print("✓ Using credentials from command line")
        else:
            print("\nUsage:")
            print("  export NONKYC_API_KEY='your_key'")
            print("  export NONKYC_API_SECRET='your_secret'")
            print("  python scripts/debug_auth.py")
            return 1

    print(f"\nAPI Key: {api_key[:8]}... ({len(api_key)} chars)")
    print(f"API Secret: {api_secret[:8]}... ({len(api_secret)} chars)")

    # Generate nonce with 1e3 multiplier (13 digits)
    nonce_13 = int(time.time() * 1000)
    # Generate nonce with 1e4 multiplier (14 digits)
    nonce_14 = int(time.time() * 10000)

    print("\nGenerated nonces:")
    print(f"  1e3 multiplier: {nonce_13} ({len(str(nonce_13))} digits)")
    print(f"  1e4 multiplier: {nonce_14} ({len(str(nonce_14))} digits)")

    # Test different variations
    variants = [
        ("Path only + 13 digit nonce", "/balances", nonce_13),
        ("Path with /api/v2 + 13 digit nonce", "/api/v2/balances", nonce_13),
        (
            "Full URL + 13 digit nonce",
            "https://api.nonkyc.io/api/v2/balances",
            nonce_13,
        ),
        ("Path only + 14 digit nonce", "/balances", nonce_14),
        (
            "Full URL + 14 digit nonce",
            "https://api.nonkyc.io/api/v2/balances",
            nonce_14,
        ),
    ]

    success = False
    for variant_name, url_part, nonce in variants:
        if test_signature_variant(api_key, api_secret, variant_name, url_part, nonce):
            success = True
            print(f"\n{'='*80}")
            print("✅ WORKING CONFIGURATION FOUND!")
            print(f"{'='*80}")
            print(f"Variant: {variant_name}")
            print(f"URL part to sign: {url_part}")
            print(f"Nonce multiplier: {'1e3' if nonce == nonce_13 else '1e4'}")
            break

        # Small delay between attempts
        time.sleep(0.5)

    if not success:
        print(f"\n{'='*80}")
        print("❌ ALL VARIANTS FAILED")
        print(f"{'='*80}")
        print("\nPossible issues:")
        print("  1. API credentials are incorrect or revoked")
        print("  2. IP address not whitelisted")
        print("  3. API key doesn't have permissions for /balances")
        print("  4. Account issue on NonKYC side")
        print("\nNext steps:")
        print("  1. Verify credentials on NonKYC website")
        print("  2. Check IP whitelist settings")
        print("  3. Regenerate API key if needed")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
