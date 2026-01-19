"""Timestamp parsing utilities for NonKYC API.

The API returns timestamps in two formats:
- ISO8601 strings: "2021-12-01T00:00:00Z" or "2021-12-01T00:00:00.000Z"
- Unix milliseconds: 1696669429000
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_timestamp(value: Any) -> datetime | None:
    """Parse timestamp from API response.

    Args:
        value: Timestamp value (int, float, or ISO8601 string)

    Returns:
        datetime object in UTC, or None if value is None/empty
    """
    if value is None or value == "":
        return None

    # Handle integer/float unix timestamps (milliseconds)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)

    # Handle string timestamps
    if isinstance(value, str):
        # Try ISO8601 format
        try:
            # Handle both with and without milliseconds
            if value.endswith("Z"):
                if "." in value:
                    # With milliseconds: 2021-12-01T00:00:00.000Z
                    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
                        tzinfo=timezone.utc
                    )
                else:
                    # Without milliseconds: 2021-12-01T00:00:00Z
                    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
                        tzinfo=timezone.utc
                    )
            # Try parsing as ISO format with timezone
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass

        # Try parsing as numeric string (unix milliseconds)
        try:
            timestamp_ms = float(value)
            return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
        except (ValueError, TypeError):
            pass

    return None


def timestamp_to_unix_ms(dt: datetime) -> int:
    """Convert datetime to Unix milliseconds.

    Args:
        dt: datetime object

    Returns:
        Unix timestamp in milliseconds
    """
    return int(dt.timestamp() * 1000)


def format_timestamp_iso(dt: datetime) -> str:
    """Format datetime as ISO8601 string.

    Args:
        dt: datetime object

    Returns:
        ISO8601 formatted string (e.g., "2021-12-01T00:00:00.000Z")
    """
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def current_timestamp_ms() -> int:
    """Get current timestamp in Unix milliseconds.

    Returns:
        Current Unix timestamp in milliseconds
    """
    return int(datetime.now(timezone.utc).timestamp() * 1000)
