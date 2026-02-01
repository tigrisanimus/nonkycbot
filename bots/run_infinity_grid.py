#!/usr/bin/env python3
"""
Infinity Grid bot - grid trading with no upper limit.

Like standard ladder grid but with unlimited upside:
- Places buy orders below current price (with lower limit)
- Places sell orders above current price (NO upper limit)
- When sell order fills, places new sell order above highest
- Continuously extends the sell ladder as price rises

Usage:
    # Monitor mode (no execution, just logging)
    python bots/run_infinity_grid.py examples/infinity_grid.yml --monitor-only

    # Live trading mode
    python bots/run_infinity_grid.py examples/infinity_grid.yml

    # Dry run mode (simulated execution)
    python bots/run_infinity_grid.py examples/infinity_grid.yml --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from decimal import Decimal
from pathlib import Path

import yaml

# Add src to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

LOGGER = logging.getLogger("nonkyc_bot.infinity_grid")


def build_config(raw_config: dict):
    """Build config from raw dict."""
    from strategies.infinity_ladder_grid import InfinityLadderGridConfig

    symbol = raw_config.get("symbol", "BTC_USDT")
    step_mode = raw_config.get("step_mode", "pct")
    step_pct = Decimal(str(raw_config["step_pct"])) if step_mode == "pct" else None
    step_abs = Decimal(str(raw_config["step_abs"])) if step_mode == "abs" else None

    return InfinityLadderGridConfig(
        symbol=symbol,
        step_mode=step_mode,
        step_pct=step_pct,
        step_abs=step_abs,
        n_buy_levels=int(raw_config.get("n_buy_levels", 10)),
        initial_sell_levels=int(raw_config.get("initial_sell_levels", 10)),
        base_order_size=Decimal(str(raw_config.get("base_order_size", "0.001"))),
        min_notional_quote=Decimal(str(raw_config.get("min_notional_quote", "1.0"))),
        fee_buffer_pct=Decimal(str(raw_config.get("fee_buffer_pct", "0.0001"))),
        total_fee_rate=Decimal(str(raw_config.get("total_fee_rate", "0.002"))),
        tick_size=Decimal(str(raw_config.get("tick_size", "0.01"))),
        step_size=Decimal(str(raw_config.get("step_size", "0.00000001"))),
        poll_interval_sec=float(raw_config.get("poll_interval_sec", 60.0)),
        fetch_backoff_sec=float(raw_config.get("fetch_backoff_sec", 15.0)),
        startup_cancel_all=bool(raw_config.get("startup_cancel_all", False)),
        startup_rebalance=bool(raw_config.get("startup_rebalance", False)),
        rebalance_target_base_pct=Decimal(
            str(raw_config.get("rebalance_target_base_pct", "0.5"))
        ),
        rebalance_slippage_pct=Decimal(
            str(raw_config.get("rebalance_slippage_pct", "0.002"))
        ),
        rebalance_max_attempts=int(raw_config.get("rebalance_max_attempts", 2)),
        reconcile_interval_sec=float(raw_config.get("reconcile_interval_sec", 60.0)),
        balance_refresh_sec=float(raw_config.get("balance_refresh_sec", 60.0)),
        mode=raw_config.get("mode", "live"),
        extend_buy_levels_on_restart=bool(
            raw_config.get("extend_buy_levels_on_restart", False)
        ),
    )


def run_infinity_grid(config: dict, state_path: str) -> None:
    """Run infinity grid bot."""
    from engine.rest_client_factory import build_exchange_client
    from strategies.infinity_ladder_grid import InfinityLadderGridStrategy

    # Build exchange client using centralized factory
    client = build_exchange_client(config)

    # Build grid config
    grid_config = build_config(config)

    # Create strategy
    strategy = InfinityLadderGridStrategy(
        config=grid_config,
        client=client,
        state_path=Path(state_path),
    )

    # Cancel existing orders if requested
    if grid_config.startup_cancel_all:
        LOGGER.info("Cancelling all existing orders...")
        try:
            client.cancel_all_orders()
            time.sleep(2)
        except Exception as exc:
            LOGGER.warning(f"Failed to cancel all orders: {exc}")

    # Seed the grid
    LOGGER.info("Seeding infinity grid...")
    strategy.seed_ladder()

    # Main loop
    LOGGER.info(
        f"Infinity grid running. Press Ctrl+C to stop. "
        f"symbol={grid_config.symbol} poll_interval={grid_config.poll_interval_sec}s"
    )

    last_reconcile = time.time()

    try:
        while True:
            now = time.time()

            # Reconcile (check for fills and refill)
            if now - last_reconcile >= grid_config.reconcile_interval_sec:
                strategy.reconcile(now)
                last_reconcile = now

            time.sleep(grid_config.poll_interval_sec)

    except KeyboardInterrupt:
        LOGGER.info("\nShutting down...")
        LOGGER.info(f"Total profit: {strategy.state.total_profit_quote}")


def run_infinity_grid_from_file(config_path: str) -> None:
    """Load config and run infinity grid."""
    with open(config_path) as f:
        config = yaml.safe_load(f)
    state_path = config.get("state_path", "state/infinity_grid_state.json")
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    run_infinity_grid(config, state_path)


def main() -> None:
    """Main entry point."""
    from utils.logging_config import setup_logging

    parser = argparse.ArgumentParser(description="Infinity Grid trading bot")
    parser.add_argument("config", help="Path to configuration file (YAML)")
    parser.add_argument(
        "--monitor-only",
        action="store_true",
        help="Monitor mode only (no execution)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode (simulated execution)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    args = parser.parse_args()

    # Setup logging
    setup_logging(level=args.log_level)

    # Load config and set mode
    with open(args.config) as f:
        config = yaml.safe_load(f)

    if args.monitor_only:
        config["mode"] = "monitor"
    elif args.dry_run:
        config["mode"] = "dry-run"
    else:
        config["mode"] = config.get("mode", "live")

    state_path = config.get("state_path", "state/infinity_grid_state.json")
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    run_infinity_grid(config, state_path)


if __name__ == "__main__":
    main()
