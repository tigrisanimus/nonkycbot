"""Profit storage helper to convert net profits into PAXG."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from engine.exchange_client import ExchangeClient

LOGGER = logging.getLogger("nonkyc_bot.profit_store")


@dataclass(frozen=True)
class ProfitStoreConfig:
    enabled: bool = False
    target_symbol: str = "PAXG_USDT"
    quote_asset: str = "USDT"
    min_profit_quote: Decimal = Decimal("1")
    aggressive_limit_pct: Decimal = Decimal("0.003")
    principal_investment_quote: Decimal | None = None
    exit_dump_pct: Decimal = Decimal("0.75")
    exit_convert_pct: Decimal = Decimal("0.5")


class ProfitStore:
    """Track net profits and convert them into PAXG once thresholds are met."""

    def __init__(
        self,
        client: ExchangeClient,
        config: ProfitStoreConfig,
        mode: str = "live",
    ) -> None:
        self.client = client
        self.config = config
        self.mode = mode
        self.pending_profit = Decimal("0")
        self.reserved_profit = Decimal("0")
        self.open_order_id: str | None = None
        self.total_converted_quote = Decimal("0")
        self._exit_triggered = False

    def record_profit(self, amount: Decimal, asset: str) -> None:
        if not self.config.enabled:
            return
        if amount <= 0:
            return
        if asset != self.config.quote_asset:
            LOGGER.info(
                "Profit store ignored %s %s (expected %s).",
                amount,
                asset,
                self.config.quote_asset,
            )
            return
        self.pending_profit += amount
        self.process()

    def process(self) -> None:
        if not self.config.enabled:
            return
        if self.open_order_id is not None:
            resolved = self._reconcile_open_order()
            if resolved:
                return
        if self.open_order_id is not None:
            return
        if self.pending_profit < self.config.min_profit_quote:
            return
        self._place_conversion_order()

    def _place_conversion_order(self) -> None:
        if self.mode != "live":
            LOGGER.info(
                "Profit store idle in %s mode with pending profit %s %s.",
                self.mode,
                self.pending_profit,
                self.config.quote_asset,
            )
            return
        try:
            _, best_ask = self.client.get_orderbook_top(self.config.target_symbol)
        except Exception as exc:
            LOGGER.warning("Profit store failed to read orderbook: %s", exc)
            return
        limit_price = best_ask * (Decimal("1") + self.config.aggressive_limit_pct)
        if limit_price <= 0:
            LOGGER.warning("Profit store invalid limit price: %s", limit_price)
            return
        quantity = self.pending_profit / limit_price
        if quantity <= 0:
            LOGGER.warning("Profit store invalid quantity: %s", quantity)
            return
        try:
            order_id = self.client.place_limit(
                self.config.target_symbol,
                "buy",
                limit_price,
                quantity,
            )
        except Exception as exc:
            LOGGER.warning("Profit store failed to place order: %s", exc)
            return
        self.open_order_id = order_id
        self.reserved_profit = self.pending_profit
        self.pending_profit = Decimal("0")
        base_asset, _ = _split_symbol(self.config.target_symbol)
        LOGGER.info(
            "Profit store placed %s BUY for %s %s at %s (order_id=%s).",
            self.config.target_symbol,
            quantity,
            base_asset,
            limit_price,
            order_id,
        )

    def _reconcile_open_order(self) -> bool:
        if self.open_order_id is None:
            return False
        try:
            status = self.client.get_order(self.open_order_id)
        except Exception as exc:
            LOGGER.warning("Profit store failed to fetch order status: %s", exc)
            return False
        normalized = status.status.lower() if status.status else ""
        filled_statuses = {"filled", "closed"}
        cancelled_statuses = {"cancelled", "canceled", "rejected", "expired"}
        if normalized in filled_statuses:
            LOGGER.info(
                "Profit store conversion filled (order_id=%s).",
                self.open_order_id,
            )
            self.total_converted_quote += self.reserved_profit
            self.open_order_id = None
            self.reserved_profit = Decimal("0")
            self._check_exit_trigger()
            return True
        if normalized in cancelled_statuses:
            LOGGER.info(
                "Profit store conversion canceled (order_id=%s).",
                self.open_order_id,
            )
            self.pending_profit += self.reserved_profit
            self.reserved_profit = Decimal("0")
            self.open_order_id = None
            return True
        return False

    def should_trigger_exit(self) -> bool:
        return self._exit_triggered

    def mark_exit_handled(self) -> None:
        if self._exit_triggered:
            self._exit_triggered = False

    def _check_exit_trigger(self) -> None:
        target = self.config.principal_investment_quote
        if target is None or target <= 0:
            return
        if self.total_converted_quote >= target:
            self._exit_triggered = True


def execute_exit_liquidation(
    client: ExchangeClient,
    profit_store: ProfitStore,
    symbol: str,
    mode: str,
) -> bool:
    if not profit_store.config.enabled:
        return False
    if not symbol:
        LOGGER.warning("Exit liquidation skipped: missing liquidation symbol.")
        return False
    if mode == "monitor":
        LOGGER.info("MONITOR MODE: Profit-store exit triggered; no orders placed.")
        return True
    if mode == "dry-run":
        LOGGER.info("DRY RUN: Profit-store exit triggered; no orders placed.")
        return True

    profit_config = profit_store.config
    symbols_to_cancel = {symbol, profit_config.target_symbol}
    if profit_store.open_order_id is not None:
        try:
            client.cancel_order(profit_store.open_order_id)
        except Exception as exc:
            LOGGER.warning(
                "Exit cancel failed for %s: %s", profit_store.open_order_id, exc
            )
        profit_store.open_order_id = None

    for cancel_symbol in symbols_to_cancel:
        try:
            open_orders = client.list_open_orders(cancel_symbol)
        except Exception as exc:
            LOGGER.warning(
                "Exit failed to list open orders for %s: %s", cancel_symbol, exc
            )
            try:
                client.cancel_all(cancel_symbol)
            except Exception as cancel_exc:
                LOGGER.warning(
                    "Exit cancel-all failed for %s: %s",
                    cancel_symbol,
                    cancel_exc,
                )
            continue
        for order in open_orders:
            try:
                client.cancel_order(order.order_id)
            except Exception as exc:
                LOGGER.warning("Exit cancel failed for %s: %s", order.order_id, exc)

    balances = client.get_balances()
    base_asset, _ = _split_symbol(symbol)
    base_available = balances.get(base_asset, (Decimal("0"), Decimal("0")))[0]
    if base_available <= 0:
        LOGGER.info("Exit triggered but no %s balance to sell.", base_asset)
        return True

    dump_qty = base_available * profit_config.exit_dump_pct
    if dump_qty <= 0:
        return True
    try:
        best_bid, _ = client.get_orderbook_top(symbol)
    except Exception as exc:
        LOGGER.warning("Exit failed to read %s orderbook: %s", symbol, exc)
        return False
    limit_price = best_bid * (Decimal("1") - profit_config.aggressive_limit_pct)
    if limit_price <= 0:
        return False
    try:
        client.place_limit(symbol, "sell", limit_price, dump_qty)
        LOGGER.info(
            "Exit placed SELL %s %s @ %s",
            dump_qty,
            base_asset,
            limit_price,
        )
    except Exception as exc:
        LOGGER.warning("Exit SELL placement failed: %s", exc)
        return False

    quote_estimate = dump_qty * limit_price
    convert_quote = quote_estimate * profit_config.exit_convert_pct
    if convert_quote <= 0:
        return True
    try:
        _, ask = client.get_orderbook_top(profit_config.target_symbol)
    except Exception as exc:
        LOGGER.warning(
            "Exit failed to read %s orderbook: %s",
            profit_config.target_symbol,
            exc,
        )
        return False
    buy_price = ask * (Decimal("1") + profit_config.aggressive_limit_pct)
    if buy_price <= 0:
        return False
    buy_qty = convert_quote / buy_price
    if buy_qty <= 0:
        return True
    try:
        client.place_limit(profit_config.target_symbol, "buy", buy_price, buy_qty)
        LOGGER.info(
            "Exit placed %s BUY %s @ %s",
            profit_config.target_symbol,
            buy_qty,
            buy_price,
        )
    except Exception as exc:
        LOGGER.warning("Exit profit-store BUY failed: %s", exc)
        return False
    return True


def build_profit_store(
    config: dict[str, Any],
    client: ExchangeClient,
    mode: str,
) -> ProfitStore | None:
    raw = config.get("profit_store")
    if not isinstance(raw, dict):
        return None
    profit_config = ProfitStoreConfig(
        enabled=bool(raw.get("enabled", False)),
        target_symbol=str(raw.get("target_symbol", "PAXG_USDT")),
        quote_asset=str(raw.get("quote_asset", "USDT")),
        min_profit_quote=Decimal(str(raw.get("min_profit_quote", "1"))),
        aggressive_limit_pct=Decimal(str(raw.get("aggressive_limit_pct", "0.003"))),
        principal_investment_quote=(
            Decimal(str(raw["principal_investment_quote"]))
            if "principal_investment_quote" in raw
            else None
        ),
        exit_dump_pct=Decimal(str(raw.get("exit_dump_pct", "0.75"))),
        exit_convert_pct=Decimal(str(raw.get("exit_convert_pct", "0.5"))),
    )
    return ProfitStore(client=client, config=profit_config, mode=mode)


def _split_symbol(symbol: str) -> tuple[str, str]:
    if "/" in symbol:
        base, quote = symbol.split("/", 1)
    elif "-" in symbol:
        base, quote = symbol.split("-", 1)
    elif "_" in symbol:
        base, quote = symbol.split("_", 1)
    else:
        raise ValueError(f"Unsupported symbol format: {symbol}")
    return base, quote
