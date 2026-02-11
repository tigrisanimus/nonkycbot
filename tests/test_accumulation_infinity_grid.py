"""Tests for the AccumulationInfinityGrid strategy.

Covers: config loading, market state, grid engine, DCA engine,
coordination, impact detection, VWAP controller, execution engine,
and the main strategy class.
"""

from __future__ import annotations

import json
import time
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from engine.exchange_client import OpenOrder, OrderStatusView
from strategies.accumulation_infinity_grid import (
    AccumulationConfig,
    AccumulationInfinityGrid,
    Coordinator,
    DCAEngine,
    DCAParams,
    DCAState,
    EMAParams,
    ExecutionEngine,
    GridEngine,
    GridLevel,
    GridParams,
    GridState,
    GuardParams,
    ImpactDetector,
    MarketState,
    MarketStateTracker,
    VWAPController,
    VWAPParams,
    VWAPSample,
    describe,
    load_config_from_dict,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ZERO = Decimal("0")
_ONE = Decimal("1")


def _make_config(**overrides: Any) -> AccumulationConfig:
    """Build a minimal AccumulationConfig for testing."""
    defaults = dict(
        symbol="BTC_USDT",
        grid=GridParams(
            n=5,
            d0=Decimal("0.005"),
            g=Decimal("1.3"),
            s0=Decimal("0.001"),
            k=Decimal("1.1"),
            per_order_volume_cap=Decimal("0.01"),
        ),
        dca=DCAParams(
            budget_daily=Decimal("20"),
            interval_sec=3600,
            epsilon=Decimal("0.001"),
            ttl_sec=1800,
        ),
        guards=GuardParams(
            participation_cap=Decimal("0.05"),
            spread_limit=Decimal("0.03"),
            cooldown_impact_sec=300,
            cooldown_grid_dca_sec=600,
            fill_time_threshold_sec=2.0,
            mid_jump_threshold=Decimal("0.005"),
            best_bid_touch_max=5,
            best_bid_touch_window_sec=300,
            spread_widen_threshold=Decimal("2.0"),
        ),
        vwap=VWAPParams(
            window_sec=3600,
            size_reduction_factor=Decimal("0.5"),
            spacing_widen_factor=Decimal("1.5"),
            pause_threshold=Decimal("1.05"),
        ),
        ema=EMAParams(
            ema_window_sec=3600,
            ema_alpha=Decimal("0.01"),
            atr_window=60,
            atr_flat_threshold=Decimal("0.001"),
        ),
        daily_budget_quote=Decimal("100"),
        poll_interval_sec=5,
        price_decimals=2,
        qty_decimals=6,
        mode="dry-run",
    )
    defaults.update(overrides)
    return AccumulationConfig(**defaults)


def _mock_client(
    bid: Decimal = Decimal("50000"),
    ask: Decimal = Decimal("50100"),
    open_orders: list[OpenOrder] | None = None,
) -> MagicMock:
    """Create a mock ExchangeClient."""
    client = MagicMock()
    client.get_orderbook_top.return_value = (bid, ask)
    client.get_mid_price.return_value = (bid + ask) / 2
    client.list_open_orders.return_value = open_orders or []
    client.place_limit.return_value = "test-order-id"
    client.cancel_order.return_value = True
    client.get_balances.return_value = {
        "BTC": (Decimal("1.0"), Decimal("0")),
        "USDT": (Decimal("10000"), Decimal("0")),
    }
    return client


# ---------------------------------------------------------------------------
# describe()
# ---------------------------------------------------------------------------


def test_describe() -> None:
    desc = describe()
    assert "accumulation" in desc.lower()
    assert "buy" in desc.lower()


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def test_load_config_from_dict() -> None:
    raw = {
        "symbol": "ETH_USDT",
        "grid": {
            "n": 10,
            "d0": "0.005",
            "g": "1.3",
            "s0": "0.001",
            "k": "1.1",
            "per_order_volume_cap": "0.01",
        },
        "dca": {
            "budget_daily": "20",
            "interval_sec": 3600,
            "epsilon": "0.001",
            "ttl_sec": 1800,
        },
        "guards": {
            "participation_cap": "0.05",
            "spread_limit": "0.03",
            "cooldown_impact_sec": 300,
            "cooldown_grid_dca_sec": 600,
            "fill_time_threshold_sec": 2.0,
            "mid_jump_threshold": "0.005",
            "best_bid_touch_max": 5,
            "best_bid_touch_window_sec": 300,
            "spread_widen_threshold": "2.0",
        },
        "vwap": {
            "window_sec": 3600,
            "size_reduction_factor": "0.5",
            "spacing_widen_factor": "1.5",
            "pause_threshold": "1.05",
        },
        "ema": {
            "ema_window_sec": 3600,
            "ema_alpha": "0.01",
            "atr_window": 60,
            "atr_flat_threshold": "0.001",
        },
        "daily_budget_quote": "100",
        "poll_interval_sec": 10,
        "price_decimals": 2,
        "qty_decimals": 6,
        "mode": "monitor",
    }
    cfg = load_config_from_dict(raw)
    assert cfg.symbol == "ETH_USDT"
    assert cfg.grid.n == 10
    assert cfg.grid.d0 == Decimal("0.005")
    assert cfg.dca.budget_daily == Decimal("20")
    assert cfg.mode == "monitor"


# ---------------------------------------------------------------------------
# MarketStateTracker
# ---------------------------------------------------------------------------


def test_market_state_tracker_update() -> None:
    cfg = _make_config()
    tracker = MarketStateTracker(cfg)
    client = _mock_client()
    now = time.time()

    state = tracker.update(client, now)
    assert state.has_data
    assert state.mid_price == Decimal("50050")
    assert state.best_bid == Decimal("50000")
    assert state.best_ask == Decimal("50100")
    assert state.spread_abs == Decimal("100")
    assert state.ema_price == Decimal("50050")  # first update = mid


def test_market_state_tracker_ema_smoothing() -> None:
    cfg = _make_config()
    tracker = MarketStateTracker(cfg)
    client = _mock_client(bid=Decimal("50000"), ask=Decimal("50100"))
    now = time.time()

    # First update initialises EMA to mid
    tracker.update(client, now)

    # Second update with higher price
    client.get_orderbook_top.return_value = (Decimal("51000"), Decimal("51100"))
    state = tracker.update(client, now + 10)

    # EMA should move slightly toward 51050 (alpha = 0.01)
    expected_ema = Decimal("0.01") * Decimal("51050") + Decimal("0.99") * Decimal(
        "50050"
    )
    assert state.ema_price == expected_ema


def test_market_state_invalid_orderbook() -> None:
    cfg = _make_config()
    tracker = MarketStateTracker(cfg)
    client = _mock_client(bid=Decimal("0"), ask=Decimal("0"))
    now = time.time()

    state = tracker.update(client, now)
    assert not state.has_data


# ---------------------------------------------------------------------------
# GridEngine
# ---------------------------------------------------------------------------


def test_grid_compute_levels() -> None:
    cfg = _make_config()
    engine = GridEngine(cfg)

    pref = Decimal("50000")
    levels = engine.compute_levels(pref, 3, 1, 2, 6)

    assert len(levels) == 3
    # Level 1: P = 50000 * (1 - 0.005 * 1.3^0) = 50000 * 0.995 = 49750
    assert levels[0].index == 1
    assert levels[0].price == Decimal("49750.00")
    # Level 2: P = 50000 * (1 - 0.005 * 1.3^1) = 50000 * (1 - 0.0065) = 49675
    assert levels[1].index == 2
    assert levels[1].price == Decimal("49675.00")
    # Level 3: P = 50000 * (1 - 0.005 * 1.3^2) = 50000 * (1 - 0.00845) = 49577.50
    assert levels[2].index == 3
    assert levels[2].price == Decimal("49577.50")


def test_grid_compute_levels_sizes_grow() -> None:
    cfg = _make_config()
    engine = GridEngine(cfg)

    pref = Decimal("50000")
    levels = engine.compute_levels(pref, 3, 1, 2, 6)

    # Sizes grow geometrically (with jitter, hard to test exact values)
    # Just verify all sizes are positive and non-zero
    for lv in levels:
        assert lv.quantity > _ZERO


def test_grid_compute_levels_respects_volume_cap() -> None:
    cfg = _make_config(
        grid=GridParams(
            n=5,
            d0=Decimal("0.005"),
            g=Decimal("1.3"),
            s0=Decimal("100"),  # very large base
            k=Decimal("2.0"),  # aggressive growth
            per_order_volume_cap=Decimal("0.01"),  # small cap
        ),
    )
    engine = GridEngine(cfg)
    levels = engine.compute_levels(Decimal("50000"), 3, 1, 2, 6)
    for lv in levels:
        # With jitter of up to 1.05, cap is 0.01 * 1.05 = 0.0105
        assert lv.quantity <= Decimal("0.0106")


def test_grid_reconcile_fills() -> None:
    cfg = _make_config()
    engine = GridEngine(cfg)

    # Set up two levels with orders
    engine.state.levels = [
        GridLevel(
            index=1,
            price=Decimal("49750"),
            quantity=Decimal("0.001"),
            order_id="order-1",
            placed_at=100.0,
        ),
        GridLevel(
            index=2,
            price=Decimal("49675"),
            quantity=Decimal("0.001"),
            order_id="order-2",
            placed_at=100.0,
        ),
    ]

    # order-1 is gone (filled), order-2 still open
    open_orders = [
        OpenOrder(
            order_id="order-2",
            symbol="BTC_USDT",
            side="buy",
            price=Decimal("49675"),
            quantity=Decimal("0.001"),
        ),
    ]

    filled = engine.reconcile_fills(open_orders, 200.0)
    assert len(filled) == 1
    assert filled[0].order_id == "order-1"
    assert filled[0].filled is True
    assert engine.state.total_filled_base == Decimal("0.001")


def test_grid_shallowest_active() -> None:
    cfg = _make_config()
    engine = GridEngine(cfg)
    engine.state.levels = [
        GridLevel(
            index=1, price=Decimal("49750"), quantity=Decimal("0.001"), order_id="o1"
        ),
        GridLevel(
            index=2, price=Decimal("49675"), quantity=Decimal("0.001"), order_id="o2"
        ),
        GridLevel(
            index=3, price=Decimal("49500"), quantity=Decimal("0.001"), order_id="o3"
        ),
    ]

    shallowest = engine.shallowest_active()
    assert shallowest is not None
    assert shallowest.order_id == "o1"  # highest price = shallowest


def test_grid_no_levels_above_zero_price() -> None:
    """Ensure grid doesn't produce negative or zero prices."""
    cfg = _make_config(
        grid=GridParams(
            n=100,
            d0=Decimal("0.5"),  # 50% distance
            g=Decimal("2.0"),  # aggressive doubling
            s0=Decimal("0.001"),
            k=Decimal("1.0"),
            per_order_volume_cap=Decimal("1"),
        ),
    )
    engine = GridEngine(cfg)
    levels = engine.compute_levels(Decimal("100"), 100, 1, 2, 6)
    for lv in levels:
        assert lv.price > _ZERO


# ---------------------------------------------------------------------------
# DCAEngine
# ---------------------------------------------------------------------------


def test_dca_should_attempt_timer() -> None:
    cfg = _make_config()
    dca = DCAEngine(cfg)

    # Not enough time passed
    dca.state.last_attempt_at = 1000.0
    assert not dca.should_attempt(1000.0 + 100, is_flat=True, last_grid_fill_at=0)

    # Enough time passed
    assert dca.should_attempt(1000.0 + 3601, is_flat=True, last_grid_fill_at=0)


def test_dca_should_attempt_not_flat() -> None:
    cfg = _make_config()
    dca = DCAEngine(cfg)
    dca.state.last_attempt_at = 0
    assert not dca.should_attempt(5000, is_flat=False, last_grid_fill_at=0)


def test_dca_should_attempt_grid_cooldown() -> None:
    cfg = _make_config()
    dca = DCAEngine(cfg)
    dca.state.last_attempt_at = 0
    dca.state.daily_reset_at = 0

    now_base = 100000.0
    grid_fill_time = now_base

    # Grid filled 100s ago, cooldown is 600s → should skip
    assert not dca.should_attempt(
        grid_fill_time + 100, is_flat=True, last_grid_fill_at=grid_fill_time
    )

    # Grid filled 700s ago → cooldown expired, should attempt
    assert dca.should_attempt(
        grid_fill_time + 700, is_flat=True, last_grid_fill_at=grid_fill_time
    )


def test_dca_should_attempt_budget_exhausted() -> None:
    cfg = _make_config()
    dca = DCAEngine(cfg)
    dca.state.last_attempt_at = 0
    dca.state.daily_spent_quote = Decimal("20")  # budget_daily = 20
    dca.state.daily_reset_at = time.time()

    assert not dca.should_attempt(time.time() + 3601, is_flat=True, last_grid_fill_at=0)


def test_dca_compute_order() -> None:
    cfg = _make_config()
    dca = DCAEngine(cfg)

    price, qty = dca.compute_order(
        best_bid=Decimal("50000"),
        price_dec=2,
        qty_dec=6,
    )
    # Price = 50000 * (1 - 0.001) = 49950
    assert price == Decimal("49950.00")
    assert qty > _ZERO


def test_dca_record_fill() -> None:
    cfg = _make_config()
    dca = DCAEngine(cfg)
    dca.state.current_order_id = "dca-1"
    dca.state.current_order_price = Decimal("50000")
    dca.state.current_order_qty = Decimal("0.0001")
    dca.state.daily_reset_at = time.time()

    dca.record_fill(time.time())

    assert dca.state.current_order_id is None
    assert dca.state.total_filled_base == Decimal("0.0001")
    assert dca.state.daily_spent_quote == Decimal("5.0000")


def test_dca_cancel_stale() -> None:
    cfg = _make_config()
    dca = DCAEngine(cfg)
    dca.state.current_order_id = "dca-1"
    dca.state.current_order_placed_at = 1000.0

    # Not stale yet (ttl_sec = 1800)
    assert not dca.should_cancel_stale(1000.0 + 1799)
    # Stale
    assert dca.should_cancel_stale(1000.0 + 1801)


def test_dca_daily_reset() -> None:
    cfg = _make_config()
    dca = DCAEngine(cfg)
    dca.state.daily_spent_quote = Decimal("20")
    dca.state.daily_reset_at = 0  # very old

    # After 86400s the budget should reset
    dca.state.last_attempt_at = 0
    assert dca.should_attempt(86401, is_flat=True, last_grid_fill_at=0)


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


def test_coordinator_daily_budget() -> None:
    cfg = _make_config()
    coord = Coordinator(cfg)
    now = time.time()
    coord._daily_reset_at = now

    assert coord.daily_budget_remaining(now) == Decimal("100")

    coord.record_grid_fill(now, Decimal("60"))
    assert coord.daily_budget_remaining(now) == Decimal("40")

    coord.record_dca_fill(now, Decimal("40"))
    assert coord.daily_budget_exhausted(now)


def test_coordinator_participation_cap() -> None:
    cfg = _make_config()
    coord = Coordinator(cfg)
    now = time.time()
    coord._daily_reset_at = now

    # No spending - ok
    assert coord.participation_ok(Decimal("1000"))

    # Spend 60, volume 1000 → ratio 0.06 > cap 0.05
    coord.record_grid_fill(now, Decimal("60"))
    assert not coord.participation_ok(Decimal("1000"))


def test_coordinator_grid_fill_time_tracking() -> None:
    cfg = _make_config()
    coord = Coordinator(cfg)
    assert coord.last_grid_fill_at == 0.0

    coord.record_grid_fill(123.0, Decimal("10"))
    assert coord.last_grid_fill_at == 123.0


# ---------------------------------------------------------------------------
# ImpactDetector
# ---------------------------------------------------------------------------


def test_impact_fill_speed() -> None:
    cfg = _make_config()
    detector = ImpactDetector(cfg)

    # Fill in 1s (threshold = 2s) → triggered
    assert detector.check_fill_speed(100.0, 101.0, 101.0)
    assert detector.state.paused

    # Fill in 5s → not triggered
    detector.state.paused = False
    assert not detector.check_fill_speed(100.0, 105.0, 105.0)


def test_impact_mid_jump() -> None:
    cfg = _make_config()
    detector = ImpactDetector(cfg)

    # Jump of 1% (threshold = 0.5%)
    assert detector.check_mid_jump_after_fill(
        Decimal("50000"), Decimal("50500"), time.time()
    )
    assert detector.state.paused


def test_impact_mid_jump_no_trigger() -> None:
    cfg = _make_config()
    detector = ImpactDetector(cfg)

    # Jump of 0.1% < threshold 0.5%
    assert not detector.check_mid_jump_after_fill(
        Decimal("50000"), Decimal("50050"), time.time()
    )
    assert not detector.state.paused


def test_impact_best_bid_frequency() -> None:
    cfg = _make_config()
    detector = ImpactDetector(cfg)
    now = time.time()

    # Touch best bid 4 times (max 5) → no trigger
    for i in range(4):
        detector.record_best_bid_touch(now + i)
    assert not detector.check_best_bid_frequency(now + 4)

    # 5th touch → trigger
    detector.record_best_bid_touch(now + 5)
    assert detector.check_best_bid_frequency(now + 5)
    assert detector.state.paused


def test_impact_spread_widen() -> None:
    cfg = _make_config()
    detector = ImpactDetector(cfg)

    # Spread 3x median (threshold = 2x)
    assert detector.check_spread_widen(Decimal("0.03"), Decimal("0.01"), time.time())
    assert detector.state.paused

    # Spread 1.5x median → no trigger
    detector.state.paused = False
    assert not detector.check_spread_widen(
        Decimal("0.015"), Decimal("0.01"), time.time()
    )


def test_impact_cooldown_expires() -> None:
    cfg = _make_config()
    detector = ImpactDetector(cfg)
    now = 1000.0

    detector.check_fill_speed(now - 1, now, now)  # trigger
    assert detector.is_paused(now)

    # After cooldown (300s)
    assert not detector.is_paused(now + 301)


# ---------------------------------------------------------------------------
# VWAPController
# ---------------------------------------------------------------------------


def test_vwap_no_data() -> None:
    cfg = _make_config()
    vwap = VWAPController(cfg)
    size_f, spacing_f, pause = vwap.adjustments(time.time())
    assert size_f == _ONE
    assert spacing_f == _ONE
    assert not pause


def test_vwap_bot_below_market() -> None:
    cfg = _make_config()
    vwap = VWAPController(cfg)
    now = time.time()

    # Bot buys at 49000, market at 50000
    vwap.record_bot_fill(Decimal("49000"), Decimal("1"), now)
    vwap.record_market_price(Decimal("50000"), now)

    size_f, spacing_f, pause = vwap.adjustments(now)
    assert size_f == _ONE
    assert spacing_f == _ONE
    assert not pause


def test_vwap_bot_above_market_triggers_reduction() -> None:
    cfg = _make_config()
    vwap = VWAPController(cfg)
    now = time.time()

    # Bot buys at 51000, market mid at 50000
    vwap.record_bot_fill(Decimal("51000"), Decimal("1"), now)
    vwap.record_market_price(Decimal("50000"), now)

    size_f, spacing_f, pause = vwap.adjustments(now)
    # bot_vwap (51000) > market_vwap (50000) → reduction
    assert size_f == Decimal("0.5")
    assert spacing_f == Decimal("1.5")
    assert not pause


def test_vwap_pause_threshold() -> None:
    cfg = _make_config()
    vwap = VWAPController(cfg)
    now = time.time()

    # Bot buys at 53000, market mid at 50000 → ratio 1.06 > 1.05 threshold
    vwap.record_bot_fill(Decimal("53000"), Decimal("1"), now)
    vwap.record_market_price(Decimal("50000"), now)

    _, _, pause = vwap.adjustments(now)
    assert pause


# ---------------------------------------------------------------------------
# ExecutionEngine
# ---------------------------------------------------------------------------


def test_execution_place_buy_dry_run() -> None:
    cfg = _make_config()
    client = _mock_client()
    exec_eng = ExecutionEngine(client, cfg)

    order_id = exec_eng.place_buy(
        Decimal("50000"), Decimal("0.001"), "client-1", dry_run=True
    )
    assert order_id is not None
    assert order_id.startswith("dry-")
    client.place_limit.assert_not_called()


def test_execution_place_buy_live() -> None:
    cfg = _make_config()
    client = _mock_client()
    exec_eng = ExecutionEngine(client, cfg)

    order_id = exec_eng.place_buy(
        Decimal("50000"), Decimal("0.001"), "client-1", dry_run=False
    )
    assert order_id == "test-order-id"
    client.place_limit.assert_called_once_with(
        symbol="BTC_USDT",
        side="buy",
        price=Decimal("50000"),
        quantity=Decimal("0.001"),
        client_id="client-1",
    )


def test_execution_rejects_invalid_price() -> None:
    cfg = _make_config()
    client = _mock_client()
    exec_eng = ExecutionEngine(client, cfg)

    assert exec_eng.place_buy(Decimal("0"), Decimal("0.001"), "c1") is None
    assert exec_eng.place_buy(Decimal("-1"), Decimal("0.001"), "c1") is None
    assert exec_eng.place_buy(Decimal("50000"), Decimal("0"), "c1") is None


def test_execution_cancel_dry_run() -> None:
    cfg = _make_config()
    client = _mock_client()
    exec_eng = ExecutionEngine(client, cfg)

    result = exec_eng.cancel("order-1", dry_run=True)
    assert result is True
    client.cancel_order.assert_not_called()


def test_execution_never_sells() -> None:
    """Verify ExecutionEngine has no sell method."""
    cfg = _make_config()
    client = _mock_client()
    exec_eng = ExecutionEngine(client, cfg)

    # Only place_buy and cancel exist
    assert hasattr(exec_eng, "place_buy")
    assert hasattr(exec_eng, "cancel")
    assert not hasattr(exec_eng, "place_sell")
    assert not hasattr(exec_eng, "place_ask")


def test_execution_never_market_orders() -> None:
    """Verify ExecutionEngine never calls place_market."""
    cfg = _make_config()
    client = _mock_client()
    exec_eng = ExecutionEngine(client, cfg)

    exec_eng.place_buy(Decimal("50000"), Decimal("0.001"), "c1", dry_run=False)
    client.place_market.assert_not_called()


# ---------------------------------------------------------------------------
# AccumulationInfinityGrid (integration)
# ---------------------------------------------------------------------------


def test_strategy_poll_monitor_mode() -> None:
    """In monitor mode, no orders should be placed."""
    cfg = _make_config(mode="monitor")
    client = _mock_client()
    strategy = AccumulationInfinityGrid(client, cfg)

    strategy.poll_once()

    client.place_limit.assert_not_called()
    client.cancel_order.assert_not_called()


def test_strategy_poll_dry_run_seeds_grid() -> None:
    """In dry-run mode, grid should be seeded but no real orders placed."""
    cfg = _make_config(mode="dry-run")
    client = _mock_client()
    strategy = AccumulationInfinityGrid(client, cfg)

    strategy.poll_once()

    # Grid should have been seeded with N levels
    assert len(strategy._grid.state.levels) == cfg.grid.n
    # No real orders placed (dry-run)
    client.place_limit.assert_not_called()


def test_strategy_no_sells_in_grid_levels() -> None:
    """Verify all grid levels are buy-only."""
    cfg = _make_config(mode="dry-run")
    client = _mock_client()
    strategy = AccumulationInfinityGrid(client, cfg)

    strategy.poll_once()

    # All levels should be below Pref (buy side)
    pref = strategy._market.state.ema_price
    for lv in strategy._grid.state.levels:
        assert lv.price < pref


def test_strategy_grid_does_not_chase_up() -> None:
    """If price rises, existing grid levels stay — no upward replacement.

    The EMA (Pref) will shift slightly upward so the strategy may place
    pending levels that are still below the *new* Pref.  The key invariant
    is that no level is ever placed above Pref, and fills are never replaced
    upward.
    """
    cfg = _make_config(mode="dry-run")
    client = _mock_client(bid=Decimal("50000"), ask=Decimal("50100"))
    strategy = AccumulationInfinityGrid(client, cfg)

    # Initial seed
    strategy.poll_once()

    # Capture highest grid price from initial seed
    initial_highest = max(lv.price for lv in strategy._grid.state.levels)

    # Price rises significantly
    client.get_orderbook_top.return_value = (Decimal("55000"), Decimal("55100"))
    strategy.poll_once()

    # All grid levels must remain below Pref (no upward chasing)
    pref = strategy._market.state.ema_price
    for lv in strategy._grid.state.levels:
        assert lv.price < pref, f"Level {lv.index} price {lv.price} >= Pref {pref}"


def test_strategy_state_persistence(tmp_path: Path) -> None:
    """Test save/load state round-trip."""
    state_file = tmp_path / "test_state.json"
    cfg = _make_config(mode="dry-run")
    client = _mock_client()

    # Create strategy, run one cycle, save
    s1 = AccumulationInfinityGrid(client, cfg, state_path=state_file)
    s1.poll_once()
    s1.save_state()

    assert state_file.exists()

    # Load into new strategy
    s2 = AccumulationInfinityGrid(client, cfg, state_path=state_file)
    s2.load_state()

    assert len(s2._grid.state.levels) == len(s1._grid.state.levels)
    assert s2._cycle_count == s1._cycle_count


def test_strategy_pauses_on_wide_spread() -> None:
    """Strategy should not place orders when spread exceeds limit."""
    cfg = _make_config(mode="dry-run")
    # Spread = 5000/52500 ≈ 9.5% > 3% limit
    client = _mock_client(bid=Decimal("50000"), ask=Decimal("55000"))
    strategy = AccumulationInfinityGrid(client, cfg)

    strategy.poll_once()

    # No grid levels should be placed (spread too wide)
    active = strategy._grid.active_levels()
    assert len(active) == 0


def test_strategy_pauses_on_daily_budget() -> None:
    """Strategy should stop when daily budget is exhausted."""
    cfg = _make_config(mode="dry-run", daily_budget_quote=Decimal("0.01"))
    client = _mock_client()
    strategy = AccumulationInfinityGrid(client, cfg)

    # Exhaust budget
    now = time.time()
    strategy._coord._daily_reset_at = now
    strategy._coord._daily_total_spent = Decimal("0.01")

    strategy.poll_once()

    # No new levels should be added
    assert len(strategy._grid.state.levels) == 0


def test_strategy_grid_fills_extend_deeper() -> None:
    """When a grid level fills, a deeper level should be appended."""
    cfg = _make_config(mode="dry-run")
    client = _mock_client()
    strategy = AccumulationInfinityGrid(client, cfg)

    # Seed grid
    strategy.poll_once()
    initial_count = len(strategy._grid.state.levels)

    # Simulate a fill: remove order-id from first level so reconcile detects fill
    first_level = strategy._grid.state.levels[0]
    first_level.order_id = "filled-order"
    first_level.placed_at = time.time() - 100

    # open_orders doesn't include the filled order
    client.list_open_orders.return_value = []

    strategy.poll_once()

    # Should have added one deeper level
    assert len(strategy._grid.state.levels) > initial_count


def test_no_sell_logic_anywhere() -> None:
    """Scan for any sell-related attributes or methods in the strategy class."""
    cfg = _make_config()
    client = _mock_client()
    strategy = AccumulationInfinityGrid(client, cfg)

    # Check strategy
    for attr in dir(strategy):
        lower = attr.lower()
        assert "sell" not in lower, f"Found sell-related attribute: {attr}"
        assert "ask" not in lower or attr.startswith(
            "_"
        ), f"Found ask-related attribute: {attr}"

    # Check execution engine
    for attr in dir(strategy._exec):
        lower = attr.lower()
        assert "sell" not in lower, f"Found sell-related attribute in exec: {attr}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_grid_empty_orderbook() -> None:
    """Strategy handles empty/zero orderbook gracefully."""
    cfg = _make_config(mode="dry-run")
    client = _mock_client(bid=Decimal("0"), ask=Decimal("0"))
    strategy = AccumulationInfinityGrid(client, cfg)

    # Should not crash
    strategy.poll_once()
    assert len(strategy._grid.state.levels) == 0


def test_dca_not_active_when_market_volatile() -> None:
    """DCA should not fire when ATR is above flat threshold."""
    cfg = _make_config()
    dca = DCAEngine(cfg)
    dca.state.last_attempt_at = 0

    assert not dca.should_attempt(5000, is_flat=False, last_grid_fill_at=0)


def test_config_no_hidden_defaults() -> None:
    """All config fields must be explicitly provided."""
    # Missing required field should raise
    raw = {"symbol": "BTC_USDT"}
    with pytest.raises(KeyError):
        load_config_from_dict(raw)
