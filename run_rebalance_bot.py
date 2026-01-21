#!/usr/bin/env python3
"""
Portfolio rebalance bot for nonkyc.io exchange.

Monitors portfolio drift and automatically rebalances when the target ratio drifts
beyond the configured threshold.

Usage:
    # Monitor mode (no execution, just logging)
    python run_rebalance_bot.py config.yml --monitor-only

    # Live trading mode
    python run_rebalance_bot.py config.yml

    # Dry run mode (simulated execution)
    python run_rebalance_bot.py config.yml --dry-run
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

from nonkyc_client.models import OrderRequest
from nonkyc_client.rest import RestClient
from strategies.rebalance import calculate_rebalance_order
from utils.credentials import DEFAULT_SERVICE_NAME, load_api_credentials
from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


class RebalanceBot:
    """Portfolio rebalance bot."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize bot with configuration."""
        self.config = config
        self.rest_client = self._build_rest_client()
        self.mode = config.get("mode", "monitor")  # monitor, dry-run, or live

        # Market configuration
        self.trading_pair = config.get("trading_pair", "ETH_USDT")
        self.target_base_percent = Decimal(str(config.get("target_base_percent", "0.5")))
        self.rebalance_threshold_percent = Decimal(
            str(config.get("rebalance_threshold_percent", "0.02"))
        )

        # Order configuration
        self.order_type = config.get("rebalance_order_type", "limit")
        self.order_spread = Decimal(str(config.get("rebalance_order_spread", "0.002")))
        self.min_notional_quote = Decimal(str(config.get("min_notional_quote", "1.0")))  # $1 minimum

        # Poll configuration
        self.poll_interval = config.get("poll_interval_seconds", config.get("refresh_time", 60))

        # Price source
        self.price_source = config.get("price_source", "mid")  # mid, last, bid, ask

        # Statistics
        self.checks_performed = 0
        self.rebalances_executed = 0

        logger.info(f"Initialized RebalanceBot in {self.mode.upper()} mode")
        logger.info(f"Trading pair: {self.trading_pair}")
        logger.info(f"Target base ratio: {self.target_base_percent * 100}%")
        logger.info(f"Rebalance threshold: {self.rebalance_threshold_percent * 100}%")

    def _build_rest_client(self) -> RestClient:
        """Build REST client from config."""
        from nonkyc_client.auth import AuthSigner

        credentials = load_api_credentials(DEFAULT_SERVICE_NAME, self.config)
        base_url = self.config.get("base_url", "https://api.nonkyc.io/api/v2")

        # Create signer with proper configuration
        signer = AuthSigner(
            nonce_multiplier=self.config.get("nonce_multiplier", 1e3),
            sort_params=self.config.get("sort_params", False),
            sort_body=self.config.get("sort_body", False),
        )

        return RestClient(
            base_url=base_url,
            credentials=credentials,
            signer=signer,
            # Allow toggling signature scheme from YAML/env for debugging:
            # - true  => sign absolute URL (https://host/path?query)
            # - false => sign path only (/path?query)
            sign_absolute_url=self.config.get("sign_absolute_url"),
            timeout=self.config.get("rest_timeout_sec", 30.0),
            max_retries=self.config.get("rest_retries", 3),
            backoff_factor=self.config.get("rest_backoff_factor", 0.5),
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
                if balance.asset == base:
                    base_balance = Decimal(balance.available)
                elif balance.asset == quote:
                    quote_balance = Decimal(balance.available)

            return base_balance, quote_balance

        except Exception as e:
            logger.error(f"Failed to fetch balances: {e}", exc_info=True)
            return None

    def execute_rebalance(self, side: str, amount: Decimal, price: Decimal) -> bool:
        """Execute rebalance order.

        Args:
            side: Buy or sell
            amount: Amount to trade
            price: Limit price

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
            logger.info(f"MONITOR MODE: Would execute rebalance: {side} {amount} at {price} (notional: ${notional_value:.2f})")
            return False

        if self.mode == "dry-run":
            logger.info(f"DRY RUN MODE: Would {side} {amount} at {price} (notional: ${notional_value:.2f})")
            return True

        # Live execution
        try:
            order = OrderRequest(
                symbol=self.trading_pair,
                side=side.lower(),
                order_type=self.order_type,
                quantity=str(amount),
                price=str(price) if self.order_type == "limit" else None,
            )
            response = self.rest_client.place_order(order)
            logger.info(f"Rebalance order placed: {response.order_id}, Status: {response.status}")
            return True

        except Exception as e:
            logger.error(f"Failed to execute rebalance: {e}", exc_info=True)
            return False

    def run_cycle(self) -> None:
        """Run one iteration of the rebalance check."""
        try:
            self.checks_performed += 1

            # Fetch price
            logger.debug("Fetching market price...")
            price = self.get_price()
            if price is None:
                logger.warning("Failed to fetch price, skipping cycle")
                return

            logger.debug(f"Current price: {price}")

            # Fetch balances
            logger.debug("Fetching balances...")
            balances = self.get_balances()
            if balances is None:
                logger.warning("Failed to fetch balances, skipping cycle")
                return

            base_balance, quote_balance = balances
            logger.debug(f"Balances - Base: {base_balance}, Quote: {quote_balance}")

            # Calculate current ratio
            if base_balance == 0 and quote_balance == 0:
                logger.warning("Both balances are zero, cannot rebalance")
                return

            base_value = base_balance * price
            total_value = base_value + quote_balance
            current_ratio = base_value / total_value if total_value > 0 else Decimal("0")

            logger.info(
                f"Portfolio status: {current_ratio * 100:.2f}% base "
                f"(target: {self.target_base_percent * 100:.2f}%)"
            )

            # Check if rebalance is needed
            rebalance_order = calculate_rebalance_order(
                base_balance=base_balance,
                quote_balance=quote_balance,
                mid_price=price,
                target_base_ratio=self.target_base_percent,
                drift_threshold=self.rebalance_threshold_percent,
            )

            if rebalance_order is None:
                logger.info("✓ Portfolio within target range, no rebalance needed")
                return

            # Rebalance needed
            drift = abs(current_ratio - self.target_base_percent)
            logger.info(
                f"⚠️  Rebalance needed! Drift: {drift * 100:.2f}% "
                f"(threshold: {self.rebalance_threshold_percent * 100:.2f}%)"
            )
            logger.info(
                f"Action: {rebalance_order.side.upper()} {rebalance_order.amount} "
                f"at price {rebalance_order.price}"
            )

            # Calculate limit price with spread
            # Buy: place order BELOW market to get better price (maker)
            # Sell: place order ABOVE market to get better price (maker)
            if self.order_type == "limit":
                if rebalance_order.side == "buy":
                    limit_price = rebalance_order.price * (Decimal("1") - self.order_spread)
                else:
                    limit_price = rebalance_order.price * (Decimal("1") + self.order_spread)
            else:
                limit_price = rebalance_order.price

            # Execute rebalance
            success = self.execute_rebalance(
                rebalance_order.side,
                rebalance_order.amount,
                limit_price,
            )

            if success:
                self.rebalances_executed += 1
                logger.info(f"✅ Rebalance executed successfully (total: {self.rebalances_executed})")

        except Exception as e:
            logger.error(f"Error in rebalance cycle: {e}", exc_info=True)

    def run(self) -> None:
        """Run the bot continuously."""
        logger.info("Starting RebalanceBot...")
        logger.info("Press Ctrl+C to stop")

        try:
            while True:
                start_time = time.time()
                self.run_cycle()
                elapsed = time.time() - start_time

                # Log statistics periodically
                if self.checks_performed % 10 == 0:
                    logger.info(
                        f"Stats: {self.checks_performed} checks performed, "
                        f"{self.rebalances_executed} rebalances executed"
                    )

                # Sleep until next poll
                sleep_time = max(0, self.poll_interval - elapsed)
                if sleep_time > 0:
                    logger.debug(f"Sleeping for {sleep_time:.1f} seconds...")
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            logger.info("\nShutting down...")
            logger.info(
                f"Final stats: {self.checks_performed} checks performed, "
                f"{self.rebalances_executed} rebalances executed"
            )


def load_config(config_path: str) -> dict[str, Any]:
    """Load configuration from YAML file."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Portfolio rebalance bot")
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
    bot = RebalanceBot(config)
    bot.run()


if __name__ == "__main__":
    main()
