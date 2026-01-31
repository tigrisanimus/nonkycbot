#!/usr/bin/env python3
"""Store NonKYC API credentials in the OS keychain."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def build_parser() -> argparse.ArgumentParser:
    from utils.credentials import (
        DEFAULT_API_KEY_ENV,
        DEFAULT_API_SECRET_ENV,
        DEFAULT_SERVICE_NAME,
    )

    parser = argparse.ArgumentParser(
        description="Store NonKYC API credentials in the OS keychain."
    )
    parser.add_argument(
        "--service-name",
        default=DEFAULT_SERVICE_NAME,
        help=f"Keyring service name (default: {DEFAULT_SERVICE_NAME}).",
    )
    parser.add_argument(
        "--api-key",
        help=f"API key (defaults to ${DEFAULT_API_KEY_ENV} or prompt).",
    )
    parser.add_argument(
        "--api-secret",
        help=f"API secret (defaults to ${DEFAULT_API_SECRET_ENV} or prompt).",
    )
    return parser


def main() -> int:
    from utils.credentials import (
        DEFAULT_API_KEY_ENV,
        DEFAULT_API_SECRET_ENV,
        store_api_credentials,
    )

    parser = build_parser()
    args = parser.parse_args()
    api_key = args.api_key or os.getenv(DEFAULT_API_KEY_ENV)
    api_secret = args.api_secret or os.getenv(DEFAULT_API_SECRET_ENV)

    if not api_key:
        api_key = getpass.getpass("Enter NonKYC API key: ")
    if not api_secret:
        api_secret = getpass.getpass("Enter NonKYC API secret: ")

    store_api_credentials(args.service_name, api_key, api_secret)
    print(
        f"✅ Stored credentials in keychain for service '{args.service_name}'.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
