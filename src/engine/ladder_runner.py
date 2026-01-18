"""Runner utilities for the ladder grid strategy."""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path

from nonkyc_client.auth import ApiCredentials, AuthSigner
from nonkyc_client.rest import RestClient
from nonkyc_client.rest_exchange import NonkycRestExchangeClient
from strategies.ladder_grid import (
    LadderGridConfig,
    LadderGridStrategy,
    derive_market_id,
)


def build_rest_client(config: dict) -> RestClient:
    signing_enabled = config.get("sign_requests", True)
    creds = (
        ApiCredentials(api_key=config["api_key"], api_secret=config["api_secret"])
        if signing_enabled
        else None
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
        sign_absolute_url=True,
        debug_auth=config.get("debug_auth"),
    )


def build_strategy(config: dict, state_path: Path) -> LadderGridStrategy:
    step_mode = config.get("step_mode", "pct")
    ladder_config = LadderGridConfig(
        symbol=config["symbol"],
        step_mode=step_mode,
        step_pct=Decimal(str(config.get("step_pct"))) if step_mode == "pct" else None,
        step_abs=Decimal(str(config.get("step_abs"))) if step_mode == "abs" else None,
        n_buy_levels=int(config.get("n_buy_levels", 3)),
        n_sell_levels=int(config.get("n_sell_levels", 3)),
        base_order_size=Decimal(str(config.get("base_order_size", "1"))),
        min_notional_quote=Decimal(str(config.get("min_notional_quote", "1.05"))),
        fee_buffer_pct=Decimal(str(config.get("fee_buffer_pct", "0.002"))),
        tick_size=Decimal(str(config.get("tick_size", "0"))),
        step_size=Decimal(str(config.get("step_size", "0"))),
        poll_interval_sec=float(config.get("poll_interval_sec", 5)),
        startup_cancel_all=bool(config.get("startup_cancel_all", False)),
        reconcile_interval_sec=float(config.get("reconcile_interval_sec", 60)),
        balance_refresh_sec=float(config.get("balance_refresh_sec", 60)),
    )
    rest_client = build_rest_client(config)
    exchange = NonkycRestExchangeClient(rest_client)
    return LadderGridStrategy(exchange, ladder_config, state_path=state_path)


def run_ladder_grid(config: dict, state_path: Path) -> None:
    strategy = build_strategy(config, state_path)
    strategy.load_state()
    if not strategy.state.open_orders:
        if strategy.config.startup_cancel_all:
            market_id = derive_market_id(strategy.config.symbol)
            strategy.client.cancel_all(market_id, "all")
        strategy.seed_ladder()
    while True:
        strategy.poll_once()
        time.sleep(strategy.config.poll_interval_sec)
