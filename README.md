# nonkyc bot

A standalone trading bot framework for nonkyc.io exchange. This repository provides a complete, independent project structure including exchange client integrations, trading engine components, strategy implementations, and a command-line interface.

**100% standalone** - No external trading frameworks required.

**Free and Open Source** - Licensed under Apache 2.0. Use it, modify it, redistribute it - no restrictions. See [License](#license) and [Acknowledgments](#acknowledgments) for details.

## Table of Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Usage](#usage)
- [Available Strategies](#available-strategies)
- [Asset Requirements](#asset-requirements)
- [Authentication Configuration](#authentication-configuration)
- [Testing Your Connection](#testing-your-connection)
- [Project Structure](#project-structure)
- [API Compatibility](#api-compatibility)
- [Development](#development)
- [Security](#security)
- [License](#license)
- [Acknowledgments](#acknowledgments)

## Features

✅ **Standalone Architecture** - No dependencies on external trading frameworks
✅ **HMAC SHA256 Authentication** - Secure API authentication compatible with NonKYC.io
✅ **REST API Client** - Production-ready synchronous client with retry logic
✅ **Multiple Strategies** - Grid trading, rebalancing, arbitrage, and more
✅ **Configuration Management** - Supports JSON, TOML, and YAML config files
✅ **State Persistence** - Automatic state saving and recovery
✅ **Multi-Instance Support** - Run multiple bots simultaneously with different configs
✅ **Risk Controls** - Built-in order management and balance tracking

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/tigrisanimus/nonkycbot.git
cd nonkycbot

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

**Dependencies**: Requires `pyyaml`, `keyring`, and `tomli` (for Python <3.11).

### 2. Get API Credentials

1. Create an account at [nonkyc.io](https://nonkyc.io)
2. Navigate to **API Settings** in your account
3. Generate a new API key pair
4. Save your `API Key` and `API Secret` securely

**Recommended: store credentials in your OS keychain**

```bash
# Store credentials securely (uses the OS keychain via keyring)
python scripts/nonkyc_store_credentials.py --api-key "$NONKYC_API_KEY" --api-secret "$NONKYC_API_SECRET"
```

This stores two entries under the `nonkyc-bot` service name with usernames `api_key` and `api_secret`.

Alternatively, you can store credentials directly with `keyring`:

```bash
python - <<'PY'
import keyring

keyring.set_password("nonkyc-bot", "api_key", "your_api_key")
keyring.set_password("nonkyc-bot", "api_secret", "your_api_secret")
PY
```

### 3. Configure Your Bot

Create a configuration file (see [examples/rebalance_bot.yml](examples/rebalance_bot.yml) for reference):

```yaml
# config.yml
exchange: "nonkyc"
trading_pair: "BTC_USDT"  # NOTE: Use UNDERSCORE format (not slash or hyphen)
api_key: "your_api_key_here"       # Optional if stored in keychain
api_secret: "your_api_secret_here" # Optional if stored in keychain

# Strategy-specific settings
target_base_percent: 0.5
rebalance_threshold_percent: 0.05
refresh_time: 60
```

**Security Note**: Never commit API credentials to git. Prefer the OS keychain, or use environment variables/secure config files with restricted permissions.

### 4. Test Your Connection

```bash
# Edit scripts/connection_check.py with your API credentials
nano scripts/connection_check.py

# Run the connection test
python scripts/connection_check.py
```

This will verify:
- ✓ API authentication is working
- ✓ You can fetch account balances
- ✓ Market data is accessible

### 5. Run Your First Bot

**Option A: Using standalone bot scripts (recommended for beginners)**
```bash
python bots/run_rebalance_bot.py examples/rebalance_bot.yml
```

**Option B: Using the CLI**
```bash
# From project root
PYTHONPATH=src python -m cli.main start --strategy rebalance --config config.yml --log-level INFO
```

The standalone scripts (`bots/run_*.py`) are simpler and include strategy-specific options.

## Configuration

### Configuration File Formats

The bot supports **JSON**, **TOML**, and **YAML** configuration files:

**YAML Example** (`config.yml`):
```yaml
exchange: "nonkyc"
trading_pair: "BTC_USDT"
api_key: "${NONKYC_API_KEY}"      # Can use environment variables
api_secret: "${NONKYC_API_SECRET}"
#
# If omitted, the bot will fall back to env vars or the OS keychain.
strategy_settings:
  target_base_percent: 0.5
  rebalance_threshold_percent: 0.05
```

**JSON Example** (`config.json`):
```json
{
  "exchange": "nonkyc",
  "trading_pair": "BTC_USDT",
  "api_key": "your_api_key",
  "api_secret": "your_api_secret"
}
```

**TOML Example** (`config.toml`):
```toml
exchange = "nonkyc"
trading_pair = "BTC_USDT"
api_key = "your_api_key"
api_secret = "your_api_secret"
```

### Multi-Instance Configuration

Run multiple bots with different strategies:

```bash
# Instance 1: Rebalance strategy
python -m cli.main start --strategy rebalance \
  --config config_rebalance.yml \
  --instance-id rebalance_btc

# Instance 2: Grid trading
python -m cli.main start --strategy infinity_grid \
  --config config_grid.yml \
  --instance-id grid_eth
```

Each instance maintains its own state file in `instances/{instance_id}/state.json`.

## Usage

### CLI Commands

```bash
# Show help
python -m cli.main --help

# Show version
python -m cli.main --version

# Start a strategy
python -m cli.main start --strategy STRATEGY_NAME --config CONFIG_FILE [OPTIONS]

# Options:
#   --strategy         Strategy to run (rebalance, infinity_grid, etc.)
#   --config          Path to configuration file
#   --config-dir      Directory containing config (default: current dir)
#   --instance-id     Unique identifier for this bot instance
#   --log-level       Logging level (DEBUG, INFO, WARNING, ERROR)
```

### Programmatic Usage

**REST Client Example**:

```python
from nonkyc_client.rest import RestClient
from nonkyc_client.auth import ApiCredentials
from nonkyc_client.models import OrderRequest

# Initialize client
creds = ApiCredentials(api_key="your_key", api_secret="your_secret")
client = RestClient(base_url="https://api.nonkyc.io/api/v2", credentials=creds)

# Get balances
balances = client.get_balances()
for balance in balances:
    print(f"{balance.asset}: {balance.available}")

# Place an order
order = OrderRequest(
    symbol="BTC_USDT",
    side="buy",
    order_type="limit",
    quantity="0.001",
    price="45000"
)
response = client.place_order(order)
print(f"Order ID: {response.order_id}, Status: {response.status}")

# Get market data
ticker = client.get_market_data("BTC_USDT")
print(f"Last price: {ticker.last_price}")
```

**Strategy Usage Example**:

```python
from decimal import Decimal
from strategies.rebalance import calculate_rebalance_order

# Calculate rebalancing order
order = calculate_rebalance_order(
    base_balance=Decimal("1.5"),      # BTC balance
    quote_balance=Decimal("60000"),    # USDT balance
    mid_price=Decimal("50000"),        # Current BTC price
    target_base_ratio=Decimal("0.5"),  # Target 50% in BTC
    drift_threshold=Decimal("0.05")    # Rebalance if drift > 5%
)

if order:
    print(f"Action: {order.side} {order.amount} at {order.price}")
else:
    print("No rebalancing needed")
```

## Available Strategies

### 1. Grid Trading
Fill-driven grid with ladder behavior that automatically refills orders as they execute.

**Use case**: Profit from price oscillations in ranging markets
**How it works**: Places buy orders below and sell orders above current price. When an order fills, automatically places a new order on the opposite side.
**Config**: `symbol`, `step_pct`, `n_buy_levels`, `n_sell_levels`, `base_order_size`, `total_fee_rate`
**Module**: `strategies.grid`
**Runner**: `bots/run_grid.py`
**Examples**: `examples/grid.yml`

**Profitability rule**: Spacing must exceed fees so that each buy/sell cycle clears costs.
- `step_pct` mode requires `step_pct > total_fee_rate`.
- `step_abs` mode checks the implied spacing around mid: `(sell_price / buy_price - 1) > total_fee_rate`.
- `total_fee_rate` is the round-trip fee rate (e.g., 0.002 for 0.2%).

### 2. Infinity Grid
Grid trading with NO upper limit - continuously extends sell ladder as price rises, perfect for bull markets.

**Use case**: Profit from sustained uptrends with unlimited upside potential
**How it works**:
- Places buy orders below price (with lower limit) AND sell orders above price (no upper limit)
- When sell fills → places NEW sell order above highest (extends ladder infinitely!)
- When buy fills → places sell order above to take profit
- Continuously profits from upward price movement without bound
**Config**: `symbol`, `step_pct`, `n_buy_levels`, `initial_sell_levels`, `base_order_size`, `total_fee_rate`
**Module**: `strategies.infinity_ladder_grid`
**Runner**: `bots/run_infinity_grid.py`
**Examples**: `examples/infinity_grid.yml`, `examples/infinity_grid_small_balance.yml`, `examples/infinity_grid_tight.yml`
**Documentation**: See [docs/guides/INFINITY_GRID_GUIDE.md](docs/guides/INFINITY_GRID_GUIDE.md) and [docs/guides/GRID_SPACING_GUIDE.md](docs/guides/GRID_SPACING_GUIDE.md) for complete setup guide

**Key features**:
- **No upper limit**: Sell ladder extends infinitely upward as price rises
- **Lower limit**: Buy orders have a floor based on available USDT
- **Grid strategy**: Places standing orders on the book (not reactive trades)
- **Best for bull markets**: Optimized for trending upward markets
- **Optimal spacing**: Use 0.5-2% spacing (see [docs/guides/GRID_SPACING_GUIDE.md](docs/guides/GRID_SPACING_GUIDE.md) for calculations)

### 3. Triangular Arbitrage
Identifies and executes arbitrage opportunities across three trading pairs.

**Use case**: Profit from price discrepancies (e.g., USDT → ETH → BTC → USDT)
**How it works**: Monitors three pairs for profitable cycles and executes market orders when opportunities arise
**Config**: `asset_a`, `asset_b`, `asset_c`, `pair_ab`, `pair_bc`, `pair_ac`, `trade_amount_a`, `min_profitability`
**Module**: `strategies.triangular_arb`
**Runner**: `bots/run_arb_bot.py`
**Examples**: `examples/triangular_arb.yml`

### 4. Hybrid Arbitrage
Combines order book trading with liquidity pool swaps for arbitrage.

**Use case**: Exploit price differences between order books and AMM pools
**How it works**: Monitors both order book pairs and liquidity pools, executing profitable cycles
**Config**: `orderbook_pairs`, `pool_pair`, `base_currency`, `trade_amount`, `min_profit_pct`
**Module**: `strategies.hybrid_triangular_arb`
**Runner**: `bots/run_hybrid_arb_bot.py`
**Examples**: `examples/hybrid_arb.yml`

### 5. Rebalance Strategy
Maintains a target ratio between base and quote assets.

**Use case**: Keep consistent portfolio allocation (e.g., 50% ETH, 50% USDT)
**How it works**: Monitors portfolio drift and places rebalancing trades when threshold is exceeded
**Config**: `target_base_percent`, `rebalance_threshold_percent`, `poll_interval_seconds`
**Module**: `strategies.rebalance`
**Runner**: `bots/run_rebalance_bot.py`
**Examples**: `examples/rebalance_bot.yml`

### 6. Adaptive Capped Martingale (Spot)
Fee-aware, spot-only mean reversion strategy that accumulates BTC with capped geometric adds.

**Use case**: Accumulate BTC during pullbacks with capped exposure and staged exits
**How it works**:
- Places a base buy at the best bid and tracks fills with fee-aware average entry
- Adds only when price drops by a fixed step and budget allows (capped sizing)
- Takes partial profit at TP1 and exits remaining position at TP2
- Uses a time stop to exit at breakeven after prolonged cycles
**Config**: `symbol`, `cycle_budget`, `base_order_pct`, `multiplier`, `max_adds`, `step_pct`, `tp1_pct`, `tp2_pct`, `fee_rate`
**Module**: `strategies.adaptive_capped_martingale`
**Runner**: `bots/run_adaptive_capped_martingale.py`
**Examples**: `examples/adaptive_capped_martingale_btc_usdt.yml`

See [examples/](examples/) directory for complete configuration examples with detailed usage instructions.

### Strategy Guides

Comprehensive guides are available for complex strategies:

- **[docs/guides/INFINITY_GRID_GUIDE.md](docs/guides/INFINITY_GRID_GUIDE.md)** - Complete setup guide for infinity grid including:
  - How infinity grid works (standing orders vs reactive trades)
  - Lower limit calculation and behavior
  - Order size calculation for your balance
  - Configuration examples for different balance sizes
  - Troubleshooting common issues

- **[docs/guides/GRID_SPACING_GUIDE.md](docs/guides/GRID_SPACING_GUIDE.md)** - Grid spacing optimization guide including:
  - Minimum profitable spacing calculations (0.42% minimum with 0.2% fees)
  - Recommended spacing for different balance sizes
  - Comparison of tight (0.5%), medium (1-2%), and wide (5%) grids
  - Profit examples for different market volatility
  - Rate limit considerations

These guides provide detailed calculations and examples to help you optimize your bot configuration.

## Asset Requirements

Before running any bot, you need to have the appropriate assets in your nonkyc.io account. Here's what you need for each strategy:

### Grid Trading
**Requires: BOTH base and quote assets in balanced amounts**

- **What you need**: Both sides of the trading pair (e.g., BTC + USDT for BTC_USDT)
- **Why**: Grid places buy orders below price (needs quote currency) AND sell orders above price (needs base currency)
- **Example**: For BTC_USDT grid with 10 levels @ 0.01 BTC per level:
  - Need: ~0.05 BTC (for 5 sell orders)
  - Need: ~$25,000 USDT (for 5 buy orders at $50k/BTC)
- **⚠️ Important**: If you only have BTC, you can only place sell orders. If you only have USDT, you can only place buy orders. You need both!

### Infinity Grid
**Requires: BOTH base and quote assets**

- **What you need**: Base asset (e.g., BTC) AND quote asset (e.g., USDT) for buying dips
- **Why**: Two-sided grid - sells BTC as price rises, buys BTC as price drops below entry
- **Example**: Start with 1 BTC @ $50k + $10k USDT
  - Bot maintains $50k constant value in BTC
  - As BTC price rises, bot sells BTC to maintain $50k worth (profits in USDT)
  - As BTC price drops below $50k, bot buys BTC using the $10k USDT allocation
  - Lower limit calculated from USDT: with $10k USDT and 1% steps, can support dips to ~$40k
- **Important**: More USDT allocated = lower the grid can extend = more dip-buying capacity

### Adaptive Capped Martingale
**Requires: quote asset for buys; base asset only after fills**

- **What you need**: USDT (or quote currency) for base and add buys
- **Why**: Strategy is spot-only and long-only; it accumulates BTC and sells portions for profit
- **Example**: For a $500 cycle budget, the base order starts at ~$7.50 with capped adds up to $50 per order

### Triangular Arbitrage
**Requires: Starting currency ONLY**

- **What you need**: The first asset in your cycle (typically USDT)
- **Why**: Bot executes complete cycle and returns to starting asset
- **Example**: USDT → ETH → BTC → USDT cycle
  - Only need: 100 USDT to start
  - Don't need: ETH or BTC (bought/sold during cycle)
  - End with: USDT + profit
- **Cycle completes in seconds**: No need to hold intermediate assets

### Hybrid Arbitrage
**Requires: Base currency ONLY**

- **What you need**: Base currency specified in config (typically USDT)
- **Why**: Similar to triangular arb - executes full cycle
- **Example**: Hybrid COSA/PIRATE arb with USDT base
  - Only need: 100 USDT
  - Don't need: COSA or PIRATE
  - Profit accumulates in USDT

### Rebalance
**Requires: BOTH base and quote assets near target ratio**

- **What you need**: Both assets in approximately your target allocation
- **Why**: Bot rebalances existing holdings, doesn't create positions from scratch
- **Example**: 50/50 ETH/USDT rebalance with $10k portfolio
  - Need: ~0.1 ETH (~$5k worth)
  - Need: ~$5k USDT
  - Should start close to 50/50 ratio
- **Starting ratio matters**: If you start 90/10, bot will immediately try to rebalance to 50/50

## Minimum Capital Guidelines

| Strategy | Minimum Recommended | Comfortable Start | Notes |
|----------|-------------------|-------------------|-------|
| Grid | $1,000 - $2,000 | $5,000+ | Need balanced inventory |
| Infinity Grid | $1,000 - $2,000 | $5,000+ | Two-sided grid, needs USDT for dips |
| Triangular Arb | $100 - $500 | $1,000+ | Can start small, test profitability |
| Hybrid Arb | $100 - $500 | $1,000+ | Similar to triangular |
| Rebalance | $500 - $1,000 | $2,000+ | Need both assets |

**Important considerations:**
- **Exchange minimums**: nonkyc.io typically requires ~$1 minimum per order (`min_notional_quote`)
- **Gas/fees**: Smaller amounts = fees eat into profits more
- **Slippage**: Larger orders may face more slippage on low-liquidity pairs
- **Start small**: Always test with minimum amounts in monitor/dry-run mode first!

## Authentication Configuration

All bots support flexible authentication configuration for compatibility with NonKYC and other exchanges.

### Required Settings

Add these to your configuration file for proper NonKYC authentication:

```yaml
# Authentication settings (REQUIRED for NonKYC)
sign_absolute_url: true         # Sign full URL (NonKYC requires this)
nonce_multiplier: 10000         # 14-digit nonce (1e4 or 10000)

# Optional: Debug authentication issues
# debug_auth: true              # Show detailed auth info (NEVER use in production!)
```

### How It Works

NonKYC uses **full URL signing** with a **14-digit nonce**:
- `sign_absolute_url: true` → signs `https://api.nonkyc.io/api/v2/balances`
- `sign_absolute_url: false` → signs `/balances` (path only - won't work with NonKYC)
- `nonce_multiplier: 10000` → generates 14-digit nonce (required by NonKYC)

### Testing Authentication

Use the included debug script to test all authentication variations:

```bash
# Edit scripts/debug_auth.py with your credentials
python scripts/debug_auth.py

# This will test:
# ✓ Path-only signing
# ✓ Full URL signing
# ✓ 13-digit nonce
# ✓ 14-digit nonce
# Shows which combination works!
```

### All Bots Support This

Every bot runner automatically supports these settings:
- `bots/run_grid.py`
- `bots/run_infinity_grid.py`
- `bots/run_arb_bot.py`
- `bots/run_hybrid_arb_bot.py`
- `bots/run_rebalance_bot.py`

Just add `sign_absolute_url` and `nonce_multiplier` to your config file and all bots will use them.

## Testing Your Connection

### Quick Test Script

The repository includes `scripts/connection_check.py` for manual API testing:

```bash
# 1. Edit the script with your credentials
nano scripts/connection_check.py

# 2. Update these lines:
API_KEY = "your_actual_api_key"
API_SECRET = "your_actual_api_secret"

# 3. Run the test
python scripts/connection_check.py
```

The test will:
- ✓ Verify HMAC authentication
- ✓ Fetch your account balances
- ✓ Retrieve market data (BTC_USDT)
- ✓ Display detailed error messages if something fails

### Troubleshooting 401 Unauthorized

If you see `HTTP error 401: Not Authorized` errors:

**Authentication Configuration** (Most Common Issue):
- **Check signing mode**: NonKYC requires full URL signing. Add to your config:
  ```yaml
  sign_absolute_url: true       # Sign full URL (required for NonKYC)
  nonce_multiplier: 10000       # Use 14-digit nonce (1e4 or 10000)
  ```
- **Debug authentication**: Use the provided debug script:
  ```bash
  python scripts/debug_auth.py
  ```
  This tests all signing variations and shows which one works.

**Other Common Issues**:
- **Confirm API key permissions**: ensure the key has trading enabled (not just read-only).
- **Check IP allowlists**: if the exchange restricts API keys by IP, verify your current egress IP is whitelisted. VPNs (including static IPs) can still change egress endpoints if the tunnel reconnects or the region changes.
- **Validate credentials**: re-copy the API key/secret and confirm there are no extra spaces or hidden characters.
- **Verify system time**: the signature uses a millisecond nonce, so clock skew can cause auth failures.
- **Compare private vs. public calls**: if balances succeed but order placement fails with 401, the key likely lacks trading permission for private endpoints or the IP allowlist is scoped to trade actions.
- **Regenerate credentials**: if the key has full access and the IP is correct, generate a fresh API key/secret to rule out a stale or revoked credential.

### Running Unit Tests

```bash
# Install pytest (for development)
pip install pytest

# Run all tests
PYTHONPATH=src pytest tests/ -v

# Run specific test file
PYTHONPATH=src pytest tests/test_strategies.py -v
```

### Validating Bot Code (Prevent Regressions)

The repository includes a validation script that checks all bots for common issues:

```bash
# Run validation on all bots and strategies
python scripts/validate_bots.py
```

This automatically checks for:
- ✓ Correct authentication setup (sign_absolute_url, nonce_multiplier)
- ✓ Correct API method names (get_order not get_order_status)
- ✓ Symbol format support (underscore format: BTC_USDT)
- ✓ Profit validation in grid strategies
- ✓ No deprecated imports

**Run this before committing changes** to ensure no regressions are introduced.

## Project Structure

```
nonkycbot/
├── src/
│   ├── nonkyc_client/          # Exchange API client
│   │   ├── auth.py             # HMAC SHA256 authentication
│   │   ├── rest.py             # REST API client
│   │   ├── async_rest.py       # Async REST API client
│   │   ├── ws.py               # WebSocket client
│   │   └── models.py           # Data models
│   ├── engine/                 # Trading engine
│   │   ├── grid_runner.py      # Grid bot runner
│   │   ├── order_manager.py    # Order lifecycle management
│   │   ├── balances.py         # Balance tracking
│   │   ├── state.py            # State persistence
│   │   └── risk.py             # Risk controls
│   ├── strategies/             # Trading strategies
│   │   ├── grid.py             # Ladder grid trading
│   │   ├── adaptive_capped_martingale.py # Spot-only martingale strategy
│   │   ├── infinity_ladder_grid.py # Infinity grid (no upper limit)
│   │   ├── triangular_arb.py   # Triangular arbitrage
│   │   ├── hybrid_triangular_arb.py # Hybrid arbitrage
│   │   └── rebalance.py        # Portfolio rebalancing
│   ├── utils/                  # Utility modules
│   │   ├── credentials.py      # Credential management
│   │   ├── profit_calculator.py # Profit validation utilities
│   │   └── logging_config.py   # Logging configuration
│   └── cli/                    # Command-line interface
│       ├── main.py             # CLI entry point
│       └── config.py           # Configuration loader
├── examples/                   # Example configurations
│   ├── adaptive_capped_martingale_btc_usdt.yml # Adaptive martingale example
│   ├── infinity_grid.yml       # Infinity grid example (general)
│   ├── infinity_grid_small_balance.yml # Small balance config
│   ├── infinity_grid_tight.yml # Tight spacing (0.5%) config
│   ├── grid.yml                # Standard grid example
│   ├── hybrid_arb.yml          # Hybrid arbitrage example
│   ├── rebalance_bot.yml       # Rebalance strategy config
│   └── triangular_arb.yml      # Triangular arbitrage example
├── tests/                      # Unit tests
│   └── test_strategies.py      # Strategy tests
├── bots/                      # Bot runner scripts
│   ├── run_grid.py            # Grid bot runner script
│   ├── run_adaptive_capped_martingale.py # Adaptive martingale runner script
│   ├── run_infinity_grid.py   # Infinity grid bot runner script
│   ├── run_arb_bot.py         # Arbitrage bot runner script
│   ├── run_hybrid_arb_bot.py  # Hybrid arbitrage runner script
│   └── run_rebalance_bot.py   # Rebalance bot runner script
├── scripts/                   # Utility and validation tools
│   ├── connection_check.py    # Manual API test script
│   ├── debug_auth.py          # Authentication debugging tool
│   ├── validate_bots.py       # Bot code validation (prevent regressions)
│   └── check_grid_balances.py # Grid balance diagnostics tool
├── docs/                      # Documentation
│   ├── guides/                # How-to guides
│   │   ├── INFINITY_GRID_GUIDE.md # Complete infinity grid setup guide
│   │   └── GRID_SPACING_GUIDE.md  # Grid spacing optimization guide
│   └── audits/                # Compatibility & audit docs
│       └── COMPATIBILITY_AUDIT.md # API compatibility documentation
├── state/                     # Bot state files (runtime)
├── requirements.txt            # Python dependencies
├── pyproject.toml             # Build configuration
└── README.md                  # This file
```

## API Compatibility

This bot is designed for **NonKYC.io** exchange. See [docs/audits/COMPATIBILITY_AUDIT.md](docs/audits/COMPATIBILITY_AUDIT.md) for detailed analysis.

### Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| Authentication | ✅ Compatible | HMAC SHA256 correctly implemented |
| REST Client | ✅ Production-ready | Synchronous, with retry logic |
| Async REST Client | ✅ Available | aiohttp-based client with retry handling |
| REST Endpoints | ✅ Compatible | All standard endpoints supported |
| WebSocket Payloads | ✅ Compatible | Correct message formats |
| WebSocket Connection | ✅ Implemented | Reconnect, login, and handlers |
| Data Models | ✅ Complete | All models implemented |
| Strategies | ✅ Exchange-agnostic | Works with any exchange |

### Production Recommendations

**For REST-only trading** (current implementation):
- ✅ Ready to use now
- Authentication and order placement work
- Suitable for slower strategies (rebalancing, daily grid updates)

**For async REST trading** (scalable execution):
- ✅ Async client available in `src/nonkyc_client/async_rest.py`
- Use `aiohttp` to avoid blocking event loops
- Recommended for concurrent strategies

**For WebSocket streaming** (implemented):
- Requires: `pip install websockets aiohttp`
- WebSocket client in `src/nonkyc_client/ws.py` supports login, subscriptions, and reconnects
- Recommended for high-frequency strategies

See [docs/audits/COMPATIBILITY_AUDIT.md](docs/audits/COMPATIBILITY_AUDIT.md) for full details and implementation guidance.

## Development

### Setting Up Development Environment

```bash
# Clone and install
git clone https://github.com/tigrisanimus/nonkycbot.git
cd nonkycbot
python -m venv .venv
source .venv/bin/activate

# Install dependencies + dev tools
pip install -r requirements.txt
pip install pytest black isort mypy

# Run tests
PYTHONPATH=src pytest tests/ -v

# Format code
black src/ tests/
isort src/ tests/

# Type checking
mypy src/
```

### Adding a New Strategy

1. Create strategy file in `src/strategies/your_strategy.py`
2. Implement calculation functions
3. Add `describe()` function
4. Export in `src/strategies/__init__.py`
5. Add tests in `tests/test_strategies.py`
6. Create example config in `examples/`

**Example skeleton**:

```python
# src/strategies/your_strategy.py
from decimal import Decimal

def calculate_signal(price: Decimal, threshold: Decimal) -> str:
    """Calculate trading signal."""
    # Your logic here
    return "buy" if price < threshold else "sell"

def describe() -> str:
    return "Your strategy description"
```

### Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Security

⚠️ **Important Security Practices**:

- **Never commit API credentials** to version control
- Use environment variables or encrypted config files
- Set restrictive file permissions on config files: `chmod 600 config.yml`
- Use API keys with minimal required permissions
- Consider IP whitelist restrictions on your API keys
- Monitor your account for unusual activity
- Test with small amounts first

## License

Copyright 2026 Robert Clarke

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

See the [LICENSE](LICENSE) file for the full license text.

## Acknowledgments

This project was inspired by the [NonKYC fork of Hummingbot](https://github.com/tigrisanimus/hummingbot-nonkyc), an open-source algorithmic trading bot. While nonkyc bot is a standalone implementation with its own architecture, the NonKYC Hummingbot fork provided valuable inspiration for trading strategies and exchange integration patterns.

**Development**: This software was developed with the assistance of AI-powered coding tools:
- ChatGPT Codex (OpenAI)
- Claude Code (Anthropic)

See the [NOTICE](NOTICE) file for complete attribution information and third-party licenses.

## Support

- **Issues**: [GitHub Issues](https://github.com/tigrisanimus/nonkycbot/issues)
- **Documentation**: See [docs/audits/COMPATIBILITY_AUDIT.md](docs/audits/COMPATIBILITY_AUDIT.md)
- **NonKYC Exchange**: [https://nonkyc.io](https://nonkyc.io)

## Disclaimer

This software is for educational and research purposes. Trading cryptocurrencies carries risk. Always test thoroughly with small amounts before deploying to production. The authors are not responsible for any financial losses incurred through use of this software.
