"""Exchange server-time synchronization helpers."""

from __future__ import annotations

import json
import time
from typing import Any, Callable
from urllib.request import Request, urlopen


class TimeSynchronizer:
    """Fetches exchange time and maintains a local offset."""

    def __init__(
        self,
        *,
        server_time_url: str = "https://nonkyc.io/api/v2/getservertime",
        max_age: float = 60.0,
        time_provider: Callable[[], float] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._server_time_url = server_time_url
        self._max_age = max_age
        self._time_provider = time_provider or time.time
        self._timeout = timeout
        self._offset = 0.0
        self._last_sync = 0.0

    def time(self) -> float:
        now = self._time_provider()
        if self._should_sync(now):
            self._sync_with_guard()
        return now + self._offset

    def set_offset(self, offset: float, *, synced_at: float | None = None) -> None:
        self._offset = offset
        if synced_at is not None:
            self._last_sync = synced_at

    def _should_sync(self, now: float) -> bool:
        return self._last_sync == 0.0 or (now - self._last_sync) >= self._max_age

    def _sync_with_guard(self) -> None:
        try:
            self.sync()
        except (OSError, ValueError, json.JSONDecodeError):
            # Keep the last known offset if sync fails.
            return

    def sync(self) -> None:
        request = Request(self._server_time_url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=self._timeout) as response:
            payload = response.read().decode("utf8")
        parsed = json.loads(payload)
        server_time = self._extract_server_time(parsed)
        local_time = self._time_provider()
        self._offset = server_time - local_time
        self._last_sync = local_time

    def _extract_server_time(self, payload: Any) -> float:
        if isinstance(payload, dict):
            for key in ("serverTime", "server_time", "time", "timestamp"):
                if key in payload:
                    return self._normalize_time(payload[key])
            for key in ("data", "result"):
                if key in payload:
                    nested = payload[key]
                    if isinstance(nested, dict):
                        for nested_key in (
                            "serverTime",
                            "server_time",
                            "time",
                            "timestamp",
                        ):
                            if nested_key in nested:
                                return self._normalize_time(nested[nested_key])
                    return self._normalize_time(nested)
        return self._normalize_time(payload)

    def _normalize_time(self, value: Any) -> float:
        if isinstance(value, str):
            value = value.strip()
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Unsupported server time payload") from exc
        if numeric > 1e12:
            numeric /= 1000.0
        return numeric
