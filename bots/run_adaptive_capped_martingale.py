#!/usr/bin/env python3
"""
Adaptive Capped Martingale bot - progressive position building with risk caps.

Starts a cycle with a base order sized as a percentage of cycle budget, then
adds positions at fixed step distances with a multiplier (capped per add).
Uses two take-profit targets to scale out of the position and stops after
a time limit to avoid runaway exposure.

Usage:
    # Monitor mode (no execution, just logging)
    python bots/run_adaptive_capped_martingale.py examples/adaptive_capped_martingale_btc_usdt.yml --monitor-only

    # Live trading mode
    python bots/run_adaptive_capped_martingale.py examples/adaptive_capped_martingale_btc_usdt.yml

    # Dry run mode (simulated execution)
    python bots/run_adaptive_capped_martingale.py examples/adaptive_capped_martingale_btc_usdt.yml --dry-run
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


def main() -> None:
    """Main entry point."""
    from engine.adaptive_capped_martingale_runner import run_adaptive_capped_martingale
    from utils.logging_config import setup_logging

    parser = argparse.ArgumentParser(
        description="Adaptive Capped Martingale trading bot"
    )
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
    config = load_config(args.config)
    if args.monitor_only:
        config["mode"] = "monitor"
    elif args.dry_run:
        config["mode"] = "dry-run"
    else:
        config["mode"] = config.get("mode", "live")

    state_path = Path(config.get("state_path", "state/martingale_state.json"))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    run_adaptive_capped_martingale(config, state_path)


if __name__ == "__main__":
    main()
