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

## Next
- [ ] Define API client interfaces and error handling.
- [ ] Implement persistent configuration and secrets management.
- [ ] Add strategy configuration schemas.

## Later
- [ ] Add exchange-specific adapters.
- [ ] Add backtesting harness.
