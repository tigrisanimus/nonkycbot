"""Runner utilities for the market maker strategy."""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path

from engine.rest_client_factory import build_exchange_client
from strategies.market_maker import MarketMakerConfig, MarketMakerStrategy


def build_strategy(config: dict, state_path: Path) -> MarketMakerStrategy:
    strategy_config = MarketMakerConfig(
        symbol=config["symbol"],
        base_order_size=Decimal(str(config.get("base_order_size", "0.01"))),
        sell_quote_target=Decimal(str(config.get("sell_quote_target", "10"))),
        min_notional_quote=Decimal(str(config.get("min_notional_quote", "1"))),
        fee_rate=Decimal(str(config.get("fee_rate", "0.001"))),
        safety_buffer_pct=Decimal(str(config.get("safety_buffer_pct", "0.0005"))),
        inside_spread_pct=Decimal(str(config.get("inside_spread_pct", "0.1"))),
        inventory_target_pct=Decimal(str(config.get("inventory_target_pct", "0.5"))),
        inventory_tolerance_pct=Decimal(
            str(config.get("inventory_tolerance_pct", "0.05"))
        ),
        inventory_skew_pct=Decimal(str(config.get("inventory_skew_pct", "0.2"))),
        tick_size=Decimal(str(config.get("tick_size", "0"))),
        step_size=Decimal(str(config.get("step_size", "0"))),
        poll_interval_sec=float(config.get("poll_interval_sec", 5)),
        max_order_age_sec=float(config.get("max_order_age_sec", 30)),
        balance_refresh_sec=float(config.get("balance_refresh_sec", 30)),
        mode=config.get("mode", "live"),
        post_only=bool(config.get("post_only", True)),
    )
    exchange = build_exchange_client(config)
    return MarketMakerStrategy(exchange, strategy_config, state_path=state_path)


def run_market_maker(config: dict, state_path: Path) -> None:
    strategy = build_strategy(config, state_path)
    strategy.load_state()
    print(
        "Market maker bot running. Press Ctrl+C to stop. "
        f"symbol={strategy.config.symbol} "
        f"poll_interval_sec={strategy.config.poll_interval_sec}"
    )
    while True:
        strategy.poll_once()
        time.sleep(strategy.config.poll_interval_sec)
