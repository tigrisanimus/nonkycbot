# NonKYC Bot Roadmap

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
- [x] Align REST signing defaults with NonKYC/Hummingbot nonce precision and payload ordering.
- [x] Honor absolute URL signing configuration in REST client.
- [x] Standardize cancel-all orders handling with response validation and symbol formatting.
- [x] Auto-refresh bot orders at most every 30 minutes.
- [x] Add missing resolve_quantity_rounding import for MMX grid runner.
- [x] Verify resolve_quantity_rounding import/reference in MMX grid runner.

## Next
- [ ] Define API client interfaces and error handling.
- [ ] Implement persistent configuration and secrets management.
- [ ] Add strategy configuration schemas.

## Later
- [ ] Add exchange-specific adapters.
- [ ] Add backtesting harness.
