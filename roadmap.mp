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
- [x] Add signer configuration overrides to bot runner configs.
- [x] Add signer override reporting to test_connection helper script.
- [x] Ensure all bots/scripts expose signer configuration and absolute-URL signing toggles.
- [x] Default REST signing to full URLs with explicit opt-out coverage.
- [x] Add optional server-time synchronization for REST nonce signing.
- [x] Allow bot runners to override signer settings and disable signing via config.
- [x] Add minimum notional checks before bot order placement.
- [x] Improve REST error parsing for min-notional violations.
- [x] Note bots enforce minimum $1 notional rule before placing orders.
- [x] Add min-quantity helper with fee-aware rounding and apply to bots.
- [x] Add pricing helpers for notional math and use them in bot scripts.
- [x] Skip grid levels that do not clear fees before order placement.
- [x] Recompute triangular arb cycles with fee-adjusted min quantities before execution.

## Next
- [ ] Define API client interfaces and error handling.
- [ ] Implement persistent configuration and secrets management.
- [ ] Add strategy configuration schemas.

## Later
- [ ] Add exchange-specific adapters.
- [ ] Add backtesting harness.
