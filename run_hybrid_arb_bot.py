#!/usr/bin/env python3
"""
Hybrid triangular arbitrage bot for NonKYC exchange.

Monitors order books and liquidity pools to find profitable arbitrage opportunities
mixing limit orders and AMM swaps.

Usage:
    # Monitor mode (no execution, just logging)
    python run_hybrid_arb_bot.py config.yml --monitor-only

    # Live trading mode
    python run_hybrid_arb_bot.py config.yml

    # Dry run mode (simulated execution)
    python run_hybrid_arb_bot.py config.yml --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from nonkyc_client.auth import ApiCredentials
from nonkyc_client.models import OrderRequest
from nonkyc_client.rest import RestClient
from strategies.hybrid_triangular_arb import (
    ArbitrageCycle,
    LegType,
    TradeLeg,
    TradeSide,
    create_orderbook_leg,
    create_pool_swap_leg,
    evaluate_cycle,
    find_best_cycle,
    format_cycle_summary,
    is_cycle_profitable,
)
from utils.amm_pricing import (
    PoolReserves,
    get_swap_quote,
)
from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


class HybridArbBot:
    """Hybrid arbitrage bot mixing order books and liquidity pools."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize bot with configuration."""
        self.config = config
        self.rest_client = self._build_rest_client()
        self.mode = config.get("mode", "monitor")  # monitor, dry-run, or live
        self.min_profit_pct = Decimal(str(config.get("min_profit_pct", "0.5")))
        self.trade_amount = Decimal(str(config.get("trade_amount", "100")))
        self.poll_interval = config.get("poll_interval_seconds", 2.0)

        # Market configuration
        self.orderbook_pairs = config.get("orderbook_pairs", [])
        self.pool_pair = config.get("pool_pair", "")
        self.base_currency = config.get("base_currency", "USDT")

        # Fee configuration
        self.orderbook_fee = Decimal(str(config.get("orderbook_fee", "0.002")))
        self.pool_fee = Decimal(str(config.get("pool_fee", "0.003")))

        # Statistics
        self.cycles_evaluated = 0
        self.opportunities_found = 0
        self.trades_executed = 0
        self.total_profit = Decimal("0")

        logger.info(f"Initialized HybridArbBot in {self.mode.upper()} mode")
        logger.info(f"Monitoring {len(self.orderbook_pairs)} order book pairs + 1 pool")
        logger.info(f"Min profit threshold: {self.min_profit_pct}%")

    def _build_rest_client(self) -> RestClient:
        """Build REST client from config."""
        credentials = ApiCredentials(
            api_key=self.config["api_key"],
            api_secret=self.config["api_secret"],
        )
        base_url = self.config.get("base_url", "https://nonkyc.io")
        return RestClient(
            base_url=base_url,
            credentials=credentials,
            timeout=self.config.get("rest_timeout_sec", 30.0),
            max_retries=self.config.get("rest_retries", 3),
        )

    def fetch_orderbook_prices(self, symbol: str) -> dict[str, Decimal]:
        """
        Fetch best bid/ask from order book.

        Returns:
            Dictionary with 'bid' and 'ask' prices
        """
        try:
            ticker = self.rest_client.get_market_data(symbol)
            return {
                "bid": Decimal(ticker.bid) if ticker.bid else Decimal("0"),
                "ask": Decimal(ticker.ask) if ticker.ask else Decimal("0"),
            }
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
                raise ValueError(f"Expected dict, got {type(pool_data).__name__}: {str(pool_data)[:100]}")

            # Parse reserves
            reserve_a = Decimal(str(pool_data.get("reserve_a", "0")))
            reserve_b = Decimal(str(pool_data.get("reserve_b", "0")))

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
                "last_price": Decimal(str(pool_data.get("last_price", "0"))),
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
        cycles = []

        # Extract pool tokens (support both "/" and "_" separators)
        if "/" in self.pool_pair:
            pool_tokens = self.pool_pair.split("/")
        elif "_" in self.pool_pair:
            pool_tokens = self.pool_pair.split("_")
        else:
            logger.error(
                f"Invalid pool pair format: {self.pool_pair} (expected '/' or '_' separator)"
            )
            return cycles

        if len(pool_tokens) != 2:
            logger.error(f"Invalid pool pair format: {self.pool_pair}")
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
            # Check if we have order book pairs for both tokens
            # Try both formats: slash and underscore
            token_a_pair_slash = f"{token_a}/{base}"
            token_b_pair_slash = f"{token_b}/{base}"
            token_a_pair_underscore = f"{token_a}_{base}"
            token_b_pair_underscore = f"{token_b}_{base}"

            # Determine which format is actually in use
            if (
                token_a_pair_underscore in orderbook_prices
                and token_b_pair_underscore in orderbook_prices
            ):
                token_a_pair = token_a_pair_underscore
                token_b_pair = token_b_pair_underscore
            elif (
                token_a_pair_slash in orderbook_prices
                and token_b_pair_slash in orderbook_prices
            ):
                token_a_pair = token_a_pair_slash
                token_b_pair = token_b_pair_slash
            else:
                logger.warning(
                    f"Missing order book pairs for {token_a} and {token_b} with base {base}"
                )
                continue

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
            return True

        except Exception as e:
            logger.error(f"Cycle execution failed: {e}", exc_info=True)
            return False

    def _execute_leg(self, leg: TradeLeg) -> bool:
        """Execute a single leg of the cycle."""
        if leg.input_amount is None or leg.output_amount is None:
            logger.error("Leg missing amount information")
            return False

        try:
            if leg.leg_type == LegType.ORDERBOOK:
                # Place limit order
                order = OrderRequest(
                    symbol=leg.symbol,
                    side="buy" if leg.side == TradeSide.BUY else "sell",
                    order_type="limit",
                    quantity=str(leg.input_amount),
                    price=str(leg.price),
                )
                response = self.rest_client.place_order(order)
                logger.info(f"Order placed: {response.order_id}")

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

    def run_cycle(self) -> None:
        """Run one iteration of the arbitrage detection cycle."""
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
        logger.info("Starting HybridArbBot...")
        logger.info("Press Ctrl+C to stop")

        try:
            while True:
                start_time = time.time()
                self.run_cycle()
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


def load_config(config_path: str) -> dict[str, Any]:
    """Load configuration from YAML file."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def main() -> None:
    """Main entry point."""
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
