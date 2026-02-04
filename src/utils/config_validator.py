"""Configuration validation utilities for nonkyc bot."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


class ConfigValidationError(ValueError):
    """Raised when configuration validation fails."""


def validate_api_credentials(
    config: dict[str, Any], *, allow_missing: bool = False
) -> None:
    """Validate API credentials are present and properly formatted."""
    has_api_key = "api_key" in config
    has_api_secret = "api_secret" in config
    if not has_api_key and not has_api_secret:
        if allow_missing:
            return
        raise ConfigValidationError("Missing required field: api_key")
    if not has_api_key:
        raise ConfigValidationError("Missing required field: api_key")
    if not has_api_secret:
        raise ConfigValidationError("Missing required field: api_secret")

    api_key = config["api_key"]
    api_secret = config["api_secret"]

    if not isinstance(api_key, str) or not api_key.strip():
        raise ConfigValidationError("api_key must be a non-empty string")
    if not isinstance(api_secret, str) or not api_secret.strip():
        raise ConfigValidationError("api_secret must be a non-empty string")

    if len(api_key) < 8:
        raise ConfigValidationError("api_key appears too short (minimum 8 characters)")
    if len(api_secret) < 16:
        raise ConfigValidationError(
            "api_secret appears too short (minimum 16 characters)"
        )


def validate_symbol(config: dict[str, Any]) -> None:
    """Validate trading symbol is present and properly formatted."""
    if "symbol" not in config:
        raise ConfigValidationError("Missing required field: symbol")

    symbol = config["symbol"]
    if not isinstance(symbol, str) or not symbol.strip():
        raise ConfigValidationError("symbol must be a non-empty string")

    # Check for common symbol formats like BTC/USDT, BTC-USDT, or BTC_USDT
    if not re.match(r"^[A-Z0-9]+[/-_][A-Z0-9]+$", symbol, re.IGNORECASE):
        raise ConfigValidationError(
            "symbol '{symbol}' does not match expected format (e.g., BTC/USDT, "
            "BTC-USDT, or BTC_USDT)".format(symbol=symbol)
        )


def validate_positive_decimal(
    config: dict[str, Any], field: str, *, required: bool = True
) -> None:
    """Validate that a field is a positive decimal value."""
    if field not in config:
        if required:
            raise ConfigValidationError(f"Missing required field: {field}")
        return

    value = config[field]
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ConfigValidationError(
            f"{field} must be a valid number, got: {value}"
        ) from exc

    if decimal_value <= 0:
        raise ConfigValidationError(f"{field} must be positive, got: {decimal_value}")


def validate_non_negative_decimal(
    config: dict[str, Any], field: str, *, required: bool = True
) -> None:
    """Validate that a field is a non-negative decimal value."""
    if field not in config:
        if required:
            raise ConfigValidationError(f"Missing required field: {field}")
        return

    value = config[field]
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ConfigValidationError(
            f"{field} must be a valid number, got: {value}"
        ) from exc

    if decimal_value < 0:
        raise ConfigValidationError(
            f"{field} must be non-negative, got: {decimal_value}"
        )


def validate_positive_integer(
    config: dict[str, Any], field: str, *, required: bool = True, minimum: int = 1
) -> None:
    """Validate that a field is a positive integer."""
    if field not in config:
        if required:
            raise ConfigValidationError(f"Missing required field: {field}")
        return

    value = config[field]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigValidationError(
            f"{field} must be an integer, got: {type(value).__name__}"
        )

    if value < minimum:
        raise ConfigValidationError(f"{field} must be >= {minimum}, got: {value}")


def validate_percentage(
    config: dict[str, Any], field: str, *, required: bool = True
) -> None:
    """Validate that a field is a percentage between 0 and 100."""
    if field not in config:
        if required:
            raise ConfigValidationError(f"Missing required field: {field}")
        return

    value = config[field]
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ConfigValidationError(
            f"{field} must be a valid number, got: {value}"
        ) from exc

    if not (Decimal("0") <= decimal_value <= Decimal("100")):
        raise ConfigValidationError(
            f"{field} must be between 0 and 100, got: {decimal_value}"
        )


def validate_choice(
    config: dict[str, Any], field: str, choices: set[str], *, required: bool = True
) -> None:
    """Validate that a field is one of the allowed choices."""
    if field not in config:
        if required:
            raise ConfigValidationError(f"Missing required field: {field}")
        return

    value = config[field]
    if not isinstance(value, str):
        raise ConfigValidationError(
            f"{field} must be a string, got: {type(value).__name__}"
        )

    if value not in choices:
        choices_str = ", ".join(sorted(choices))
        raise ConfigValidationError(
            f"{field} must be one of [{choices_str}], got: {value}"
        )


def validate_url(config: dict[str, Any], field: str = "base_url") -> None:
    """Validate that a URL field is properly formatted."""
    if field not in config:
        return  # URL is usually optional with sensible defaults

    url = config[field]
    if not isinstance(url, str) or not url.strip():
        raise ConfigValidationError(f"{field} must be a non-empty string")

    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ConfigValidationError(
            f"{field} must start with http:// or https://, got: {url}"
        )


def validate_grid_config(config: dict[str, Any]) -> None:
    """Validate configuration for grid trading strategy."""
    validate_api_credentials(config, allow_missing=True)
    validate_symbol(config)
    validate_url(config)

    # Step mode validation
    step_mode = config.get("step_mode", "pct")
    validate_choice(config, "step_mode", {"pct", "abs"}, required=False)

    if step_mode == "pct":
        validate_positive_decimal(config, "step_pct", required=True)
        # Ensure step percentage is reasonable (< 50%)
        if "step_pct" in config:
            step_pct = Decimal(str(config["step_pct"]))
            if step_pct > Decimal("0.5"):
                raise ConfigValidationError(
                    f"step_pct should be < 0.5 (50%), got: {step_pct}"
                )
    elif step_mode == "abs":
        validate_positive_decimal(config, "step_abs", required=True)

    # Grid levels
    validate_positive_integer(config, "n_buy_levels", required=True, minimum=1)
    validate_positive_integer(config, "n_sell_levels", required=True, minimum=1)

    # Order size
    validate_positive_decimal(config, "base_order_size", required=True)

    # Fee rate
    validate_non_negative_decimal(config, "total_fee_rate", required=False)

    # Timeouts and retries
    if "rest_timeout_sec" in config:
        validate_positive_decimal(config, "rest_timeout_sec", required=False)
    if "rest_retries" in config:
        validate_positive_integer(config, "rest_retries", required=False, minimum=0)


def validate_rebalance_config(config: dict[str, Any]) -> None:
    """Validate configuration for rebalance strategy."""
    validate_api_credentials(config, allow_missing=True)
    validate_url(config)

    if "rebalance_assets" in config:
        assets = config["rebalance_assets"]
        if not isinstance(assets, list) or not assets:
            raise ConfigValidationError("rebalance_assets must be a non-empty list")
        for entry in assets:
            if not isinstance(entry, dict):
                raise ConfigValidationError(
                    "Each rebalance asset entry must be a mapping"
                )
            asset = entry.get("asset")
            if not isinstance(asset, str) or not asset.strip():
                raise ConfigValidationError("rebalance_assets entries require asset")
            if "target_percent" not in entry:
                raise ConfigValidationError(
                    f"rebalance_assets entry for {asset} missing target_percent"
                )
            validate_percentage(entry, "target_percent", required=True)
            if "trading_pair" in entry:
                validate_symbol({"symbol": entry["trading_pair"]})
        if "quote_asset" in config and (
            not isinstance(config["quote_asset"], str)
            or not config["quote_asset"].strip()
        ):
            raise ConfigValidationError("quote_asset must be a non-empty string")
        validate_percentage(config, "drift_threshold", required=True)
    else:
        if "symbol" in config:
            validate_symbol(config)
        elif "trading_pair" in config:
            validate_symbol({"symbol": config["trading_pair"]})
        else:
            raise ConfigValidationError("Missing required field: symbol")
        validate_percentage(config, "target_base_percent", required=True)
        validate_percentage(config, "drift_threshold", required=True)

    # Ensure drift threshold is reasonable
    if "drift_threshold" in config:
        drift = Decimal(str(config["drift_threshold"]))
        if drift > Decimal("50"):
            raise ConfigValidationError(
                f"drift_threshold should be < 50%, got: {drift}"
            )


def validate_infinity_grid_config(config: dict[str, Any]) -> None:
    """Validate configuration for infinity grid strategy."""
    validate_api_credentials(config, allow_missing=True)
    validate_symbol(config)
    validate_url(config)

    step_mode = config.get("step_mode", "pct")
    validate_choice(config, "step_mode", {"pct", "abs"}, required=False)

    if step_mode == "pct":
        validate_positive_decimal(config, "step_pct", required=True)
        # Ensure step percentage is reasonable
        step_pct = Decimal(str(config["step_pct"]))
        if step_pct > Decimal("0.5"):
            raise ConfigValidationError(
                f"step_pct should be < 0.5 (50%), got: {step_pct}"
            )
    else:
        validate_positive_decimal(config, "step_abs", required=True)

    validate_positive_integer(config, "n_buy_levels", required=True, minimum=1)
    validate_positive_integer(config, "initial_sell_levels", required=True, minimum=1)
    validate_positive_decimal(config, "base_order_size", required=True)
    validate_choice(
        config,
        "buy_sizing_mode",
        {"fixed", "dynamic", "hybrid"},
        required=False,
    )
    validate_choice(
        config,
        "sell_sizing_mode",
        {"fixed", "dynamic", "hybrid"},
        required=False,
    )
    validate_positive_decimal(config, "fixed_base_order_qty", required=False)
    validate_positive_decimal(config, "target_quote_per_order", required=False)
    validate_positive_decimal(config, "min_base_order_qty", required=False)
    validate_positive_decimal(config, "min_order_qty", required=False)
    sizing_modes = {
        config.get("buy_sizing_mode", "fixed"),
        config.get("sell_sizing_mode", "dynamic"),
    }
    if "hybrid" in sizing_modes and "min_base_order_qty" not in config:
        raise ConfigValidationError(
            "min_base_order_qty is required when using hybrid sizing mode."
        )

    validate_positive_decimal(config, "min_notional_quote", required=True)
    validate_non_negative_decimal(config, "total_fee_rate", required=True)
    validate_non_negative_decimal(config, "fee_buffer_pct", required=True)
    validate_positive_decimal(config, "tick_size", required=True)
    validate_positive_decimal(config, "step_size", required=True)

    if "poll_interval_sec" in config:
        validate_positive_decimal(config, "poll_interval_sec", required=False)
    if "reconcile_interval_sec" in config:
        validate_positive_decimal(config, "reconcile_interval_sec", required=False)
    if "balance_refresh_sec" in config:
        validate_positive_decimal(config, "balance_refresh_sec", required=False)
    if "fetch_backoff_sec" in config:
        validate_positive_decimal(config, "fetch_backoff_sec", required=False)
    if "extend_buy_levels_on_restart" in config and not isinstance(
        config["extend_buy_levels_on_restart"], bool
    ):
        raise ConfigValidationError(
            "extend_buy_levels_on_restart must be a boolean if provided."
        )


def validate_triangular_arb_config(config: dict[str, Any]) -> None:
    """Validate configuration for triangular arbitrage strategy."""
    validate_api_credentials(config, allow_missing=True)
    validate_url(config)

    # Validate trading pairs
    for pair_field in ["pair_ab", "pair_bc", "pair_ac"]:
        if pair_field not in config:
            raise ConfigValidationError(f"Missing required field: {pair_field}")
        symbol = config[pair_field]
        if not isinstance(symbol, str) or not symbol.strip():
            raise ConfigValidationError(f"{pair_field} must be a non-empty string")

    validate_positive_decimal(config, "trade_amount", required=True)
    validate_non_negative_decimal(config, "min_profitability", required=True)

    # Ensure min profitability is reasonable (< 100%)
    if "min_profitability" in config:
        min_prof = Decimal(str(config["min_profitability"]))
        if min_prof > Decimal("1.0"):
            raise ConfigValidationError(
                f"min_profitability should be < 1.0 (100%), got: {min_prof}"
            )


def validate_adaptive_capped_martingale_config(config: dict[str, Any]) -> None:
    """Validate configuration for adaptive capped martingale strategy."""
    validate_api_credentials(config, allow_missing=True)
    validate_symbol(config)
    validate_url(config)

    validate_positive_decimal(config, "cycle_budget", required=True)
    validate_positive_decimal(config, "base_order_pct", required=False)
    validate_positive_decimal(config, "multiplier", required=False)
    validate_positive_integer(config, "max_adds", required=False, minimum=0)
    validate_positive_decimal(config, "per_order_cap_pct", required=False)
    validate_positive_decimal(config, "step_pct", required=False)
    validate_positive_decimal(config, "tp1_pct", required=False)
    validate_positive_decimal(config, "tp2_pct", required=False)
    validate_positive_decimal(config, "slippage_buffer_pct", required=False)
    validate_positive_decimal(config, "fee_rate", required=False)
    validate_positive_decimal(config, "min_order_notional", required=False)
    validate_positive_decimal(config, "min_order_qty", required=False)
    if "time_stop_seconds" in config:
        validate_positive_decimal(config, "time_stop_seconds", required=False)
    if "poll_interval_sec" in config:
        validate_positive_decimal(config, "poll_interval_sec", required=False)


def validate_market_maker_config(config: dict[str, Any]) -> None:
    """Validate configuration for market maker strategy."""
    validate_api_credentials(config, allow_missing=True)
    validate_symbol(config)
    validate_url(config)

    validate_positive_decimal(config, "base_order_size", required=True)
    validate_positive_decimal(config, "sell_quote_target", required=True)
    validate_positive_decimal(config, "fee_rate", required=True)
    validate_positive_decimal(config, "min_notional_quote", required=False)
    validate_non_negative_decimal(config, "safety_buffer_pct", required=False)
    validate_non_negative_decimal(config, "inside_spread_pct", required=False)
    validate_non_negative_decimal(config, "inventory_skew_pct", required=False)
    if "inventory_target_pct" in config:
        target_pct = Decimal(str(config["inventory_target_pct"]))
        if not (Decimal("0") <= target_pct <= Decimal("1")):
            raise ConfigValidationError("inventory_target_pct must be between 0 and 1")
    if "inventory_tolerance_pct" in config:
        validate_positive_decimal(config, "inventory_tolerance_pct", required=False)
    if "tick_size" in config:
        validate_non_negative_decimal(config, "tick_size", required=False)
    if "step_size" in config:
        validate_non_negative_decimal(config, "step_size", required=False)
    if "poll_interval_sec" in config:
        validate_positive_decimal(config, "poll_interval_sec", required=False)
    if "max_order_age_sec" in config:
        validate_positive_decimal(config, "max_order_age_sec", required=False)
    if "balance_refresh_sec" in config:
        validate_positive_decimal(config, "balance_refresh_sec", required=False)
    if "post_only" in config and not isinstance(config["post_only"], bool):
        raise ConfigValidationError("post_only must be a boolean")


def validate_config(config: dict[str, Any], strategy: str | None = None) -> None:
    """
    Validate configuration for a specific strategy.

    Args:
        config: Configuration dictionary
        strategy: Strategy name (e.g., 'grid', 'rebalance')

    Raises:
        ConfigValidationError: If configuration is invalid
    """
    if not isinstance(config, dict):
        raise ConfigValidationError("Configuration must be a dictionary")

    if not config:
        raise ConfigValidationError("Configuration cannot be empty")

    # Always validate API credentials if present (optional for some test modes)
    if "api_key" in config or "api_secret" in config:
        validate_api_credentials(config)

    # Strategy-specific validation
    if strategy == "grid":
        validate_grid_config(config)
    elif strategy == "rebalance":
        validate_rebalance_config(config)
    elif strategy == "infinity_grid":
        validate_infinity_grid_config(config)
    elif strategy == "triangular_arb":
        validate_triangular_arb_config(config)
    elif strategy == "adaptive_capped_martingale":
        validate_adaptive_capped_martingale_config(config)
    elif strategy == "market_maker":
        validate_market_maker_config(config)
    elif strategy is not None:
        # For other strategies, at least validate basic fields
        if "symbol" in config:
            validate_symbol(config)
        validate_url(config)
