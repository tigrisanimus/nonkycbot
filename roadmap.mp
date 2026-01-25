# nonkyc bot Roadmap

## Now
- [x] Initialize repository scaffold with core packages, CLI, and tests.
- [x] Add standard grid strategy placeholder.
- [x] Implement infinity grid helper module with deterministic refresh logic.
- [x] Implement rebalance helper module for target ratio adjustments.
- [x] Implement triangular arbitrage helper module for cycle scanning.
- [x] Implement profit reinvest helper module for reserve allocation.
- [x] Add CLI start command with strategy config parsing and multi-instance support.
- [x] Add deterministic REST/WS, order manager, and strategy tests.
- [x] Document 401 Unauthorized troubleshooting and API auth guidance.
- [x] Clarify 401 guidance for private endpoint permission checks.
- [x] Add remediation step for regenerating API credentials when 401 persists.
- [x] Thread userProvidedId/strictValidate order payload support through bots and tests.
- [x] Pass optional userProvidedId/strictValidate through triangular arbitrage bot orders.
- [x] Expose signed JSON payloads in debug auth output for REST signing checks.
- [x] Use RestRequest for cancel-all orders in all bot runners.
- [x] Align cancel-order payload with NonKYC docs and support userProvidedId.
- [x] Use documented limit field for order book subscriptions.
- [x] Re-enable balances subscription for account updates in WS client.
- [x] Align REST signing defaults with NonKYC nonce precision and payload ordering.
- [x] Align NonKYC nonce multiplier defaults with Hummingbot reference signing.
- [x] Honor absolute URL signing configuration in REST client.
- [x] Standardize cancel-all orders handling with response validation and symbol formatting.
- [x] Auto-refresh bot orders at most every 30 minutes.
- [x] Add missing resolve_quantity_rounding import for MMX grid runner.
- [x] Verify resolve_quantity_rounding import/reference in MMX grid runner.
- [x] Restore known-good REST signer defaults and add createorder signature coverage.
- [x] Assert createorder signing uses the exact JSON request payload.
- [x] Stop grid cycles on cancel-all auth failures to avoid cascading order errors.
- [x] Default cancel-all symbol format to dash and log resolved cancel symbols.
- [x] Retry cancel-all with alternate symbol formats when required input is missing.
- [x] Allow cancel-all requests without a symbol and verify request body handling in tests.
- [x] Align cancel-all REST/bot schema with slash symbols and side-aware payloads.
- [x] Treat cancel-side "all" as omit-side for cancel-all payloads.
- [x] Retry cancel-all across all symbol formats before giving up.
- [x] Retry cancel-all without a symbol when required input errors persist.
- [x] Add ExchangeClient interface and NonKYC REST adapter.
- [x] Implement fill-driven ladder grid strategy with add-only reconciliation.
- [x] Add v1 cancel-all signing support and ladder grid tests.
- [x] Attempt v1 cancel-all in MMX grid before v2 fallback when canceling orders.
- [x] Normalize ladder grid configs to accept legacy MMX grid fields and add startup log.
- [x] Refresh ladder grid balances before seeding and halt cycles on insufficient funds errors.
- [x] Skip ladder grid updates on transient order fetch errors.
- [x] Support ladder REST timeout/retry config and test transient REST retry behavior.
- [x] Retry REST and async REST calls on network timeouts.
- [x] Retry REST calls on remote disconnects with coverage.
- [x] Add ladder grid startup rebalance with market/limit fallback and tests.
- [x] Halt ladder seeding on startup rebalance failures and surface manual guidance.
- [x] Validate ladder grid spacing against total fee rate and document configuration.
- [x] Add ladder grid fee-rate spacing validation coverage for profitable vs. unprofitable steps.
- [x] Add ladder grid fetch backoff for transient order status timeouts.
- [x] Update the triangular arbitrage default triangle to USDT/ETH/BTC and refresh config docs.
- [x] Remove manual arbitrage prompt in arb runner and add execution-path test coverage.
- [x] Guard arbitrage price parsing against invalid ticker values with test coverage.
- [x] Enforce market-only triangular arbitrage execution, fixed fee rate, and remove cancel-all usage.
- [x] Remove residual external framework references from docs and roadmap.

- [x] Implement WebSocket streaming client with reconnect, login, and handlers.
- [x] Add async REST client for scalable trading workflows.
- [x] Expand ticker parsing to handle alternate last-price fields.
- [x] Fallback to bid/ask mid-price when ticker last price is absent.
- [x] Add lastPrice and bid/ask mid fallback parsing for arbitrage tickers.
- [x] Align hybrid arbitrage example/API base URL with v2 REST endpoints.
- [x] Implement keychain-backed credential loading and storage helpers.
- [x] Normalize infinity ladder grid order status handling for capitalized API values.
- [x] Sync infinity ladder startup state with exchange open orders.

## Next
- [ ] Define API client interfaces and error handling.
- [ ] Add strategy configuration schemas.

## Later
- [ ] Add exchange-specific adapters.
- [ ] Add backtesting harness.
