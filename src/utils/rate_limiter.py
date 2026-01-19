"""Rate limiting utilities for API clients."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Callable


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    max_requests: int  # Maximum number of requests
    time_window: float  # Time window in seconds
    burst_size: int | None = None  # Optional burst size (defaults to max_requests)

    def __post_init__(self) -> None:
        if self.burst_size is None:
            self.burst_size = self.max_requests


class RateLimitExceeded(Exception):
    """Raised when rate limit would be exceeded."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class RateLimiter:
    """
    Token bucket rate limiter with sliding window tracking.

    Thread-safe implementation suitable for synchronous REST clients.

    Example:
        # Allow 10 requests per second with burst of 20
        limiter = RateLimiter(
            RateLimitConfig(max_requests=10, time_window=1.0, burst_size=20)
        )

        # Before making API request
        limiter.acquire()  # Blocks until token available
        # ... make request ...
    """

    def __init__(
        self,
        config: RateLimitConfig,
        time_provider: Callable[[], float] | None = None,
    ) -> None:
        self.config = config
        self._time_provider = time_provider or time.time
        self._timestamps: deque[float] = deque()
        self._lock = Lock()

    def acquire(self, *, blocking: bool = True) -> bool:
        """
        Acquire permission to make a request.

        Args:
            blocking: If True, waits until request can be made. If False, returns immediately.

        Returns:
            True if request can be made, False if rate limit exceeded (only when blocking=False)

        Raises:
            RateLimitExceeded: When blocking=False and rate limit exceeded
        """
        with self._lock:
            current_time = self._time_provider()
            self._cleanup_old_timestamps(current_time)

            if len(self._timestamps) < (
                self.config.burst_size or self.config.max_requests
            ):
                self._timestamps.append(current_time)
                return True

            if not blocking:
                retry_after = self._calculate_retry_after(current_time)
                raise RateLimitExceeded(
                    f"Rate limit exceeded: {self.config.max_requests} requests "
                    f"per {self.config.time_window}s",
                    retry_after=retry_after,
                )

        # If blocking, wait and retry
        while True:
            with self._lock:
                current_time = self._time_provider()
                self._cleanup_old_timestamps(current_time)

                if len(self._timestamps) < (
                    self.config.burst_size or self.config.max_requests
                ):
                    self._timestamps.append(current_time)
                    return True

                wait_time = self._calculate_retry_after(current_time)

            time.sleep(wait_time)

    def _cleanup_old_timestamps(self, current_time: float) -> None:
        """Remove timestamps outside the time window."""
        cutoff = current_time - self.config.time_window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    def _calculate_retry_after(self, current_time: float) -> float:
        """Calculate how long to wait before next request."""
        if not self._timestamps:
            return 0.0

        oldest_timestamp = self._timestamps[0]
        time_until_slot_free = (
            oldest_timestamp + self.config.time_window
        ) - current_time
        return max(0.0, time_until_slot_free)

    def get_current_usage(self) -> tuple[int, int]:
        """
        Get current rate limit usage.

        Returns:
            Tuple of (current_requests, max_requests)
        """
        with self._lock:
            current_time = self._time_provider()
            self._cleanup_old_timestamps(current_time)
            return len(self._timestamps), self.config.max_requests

    def reset(self) -> None:
        """Reset the rate limiter state."""
        with self._lock:
            self._timestamps.clear()


class AsyncRateLimiter:
    """
    Async version of RateLimiter for async REST clients.

    Example:
        limiter = AsyncRateLimiter(
            RateLimitConfig(max_requests=10, time_window=1.0)
        )

        # Before making API request
        await limiter.acquire()
        # ... make async request ...
    """

    def __init__(
        self,
        config: RateLimitConfig,
        time_provider: Callable[[], float] | None = None,
    ) -> None:
        self.config = config
        self._time_provider = time_provider or time.time
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, *, blocking: bool = True) -> bool:
        """
        Acquire permission to make a request (async version).

        Args:
            blocking: If True, waits until request can be made. If False, returns immediately.

        Returns:
            True if request can be made, False if rate limit exceeded (only when blocking=False)

        Raises:
            RateLimitExceeded: When blocking=False and rate limit exceeded
        """
        async with self._lock:
            current_time = self._time_provider()
            self._cleanup_old_timestamps(current_time)

            if len(self._timestamps) < (
                self.config.burst_size or self.config.max_requests
            ):
                self._timestamps.append(current_time)
                return True

            if not blocking:
                retry_after = self._calculate_retry_after(current_time)
                raise RateLimitExceeded(
                    f"Rate limit exceeded: {self.config.max_requests} requests "
                    f"per {self.config.time_window}s",
                    retry_after=retry_after,
                )

        # If blocking, wait and retry
        while True:
            async with self._lock:
                current_time = self._time_provider()
                self._cleanup_old_timestamps(current_time)

                if len(self._timestamps) < (
                    self.config.burst_size or self.config.max_requests
                ):
                    self._timestamps.append(current_time)
                    return True

                wait_time = self._calculate_retry_after(current_time)

            await asyncio.sleep(wait_time)

    def _cleanup_old_timestamps(self, current_time: float) -> None:
        """Remove timestamps outside the time window."""
        cutoff = current_time - self.config.time_window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    def _calculate_retry_after(self, current_time: float) -> float:
        """Calculate how long to wait before next request."""
        if not self._timestamps:
            return 0.0

        oldest_timestamp = self._timestamps[0]
        time_until_slot_free = (
            oldest_timestamp + self.config.time_window
        ) - current_time
        return max(0.0, time_until_slot_free)

    async def get_current_usage(self) -> tuple[int, int]:
        """
        Get current rate limit usage.

        Returns:
            Tuple of (current_requests, max_requests)
        """
        async with self._lock:
            current_time = self._time_provider()
            self._cleanup_old_timestamps(current_time)
            return len(self._timestamps), self.config.max_requests

    async def reset(self) -> None:
        """Reset the rate limiter state."""
        async with self._lock:
            self._timestamps.clear()
