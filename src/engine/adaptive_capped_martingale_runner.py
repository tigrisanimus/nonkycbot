"""Runner utilities for the adaptive capped martingale strategy."""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from pathlib import Path

from engine.rest_client_factory import build_exchange_client, build_rest_client
from nonkyc_client.rest import RestError, RestRequest
from strategies.adaptive_capped_martingale import (
    AdaptiveCappedMartingaleConfig,
    AdaptiveCappedMartingaleStrategy,
)

LOGGER = logging.getLogger("nonkyc_bot.engine.adaptive_capped_martingale_runner")


def _normalize_market_symbol(symbol: str) -> str:
    if "/" in symbol:
        return symbol
    if "_" in symbol:
        return symbol.replace("_", "/")
    if "-" in symbol:
        return symbol.replace("-", "/")
    return symbol


def _extract_market_list(response: object) -> list[dict] | None:
    if isinstance(response, list):
        return [entry for entry in response if isinstance(entry, dict)]
    if isinstance(response, dict):
        payload = response.get("data", response.get("result", response))
        if isinstance(payload, list):
            return [entry for entry in payload if isinstance(entry, dict)]
    return None


def _fetch_min_order_qty(config: dict, symbol: str) -> Decimal | None:
    client = build_rest_client({**config, "sign_requests": False})
    try:
        response = client.send(RestRequest(method="GET", path="/market/getlist"))
    except RestError as exc:
        LOGGER.warning("Failed to fetch market metadata: %s", exc)
        return None
    markets = _extract_market_list(response)
    if not markets:
        return None
    target = _normalize_market_symbol(symbol)
    for entry in markets:
        if entry.get("symbol") == target:
            minimum_qty = entry.get("minimumQuantity") or entry.get("minimum_quantity")
            if minimum_qty is None:
                return None
            try:
                return Decimal(str(minimum_qty))
            except Exception:
                return None
    return None


def build_strategy(config: dict, state_path: Path) -> AdaptiveCappedMartingaleStrategy:
    min_order_qty = config.get("min_order_qty")
    if min_order_qty is not None:
        min_order_qty = Decimal(str(min_order_qty))
    else:
        min_order_qty = _fetch_min_order_qty(config, config["symbol"])
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
        min_order_qty=min_order_qty,
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
