"""Credential loading helpers for NonKYC Bot."""

from __future__ import annotations

import os
import re
from typing import Mapping

import keyring
from keyring.errors import KeyringError

from nonkyc_client.auth import ApiCredentials

DEFAULT_SERVICE_NAME = "nonkyc-bot"
DEFAULT_API_KEY_ENV = "NONKYC_API_KEY"
DEFAULT_API_SECRET_ENV = "NONKYC_API_SECRET"
DEFAULT_API_KEY_USERNAME = "api_key"
DEFAULT_API_SECRET_USERNAME = "api_secret"
_ENV_PATTERN = re.compile(r"^\$\{([A-Z0-9_]+)\}$")


def load_api_credentials(
    service_name: str,
    config: Mapping[str, object] | None = None,
    *,
    api_key_env: str = DEFAULT_API_KEY_ENV,
    api_secret_env: str = DEFAULT_API_SECRET_ENV,
    api_key_username: str = DEFAULT_API_KEY_USERNAME,
    api_secret_username: str = DEFAULT_API_SECRET_USERNAME,
) -> ApiCredentials:
    """Load API credentials from config, env vars, or keyring in order."""
    api_key = _resolve_value(config, "api_key")
    api_secret = _resolve_value(config, "api_secret")

    if not api_key:
        api_key = _clean_value(os.getenv(api_key_env))
    if not api_secret:
        api_secret = _clean_value(os.getenv(api_secret_env))

    if not api_key:
        api_key = _get_keyring_value(service_name, api_key_username)
    if not api_secret:
        api_secret = _get_keyring_value(service_name, api_secret_username)

    if not api_key or not api_secret:
        raise ValueError(
            "API credentials are missing. Provide api_key/api_secret in the config, "
            f"set {api_key_env}/{api_secret_env}, or store them in the keychain "
            f"for service '{service_name}'."
        )

    return ApiCredentials(api_key=api_key, api_secret=api_secret)


def store_api_credentials(
    service_name: str,
    api_key: str,
    api_secret: str,
    *,
    api_key_username: str = DEFAULT_API_KEY_USERNAME,
    api_secret_username: str = DEFAULT_API_SECRET_USERNAME,
) -> None:
    """Store API credentials in the OS keychain via keyring."""
    api_key_value = _clean_value(api_key)
    api_secret_value = _clean_value(api_secret)
    if not api_key_value or not api_secret_value:
        raise ValueError("api_key and api_secret must be non-empty strings.")
    try:
        keyring.set_password(service_name, api_key_username, api_key_value)
        keyring.set_password(service_name, api_secret_username, api_secret_value)
    except KeyringError as exc:
        raise RuntimeError(
            "Failed to store credentials in the OS keychain. "
            "Ensure a keyring backend is available."
        ) from exc


def _resolve_value(config: Mapping[str, object] | None, key: str) -> str | None:
    if not config or key not in config:
        return None
    raw = config.get(key)
    if not isinstance(raw, str):
        return _clean_value(str(raw)) if raw is not None else None
    raw = raw.strip()
    if not raw:
        return None
    match = _ENV_PATTERN.match(raw)
    if match:
        return _clean_value(os.getenv(match.group(1)))
    return _clean_value(raw)


def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    return candidate or None


def _get_keyring_value(service_name: str, username: str) -> str | None:
    try:
        return _clean_value(keyring.get_password(service_name, username))
    except KeyringError as exc:
        raise RuntimeError(
            "Failed to access the OS keychain. "
            "Ensure a keyring backend is available."
        ) from exc
