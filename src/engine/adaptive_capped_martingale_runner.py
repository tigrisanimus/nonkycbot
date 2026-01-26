"""Runner utilities for the adaptive capped martingale strategy."""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path

from engine.rest_client_factory import build_exchange_client
from strategies.adaptive_capped_martingale import (
    AdaptiveCappedMartingaleConfig,
    AdaptiveCappedMartingaleStrategy,
)


def build_strategy(config: dict, state_path: Path) -> AdaptiveCappedMartingaleStrategy:
    strategy_config = AdaptiveCappedMartingaleConfig(
        symbol=config["symbol"],
        cycle_budget=Decimal(str(config["cycle_budget"])),
        base_order_pct=Decimal(str(config.get("base_order_pct", "0.015"))),
        multiplier=Decimal(str(config.get("multiplier", "1.45"))),
        max_adds=int(config.get("max_adds", 8)),
        per_order_cap_pct=Decimal(str(config.get("per_order_cap_pct", "0.10"))),
        step_pct=Decimal(str(config.get("step_pct", "0.012"))),
        slippage_buffer_pct=Decimal(str(config.get("slippage_buffer_pct", "0.001"))),
        tp1_pct=Decimal(str(config.get("tp1_pct", "0.008"))),
        tp2_pct=Decimal(str(config.get("tp2_pct", "0.014"))),
        fee_rate=Decimal(str(config.get("fee_rate", "0.002"))),
        min_order_notional=Decimal(str(config.get("min_order_notional", "2"))),
        time_stop_seconds=float(config.get("time_stop_seconds", 72 * 3600)),
        time_stop_exit_buffer_pct=Decimal(
            str(config.get("time_stop_exit_buffer_pct", "0.001"))
        ),
        poll_interval_sec=float(config.get("poll_interval_sec", 5)),
        quantity_step=(
            Decimal(str(config["quantity_step"])) if "quantity_step" in config else None
        ),
        quantity_precision=(
            int(config["quantity_precision"])
            if "quantity_precision" in config
            else None
        ),
    )
    exchange = build_exchange_client(config)
    return AdaptiveCappedMartingaleStrategy(
        exchange, strategy_config, state_path=state_path
    )


def run_adaptive_capped_martingale(config: dict, state_path: Path) -> None:
    strategy = build_strategy(config, state_path)
    strategy.load_state()
    print(
        "Adaptive capped martingale bot running. Press Ctrl+C to stop. "
        f"symbol={strategy.config.symbol} "
        f"poll_interval_sec={strategy.config.poll_interval_sec}"
    )
    while True:
        strategy.poll_once()
        time.sleep(strategy.config.poll_interval_sec)
