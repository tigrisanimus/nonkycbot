#!/usr/bin/env python3
"""
Infinity Grid bot for nonkyc.io exchange.

Maintains constant base asset value with no upper limit, profiting from price increases.
Optimal for trending bull markets.

Usage:
    # Monitor mode (no execution, just logging)
    python run_infinity_grid.py config.yml --monitor-only

    # Live trading mode
    python run_infinity_grid.py config.yml

    # Dry run mode (simulated execution)
    python run_infinity_grid.py config.yml --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from nonkyc_client.models import OrderRequest
from nonkyc_client.rest import RestClient
from strategies.infinity_grid import (
    InfinityGridState,
    calculate_infinity_grid_order,
    initialize_infinity_grid,
    update_infinity_grid_state,
)
from utils.credentials import DEFAULT_SERVICE_NAME, load_api_credentials
from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


class InfinityGridBot:
    """Infinity Grid trading bot."""

    def __init__(self, config: dict[str, Any], state_path: Path) -> None:
        """Initialize bot with configuration."""
        self.config = config
        self.state_path = state_path
        self.rest_client = self._build_rest_client()
        self.mode = config.get("mode", "monitor")  # monitor, dry-run, or live

        # Market configuration
        self.trading_pair = config.get("trading_pair", "BTC_USDT")
        self.step_pct = Decimal(str(config.get("step_pct", "0.01")))

        # Order configuration
        self.order_type = config.get("order_type", "limit")
        self.order_spread = Decimal(str(config.get("order_spread", "0.001")))  # 0.1% from mid
        self.min_notional_quote = Decimal(str(config.get("min_notional_quote", "1.0")))  # $1 minimum

        # Poll configuration
        self.poll_interval = config.get("poll_interval_seconds", 60)

        # Price source
        self.price_source = config.get("price_source", "mid")  # mid, last, bid, ask

        # State
        self.grid_state: InfinityGridState | None = None

        # Statistics
        self.checks_performed = 0
        self.rebalances_executed = 0

        logger.info(f"Initialized InfinityGridBot in {self.mode.upper()} mode")
        logger.info(f"Trading pair: {self.trading_pair}")
        logger.info(f"Grid step: {self.step_pct * 100}%")

    def _build_rest_client(self) -> RestClient:
        """Build REST client from config."""
        credentials = load_api_credentials(DEFAULT_SERVICE_NAME, self.config)
        base_url = self.config.get("base_url", "https://api.nonkyc.io")
        return RestClient(
            base_url=base_url,
            credentials=credentials,
            timeout=self.config.get("rest_timeout_sec", 30.0),
            max_retries=self.config.get("rest_retries", 3),
        )

    def get_price(self) -> Decimal | None:
        """Fetch current market price based on configured price source."""
        try:
            ticker = self.rest_client.get_market_data(self.trading_pair)

            if self.price_source == "mid":
                bid = Decimal(ticker.bid) if ticker.bid else None
                ask = Decimal(ticker.ask) if ticker.ask else None
                if bid and ask:
                    return (bid + ask) / Decimal("2")
            elif self.price_source == "last":
                if ticker.last_price:
                    return Decimal(ticker.last_price)
            elif self.price_source == "bid":
                if ticker.bid:
                    return Decimal(ticker.bid)
            elif self.price_source == "ask":
                if ticker.ask:
                    return Decimal(ticker.ask)

            # Fallback to last price
            if ticker.last_price:
                return Decimal(ticker.last_price)

            logger.warning(f"No price data available for {self.trading_pair}")
            return None

        except Exception as e:
            logger.error(f"Failed to fetch price for {self.trading_pair}: {e}", exc_info=True)
            return None

    def get_balances(self) -> tuple[Decimal, Decimal] | None:
        """Get base and quote balances.

        Returns:
            Tuple of (base_balance, quote_balance) or None if failed
        """
        try:
            # Extract base and quote from trading pair (underscore format)
            base, quote = self.trading_pair.split("_")

            balances = self.rest_client.get_balances()

            base_balance = Decimal("0")
            quote_balance = Decimal("0")

            for balance in balances:
                if balance.currency == base:
                    base_balance = Decimal(balance.available)
                elif balance.currency == quote:
                    quote_balance = Decimal(balance.available)

            return base_balance, quote_balance

        except Exception as e:
            logger.error(f"Failed to fetch balances: {e}", exc_info=True)
            return None

    def load_or_initialize_state(self) -> bool:
        """Load existing state or initialize new state.

        Returns:
            True if successful, False otherwise
        """
        # Try to load existing state
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    state_data = json.load(f)

                self.grid_state = InfinityGridState(
                    constant_value_quote=Decimal(state_data["constant_value_quote"]),
                    last_rebalance_price=Decimal(state_data["last_rebalance_price"]),
                    step_pct=Decimal(state_data["step_pct"]),
                    lower_limit=Decimal(state_data["lower_limit"]),
                    allocated_quote=Decimal(state_data["allocated_quote"]),
                    total_profit_quote=Decimal(state_data.get("total_profit_quote", "0")),
                )

                logger.info("Loaded existing infinity grid state")
                logger.info(f"  Constant value: {self.grid_state.constant_value_quote}")
                logger.info(f"  Last rebalance price: {self.grid_state.last_rebalance_price}")
                logger.info(f"  Total profit: {self.grid_state.total_profit_quote}")
                return True

            except Exception as e:
                logger.warning(f"Failed to load state from {self.state_path}: {e}")
                logger.info("Will initialize new state")

        # Initialize new state
        logger.info("Initializing new infinity grid state...")

        # Get current balances and price
        balances = self.get_balances()
        if balances is None:
            logger.error("Cannot initialize: failed to fetch balances")
            return False

        base_balance, quote_balance = balances
        if base_balance <= 0:
            logger.error(f"Cannot initialize: no base asset balance ({base_balance})")
            return False
        if quote_balance < 0:
            logger.error(f"Cannot initialize: invalid quote balance ({quote_balance})")
            return False

        current_price = self.get_price()
        if current_price is None:
            logger.error("Cannot initialize: failed to fetch price")
            return False

        # Initialize grid state (lower limit calculated automatically from quote balance)
        self.grid_state = initialize_infinity_grid(
            base_balance=base_balance,
            quote_balance=quote_balance,
            current_price=current_price,
            step_pct=self.step_pct,
        )

        logger.info(f"✓ Initialized infinity grid:")
        logger.info(f"  Entry price: {current_price}")
        logger.info(f"  Base balance: {base_balance}")
        logger.info(f"  Quote balance: {quote_balance}")
        logger.info(f"  Constant value: {self.grid_state.constant_value_quote}")
        logger.info(f"  Lower limit: {self.grid_state.lower_limit} (calculated from quote allocation)")
        logger.info(f"  Grid step: {self.step_pct * 100}%")

        # Save initial state
        self.save_state()

        return True

    def save_state(self) -> None:
        """Save grid state to disk."""
        if self.grid_state is None:
            return

        try:
            state_data = {
                "constant_value_quote": str(self.grid_state.constant_value_quote),
                "last_rebalance_price": str(self.grid_state.last_rebalance_price),
                "step_pct": str(self.grid_state.step_pct),
                "lower_limit": str(self.grid_state.lower_limit),
                "allocated_quote": str(self.grid_state.allocated_quote),
                "total_profit_quote": str(self.grid_state.total_profit_quote),
            }

            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_path, "w") as f:
                json.dump(state_data, f, indent=2)

        except Exception as e:
            logger.error(f"Failed to save state: {e}", exc_info=True)

    def execute_rebalance(self, side: str, amount: Decimal, price: Decimal) -> bool:
        """Execute rebalance order.

        Args:
            side: "buy" or "sell"
            amount: Amount of base asset to trade
            price: Execution price

        Returns:
            True if successful, False otherwise
        """
        # Check minimum notional value (dollar amount)
        notional_value = amount * price
        if notional_value < self.min_notional_quote:
            logger.warning(
                f"Order below minimum notional: ${notional_value:.2f} < ${self.min_notional_quote:.2f}. Skipping."
            )
            return False

        if self.mode == "monitor":
            logger.info(f"MONITOR MODE: Would {side} {amount} at {price} (notional: ${notional_value:.2f})")
            return False

        if self.mode == "dry-run":
            logger.info(f"DRY RUN: Simulating {side} {amount} at {price} (notional: ${notional_value:.2f})")
            return True

        # Live execution
        try:
            order = OrderRequest(
                symbol=self.trading_pair,
                side=side,
                order_type=self.order_type,
                quantity=str(amount),
                price=str(price) if self.order_type == "limit" else None,
            )

            response = self.rest_client.place_order(order)
            logger.info(f"✓ Order placed: {response.order_id}")
            logger.info(f"  Side: {side}")
            logger.info(f"  Amount: {amount}")
            logger.info(f"  Price: {price}")
            logger.info(f"  Status: {response.status}")

            return True

        except Exception as e:
            logger.error(f"Failed to execute order: {e}", exc_info=True)
            return False

    def run_cycle(self) -> None:
        """Run one iteration of the infinity grid check."""
        if self.grid_state is None:
            logger.error("Grid state not initialized")
            return

        self.checks_performed += 1

        # Get current price
        current_price = self.get_price()
        if current_price is None:
            logger.warning("Skipping cycle: no price data")
            return

        # Get current balances
        balances = self.get_balances()
        if balances is None:
            logger.warning("Skipping cycle: no balance data")
            return

        base_balance, quote_balance = balances

        # Log current state
        current_value = base_balance * current_price
        price_change_pct = (
            (current_price - self.grid_state.last_rebalance_price)
            / self.grid_state.last_rebalance_price
            * Decimal("100")
        )

        logger.info(f"\n{'='*60}")
        logger.info(f"Check #{self.checks_performed}")
        logger.info(f"{'='*60}")
        logger.info(f"Price: {current_price} (last rebalance: {self.grid_state.last_rebalance_price})")
        logger.info(f"Price change: {price_change_pct:+.2f}% from last rebalance")
        logger.info(f"Base balance: {base_balance}")
        logger.info(f"Current value: {current_value}")
        logger.info(f"Target value: {self.grid_state.constant_value_quote}")
        logger.info(f"Total profit: {self.grid_state.total_profit_quote}")

        # Calculate if rebalance is needed
        order = calculate_infinity_grid_order(
            base_balance=base_balance,
            quote_balance=quote_balance,
            current_price=current_price,
            grid_state=self.grid_state,
        )

        if order is None:
            logger.info("✓ No rebalance needed")
            return

        # Rebalance needed
        logger.info(f"\n🎯 REBALANCE TRIGGERED")
        logger.info(f"  Reason: {order.reason}")
        logger.info(f"  Action: {order.side.upper()} {order.amount}")
        logger.info(f"  Price: {order.price}")

        # Calculate execution price (apply spread for limit orders)
        # Buy: place order BELOW market to get better price (maker)
        # Sell: place order ABOVE market to get better price (maker)
        if self.order_type == "limit":
            if order.side == "buy":
                exec_price = order.price * (Decimal("1") - self.order_spread)
            else:  # sell
                exec_price = order.price * (Decimal("1") + self.order_spread)
        else:
            exec_price = order.price

        # Execute
        success = self.execute_rebalance(order.side, order.amount, exec_price)

        if success or self.mode == "dry-run":
            self.rebalances_executed += 1

            # Calculate profit (for sells, entire sale is profit)
            profit = Decimal("0")
            if order.side == "sell":
                profit = order.amount * exec_price

            # Update state
            self.grid_state = update_infinity_grid_state(
                current_state=self.grid_state,
                new_rebalance_price=current_price,
                profit_realized=profit,
            )

            logger.info(f"✓ State updated")
            logger.info(f"  Profit this cycle: {profit}")
            logger.info(f"  Total profit: {self.grid_state.total_profit_quote}")

            # Save state
            self.save_state()

    def run(self) -> None:
        """Run the bot continuously."""
        logger.info("Starting Infinity Grid Bot...")

        # Initialize or load state
        if not self.load_or_initialize_state():
            logger.error("Failed to initialize grid state. Exiting.")
            return

        logger.info("Press Ctrl+C to stop")

        try:
            while True:
                start_time = time.time()
                self.run_cycle()
                elapsed = time.time() - start_time

                # Log statistics periodically
                if self.checks_performed % 10 == 0:
                    logger.info(f"\n📊 Statistics:")
                    logger.info(f"  Checks performed: {self.checks_performed}")
                    logger.info(f"  Rebalances executed: {self.rebalances_executed}")
                    if self.grid_state:
                        logger.info(f"  Total profit: {self.grid_state.total_profit_quote}")

                # Sleep until next poll
                sleep_time = max(0, self.poll_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            logger.info("\n\nShutting down...")
            logger.info(f"Final statistics:")
            logger.info(f"  Checks performed: {self.checks_performed}")
            logger.info(f"  Rebalances executed: {self.rebalances_executed}")
            if self.grid_state:
                logger.info(f"  Total profit: {self.grid_state.total_profit_quote}")


def load_config(config_path: str) -> dict[str, Any]:
    """Load configuration from YAML file."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Infinity Grid trading bot")
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
    parser.add_argument(
        "--state-file",
        default="infinity_grid_state.json",
        help="Path to state file (default: infinity_grid_state.json)",
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
    state_path = Path(args.state_file)
    bot = InfinityGridBot(config, state_path)
    bot.run()


if __name__ == "__main__":
    main()
