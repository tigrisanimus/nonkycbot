"""Balance tracking scaffolding."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Callable, Mapping


@dataclass
class Balances:
    available: dict[str, float] = field(default_factory=dict)
    fetcher: Callable[[], Mapping[str, float]] | None = None
    cache_ttl: float = 5.0
    last_fetch: float | None = None
    pending_adjustments: dict[str, float] = field(default_factory=dict)

    def update(self, asset: str, amount: float) -> None:
        self.available[asset] = amount

    def get(self, asset: str) -> float:
        return self.available.get(asset, 0.0)

    def apply_fill(self, deltas: Mapping[str, float]) -> None:
        for asset, delta in deltas.items():
            self.available[asset] = self.available.get(asset, 0.0) + delta
            self.pending_adjustments[asset] = (
                self.pending_adjustments.get(asset, 0.0) + delta
            )

    def fetch(self, force: bool = False) -> dict[str, float]:
        if self.fetcher is None:
            raise RuntimeError("No balance fetcher configured.")
        now = monotonic()
        if (
            not force
            and self.last_fetch is not None
            and now - self.last_fetch < self.cache_ttl
        ):
            return dict(self.available)
        fetched = dict(self.fetcher())
        self._reconcile(fetched)
        self.last_fetch = now
        return dict(self.available)

    def _reconcile(self, fetched: Mapping[str, float]) -> None:
        tolerance = 1e-9
        for asset in set(fetched) | set(self.available) | set(self.pending_adjustments):
            local_amount = self.available.get(asset, 0.0)
            fetched_amount = fetched.get(asset, 0.0)
            pending = self.pending_adjustments.get(asset, 0.0)
            if abs(fetched_amount - local_amount) <= tolerance:
                if asset in self.pending_adjustments:
                    del self.pending_adjustments[asset]
                self.available[asset] = fetched_amount
                continue
            reconciled_amount = fetched_amount + pending
            self.available[asset] = reconciled_amount
