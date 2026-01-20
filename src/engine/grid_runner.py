"""Runner utilities for the grid trading strategy."""

from __future__ import annotations

import sys
import time
from decimal import Decimal
from pathlib import Path

from nonkyc_client.auth import AuthSigner
from nonkyc_client.rest import RestClient
from nonkyc_client.rest_exchange import NonkycRestExchangeClient
from strategies.grid import (
    LadderGridConfig,
    LadderGridStrategy,
    derive_market_id,
)
from utils.credentials import DEFAULT_SERVICE_NAME, load_api_credentials


def build_rest_client(config: dict) -> RestClient:
    signing_enabled = config.get("sign_requests", True)
    rest_timeout = config.get("rest_timeout_sec", 10.0)
    rest_retries = config.get("rest_retries", 3)
    rest_backoff = config.get("rest_backoff_factor", 0.5)
    creds = (
        load_api_credentials(DEFAULT_SERVICE_NAME, config) if signing_enabled else None
    )
    signer = (
        AuthSigner(
            nonce_multiplier=config.get("nonce_multiplier", 1e4),
            sort_params=config.get("sort_params", False),
            sort_body=config.get("sort_body", False),
        )
        if signing_enabled
        else None
    )
    return RestClient(
        base_url="https://api.nonkyc.io",
        credentials=creds,
        signer=signer,
        use_server_time=config.get("use_server_time"),
        timeout=float(rest_timeout),
        max_retries=int(rest_retries),
        backoff_factor=float(rest_backoff),
        sign_absolute_url=True,
        debug_auth=config.get("debug_auth"),
    )


def normalize_ladder_config(config: dict) -> dict:
    normalized = dict(config)
    if "symbol" not in normalized and "trading_pair" in normalized:
        normalized["symbol"] = normalized["trading_pair"]
    if "step_mode" not in normalized and "grid_spread" in normalized:
        normalized["step_mode"] = "pct"
    if "step_pct" not in normalized and "grid_spread" in normalized:
        normalized["step_pct"] = normalized["grid_spread"]
    if "base_order_size" not in normalized and "order_amount_mmx" in normalized:
        normalized["base_order_size"] = normalized["order_amount_mmx"]
    if "n_buy_levels" not in normalized and "grid_levels" in normalized:
        normalized["n_buy_levels"] = normalized["grid_levels"]
    if "n_sell_levels" not in normalized and "grid_levels" in normalized:
        normalized["n_sell_levels"] = normalized["grid_levels"]
    if "min_notional_quote" not in normalized and "min_notional_usd" in normalized:
        normalized["min_notional_quote"] = normalized["min_notional_usd"]
    if "rest_timeout_sec" not in normalized and "rest_timeout" in normalized:
        normalized["rest_timeout_sec"] = normalized["rest_timeout"]
    if "rest_retries" not in normalized and "rest_max_retries" in normalized:
        normalized["rest_retries"] = normalized["rest_max_retries"]
    if "rest_backoff_factor" not in normalized and "rest_backoff" in normalized:
        normalized["rest_backoff_factor"] = normalized["rest_backoff"]
    return normalized


def build_strategy(config: dict, state_path: Path) -> LadderGridStrategy:
    normalized = normalize_ladder_config(config)
    step_mode = normalized.get("step_mode", "pct")
    ladder_config = LadderGridConfig(
        symbol=normalized["symbol"],
        step_mode=step_mode,
        step_pct=(
            Decimal(str(normalized.get("step_pct"))) if step_mode == "pct" else None
        ),
        step_abs=(
            Decimal(str(normalized.get("step_abs"))) if step_mode == "abs" else None
        ),
        n_buy_levels=int(normalized.get("n_buy_levels", 3)),
        n_sell_levels=int(normalized.get("n_sell_levels", 3)),
        base_order_size=Decimal(str(normalized.get("base_order_size", "1"))),
        min_notional_quote=Decimal(str(normalized.get("min_notional_quote", "1.05"))),
        fee_buffer_pct=Decimal(str(normalized.get("fee_buffer_pct", "0.002"))),
        total_fee_rate=Decimal(
            str(
                normalized.get(
                    "total_fee_rate", normalized.get("fee_buffer_pct", "0.002")
                )
            )
        ),
        tick_size=Decimal(str(normalized.get("tick_size", "0"))),
        step_size=Decimal(str(normalized.get("step_size", "0"))),
        poll_interval_sec=float(normalized.get("poll_interval_sec", 5)),
        fetch_backoff_sec=float(normalized.get("fetch_backoff_sec", 15)),
        startup_cancel_all=bool(normalized.get("startup_cancel_all", False)),
        startup_rebalance=bool(normalized.get("startup_rebalance", False)),
        rebalance_target_base_pct=Decimal(
            str(normalized.get("rebalance_target_base_pct", "0.5"))
        ),
        rebalance_slippage_pct=Decimal(
            str(normalized.get("rebalance_slippage_pct", "0.002"))
        ),
        rebalance_max_attempts=int(normalized.get("rebalance_max_attempts", 2)),
        reconcile_interval_sec=float(normalized.get("reconcile_interval_sec", 60)),
        balance_refresh_sec=float(normalized.get("balance_refresh_sec", 60)),
    )
    rest_client = build_rest_client(normalized)
    exchange = NonkycRestExchangeClient(rest_client)
    return LadderGridStrategy(exchange, ladder_config, state_path=state_path)


def run_grid(config: dict, state_path: Path) -> None:
    strategy = build_strategy(config, state_path)
    strategy.load_state()
    if not strategy.state.open_orders:
        if strategy.config.startup_cancel_all:
            market_id = derive_market_id(strategy.config.symbol)
            strategy.client.cancel_all(market_id, "all")
        if strategy.config.startup_rebalance:
            try:
                strategy.rebalance_startup()
            except Exception as exc:
                print(
                    "Startup rebalance failed. Manual balancing required. " f"{exc}",
                    file=sys.stderr,
                )
                raise
        strategy.seed_ladder()
    print(
        "Grid bot running. Press Ctrl+C to stop. "
        f"symbol={strategy.config.symbol} "
        f"poll_interval_sec={strategy.config.poll_interval_sec}"
    )
    while True:
        strategy.poll_once()
        time.sleep(strategy.config.poll_interval_sec)
