# nonkyc bot Roadmap

## Current Status

The nonkyc bot is **feature-complete** for production trading. All core strategies, API integrations, and infrastructure are implemented and tested.

## Planned Improvements

### Next
- [ ] Define API client interfaces and error handling
- [ ] Add strategy configuration schemas

### Later
- [ ] Add exchange-specific adapters
- [ ] Add backtesting harness

---

## Completed Features

### Core Infrastructure
- Repository scaffold with CLI, packages, and tests
- Multi-instance support with state persistence
- REST and async REST clients with retry/timeout handling
- WebSocket streaming with reconnect and login handlers
- Rate limiting (sync and async) with token-bucket implementation

### Authentication & Security
- HMAC SHA256 signing with configurable nonce precision
- Keychain-backed credential storage (OS keychain, env vars, config fallback)
- Debug auth mode for troubleshooting
- Log sanitization for sensitive data

### Trading Strategies
- **Grid Trading**: Standard grid with ladder behavior
- **Infinity Grid**: No upper limit, extends sell ladder as price rises
- **Infinity Grid**: Continue buy-back placements even when sell-side funds are briefly insufficient
- **Triangular Arbitrage**: USDT/ETH/BTC cycle scanning with market execution
- **Hybrid Arbitrage**: Order book + AMM pool swaps
- **Portfolio Rebalance**: Multi-asset drift-based rebalancing
- **Market Maker**: Fee-aware spread capture with inventory skew
- **Adaptive Capped Martingale**: Progressive spot accumulation with capped risk

### Order Management
- Cancel-all with symbol format fallbacks (v1/v2 API)
- Order validation (profitability, min notional)
- Fill-driven order refills
- Startup rebalance with market/limit fallback

### Exchange Client
- ExchangeClient interface with NonKYC REST adapter
- Order book data (ticker, depth, top-of-book)
- Balance fetching with pending adjustment tracking
- Order creation, cancellation, and status polling

### Profit & Risk
- Profit store with net profit tracking
- Exit triggers for partial liquidation
- Fee-aware order sizing
- Grid spacing validation against fee rates

### Documentation & Testing
- Comprehensive config reference and example YAMLs
- Strategy guides (infinity grid, hybrid arb, troubleshooting)
- Security and compatibility audits
- 100+ tests with CI (Python 3.10-3.12, Linux/macOS)
