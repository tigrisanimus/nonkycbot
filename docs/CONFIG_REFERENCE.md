# Configuration Reference

This document lists every configuration key the bots read from `config.yml` files,
including defaults and supported aliases.

## Common REST/auth settings (all bots)

These settings are used by the shared REST client factory:

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `api_key` | string | required | API key for signed requests. |
| `api_secret` | string | required | API secret for signed requests. |
| `sign_requests` | bool | `true` | Enable/disable request signing. |
| `base_url` | string | `https://api.nonkyc.io/api/v2` | REST API base URL. |
| `nonce_multiplier` | number | `1e4` | NonKYC 14-digit nonce multiplier. |
| `sign_absolute_url` | bool | `true` | Sign absolute URL (required by NonKYC). |
| `sort_params` | bool | `false` | Sort query params when signing. |
| `sort_body` | bool | `false` | Sort body params when signing. |
| `rest_timeout_sec` | number | `10.0` | REST request timeout. |
| `rest_retries` | int | `3` | REST retry attempts. |
| `rest_backoff_factor` | number | `0.5` | REST retry backoff factor. |
| `use_server_time` | bool | unset | Use server time for nonce when supported. |
| `debug_auth` | bool | unset | Emit debug signing details. |

## Profit store settings (optional, all bots)

These keys enable the opt-in profit store. If omitted, the feature is disabled.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `profit_store.enabled` | bool | `false` | Enable profit store. |
| `profit_store.target_symbol` | string | `PAXG_USDT` | Market to buy with profits. |
| `profit_store.quote_asset` | string | `USDT` | Profit asset required to trigger conversion. |
| `profit_store.min_profit_quote` | number | `1` | Minimum net profit before conversion. |
| `profit_store.aggressive_limit_pct` | number | `0.003` | Extra premium for pseudo-market limits. |
| `profit_store.principal_investment_quote` | number | unset | Net-profit target to trigger exit dump logic. |
| `profit_store.exit_dump_pct` | number | `0.75` | Portion of base balance to sell on exit trigger. |
| `profit_store.exit_convert_pct` | number | `0.5` | Portion of exit proceeds to convert to target asset. |

## Grid bot (`bots/run_grid.py`)

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `state_path` | string | `state/grid_state.json` | State file path. |
| `symbol` | string | required | Trading pair (preferred key). |
| `trading_pair` | string | alias | Alias for `symbol`. |
| `step_mode` | string | `pct` | `pct` or `abs`. |
| `step_pct` | number | required if `pct` | Grid step size as percent. |
| `step_abs` | number | required if `abs` | Grid step size in absolute price. |
| `n_buy_levels` | int | `3` | Buy levels below mid. |
| `n_sell_levels` | int | `3` | Sell levels above mid. |
| `base_order_size` | number | `1` | Base order size in base asset. |
| `min_notional_quote` | number | `1.05` | Minimum quote notional. |
| `min_notional_usd` | number | alias | Alias for `min_notional_quote`. |
| `fee_buffer_pct` | number | `0.002` | Extra buffer for fee validation. |
| `total_fee_rate` | number | `fee_buffer_pct` | Total fees used in profitability checks. |
| `tick_size` | number | `0` | Price tick size. |
| `step_size` | number | `0` | Quantity step size. |
| `poll_interval_sec` | number | `5` | Loop sleep time. |
| `fetch_backoff_sec` | number | `15` | Order status backoff after errors. |
| `startup_cancel_all` | bool | `false` | Cancel open orders on startup. |
| `startup_rebalance` | bool | `false` | Perform startup rebalance before seeding. |
| `rebalance_target_base_pct` | number | `0.5` | Target base ratio for rebalance. |
| `rebalance_slippage_pct` | number | `0.002` | Slippage for rebalance orders. |
| `rebalance_max_attempts` | int | `2` | Max rebalance attempts. |
| `reconcile_interval_sec` | number | `60` | Interval for level reconciliation. |
| `balance_refresh_sec` | number | `60` | Balance refresh cadence. |
| `mode` | string | `live` | `live`, `dry-run`, or `monitor`. |

## Infinity grid bot (`bots/run_infinity_grid.py`)

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `state_path` | string | `state/infinity_grid_state.json` | State file path. |
| `symbol` | string | `BTC_USDT` | Trading pair. |
| `step_mode` | string | `pct` | `pct` or `abs`. |
| `step_pct` | number | required if `pct` | Grid step size as percent. |
| `step_abs` | number | required if `abs` | Grid step size in absolute price. |
| `n_buy_levels` | int | `10` | Buy levels below mid. |
| `initial_sell_levels` | int | `10` | Initial sell levels above mid. |
| `base_order_size` | number | `0.001` | Base order size in base asset. |
| `buy_sizing_mode` | string | `fixed` | `fixed`/`dynamic`/`hybrid` for buys. |
| `sell_sizing_mode` | string | `dynamic` | `fixed`/`dynamic`/`hybrid` for sells. |
| `fixed_base_order_qty` | number | unset | Fixed base qty override. |
| `target_quote_per_order` | number | unset | Quote target for dynamic sizing. |
| `min_base_order_qty` | number | unset | Minimum base qty for hybrid sizing. |
| `min_order_qty` | number | unset | Minimum order quantity guard. |
| `min_notional_quote` | number | `1.0` | Minimum quote notional. |
| `fee_buffer_pct` | number | `0.0001` | Extra buffer for fee validation. |
| `total_fee_rate` | number | `0.002` | Total fees used in profitability checks. |
| `tick_size` | number | `0.01` | Price tick size. |
| `step_size` | number | `0.00000001` | Quantity step size. |
| `poll_interval_sec` | number | `60.0` | Loop sleep time. |
| `fetch_backoff_sec` | number | `15.0` | Order status backoff after errors. |
| `startup_cancel_all` | bool | `false` | Cancel open orders on startup. |
| `startup_rebalance` | bool | `false` | Perform startup rebalance before seeding. |
| `rebalance_target_base_pct` | number | `0.5` | Target base ratio for rebalance. |
| `rebalance_slippage_pct` | number | `0.002` | Slippage for rebalance orders. |
| `rebalance_max_attempts` | int | `2` | Max rebalance attempts. |
| `reconcile_interval_sec` | number | `60.0` | Interval for reconciliation. |
| `balance_refresh_sec` | number | `60.0` | Balance refresh cadence. |
| `mode` | string | `live` | `live`, `dry-run`, or `monitor`. |
| `extend_buy_levels_on_restart` | bool | `false` | Extend buy ladder on restart. |

## Adaptive capped martingale bot (`bots/run_adaptive_capped_martingale.py`)

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `state_path` | string | `state/martingale_state.json` | State file path. |
| `symbol` | string | required | Trading pair. |
| `cycle_budget` | number | required | Max quote budget for cycle. |
| `base_order_pct` | number | `0.015` | Base order % of cycle budget. |
| `multiplier` | number | `1.45` | Add order size multiplier. |
| `max_adds` | int | `8` | Maximum add orders per cycle. |
| `per_order_cap_pct` | number | `0.10` | Per-order cap as % of cycle budget. |
| `step_pct` | number | `0.012` | Add order step percentage. |
| `slippage_buffer_pct` | number | `0.001` | Slippage buffer for market orders. |
| `tp1_pct` | number | `0.008` | Take-profit 1 percentage. |
| `tp2_pct` | number | `0.014` | Take-profit 2 percentage. |
| `fee_rate` | number | `0.002` | Fee rate used in calculations. |
| `min_order_notional` | number | `2` | Minimum quote notional per order. |
| `min_order_qty` | number | auto | Minimum base quantity (auto-fetched if missing). |
| `time_stop_seconds` | number | `259200` | Time stop in seconds. |
| `time_stop_exit_buffer_pct` | number | `0.001` | Extra buffer for time-stop exit. |
| `poll_interval_sec` | number | `5` | Loop sleep time. |
| `quantity_step` | number | unset | Quantity step size override. |
| `quantity_precision` | int | unset | Quantity precision override. |

## Rebalance bot (`bots/run_rebalance_bot.py`)

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `state_path` | string | `state/rebalance_state.json` | State file path. |
| `trading_pair` | string | `ETH_USDT` | Trading pair. |
| `target_base_percent` | number | `0.5` | Target base ratio. |
| `rebalance_threshold_percent` | number | `0.02` | Drift threshold before rebalance. |
| `rebalance_order_type` | string | `limit` | `limit` or `market`. |
| `rebalance_order_spread` | number | `0.002` | Spread for limit orders. |
| `min_notional_quote` | number | `1.0` | Minimum quote notional. |
| `poll_interval_seconds` | number | `60` | Loop sleep time. |
| `refresh_time` | number | alias | Alias for `poll_interval_seconds`. |
| `price_source` | string | `mid` | `mid`, `last`, `bid`, or `ask`. |
| `mode` | string | `monitor` | `live`, `dry-run`, or `monitor`. |

## Triangular arbitrage bot (`bots/run_arb_bot.py`)

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `state_path` | string | `state/arb_state.json` | State file path. |
| `asset_a` | string | required | Start/end asset (e.g., `USDT`). |
| `asset_b` | string | required | Second asset (e.g., `ETH`). |
| `asset_c` | string | required | Third asset (e.g., `BTC`). |
| `pair_ab` | string | required | Market for `asset_a`→`asset_b`. |
| `pair_bc` | string | required | Market for `asset_b`→`asset_c`. |
| `pair_ac` | string | required | Market for `asset_c`→`asset_a`. |
| `trade_amount_a` | number | required | Starting amount of `asset_a`. |
| `min_profitability` | number | required | Minimum profit ratio (e.g., `0.005`). |
| `fee_rate` | number | `0.002` | Exchange fee rate (forced to 0.002). |
| `poll_interval_seconds` | number | `refresh_time`/`2` | Loop sleep time. |
| `refresh_time` | number | `2` | Alias for poll interval. |
| `strictValidate` | bool | unset | Pass strict validate to orders if supported. |
| `enable_signing` | bool | alias | Alias for `sign_requests`. |
| `use_signing` | bool | alias | Alias for `sign_requests`. |
| `mode` | string | `live` | `live`, `dry-run`, or `monitor`. |

## Hybrid triangular arbitrage bot (`bots/run_hybrid_arb_bot.py`)

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `state_path` | string | `state/hybrid_arb_state.json` | State file path. |
| `min_profit_pct` | number | `0.5` | Minimum profit percent. |
| `trade_amount` | number | `100` | Trade amount in base currency. |
| `min_notional_quote` | number | `1.0` | Minimum quote notional. |
| `poll_interval_seconds` | number | `2.0` | Loop sleep time. |
| `orderbook_pairs` | list | required | Orderbook pairs to monitor. |
| `pool_pair` | string | required | Pool pair symbol. |
| `base_currency` | string | `USDT` | Base currency for profit tracking. |
| `orderbook_fee` | number | `0.002` | Fee for orderbook trades. |
| `pool_fee` | number | `0.003` | Fee for pool swaps. |
| `mode` | string | `monitor` | `live`, `dry-run`, or `monitor`. |
