#!/usr/bin/env python3
"""Store NonKYC API credentials in the OS keychain."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from utils.credentials import (  # noqa: E402
    DEFAULT_API_KEY_ENV,
    DEFAULT_API_SECRET_ENV,
    DEFAULT_SERVICE_NAME,
    store_api_credentials,
)


def build_parser() -> argparse.ArgumentParser:
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
