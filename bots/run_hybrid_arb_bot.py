#!/usr/bin/env python3
"""
Hybrid triangular arbitrage bot for nonkyc.io exchange.

Monitors order books and liquidity pools to find profitable arbitrage opportunities
mixing limit orders and AMM swaps.

Usage:
    # Monitor mode (no execution, just logging)
    python bots/run_hybrid_arb_bot.py config.yml --monitor-only

    # Live trading mode
    python bots/run_hybrid_arb_bot.py config.yml

    # Dry run mode (simulated execution)
    python bots/run_hybrid_arb_bot.py config.yml --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from strategies.hybrid_triangular_arb import ArbitrageCycle, TradeLeg

# Add src to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

logger = logging.getLogger(__name__)


def build_rest_client(config: dict[str, Any]):
    from engine.rest_client_factory import (
        build_rest_client as factory_build_rest_client,
    )

    return factory_build_rest_client(config)


class HybridArbBot:
    """Hybrid arbitrage bot mixing order books and liquidity pools."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize bot with configuration."""
        from engine.rest_client_factory import build_exchange_client
        from utils.profit_store import build_profit_store

        self.config = config
        self.rest_client = self._build_rest_client()
        self.exchange_client = build_exchange_client(config)
        self.mode = config.get("mode", "monitor")  # monitor, dry-run, or live
        self.min_profit_pct = Decimal(str(config.get("min_profit_pct", "0.5")))
        self.trade_amount = Decimal(str(config.get("trade_amount", "100")))
        self.min_notional_quote = Decimal(
            str(config.get("min_notional_quote", "1.0"))
        )  # $1 minimum
        self.poll_interval = config.get("poll_interval_seconds", 2.0)
        self.orderbook_aggressive_limit_pct = Decimal(
            str(
                config.get(
                    "orderbook_aggressive_limit_pct",
                    config.get("aggressive_limit_pct", "0.003"),
                )
            )
        )

        # Market configuration
        self.orderbook_pairs = config.get("orderbook_pairs", [])
        self.pool_pair = config.get("pool_pair", "")
        self.base_currency = config.get("base_currency", "USDT")
        self.exit_symbol = config.get("exit_symbol")
        if not self.exit_symbol and self.orderbook_pairs:
            self.exit_symbol = self.orderbook_pairs[0]

        # Fee configuration
        self.orderbook_fee = Decimal(str(config.get("orderbook_fee", "0.002")))
        self.pool_fee = Decimal(str(config.get("pool_fee", "0.003")))

        # Statistics
        self.cycles_evaluated = 0
        self.opportunities_found = 0
        self.trades_executed = 0
        self.total_profit = Decimal("0")
        self.profit_store = build_profit_store(config, self.exchange_client, self.mode)
        self.state_path = Path(config.get("state_path", "state/hybrid_arb_state.json"))
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Initialized HybridArbBot in {self.mode.upper()} mode")
        logger.info(f"Monitoring {len(self.orderbook_pairs)} order book pairs + 1 pool")
        logger.info(f"Min profit threshold: {self.min_profit_pct}%")
        logger.info(
            "Orderbook aggressive limit pct: "
            f"{self.orderbook_aggressive_limit_pct:.4%}"
        )
        if self.exit_symbol:
            logger.info(f"Exit liquidation symbol: {self.exit_symbol}")

    def _build_rest_client(self):
        """Build REST client from config using centralized factory."""
        return build_rest_client(self.config)

    def fetch_orderbook_prices(self, symbol: str) -> dict[str, Decimal]:
        """
        Fetch best bid/ask from order book.

        Returns:
            Dictionary with 'bid' and 'ask' prices
        """
        try:
            bid, ask = self.exchange_client.get_orderbook_top(symbol)
            return {"bid": bid, "ask": ask}
        except Exception as e:
            logger.warning(f"Failed to fetch prices for {symbol}: {e}")
            return {"bid": Decimal("0"), "ask": Decimal("0")}

    def fetch_pool_data(self, symbol: str) -> dict[str, Any]:
        """
        Fetch liquidity pool data.

        Returns:
            Dictionary with pool reserves and pricing info
        """
        try:
            pool_data = self.rest_client.get_liquidity_pool(symbol)

            # Debug logging to see what we actually got
            logger.debug(f"Pool data type for {symbol}: {type(pool_data).__name__}")
            logger.debug(f"Pool data content: {str(pool_data)[:200]}")

            # Ensure we got a valid dict response
            if not isinstance(pool_data, dict):
                logger.error(
                    f"Invalid pool data type for {symbol}: {type(pool_data).__name__}, content: {str(pool_data)[:100]}"
                )
                raise ValueError(
                    f"Expected dict, got {type(pool_data).__name__}: {str(pool_data)[:100]}"
                )

            # Parse reserves - handle None values
            reserve_a_raw = pool_data.get("reserve_a")
            reserve_b_raw = pool_data.get("reserve_b")
            last_price_raw = pool_data.get("last_price")

            # Convert to Decimal, handling None/invalid values
            try:
                reserve_a = (
                    Decimal(str(reserve_a_raw))
                    if reserve_a_raw is not None
                    else Decimal("0")
                )
            except (ValueError, TypeError):
                logger.debug(
                    f"Invalid reserve_a value: {reserve_a_raw} ({type(reserve_a_raw).__name__})"
                )
                reserve_a = Decimal("0")

            try:
                reserve_b = (
                    Decimal(str(reserve_b_raw))
                    if reserve_b_raw is not None
                    else Decimal("0")
                )
            except (ValueError, TypeError):
                logger.debug(
                    f"Invalid reserve_b value: {reserve_b_raw} ({type(reserve_b_raw).__name__})"
                )
                reserve_b = Decimal("0")

            try:
                last_price = (
                    Decimal(str(last_price_raw))
                    if last_price_raw is not None
                    else Decimal("0")
                )
            except (ValueError, TypeError):
                logger.debug(
                    f"Invalid last_price value: {last_price_raw} ({type(last_price_raw).__name__})"
                )
                last_price = Decimal("0")

            # If reserves not available, try to infer from ticker data
            if reserve_a == 0 or reserve_b == 0:
                logger.warning(
                    f"Pool {symbol} has no reserve data. "
                    "Will use spot price only (no slippage calculation)."
                )

            return {
                "reserve_a": reserve_a,
                "reserve_b": reserve_b,
                "token_a": pool_data.get("token_a", ""),
                "token_b": pool_data.get("token_b", ""),
                "last_price": last_price,
                "raw": pool_data,
            }
        except Exception as e:
            logger.warning(f"Failed to fetch pool data for {symbol}: {e}")
            return {
                "reserve_a": Decimal("0"),
                "reserve_b": Decimal("0"),
                "token_a": "",
                "token_b": "",
                "last_price": Decimal("0"),
                "raw": {},
            }

    def build_cycles(
        self,
        orderbook_prices: dict[str, dict[str, Decimal]],
        pool_data: dict[str, Any],
    ) -> list[ArbitrageCycle]:
        """
        Build all possible arbitrage cycles from current market data.

        For COSA/PIRATE pool with BTC and USDT pairs:
        - Cycle 1: USDT → COSA (buy) → PIRATE (pool swap) → USDT (sell)
        - Cycle 2: USDT → PIRATE (buy) → COSA (pool swap) → USDT (sell)
        - Cycle 3: BTC → COSA (buy) → PIRATE (pool swap) → BTC (sell)
        - Cycle 4: BTC → PIRATE (buy) → COSA (pool swap) → BTC (sell)
        """
        from strategies.hybrid_triangular_arb import (
            TradeSide,
            create_orderbook_leg,
            create_pool_swap_leg,
            evaluate_cycle,
        )
        from utils.amm_pricing import PoolReserves, get_swap_quote

        cycles = []

        # Extract pool tokens (underscore format)
        pool_tokens = self.pool_pair.split("_")
        if len(pool_tokens) != 2:
            logger.error(
                f"Invalid pool pair format: {self.pool_pair} (expected underscore format)"
            )
            return cycles

        token_a, token_b = pool_tokens

        # Calculate pool effective prices with slippage
        pool_reserves = None
        if pool_data["reserve_a"] > 0 and pool_data["reserve_b"] > 0:
            pool_reserves = PoolReserves(
                reserve_token_a=pool_data["reserve_a"],
                reserve_token_b=pool_data["reserve_b"],
                token_a_symbol=token_a,
                token_b_symbol=token_b,
            )

        # Build cycles for each base currency (USDT, BTC, etc.)
        for base in [self.base_currency]:
            # Build order book pair names (underscore format)
            token_a_pair = f"{token_a}_{base}"
            token_b_pair = f"{token_b}_{base}"

            # Check if we have order book data for both pairs
            if (
                token_a_pair not in orderbook_prices
                or token_b_pair not in orderbook_prices
            ):
                logger.warning(
                    f"Missing order book data for {token_a_pair} or {token_b_pair}"
                )
                continue

            token_a_prices = orderbook_prices[token_a_pair]
            token_b_prices = orderbook_prices[token_b_pair]

            # Cycle 1: BASE → Token A → Token B (pool) → BASE
            # Buy Token A, swap to Token B, sell Token B
            if token_a_prices["ask"] > 0 and token_b_prices["bid"] > 0:
                try:
                    # Calculate pool swap price with slippage
                    if pool_reserves:
                        # Estimate how much Token A we'll have after first leg
                        approx_token_a = self.trade_amount / token_a_prices["ask"]
                        swap_quote = get_swap_quote(
                            approx_token_a, pool_reserves, token_a, self.pool_fee
                        )
                        pool_effective_price = swap_quote.effective_price
                        slippage_pct = swap_quote.price_impact
                    else:
                        # Use spot price if no reserves
                        pool_effective_price = pool_data["last_price"]
                        slippage_pct = Decimal("0")

                    leg1 = create_orderbook_leg(
                        symbol=token_a_pair,
                        side=TradeSide.BUY,
                        price=Decimal("1")
                        / token_a_prices["ask"],  # Invert: get token per base
                        input_currency=base,
                        output_currency=token_a,
                        fee_rate=self.orderbook_fee,
                    )

                    leg2 = create_pool_swap_leg(
                        symbol=self.pool_pair,
                        side=TradeSide.SELL,  # Swap Token A for Token B
                        effective_price=pool_effective_price,
                        input_currency=token_a,
                        output_currency=token_b,
                        fee_rate=self.pool_fee,
                        slippage_pct=slippage_pct,
                    )

                    leg3 = create_orderbook_leg(
                        symbol=token_b_pair,
                        side=TradeSide.SELL,
                        price=token_b_prices["bid"],  # Get base per token
                        input_currency=token_b,
                        output_currency=base,
                        fee_rate=self.orderbook_fee,
                    )

                    cycle = evaluate_cycle(leg1, leg2, leg3, self.trade_amount)
                    cycles.append(cycle)
                except Exception as e:
                    logger.debug(f"Failed to build cycle 1: {e}")

            # Cycle 2: BASE → Token B → Token A (pool) → BASE
            # Buy Token B, swap to Token A, sell Token A
            if token_b_prices["ask"] > 0 and token_a_prices["bid"] > 0:
                try:
                    if pool_reserves:
                        approx_token_b = self.trade_amount / token_b_prices["ask"]
                        swap_quote = get_swap_quote(
                            approx_token_b, pool_reserves, token_b, self.pool_fee
                        )
                        pool_effective_price = swap_quote.effective_price
                        slippage_pct = swap_quote.price_impact
                    else:
                        pool_effective_price = Decimal("1") / pool_data["last_price"]
                        slippage_pct = Decimal("0")

                    leg1 = create_orderbook_leg(
                        symbol=token_b_pair,
                        side=TradeSide.BUY,
                        price=Decimal("1") / token_b_prices["ask"],
                        input_currency=base,
                        output_currency=token_b,
                        fee_rate=self.orderbook_fee,
                    )

                    leg2 = create_pool_swap_leg(
                        symbol=self.pool_pair,
                        side=TradeSide.BUY,  # Swap Token B for Token A
                        effective_price=pool_effective_price,
                        input_currency=token_b,
                        output_currency=token_a,
                        fee_rate=self.pool_fee,
                        slippage_pct=slippage_pct,
                    )

                    leg3 = create_orderbook_leg(
                        symbol=token_a_pair,
                        side=TradeSide.SELL,
                        price=token_a_prices["bid"],
                        input_currency=token_a,
                        output_currency=base,
                        fee_rate=self.orderbook_fee,
                    )

                    cycle = evaluate_cycle(leg1, leg2, leg3, self.trade_amount)
                    cycles.append(cycle)
                except Exception as e:
                    logger.debug(f"Failed to build cycle 2: {e}")

        return cycles

    def execute_cycle(self, cycle: ArbitrageCycle) -> bool:
        """
        Execute an arbitrage cycle.

        Returns:
            True if execution succeeded, False otherwise
        """
        from strategies.hybrid_triangular_arb import format_cycle_summary

        if self.mode == "monitor":
            logger.info("MONITOR MODE: Would execute cycle but skipping")
            return False

        if self.mode == "dry-run":
            logger.info("DRY RUN MODE: Simulating execution")
            logger.info(format_cycle_summary(cycle))
            return True

        # Live execution mode
        logger.info("Executing cycle:")
        logger.info(format_cycle_summary(cycle))

        try:
            # Execute leg 1
            success = self._execute_leg(cycle.leg1)
            if not success:
                logger.error("Leg 1 failed, aborting cycle")
                return False

            # Execute leg 2
            success = self._execute_leg(cycle.leg2)
            if not success:
                logger.error("Leg 2 failed, attempting to reverse leg 1")
                # TODO: Implement reversal logic
                return False

            # Execute leg 3
            success = self._execute_leg(cycle.leg3)
            if not success:
                logger.error("Leg 3 failed, attempting to reverse previous legs")
                # TODO: Implement reversal logic
                return False

            logger.info(f"Cycle executed successfully! Profit: {cycle.net_profit:.4f}")
            self.trades_executed += 1
            self.total_profit += cycle.net_profit
            if self.profit_store is not None:
                self.profit_store.record_profit(cycle.net_profit, self.base_currency)
            return True

        except Exception as e:
            logger.error(f"Cycle execution failed: {e}", exc_info=True)
            return False

    def _execute_leg(self, leg: TradeLeg) -> bool:
        """Execute a single leg of the cycle."""
        from strategies.hybrid_triangular_arb import LegType, TradeSide

        if leg.input_amount is None or leg.output_amount is None:
            logger.error("Leg missing amount information")
            return False

        # Check minimum notional for orderbook trades
        if leg.leg_type == LegType.ORDERBOOK:
            if leg.price is None or leg.price <= 0:
                logger.error(f"Leg {leg.symbol} missing price data")
                return False
            if leg.side == TradeSide.BUY:
                notional_value = leg.input_amount
            else:
                notional_value = leg.input_amount * leg.price
            if notional_value < self.min_notional_quote:
                logger.warning(
                    f"Leg {leg.symbol} below minimum notional: ${notional_value:.2f} < ${self.min_notional_quote:.2f}. Skipping."
                )
                return False

        try:
            if leg.leg_type == LegType.ORDERBOOK:
                if leg.price is None or leg.price <= 0:
                    logger.error(f"Leg {leg.symbol} missing price data")
                    return False
                if leg.side == TradeSide.BUY:
                    order_price = Decimal("1") / leg.price
                    quantity = leg.input_amount * leg.price
                else:
                    order_price = leg.price
                    quantity = leg.input_amount

                order_price = self._apply_aggressive_limit_price(
                    order_price, leg.side
                )

                if order_price <= 0 or quantity <= 0:
                    logger.error(f"Leg {leg.symbol} has invalid order values")
                    return False

                # Place aggressive limit order to emulate market execution.
                side = "buy" if leg.side == TradeSide.BUY else "sell"
                order_id = self.exchange_client.place_limit(
                    symbol=leg.symbol,
                    side=side,
                    price=order_price,
                    quantity=quantity,
                )
                logger.info(
                    "Order placed: %s %s %s @ %s",
                    leg.symbol,
                    side,
                    quantity,
                    order_price,
                )

                # TODO: Wait for fill with timeout
                # For now, assume immediate fill (risky!)

                return True

            elif leg.leg_type == LegType.POOL_SWAP:
                # Execute pool swap
                min_received = leg.output_amount * Decimal(
                    "0.99"
                )  # 1% slippage tolerance
                result = self.rest_client.execute_pool_swap(
                    symbol=leg.symbol,
                    side="buy" if leg.side == TradeSide.BUY else "sell",
                    amount=str(leg.input_amount),
                    min_received=str(min_received),
                )
                logger.info(f"Swap executed: {result.get('swap_id')}")
                return True

        except Exception as e:
            logger.error(f"Leg execution failed: {e}", exc_info=True)
            return False

        return False

    def _apply_aggressive_limit_price(
        self, price: Decimal, side: "TradeSide"
    ) -> Decimal:
        from strategies.hybrid_triangular_arb import TradeSide

        if self.orderbook_aggressive_limit_pct <= 0:
            return price
        if side == TradeSide.BUY:
            return price * (Decimal("1") + self.orderbook_aggressive_limit_pct)
        return price * (Decimal("1") - self.orderbook_aggressive_limit_pct)

    def run_cycle(self) -> None:
        """Run one iteration of the arbitrage detection cycle."""
        from strategies.hybrid_triangular_arb import (
            find_best_cycle,
            is_cycle_profitable,
        )

        try:
            # Fetch all market data
            logger.debug("Fetching market data...")
            orderbook_prices = {}
            for pair in self.orderbook_pairs:
                prices = self.fetch_orderbook_prices(pair)
                orderbook_prices[pair] = prices
                logger.debug(
                    f"{pair}: bid={prices['bid']:.8f}, ask={prices['ask']:.8f}"
                )

            pool_data = self.fetch_pool_data(self.pool_pair)
            logger.debug(
                f"{self.pool_pair} pool: "
                f"reserves=({pool_data['reserve_a']:.4f}, {pool_data['reserve_b']:.4f})"
            )

            # Build and evaluate cycles
            cycles = self.build_cycles(orderbook_prices, pool_data)
            self.cycles_evaluated += len(cycles)

            if not cycles:
                logger.debug("No cycles could be built from current market data")
                return

            # Find best cycle
            best_cycle = find_best_cycle(cycles)
            if best_cycle is None:
                return

            # Log all cycles
            for cycle in cycles:
                profit_indicator = (
                    "✓" if is_cycle_profitable(cycle, self.min_profit_pct) else "✗"
                )
                logger.debug(
                    f"{profit_indicator} {cycle.cycle_id}: "
                    f"{cycle.net_profit:+.4f} ({cycle.profit_pct:+.3f}%)"
                )

            # Check if profitable
            if is_cycle_profitable(best_cycle, self.min_profit_pct):
                self.opportunities_found += 1
                logger.info(
                    f"🎯 OPPORTUNITY #{self.opportunities_found}: "
                    f"{best_cycle.cycle_id} | "
                    f"Profit: {best_cycle.net_profit:.4f} ({best_cycle.profit_pct:.3f}%)"
                )

                # Execute if not in monitor mode
                if self.mode != "monitor":
                    self.execute_cycle(best_cycle)
            else:
                logger.info(
                    f"Best cycle: {best_cycle.cycle_id} | "
                    f"Profit: {best_cycle.net_profit:.4f} ({best_cycle.profit_pct:.3f}%) "
                    f"[Below threshold]"
                )

        except Exception as e:
            logger.error(f"Error in run cycle: {e}", exc_info=True)

    def run(self) -> None:
        """Run the bot continuously."""
        from utils.profit_store import execute_exit_liquidation

        logger.info("Starting HybridArbBot...")
        logger.info("Press Ctrl+C to stop")

        try:
            while True:
                start_time = time.time()
                self.run_cycle()
                if self.profit_store is not None:
                    self.profit_store.process()
                    if self.profit_store.should_trigger_exit():
                        if not self.exit_symbol:
                            logger.warning(
                                "Profit-store exit triggered but no exit symbol configured."
                            )
                        else:
                            handled = execute_exit_liquidation(
                                self.exchange_client,
                                self.profit_store,
                                self.exit_symbol,
                                self.mode,
                            )
                            if handled:
                                self.profit_store.mark_exit_handled()
                self._save_state()
                elapsed = time.time() - start_time

                # Log statistics periodically
                if self.cycles_evaluated % 100 == 0 and self.cycles_evaluated > 0:
                    logger.info(
                        f"Stats: {self.cycles_evaluated} cycles evaluated, "
                        f"{self.opportunities_found} opportunities, "
                        f"{self.trades_executed} executed, "
                        f"total profit: {self.total_profit:.4f}"
                    )

                # Sleep until next poll
                sleep_time = max(0, self.poll_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            logger.info("\nShutting down...")
            logger.info(
                f"Final stats: {self.cycles_evaluated} cycles evaluated, "
                f"{self.opportunities_found} opportunities found, "
                f"{self.trades_executed} trades executed, "
                f"total profit: {self.total_profit:.4f}"
            )
            self._save_state()

    def _save_state(self) -> None:
        payload = {
            "mode": self.mode,
            "cycles_evaluated": self.cycles_evaluated,
            "opportunities_found": self.opportunities_found,
            "trades_executed": self.trades_executed,
            "total_profit": str(self.total_profit),
            "updated_at": time.time(),
        }
        self.state_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )


def load_config(config_path: str) -> dict[str, Any]:
    """Load configuration from YAML file."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def main() -> None:
    """Main entry point."""
    from utils.logging_config import setup_logging

    parser = argparse.ArgumentParser(description="Hybrid triangular arbitrage bot")
    parser.add_argument("config", help="Path to configuration file")
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

    # Load config
    config = load_config(args.config)

    # Set mode
    if args.monitor_only:
        config["mode"] = "monitor"
    elif args.dry_run:
        config["mode"] = "dry-run"
    else:
        config["mode"] = config.get("mode", "live")

    # Run bot
    bot = HybridArbBot(config)
    bot.run()


if __name__ == "__main__":
    main()
