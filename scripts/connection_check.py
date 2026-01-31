#!/usr/bin/env python
"""Test script to verify NonKYC API connection and authentication."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nonkyc_client.auth import AuthSigner

# Add src to path so we can import the modules
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

# Replace with your actual API credentials
API_KEY = "your_api_key_here"
API_SECRET = "your_api_secret_here"

# Optional signer overrides (set to None to use environment or defaults)
SIGNER_NONCE_MULTIPLIER = None
SIGNER_SORT_PARAMS = None
SIGNER_SORT_BODY = None
SIGN_ABSOLUTE_URL = True  # NonKYC requires full URL signing

DEFAULT_NONCE_MULTIPLIER = 1e4  # 14 digits (required by NonKYC)
DEFAULT_SORT_PARAMS = False
DEFAULT_SORT_BODY = False


def _parse_bool(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _resolve_float(
    env_name: str,
    default: float,
    override: float | None,
    warnings: list[str],
) -> float:
    if override is not None:
        return override
    raw = os.getenv(env_name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        warnings.append(f"{env_name}={raw!r} (invalid float, using {default})")
        return default


def _resolve_bool(
    env_name: str,
    default: bool,
    override: bool | None,
    warnings: list[str],
) -> bool:
    if override is not None:
        return override
    raw = os.getenv(env_name)
    if raw is None:
        return default
    parsed = _parse_bool(raw)
    if parsed is None:
        warnings.append(f"{env_name}={raw!r} (invalid bool, using {default})")
        return default
    return parsed


def _resolve_signer_settings() -> tuple[AuthSigner, float, bool, bool, bool, list[str]]:
    from nonkyc_client.auth import AuthSigner

    warnings: list[str] = []
    nonce_multiplier = _resolve_float(
        "NONKYC_NONCE_MULTIPLIER",
        DEFAULT_NONCE_MULTIPLIER,
        SIGNER_NONCE_MULTIPLIER,
        warnings,
    )
    sort_params = _resolve_bool(
        "NONKYC_SORT_PARAMS",
        DEFAULT_SORT_PARAMS,
        SIGNER_SORT_PARAMS,
        warnings,
    )
    sort_body = _resolve_bool(
        "NONKYC_SORT_BODY",
        DEFAULT_SORT_BODY,
        SIGNER_SORT_BODY,
        warnings,
    )
    sign_absolute_url = _resolve_bool(
        "NONKYC_SIGN_FULL_URL",
        False,
        SIGN_ABSOLUTE_URL,
        warnings,
    )
    signer = AuthSigner(
        nonce_multiplier=nonce_multiplier,
        sort_params=sort_params,
        sort_body=sort_body,
    )
    return signer, nonce_multiplier, sort_params, sort_body, sign_absolute_url, warnings


def test_connection():
    """Test the nonkyc.io API connection."""
    from nonkyc_client.auth import ApiCredentials
    from nonkyc_client.rest import RestClient

    print("=" * 60)
    print("nonkyc bot - Connection Test")
    print("=" * 60)

    # Create credentials
    creds = ApiCredentials(api_key=API_KEY, api_secret=API_SECRET)

    (
        signer,
        nonce_multiplier,
        sort_params,
        sort_body,
        sign_absolute_url,
        warnings,
    ) = _resolve_signer_settings()

    # Create REST client
    client = RestClient(
        base_url="https://api.nonkyc.io/api/v2",  # Correct base URL with /api/v2
        credentials=creds,
        signer=signer,
        timeout=10.0,
        sign_absolute_url=sign_absolute_url,
    )

    print("\n✓ Client initialized")
    print(f"  Base URL: {client.base_url}")
    print(f"  Timeout: {client.timeout}s")
    print(f"  Max retries: {client.max_retries}")
    print("  Signer settings:")
    print(f"    NONKYC_NONCE_MULTIPLIER: {nonce_multiplier}")
    print(f"    NONKYC_SORT_PARAMS: {sort_params}")
    print(f"    NONKYC_SORT_BODY: {sort_body}")
    print(f"    NONKYC_SIGN_FULL_URL: {sign_absolute_url}")
    if warnings:
        print("  Signer warnings:")
        for warning in warnings:
            print(f"    - {warning}")

    # Test 1: Get balances
    print("\n" + "-" * 60)
    print("Test 1: Fetching account balances...")
    print("-" * 60)

    try:
        balances = client.get_balances()
        print(f"✓ Success! Retrieved {len(balances)} balance(s)")
        for balance in balances:
            print(
                f"  {balance.asset}: Available={balance.available}, Held={balance.held}"
            )
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")

    # Test 2: Get market data (example with BTC/USDT)
    print("\n" + "-" * 60)
    print("Test 2: Fetching market data (BTC/USDT)...")
    print("-" * 60)

    try:
        ticker = client.get_market_data("BTC/USDT")
        print("✓ Success! Market data retrieved")
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
        print("   Edit scripts/connection_check.py and replace:")
        print("   - API_KEY = 'your_api_key_here'")
        print("   - API_SECRET = 'your_api_secret_here'")
        print("\n   Then run: python scripts/connection_check.py")
        sys.exit(1)

    test_connection()
