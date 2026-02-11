"""
Accumulation Infinity Grid strategy.

A buy-only, downward-expanding infinity grid combined with a slow passive DCA
layer.  The bot absorbs impatience: if the market does not offer cheap coins,
it does almost nothing.

Modules inside this file
------------------------
1. Config          - AccumulationConfig dataclass
2. Market state    - MarketState (mid, spread, depth, rolling volume, ATR, EMA)
3. Grid engine     - Layer A: one-sided downward infinity grid
4. DCA engine      - Layer B: independent passive DCA on a timer
5. Coordination    - Grid > DCA priority, shared caps
6. Impact detect   - Pause on adverse fills / spread widening
7. VWAP controller - Track bot vs market VWAP, throttle when needed
8. Execution       - Limit-only with randomised timing/sizing

Explicit prohibitions enforced throughout:
- NO sells anywhere
- NO market orders
- NO upward price chasing
- NO reuse of existing grid classes
"""

from __future__ import annotations

import json
import logging
import random
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from pathlib import Path
from typing import Any

from engine.exchange_client import ExchangeClient, OpenOrder

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Config module
# ---------------------------------------------------------------------------

_ZERO = Decimal("0")
_ONE = Decimal("1")
_NOTIONAL_BUFFER = Decimal("1.01")  # 1% safety margin for exchange min notional


@dataclass(frozen=True)
class GridParams:
    """Grid engine (Layer A) parameters."""

    n: int  # max active buy levels
    d0: Decimal  # initial distance from Pref (fraction, e.g. 0.005)
    g: Decimal  # geometric growth factor for level spacing
    s0: Decimal  # base order size (in base asset)
    k: Decimal  # size growth factor per level
    per_order_volume_cap: Decimal  # max size per single order


@dataclass(frozen=True)
class DCAParams:
    """DCA engine (Layer B) parameters."""

    budget_daily: Decimal  # fixed daily DCA budget (quote)
    interval_sec: float  # Td - timer interval between DCA attempts
    epsilon: Decimal  # offset below best bid (fraction, e.g. 0.001)
    ttl_sec: float  # cancel unfilled DCA order after this many seconds


@dataclass(frozen=True)
class GuardParams:
    """Global safety + impact control parameters."""

    participation_cap: Decimal  # max fraction of rolling volume bot may fill
    spread_limit: Decimal  # pause if spread exceeds this (fraction of mid)
    cooldown_impact_sec: float  # cooldown after impact trigger
    cooldown_grid_dca_sec: float  # pause DCA this many seconds after grid fill
    fill_time_threshold_sec: float  # impact: fill too fast
    mid_jump_threshold: Decimal  # impact: mid jumps up after fill (fraction)
    best_bid_touch_max: int  # impact: bot becomes best bid this many times
    best_bid_touch_window_sec: float  # … within this window
    spread_widen_threshold: Decimal  # impact: spread widens by this factor


@dataclass(frozen=True)
class VWAPParams:
    """VWAP controller parameters."""

    window_sec: float  # rolling window for bot + market VWAP
    size_reduction_factor: Decimal  # reduce size by this when VWAP_bot > VWAP_mkt
    spacing_widen_factor: Decimal  # widen grid spacing by this factor
    pause_threshold: Decimal  # pause entirely if ratio exceeds this


@dataclass(frozen=True)
class EMAParams:
    """EMA / ATR windows."""

    ema_window_sec: float  # EMA smoothing window
    ema_alpha: Decimal  # smoothing factor (0 < alpha <= 1)
    atr_window: int  # number of samples for ATR
    atr_flat_threshold: Decimal  # ATR below this ⇒ market flat (for DCA)


@dataclass(frozen=True)
class AccumulationConfig:
    """Complete configuration for AccumulationInfinityGrid."""

    symbol: str
    grid: GridParams
    dca: DCAParams
    guards: GuardParams
    vwap: VWAPParams
    ema: EMAParams
    daily_budget_quote: Decimal  # hard daily budget across both layers
    poll_interval_sec: float  # main loop interval
    price_decimals: int  # decimal places for price rounding
    qty_decimals: int  # decimal places for quantity rounding
    min_order_notional: Decimal = Decimal("1.0")  # minimum order value (quote)
    mode: str = "live"  # monitor | dry-run | live


# ---------------------------------------------------------------------------
# 2. Market state module
# ---------------------------------------------------------------------------


@dataclass
class MarketState:
    """Read-only market snapshot refreshed each poll cycle."""

    mid_price: Decimal = _ZERO
    best_bid: Decimal = _ZERO
    best_ask: Decimal = _ZERO
    spread_abs: Decimal = _ZERO
    spread_pct: Decimal = _ZERO
    median_spread_pct: Decimal = _ZERO
    top_bid_depth: Decimal = _ZERO
    top_ask_depth: Decimal = _ZERO

    # Rolling volumes (quote)
    volume_1m: Decimal = _ZERO
    volume_5m: Decimal = _ZERO
    volume_1h: Decimal = _ZERO

    # ATR & EMA
    atr: Decimal = _ZERO
    ema_price: Decimal = _ZERO  # Pref

    # Derived flags
    is_flat: bool = False

    @property
    def has_data(self) -> bool:
        return self.mid_price > _ZERO


class MarketStateTracker:
    """Computes and maintains rolling market statistics."""

    def __init__(self, config: AccumulationConfig) -> None:
        self._cfg = config
        self.state = MarketState()

        # Rolling buffers
        self._spread_samples: deque[Decimal] = deque(maxlen=120)
        self._price_samples: deque[tuple[float, Decimal]] = deque(maxlen=7200)
        self._volume_samples: deque[tuple[float, Decimal]] = deque(maxlen=7200)
        self._atr_samples: deque[Decimal] = deque(maxlen=config.ema.atr_window)

        self._last_price: Decimal = _ZERO
        self._ema_initialised = False

    def update(self, client: ExchangeClient, now: float) -> MarketState:
        """Refresh market state from exchange."""
        symbol = self._cfg.symbol

        bid, ask = client.get_orderbook_top(symbol)
        if bid <= _ZERO or ask <= _ZERO:
            logger.warning("Invalid orderbook top: bid=%s ask=%s", bid, ask)
            return self.state

        mid = (bid + ask) / 2
        spread_abs = ask - bid
        spread_pct = spread_abs / mid if mid > _ZERO else _ZERO

        # Spread tracking
        self._spread_samples.append(spread_pct)
        sorted_spreads = sorted(self._spread_samples)
        median_idx = len(sorted_spreads) // 2
        median_spread = sorted_spreads[median_idx] if sorted_spreads else _ZERO

        # Price / volume tracking
        self._price_samples.append((now, mid))
        # We approximate volume from price changes; real volume would come from
        # trades endpoint if available.  For now we track price movement as a proxy.
        if self._last_price > _ZERO:
            move = abs(mid - self._last_price)
            self._volume_samples.append((now, move * mid))  # notional proxy

        # EMA (Pref)
        alpha = self._cfg.ema.ema_alpha
        if not self._ema_initialised:
            ema = mid
            self._ema_initialised = True
        else:
            ema = alpha * mid + (_ONE - alpha) * self.state.ema_price
        # ATR
        if self._last_price > _ZERO:
            tr = abs(mid - self._last_price)
            self._atr_samples.append(tr)
        atr = (
            sum(self._atr_samples) / Decimal(len(self._atr_samples))
            if self._atr_samples
            else _ZERO
        )
        is_flat = atr < self._cfg.ema.atr_flat_threshold

        # Rolling volume windows
        vol_1m = self._sum_volume(now, 60)
        vol_5m = self._sum_volume(now, 300)
        vol_1h = self._sum_volume(now, 3600)

        self._last_price = mid

        self.state = MarketState(
            mid_price=mid,
            best_bid=bid,
            best_ask=ask,
            spread_abs=spread_abs,
            spread_pct=spread_pct,
            median_spread_pct=median_spread,
            top_bid_depth=_ZERO,  # depth requires full book; omitted for now
            top_ask_depth=_ZERO,
            volume_1m=vol_1m,
            volume_5m=vol_5m,
            volume_1h=vol_1h,
            atr=atr,
            ema_price=ema,
            is_flat=is_flat,
        )
        return self.state

    def _sum_volume(self, now: float, window_sec: float) -> Decimal:
        cutoff = now - window_sec
        return sum(v for t, v in self._volume_samples if t >= cutoff)


# ---------------------------------------------------------------------------
# 3. Grid engine (Layer A) - one-sided downward infinity grid
# ---------------------------------------------------------------------------


@dataclass
class GridLevel:
    """Represents one active grid buy level."""

    index: int  # level index (1-based)
    price: Decimal
    quantity: Decimal
    order_id: str | None = None
    client_id: str = ""
    placed_at: float = 0.0
    filled: bool = False
    filled_at: float = 0.0


@dataclass
class GridState:
    """State of the grid engine."""

    levels: list[GridLevel] = field(default_factory=list)
    next_index: int = 1
    deepest_fill_index: int = 0
    total_filled_quote: Decimal = _ZERO
    total_filled_base: Decimal = _ZERO


class GridEngine:
    """Layer A: one-sided downward infinity grid.

    Rules:
    - Maintain max N active buy levels below Pref
    - Pi = Pref * (1 - d0 * g^(i-1))
    - Si = min(s0 * k^(i-1), per_order_volume_cap)
    - On fill: do NOT replace upward, append one deeper level
    - If price rises: do nothing
    - If liquidity gate fails: cancel lowest-risk (shallowest) levels first
    """

    def __init__(self, config: AccumulationConfig) -> None:
        self._cfg = config
        self.state = GridState()

    def compute_levels(
        self,
        pref: Decimal,
        n: int,
        start_index: int,
        price_dec: int,
        qty_dec: int,
        vwap_spacing_factor: Decimal = _ONE,
        vwap_size_factor: Decimal = _ONE,
    ) -> list[GridLevel]:
        """Compute N grid levels starting from start_index below Pref."""
        g = self._cfg.grid
        levels: list[GridLevel] = []
        for i in range(n):
            idx = start_index + i
            # Price: Pi = Pref * (1 - d0 * g^(idx-1)) * vwap_spacing_factor
            exponent = idx - 1
            distance = g.d0 * (g.g**exponent) * vwap_spacing_factor
            price = pref * (_ONE - distance)
            price = price.quantize(Decimal(10) ** -price_dec, rounding=ROUND_DOWN)
            if price <= _ZERO:
                break
            # Size: Si = min(s0 * k^(idx-1), per_order_volume_cap) * vwap_size_factor
            size = g.s0 * (g.k**exponent) * vwap_size_factor
            size = min(size, g.per_order_volume_cap)
            # Randomise size +-5%
            jitter = Decimal(str(random.uniform(0.95, 1.05)))
            size = (size * jitter).quantize(
                Decimal(10) ** -qty_dec, rounding=ROUND_DOWN
            )
            if size <= _ZERO:
                break
            # Enforce minimum order notional (with safety buffer to avoid
            # exchange rejection due to rounding at the boundary)
            min_notional = self._cfg.min_order_notional * _NOTIONAL_BUFFER
            if price > _ZERO and price * size < min_notional:
                size = (min_notional / price).quantize(
                    Decimal(10) ** -qty_dec, rounding=ROUND_UP
                )
            levels.append(
                GridLevel(
                    index=idx,
                    price=price,
                    quantity=size,
                    client_id=str(uuid.uuid4()),
                )
            )
        return levels

    def reconcile_fills(
        self,
        open_orders: list[OpenOrder],
        now: float,
    ) -> list[GridLevel]:
        """Check which grid levels have been filled.

        Returns list of newly filled levels.
        """
        open_ids = {o.order_id for o in open_orders}
        newly_filled: list[GridLevel] = []
        for lvl in self.state.levels:
            if lvl.filled:
                continue
            if lvl.order_id is not None and lvl.order_id not in open_ids:
                lvl.filled = True
                lvl.filled_at = now
                self.state.total_filled_quote += lvl.price * lvl.quantity
                self.state.total_filled_base += lvl.quantity
                if lvl.index > self.state.deepest_fill_index:
                    self.state.deepest_fill_index = lvl.index
                newly_filled.append(lvl)
                logger.info(
                    "GRID FILL level=%d price=%s qty=%s order=%s",
                    lvl.index,
                    lvl.price,
                    lvl.quantity,
                    lvl.order_id,
                )
        return newly_filled

    def pending_levels(self) -> list[GridLevel]:
        """Return levels that are not yet placed and not filled."""
        return [
            lvl for lvl in self.state.levels if lvl.order_id is None and not lvl.filled
        ]

    def active_levels(self) -> list[GridLevel]:
        """Return levels with live orders on exchange."""
        return [
            lvl
            for lvl in self.state.levels
            if lvl.order_id is not None and not lvl.filled
        ]

    def shallowest_active(self) -> GridLevel | None:
        """Return the active level closest to current price (lowest risk)."""
        active = self.active_levels()
        if not active:
            return None
        return max(active, key=lambda lv: lv.price)

    def cancel_shallowest(self) -> GridLevel | None:
        """Mark the shallowest active level for cancellation.

        Returns the level to cancel, or None.
        """
        lvl = self.shallowest_active()
        if lvl is not None:
            # Mark as needing cancel; caller handles exchange cancel
            return lvl
        return None


# ---------------------------------------------------------------------------
# 4. DCA engine (Layer B)
# ---------------------------------------------------------------------------


@dataclass
class DCAState:
    """State of the DCA engine."""

    last_attempt_at: float = 0.0
    last_fill_at: float = 0.0
    current_order_id: str | None = None
    current_order_placed_at: float = 0.0
    current_order_price: Decimal = _ZERO
    current_order_qty: Decimal = _ZERO
    daily_spent_quote: Decimal = _ZERO
    daily_reset_at: float = 0.0
    total_filled_quote: Decimal = _ZERO
    total_filled_base: Decimal = _ZERO
    skipped_grid_active: int = 0


class DCAEngine:
    """Layer B: independent slow passive DCA.

    Rules:
    - Runs on timer (Td)
    - Only active when market is flat (ATR-based)
    - Passive limit orders only: Pd = best_bid * (1 - epsilon)
    - Cancel if not filled within TTL
    - Skip if grid filled recently
    - Fixed daily budget, never borrows from grid allocation
    """

    def __init__(self, config: AccumulationConfig) -> None:
        self._cfg = config
        self.state = DCAState()

    def should_attempt(
        self,
        now: float,
        is_flat: bool,
        last_grid_fill_at: float,
    ) -> bool:
        """Determine if DCA should attempt a cycle."""
        dca = self._cfg.dca
        guards = self._cfg.guards

        # Timer check
        if now - self.state.last_attempt_at < dca.interval_sec:
            return False

        # Market must be flat
        if not is_flat:
            logger.debug("DCA skip: market not flat")
            return False

        # Grid priority: skip if grid filled recently
        if now - last_grid_fill_at < guards.cooldown_grid_dca_sec:
            self.state.skipped_grid_active += 1
            logger.info(
                "DCA skip: grid filled %.0fs ago (cooldown=%ss)",
                now - last_grid_fill_at,
                guards.cooldown_grid_dca_sec,
            )
            return False

        # Daily budget check
        self._maybe_reset_daily(now)
        if self.state.daily_spent_quote >= dca.budget_daily:
            logger.info(
                "DCA skip: daily budget exhausted (%s/%s)",
                self.state.daily_spent_quote,
                dca.budget_daily,
            )
            return False

        return True

    def compute_order(
        self,
        best_bid: Decimal,
        price_dec: int,
        qty_dec: int,
    ) -> tuple[Decimal, Decimal]:
        """Compute DCA order price and quantity.

        Returns (price, quantity) in base asset.
        """
        dca = self._cfg.dca
        epsilon = dca.epsilon

        price = best_bid * (_ONE - epsilon)
        price = price.quantize(Decimal(10) ** -price_dec, rounding=ROUND_DOWN)

        # Remaining daily budget
        self._maybe_reset_daily(time.time())
        remaining = dca.budget_daily - self.state.daily_spent_quote
        # Size = remaining / intervals_left, but simplified to spread evenly
        intervals_per_day = Decimal(str(86400.0 / dca.interval_sec))
        per_interval_budget = dca.budget_daily / max(intervals_per_day, _ONE)
        per_interval_budget = min(per_interval_budget, remaining)

        if price > _ZERO:
            qty = per_interval_budget / price
            # Randomise +-3%
            jitter = Decimal(str(random.uniform(0.97, 1.03)))
            qty = (qty * jitter).quantize(Decimal(10) ** -qty_dec, rounding=ROUND_DOWN)
            # Enforce minimum order notional (with safety buffer to avoid
            # exchange rejection due to rounding at the boundary)
            min_notional = self._cfg.min_order_notional * _NOTIONAL_BUFFER
            if price * qty < min_notional:
                qty = (min_notional / price).quantize(
                    Decimal(10) ** -qty_dec, rounding=ROUND_UP
                )
        else:
            qty = _ZERO

        return price, qty

    def should_cancel_stale(self, now: float) -> bool:
        """Check if current DCA order should be cancelled (TTL expired)."""
        if self.state.current_order_id is None:
            return False
        return now - self.state.current_order_placed_at > self._cfg.dca.ttl_sec

    def record_fill(self, now: float) -> None:
        """Record a DCA fill."""
        self.state.last_fill_at = now
        cost = self.state.current_order_price * self.state.current_order_qty
        self.state.daily_spent_quote += cost
        self.state.total_filled_quote += cost
        self.state.total_filled_base += self.state.current_order_qty
        logger.info(
            "DCA FILL price=%s qty=%s cost=%s daily_spent=%s/%s",
            self.state.current_order_price,
            self.state.current_order_qty,
            cost,
            self.state.daily_spent_quote,
            self._cfg.dca.budget_daily,
        )
        self.state.current_order_id = None

    def record_cancel(self) -> None:
        """Record a DCA cancel (TTL expired unfilled)."""
        logger.info(
            "DCA CANCEL stale order=%s price=%s",
            self.state.current_order_id,
            self.state.current_order_price,
        )
        self.state.current_order_id = None

    def _maybe_reset_daily(self, now: float) -> None:
        if now - self.state.daily_reset_at >= 86400:
            self.state.daily_spent_quote = _ZERO
            self.state.daily_reset_at = now


# ---------------------------------------------------------------------------
# 5. Coordination logic
# ---------------------------------------------------------------------------


class Coordinator:
    """Enforces priority: Grid > DCA.

    Shared constraints:
    - Participation cap
    - Impact detection
    - VWAP enforcement
    """

    def __init__(self, config: AccumulationConfig) -> None:
        self._cfg = config
        self._last_grid_fill_at: float = 0.0
        self._daily_total_spent: Decimal = _ZERO
        self._daily_reset_at: float = 0.0

    def record_grid_fill(self, now: float, cost: Decimal) -> None:
        self._last_grid_fill_at = now
        self._maybe_reset_daily(now)
        self._daily_total_spent += cost

    def record_dca_fill(self, now: float, cost: Decimal) -> None:
        self._maybe_reset_daily(now)
        self._daily_total_spent += cost

    @property
    def last_grid_fill_at(self) -> float:
        return self._last_grid_fill_at

    def daily_budget_remaining(self, now: float) -> Decimal:
        self._maybe_reset_daily(now)
        return max(_ZERO, self._cfg.daily_budget_quote - self._daily_total_spent)

    def daily_budget_exhausted(self, now: float) -> bool:
        return self.daily_budget_remaining(now) <= _ZERO

    def participation_ok(self, volume_1h: Decimal) -> bool:
        """Check if bot is within participation cap."""
        if volume_1h <= _ZERO:
            return True  # no volume data, allow cautiously
        ratio = self._daily_total_spent / volume_1h if volume_1h > _ZERO else _ZERO
        ok = ratio < self._cfg.guards.participation_cap
        if not ok:
            logger.warning(
                "PARTICIPATION CAP hit: ratio=%s cap=%s",
                ratio,
                self._cfg.guards.participation_cap,
            )
        return ok

    def _maybe_reset_daily(self, now: float) -> None:
        if now - self._daily_reset_at >= 86400:
            self._daily_total_spent = _ZERO
            self._daily_reset_at = now


# ---------------------------------------------------------------------------
# 6. Impact detection module
# ---------------------------------------------------------------------------


@dataclass
class ImpactState:
    paused: bool = False
    pause_until: float = 0.0
    reason: str = ""
    trigger_count: int = 0


class ImpactDetector:
    """Detects adverse market impact from bot's own orders.

    Triggers pause if any:
    - Fill time < threshold (order filled too fast)
    - Mid price jumps up after fill
    - Bot frequently becomes best bid
    - Spread widens abnormally
    """

    def __init__(self, config: AccumulationConfig) -> None:
        self._cfg = config
        self.state = ImpactState()
        self._best_bid_touches: deque[float] = deque(maxlen=200)
        self._pre_fill_mids: deque[tuple[float, Decimal]] = deque(maxlen=50)

    def is_paused(self, now: float) -> bool:
        if self.state.paused and now >= self.state.pause_until:
            logger.info("IMPACT cooldown expired, resuming")
            self.state.paused = False
            self.state.reason = ""
        return self.state.paused

    def check_fill_speed(self, placed_at: float, filled_at: float, now: float) -> bool:
        """Return True if fill was suspiciously fast."""
        fill_time = filled_at - placed_at
        if fill_time < self._cfg.guards.fill_time_threshold_sec:
            self._trigger(now, f"fast_fill ({fill_time:.1f}s)")
            return True
        return False

    def check_mid_jump_after_fill(
        self,
        mid_before: Decimal,
        mid_after: Decimal,
        now: float,
    ) -> bool:
        """Return True if mid price jumped up after our fill."""
        if mid_before <= _ZERO:
            return False
        jump = (mid_after - mid_before) / mid_before
        if jump > self._cfg.guards.mid_jump_threshold:
            self._trigger(now, f"mid_jump ({jump:.4f})")
            return True
        return False

    def record_best_bid_touch(self, now: float) -> None:
        """Record when our order is at or near best bid."""
        self._best_bid_touches.append(now)

    def check_best_bid_frequency(self, now: float) -> bool:
        """Return True if bot became best bid too often."""
        window = self._cfg.guards.best_bid_touch_window_sec
        cutoff = now - window
        recent = sum(1 for t in self._best_bid_touches if t >= cutoff)
        if recent >= self._cfg.guards.best_bid_touch_max:
            self._trigger(now, f"best_bid_touch ({recent} in {window}s)")
            return True
        return False

    def check_spread_widen(
        self,
        current_spread_pct: Decimal,
        median_spread_pct: Decimal,
        now: float,
    ) -> bool:
        """Return True if spread widened abnormally."""
        if median_spread_pct <= _ZERO:
            return False
        ratio = current_spread_pct / median_spread_pct
        if ratio > self._cfg.guards.spread_widen_threshold:
            self._trigger(now, f"spread_widen (ratio={ratio:.2f})")
            return True
        return False

    def _trigger(self, now: float, reason: str) -> None:
        cooldown = self._cfg.guards.cooldown_impact_sec
        self.state.paused = True
        self.state.pause_until = now + cooldown
        self.state.reason = reason
        self.state.trigger_count += 1
        logger.warning(
            "IMPACT TRIGGER: %s — pausing for %ss (total triggers: %d)",
            reason,
            cooldown,
            self.state.trigger_count,
        )


# ---------------------------------------------------------------------------
# 7. VWAP controller
# ---------------------------------------------------------------------------


@dataclass
class VWAPSample:
    timestamp: float
    price: Decimal
    quantity: Decimal


class VWAPController:
    """Track bot VWAP vs market VWAP and throttle when needed.

    Rule: if VWAP_bot > VWAP_market ⇒ reduce size, widen grid, or pause.
    """

    def __init__(self, config: AccumulationConfig) -> None:
        self._cfg = config
        self._bot_fills: deque[VWAPSample] = deque(maxlen=5000)
        self._market_samples: deque[VWAPSample] = deque(maxlen=5000)

    def record_bot_fill(self, price: Decimal, qty: Decimal, now: float) -> None:
        self._bot_fills.append(VWAPSample(now, price, qty))

    def record_market_price(self, price: Decimal, now: float) -> None:
        """Record a market price sample (mid price each poll)."""
        self._market_samples.append(VWAPSample(now, price, _ONE))

    def bot_vwap(self, now: float) -> Decimal:
        window = self._cfg.vwap.window_sec
        cutoff = now - window
        samples = [s for s in self._bot_fills if s.timestamp >= cutoff]
        total_cost = sum(s.price * s.quantity for s in samples)
        total_qty = sum(s.quantity for s in samples)
        return total_cost / total_qty if total_qty > _ZERO else _ZERO

    def market_vwap(self, now: float) -> Decimal:
        window = self._cfg.vwap.window_sec
        cutoff = now - window
        samples = [s for s in self._market_samples if s.timestamp >= cutoff]
        total_cost = sum(s.price * s.quantity for s in samples)
        total_qty = sum(s.quantity for s in samples)
        return total_cost / total_qty if total_qty > _ZERO else _ZERO

    def adjustments(self, now: float) -> tuple[Decimal, Decimal, bool]:
        """Return (size_factor, spacing_factor, should_pause).

        Called each cycle to modify grid/DCA parameters.
        """
        bv = self.bot_vwap(now)
        mv = self.market_vwap(now)

        if bv <= _ZERO or mv <= _ZERO:
            return _ONE, _ONE, False

        if bv > mv:
            ratio = bv / mv
            logger.warning(
                "VWAP WARNING: bot_vwap=%s > market_vwap=%s (ratio=%.4f)",
                bv,
                mv,
                ratio,
            )
            if ratio > self._cfg.vwap.pause_threshold:
                logger.warning(
                    "VWAP PAUSE: ratio %.4f exceeds threshold %s",
                    ratio,
                    self._cfg.vwap.pause_threshold,
                )
                return _ZERO, _ONE, True
            size_f = self._cfg.vwap.size_reduction_factor
            spacing_f = self._cfg.vwap.spacing_widen_factor
            return size_f, spacing_f, False

        return _ONE, _ONE, False


# ---------------------------------------------------------------------------
# 8. Execution engine
# ---------------------------------------------------------------------------


class ExecutionEngine:
    """Limit-only execution with randomised timing and sizing.

    Hard constraints:
    - Limit orders only (never market)
    - Randomised placement timing
    - Randomised sizing within bounds (applied in grid/DCA compute)
    - Cancel/replace throttled
    """

    def __init__(
        self,
        client: ExchangeClient,
        config: AccumulationConfig,
    ) -> None:
        self._client = client
        self._cfg = config
        self._last_place_at: float = 0.0
        self._last_cancel_at: float = 0.0
        self._min_action_gap: float = 0.5  # minimum seconds between actions
        self.insufficient_funds: bool = False  # set when exchange rejects for low balance

    def place_buy(
        self,
        price: Decimal,
        quantity: Decimal,
        client_id: str,
        *,
        dry_run: bool = False,
    ) -> str | None:
        """Place a limit buy order. Returns order_id or None."""
        if price <= _ZERO or quantity <= _ZERO:
            logger.warning("EXEC skip: invalid price=%s qty=%s", price, quantity)
            return None

        notional = price * quantity
        min_notional = self._cfg.min_order_notional * _NOTIONAL_BUFFER
        if notional < min_notional:
            logger.warning(
                "EXEC skip: notional %s < min %s (price=%s qty=%s)",
                notional,
                min_notional,
                price,
                quantity,
            )
            return None

        # Randomised timing jitter (0-300ms)
        jitter = random.uniform(0, 0.3)
        elapsed = time.time() - self._last_place_at
        if elapsed < self._min_action_gap + jitter:
            time.sleep(self._min_action_gap + jitter - elapsed)

        logger.info(
            "EXEC PLACE BUY price=%s qty=%s client_id=%s dry_run=%s",
            price,
            quantity,
            client_id,
            dry_run,
        )

        if dry_run:
            fake_id = f"dry-{client_id[:8]}"
            self._last_place_at = time.time()
            return fake_id

        try:
            order_id = self._client.place_limit(
                symbol=self._cfg.symbol,
                side="buy",
                price=price,
                quantity=quantity,
                client_id=client_id,
            )
            self._last_place_at = time.time()
            logger.info("EXEC PLACED order_id=%s", order_id)
            return order_id
        except Exception as exc:
            logger.exception("EXEC PLACE FAILED price=%s qty=%s", price, quantity)
            if "Insufficient funds" in str(exc):
                self.insufficient_funds = True
                logger.warning(
                    "EXEC insufficient funds detected — skipping remaining orders this cycle"
                )
            return None

    def cancel(self, order_id: str, *, dry_run: bool = False) -> bool:
        """Cancel an order. Returns True on success."""
        jitter = random.uniform(0, 0.2)
        elapsed = time.time() - self._last_cancel_at
        if elapsed < self._min_action_gap + jitter:
            time.sleep(self._min_action_gap + jitter - elapsed)

        logger.info("EXEC CANCEL order_id=%s dry_run=%s", order_id, dry_run)

        if dry_run:
            self._last_cancel_at = time.time()
            return True

        try:
            result = self._client.cancel_order(order_id)
            self._last_cancel_at = time.time()
            if result:
                logger.info("EXEC CANCELLED order_id=%s", order_id)
            else:
                logger.warning("EXEC CANCEL returned False order_id=%s", order_id)
            return result
        except Exception:
            logger.exception("EXEC CANCEL FAILED order_id=%s", order_id)
            return False


# ---------------------------------------------------------------------------
# Main strategy class: AccumulationInfinityGrid
# ---------------------------------------------------------------------------


class AccumulationInfinityGrid:
    """Buy-only accumulation bot combining a downward infinity grid with passive DCA.

    This bot absorbs impatience.
    If the market doesn't offer cheap coins, the bot does almost nothing.
    """

    def __init__(
        self,
        client: ExchangeClient,
        config: AccumulationConfig,
        *,
        state_path: Path | None = None,
        time_provider: Any = None,
    ) -> None:
        self._client = client
        self._cfg = config
        self._state_path = state_path
        self._time = time_provider or time.time
        self._dry_run = config.mode == "dry-run"
        self._monitor = config.mode == "monitor"

        # Sub-modules
        self._market = MarketStateTracker(config)
        self._grid = GridEngine(config)
        self._dca = DCAEngine(config)
        self._coord = Coordinator(config)
        self._impact = ImpactDetector(config)
        self._vwap = VWAPController(config)
        self._exec = ExecutionEngine(client, config)

        # Tracking
        self._cycle_count: int = 0
        self._mid_before_fill: Decimal = _ZERO

    # ----- State persistence -----

    def load_state(self) -> None:
        """Load persisted state from JSON file."""
        if self._state_path is None or not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            # Grid state
            gs = data.get("grid", {})
            self._grid.state.next_index = gs.get("next_index", 1)
            self._grid.state.deepest_fill_index = gs.get("deepest_fill_index", 0)
            self._grid.state.total_filled_quote = Decimal(
                str(gs.get("total_filled_quote", "0"))
            )
            self._grid.state.total_filled_base = Decimal(
                str(gs.get("total_filled_base", "0"))
            )
            for lv in gs.get("levels", []):
                self._grid.state.levels.append(
                    GridLevel(
                        index=lv["index"],
                        price=Decimal(str(lv["price"])),
                        quantity=Decimal(str(lv["quantity"])),
                        order_id=lv.get("order_id"),
                        client_id=lv.get("client_id", ""),
                        placed_at=lv.get("placed_at", 0.0),
                        filled=lv.get("filled", False),
                        filled_at=lv.get("filled_at", 0.0),
                    )
                )
            # DCA state
            ds = data.get("dca", {})
            self._dca.state.last_attempt_at = ds.get("last_attempt_at", 0.0)
            self._dca.state.last_fill_at = ds.get("last_fill_at", 0.0)
            self._dca.state.current_order_id = ds.get("current_order_id")
            self._dca.state.current_order_placed_at = ds.get(
                "current_order_placed_at", 0.0
            )
            self._dca.state.current_order_price = Decimal(
                str(ds.get("current_order_price", "0"))
            )
            self._dca.state.current_order_qty = Decimal(
                str(ds.get("current_order_qty", "0"))
            )
            self._dca.state.daily_spent_quote = Decimal(
                str(ds.get("daily_spent_quote", "0"))
            )
            self._dca.state.daily_reset_at = ds.get("daily_reset_at", 0.0)
            self._dca.state.total_filled_quote = Decimal(
                str(ds.get("total_filled_quote", "0"))
            )
            self._dca.state.total_filled_base = Decimal(
                str(ds.get("total_filled_base", "0"))
            )
            # Coordinator
            cs = data.get("coordinator", {})
            self._coord._last_grid_fill_at = cs.get("last_grid_fill_at", 0.0)
            self._coord._daily_total_spent = Decimal(
                str(cs.get("daily_total_spent", "0"))
            )
            self._coord._daily_reset_at = cs.get("daily_reset_at", 0.0)
            # Impact
            imp = data.get("impact", {})
            self._impact.state.trigger_count = imp.get("trigger_count", 0)
            # Cycle
            self._cycle_count = data.get("cycle_count", 0)

            logger.info(
                "State loaded: grid_levels=%d dca_spent=%s cycles=%d",
                len(self._grid.state.levels),
                self._dca.state.daily_spent_quote,
                self._cycle_count,
            )
        except Exception:
            logger.exception("Failed to load state from %s", self._state_path)

    def save_state(self) -> None:
        """Persist state to JSON file."""
        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "grid": {
                    "next_index": self._grid.state.next_index,
                    "deepest_fill_index": self._grid.state.deepest_fill_index,
                    "total_filled_quote": str(self._grid.state.total_filled_quote),
                    "total_filled_base": str(self._grid.state.total_filled_base),
                    "levels": [
                        {
                            "index": lv.index,
                            "price": str(lv.price),
                            "quantity": str(lv.quantity),
                            "order_id": lv.order_id,
                            "client_id": lv.client_id,
                            "placed_at": lv.placed_at,
                            "filled": lv.filled,
                            "filled_at": lv.filled_at,
                        }
                        for lv in self._grid.state.levels
                    ],
                },
                "dca": {
                    "last_attempt_at": self._dca.state.last_attempt_at,
                    "last_fill_at": self._dca.state.last_fill_at,
                    "current_order_id": self._dca.state.current_order_id,
                    "current_order_placed_at": self._dca.state.current_order_placed_at,
                    "current_order_price": str(self._dca.state.current_order_price),
                    "current_order_qty": str(self._dca.state.current_order_qty),
                    "daily_spent_quote": str(self._dca.state.daily_spent_quote),
                    "daily_reset_at": self._dca.state.daily_reset_at,
                    "total_filled_quote": str(self._dca.state.total_filled_quote),
                    "total_filled_base": str(self._dca.state.total_filled_base),
                },
                "coordinator": {
                    "last_grid_fill_at": self._coord._last_grid_fill_at,
                    "daily_total_spent": str(self._coord._daily_total_spent),
                    "daily_reset_at": self._coord._daily_reset_at,
                },
                "impact": {
                    "trigger_count": self._impact.state.trigger_count,
                },
                "cycle_count": self._cycle_count,
            }
            self._state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            logger.exception("Failed to save state to %s", self._state_path)

    def _fetch_available_quote(self) -> Decimal:
        """Fetch available balance of the quote asset."""
        try:
            # Symbol format is BASE_QUOTE, e.g. COSA_BTC
            quote = self._cfg.symbol.split("_")[1]
            balances = self._client.get_balances()
            if quote in balances:
                available, _held = balances[quote]
                return available
        except Exception:
            logger.debug("Could not fetch quote balance, skipping pre-flight check")
        return Decimal("Infinity")  # allow all if balance check fails

    # ----- Main poll loop -----

    def poll_once(self) -> None:
        """Execute one cycle of the accumulation strategy."""
        now = self._time()
        self._cycle_count += 1

        # 1. Update market state
        mkt = self._market.update(self._client, now)
        if not mkt.has_data:
            logger.warning("No market data, skipping cycle %d", self._cycle_count)
            return

        self._vwap.record_market_price(mkt.mid_price, now)

        # 2. Log observability snapshot
        if self._cycle_count % 10 == 0:
            self._log_status(mkt, now)

        # 3. Check global guards
        if self._impact.is_paused(now):
            logger.info(
                "PAUSED (impact): reason=%s until=%.0f",
                self._impact.state.reason,
                self._impact.state.pause_until,
            )
            return

        # Spread guard
        if mkt.spread_pct > self._cfg.guards.spread_limit:
            logger.info(
                "PAUSED (spread): current=%s limit=%s",
                mkt.spread_pct,
                self._cfg.guards.spread_limit,
            )
            return

        # Daily budget guard
        if self._coord.daily_budget_exhausted(now):
            logger.info("PAUSED (daily budget exhausted)")
            return

        # Participation cap
        if not self._coord.participation_ok(mkt.volume_1h):
            return

        # VWAP enforcement
        vwap_size_f, vwap_spacing_f, vwap_pause = self._vwap.adjustments(now)
        if vwap_pause:
            logger.info("PAUSED (VWAP)")
            return

        # 4. Monitor mode: log-only, no actions
        if self._monitor:
            return

        # Reset per-cycle execution flags
        self._exec.insufficient_funds = False

        # Pre-flight balance check
        available_quote = self._fetch_available_quote()

        # 5. Reconcile exchange state
        open_orders = self._client.list_open_orders(self._cfg.symbol)

        # --- Grid engine (Layer A) ---
        self._run_grid(mkt, open_orders, now, vwap_size_f, vwap_spacing_f, available_quote)

        # --- DCA engine (Layer B) ---
        self._run_dca(mkt, open_orders, now, available_quote)

        # 6. Persist
        self.save_state()

    def _run_grid(
        self,
        mkt: MarketState,
        open_orders: list[OpenOrder],
        now: float,
        vwap_size_f: Decimal,
        vwap_spacing_f: Decimal,
        available_quote: Decimal = Decimal("Infinity"),
    ) -> None:
        """Run the grid engine cycle."""
        pref = mkt.ema_price
        price_dec = self._cfg.price_decimals
        qty_dec = self._cfg.qty_decimals

        # Reconcile fills
        mid_before = (
            self._mid_before_fill if self._mid_before_fill > _ZERO else mkt.mid_price
        )
        newly_filled = self._grid.reconcile_fills(open_orders, now)

        for fill in newly_filled:
            # Record in coordinator and VWAP
            cost = fill.price * fill.quantity
            self._coord.record_grid_fill(now, cost)
            self._vwap.record_bot_fill(fill.price, fill.quantity, now)

            # Impact checks
            self._impact.check_fill_speed(fill.placed_at, fill.filled_at, now)
            self._impact.check_mid_jump_after_fill(mid_before, mkt.mid_price, now)

            # Append one deeper level (infinity grid behaviour)
            deeper_idx = self._grid.state.next_index
            new_levels = self._grid.compute_levels(
                pref,
                1,
                deeper_idx,
                price_dec,
                qty_dec,
                vwap_spacing_factor=vwap_spacing_f,
                vwap_size_factor=vwap_size_f,
            )
            for nl in new_levels:
                self._grid.state.levels.append(nl)
                self._grid.state.next_index = nl.index + 1
                logger.info(
                    "GRID EXTEND deeper level=%d price=%s qty=%s",
                    nl.index,
                    nl.price,
                    nl.quantity,
                )

        # Seed initial grid if empty
        active = self._grid.active_levels()
        pending = self._grid.pending_levels()
        if not active and not pending:
            needed = self._cfg.grid.n
            start_idx = self._grid.state.next_index
            new_levels = self._grid.compute_levels(
                pref,
                needed,
                start_idx,
                price_dec,
                qty_dec,
                vwap_spacing_factor=vwap_spacing_f,
                vwap_size_factor=vwap_size_f,
            )
            for nl in new_levels:
                self._grid.state.levels.append(nl)
            if new_levels:
                self._grid.state.next_index = new_levels[-1].index + 1
            logger.info(
                "GRID SEED %d levels from index %d (Pref=%s)",
                len(new_levels),
                start_idx,
                pref,
            )

        # Enforce max N active levels: cancel shallowest if too many
        active = self._grid.active_levels()
        while len(active) > self._cfg.grid.n:
            lvl = self._grid.cancel_shallowest()
            if lvl and lvl.order_id:
                self._exec.cancel(lvl.order_id, dry_run=self._dry_run)
                lvl.order_id = None
                logger.info("GRID CANCEL excess level=%d", lvl.index)
            active = self._grid.active_levels()

        # Place pending levels (track committed cost from active orders to
        # avoid over-committing beyond the daily budget)
        active_committed = sum(
            lv.price * lv.quantity for lv in self._grid.active_levels()
        )
        for lvl in self._grid.pending_levels():
            # Stop placing if exchange reported insufficient funds
            if self._exec.insufficient_funds:
                logger.info("GRID skip remaining levels: insufficient funds")
                break
            # Only place if below Pref
            if lvl.price >= pref:
                continue
            # Check daily budget (remaining minus already-committed active orders)
            cost = lvl.price * lvl.quantity
            if self._coord.daily_budget_remaining(now) - active_committed < cost:
                logger.debug("GRID skip level=%d: daily budget", lvl.index)
                continue
            # Check available exchange balance
            if available_quote - active_committed < cost:
                logger.info(
                    "GRID skip level=%d: insufficient balance (need=%s, available=%s, committed=%s)",
                    lvl.index,
                    cost,
                    available_quote,
                    active_committed,
                )
                break
            order_id = self._exec.place_buy(
                lvl.price, lvl.quantity, lvl.client_id, dry_run=self._dry_run
            )
            if order_id:
                lvl.order_id = order_id
                lvl.placed_at = now
                active_committed += cost

        # Impact: check if our orders are at best bid
        for lvl in self._grid.active_levels():
            if lvl.price >= mkt.best_bid:
                self._impact.record_best_bid_touch(now)
        self._impact.check_best_bid_frequency(now)

        # Impact: check spread widening
        self._impact.check_spread_widen(mkt.spread_pct, mkt.median_spread_pct, now)

        # Save mid for next cycle's impact check
        self._mid_before_fill = mkt.mid_price

    def _run_dca(
        self,
        mkt: MarketState,
        open_orders: list[OpenOrder],
        now: float,
        available_quote: Decimal = Decimal("Infinity"),
    ) -> None:
        """Run the DCA engine cycle."""
        # Check for stale DCA order
        if self._dca.should_cancel_stale(now):
            if self._dca.state.current_order_id:
                # Check if it filled instead
                open_ids = {o.order_id for o in open_orders}
                if self._dca.state.current_order_id not in open_ids:
                    # Filled
                    self._dca.record_fill(now)
                    self._coord.record_dca_fill(
                        now,
                        self._dca.state.current_order_price
                        * self._dca.state.current_order_qty,
                    )
                    self._vwap.record_bot_fill(
                        self._dca.state.current_order_price,
                        self._dca.state.current_order_qty,
                        now,
                    )
                else:
                    # Cancel stale order
                    self._exec.cancel(
                        self._dca.state.current_order_id, dry_run=self._dry_run
                    )
                    self._dca.record_cancel()

        # Check for DCA fill (not stale path)
        if self._dca.state.current_order_id:
            open_ids = {o.order_id for o in open_orders}
            if self._dca.state.current_order_id not in open_ids:
                self._dca.record_fill(now)
                cost = (
                    self._dca.state.current_order_price
                    * self._dca.state.current_order_qty
                )
                self._coord.record_dca_fill(now, cost)
                self._vwap.record_bot_fill(
                    self._dca.state.current_order_price,
                    self._dca.state.current_order_qty,
                    now,
                )

        # Attempt new DCA order
        if self._dca.state.current_order_id is not None:
            return  # already have an active DCA order

        # Skip DCA if insufficient funds was hit during grid placement
        if self._exec.insufficient_funds:
            logger.debug("DCA skip: insufficient funds from earlier this cycle")
            return

        if not self._dca.should_attempt(
            now, mkt.is_flat, self._coord.last_grid_fill_at
        ):
            return

        price, qty = self._dca.compute_order(
            mkt.best_bid, self._cfg.price_decimals, self._cfg.qty_decimals
        )
        if qty <= _ZERO:
            return

        # Budget check (account for committed cost of active grid orders)
        grid_committed = sum(
            lv.price * lv.quantity for lv in self._grid.active_levels()
        )
        cost = price * qty
        if self._coord.daily_budget_remaining(now) - grid_committed < cost:
            logger.debug("DCA skip: daily budget insufficient")
            return
        # Balance check
        if available_quote - grid_committed < cost:
            logger.info("DCA skip: insufficient balance (need=%s, available=%s)", cost, available_quote)
            return

        client_id = str(uuid.uuid4())
        order_id = self._exec.place_buy(price, qty, client_id, dry_run=self._dry_run)
        if order_id:
            self._dca.state.current_order_id = order_id
            self._dca.state.current_order_placed_at = now
            self._dca.state.current_order_price = price
            self._dca.state.current_order_qty = qty
            self._dca.state.last_attempt_at = now

    def _log_status(self, mkt: MarketState, now: float) -> None:
        """Log observability snapshot."""
        grid_active = len(self._grid.active_levels())
        grid_pending = len(self._grid.pending_levels())
        grid_filled = sum(1 for lv in self._grid.state.levels if lv.filled)
        bv = self._vwap.bot_vwap(now)
        mv = self._vwap.market_vwap(now)
        remaining = self._coord.daily_budget_remaining(now)

        logger.info(
            "STATUS cycle=%d mid=%s ema=%s spread=%s atr=%s flat=%s | "
            "grid: active=%d pending=%d filled=%d total_base=%s | "
            "dca: spent=%s/%s total_base=%s | "
            "vwap: bot=%s market=%s | "
            "budget: remaining=%s | "
            "impact: paused=%s triggers=%d",
            self._cycle_count,
            mkt.mid_price,
            mkt.ema_price,
            mkt.spread_pct,
            mkt.atr,
            mkt.is_flat,
            grid_active,
            grid_pending,
            grid_filled,
            self._grid.state.total_filled_base,
            self._dca.state.daily_spent_quote,
            self._cfg.dca.budget_daily,
            self._dca.state.total_filled_base,
            bv,
            mv,
            remaining,
            self._impact.state.paused,
            self._impact.state.trigger_count,
        )


# ---------------------------------------------------------------------------
# Config loader helper
# ---------------------------------------------------------------------------


def load_config_from_dict(raw: dict[str, Any]) -> AccumulationConfig:
    """Build AccumulationConfig from a flat/nested config dict (e.g. YAML)."""
    g = raw["grid"]
    d = raw["dca"]
    gu = raw["guards"]
    v = raw["vwap"]
    e = raw["ema"]

    return AccumulationConfig(
        symbol=raw["symbol"],
        grid=GridParams(
            n=int(g["n"]),
            d0=Decimal(str(g["d0"])),
            g=Decimal(str(g["g"])),
            s0=Decimal(str(g["s0"])),
            k=Decimal(str(g["k"])),
            per_order_volume_cap=Decimal(str(g["per_order_volume_cap"])),
        ),
        dca=DCAParams(
            budget_daily=Decimal(str(d["budget_daily"])),
            interval_sec=float(d["interval_sec"]),
            epsilon=Decimal(str(d["epsilon"])),
            ttl_sec=float(d["ttl_sec"]),
        ),
        guards=GuardParams(
            participation_cap=Decimal(str(gu["participation_cap"])),
            spread_limit=Decimal(str(gu["spread_limit"])),
            cooldown_impact_sec=float(gu["cooldown_impact_sec"]),
            cooldown_grid_dca_sec=float(gu["cooldown_grid_dca_sec"]),
            fill_time_threshold_sec=float(gu["fill_time_threshold_sec"]),
            mid_jump_threshold=Decimal(str(gu["mid_jump_threshold"])),
            best_bid_touch_max=int(gu["best_bid_touch_max"]),
            best_bid_touch_window_sec=float(gu["best_bid_touch_window_sec"]),
            spread_widen_threshold=Decimal(str(gu["spread_widen_threshold"])),
        ),
        vwap=VWAPParams(
            window_sec=float(v["window_sec"]),
            size_reduction_factor=Decimal(str(v["size_reduction_factor"])),
            spacing_widen_factor=Decimal(str(v["spacing_widen_factor"])),
            pause_threshold=Decimal(str(v["pause_threshold"])),
        ),
        ema=EMAParams(
            ema_window_sec=float(e["ema_window_sec"]),
            ema_alpha=Decimal(str(e["ema_alpha"])),
            atr_window=int(e["atr_window"]),
            atr_flat_threshold=Decimal(str(e["atr_flat_threshold"])),
        ),
        daily_budget_quote=Decimal(str(raw["daily_budget_quote"])),
        poll_interval_sec=float(raw.get("poll_interval_sec", 5)),
        price_decimals=int(raw.get("price_decimals", 2)),
        qty_decimals=int(raw.get("qty_decimals", 6)),
        min_order_notional=Decimal(str(raw.get("min_order_notional", "1.0"))),
        mode=raw.get("mode", "live"),
    )


def describe() -> str:
    return (
        "Accumulation Infinity Grid: buy-only downward grid + passive DCA. "
        "Absorbs impatience — if the market doesn't offer cheap coins, "
        "the bot does almost nothing."
    )
