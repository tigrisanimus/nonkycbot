"""
Centralized REST client factory - SINGLE SOURCE OF TRUTH for API/authentication.

ALL bots MUST use this factory to create REST clients. This ensures:
- Consistent authentication across all bots
- Single place to fix authentication issues
- No duplicate/inconsistent implementations
"""

from __future__ import annotations

from typing import Any

from nonkyc_client.auth import AuthSigner
from nonkyc_client.constants import default_rest_base_url
from nonkyc_client.rest import RestClient
from nonkyc_client.rest_exchange import NonkycRestExchangeClient
from utils.credentials import DEFAULT_SERVICE_NAME, load_api_credentials


def build_rest_client(config: dict[str, Any]) -> RestClient:
    """
    Build REST client from config - SINGLE SOURCE OF TRUTH.

    This function is used by ALL bots to ensure consistent authentication.

    Args:
        config: Configuration dict containing:
            - sign_requests: bool (default: True) - Enable signing
            - base_url: str (default: "https://api.nonkyc.io/api/v2")
            - nonce_multiplier: float (default: 1e4) - 14-digit nonce (REQUIRED)
            - sign_absolute_url: bool (default: True) - Sign full URL (REQUIRED)
            - sort_params: bool (default: False) - Sort query params
            - sort_body: bool (default: False) - Sort body params
            - rest_timeout_sec: float (default: 10.0) - Request timeout
            - rest_retries: int (default: 3) - Max retries
            - rest_backoff_factor: float (default: 0.5) - Backoff multiplier
            - use_server_time: bool (optional) - Use server time for nonce
            - debug_auth: bool (optional) - Debug authentication

    Returns:
        RestClient: Configured REST client with proper authentication

    Example:
        >>> config = {
        ...     "base_url": "https://api.nonkyc.io/api/v2",
        ...     "nonce_multiplier": 1e4,
        ...     "sign_absolute_url": True,
        ... }
        >>> client = build_rest_client(config)
    """
    # Authentication settings
    signing_enabled = config.get("sign_requests", True)

    # API endpoint
    base_url = config.get("base_url", default_rest_base_url())

    # CRITICAL: NonKYC requires these exact settings
    # DO NOT CHANGE without testing with debug_auth.py first!
    nonce_multiplier = config.get("nonce_multiplier", 1e4)  # 14 digits
    sign_absolute_url = config.get("sign_absolute_url", True)  # Full URL signing
    sort_params = config.get("sort_params", False)
    sort_body = config.get("sort_body", False)

    # Timeouts and retries
    rest_timeout = config.get("rest_timeout_sec", 10.0)
    rest_retries = config.get("rest_retries", 3)
    rest_backoff = config.get("rest_backoff_factor", 0.5)

    # Optional settings
    use_server_time = config.get("use_server_time")
    debug_auth = config.get("debug_auth")

    # Load credentials
    creds = (
        load_api_credentials(DEFAULT_SERVICE_NAME, config) if signing_enabled else None
    )

    # Create signer
    signer = (
        AuthSigner(
            nonce_multiplier=nonce_multiplier,
            sort_params=sort_params,
            sort_body=sort_body,
        )
        if signing_enabled
        else None
    )

    # Create REST client
    return RestClient(
        base_url=base_url,
        credentials=creds,
        signer=signer,
        use_server_time=use_server_time,
        timeout=float(rest_timeout),
        max_retries=int(rest_retries),
        backoff_factor=float(rest_backoff),
        sign_absolute_url=sign_absolute_url,
        debug_auth=debug_auth,
    )


def build_exchange_client(config: dict[str, Any]) -> NonkycRestExchangeClient:
    """
    Build exchange client from config - wraps REST client with exchange-specific logic.

    This is the most convenient function for bots to use.

    Args:
        config: Same as build_rest_client()

    Returns:
        NonkycRestExchangeClient: Exchange client wrapping REST client

    Example:
        >>> config = {"base_url": "https://api.nonkyc.io/api/v2"}
        >>> client = build_exchange_client(config)
        >>> balances = client.get_balances()
    """
    rest_client = build_rest_client(config)
    return NonkycRestExchangeClient(rest_client)
