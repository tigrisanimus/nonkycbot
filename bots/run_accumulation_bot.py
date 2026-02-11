#!/usr/bin/env python3
"""
Accumulation Infinity Grid bot for nonkyc.io exchange.

Buy-only downward infinity grid combined with passive DCA.  The bot absorbs
impatience: if the market doesn't offer cheap coins, it does almost nothing.

Usage:
    # Monitor mode (no execution, just logging)
    python bots/run_accumulation_bot.py examples/accumulation_bot.yml --monitor-only

    # Dry run mode (simulated execution)
    python bots/run_accumulation_bot.py examples/accumulation_bot.yml --dry-run

    # Live trading mode
    python bots/run_accumulation_bot.py examples/accumulation_bot.yml
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

import yaml

# Add src to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

logger = logging.getLogger(__name__)

_SHUTDOWN = False


def _handle_signal(signum: int, frame: object) -> None:
    global _SHUTDOWN
    logger.info("Received signal %d, shutting down gracefully...", signum)
    _SHUTDOWN = True


def load_config(config_file: str) -> dict:
    with open(config_file, "r") as f:
        return yaml.safe_load(f)


def main() -> None:
    from engine.rest_client_factory import build_exchange_client
    from strategies.accumulation_infinity_grid import (
        AccumulationInfinityGrid,
        load_config_from_dict,
    )
    from utils.logging_config import setup_logging

    parser = argparse.ArgumentParser(
        description="Accumulation Infinity Grid bot (buy-only)"
    )
    parser.add_argument("config", help="Path to configuration file (YAML)")
    parser.add_argument(
        "--monitor-only",
        action="store_true",
        help="Monitor mode: log market data, no orders",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run mode: simulate order placement",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log level from config",
    )
    args = parser.parse_args()

    # Load YAML config
    raw_config = load_config(args.config)

    # Determine mode
    if args.monitor_only:
        raw_config["mode"] = "monitor"
    elif args.dry_run:
        raw_config["mode"] = "dry-run"
    else:
        raw_config["mode"] = raw_config.get("mode", "live")

    # Setup logging
    log_level = args.log_level or raw_config.get("log_level", "INFO")
    log_file = raw_config.get("log_file")
    setup_logging(level=log_level, log_file=log_file)

    mode = raw_config["mode"]
    logger.info("=== Accumulation Infinity Grid Bot ===")
    logger.info("Mode: %s", mode)
    logger.info("Config: %s", args.config)
    logger.info("Symbol: %s", raw_config.get("symbol", "?"))

    # Build exchange client
    exchange = build_exchange_client(raw_config)

    # Build strategy config
    strategy_config = load_config_from_dict(raw_config)

    # State persistence
    state_path_str = raw_config.get("state_path", "state/accumulation_bot_state.json")
    state_path = Path(state_path_str)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    # Create strategy instance
    strategy = AccumulationInfinityGrid(
        client=exchange,
        config=strategy_config,
        state_path=state_path,
    )
    strategy.load_state()

    logger.info("State path: %s", state_path)
    logger.info("Poll interval: %ss", strategy_config.poll_interval_sec)
    logger.info(
        "Grid levels: N=%d, d0=%s, g=%s",
        strategy_config.grid.n,
        strategy_config.grid.d0,
        strategy_config.grid.g,
    )
    logger.info(
        "DCA budget: %s/day, interval=%ss",
        strategy_config.dca.budget_daily,
        strategy_config.dca.interval_sec,
    )
    logger.info("Daily budget cap: %s", strategy_config.daily_budget_quote)
    logger.info("Bot started. Press Ctrl+C to stop.")

    # Signal handling for graceful shutdown
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Main loop
    poll_sec = strategy_config.poll_interval_sec
    while not _SHUTDOWN:
        try:
            strategy.poll_once()
        except KeyboardInterrupt:
            break
        except Exception:
            logger.exception("Error in poll cycle")

        # Sleep with early exit on shutdown
        sleep_until = time.time() + poll_sec
        while time.time() < sleep_until and not _SHUTDOWN:
            time.sleep(min(1.0, sleep_until - time.time()))

    # Final state save
    logger.info("Saving final state...")
    strategy.save_state()
    logger.info("Accumulation bot stopped.")


if __name__ == "__main__":
    main()
