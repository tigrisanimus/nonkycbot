#!/usr/bin/env python3
"""
Market maker bot - fee-aware spread capture with inventory skewing.

Usage:
    # Monitor mode (no execution, just logging)
    python bots/run_market_maker.py examples/market_maker.yml --monitor-only

    # Live trading mode
    python bots/run_market_maker.py examples/market_maker.yml

    # Dry run mode (simulated execution)
    python bots/run_market_maker.py examples/market_maker.yml --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def load_config(config_file: str) -> dict:
    with open(config_file, "r") as handle:
        return yaml.safe_load(handle)


def run_market_maker_from_file(config_file: str) -> None:
    from engine.market_maker_runner import run_market_maker

    config = load_config(config_file)
    state_path = Path(config.get("state_path", "state/market_maker_state.json"))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    run_market_maker(config, state_path)


def main() -> None:
    """Main entry point."""
    from engine.market_maker_runner import run_market_maker
    from utils.logging_config import setup_logging

    parser = argparse.ArgumentParser(description="Market maker bot")
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

    setup_logging(level=args.log_level)

    config = load_config(args.config)
    if args.monitor_only:
        config["mode"] = "monitor"
    elif args.dry_run:
        config["mode"] = "dry-run"
    else:
        config["mode"] = config.get("mode", "live")

    state_path = Path(config.get("state_path", "state/market_maker_state.json"))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    run_market_maker(config, state_path)


if __name__ == "__main__":
    main()
