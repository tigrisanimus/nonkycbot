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
python nonkyc_store_credentials.py --api-key "$NONKYC_API_KEY" --api-secret "$NONKYC_API_SECRET"
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
# Edit test_connection.py with your API credentials
nano test_connection.py

# Run the connection test
python test_connection.py
```

This will verify:
- ✓ API authentication is working
- ✓ You can fetch account balances
- ✓ Market data is accessible

### 5. Run Your First Bot

**Option A: Using standalone bot scripts (recommended for beginners)**
```bash
python run_rebalance_bot.py examples/rebalance_bot.yml
```

**Option B: Using the CLI**
```bash
# From project root
PYTHONPATH=src python -m cli.main start --strategy rebalance --config config.yml --log-level INFO
```

The standalone scripts (`run_*.py`) are simpler and include strategy-specific options.

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
client = RestClient(base_url="https://api.nonkyc.io", credentials=creds)

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

**Use case**: Profit from price oscillations in ranging or trending markets
**How it works**: Places buy orders below and sell orders above current price. When an order fills, automatically places a new order on the opposite side.
**Config**: `symbol`, `step_pct`, `n_buy_levels`, `n_sell_levels`, `base_order_size`, `total_fee_rate`
**Module**: `strategies.grid`
**Runner**: `run_grid.py`
**Examples**: `examples/grid_cosa_pirate.yml`, `examples/infinity_grid.yml`

**Profitability rule**: Spacing must exceed fees so that each buy/sell cycle clears costs.
- `step_pct` mode requires `step_pct > total_fee_rate`.
- `step_abs` mode checks the implied spacing around mid: `(sell_price / buy_price - 1) > total_fee_rate`.
- `total_fee_rate` is the round-trip fee rate (e.g., 0.002 for 0.2%).

**Grid variants**:
- **Standard Grid**: Balanced grid for range-bound markets (see `grid_cosa_pirate.yml`)
- **Infinity Grid**: Tighter spreads with fewer levels for trending markets (see `infinity_grid.yml`)

### 2. Triangular Arbitrage
Identifies and executes arbitrage opportunities across three trading pairs.

**Use case**: Profit from price discrepancies (e.g., USDT → ETH → BTC → USDT)
**How it works**: Monitors three pairs for profitable cycles and executes market orders when opportunities arise
**Config**: `asset_a`, `asset_b`, `asset_c`, `pair_ab`, `pair_bc`, `pair_ac`, `trade_amount_a`, `min_profitability`
**Module**: `strategies.triangular_arb`
**Runner**: `run_arb_bot.py`
**Examples**: `examples/arb_usdt_eth_btc.yml`, `examples/nonkyc_triangular_arbitrage.yml`

### 3. Hybrid Arbitrage
Combines order book trading with liquidity pool swaps for arbitrage.

**Use case**: Exploit price differences between order books and AMM pools
**How it works**: Monitors both order book pairs and liquidity pools, executing profitable cycles
**Config**: `orderbook_pairs`, `pool_pair`, `base_currency`, `trade_amount`, `min_profit_pct`
**Module**: `strategies.hybrid_triangular_arb`
**Runner**: `run_hybrid_arb_bot.py`
**Examples**: `examples/hybrid_arb_cosa_pirate.yml`

### 4. Rebalance Strategy
Maintains a target ratio between base and quote assets.

**Use case**: Keep consistent portfolio allocation (e.g., 50% ETH, 50% USDT)
**How it works**: Monitors portfolio drift and places rebalancing trades when threshold is exceeded
**Config**: `target_base_percent`, `rebalance_threshold_percent`, `poll_interval_seconds`
**Module**: `strategies.rebalance`
**Runner**: `run_rebalance_bot.py`
**Examples**: `examples/rebalance_bot.yml`

See [examples/](examples/) directory for complete configuration examples with detailed usage instructions.

## Testing Your Connection

### Quick Test Script

The repository includes `test_connection.py` for manual API testing:

```bash
# 1. Edit the script with your credentials
nano test_connection.py

# 2. Update these lines:
API_KEY = "your_actual_api_key"
API_SECRET = "your_actual_api_secret"

# 3. Run the test
python test_connection.py
```

The test will:
- ✓ Verify HMAC authentication
- ✓ Fetch your account balances
- ✓ Retrieve market data (BTC_USDT)
- ✓ Display detailed error messages if something fails

### Troubleshooting 401 Unauthorized

If you see `HTTP error 401: Not Authorized` when placing orders:

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
│   │   ├── grid.py             # Grid trading with ladder behavior
│   │   ├── infinity_grid.py    # Grid utilities
│   │   ├── triangular_arb.py   # Triangular arbitrage
│   │   ├── hybrid_triangular_arb.py # Hybrid arbitrage
│   │   └── rebalance.py        # Portfolio rebalancing
│   └── cli/                    # Command-line interface
│       ├── main.py             # CLI entry point
│       └── config.py           # Configuration loader
├── examples/                   # Example configurations
│   ├── grid_cosa_pirate.yml    # Standard grid example
│   ├── infinity_grid.yml       # Infinity grid example
│   ├── arb_usdt_eth_btc.yml    # Triangular arbitrage example
│   ├── hybrid_arb_cosa_pirate.yml # Hybrid arbitrage example
│   └── rebalance_bot.yml       # Rebalance strategy config
├── tests/                      # Unit tests
│   └── test_strategies.py      # Strategy tests
├── run_grid.py                # Grid bot runner script
├── run_arb_bot.py             # Arbitrage bot runner script
├── run_hybrid_arb_bot.py      # Hybrid arbitrage runner script
├── run_rebalance_bot.py       # Rebalance bot runner script
├── test_connection.py          # Manual API test script
├── requirements.txt            # Python dependencies
├── pyproject.toml             # Build configuration
└── README.md                  # This file
```

## API Compatibility

This bot is designed for **NonKYC.io** exchange. See [COMPATIBILITY_AUDIT.md](COMPATIBILITY_AUDIT.md) for detailed analysis.

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

See [COMPATIBILITY_AUDIT.md](COMPATIBILITY_AUDIT.md) for full details and implementation guidance.

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
- **Documentation**: See [COMPATIBILITY_AUDIT.md](COMPATIBILITY_AUDIT.md)
- **NonKYC Exchange**: [https://nonkyc.io](https://nonkyc.io)

## Disclaimer

This software is for educational and research purposes. Trading cryptocurrencies carries risk. Always test thoroughly with small amounts before deploying to production. The authors are not responsible for any financial losses incurred through use of this software.
