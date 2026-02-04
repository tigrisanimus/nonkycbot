# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
# Run all tests
PYTHONPATH=src pytest tests/ -v

# Run a single test file
PYTHONPATH=src pytest tests/test_strategies.py -v

# Run a specific test
PYTHONPATH=src pytest tests/test_strategies.py::test_calculate_rebalance_order -v

# Validate all bots (checks auth setup, API methods, symbol format)
python scripts/validate_bots.py

# Format code
black src/ tests/
isort src/ tests/

# Type check
mypy src/
```

## Running Bots

```bash
# Standalone bot scripts (recommended)
python bots/run_rebalance_bot.py examples/rebalance_bot.yml

# Via CLI
PYTHONPATH=src python -m cli.main start --strategy rebalance --config config.yml
```

## Architecture

### Layer Organization

- **`src/nonkyc_client/`** - Exchange API client layer (REST, WebSocket, auth)
- **`src/engine/`** - Bot runners and order management (grid_runner, order_manager, state persistence)
- **`src/strategies/`** - Pure strategy calculations, exchange-agnostic (no API calls)
- **`src/utils/`** - Shared utilities (credentials, profit calculator, rate limiter)
- **`bots/`** - Standalone bot runner scripts that wire everything together
- **`src/cli/`** - Command-line interface

### Key Patterns

1. **REST Client Factory** (`src/engine/rest_client_factory.py`): All bots MUST use `build_exchange_client(config)` to create API clients. This ensures consistent auth across all bots.

2. **Strategy/Execution Separation**: Strategies in `src/strategies/` are pure calculation functions. Execution logic lives in `src/engine/` and `bots/`.

3. **State Persistence**: Bots persist state to JSON files (configurable via `state_path`). State includes open orders, grid levels, and cycle data.

4. **Config Loading**: Supports YAML, JSON, and TOML. Credentials can come from config, environment variables, or OS keychain (via `keyring`).

## NonKYC API Requirements

The exchange requires specific authentication settings:
- `sign_absolute_url: true` - Sign full URL (not just path)
- `nonce_multiplier: 10000` - 14-digit nonce

These defaults are set in `rest_client_factory.py`. If auth fails, use `python scripts/debug_auth.py` to diagnose.

## Trading Pair Format

Always use underscore format: `BTC_USDT`, not `BTC/USDT` or `BTC-USDT`.

## Adding a New Strategy

1. Create `src/strategies/your_strategy.py` with pure calculation functions
2. Add `describe()` function returning strategy description
3. Export in `src/strategies/__init__.py`
4. Create runner in `bots/run_your_strategy.py` using `build_exchange_client()`
5. Add example config in `examples/`
6. Add tests in `tests/`
