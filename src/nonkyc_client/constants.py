"""Shared API constants aligned with the Hummingbot NonKYC connector."""

# Reference: HUMMINGBOT_API_REFERENCE_CODE/nonkyc_constants.py

REST_URL = "https://api.nonkyc.io/api"
API_VERSION = "v2"
WS_URL = "wss://api.nonkyc.io"
SERVER_TIME_URL = "https://nonkyc.io/api/v2/getservertime"


def default_rest_base_url() -> str:
    """Return the default REST base URL including the API version."""
    return f"{REST_URL}/{API_VERSION}"
